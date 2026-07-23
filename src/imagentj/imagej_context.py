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
scyjava.config.add_options(f"-Xmx{os.environ.get('IMAGENTJ_JVM_HEAP', '6g')}")
# Local Fiji installation is complete — no network calls needed at JVM startup.
# Without this, scyjava tries to download Maven from archive.apache.org if mvn
# is not on PATH, which fails in restricted/flaky network environments.
scyjava.config.set_java_constraints(fetch='never')

def get_ij():
    global _ij_instance
    if _ij_instance is None:
        _ij_instance = imagej.init(FIJI_JAVA_HOME, mode='interactive')
    return _ij_instance
