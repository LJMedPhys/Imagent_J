# Your Files, Chats and Reports

## Where your files are saved

Everything Agentic-J saves appears straight away in the `data/` folder on your computer. You don't need to copy anything out. When you start an analysis, Agentic-J creates a project folder for it with the layout below. You can also put your images anywhere inside `data/` and tell the assistant where they are.

```
data/
├── projects/                   ← one folder per analysis
│   └── my_project/
│       ├── raw_images/         ← copies of your original images
│       ├── processed_images/
│       │   ├── channels/       ← separated or pre-processed channels
│       │   └── montages/       ← overview images
│       ├── scripts/
│       │   ├── imagej/         ← Fiji scripts (Groovy)
│       │   └── python/         ← Python scripts (statistics, plots, napari)
│       ├── data/               ← measurement tables (CSV)
│       ├── figures/            ← plots and figures
│       ├── logs/               ← logs, including usage and cost per message
│       ├── state_ledger.json   ← the project's memory: settings, steps, decisions
│       └── QA_Checklist_Report.md  ← written by the QA checker (if switched on)
├── fine-tuned-models/          ← your own Cellpose models (see chapter 02)
├── learned/                    ← lessons Agentic-J has learned from fixing errors
├── chats/                      ← chat history
│   ├── checkpoints.db          ← all conversations
│   └── index.json              ← chat titles and dates
└── agentic-j_debug.log         ← technical log, useful when reporting problems
```

Every script that produced a result is saved, and older versions are kept in an `archive/` folder next to it. So you can always see exactly what was done, and run it again.

When you [fine-tune a model](06_napari_and_fine_tuning.md), the image squares you corrected, the trained model and the before/after scores are also saved in the project folder.

---

## Chat history

Your conversations are saved and kept after restarting. The side bar on the left of the chat window lists all chats; click one to open it. Keeping one chat per topic or project helps the assistant remember the context.

You can't switch chats while the assistant is working.

---

## Usage reports

The **Save Usage Report** button saves a file with the number of AI tokens used, the estimated cost and the models used in the current chat. Use it to keep track of spending. You choose where the file is saved.

The same information, message by message, is also in each project's `logs/usage_log.json`.

---

## Reporting issues

The **Report Issue** button shows two ways to reach the developers:

- **GitHub:** open a new issue at <https://github.com/MMV-Lab/Agentic-J/issues/new> (you need a GitHub account). Issues there are public.
- **Email:** write to **agentj.help@gmail.com**.

Each has a **Copy** button. Because Agentic-J runs inside its own virtual desktop, the copied text appears in the clipboard panel of the noVNC side bar (see [Copying and pasting](02_interface_and_agents.md#copying-and-pasting-clipboard)), from where you can paste it into your own browser or email program.

Please describe what you asked the assistant to do and what went wrong. It also helps to attach:
- the **usage report** of the chat (**Save Usage Report** button);
- the project's `state_ledger.json` and `logs/` folder;
- `data/agentic-j_debug.log`.

These files can contain file names, measurements and parts of your conversation, so check them before posting them publicly on GitHub.
