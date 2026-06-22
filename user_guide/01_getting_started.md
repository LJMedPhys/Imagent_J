# Getting Started

## Prerequisites

- [Docker Desktop](https://www.docker.com/products/docker-desktop/) (or Docker Engine + Compose on Linux)
- At least 8 GB RAM and 30 GB free disk space
- An API key — either OpenAI or OpenRouter (see below)

---

## 1. Choose how to run Agentic-J

There are two supported Docker paths:

- **Published Docker image, no source checkout:** fastest path for regular use. Docker downloads the published Compose file and image from Docker Hub.
- **Source checkout:** best for development or local code changes. You clone the repository and run `docker compose up` from the project root.

---

## 2. Run the published image without cloning the repository

Open Terminal in any folder where you want to keep your Agentic-J working files, then create a `data/` folder:

```bash
mkdir -p data
```

Put your image files in this `data/` folder. Inside the container it will be mounted at `/app/data`.

Start Agentic-J from the published Docker Compose artifact:

```bash
docker compose \
  -f oci://docker.io/mmvlab/agenticj-compose:latest \
  run \
  -d \
  --service-ports \
  -e OPEN_ROUTER_API_KEY="your-openrouter-api-key" \
  -v "$PWD/data:/app/data" \
  imagentj
```

Replace `your-openrouter-api-key` with your key. If you prefer OpenAI, replace `OPEN_ROUTER_API_KEY` with `OPENAI_API_KEY`. If you leave the key unset, or set it to an empty string (`OPEN_ROUTER_API_KEY=""`), a setup wizard will appear in the browser before Fiji launches.

Open your browser and go to:

```text
http://localhost:6080/vnc.html
```

Click "Connect". Fiji and the Agentic-J chat panel should appear in the browser window.

To stop and remove the container/network created by Compose:

```bash
docker compose \
  -f oci://docker.io/mmvlab/agenticj-compose:latest \
  down --remove-orphans
```

Your `data/` folder stays on your machine. Runtime state such as Fiji plugins, saved scripts, chat history, Cellpose models, and Qdrant data is stored in Docker named volumes.

---

## 3. Run from a source checkout

Use this path if you cloned the repository and want to build or run from the local source tree.

### Create a `.env` file

Copy `.env.template` and paste the file into the project root (i.e. the cloned repo), rename this as `.env`. This files helps pass credentials into the container. The `GMAIL_APP_PASSWORD` (not an actual password, trust us) is for sending the error report directly to the developers. A minimal example of the `.env` file content:

```env
# Required: pick one 
OPENAI_API_KEY=your-openai-api-key-here
OPEN_ROUTER_API_KEY=your-openrouter-api-key-here

# For reporting issues directly
GMAIL_APP_PASSWORD=sntt iusy rddg mtoi

```

---

### API key options

| Provider | Variable | Notes |
|----------|----------|-------|
| **OpenAI** | `OPENAI_API_KEY` | Direct access to GPT models. OpenAI-only setups use `gpt-5.6-luna` through the Responses API with high reasoning for the VLM Judge. |
| **OpenRouter** | `OPEN_ROUTER_API_KEY` | Proxy that routes to many providers. The VLM Judge uses `google/gemini-3.5-flash`; this route takes priority when both keys are present. |

If neither key is set in the `.env` when the container starts, a **setup wizard** will appear in the browser before Fiji launches. You can insert the key there.

<!-- SCREENSHOT: setupwizard-->


---

### Place your images

Put your image files in the `data/` folder at the project root (i.e. the cloned repo). Inside the container this folder is mounted at `/app/data`. The agent can read from and write to this path.

```
project-root/
├── data/           ← your images go here
│   └── my_image.tif
├── .env
└── docker-compose.yml
```

---

### Start the container
Open the Terminal, and find your project folder. Inside the project folder, run the following command:

```bash
docker compose up
```

During the first run, Docker will pull/build the image (this takes several minutes). On subsequent starts it reuses the cached image. In the terminal, a long log will be printed out, but do not fret, most of it is just informative. 

Open your browser and go to:

```
http://localhost:6080/vnc.html
```

Click on "Connect", Fiji and the Agentic-J chat panel should appear in the browser window. Sometimes the SL4FJ warning pops up in the Console window, but this is not severe, and the window can be closed. 

To stop:

```bash
docker compose down
```

> Your data, scripts, models, plugins, and chat history are persisted in Docker named volumes and the `data/` folder — they survive container restarts and image rebuilds.

---

## 4. Updating

When a new image version is available:

```bash
docker compose pull   # or rebuild: docker compose build
docker compose up
```

Named volumes (Fiji plugins, chat history, saved scripts) are preserved across updates.
