# datapi — Official Brand Identity & Design System

> "Raw data in. Production APIs out."

This document details the visual identity, design tokens, logo rules, and typography for **datapi** (derived from the official `docs/brand-kit.html`).

---

## 1. Identity & Wordmark

- **Company & Tool Name**: `datapi`
- **Casing**: Strictly lowercase (**datapi**). Never capitalize as "Datapi", "DataPI", or "DataApi".
- **Typography**: Space Grotesk Bold (`font-weight: 700`), tight tracking (`letter-spacing: -0.02em` / `-2px`).
- **Tagline**: *"Raw data in. Production APIs out."*
- **Positioning**: The autonomous schema-to-API engine that turns raw data files into containerized microservices, type-safe SDKs, and self-healing pull requests in sub-50ms.

---

## 2. The Mark: "The Flow D"

The logo mark is a geometric capital **D** drawn as a single pipeline:
- **Pipeline Stem & Bowl**: Signal Blue (`#2F6BFF`)
  - Stem: `width: 52px`, `height: 288px`, `rx: 26px`
  - Bowl Stroke: `stroke-width: 52px`, round linecap
- **The Nodes**: Two Pulse Mint (`#3DDC97`) circles with Inkwell outline (`#0A0F1E`, stroke-width: 10px) riding the curve at `(340, 196)` and `(340, 316)`.
- **Meaning**: Data packets flowing through the pipeline. Mint means live data in motion.

### Clearspace Rule
Clearspace is **one node diameter** on all sides. Nothing enters it — no type, no rules, no other marks.

---

## 3. Color Palette & Design Tokens

| Token | Hex Value | Role / Usage |
|---|---|---|
| `--inkwell` | `#0A0F1E` | Primary deep surface, terminal background, icon tiles |
| `--inkwell-deep`| `#060A15` | Canvas background, activity bar, editor gutter |
| `--panel` | `#0E1528` | Window titlebar, panels, active tabs, dropdown menus |
| `--panel-2` | `#111A30` | Hover states, elevated cards, interactive containers |
| `--line` | `#1E2A45` | Structural borders, splitters, dividers |
| `--signal` | `#2F6BFF` | Primary brand accent, primary CTA, active tab indicator |
| `--signal-soft`| `#6E97FF` | Links, secondary accents, hover highlights |
| `--mint` | `#3DDC97` | Live agent status, success states, data nodes, 200 OK |
| `--paper` | `#F5F7FA` | Inverted surfaces, contrast documentation |
| `--slate` | `#5A6478` | Muted labels, line numbers, inactive controls |
| `--slate-light`| `#93A0B8` | Secondary body text, timestamps, breadcrumb paths |
| `--text` | `#E9EDF5` | High-contrast body text, headings, code editor text |
| `--danger` | `#FF5C5C` | Error toasts, breaking schema diff badges, 500 status |

---

## 4. Typography Scale

- **Display & Headings**: `Space Grotesk` (500, 600, 700)
- **Body & UI**: `Inter`, `-apple-system`, `system-ui`, sans-serif (400, 500, 600)
- **Code & Numbers**: `JetBrains Mono`, `ui-monospace`, `SF Mono`, Menlo, monospace

---

## 5. Asset Files

- `datapi/studio/assets/datapi-mark.svg` — The Flow D mark
- `datapi/studio/assets/datapi-logo.svg` — Horizontal lockup with wordmark
- `datapi/studio/assets/datapi-favicon.svg` — Browser favicon
- `datapi/studio/assets/datapi-app-icon.svg` — 512x512 rounded tile icon
- `docs/brand-kit.html` — Interactive brand kit presentation with one-click downloads
