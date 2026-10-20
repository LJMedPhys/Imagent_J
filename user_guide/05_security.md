# Security and Privacy

## What the assistant can do on your computer

Agentic-J runs and writes code in Fiji and Python, reads and writes files, and installs Fiji plugins. That is what makes it useful. It does all of this inside its own isolated box (the Docker container), and the only folder of yours it can see is `data/`. Files elsewhere on your computer are out of its reach.

Still, keep a backup of important original images **outside** `data/`, because the assistant can change and delete files there.

---

## What is sent to the AI provider, and what stays on your computer

The AI models run at the provider whose key you use (OpenAI, or the companies reached through OpenRouter). Image processing itself (Fiji, Python, napari, Cellpose and so on) runs **on your computer**.

| | Sent to the AI provider? |
|---|---|
| Your chat messages | **Yes**, always |
| File and folder names, and image information such as size, pixel size, number of channels and bit depth | **Yes** |
| The scripts it writes, and what they print (numbers, measurements, error messages) | **Yes** |
| Tables and text files the assistant opens to read (for example a results CSV) | **Yes**, the parts it reads |
| The pixels of your images | **No**, unless one of the three cases below applies |

Your images leave your computer only in these cases:

1. **The Vision Judge is on.** Small copies of your images and results are sent for review (see below).
2. **You ask about an open window** ("What does this window do?"). A screenshot of that Fiji or napari window is sent so it can be explained. Anything visible in the window, including an image, is part of the screenshot.
3. **The assistant takes a screenshot of napari** to check what is displayed. This can happen when you work with napari.

If you use the web search, the search words are sent to a search service.

Check your AI provider's terms for how long they keep data and whether they use it for training, especially for unpublished or sensitive data.

---

## The Vision Judge

The Vision Judge is an AI model that can look at pictures. Switch it on or off with the **Vision Judge** tick box in the chat window. It is **off by default**, and the setting is saved for each chat.

### When it is on

- **At the start**, it looks at a representative input image and gives a general impression (for example: is it in focus, is it saturated, are the objects visible?).
- **After every step that produces an image** (a processed image, a mask, an overlay), it looks at the result and checks whether it matches what was expected. For a segmentation, it gets a side-by-side picture of the original image, the mask and the mask laid over the original.
- **What is sent:** a PNG copy of each picture, shrunk so the longest side is at most 1024 pixels. Your original files are not sent.
- **Where it is sent:** with an OpenRouter key, to Google's Gemini model (through OpenRouter); with only an OpenAI key, to OpenAI. The model can be changed in [`imagentj_config.yaml`](02_interface_and_agents.md#settings-imagentj_configyaml).
- **What it does with the answer:** its comments are **advice only**. The measurements, the image information and your own approval always count for more. Its comments are written into the project's `state_ledger.json`. If the Vision Judge fails or is unavailable, the analysis carries on without it.
- **Cost:** each check is an extra AI call, so an analysis becomes somewhat slower and more expensive.

### When it is off

The Vision Judge is removed for that chat completely: the assistant cannot call it. Your images are then processed only on your computer, and only the information in the table above (text, numbers, image information) is sent, plus screenshots in cases 2 and 3.

---

## Default protection

| What | Setting |
|---------|--------|
| Container user | Runs as a normal user (`imagentj`), not as administrator |
| System permissions | All extra Linux permissions removed; it can't give itself more |
| Resources | Up to 4 processor cores and 12 GB of memory |
| Browser access | Port 6080 (see below) |

**Network access:** the current `docker-compose.yml` makes port 6080 reachable from other computers on your network, not only from your own computer. On a shared or public network, either set a password with `VNC_PASSWORD=...` in `.env`, or change the line `"0.0.0.0:6080:6080"` in `docker-compose.yml` to `"127.0.0.1:6080:6080"` so that only your computer can connect.

---

## API keys

- Keep your keys only in `.env`, and never share that file.
- `.env` is not copied into the Agentic-J image.
- Keys reach Agentic-J as settings when it starts. The assistant cannot read the file where keys entered in the setup wizard are stored.
