import os
import imagej
from typing import Optional
from config.imagej_config import FIJI_JAVA_HOME
import scyjava

_ij_instance: Optional["imagej.ImageJ"] = None


# The BIOP Cellpose wrapper (ch.epfl.biop.wrappers) segments by spawning
# `bash -c "conda activate <env> && python -m cellpose ..."` via ProcessBuilder.
# Groovy runs in-process in this JVM (ij.py.run_script), so that bash inherits
# THIS process's environment. A bare non-login `bash -c` cannot run
# `conda activate` ("Run 'conda init' before 'conda activate'"); pointing
# BASH_ENV at conda.sh makes the conda shell function available so activation
# works. Harmless for other code paths (only `bash -c` sources it).
_CONDA_PROFILE = "/opt/conda/etc/profile.d/conda.sh"
if os.path.exists(_CONDA_PROFILE):
    os.environ.setdefault("BASH_ENV", _CONDA_PROFILE)

# Heap for this JVM. Configurable because the batch-execution subprocess starts a
# SECOND Fiji in the same container: two JVMs at the 6g default would exceed the
# container's memory limit, so the worker asks for a smaller heap via this env var.
def _available_memory_gb() -> Optional[int]:
    """Memory this process may actually use, in GiB — the cgroup cap if capped,
    otherwise host RAM.

    A fixed default is right for docker-compose (which sets an 8 GB cap) and
    silently wrong under Apptainer/HPC, which applies no such cap: a run there
    had 188-250 GB available but still got a 6 GB heap, and a 4-channel 8x8
    mosaic fusion died with OutOfMemoryError that nothing surfaced.
    """
    for path, unlimited in (
        ("/sys/fs/cgroup/memory.max", {"max"}),                       # cgroup v2
        ("/sys/fs/cgroup/memory/memory.limit_in_bytes", set()),       # cgroup v1
    ):
        try:
            with open(path) as fh:
                raw = fh.read().strip()
            if raw in unlimited:
                break
            value = int(raw)
            # v1 reports a sentinel near 2^63 when uncapped; treat >1 PiB as no cap.
            if value < (1 << 50):
                return max(1, value // (1 << 30))
            break
        except (OSError, ValueError):
            continue
    try:
        with open("/proc/meminfo") as fh:
            for line in fh:
                if line.startswith("MemTotal:"):
                    return max(1, int(line.split()[1]) // (1 << 20))
    except (OSError, ValueError, IndexError):
        pass
    return None


def _default_heap_gb() -> int:
    """Half of what is available, but never below the historical default on a
    machine that can afford it — so docker-compose's 8 GB cap still yields the
    6 g it always did, while an uncapped 188 GB node gets a heap that matches."""
    limit = _available_memory_gb()
    if limit is None:
        return 6
    half = max(1, limit // 2)
    return max(6, half) if limit >= 8 else max(2, half)


_JVM_HEAP = os.environ.get("IMAGENTJ_JVM_HEAP") or f"{_default_heap_gb()}g"
scyjava.config.add_options(f"-Xmx{_JVM_HEAP}")
print(f"[imagej_context] JVM heap -Xmx{_JVM_HEAP} "
      f"(detected {_available_memory_gb()} GiB available; "
      f"set IMAGENTJ_JVM_HEAP to override)")
# Local Fiji installation is complete — no network calls needed at JVM startup.
# Without this, scyjava tries to download Maven from archive.apache.org if mvn
# is not on PATH, which fails in restricted/flaky network environments.
scyjava.config.set_java_constraints(fetch='never')

def get_ij():
    global _ij_instance
    if _ij_instance is None:
        _ij_instance = imagej.init(FIJI_JAVA_HOME, mode='interactive')
    return _ij_instance


# ── Bio-Formats: never build the importer dialog ─────────────────────────────
# `IJ.open()` / `IJ.openImage()` dispatch unknown formats through
# HandleExtraFileTypes -> LociImporter -> Importer.showDialogs(), which is the
# *prompting* path: it constructs a modal Swing dialog. Under Xvfb (and in any
# unattended run) nobody can answer it, and the look-and-feel cannot supply UI
# delegates, so dialog construction throws
#   java.lang.Error: no ComponentUI class for: javax.swing.JSeparator
# The import process then retries and throws again. Observed in a benchmark run
# on a 460 MB OME-TIFF: 35 occurrences, the agent never escaped the retry loop,
# and the task burned its full 7200 s budget doing nothing.
#
# Opening through the Bio-Formats API with windowless=true skips ImporterPrompter
# entirely. NOTE: setting the `bioformats.windowless` IJ preference does NOT work
# — verified against bio-formats_plugins 8.5.0, `ImporterOptions.isWindowless()`
# still reports False afterwards. The programmatic setter is the only switch.
_BIOFORMATS_EXTS = (
    ".lif", ".czi", ".nd2", ".lsm", ".oib", ".oif", ".ims", ".vsi", ".scn",
    ".svs", ".ndpi", ".dv", ".zvi", ".ipl", ".seq", ".stk", ".flex", ".mvd2",
    ".cif", ".xdce", ".sld", ".nrrd", ".mrc",
)


def needs_bioformats(path: str) -> bool:
    """True when opening `path` with IJ.open would go down the prompting path.

    `.ome.tif` matters most and is easy to miss: the suffix is plain `.tif`, so an
    extension check alone lets it through to the dialog.
    """
    name = str(path).lower()
    return name.endswith((".ome.tif", ".ome.tiff", ".ome.zarr")) or name.endswith(_BIOFORMATS_EXTS)


def open_image_windowless(path: str, show: bool = False):
    """Open an image through Bio-Formats with the importer dialog disabled.

    Returns a list of ImagePlus (possibly empty), or None if Bio-Formats is not
    available — callers should then fall back to IJ.open.
    """
    from scyjava import jimport
    try:
        ImporterOptions = jimport("loci.plugins.in.ImporterOptions")
        BF = jimport("loci.plugins.BF")
    except Exception:
        return None

    opts = ImporterOptions()
    opts.setWindowless(True)   # the actual switch — see note above
    opts.setId(str(path))
    imps = list(BF.openImagePlus(opts) or [])
    if show:
        for imp in imps:
            imp.show()
    return imps
