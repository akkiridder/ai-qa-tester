# ⚡ AI QA Tester (v2.5 - Advanced)

An AI-powered eCommerce QA testing platform that uses a **local AI agent (Ollama)** to autonomously execute browser-based test cases. This version features automated test generation, mobile emulation, and technical failure detection (Network/Console analysis).

> **100% Local & Offline.** Runs entirely on your machine using [Ollama](https://ollama.com). No cloud APIs or internet required for execution.

---

## 📋 Table of Contents

- [Core Updates (v2.5)](#-core-updates-v25)
- [System Requirements](#-system-requirements)
- [AI Backend — Ollama](#-ai-backend--ollama)
- [Key Features](#-features)
- [Architecture](#-architecture)
- [Getting Started](#-getting-started)
- [Usage Guide](#-usage-guide)
- [Chrome Extension](#-chrome-extension-recorder)
- [Technical Parity](#-technical-parity)

---

## 🚀 Core Updates (v2.5)

This project has been significantly upgraded with enterprise-grade features:
- **AI Test Generator:** Automatically crawls any URL to generate 10-15 relevant eCommerce test cases (Login, Search, Cart, etc.) in seconds.
- **Technical Failure Detection:** Tests now fail if hidden JavaScript errors or 4xx/5xx Network failures occur, even if the UI appears correct.
- **Mobile Emulation:** Native support for running test cases on mobile viewports (iPhone 13) with touch event simulation.
- **Auto-Healing Selectors:** If a selector fails, the AI analyzes the DOM, finds the best alternative, and **permanently updates the database**.
- **Sequential Regression:** "Run All" now processes tests one-by-one to prevent system hang and ensure 100% Ollama reliability.

---

## 💻 System Requirements

Based on the current optimized setup:
- **CPU:** Intel i7-6700 (or equivalent) recommended.
- **RAM:** 16 GB (Ensure at least 3-4 GB is free for the AI model).
- **GPU:** Not required (Integrated Intel HD 530 is sufficient for the `3B` model).
- **OS:** Windows 10/11 (win32).

---

## 🤖 AI Backend — Ollama

We use **Qwen 2.5 Coder 3B** as the default model. It is the "Sweet Spot" for CPU-based QA—smart enough for complex logic but fast enough for real-time testing.

### Pull the Model
```bash
ollama pull qwen2.5-coder:3b
```

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

### 1. Environment Setup
```bash
# Install dependencies
pip install -r requirements.txt

# Install Playwright browsers
playwright install chromium
```

### 2. Run the Server
```bash
python smart_tester.py
```
Access the dashboard at: `http://localhost:5000`

---

## 🧩 Chrome Extension (Recorder)

The **AI QA Recorder** allows you to build test cases without writing a single line of code.
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
**Internal tool — Optimized for Local AI Performance.**
