FROM continuumio/miniconda3:latest AS base-cpu
ENV DEBIAN_FRONTEND=noninteractive
FROM base-cpu AS cpu

# ── Core system dependencies (rarely change) ─────────────────────────────────
# Split from fonts to preserve cache when adding new fonts
RUN apt-get update && apt-get install -y --no-install-recommends \
    # Virtual display & VNC
    xvfb x11vnc fluxbox \
    # noVNC (websocket proxy)
    novnc websockify \
    # X11 / Qt xcb dependencies
    libxcb-xinerama0 libxcb-cursor0 libxcb-keysyms1 libxcb-render-util0 \
    libxcb-icccm4 libxcb-image0 libxcb-shape0 libxkbcommon-x11-0 \
    libxcb-randr0 libxcb-xfixes0 libxcb-sync1 libxcb-glx0 \
    libegl1 libgl1 libglib2.0-0 libfontconfig1 libdbus-1-3 \
    x11-xserver-utils\
    # Java AWT / Fiji display
    libxtst6 libxi6 libxrender1 libxt6 libxext6 libx11-6 \
    # OpenGL
    libopengl0 libglx0 \
    # Utilities
    wget unzip procps curl \
    && rm -rf /var/lib/apt/lists/*

# ── Install Fiji ──────────────────────────────────────────────────────────────
RUN wget -q https://downloads.imagej.net/fiji/latest/fiji-latest-linux64-jdk.zip -O /tmp/fiji.zip \
    && unzip -q /tmp/fiji.zip -d /opt \
    && rm /tmp/fiji.zip \
    # Rename to .app to match standard ENV variables if you have them
    && mv /opt/Fiji /opt/Fiji.app \
    # The actual binary name is fiji-linux-x64
    && chmod +x /opt/Fiji.app/fiji-linux-x64

# ── Install plugins via update sites ─────────────────────────────────────────
# Order matters: TensorFlow → CSBDeep → StarDist (dependency chain).
# MorphoLibJ (IJPB-plugins) is a dep of TrackMate-MorphoLibJ.
RUN printf '%s\n' \
    'IJPB-plugins https://sites.imagej.net/IJPB-plugins/' \
    'TensorFlow https://sites.imagej.net/TensorFlow/' \
    'CSBDeep https://sites.imagej.net/CSBDeep/' \
    'StarDist https://sites.imagej.net/StarDist/' \
    'TrackMate-StarDist https://sites.imagej.net/TrackMate-StarDist/' \
    'TrackMate-MorphoLibJ https://sites.imagej.net/TrackMate-MorphoLibJ/' \
    'TrackMate-Cellpose https://sites.imagej.net/TrackMate-Cellpose/' \
    > /tmp/sites.txt \
    && while read -r name url; do \
        DISPLAY="" /opt/Fiji.app/fiji-linux-x64 --headless --update add-update-site "$name" "$url" || true; \
    done < /tmp/sites.txt \
    && rm /tmp/sites.txt \
    && /opt/Fiji.app/fiji-linux-x64 --headless --update update

# ── Apply staged updates into jars/ and plugins/ ─────────────────────────────
# --update update only STAGES files into update/ — it does not apply them.
# We copy here so all plugins are baked into the image with no runtime network dep.
RUN cp -a /opt/Fiji.app/update/plugins/. /opt/Fiji.app/plugins/ 2>/dev/null || true \
    && cp -a /opt/Fiji.app/update/jars/.    /opt/Fiji.app/jars/    2>/dev/null || true \
    && cp -a /opt/Fiji.app/update/macros/.  /opt/Fiji.app/macros/  2>/dev/null || true \
    && cp -a /opt/Fiji.app/update/scripts/. /opt/Fiji.app/scripts/ 2>/dev/null || true \
    && cp -a /opt/Fiji.app/update/lib/.     /opt/Fiji.app/lib/     2>/dev/null || true \
    && rm -rf /opt/Fiji.app/update/*

# ── Direct Maven download for CSBDeep and StarDist JARs ──────────────────────
# The Fiji update sites for these two plugins have stale file links (all 404s).
# URLs verified from maven.scijava.org (2026-04).
#   csbdeep-0.6.0.jar         → jars/   (SciJava @Plugin library, not a menu plugin)
#   StarDist_-0.3.0-scijava.jar → plugins/
#   Clipper-6.4.2.jar         → jars/   (required runtime dep of StarDist)
RUN python3 - <<'PYEOF'
import urllib.request, ssl, sys
from pathlib import Path

plugins_dir = Path('/opt/Fiji.app/plugins')
jars_dir    = Path('/opt/Fiji.app/jars')

ctx = ssl.create_default_context()
ctx.check_hostname = False
ctx.verify_mode    = ssl.CERT_NONE

MAVEN = 'https://maven.scijava.org/content/repositories'

DOWNLOADS = [
    (jars_dir,    'csbdeep-0.6.0.jar',
     f'{MAVEN}/releases/de/csbdresden/csbdeep/0.6.0/csbdeep-0.6.0.jar'),
    (plugins_dir, 'StarDist_-0.3.0-scijava.jar',
     f'{MAVEN}/releases/de/csbdresden/StarDist_/0.3.0-scijava/StarDist_-0.3.0-scijava.jar'),
    (jars_dir,    'Clipper-6.4.2.jar',
     f'{MAVEN}/public/de/lighti/Clipper/6.4.2/Clipper-6.4.2.jar'),
]

all_ok = True
for dest_dir, fname, url in DOWNLOADS:
    dest = dest_dir / fname
    if dest.exists():
        print(f'[maven-dl] already present: {fname}')
        continue
    print(f'[maven-dl] GET {url}')
    try:
        req  = urllib.request.Request(url, headers={'User-Agent': 'Fiji-Docker/2.0'})
        data = urllib.request.urlopen(req, timeout=120, context=ctx).read()
        dest.write_bytes(data)
        print(f'[maven-dl] saved {fname} ({len(data):,} bytes)')
    except Exception as e:
        print(f'[maven-dl] ERROR: {fname}: {e}', file=sys.stderr)
        all_ok = False

sys.exit(0 if all_ok else 1)
PYEOF

# Verify JARs are present (CSBDeep lives in jars/, not plugins/)
RUN ls /opt/Fiji.app/jars/csbdeep-*.jar \
    && ls /opt/Fiji.app/plugins/StarDist_*.jar \
    && echo "OK: csbdeep and StarDist_ JARs verified" \
    || { echo "ERROR: CSBDeep or StarDist JARs missing — Maven download failed"; exit 1; }

ENV FIJI_PATH=/opt/Fiji.app

# ── Conda environment (heaviest layer - keep stable) ─────────────────────────
COPY environment.yml /tmp/environment.yml
RUN conda env create -f /tmp/environment.yml \
    && conda clean -afy \
    && rm /tmp/environment.yml

# Put the conda env on PATH so it's active by default
ENV PATH=/opt/conda/envs/local_imagent_J/bin:$PATH
ENV CONDA_DEFAULT_ENV=local_imagent_J

# ── Conda env: cellpose  (PyTorch + Cellpose, served by TrackMate-Cellpose) ───
RUN /opt/conda/bin/conda create -n cellpose python=3.10 -y \
    && /opt/conda/envs/cellpose/bin/pip install --no-cache-dir \
        torch torchvision --index-url https://download.pytorch.org/whl/cu124 \
    && /opt/conda/envs/cellpose/bin/pip install --no-cache-dir 'cellpose[gui]==3.1.1.2' \
    && /opt/conda/envs/cellpose/bin/cellpose --version \
    && /opt/conda/bin/conda clean -afy

# ── Conda env: stardist  (TensorFlow + CSBDeep + StarDist inference) ─────────
# Separate env so TF version is independent of the main Python env.
# Python 3.11 + TF 2.15 is the most stable combo for CSBDeep
# (uses tf.compat.v1 graph APIs, which became fragile in TF 2.17+).
# numpy<2 required — NumPy 2.0 breaks csbdeep's C-extension assumptions.
# tensorflow-cpu used here (CPU image); swap for tensorflow==2.15.* on GPU.
RUN /opt/conda/bin/conda create -n stardist python=3.11 -y \
    && /opt/conda/envs/stardist/bin/pip install --no-cache-dir \
        "tensorflow-cpu==2.15.*" \
        "csbdeep>=0.7.4" \
        "stardist>=0.9" \
        "numpy<2" \
    && /opt/conda/bin/conda clean -afy

# Verify the StarDist Python stack imports correctly
RUN /opt/conda/envs/stardist/bin/python -c \
    "import stardist, csbdeep, tensorflow as tf; print('[OK] StarDist Python stack: tf', tf.__version__)"

# TrackMate-StarDist looks for a Python executable via this env var
ENV SCIJAVA_PYTHON=/opt/conda/envs/stardist/bin/python

# ── TrackMate micromamba shim ─────────────────────────────────────────────────
# TrackMate-Cellpose v8 hardcodes /usr/local/opt/micromamba/bin/micromamba and
# always calls it with '-n base'. The shim intercepts this, strips the env argument,
# and forces '-n cellpose' so the correct environment is always used.
COPY micromamba_shim.sh /usr/local/opt/micromamba/bin/micromamba
RUN chmod +x /usr/local/opt/micromamba/bin/micromamba

# ── Fonts (separate layer - changes here won't invalidate conda cache) ───────
RUN apt-get update && apt-get install -y --no-install-recommends \
    fonts-dejavu-core fonts-liberation fonts-noto-color-emoji \
    && rm -rf /var/lib/apt/lists/* \
    && fc-cache -f -v

# ── Non-root user ─────────────────────────────────────────────────────────────
RUN groupadd -g 1000 imagentj \
    && useradd -u 1000 -g imagentj -m -d /home/imagentj -s /bin/bash imagentj
    
# ── Application code ─────────────────────────────────────────────────────────
WORKDIR /app
COPY . /app

# Use keys_template.py as keys.py (keys.py is .dockerignored since it has real secrets)
RUN cp /app/src/config/keys_template.py /app/src/config/keys.py

# Ensure the app user owns everything it needs to write to (including qdrant_data directory)
# ── TrackMate v8 conda configuration ─────────────────────────────────────────
# TrackMate v8 uses a unified conda framework for all Python-based detectors.
# Each plugin activates its own named env:
#   TrackMate-Cellpose  → env 'cellpose'
#   TrackMate-StarDist  → env 'stardist'
# The micromamba shim (below) provides a fallback for plugins that still
# hardcode the micromamba path.
RUN mkdir -p /home/imagentj/.imagej \
    && printf '[trackmate]\ncondaRootPrefix=/opt/conda\ncondaExecutable=/opt/conda/bin/conda\n' \
        > /home/imagentj/.imagej/trackmate-conda.prefs \
    && chown -R imagentj:imagentj /home/imagentj/.imagej

RUN mkdir -p /app/qdrant_data /home/imagentj/.cellpose \
    && chown -R imagentj:imagentj /app /home/imagentj /app/qdrant_data \
    && chown -R imagentj:imagentj /opt/Fiji.app

# ── Environment defaults ─────────────────────────────────────────────────────
ENV DISPLAY=:1
ENV QT_QPA_PLATFORM=xcb
ENV JAVA_HOME=/opt/conda/envs/local_imagent_J
ENV HOME=/home/imagentj

# ── Entrypoint ────────────────────────────────────────────────────────────────
COPY docker-entrypoint.sh /docker-entrypoint.sh
RUN chmod +x /docker-entrypoint.sh

EXPOSE 6080

USER imagentj

ENTRYPOINT ["/docker-entrypoint.sh"]
CMD ["python", "gui_runner.py"]