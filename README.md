# ⚡ AI QA Tester (v2.5 - Advanced)

An AI-powered eCommerce QA testing platform that uses a **local AI agent (Ollama)** to autonomously execute browser-based test cases autonomously. Features automated test generation, mobile emulation, and technical failure detection (Network/Console analysis).

> **100% Local & Offline.** Runs entirely on your machine using [Ollama](https://ollama.com). No cloud APIs or internet required for execution.

> 📄 Full documentation: [`AI Agent QA.md`](AI%20Agent%20QA.md) · 🗺️ Roadmap: [`ROADMAP.md`](ROADMAP.md)

---

## ✨ Features

| Feature | Description |
|---|---|
| 🤖 **AI Discovery (Adv)** | Auto-scan site to generate 15-20 tests including Edge Cases & Negative tests. |
| 🕵️ **Tech-Audit** | Real-time capturing of Console Errors and Network failures during execution. |
| 📱 **Mobile Emulation** | Switch between Desktop and Mobile viewports for responsive testing. |
| 🛠 **Auto-Healing** | AI automatically repairs broken selectors and saves them back to the DB. |
| 🗂 **Project Workspace** | Multi-project support with unique Base URLs and analytics. |
| 📡 **Ollama Live Terminal** | See the AI's "Thought Process" and "Reasoning" live as it works. |
| 📸 **Screenshot Gallery** | Physical image storage for every step (saved in `data/screenshots/`). |
| 🧩 **Chrome Extension** | Native recording & syncing — record on any site, save to project instantly. |
| 🌓 **Theme Engine** | Full Dark/Light mode support with persistent state. |

---

## 🏗 Architecture

- **Frontend:** Vanilla JS (SPA), Inter Font, SSE Real-time streaming.
- **Backend:** Flask (Python), Playwright (Browser Control), Threaded Worker Queue.
- **Database:** TinyDB (Local JSON) + File System (Screenshots).
- **AI Agent:** Ollama (qwen2.5-coder:3b) with Adaptive Selector Logic.

---

## 🛠 Getting Started

### 1. System Requirements
- **CPU:** Intel i7-6700 (or equivalent) recommended.
- **RAM:** 16 GB (ensure at least 3-4 GB free for the AI model).
- **OS:** Windows 10/11.

### 2. Environment Setup
```bash
# Create & activate virtual environment (recommended)
python -m venv .venv
.venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt

# Install Playwright browsers
playwright install chromium
```

### 3. Set up the AI Backend (Ollama)
```bash
# Install Ollama from https://ollama.com, then pull the model
ollama pull qwen2.5-coder:3b
```

### 4. Run the Server
```bash
python smart_tester.py
```

Access the dashboard at: **http://localhost:5000**

---

## 🧩 Chrome Extension (Recorder)

The **AI QA Recorder** lets you build test cases without writing a single line of code.

1. Load `chrome-extension/` into Chrome (Developer Mode).
2. Set Server URL to `http://localhost:5000`.
3. Record your flow (Clicks, Typing, Selects).
4. Click **Save to Project** — the extension automatically maps actions to the AI's native format.

---

## ✅ Technical Parity

| Target Site | Status | Notes |
|---|---|---|
| **hmemedicalshop** | PASS | Standard eCommerce flow (100% Accurate). |
| **naseej** | ADAPTED | Complex Hyva UI - handled via Coordinate Clicks. |
| **Google Baseline** | PASS | Search & Interaction verified. |

---

## 📂 Project Structure
```
AI Agent QA/
├── smart_tester.py         # Main Flask Backend & AI Logic
├── ui/                     # Frontend Dashboard (HTML/CSS/JS)
├── data/
│   ├── database.json       # Metadata & Results (<300KB)
│   └── screenshots/        # Physical test evidence (PNG)
├── chrome-extension/       # Native Browser Recorder
└── .venv/                  # Local Python Environment
```

---

## 🗺 Roadmap

See [`ROADMAP.md`](ROADMAP.md) for upcoming features:
1. ⏰ Scheduled Runs (CRON)
2. 📊 Advanced PDF/CSV Reporting
3. 🛠️ AI "Self-Healing" Test Updates
4. 📸 Visual Regression (Baseline Comparison)
5. 🔗 Webhook & Slack/Discord Integration

---

**Internal tool — Optimized for Local AI Performance.**