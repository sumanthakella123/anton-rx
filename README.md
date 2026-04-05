# Anton Rx — Medical Benefit Drug Policy Tracker

> **Innovation Hacks 2.0 · April 2026 · Arizona State University**

An AI-powered system that ingests, parses, and normalizes medical benefit drug policy documents from multiple health plans, and exposes them through a natural-language chat interface that lets analysts instantly answer coverage questions, compare payers side-by-side, and track policy changes — all without opening a single PDF.

---

## The Problem

Health plans govern medical benefit drug coverage through individual policy documents that:
- Are published in different formats (PDFs, portals, mega-documents) by every payer
- Differ in terminology, structure, and clinical criteria across plans
- Change frequently with little notice

Analysts today read PDFs one at a time, manually extract data, and try to mentally normalize information across plans. It is slow, expensive, and error-prone.

---

## What We Built

A two-part system:

### 1. Ingestion Pipeline (`anton-rx-backend/`)

A Python pipeline that takes raw policy PDFs and produces a structured, normalized SQLite database:

```
PDF  →  pdfplumber  →  Gemini multi-stage extraction  →  SQLite
```

**Four extraction stages powered by Gemini:**
1. **Discovery** — Identify the payer, drug name, drug category, and document type
2. **Page Map** — Locate which pages contain coverage criteria, step therapy, prior auth
3. **Extraction** — Pull 20+ structured fields per drug policy (coverage status, PA criteria, step therapy, HCPCS codes, ICD-10 codes, indications, site-of-care restrictions, and more)
4. **Validation** — Score extraction confidence, flag anomalies, optionally retry low-confidence fields

A SHA-256 hash on every document prevents duplicate ingestion.

### 2. Chat Interface (`anton-rx-chat/`)

A Next.js chat application backed by Gemini 2.5 Flash with four server-side tools wired to the SQLite database:

| Tool | What it does |
|---|---|
| `search_drug_policy` | Look up a single drug across all payers |
| `compare_drug_between_payers` | Side-by-side comparison table for a drug across plans |
| `get_available_payers` | List all health plans currently in the database |
| `get_policy_changes` | Surface policy change logs and review summaries |

The comparison tool renders an **interactive table** directly in the chat — not raw text — so analysts can instantly see differences between payers without reading through an LLM response.

---

## Key Features

- **Natural language Q&A** — "Does Cigna cover Botox for migraines? What are the PA criteria?"
- **Cross-payer comparison table** — rendered as a first-class UI component with Export CSV
- **Change tracking** — query the policy change log by payer or keyword
- **Multi-thread chat** — conversations persist in the browser (IndexedDB), with a sidebar to switch between sessions
- **FTS5 + indexed SQLite** — fast search on drug names, categories, and criteria across the entire corpus
- **Generic name matching** — searching by INN/generic name finds policies that only mention the brand name, and vice versa

---

## Tech Stack

| Layer | Technology |
|---|---|
| PDF parsing | `pdfplumber` |
| AI extraction | Google Gemini (`google-genai`) |
| Database | SQLite + FTS5 (`better-sqlite3` for reads) |
| Frontend framework | Next.js 16 (App Router) |
| Chat UI | `@assistant-ui/react` + `@ai-sdk/react` |
| AI chat model | Gemini 2.5 Flash via `@ai-sdk/google` |
| Chat persistence | Browser IndexedDB (`idb`) |
| Styling | Tailwind CSS v4, shadcn/ui components |

---

## Project Structure

```
hackathon/
├── README.md
├── .gitignore
│
├── anton-rx-backend/          # Ingestion pipeline (Python)
│   ├── main.py                # CLI entry point
│   ├── dashboard.py           # Streamlit inspection UI
│   ├── migrate_indexes.py     # One-shot DB migration (FTS5 + indexes)
│   ├── requirements.txt
│   ├── .env.example
│   └── anton_rx/
│       ├── database.py        # Schema, inserts, FTS5
│       ├── orchestrator.py    # Full pipeline orchestration
│       ├── pdf_parser.py      # pdfplumber + SHA-256 hash
│       ├── stage_discovery.py
│       ├── stage_extraction.py
│       ├── stage_pagemap.py
│       ├── stage_validation.py
│       └── stage_changelog.py
│
└── anton-rx-chat/             # Chat interface (Next.js)
    ├── .env.example
    ├── data/                  # Place anton_rx.db here for deployment
    ├── app/
    │   ├── page.tsx
    │   ├── layout.tsx
    │   ├── assistant.tsx      # Main assistant component + thread management
    │   └── api/chat/route.ts  # Streaming API route with tool definitions
    ├── components/
    │   └── assistant-ui/
    │       ├── thread.tsx
    │       ├── thread-list.tsx
    │       ├── comparison-table.tsx   # Interactive cross-payer table + CSV export
    │       └── ...
    └── lib/
        ├── chat-db.ts         # IndexedDB thread storage
        └── chat-store.ts      # Zustand store for thread management
```

---

## Local Setup

### Prerequisites
- Node.js 20+
- Python 3.11+
- A Google AI API key — [get one free at Google AI Studio](https://aistudio.google.com/app/apikey)

### 1. Clone and install

```bash
git clone https://github.com/YOUR_USERNAME/anton-rx.git
cd anton-rx
```

### 2. Backend — run the ingestion pipeline

```bash
cd anton-rx-backend

# Create and activate a virtual environment
python -m venv .venv
.venv\Scripts\activate          # Windows
# source .venv/bin/activate     # macOS/Linux

# Install dependencies
pip install -r requirements.txt
pip install python-dotenv streamlit pandas   # not in requirements.txt

# Set your API key
cp .env.example .env
# Edit .env and add your GOOGLE_API_KEY

# Ingest a folder of policy PDFs
python main.py --dir path/to/your/pdfs

# (Optional) Apply FTS5 indexes to an existing database
python migrate_indexes.py

# (Optional) Browse the database with the Streamlit dashboard
streamlit run dashboard.py
```

The pipeline creates `anton-rx-backend/anton_rx.db`.

### 3. Frontend — run the chat interface

```bash
cd ../anton-rx-chat

npm install

# Set your API key
cp .env.example .env.local
# Edit .env.local and add your GOOGLE_GENERATIVE_AI_API_KEY
# Leave DB_PATH commented out — local dev uses ../anton-rx-backend/anton_rx.db

npm run dev
# Open http://localhost:3000
```

---

## Deploying to Railway (Recommended)

Railway supports Node.js + persistent file storage, which makes it ideal for this SQLite-backed app.

### Step 1 — Prepare the database file

After running the ingestion pipeline locally, copy the generated database into the frontend project:

```bash
# From the repo root
cp anton-rx-backend/anton_rx.db anton-rx-chat/data/anton_rx.db
```

Commit it (it is a read-only pre-populated dataset, safe to commit for a demo):

```bash
git add anton-rx-chat/data/anton_rx.db
git commit -m "add pre-populated policy database"
```

### Step 2 — Push to GitHub

```bash
git remote add origin https://github.com/YOUR_USERNAME/anton-rx.git
git push -u origin master
```

### Step 3 — Deploy on Railway

1. Go to [railway.app](https://railway.app) → **New Project** → **Deploy from GitHub repo**
2. Select your repository
3. Set **Root Directory** to `anton-rx-chat`
4. Railway auto-detects Next.js and sets the build command to `npm run build`
5. Under **Variables**, add:

```
GOOGLE_GENERATIVE_AI_API_KEY = your_key_here
DB_PATH                      = data/anton_rx.db
```

6. Click **Deploy** — Railway gives you a public URL in ~2 minutes.

### Alternative: Vercel

Vercel works identically for the Next.js frontend. After committing the DB file:

```bash
npm install -g vercel
cd anton-rx-chat
vercel --prod
```

Set the same two environment variables in the Vercel dashboard.

---

## Environment Variables

### `anton-rx-backend/.env`

| Variable | Required | Description |
|---|---|---|
| `GOOGLE_API_KEY` | Yes | Google AI API key for Gemini extraction |

### `anton-rx-chat/.env.local`

| Variable | Required | Description |
|---|---|---|
| `GOOGLE_GENERATIVE_AI_API_KEY` | Yes | Google AI API key for Gemini chat model |
| `DB_PATH` | No | Path to SQLite DB relative to project root. Omit for local dev; set to `data/anton_rx.db` for deployment. |

---

## Project Write-Up

### What we built and why

Anton Rx's core business involves advising health plans on drug cost strategy — which means analysts need to know, across dozens of payers, which medical benefit drugs are covered, under what criteria, and what changed recently. Today that work is done manually: open PDF, find the relevant section, repeat for every payer, try to mentally normalize information that was written in completely different formats by completely different teams.

We built an end-to-end AI system to automate that workflow.

The backend pipeline is a multi-stage Gemini extraction system. Rather than sending a full PDF to the model and hoping for a structured response, we break the task into focused stages: first identify what the document is about, then map which pages contain which types of criteria, then extract fields one section at a time, then validate the output and flag low-confidence extractions for review. This staged approach produces significantly more reliable structured output than a single-pass prompt, and the SHA-256 dedup check means the same document is never processed twice.

The frontend is a streaming chat interface that sits on top of a SQLite database of normalized policy records. The key design decision was to make comparison a first-class UI concern rather than an LLM output: when the model calls the `compare_drug_between_payers` tool, the result is rendered as an interactive table component — not narrated in text. This directly addresses the problem statement's ask for "a clean comparison view where a non-technical person can immediately see the differences between payers without reading raw policy text."

We also added FTS5 full-text search and B-tree indexes so queries against the database stay fast as the corpus grows, generic name matching so searches on INNs find policies that only cite brand names, and a CSV export on the comparison table so analysts can drop results directly into client reports.

---

## Team

Built at **Innovation Hacks 2.0 · Arizona State University · April 2026**
