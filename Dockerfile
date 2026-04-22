FROM continuumio/miniconda3:latest

ENV DEBIAN_FRONTEND=noninteractive

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
    && mv /opt/Fiji /opt/Fiji.app \
    && find /opt/Fiji.app -maxdepth 1 -name 'ImageJ-*' -exec chmod +x {} \;

ENV FIJI_PATH=/opt/Fiji.app

ARG IMGLIB2_UNSAFE_TAG=imglib2-unsafe-1.1.0
ARG IMGLIB2_IMGLYB_TAG=imglib2-imglyb-1.1.0

# Bundle ImgLib2 helper jars locally so PyImageJ does not need to fetch them
# from maven.scijava.org during first startup.
RUN mkdir -p /opt/imagentj-bootstrap/fiji-jars; \
    set -eux; \
    build_dir="$(mktemp -d)"; \
    javac_bin="$(find /opt/Fiji.app/java -path '*/bin/javac' | head -n1)"; \
    jar_bin="$(find /opt/Fiji.app/java -path '*/bin/jar' | head -n1)"; \
    fiji_jars="$(find /opt/Fiji.app/jars -name '*.jar' -printf '%p:' | sed 's/:$//')"; \
    curl -fsSL "https://github.com/imglib/imglib2-unsafe/archive/refs/tags/${IMGLIB2_UNSAFE_TAG}.zip" -o "${build_dir}/imglib2-unsafe.zip"; \
    unzip -q "${build_dir}/imglib2-unsafe.zip" -d "${build_dir}"; \
    unsafe_src="$(find "${build_dir}" -maxdepth 1 -type d -name 'imglib*unsafe*' | head -n1)"; \
    mkdir -p "${build_dir}/unsafe-classes"; \
    find "${unsafe_src}/src/main/java" -name '*.java' > "${build_dir}/unsafe-sources.txt"; \
    "${javac_bin}" -proc:none -cp "${fiji_jars}" -d "${build_dir}/unsafe-classes" @"${build_dir}/unsafe-sources.txt"; \
    "${jar_bin}" --create --file /opt/Fiji.app/jars/imglib2-unsafe-1.1.0-local.jar -C "${build_dir}/unsafe-classes" .; \
    cp /opt/Fiji.app/jars/imglib2-unsafe-1.1.0-local.jar /opt/imagentj-bootstrap/fiji-jars/; \
    curl -fsSL "https://github.com/imglib/imglib2-imglyb/archive/refs/tags/${IMGLIB2_IMGLYB_TAG}.zip" -o "${build_dir}/imglib2-imglyb.zip"; \
    unzip -q "${build_dir}/imglib2-imglyb.zip" -d "${build_dir}"; \
    imglyb_src="$(find "${build_dir}" -maxdepth 1 -type d -name 'imglib*imglyb*' | head -n1)"; \
    python -c "from pathlib import Path; p = Path(r'${imglyb_src}/src/main/java/net/imglib2/python/Helpers.java'); text = p.read_text(); old = 'public static < T extends NativeType< T >, A > CachedCellImg< T, A > imgFromFunc('; new = 'public static < T extends NativeType< T >, A extends net.imglib2.img.basictypeaccess.DataAccess > CachedCellImg< T, A > imgFromFunc('; assert old in text, 'expected signature not found'; p.write_text(text.replace(old, new, 1))"; \
    mkdir -p "${build_dir}/imglyb-classes"; \
    find "${imglyb_src}/src/main/java" -name '*.java' > "${build_dir}/imglyb-sources.txt"; \
    "${javac_bin}" -proc:none -cp "/opt/Fiji.app/jars/imglib2-unsafe-1.1.0-local.jar:${fiji_jars}" -d "${build_dir}/imglyb-classes" @"${build_dir}/imglyb-sources.txt"; \
    "${jar_bin}" --create --file /opt/Fiji.app/jars/imglib2-imglyb-1.1.0-local.jar -C "${build_dir}/imglyb-classes" .; \
    cp /opt/Fiji.app/jars/imglib2-imglyb-1.1.0-local.jar /opt/imagentj-bootstrap/fiji-jars/; \
    rm -rf "${build_dir}"

# ── Conda environment (heaviest layer - keep stable) ─────────────────────────
COPY environment.yml /tmp/environment.yml
RUN conda env create -f /tmp/environment.yml \
    && conda clean -afy \
    && rm /tmp/environment.yml

# Put the conda env on PATH so it's active by default
ENV PATH=/opt/conda/envs/local_imagent_J/bin:$PATH
ENV CONDA_DEFAULT_ENV=local_imagent_J

# ── Fonts (separate layer - changes here won't invalidate conda cache) ───────
RUN apt-get update && apt-get install -y --no-install-recommends \
    fonts-dejavu-core fonts-liberation fonts-noto-color-emoji \
    && rm -rf /var/lib/apt/lists/* \
    && fc-cache -f -v

# ── Non-root user ─────────────────────────────────────────────────────────────
RUN groupadd -r imagentj && useradd -r -g imagentj -m -d /home/imagentj -s /bin/bash imagentj

# ── Application code ─────────────────────────────────────────────────────────
WORKDIR /app
COPY . /app

# Use keys_template.py as keys.py (keys.py is .dockerignored since it has real secrets)
RUN cp /app/src/config/keys_template.py /app/src/config/keys.py

# Ensure the app user owns everything it needs to write to (including qdrant_data directory)
RUN mkdir -p /app/qdrant_data \
    && chown -R imagentj:imagentj /app /home/imagentj /app/qdrant_data \
    && chown -R imagentj:imagentj /opt/Fiji.app

# ── Environment defaults ─────────────────────────────────────────────────────
ENV DISPLAY=:1
ENV QT_QPA_PLATFORM=xcb
ENV JAVA_HOME=/opt/conda/envs/local_imagent_J/lib/jvm
ENV HOME=/home/imagentj

# ── Entrypoint ────────────────────────────────────────────────────────────────
COPY docker-entrypoint.sh /docker-entrypoint.sh
RUN chmod +x /docker-entrypoint.sh

EXPOSE 6080

USER imagentj

ENTRYPOINT ["/docker-entrypoint.sh"]
CMD ["python", "gui_runner.py"]
