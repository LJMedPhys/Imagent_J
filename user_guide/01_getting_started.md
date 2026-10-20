# Getting Started

## What you need

- [Docker Desktop](https://www.docker.com/products/docker-desktop/) (on Linux, Docker Engine with Compose also works). Docker runs Agentic-J in its own isolated box (a "container"), so you don't have to install Fiji, napari or Python yourself.
- At least 8 GB of RAM (16 GB is more comfortable for large images) and 30 GB of free disk space.
- An API key from **OpenAI** or **OpenRouter**. This is what lets Agentic-J use the AI models. Usage is billed by the provider (see [Usage reports](04_data_history_and_reports.md#usage-reports)).

---

## 1. Create the `.env` file

The `.env` file holds your keys and passes them to Agentic-J.

1. In the project folder (the folder you downloaded or cloned), make a copy of `.env.template`.
2. Rename the copy to `.env`.
3. Paste your API key after `OPENAI_API_KEY=` or `OPEN_ROUTER_API_KEY=`. You only need one of the two.

A minimal `.env` looks like this:

```env
# Required: pick one
OPENAI_API_KEY=your-openai-api-key-here
OPEN_ROUTER_API_KEY=your-openrouter-api-key-here
```

---

## 2. Which key to use

| Provider | Line in `.env` | Notes |
|----------|----------|-------|
| **OpenAI** | `OPENAI_API_KEY` | Uses OpenAI's GPT models directly. |
| **OpenRouter** | `OPEN_ROUTER_API_KEY` | One key for models from many companies (OpenAI, Google, Anthropic and others). If both keys are present, OpenRouter is used. |

If neither key is in `.env`, a **setup wizard** opens in the browser before Fiji starts, and you can paste the key there.

To change which model each part of Agentic-J uses, see [Settings](02_interface_and_agents.md#settings-imagentj_configyaml).

---

## 3. Put your images in the `data/` folder

Copy your images into the `data/` folder inside the project folder. Agentic-J can only see files in this folder.

```
project-folder/
├── data/           ← your images go here
│   └── my_image.tif
├── .env
└── docker-compose.yml
```

Inside Agentic-J the same folder is called `/data` (and `/app/data`), so a file you put at `data/experiment_01/image.tif` is `/data/experiment_01/image.tif` in the chat.

---

## 4. Start Agentic-J

Open a terminal, go to the project folder and run:

```bash
docker compose up
```

The first start downloads and builds everything, which takes a while. Later starts are quick. The terminal prints a lot of text; most of it is just information and can be ignored.

Then open this address in your browser:

```
http://localhost:6080/vnc.html
```

Click **Connect**. Fiji and the Agentic-J chat window appear in the browser. If a console window with an "SLF4J" warning pops up, you can close it; it is harmless.

To stop Agentic-J:

```bash
docker compose down
```

Your images, results, scripts, installed plugins and chat history are kept when you stop, restart or update Agentic-J.

---

## 5. Using a graphics card (optional)

Agentic-J runs on the processor (CPU) by default. If your computer has an NVIDIA graphics card (GPU), you can use it to make deep-learning steps much faster: Cellpose, StarDist, micro-sam and, above all, [fine-tuning a model](06_napari_and_fine_tuning.md). Fine-tuning takes 10–20 minutes on a GPU, but hours on a CPU.

The setup steps are in the main [README](../README.md#gpu-support-optional). In short, you start Agentic-J with an extra file:

```bash
docker compose -f docker-compose.yml -f docker-compose.gpu.yml up
```

---

## 6. Updating

When a new version is available:

```bash
docker compose pull   # or, if you build it yourself: docker compose build
docker compose up
```

Your data, plugins, chat history and saved scripts are kept.
