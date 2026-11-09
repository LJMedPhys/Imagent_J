# syntax=docker/dockerfile:1
# =============================================================================
# Agentic-J image — slim build.
#
# What keeps it small:
#   * No conda. Python comes from uv (python-build-standalone interpreters) and
#     each env is a plain uv venv installed from a pinned lock file
#     (docker/requirements/*.txt). Envs live conda-style in /opt/uv/envs/<name>
#     so Fiji's conda callers keep working through micromamba_shim.sh.
#   * Only what the agent uses: Fiji + plugins, the main app env, a Cellpose 3
#     env (model cyto3 only) and the napari viewer env. No StarDist/CSBDeep/
#     TensorFlow, DeepImageJ, micro_sam, Cellpose 4/SAM, Omnipose, BrainGlobe or
#     docling (which dragged torch+transformers into the main env).
#   * Multi-stage: Fiji, the Python envs, noVNC and the app source are each
#     built in their own stage and only the finished trees are COPY'd into the
#     final stage, so compilers, git, download archives and deleted files never
#     reach the image.
#   * Java is the JDK that ships inside Fiji (no separate OpenJDK).
#
# Stages: uv → base → fiji / pyenvs / novnc / appsrc / seedcache → cpu (final)
# The final stage is named `cpu` for docker-compose's `target: cpu`; the GPU
# variant is the same stage built with USE_GPU=true (docker-compose.gpu.yml).
# =============================================================================

# The pinned Qt wheels for Linux ARM64 require glibc 2.39 or newer.
ARG DEBIAN_RELEASE=trixie
ARG UV_VERSION=0.11

FROM ghcr.io/astral-sh/uv:${UV_VERSION} AS uv

# ── base: runtime system packages shared by every stage ──────────────────────
FROM debian:${DEBIAN_RELEASE}-slim AS base
ENV DEBIAN_FRONTEND=noninteractive \
    LANG=C.UTF-8 \
    LC_ALL=C.UTF-8
RUN apt-get update && apt-get install -y --no-install-recommends \
    # Virtual display & VNC (noVNC itself comes from the novnc stage)
    xvfb x11vnc fluxbox x11-xserver-utils \
    # X11 / Qt xcb dependencies (PySide6 GUI, napari's PyQt6)
    libxcb-xinerama0 libxcb-cursor0 libxcb-keysyms1 libxcb-render-util0 \
    libxcb-icccm4 libxcb-image0 libxcb-shape0 libxkbcommon-x11-0 \
    libxcb-randr0 libxcb-xfixes0 libxcb-sync1 libxcb-glx0 \
    libegl1 libgl1 libglib2.0-0 libfontconfig1 libdbus-1-3 \
    # Java AWT / Fiji display
    libxtst6 libxi6 libxrender1 libxt6 libxext6 libx11-6 \
    # OpenGL — libgl1-mesa-dri provides the llvmpipe software renderer that
    # napari/vispy need under headless Xvfb (no GPU); paired with
    # LIBGL_ALWAYS_SOFTWARE=1 below.
    libopengl0 libglx0 libgl1-mesa-dri \
    # OpenCL CPU backend (required by CLIJ2 / BioVoxxel 3D Box without a GPU)
    # pocl-opencl-icd    — POCL software OpenCL device (CPU execution)
    # ocl-icd-libopencl1 — ICD loader runtime (libOpenCL.so.1)
    # ocl-icd-opencl-dev — the unversioned libOpenCL.so symlink that JOCL
    #                      needs for dlopen("libOpenCL.so") to succeed
    pocl-opencl-icd ocl-icd-libopencl1 ocl-icd-opencl-dev \
    # Utilities (wget: entrypoint downloads; unzip/ca-certificates: Fiji stage)
    ca-certificates wget curl unzip procps \
    # Locale — ilastik4ij sets LC_ALL=en_US.UTF-8 in its subprocess environment
    locales \
    # Fonts
    fonts-dejavu-core fonts-liberation fonts-noto-color-emoji \
    && sed -i 's/^# *\(en_US.UTF-8\)/\1/' /etc/locale.gen && locale-gen \
    && fc-cache -f \
    && rm -rf /var/lib/apt/lists/*

# Non-root user (uid/gid 1000), shared by every stage so COPY --chown matches.
RUN groupadd -g 1000 imagentj \
    && useradd -u 1000 -g imagentj -m -d /home/imagentj -s /bin/bash imagentj

# ── fiji: Fiji + update-site plugins ─────────────────────────────────────────
FROM base AS fiji
ARG TARGETARCH
RUN set -e; \
    if [ "$TARGETARCH" = "arm64" ]; then \
        FIJI_ZIP=fiji-latest-linux-arm64-jdk.zip; FIJI_BINARY=fiji-linux-arm64; \
    else \
        FIJI_ZIP=fiji-latest-linux64-jdk.zip;     FIJI_BINARY=fiji-linux-x64; \
    fi; \
    wget -q "https://downloads.imagej.net/fiji/latest/${FIJI_ZIP}" -O /tmp/fiji.zip \
    && unzip -q /tmp/fiji.zip -d /opt \
    && rm /tmp/fiji.zip \
    && mv /opt/Fiji /opt/Fiji.app \
    && chmod +x "/opt/Fiji.app/${FIJI_BINARY}" /opt/Fiji.app/fiji

# Update sites. MorphoLibJ (IJPB-plugins) is a dep of TrackMate-MorphoLibJ.
# Deliberately NOT enabled (removed to slim the image): TensorFlow, CSBDeep,
# StarDist, TrackMate-StarDist, DeepImageJ. They remain installable at runtime
# through the agent's install_fiji_plugin tool (plugin registry), but their
# Python/TF backends are not in the image.
RUN printf '%s\n' \
    'IJPB-plugins https://sites.imagej.net/IJPB-plugins/' \
    'Neuroanatomy https://sites.imagej.net/Neuroanatomy/' \
    'TrackMate-MorphoLibJ https://sites.imagej.net/TrackMate-MorphoLibJ/' \
    'TrackMate-Ilastik https://sites.imagej.net/TrackMate-Ilastik/' \
    'TrackMate-Cellpose https://sites.imagej.net/TrackMate-Cellpose/' \
    'ImageScience https://sites.imagej.net/ImageScience/' \
    '3D_ImageJ_Suite https://sites.imagej.net/Tboudier/' \
    'BoneJ https://sites.imagej.net/BoneJ' \
    'OrientationJ http://sites.imagej.net/BIG-EPFL/' \
    'BigStitcher http://sites.imagej.net/BigStitcher/' \
    'clij https://sites.imagej.net/clij/' \
    'clij2 https://sites.imagej.net/clij2/' \
    'clijx-assistant https://sites.imagej.net/clijx-assistant/' \
    'clijx-assistant-extensions https://sites.imagej.net/clijx-assistant-extensions/' \
    'BioVoxxel http://sites.imagej.net/BioVoxxel/' \
    'BioVoxxel-3D-Box http://sites.imagej.net/bv3dbox/' \
    > /tmp/sites.txt \
    && while read -r name url; do \
        DISPLAY="" /opt/Fiji.app/fiji --headless --update add-update-site "$name" "$url" || true; \
    done < /tmp/sites.txt \
    && rm /tmp/sites.txt \
    && /opt/Fiji.app/fiji --headless --update update

# `--update update` only STAGES files into update/ — apply them so every plugin
# is baked in with no runtime network dependency. Then the post-install fixes:
#   * SPIM_Registration is superseded by BigStitcher's multiview-reconstruction
#     (same menu commands → duplicate-command warnings).
#   * 3D ImageJ Suite: mcib3d-core must sit in jars/, not plugins/, or every
#     3D Suite plugin except About_ fails with NoClassDefFoundError.
#   * SLF4J: Fiji ships the SLF4J 2.x API but logback-classic 1.2.x binds the
#     1.7.x way, which 2.x ignores ("No SLF4J providers" warnings). Swap in the
#     2.x NOP provider; a copy in /opt/fiji-patches lets the entrypoint restore
#     it into a fiji_jars named volume created by an older image.
RUN cp -a /opt/Fiji.app/update/plugins/. /opt/Fiji.app/plugins/ 2>/dev/null || true \
    && cp -a /opt/Fiji.app/update/jars/.    /opt/Fiji.app/jars/    2>/dev/null || true \
    && cp -a /opt/Fiji.app/update/macros/.  /opt/Fiji.app/macros/  2>/dev/null || true \
    && cp -a /opt/Fiji.app/update/scripts/. /opt/Fiji.app/scripts/ 2>/dev/null || true \
    && cp -a /opt/Fiji.app/update/lib/.     /opt/Fiji.app/lib/     2>/dev/null || true \
    && rm -rf /opt/Fiji.app/update/* \
    && find /opt/Fiji.app/plugins -name 'SPIM_Registration*.jar' -delete \
    && find /opt/Fiji.app/plugins -name 'mcib3d-core*.jar' -exec mv -v {} /opt/Fiji.app/jars/ \; \
    && rm -f /opt/Fiji.app/jars/logback-classic-1.2*.jar \
    && mkdir -p /opt/fiji-patches \
    && wget -q "https://repo1.maven.org/maven2/org/slf4j/slf4j-nop/2.0.16/slf4j-nop-2.0.16.jar" \
         -O /opt/fiji-patches/slf4j-nop-2.0.16.jar \
    && cp /opt/fiji-patches/slf4j-nop-2.0.16.jar /opt/Fiji.app/jars/

# BIOP Cellpose wrapper (ch.epfl.biop.wrappers.cellpose.*, from the PTBIOP update
# site). Runs Cellpose directly and returns the label image in-process
# (cp.cellpose_imp), without TrackMate. Only this one jar is bundled (sha256
# eb0b10d8686ae32f7364dddacb01c3dae2491eb330a97fbc9bcef37cce9fa842) rather than
# the whole PTBIOP site, to avoid version drift against the pinned jars. On
# Linux it runs `<env_path>/bin/python -m cellpose ...` directly, so the uv venv
# at /opt/uv/envs/cellpose needs no conda. See skills/cellpose_documentation/.
COPY bundled_jars/ijl-utilities-wrappers-0.12.1.jar /opt/Fiji.app/jars/

# Fiji's bundled JDK becomes the system Java (JAVA_HOME=/opt/java in the final
# stage). Record its location so the final stage can link it.
RUN JAVA_BIN="$(find /opt/Fiji.app/java -type f -path '*/bin/java' | head -1)" \
    && [ -n "$JAVA_BIN" ] \
    && dirname "$(dirname "$JAVA_BIN")" > /opt/fiji-patches/java_home \
    && "$JAVA_BIN" -version

# ── pyenvs: uv-managed Python + the three venvs ──────────────────────────────
FROM base AS pyenvs
ARG TARGETARCH
# USE_GPU=true installs the CUDA build of PyTorch into the cellpose env (amd64
# only). CUDA_TAG selects the wheel index; torch 2.11.0 is published only for
# cu126 (driver 560+, default) and cu128 (driver 570+, RTX 50xx).
ARG USE_GPU=false
ARG CUDA_TAG=cu126
ARG TORCH_VERSION=2.11.0

# Build-only tools: a compiler for sdists without wheels (mahotas, pulled in by
# cp_measure) and git for cp_measure's GitHub source. They stay in this stage.
RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential git \
    && rm -rf /var/lib/apt/lists/*
COPY --from=uv /uv /usr/local/bin/uv

# UV_COMPILE_BYTECODE: site-packages are root-owned at runtime, so Python could
# never cache .pyc files itself and would recompile every module (torch,
# langchain, Qt bindings) on every start. Costs some image size; set to 0 for
# the absolute smallest image at the price of slower startup.
ENV UV_PYTHON_INSTALL_DIR=/opt/uv/python \
    UV_PYTHON_PREFERENCE=only-managed \
    UV_LINK_MODE=copy \
    UV_COMPILE_BYTECODE=1
# 3.13 for the main and napari envs; 3.12 for cellpose, because cellpose 3 caps
# numpy<2.1 and numpy 2.0.x publishes no 3.13 wheels.
RUN uv python install 3.13 3.12

COPY docker/requirements/ /tmp/requirements/

# Main app env: the agent, GUI, pyimagej and the default analyst env.
RUN --mount=type=cache,target=/root/.cache/uv \
    uv venv --python 3.13 /opt/uv/envs/main \
    && uv pip sync --python /opt/uv/envs/main/bin/python /tmp/requirements/main.txt \
    && QT_QPA_PLATFORM=offscreen /opt/uv/envs/main/bin/python -c \
        "import imagej, scyjava, PySide6.QtWidgets, langchain, langgraph, deepagents, \
         qdrant_client, fastembed, pymupdf4llm, skimage, sklearn, plotnine, bigfish, \
         cp_measure, websockify; print('[OK] main env')"

# Install torch from the PyTorch index before Cellpose. ARM64 uses the CPU
# index. Cellpose 3 does not use torchvision.
RUN --mount=type=cache,target=/root/.cache/uv set -e; \
    uv venv --python 3.12 /opt/uv/envs/cellpose; \
    if [ "$USE_GPU" = "true" ] && [ "$TARGETARCH" != "arm64" ]; then \
        uv pip install --python /opt/uv/envs/cellpose/bin/python "torch==${TORCH_VERSION}" \
            --index-url "https://download.pytorch.org/whl/${CUDA_TAG}"; \
    else \
        uv pip install --python /opt/uv/envs/cellpose/bin/python "torch==${TORCH_VERSION}" \
            --index-url https://download.pytorch.org/whl/cpu; \
    fi; \
    uv pip install --python /opt/uv/envs/cellpose/bin/python \
        -r /tmp/requirements/cellpose.in; \
    /opt/uv/envs/cellpose/bin/python -c \
        "import torch, cellpose; from cellpose import models; \
         print('[OK] cellpose env: torch', torch.__version__, 'cuda_build', torch.version.cuda)"; \
    if [ "$USE_GPU" = "true" ] && [ "$TARGETARCH" != "arm64" ]; then \
        /opt/uv/envs/cellpose/bin/python -c \
            "import torch; assert torch.version.cuda, 'expected a CUDA torch build in the GPU image'"; \
    else \
        /opt/uv/envs/cellpose/bin/python -c \
            "import torch; assert torch.version.cuda is None, 'expected a CPU torch build'"; \
    fi

# Cellpose model weights: cyto3 (+ its size model) only, so a pulled image
# segments offline. Fetched by cellpose's own downloader; if cellpose.org is
# unreachable, fall back to the project's model bundle and keep just cyto3.
ENV CELLPOSE_LOCAL_MODELS_PATH=/opt/cellpose-models
RUN mkdir -p "$CELLPOSE_LOCAL_MODELS_PATH" \
    && ( /opt/uv/envs/cellpose/bin/python -c \
            "from cellpose import models; models.Cellpose(gpu=False, model_type='cyto3')" \
         || ( echo "[cellpose] cellpose.org unreachable — using the project model bundle" \
              && curl -fsSL "https://owncloud.ut.ee/owncloud/s/HyXebMNEPd7niMa/download" -o /tmp/models.zip \
              && unzip -q -j /tmp/models.zip 'models/cyto3' 'models/size_cyto3.npy' -d "$CELLPOSE_LOCAL_MODELS_PATH" \
              && rm /tmp/models.zip ) ) \
    && test -s "$CELLPOSE_LOCAL_MODELS_PATH/cyto3" \
    && test -s "$CELLPOSE_LOCAL_MODELS_PATH/size_cyto3.npy" \
    && ls -la "$CELLPOSE_LOCAL_MODELS_PATH"

# napari-mcp env: the in-container napari viewer the supervisor drives over MCP
# (stdio). The viewer is created lazily on the first napari tool call.
RUN --mount=type=cache,target=/root/.cache/uv \
    uv venv --python 3.13 /opt/uv/envs/napari-mcp \
    && uv pip sync --python /opt/uv/envs/napari-mcp/bin/python /tmp/requirements/napari.txt \
    && QT_QPA_PLATFORM=offscreen /opt/uv/envs/napari-mcp/bin/python -c \
        "import napari, napari_mcp, fastmcp; print('[OK] napari', napari.__version__)"

# Patch napari-mcp for Agent J's persistent, interactive viewer (see
# patch_napari_mcp/patch_qt_helpers.py): survive the window close button and
# keep the Qt event pump alive on any viewer reopen. Fails the build if the
# upstream source drifts.
COPY patch_napari_mcp/patch_qt_helpers.py /tmp/patch_qt_helpers.py
RUN /opt/uv/envs/napari-mcp/bin/python /tmp/patch_qt_helpers.py

# conda/micromamba shim (see micromamba_shim.sh) at the conda-style path that
# ~/.imagej/trackmate-conda.prefs points TrackMate at.
COPY --chmod=755 micromamba_shim.sh /opt/uv/bin/conda

# ── novnc: the browser VNC client (static files) ─────────────────────────────
# From the upstream release instead of Debian's `novnc` package, which pulls a
# system Python + numpy. The websocket proxy (websockify) is in the main env.
FROM base AS novnc
ARG NOVNC_VERSION=1.5.0
RUN mkdir -p /usr/share/novnc \
    && curl -fsSL "https://github.com/novnc/noVNC/archive/refs/tags/v${NOVNC_VERSION}.tar.gz" \
       | tar xz --strip-components=1 -C /usr/share/novnc \
    && rm -rf /usr/share/novnc/tests /usr/share/novnc/docs /usr/share/novnc/snap \
              /usr/share/novnc/utils /usr/share/novnc/po \
    # Default scaling mode → "Local Scaling" (noVNC keeps the setting in the
    # browser's localStorage; this changes the default for fresh sessions).
    && sed -i "s/initSetting('resize', 'off')/initSetting('resize', 'scale')/" \
       /usr/share/novnc/app/ui.js \
    && grep -q "initSetting('resize', 'scale')" /usr/share/novnc/app/ui.js \
    && ln -s vnc.html /usr/share/novnc/index.html

# ── appsrc: application source, minus build-only files ───────────────────────
FROM base AS appsrc
COPY . /app
# keys.py is .dockerignored (real secrets); ship the template in its place.
RUN rm -rf /app/bundled_cache /app/bundled_jars /app/docker /app/docs /app/user_guide \
           /app/patch_napari_mcp /app/Dockerfile* \
    && cp /app/src/config/keys_template.py /app/src/config/keys.py

# ── seedcache: pre-warmed jgo/Maven cache for pyimagej ───────────────────────
# pyimagej resolves imglib2-imglyb via jgo at first start; maven.scijava.org is
# unreliable, so the resolved cache ships with the repo. The entrypoint copies
# it into ~/.jgo and ~/.m2 (the home dir is a named volume). With the cache in
# place jgo never calls Maven, so the image ships no Maven.
FROM base AS seedcache
COPY bundled_cache/imagentj-seed-cache.tar.gz /tmp/imagentj-seed-cache.tar.gz
RUN mkdir -p /opt/imagentj-seed \
    && tar xzf /tmp/imagentj-seed-cache.tar.gz -C /opt/imagentj-seed \
    && chmod -R a+rX /opt/imagentj-seed

# ── cpu: the runtime image ───────────────────────────────────────────────────
FROM base AS cpu
ARG TARGETARCH
ARG USE_GPU=false

# Register the NVIDIA OpenCL driver (GPU builds only). CLIJ/CLIJ2 reach the GPU
# through OpenCL, not CUDA. The container runtime (CDI) mounts
# libnvidia-opencl.so.1 but does not write the ICD file, and the OpenCL loader
# finds platforms only via /etc/OpenCL/vendors/*.icd — without this CLIJ2 sees
# only POCL's CPU device (verified 2026-08-03: 8x A100 visible after adding it).
RUN if [ "$USE_GPU" = "true" ] && [ "$TARGETARCH" != "arm64" ]; then \
        mkdir -p /etc/OpenCL/vendors \
        && echo "libnvidia-opencl.so.1" > /etc/OpenCL/vendors/nvidia.icd; \
    fi

COPY --from=fiji --chown=imagentj:imagentj /opt/Fiji.app /opt/Fiji.app
COPY --from=fiji /opt/fiji-patches /opt/fiji-patches
COPY --from=pyenvs /opt/uv /opt/uv
COPY --from=novnc /usr/share/novnc /usr/share/novnc
COPY --from=seedcache /opt/imagentj-seed /opt/imagentj-seed

# TrackMate-Cellpose hardcodes the micromamba path: older versions use
# /usr/local/opt/micromamba/bin/micromamba, newer /opt/micromamba/bin/micromamba.
# Install the same shim at both (plus `conda` aliases).
COPY --chmod=755 micromamba_shim.sh /usr/local/opt/micromamba/bin/micromamba
RUN ln -sf micromamba /usr/local/opt/micromamba/bin/conda \
    && mkdir -p /opt/micromamba/bin \
    && cp /usr/local/opt/micromamba/bin/micromamba /opt/micromamba/bin/micromamba \
    && ln -sf micromamba /opt/micromamba/bin/conda \
    && ln -s "$(cat /opt/fiji-patches/java_home)" /opt/java \
    && /opt/java/bin/java -version

ENV PATH=/opt/uv/envs/main/bin:/opt/uv/bin:$PATH \
    VIRTUAL_ENV=/opt/uv/envs/main \
    FIJI_PATH=/opt/Fiji.app \
    JAVA_HOME=/opt/java \
    PYTHONPATH=/app:/app/src \
    LIBGL_ALWAYS_SOFTWARE=1

# Home directory content baked into the image. /home/imagentj is the
# imagentj_home named volume at runtime; the entrypoint seeds it from
# /home/imagentj.seed. ~/.cellpose/models is additionally its own named volume
# (cellpose_models), which Docker initialises from this layer.
#   * TrackMate v8 conda prefs: point TrackMate at the shim and the env root.
#   * Cellpose cyto3 weights.
COPY --from=pyenvs --chown=imagentj:imagentj /opt/cellpose-models /home/imagentj/.cellpose/models
RUN mkdir -p /home/imagentj/.imagej /home/imagentj/.cache \
    && printf '[trackmate]\ncondaRootPrefix=/opt/uv\ncondaExecutable=/opt/uv/bin/conda\n' \
        > /home/imagentj/.imagej/trackmate-conda.prefs \
    && chown -R imagentj:imagentj /home/imagentj \
    && cp -a /home/imagentj /home/imagentj.seed

# ── Application code ─────────────────────────────────────────────────────────
WORKDIR /app
COPY --from=appsrc --chown=imagentj:imagentj /app /app
# The qdrant_data dir must exist and be writable (bind-mounted in compose).
RUN mkdir -p /app/qdrant_data && chown imagentj:imagentj /app/qdrant_data

COPY --chmod=755 docker-entrypoint.sh /docker-entrypoint.sh

ENV DISPLAY=:1 \
    QT_QPA_PLATFORM=xcb \
    HOME=/home/imagentj

EXPOSE 6080
USER imagentj
ENTRYPOINT ["/docker-entrypoint.sh"]
CMD ["python", "gui_runner.py"]
