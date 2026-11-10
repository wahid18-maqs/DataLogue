# Datalogue

Turn spreadsheets into client-ready presentations, through conversation.

## Overview

Datalogue is a full-stack application for uploading CSV and Excel workbooks,
understanding their structure, exploring calculated insights, asking questions
in natural language, and generating editable PowerPoint presentations.

The application combines deterministic data processing with optional AI
narrative generation. Numbers, chart values, and KPIs are calculated from the
uploaded data; the language model is used for grounded interpretation and
narrative, with deterministic templates available as a fallback.

## Features

- Upload CSV, XLSX, and XLS workbooks.
- Detect headers, column types, dates, numeric values, and categorical data.
- Process multi-sheet workbooks with sheet classification and skip reasons.
- Report `parsed`, `partially_parsed`, and `needs_attention` workbook states.
- Recalculate spreadsheet formulas when LibreOffice is available.
- Display KPIs, charts, summaries, and recent records in the dashboard.
- Render the Recent Activity table with consistent columns, sorting, page sizes
  of 10/25/50 rows, pagination, sticky headers, and dynamic number/date
  formatting.
- Ask natural-language questions about an uploaded workbook.
- Generate editable PowerPoint decks with:
  - AI-assisted narrative
  - Native PowerPoint charts
  - KPI and summary slides
  - Configurable theme and slide detail
  - Progress reporting and browser preview
- Regenerate decks from conversational feedback.
- Add, remove, reorder, and revise slides through regeneration prompts.
- Edit supported slide text directly before exporting.
- Persist generated decks by workbook, including the selected sheet, generation
  settings, feedback history, timestamps, and stale status when workbook data
  is replaced.
- Restore the saved deck and regeneration history when returning to the
  Overview dashboard.
- Persist uploaded file records in `data/uploads/uploads.db`.
- Persist workbook metadata and source bytes in `data/workbooks/workbooks.db`.
- Persist generated PowerPoint files and plans in
  `data/presentations/presentations.db`.
- Support light and dark application themes.

## Tech Stack

### Backend

- Python 3.12
- FastAPI
- Uvicorn
- pandas and NumPy
- openpyxl
- python-pptx
- SQLite
- OpenAI-compatible LLM client

### Frontend

- React 18
- Vite
- Tailwind CSS
- Recharts
- Axios

## Working

<img width="1902" height="911" alt="datalogue-dashboard" src="https://github.com/user-attachments/assets/83414186-af5e-4394-94ce-2de1d9170f21" />


https://github.com/user-attachments/assets/87a05bf4-15e0-4ae7-9a81-63fcbb6b57bc


## Architecture

```text
CSV / Excel upload
        |
        v
Ingestion and workbook processing
        |
        +--> schema, classifications, findings, cached data
        |
        v
Dashboard and AI Assistant
        |
        v
Grounded presentation planner
        |
        v
Validated deck plan
        |
        v
Editable PPTX renderer
```

The backend separates responsibilities by package:

- `ingestion` reads files, detects headers, classifies sheets, and computes
  workbook metadata.
- `workbook` owns workbook persistence, lifecycle, and dataframe caching.
- `presentation` plans, renders, edits, and stores PowerPoint artifacts.
- `assistant` handles natural-language questions and sandboxed pandas plans.
- `core` contains shared LLM and utility code.

AI-generated content is validated against computed dataset information. The
backend remains responsible for calculating values and rendering charts, so
the model cannot silently invent chart data.

## Project Structure

```text
Datalogue/
├── backend/
│   ├── app.py
│   ├── requirements.txt
│   ├── README.md
│   ├── src/
│   │   ├── assistant/
│   │   ├── core/
│   │   ├── ingestion/
│   │   ├── presentation/
│   │   └── workbook/
│   └── tests/
├── frontend/
│   ├── package.json
│   ├── src/
│   └── README.md
├── data/
│   ├── init_databases.sql
│   ├── uploads/
│   │   └── uploads.db
│   ├── workbooks/
│   │   └── workbooks.db
│   └── presentations/
│       └── presentations.db
├── run.txt
└── README.md
```

Database files are generated at runtime and should not be committed.
Use `data/init_databases.sql` to initialize all three SQLite databases.

## Getting Started

### Prerequisites

- Python 3.12 or compatible Python 3.10+.
- Node.js 20+ and npm.
- LibreOffice is optional. Install it to recalculate cached spreadsheet
  formulas before ingestion:

  ```bash
  sudo apt install libreoffice
  ```

### Installation

Clone or open the project, then install the backend dependencies:

```bash
cd /home/wahid/DataLogue/backend
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
```

Install frontend dependencies:

```bash
cd /home/wahid/DataLogue/frontend
npm install
```

### Environment Variables

Create `backend/.env` for optional AI-generated narrative:

```dotenv
# Google AI Studio through the OpenAI-compatible client
LLM_PROVIDER=gemini
GEMINI_API_KEY=your_api_key
GEMINI_MODEL=gemini-2.5-flash-lite
```

OpenRouter is also supported:

```dotenv
LLM_PROVIDER=openrouter
OPENROUTER_BASE_URL=https://openrouter.ai/api/v1
OPENROUTER_API_KEY=your_api_key
OPENROUTER_MODEL=your_model
```

If no valid provider or API key is configured, Datalogue still generates decks
using deterministic narrative templates. Never commit API keys or other
secrets to the repository.

### Run Locally

Start the backend:

```bash
cd /home/wahid/DataLogue/backend
.venv/bin/python -m uvicorn app:app --reload --port 8000
```

The backend is available at:

- API: <http://localhost:8000>
- Swagger UI: <http://localhost:8000/docs>
- Health check: <http://localhost:8000/health>

In a second terminal, start the frontend:

```bash
cd /home/wahid/DataLogue/frontend
npm run dev
```

Open the Vite URL shown in the terminal, usually
<http://localhost:5173>.

For a production frontend build:

```bash
cd /home/wahid/DataLogue/frontend
npm run build
```

For backend checks:

```bash
cd /home/wahid/DataLogue/backend
.venv/bin/python -m compileall -q app.py src tests
.venv/bin/python tests/test_workbooks.py
.venv/bin/python tests/test_workbook_api.py
.venv/bin/python tests/test_ingestion_features.py
```
