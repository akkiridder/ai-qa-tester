# 🗺️ AI QA Tester - Product Roadmap

This document outlines the planned enhancements for the **AI QA Tester** project. Each feature will be implemented sequentially to ensure system stability and high quality.

---

## ✅ Completed Phases
- **🚀 Phase 1: Auto-Healing Selectors (Self-Repair)** — System automatically learns and updates failing selectors.
- **📱 Phase 2: Mobile Emulation Testing** — Run existing test cases on simulated mobile environments.
- **🕵️ ~~Phase 3: Network & Console Log Analysis~~** — Captures hidden API failures and JS errors during execution.
- **🤖 ~~Priority 2: AI Discovery (Advanced)~~** — Replaced static Seed QA with dynamic, edge-case-aware site discovery.

---

## 🚀 Future Roadmap (New Priority Order)

### **1. ⏰ Scheduled Runs (CRON) — [PRIORITY 3]**
- **Feature:** Dedicated "Schedules" tab for each project.
- **Benefit:** Automatically execute full regression suites at specified intervals (e.g., every 4 hours, daily at midnight).

### **2. 📊 Advanced PDF/CSV Reporting — [PRIORITY 4]**
- **Feature:** Branded "Export Report" button.
- **Benefit:** Generate professional PDF reports with pass/fail charts and screenshot evidence for stakeholders and clients.

### **3. 🛠️ AI "Self-Healing" Test Updates — [PRIORITY 5]**
- **Feature:** Detect changes in element IDs or structures (e.g., `#submit-btn` to `#login-submit`).
- **Benefit:** AI automatically updates the test case steps in the database to maintain test validity over time.

### **4. 📸 Visual Regression (Baseline Comparison) — [PRIORITY 6]**
- **Feature:** Set a "Golden Screenshot" for each step.
- **Benefit:** In future runs, the system compares new screenshots against the baseline using pixel-diffing and highlights any visual changes (CSS breaks, missing images, or layout shifts).

### **5. 🔗 Webhook & Slack/Discord Integration — [PRIORITY 7]**
- **Feature:** Real-time regression alerts via webhooks.
- **Benefit:** Instant notifications for failed critical tests directly to team communication channels.

---

**Current Status:** Phase 3 and AI Test Generation completed. Starting Priority 3 (Scheduled Runs).
