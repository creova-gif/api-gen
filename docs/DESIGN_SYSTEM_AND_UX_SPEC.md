# APIGen Studio: Design System & UX Architecture Specification

**Version:** 1.0.0  
**Role:** Principal Product Designer & Front-End Architect  
**Standard:** WCAG 2.1 AA Compliant, Nielsen Heuristics Aligned, Sub-50ms Interaction Budget  

---

## 1. Assumptions & Product Context

1. **Target Users:**
   * **Solutions Architects (SAs) & Forward-Deployed Engineers (FDEs):** Need to onboard prospect/client data into an interactive API demo in < 5 minutes.
   * **Backend / Platform Engineers:** Need to eliminate repetitive CRUD boilerplate without sacrificing security, typing, or CI/CD auditability.
   * **Frontend / Full-Stack Developers:** Need instant mock endpoints and a typed TypeScript SDK to build against before backend teams finish production database wiring.
2. **Key Goals:**
   * **Zero-Setup Time-to-Hello-World (TTHW < 30 seconds):** Users drop raw data and immediately interact with a live endpoint.
   * **Transparency over Black Boxes:** Users must see the inferred types, inspect the generated Python/TypeScript code, and test endpoints live.
   * **1-Click Export:** Download clean code or copy cURL/fetch snippets with zero vendor lock-in.
3. **Tech Stack & Distribution:**
   * Standalone, zero-build client app (`apigen/studio/index.html`) using Tailwind CSS, vanilla ES2022 JavaScript, and standard browser Web APIs.
   * Bundled directly into the `api-gen` Python distribution (`python3 apigen.py studio`) and hostable statically on GitHub Pages, Vercel, or Cloud Run.

---

## 2. UX Foundation & Core User Flows

### Core Persona Archetypes
* **Primary Persona:** *Alex (Solutions Engineer at Series B SaaS)*. Needs to turn a customer's 10,000-row `transactions.csv` into an authenticated API with search and pagination for a proof-of-concept call at 2:00 PM today.
* **Secondary Persona:** *Taylor (Senior Backend Architect)*. Demands clean Pydantic v2 code, typed parameters, deterministic primary keys, and strict cloud infrastructure templates.

### Core User Flows & Rationale

#### Flow 1: Instant Onboarding & Primary Generation
```
[Drop Dataset or Click 'Load Sample'] 
       │ 
       ▼ (Automatic parsing & schema inference in <20ms)
[Inferred Schema Table + Live Simulator pre-populated]
       │
       ▼ (Tweak toggles: Auth, Synthetic Mocks, SQLite durable state)
[Inspect Code in Tabs OR Test GET/POST in Playground]
       │
       ▼
[1-Click Download .zip / Copy Code]
```
*Rationale:* Removing mandatory signup or form wizard stages shortens cognitive load. The UI updates optimistically on every keystroke or drop event.

#### Flow 2: Live Exploration & Request Simulation
```
[Select Method (GET/POST/PATCH/DELETE)]
       │
       ▼
[Enter Query Parameters or Request Payload]
       │
       ▼ (Hit 'Send' or Press Ctrl+Enter)
[Sub-10ms In-Memory Mock Execution] ───► [Status 200/201/404 + Formatted JSON + Latency Badge]
```
*Rationale:* Engineers do not trust code generation tools until they can execute against the schema and observe deterministic request/response cycles.

#### Flow 3: Error Recovery & Edge Case Handling
* **Malformed CSV/JSON:** In-line non-blocking alert banner with exact row/column number and automatic fallback to string coercion.
* **Missing Primary Key:** Non-destructive warning badge with automatic fallback to first unique column or auto-generated UUID.
* **Empty Payload:** Clear empty state illustration with immediate 1-click sample dataset injection.

---

## 3. Information Architecture & Layout Structure

The interface employs a **Master-Detail Split Architecture**:

```
+---------------------------------------------------------------------------------------------------+
| Top Navigation Bar: App Identity, Status, Dataset Switcher, Keyboard Shortcut Help, Export CTA   |
+---------------------------------------------------------------------------------------------------+
| Left Column (Control & Ingestion - 5 cols)  | Right Column (Inspection & Playground - 7 cols)     |
| - File Dropzone & Dataset Selector         | - Sticky Segmented Navigation Tabs                  |
| - Raw Schema / CSV Editor with Line Numbers |   1. 🚀 Interactive Live Playground                  |
| - Live Resource & Field Configuration      |   2. 🐍 Python (FastAPI + Pydantic v2)              |
| - Security & Infrastructure Toggles        |   3. 🔷 TypeScript Client SDK                       |
| - Inferred Schema Field Table (PK, Types)  |   4. ☁️ Terraform Infrastructure                    |
|                                            |   5. 📑 OpenAPI 3.1 Contract                        |
|                                            | - Execution Drawer: Method, URL, Body, JSON Output  |
+---------------------------------------------------------------------------------------------------+
| Keyboard Shortcut Status Footer: [⌘+Enter] Send Request  •  [⌘+K] Clear  •  [⌘+S] Export ZIP      |
+---------------------------------------------------------------------------------------------------+
```

---

## 4. Visual Design System

### 4.1 Typography Scale
* **Primary Sans:** `"Plus Jakarta Sans"`, system-ui, sans-serif (balanced geometric curves, high legibility at micro sizes).
* **Monospace:** `"JetBrains Mono"`, monospace (code blocks, types, query parameters, latency badges).

| Token | Size | Line Height | Weight | Usage |
| :--- | :--- | :--- | :--- | :--- |
| `display` | 24px (1.5rem) | 32px | 700 Bold | Hero Headers, Modal Titles |
| `title` | 18px (1.125rem) | 24px | 600 SemiBold | Section Headings |
| `body-base` | 14px (0.875rem) | 20px | 400 Regular / 500 Medium | Controls, Labels, Inputs |
| `body-sm` | 12px (0.75rem) | 16px | 400 Regular / 500 Medium | Field descriptions, badges |
| `mono-code`| 12px (0.75rem) | 18px | 400 Regular / 500 Medium | Inferred types, code editors |
| `caption` | 11px (0.6875rem)| 14px | 500 Medium | Badges, Micro-counters, Footers |

### 4.2 Color System (WCAG 2.1 AA Compliant)
Engineered for deep-focus engineering environments:

* **Surface Hierarchy:**
  * Background Base: `#08090e` (Deep Obsidian)
  * Surface Elevated: `#0f1118` (Elevation 1)
  * Surface Card: `#151824` (Elevation 2)
  * Surface Active: `#1c2132` (Elevation 3)
  * Borders / Dividers: `rgba(255, 255, 255, 0.08)`
* **Brand Accents:**
  * Primary Violet: `#8b5cf6` (Brand 500), `#7c3aed` (Brand 600)
  * Indigo Glow: `#6366f1`
* **Semantic States:**
  * **Success:** Text `#34d399` (Emerald 400), Surface `rgba(52, 211, 153, 0.1)`, Border `rgba(52, 211, 153, 0.2)`
  * **Warning:** Text `#fbbf24` (Amber 400), Surface `rgba(251, 191, 36, 0.1)`, Border `rgba(251, 191, 36, 0.2)`
  * **Destructive/Error:** Text `#f87171` (Rose 400), Surface `rgba(248, 113, 113, 0.1)`, Border `rgba(248, 113, 113, 0.2)`
  * **Info/Type:** Text `#60a5fa` (Blue 400), Surface `rgba(96, 165, 250, 0.1)`

*Contrast Verification:* All text tokens on dark surfaces exceed **4.5:1** contrast ratio (WCAG AA) with large headings exceeding **7:1** (WCAG AAA).

### 4.3 Spacing & Layout Grid
* 8-point base grid: `4px (0.5)`, `8px (1)`, `12px (1.5)`, `16px (2)`, `24px (3)`, `32px (4)`.
* Responsive Container: Max width `1440px` with fluid 24px margins.

---

## 5. Interaction Design & Motion

* **Transitions:**
  * Fast Hover States: `150ms ease-out`
  * Modal & Drawer Slides: `200ms cubic-bezier(0.16, 1, 0.3, 1)`
  * Code Tab Cross-Fades: `120ms linear`
* **Micro-Interactions:**
  * Copy-to-clipboard button replaces icon with a checkmark and green pill for 1.8 seconds.
  * Live status pill pulses gently when live simulation executes.
  * Dropzone highlights with a subtle violet glow and border dash acceleration on file drag-over.
* **Reduced Motion:** Fully adheres to `@media (prefers-reduced-motion: reduce)` by substituting instant opacity swaps for position translates.

---

## 6. Accessibility & Responsive Implementation

* **Keyboard Navigation:**
  * Full tab stop order across dropzone, editor, configuration toggles, method selectors, and tab triggers.
  * Visible focus rings: `focus-visible:ring-2 focus-visible:ring-brand-500 focus-visible:ring-offset-2 focus-visible:ring-offset-dark-900`.
  * Keyboard Shortcuts:
    * `⌘+Enter` / `Ctrl+Enter`: Send live request.
    * `⌘+S` / `Ctrl+S`: Download project .zip.
    * `Esc`: Close open modals or overlays.
* **Screen Reader Support:**
  * All interactive elements have descriptive `aria-label`, `aria-live` regions for live request outcomes, and `role="tab"` / `role="tabpanel"` semantics.
