# Agentic-J

An AI-powered agent for microscopy image analysis. Agentic-J runs ImageJ inside a container together with an LLM-driven chat panel that can plan analyses, write and execute Groovy macros, install plugins, and report results.

## Quick start (Docker)

Prerequisites:

- [Docker Desktop](https://www.docker.com/products/docker-desktop/) (or Docker Engine + Compose on Linux)
- [Git](https://git-scm.com/downloads) **and** [Git LFS](https://git-lfs.com/) — the RAG vector database (`qdrant_data/**/storage.sqlite`) is stored via Git LFS, so a plain clone without LFS will give you stub files that won't work.
- ~8 GB RAM and ~30 GB free disk
- An OpenAI/OpenRouter API key, **or** a local OpenAI-compatible endpoint (e.g. GLM-5.3-Flash)

> The optional VLM Judge uses `google/gemini-3.5-flash` when
> `OPEN_ROUTER_API_KEY` is set (including when both keys are present). OpenAI-only
> setups use `gpt-5.6-luna` with high reasoning through the Responses API.

Steps:

```bash
# 1. One-time: enable Git LFS for your user (skip if already done)
git lfs install

# 2. Clone the repository (LFS files download automatically)
git clone https://github.com/MMV-Lab/Agentic-J.git Agentic-J
cd Agentic-J

# If you cloned BEFORE running `git lfs install`, hydrate the LFS files now:
# git lfs pull

# 3. Configure credentials
cp .env.template .env
# edit .env and configure one provider

# 4. Start the container
docker compose up
```

Then open <http://localhost:6080/vnc.html> in your browser. Fiji and the Agentic-J chat panel run inside the virtual desktop.

If no API key is set in `.env`, a setup wizard appears in the browser before Fiji launches.

### Local LLM endpoint

A local vLLM/SGLang OpenAI-compatible server can replace all text and vision
roles. For one listening on host loopback port 18000, put this in `.env` (the
URL must include `/v1`):

```env
LOCAL_LLM_BASE_URL=http://127.0.0.1:18000/v1
LOCAL_LLM_API_KEY=EMPTY
LOCAL_LLM_MODEL=GLM-5.3-Flash
LOCAL_LLM_API=responses
```

`LOCAL_LLM_BASE_URL` takes priority if cloud keys are also present.

**Changing the model** is a one-line edit: `LOCAL_LLM_MODEL` is the global
switch and repoints every local agent role at once. It overrides
`local_llm.model` in `imagentj_config.yaml`, which is the fallback when the env
var is unset; `local_llm.models.<role>` pins one role and beats both. Only when
all three are absent does the built-in `config.DEFAULT_LOCAL_LLM_MODEL` apply.
The served id must match what the endpoint reports at `GET /v1/models`. The shipped
configuration uses `max` reasoning for the supervisor and script-producing
worker roles (ImageJ coder/debugger and Python data analyst); the remaining
specialist/VLM roles use `high`. In local mode, documentation retrieval uses
the prebuilt BM25 sparse index and makes no cloud embedding calls.

`LOCAL_LLM_API` selects one protocol for every local role, including the VLM.
Use `chat_completions` instead if the server exposes only
`/v1/chat/completions`; otherwise `responses` calls `/v1/responses`. Image
requests on these endpoints require an explicit `detail` level, which Agentic-J
supplies.

Because a bridge-network container cannot reach a server bound only to the
host's `127.0.0.1`, start this setup with the supplied host-network override:

```bash
docker compose -f docker-compose.yml -f docker-compose.local-kimi.yml up
```

The UI remains at <http://localhost:6081/vnc.html>. If the server instead
listens on `0.0.0.0:18000`, normal `docker compose up` also works by setting
`LOCAL_LLM_BASE_URL=http://host.docker.internal:18000/v1`.

The benchmark adapter uses an isolated bridge network rather than the
host-network override. In benchmark mode Agentic-J rewrites a loopback
`LOCAL_LLM_BASE_URL` to `host.docker.internal` automatically. The endpoint must
therefore be reachable on the host's Docker gateway address (for example, a
server bound to `0.0.0.0` or a deliberately configured host-side relay). An SSH
forward listening only on host `127.0.0.1` is not gateway-reachable; keep it
private and relay only onto the Docker bridge interface instead of exposing an
unauthenticated model port to the wider network.

Place images you want to analyse in [`./data/`](data/) — the agent sees them at `/app/data` inside the container.

> **Verifying LFS worked:** after cloning, check that `qdrant_data/collection/BioimageAnalysisDocs/storage.sqlite` is several MB, not a ~130-byte text file starting with `version https://git-lfs.github.com/...`. If it's a stub, run `git lfs install && git lfs pull`.

## Running alongside other sessions

Several people run Agentic-J from their own checkouts on the same host, so a
plain `docker compose up` collides with them. Each collision has its own knob;
set them once in `.env`.

| Collides on | Symptom | Knob | Default |
|---|---|---|---|
| Compose project name | Compose stops and recreates a *colleague's* container, because it believes it owns it | `COMPOSE_PROJECT_NAME` | the checkout's directory name |
| Bridge subnet | `Pool overlaps with other one on this address space` | `IMAGENTJ_SUBNET` | `10.10.10.0/24` |
| Published noVNC port | `Bind for 0.0.0.0:6080 failed: port is already allocated` | `NOVNC_PORT` | `6080` |

`COMPOSE_PROJECT_NAME` matters most: two checkouts are often both named
`Imagent_J`, and without it Compose treats a colleague's running container as
yours and stops it. `NOVNC_PORT` drives *both* sides of the port mapping — the
published host port and the port websockify binds inside the container — so the
UI is always at `http://localhost:$NOVNC_PORT/vnc.html`.

A working `.env` for a shared host:

```env
COMPOSE_PROJECT_NAME=imagentj_yourname
IMAGENTJ_SUBNET=100.64.200.0/24
NOVNC_PORT=7080
```

Check what is already taken before starting:

```bash
# published host ports
docker ps --format '{{.Names}}\t{{.Ports}}'

# subnets already in use
for n in $(docker network ls --format '{{.Name}}'); do
  echo "$n $(docker network inspect "$n" --format '{{range .IPAM.Config}}{{.Subnet}}{{end}}')"
done
```

Never stop a container you do not recognise. Ask who owns it first:

```bash
docker inspect <name> --format '{{index .Config.Labels "com.docker.compose.project.working_dir"}}'
```

### Host networking

`docker-compose.local-kimi.yml` switches to `network_mode: host`, which sidesteps
the subnet and port knobs entirely — but it also takes X display `:1` and VNC
port 5900 globally. A second host-network session cannot start Xvfb, fluxbox or
x11vnc and dies on startup. Use it only when nobody else is running one; the
bridge setup above is the safe default on a shared machine.

### Reaching a loopback LLM endpoint from the bridge

`LOCAL_LLM_BASE_URL=http://127.0.0.1:18000/v1` is correct under host networking,
but on the bridge `127.0.0.1` names the *container*. The entrypoint rewrites a
loopback URL to `host.docker.internal` only when `BENCHMARK_MODE` is set, so for
a normal `docker compose up` point it there yourself:

```bash
IMAGENTJ_SUBNET=100.64.200.0/24 \
LOCAL_LLM_BASE_URL=http://host.docker.internal:18000/v1 \
docker compose up -d
```

`host.docker.internal` maps to the `docker0` gateway address, not to your
project network's own gateway. An SSH forward bound only to host `127.0.0.1` is
therefore invisible to the container; bind a second one to the `docker0` address
(`ip -4 addr show docker0`) and leave the private one alone:

```bash
ssh -fN -L 10.54.0.1:18000:127.0.0.1:8000 <llm-host>
```

Confirm the container can see it before launching the full app:

```bash
docker run --rm --add-host host.docker.internal:host-gateway alpine:3 \
  wget -qO- http://host.docker.internal:18000/v1/models
```

That should print the served model id, which must match `LOCAL_LLM_MODEL`.

## GPU support (optional)

By default the container runs on **CPU** (`docker compose up`). On an NVIDIA GPU host you can run the GPU build, which accelerates the deep-learning segmentation steps — **Cellpose** (v3 + Cellpose-SAM, PyTorch) and **StarDist** (TensorFlow).

Requirements:

- NVIDIA GPU + driver **560+** (for the default CUDA 12.6 build; `560+` for `cu126`, `570+` for `cu128`)
- [nvidia-container-toolkit](https://docs.nvidia.com/datacenter/cloud-native/container-toolkit/install-guide.html)
- **CDI enabled** in Docker (Docker 25+). Verify:

  ```bash
  docker info | grep -iA2 'CDI spec'   # must list the CDI spec directories
  nvidia-ctk cdi list                   # must list nvidia.com/gpu=all, =0, ...
  ```

  If those are empty, enable CDI once (needs host admin):

  ```bash
  sudo nvidia-ctk cdi generate --output=/etc/cdi/nvidia.yaml
  # add   "features": { "cdi": true }   to /etc/docker/daemon.json
  sudo systemctl restart docker
  ```

**1. Set the build parameters.** Two build args in the [`Dockerfile`](Dockerfile) control the image — both **default to a CPU build**:

- **`USE_GPU`** — `false` (default) installs CPU PyTorch/TensorFlow; `true` installs CUDA PyTorch + `tensorflow[and-cuda]`.
- **`CUDA_TAG`** — the PyTorch CUDA wheel index. `cu126` (default) targets driver **560+**; `cu128` targets driver **570+** (newest CUDA / RTX 50xx).

`docker-compose.gpu.yml` already sets `USE_GPU=true` (and `CUDA_TAG=cu126`) for you. To pick a different CUDA build, export `CUDA_TAG` before building:

```bash
export CUDA_TAG=cu128     # optional; default is cu126
```

> **Older drivers (< 560).** `torch==2.11.0` wheels are published **only** for `cu126` and `cu128`. To target a lower tag (`cu121`/`cu124`), setting `CUDA_TAG` is not enough — you must also lower the pinned `torch==2.11.0` and `torchvision==0.26.0` strings in the [`Dockerfile`](Dockerfile) to a release that exists for that tag (e.g. `torch==2.6.0` for `cu124`), or the build fails with `No matching distribution found for torch==2.11.0`.

**2. Build and start** with the `docker-compose.gpu.yml` override:

```bash
# First time: build the GPU image (~30–60 min; downloads CUDA torch + tensorflow[and-cuda])
docker compose -f docker-compose.yml -f docker-compose.gpu.yml build

# Start
docker compose -f docker-compose.yml -f docker-compose.gpu.yml up -d
```

(To build the GPU image without the override, pass the args directly: `docker compose build --build-arg USE_GPU=true --build-arg CUDA_TAG=cu126`.)

**3. Verify** the GPU is active inside the container:

```bash
docker compose -f docker-compose.yml -f docker-compose.gpu.yml exec imagentj \
  /opt/conda/envs/cellpose/bin/python -c "import torch; print(torch.cuda.is_available())"   # -> True
```

## Documentation

The full user guide lives in [`user_guide/`](user_guide/):

| Guide | Contents |
|-------|----------|
| [01 Getting Started](user_guide/01_getting_started.md) | Prerequisites, `.env` setup, API keys, starting the container |
| [02 Interface & Agents](user_guide/02_interface_and_agents.md) | noVNC interface, agent architecture, supported plugins |
| [03 Prompting](user_guide/03_prompting.md) | How to write effective prompts |
| [04 Data, History & Reports](user_guide/04_data_history_and_reports.md) | File layout, chat history, issue reports |
| [05 Security](user_guide/05_security.md) | Security model, network exposure, key handling |


## Project layout

- [`src/imagentj/`](src/imagentj/) — main Python package (agents, tools, RAG)
- [`skills/`](skills/) — per-plugin documentation packs the agent retrieves at runtime
- [`bundled_jars/`](bundled_jars/), [`bundled_cache/`](bundled_cache/) — JARs and a pre-warmed jgo/Maven cache used to build the image offline
- [`data/`](data/) — image data and per-run outputs (mounted into the container)
- [`models/`](models/) — Cellpose models (bind-mounted at runtime)

## Development (without Docker)

Running on the host is supported but not the recommended path. See [environment.yml](environment.yml) for the conda environment, set `FIJI_PATH` to your local Fiji install, and run `python gui_runner.py` (GUI) or `python run.py` (CLI).

## Reporting issues

Use the **Report Issue** button in the chat panel, or email `agentj.help@gmail.com`.

## License

Apache License 2.0 — see [LICENSE](LICENSE) and [NOTICE](NOTICE).
Copyright © 2026 ISAS e.V.
