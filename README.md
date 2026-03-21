# Chinese Learning Dataset

> A very small personal dataset built purely for learning programming and natural language processing (NLP). Nothing serious here.

🌐 Companion website: [chineselearning-longe.streamlit.app](https://chineselearning-longe.streamlit.app)

---

## About

This dataset is sourced from Chinese text content. At the moment it only provides a **high-level outline skeleton** (chapter structure) — the actual content will be expanded and filled in gradually over time.

**Primary purpose:** Learning NLP techniques. That's it.

If it happens to be useful for anyone learning Chinese, great — but this is not intended as a Chinese learning resource.

---

## Current Status / TODO

### Data Cleaning
- [ ] Clean existing Chinese dataset
- [ ] Expand outline skeleton into full content
- [ ] Structure data into JSON format

### Model
Currently using a lightweight open-source language model from Meta (free tier). It has limitations and isn't great for complex tasks, but it works fine as an experiment. Planning to find cheaper or free multimodal AI alternatives down the line.

---

## Roadmap: Agent Crew

Planning to build a crew of **5 agents** to handle the dataset pipeline — essentially object-oriented programming, with each agent defined as a class with its own methods and responsibilities.

### Agent Architecture

| Agent | Role | Model Complexity |
|-------|------|-----------------|
| **Agent 1 — Supervisor** | Monitors all agents, reports progress | Complex |
| **Agent 2 — Design** | Handles UI and visual design tasks | Simple |
| **Agent 3 — Deployment** | Manages GitHub / Streamlit publishing | Simple |
| **Agent 4 — Data Processing** | Scrapes and cleans Chinese text from PDFs, web pages, and raw text files; outputs structured JSON | Complex |
| **Agent 5 — Script Editor** | Takes cleaned data and refines/updates scripts accordingly | Complex |

### Workflow

```
Supervisor Agent (1)
    ├── Data Processing Agent (4) → clean text / PDF / web → JSON
    │       └── Script Editor Agent (5) → update scripts
    ├── Design Agent (2) → UI design
    └── Deployment Agent (3) → GitHub + Streamlit publish
```

---

## Stack

- **Language model:** Meta open-source lightweight model (free)
- **Web app:** Streamlit
- **Data format:** JSON
- **Deployment:** GitHub + Streamlit Cloud
