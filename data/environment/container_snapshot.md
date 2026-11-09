# Container Snapshot — slim image (uv envs), 2026-11-09

Versions below are the pins in `docker/requirements/*.txt` (main, napari-mcp) and the Dockerfile
(cellpose env). Fiji plugin/jar versions come from the last Fiji build and drift with the
`fiji-latest` download.

## Cellpose aliases

Cellpose model names are not separate packages — they ship inside the `cellpose` Python
package. Common phrasings are embedded in the rows below so substring search finds them.

| Alias | Where it lives | Notes |
|-------|----------------|-------|
| Cellpose 3 / cellpose v3 / cellpose env | env `cellpose` (Python 3.12, cellpose 3.1.1.2, torch 2.11.0) | The only Cellpose in the image. `/opt/uv/envs/cellpose/bin/python`; scripts select it with `# imagentj-env: cellpose`. |
| Cellpose models: cyto3 / size_cyto3 | pre-installed in `~/.cellpose/models` | Baked into the image — works offline. |
| Cellpose models: nuclei / nucleitorch_0 / cyto2 / cyto / livecell_cp3 / tissuenet_cp3 / deepbacs_cp3 / bact_* / yeast_* | downloaded by cellpose on first use into `~/.cellpose/models` | Needs network on first use; persisted in the `cellpose_models` volume afterwards. |
| Cellpose (BIOP) Fiji plugin / direct cellpose / cellpose segmentation in Fiji / Cellpose command | Fiji jar `ijl-utilities-wrappers` 0.12.1 (BIOP wrapper); runs `/opt/uv/envs/cellpose/bin/python -m cellpose` | Direct single-image Cellpose segmentation in Fiji, NO TrackMate. Returns the label image in-process. `env_path=/opt/uv/envs/cellpose`, `env_type="conda"`. See the `cellpose_documentation` skill. |
| TrackMate-Cellpose | Fiji update site TrackMate-Cellpose; reaches env `cellpose` through the conda/micromamba shim | Leave `CONDA_ENV='base'` — the shim routes it to the cellpose env. Its Cellpose-SAM and Omnipose detectors have no backend here. |
| Cellpose fine-tuning | `skills/python/cellpose/FINETUNING.md` (envs `napari-mcp` + `cellpose`) | Hand-drawn annotation in napari, then Cellpose 3 training. |

## Not installed (removed to slim the image)

These are NOT in this image. Do not plan pipelines around them. Fiji plugins among them can be
installed at runtime with `install_fiji_plugin` (user confirmation required), but their Python /
TensorFlow backends are not available.

| Component | Status |
|-----------|--------|
| StarDist (Fiji plugin, TrackMate-StarDist, Python stardist) | NOT installed — use Cellpose (cyto3 / nuclei) or classical threshold + watershed |
| CSBDeep / CARE / N2V / TensorFlow (Fiji update site and Python) | NOT installed |
| DeepImageJ / Appose / BioImage Model Zoo runner | NOT installed |
| micro_sam / Segment Anything / SAM / mobile_sam | NOT installed |
| Cellpose 4 / Cellpose-SAM / cpsam / env cellpose4 | NOT installed — Cellpose 3 only |
| Omnipose | NOT installed |
| BrainGlobe (brainglobe-atlasapi, brainreg, env brainglobe) | NOT installed |
| docling (PDF layout parsing) | NOT installed — PDFs are read with pymupdf / pymupdf4llm |
| conda / micromamba | NOT installed — envs are uv venvs under `/opt/uv/envs`; `conda`/`micromamba` are a compatibility shim for TrackMate |

---

## System / runtime

| Component | Version / detail |
|-----------|-----------------|
| **Base image** | debian:bookworm-slim |
| **Java** | JDK 21 bundled with Fiji (`fiji-latest-*-jdk`) |
| **JAVA\_HOME** | `/opt/java` (symlink into `/opt/Fiji.app/java/...`) |
| **ImageJ 1.x** | 1.54p (2025-02-18) |
| **Fiji / imagej2** | 2.17.1-SNAPSHOT (fiji jar), imagej2 2.16.0 |
| **Groovy** | 4.0.23 (in Fiji jars) |
| **Python envs** | uv venvs: `/opt/uv/envs/main` (3.13), `/opt/uv/envs/cellpose` (3.12), `/opt/uv/envs/napari-mcp` (3.13) |
| **uv** | build-time only (not in the runtime image) |
| **CUDA** | None (CPU-only container) |
| **Xvfb / x11vnc / fluxbox** | Debian bookworm packages |
| **noVNC** | 1.5.0 (upstream release) |
| **websockify** | 0.13.0 (main env) |
| **Mesa / OpenGL** | llvmpipe software renderer (libgl1-mesa-dri) |
| **OpenCL** | POCL CPU device (pocl-opencl-icd); NVIDIA ICD registered on GPU builds |

## Python environments

### Main env (`/opt/uv/envs/main`) — Python 3.13

The default for `python_data_analyst` scripts (`# imagentj-env: main` or no header). Pinned in
`docker/requirements/main.txt`.

| Package | Version |
|---------|---------|
| aiosqlite | 0.22.1 |
| annotated-doc | 0.0.5 |
| annotated-types | 0.8.0 |
| anthropic | 2.6.0 |
| anyio | 4.16.0 |
| attrs | 26.1.0 |
| authlib | 1.9.5 |
| beartype | 0.23.1 |
| beautifulsoup4 | 4.15.0 |
| big-fish | 0.6.2 |
| bioio | 3.7.0 |
| bioio-base | 3.6.0 |
| bioio-ome-tiff | 1.4.1 |
| bioio-tifffile | 1.3.1 |
| bracex | 3.2.2 |
| burner-redis | 0.1.7 |
| cachetools | 8.0.0 |
| centrosome | 1.3.4 |
| certifi | 2026.10.23 |
| cffi | 2.1.1 |
| charset-normalizer | 3.5.2 |
| cjdk | 0.5.0 |
| click | 8.5.1 |
| cloudpickle | 3.1.2 |
| contourpy | 1.4.0 |
| cp-measure | git (cp_measure.git@e218599802f3e09689b4817f1ecba72628477d89) |
| cronsim | 2.8 |
| cryptography | 50.0.2 |
| cycler | 0.12.1 |
| cyclopts | 5.4.0 |
| dask | 2026.8.0 |
| ddgs | 9.16.1 |
| deepagents | 0.7.34 |
| deprecation | 2.1.0 |
| diskcache | 5.6.3 |
| distributed | 2026.8.0 |
| distro | 1.9.0 |
| dnspython | 2.9.2 |
| docstring-parser | 0.18.0 |
| donfig | 0.8.1.post1 |
| elementpath | 5.1.4 |
| email-validator | 2.3.0 |
| exceptiongroup | 1.3.1 |
| fakeredis | 2.34.1 |
| fastembed | 0.9.1 |
| fastmcp | 2.14.7 |
| filelock | 4.2.9 |
| filetype | 1.2.0 |
| flatbuffers | 25.12.19 |
| flexcache | 0.3 |
| flexparser | 0.4 |
| fonttools | 4.68.0 |
| formulaic | 1.2.2 |
| fsspec | 2026.9.0 |
| google-auth | 2.62.1 |
| google-crc32c | 1.9.0 |
| google-genai | 3.0.0 |
| grpcio | 1.85.1 |
| h11 | 0.16.0 |
| h2 | 4.4.1 |
| hf-xet | 1.8.0 |
| hpack | 4.2.0 |
| httpcore | 1.0.9 |
| httpcore2 | 2.16.0 |
| httpx | 0.28.1 |
| httpx-sse | 0.4.3 |
| httpx2 | 2.16.0 |
| httpx2-jsfetch | 1.0 |
| huggingface-hub | 1.33.0 |
| hyperframe | 6.1.0 |
| idna | 3.20 |
| imagecodecs | 2026.10.10 |
| imageio | 2.38.1 |
| imglyb | 2.1.0 |
| interface-meta | 2.0.1 |
| jaraco-classes | 3.4.0 |
| jaraco-context | 6.1.2 |
| jaraco-functools | 4.6.0 |
| jeepney | 0.9.0 |
| jgo | 1.0.6 |
| jinja2 | 3.1.6 |
| jiter | 0.19.0 |
| joblib | 1.6.0 |
| joserfc | 1.8.0 |
| jpype1 | 1.6.0 |
| jsonpatch | 1.44 |
| jsonpointer | 3.10 |
| jsonref | 1.1.0 |
| jsonschema | 4.26.0 |
| jsonschema-path | 0.5.0 |
| jsonschema-specifications | 2025.9.1 |
| jwcrypto | 1.6.1 |
| kerchunk | 0.2.10 |
| keyring | 25.7.0 |
| kiwisolver | 1.5.1 |
| labeling | 0.1.15 |
| langchain | 1.4.9 |
| langchain-anthropic | 1.7.10 |
| langchain-core | 1.7.6 |
| langchain-google-genai | 4.4.3 |
| langchain-openai | 1.7.4 |
| langchain-protocol | 0.0.21 |
| langchain-qdrant | 1.1.0 |
| langchain-text-splitters | 1.1.3 |
| langgraph | 1.2.20 |
| langgraph-checkpoint | 4.3.1 |
| langgraph-checkpoint-sqlite | 3.1.3 |
| langgraph-prebuilt | 1.1.1 |
| langgraph-sdk | 0.4.14 |
| langsmith | 0.14.17 |
| lazy-loader | 0.6 |
| locket | 1.0.0 |
| loguru | 0.7.3 |
| lupa | 2.8 |
| lxml | 6.1.3 |
| mahotas | 1.4.19 |
| markdown-it-py | 4.2.0 |
| markupsafe | 3.0.4 |
| matplotlib | 3.11.2 |
| mcp | 1.30.0 |
| mdurl | 0.1.2 |
| mizani | 0.14.6 |
| mmh3 | 5.3.1 |
| more-itertools | 11.2.1 |
| mrc | 0.4.0 |
| msgpack | 1.2.4 |
| msgspec | 0.22.0 |
| narwhals | 2.28.0 |
| networkx | 3.7 |
| numcodecs | 0.17.1 |
| numpy | 2.5.4 |
| ome-types | 0.7.0 |
| onnxruntime | 1.31.1 |
| openai | 3.46.0 |
| openapi-pydantic | 0.6.0 |
| opencv-python-headless | 5.0.0.93 |
| opentelemetry-api | 1.45.2 |
| orjson | 3.13.0 |
| ormsgpack | 1.13.1 |
| packaging | 26.3 |
| pandas | 3.1.1 |
| partd | 1.4.2 |
| pathable | 0.6.0 |
| pathvalidate | 3.3.1 |
| patsy | 1.0.3 |
| pillow | 11.3.0 |
| pint | 0.26.2 |
| platformdirs | 4.14.5 |
| plotnine | 0.15.9 |
| portalocker | 4.4.2 |
| primp | 2.0.1 |
| progressbar2 | 4.7.0 |
| prometheus-client | 0.26.0 |
| protobuf | 7.36.2 |
| psutil | 7.2.2 |
| py-key-value-aio | 0.3.0 |
| py-key-value-shared | 0.3.0 |
| py-rust-stemmers | 0.1.8 |
| pyasn1 | 0.6.5 |
| pyasn1-modules | 0.4.2 |
| pycparser | 3.12 |
| pydantic | 2.14.3 |
| pydantic-core | 2.50.4 |
| pydantic-extra-types | 2.11.1 |
| pydantic-settings | 2.16.2 |
| pydicom | 3.0.2 |
| pydocket | 0.28.0 |
| pygments | 2.21.0 |
| pyimagej | 1.7.0 |
| pyjwt | 2.15.1 |
| pymupdf | 2.1 |
| pymupdf-layout | 2.1 |
| pymupdf4llm | 2.1 |
| pyparsing | 3.3.3 |
| pyperclip | 1.11.0 |
| pyside6-essentials | 6.12.0 |
| python-dateutil | 4.0.0 |
| python-dotenv | 1.2.4 |
| python-json-logger | 4.2.0 |
| python-multipart | 0.0.33 |
| python-utils | 4.2.0 |
| pyyaml | 6.0.3 |
| qdrant-client | 1.20.0 |
| readlif | 0.6.6 |
| redis | 8.1.0 |
| referencing | 0.37.0 |
| regex | 2026.11.9 |
| requests | 2.34.2 |
| requests-toolbelt | 1.0.0 |
| rich | 15.0.0 |
| rich-rst | 2.2.0 |
| rpds-py | 2026.9.1 |
| scikit-image | 0.26.0 |
| scikit-learn | 1.9.1 |
| scikit-misc | 0.5.3 |
| scipy | 1.18.1 |
| scyjava | 1.12.1 |
| seaborn | 0.13.2 |
| secretstorage | 3.5.0 |
| semver | 3.1.1 |
| shellingham | 1.5.4 |
| shiboken6 | 6.12.0 |
| sniffio | 1.3.1 |
| sortedcontainers | 2.4.0 |
| soupsieve | 4.0.1 |
| sqlite-vec | 0.1.9 |
| sse-starlette | 3.7.0 |
| starlette | 1.10.0 |
| statsmodels | 0.15.0 |
| tabulate | 0.10.0 |
| tblib | 3.2.2 |
| tenacity | 9.1.4 |
| threadpoolctl | 3.8.0 |
| tifffile | 2026.11.8 |
| tiktoken | 0.14.0 |
| tokenizers | 0.23.3 |
| toolz | 1.2.0 |
| tornado | 6.6 |
| tqdm | 4.70.1 |
| truststore | 0.10.5 |
| typer | 0.28.0 |
| typing-extensions | 4.16.0 |
| typing-inspection | 0.4.5 |
| tzdata | 2026.6 |
| ujson | 6.1.0 |
| uncalled-for | 0.6.0 |
| urllib3 | 2.8.0 |
| uuid-utils | 0.19.0 |
| uvicorn | 0.54.0 |
| wcmatch | 12.0.1 |
| websockets | 17.4 |
| websockify | 0.13.0 |
| wrapt | 2.5.2 |
| xarray | 2026.9.0 |
| xmlschema | 4.3.2 |
| xsdata | 26.10 |
| xxhash | 4.0.2 |
| zarr | 3.4.2 |
| zict | 3.0.0 |
| zstandard | 0.25.0 |

### env `cellpose` (`/opt/uv/envs/cellpose`) — Python 3.12

Selected with `# imagentj-env: cellpose`. Also used by the BIOP Fiji wrapper and TrackMate-Cellpose.
torch is the CPU wheel on the CPU image and the CUDA (cu126) wheel on the GPU image.

| Package | Version |
|---------|---------|
| cellpose | 3.1.1.2 |
| torch | 2.11.0 (+cpu or +cu126) |
| numpy | 2.0.x (cellpose 3 caps numpy<2.1) |
| scipy | latest compatible |
| scikit-image | latest compatible |
| pandas | latest compatible |
| matplotlib | latest compatible |
| tifffile | >=2025.5.10 |
| opencv-python-headless | via cellpose |
| fastremap / fill-voids / roifile / natsort / numba | via cellpose |
| langchain-core / langgraph-checkpoint-sqlite / pydantic | for the analyst harness |

### env `napari-mcp` (`/opt/uv/envs/napari-mcp`) — Python 3.13

The in-container napari viewer (driven via `mcp__napari_mcp__*`) and the Cellpose fine-tuning
windows (`# imagentj-env: napari-mcp`). No deep-learning packages. Pinned in
`docker/requirements/napari.txt`.

| Package | Version |
|---------|---------|
| napari | 0.8.0 |
| napari-mcp | 0.1.0 |
| fastmcp | 2.14.7 |
| mcp | 1.30.0 |
| pyqt6 | 6.12.0 |
| pyqt6-qt6 | 6.12.0 |
| qtpy | 2.4.3 |
| superqt | 0.9.1 |
| magicgui | 0.10.2 |
| vispy | 0.16.2 |
| numpy | 2.5.4 |
| scipy | 1.18.1 |
| scikit-image | 0.26.0 |
| tifffile | 2026.11.8 |
| imageio | 2.38.1 |
| pillow | 13.0.0 |
| pandas | 3.1.1 |
| dask | 2026.8.0 |

---

## Fiji plugins (`/opt/Fiji.app/plugins/`)

| JAR | Version |
|-----|---------|
| 3D_Blob_Segmentation | 4.0.0 |
| 3D_Objects_Counter | 2.0.1 |
| 3D_Viewer | 5.0.1 |
| AnalyzeSkeleton | 3.4.2 |
| Anisotropic_Diffusion_2D | 2.0.1 |
| Archipelago_Plugins | 0.5.4 |
| Arrow_ | 2.0.2 |
| Auto_Local_Threshold | 1.11.0 |
| Auto_Threshold | 1.18.0 |
| BalloonSegmentation_ | 3.0.1 |
| Big_Stitcher | 2.6.1 |
| Biovoxxel_Plugins | 2.6.3 |
| Cell_Counter | 3.0.0 |
| Colocalisation_Analysis | 3.1.0 |
| Colour_Deconvolution | 3.0.3 |
| CorrectBleach_ | 2.1.0 |
| Descriptor_based_registration | 2.1.8 |
| Directionality_ | 2.3.0 |
| Extended_Depth_Field | 2.0.1 |
| Fiji_Plugins | 3.2.0 |
| FlowJ_ | 2.0.1 |
| Graph_Cut | 1.0.2 |
| HDF5_Vibez | 1.1.1 |
| IO_ | 4.3.0 |
| LSM_Reader | 4.1.2 |
| LocalThickness_ | 5.0.0 |
| Manual_Tracking | 2.1.1 |
| MorphoLibJ_ | 1.6.5 |
| OrientationJ_ | 2.0.7 |
| RATS_ | 2.0.2 |
| SNT | 5.0.8-SNAPSHOT |
| Siox_Segmentation | 1.0.5 |
| Skeletonize3D_ | 2.1.1 |
| StackReg_ | 2.0.1 |
| Statistical_Region_Merging | 2.0.1 |
| Stitching_ | 3.1.9 |
| ToAST_ | 25.0.2 |
| TrackMate | 8.1.6 |
| TrackMate-Cellpose | 1.0.1 |
| TrackMate-Ilastik | 2.0.0 |
| TrackMate-MorphoLibJ | 2.0.0 |
| Trainable_Segmentation (Weka) | 4.0.0 |
| TrakEM2_ | 2.0.0 |
| TurboReg_ | 2.0.1 |
| UnwarpJ_ | 2.0.0 |
| VIB_ | 4.0.0 |
| bigwarp_fiji | 9.3.1 |
| bio-formats_plugins | 8.5.0 |
| bonej-legacy-plugins_ | 7.1.10 |
| bUnwarpJ_ | 2.6.13 |
| bv3dbox | 1.25.1 |
| clij_ | 1.9.0.1 |
| clij2_ | 2.5.3.5 |
| clij2-assistant_ | 2.5.1.6 |
| clijx_ | 0.32.2.0 |
| ij_ridge_detect | 1.4.1 |
| mcib3d_plugins | 4.1.7b |
| mpicbg_ | 1.6.0 |
| multiview_reconstruction | 8.1.2 |
| n5-viewer_fiji | 6.1.2 |
| register_virtual_stack_slices | 3.0.8 |

---

## Key Fiji jars (`/opt/Fiji.app/jars/`)

| JAR | Version |
|-----|---------|
| bio-formats (formats-api/bsd/gpl) | 8.5.0 |
| fiji | 2.17.1-SNAPSHOT |
| groovy + modules | 4.0.23 |
| ij (ImageJ 1.x) | 1.54p |
| ijl-utilities-wrappers (BIOP Cellpose direct wrapper; its CellposeSAM command has no backend here) | 0.12.1 |
| imagej | 2.16.0 |
| imagej-common | 2.1.1 |
| imagej-legacy | 2.0.3 |
| imagej-ops | 2.2.0 |
| imagej-updater | 2.0.3 |
| imglib2 | 7.1.5 |
| javafx (all modules) | 23.0.2 |
| jogl-all | 2.6.0 |
| jython-slim | 2.7.4 |
| labkit-ui | 0.4.0 |
| n5 | 3.5.1 |
| nashorn-core | 15.6 |
| ome-xml | 6.5.3 |
| opencv | 4.9.0-1.5.10 |
| scijava-common | 2.100.0 |
| scifio | 0.49.0 |
| scifio-ome-xml | 0.17.1 |
| simpleitk | 2.1.0.dev54 |
| slf4j-api | 2.0.17 |
| slf4j-nop | 2.0.17 |
| sqlite-jdbc | 3.49.1.0 |
| weka-dev | 3.9.6 |

---
