# APIGen Studio: Martian-Grade Developer Experience (DX) Architecture
*Inspired by Roman Shamin & the Evil Martians Product Design Team ("Devs in mind: how to design interfaces for developer tools")*

---

## 1. The Core Philosophy: Why Dev Tools Are Different

Developer tools are fundamentally different from consumer apps:
1. **High-Stakes Screen Time:** Developers live inside these tools for hours. Micro-frictions (hunting for buttons, losing scroll position, modal popups that block view) multiply exponentially into frustration and lost productivity.
2. **Dispersed Attention & Constant Context-Switching:** Developers jump between terminal, editor, Slack, browser, and documentation. A great dev tool allows instant mental context restoration.
3. **Non-Linear Exploration:** There is no single "funnel." Developers jump between checking a field type, tweaking a mock, test-driving a cURL command, and checking Terraform configs in arbitrary order.
4. **Information Density over Artificial Whitespace:** Developers value compact, high-utility, structured information density where everything needed to make a technical decision is visible in one glance.

---

## 2. The Three Contexts Model Applied to APIGen Studio

```
+-------------------------------------------------------------------------------------------------------+
|  BROAD CONTEXT                                                                                        |
|  - Developer switching between IDE, Terminal, Browser, and Team Chat.                                 |
|  - Predictable window behavior, robust OS shortcuts, clear export paths (ZIP, Git, cURL).            |
|  +-------------------------------------------------------------------------------------------------+  |
|  |  INTERMEDIATE CONTEXT                                                                           |  |
|  |  - The holistic task: Turning messy client CSV/JSON into a live, tested, documented API.       |  |
|  |  - Two-pane workspace: Ingestion & Contract on Left; Code & Live Sandbox on Right.               |  |
|  |  - State persistence: Form values, modified rows, and history stay intact during navigation.     |  |
|  |  +-------------------------------------------------------------------------------------------+  |  |
|  |  |  IMMEDIATE CONTEXT                                                                        |  |  |
|  |  |  - Single-panel actions: Editing field types, inspecting PK, sending a test GET/POST.     |  |  |
|  |  |  - Sturdy controls: Segmented pills instead of buried dropdowns, inline line numbers.    |  |  |
|  |  |  - Micro-feedbacks: Sub-10ms response latencies, inline 1-click clipboard copy with check. |  |  |
|  |  +-------------------------------------------------------------------------------------------+  |  |
|  +-------------------------------------------------------------------------------------------------+  |
+-------------------------------------------------------------------------------------------------------+
```

### A. Immediate Context (Micro-Level Efficiency)
* **Everything in One Panel:** When testing an endpoint in the Live Playground, the method picker, path bar, query parameters, send button, status badge, and formatted JSON output exist within a unified panel. No jumping across tabs just to inspect responses.
* **Sturdy Controls:** Use explicit segmented control buttons (GET, POST, DELETE) instead of opaque dropdowns. High contrast, distinct color-coding (GET: Emerald, POST: Blue, DELETE: Rose).
* **Panel Footers for Secondary Actions:** Footers house secondary actions (Download Zip, Copy cURL, Toggle Mocks) cleanly anchored to the bottom of cards.

### B. Intermediate Context (Workflow Continuity)
* **Persistent State Across Tabs:** Switching from the Live Simulator to Python (`app/main.py`), TypeScript SDK (`sdk/client.ts`), or Terraform (`terraform/main.tf`) never resets scroll positions, parameters, or active records.
* **Instant Type Feedback:** Changing a field name or editing a row in the intake editor immediately recalculates the Inferred Schema table and updates the generated code in real time without a manual "Submit" click.
* **Quick Presets with Semantic Data:** Pre-loaded realistic industry datasets (`Customers`, `Inventory`, `Transactions`) allowing immediate mental grounding.

### C. Broad Context (Ecosystem Interoperability)
* **cURL & Fetch Quick-Copy:** Every simulated endpoint includes a 1-click **"Copy as cURL"** button, allowing the developer to immediately paste the request into their external terminal or Postman.
* **Standard OS Keyboard Shortcuts:**
  * `⌘ + Enter` / `Ctrl + Enter`: Execute simulated request.
  * `⌘ + S` / `Ctrl + S`: Export unzipped production bundle.
  * `⌘ + K` / `Ctrl + K`: Quick-focus search / path input.
* **Zero Build & Portable Distribution:** Single-file studio that works offline and natively binds to `python3 apigen.py studio`.

---

## 3. UI/UX Transformation Checklist

| Evil Martians Principle | Previous Implementation | Redesigned Martian-Grade Implementation |
| :--- | :--- | :--- |
| **Control Sturdiness** | Hidden dropdowns, small text fields. | High-visibility segmented pills, inline status tags, monospaced code inputs. |
| **Information Density** | Excessive padding, spaced out lists. | Tight 4px/8px engineering grid, compact table view of schema attributes. |
| **State Persistence** | Form values could desync on reload. | Synchronized local memory store across tabs; tab switches retain code views. |
| **Direct Ecosystem Bridges** | Code could only be copied manually. | **"Copy as cURL"** and **"Copy as Fetch"** micro-actions attached to simulator. |
| **Context Switching Friction**| User had to guess what changed in code. | Real-time schema inspector badge updating with row counts and PK flags. |
