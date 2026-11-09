# Datalogue backend

FastAPI backend for Datalogue.

## Endpoints

| Method | Path | Purpose |
|--------|------|---------|
| `GET` | `/health` | Health check |
| `POST` | `/upload` | Upload a CSV/Excel file; sets the active dataset |
| `GET` | `/datasets` | List previously uploaded datasets (for presentation generation) |
| `GET` | `/kpis` | Dataset-level and per-column KPI statistics |
| `GET` | `/charts` | Recommended chart configurations |
| `GET` | `/dashboard` | Unified dashboard payload (KPIs, main chart, secondary charts, table) |
| `GET` | `/summary` | Business summary for the active dataset |
| `POST` | `/query` | Natural language question about the active dataset |
| `POST` | `/presentations/generate` | Start generating an editable `.pptx` deck |
| `GET` | `/presentations/jobs/{job_id}` | Poll generation progress |
| `POST` | `/presentations/jobs/{job_id}/edit` | Apply the requester's live edits and re-render the deck |
| `GET` | `/presentations/download/{filename}` | Download a generated `.pptx` |

### `POST /presentations/generate`

Accepts either a direct file upload, a previously uploaded SQLite-backed dataset id, or
falls back to the currently active in-memory dataset.

```bash
# from a file
curl -X POST http://localhost:8000/presentations/generate \
  -F "file=@sales.csv"

# from a previously uploaded dataset
curl -X POST http://localhost:8000/presentations/generate \
  -F "dataset_id=0bef146023704edf91909b14f502d050"
```

The `dataset_id` may be sent as a multipart form field or as a query
parameter.

Uploaded CSV and Excel bytes are stored in `data/workbooks/workbooks.db` in the
`file_data` BLOB column. Generated PPTX bytes and their structured plans are
stored in `data/presentations/presentations.db`; temporary files are created only while
parsing or rendering. The `data/uploads/` and `data/presentations/`
directories are no longer used for new durable artifacts.

Generation runs in a background thread so the client can poll for real
progress. The response starts the job:

```json
{
  "job_id": "3d79ee724e2c400ab5934efdf882fa26",
  "status": "running",
  "stage": "reading_spreadsheet",
  "message": "Reading spreadsheet",
  "stages": [
    "reading_spreadsheet",
    "detecting_columns",
    "analyzing_data",
    "writing_narrative",
    "generating_slides",
    "preparing_powerpoint"
  ]
}
```

Poll `GET /presentations/jobs/{job_id}` until `status` is `completed` or
`failed`:

```json
{
  "job_id": "3d79ee724e2c400ab5934efdf882fa26",
  "stage": "completed",
  "status": "completed",
  "stage_history": ["reading_spreadsheet", "detecting_columns", "..."],
  "filename": "sales_a1b2c3d4.pptx",
  "download_url": "/presentations/download/sales_a1b2c3d4.pptx",
  "deck": {
    "title": "Sales & Operations Overview",
    "slide_count": 7,
    "slides": [ { "index": 1, "type": "title", "title": "..." } ]
  }
}
```

The `deck` object is a JSON description of every slide. The backend renders
the exact same plan into the `.pptx`, so the frontend preview is a faithful
representation of the downloaded file.

## The deck agent

The deck's *structure* — which slides exist, what the charts plot, which
numbers the KPI tiles carry — is computed deterministically from the dataset
by `src/presentation/presentation_generator.py`.

The *narrative* (the title-slide highlight box, the executive summary
sections, the trend caption, the empirical observations and the recommended
actions) is written by `src/presentation/deck_agent.py`, which asks the configured LLM to
interpret the data.

### The dataset document

The spreadsheet is never sent to the model. It is first converted into a
compact **JSON document** by `src/presentation/dataset_document.py`:

```json
{
  "dataset": { "row_count": 1200, "column_count": 12, "columns": ["..."] },
  "key_roles": { "date": "order_date", "measure": "revenue" },
  "column_profiles": {
    "revenue": { "dtype": "float64", "non_null": 1200, "missing": 0,
                 "min": 12.5, "max": 900.0, "mean": 143.2, "sum": 171840.0 },
    "status":  { "dtype": "object", "distinct": 3,
                 "most_common": [{ "value": "Delivered", "count": 1042 }] }
  },
  "sample_rows": [ { "order_id": "ORD-001", "revenue": 120.5 } ],
  "sample_note": "The first 40 of 1200 rows. ..."
}
```

So the model reads the actual records — not only pre-digested aggregates —
while the request stays small. The document is capped at 60,000 characters;
if the sample pushes past that, rows are dropped until it fits, and the note
says so. `document_to_text()` renders the same document as a plain-text
table, which is useful for models that read tables better than JSON.

### Validation

The agent is given the document, the schema, the computed KPIs and a set of
computed findings, and is instructed to use only those numbers. Its answer
is then validated before it is used:

- the JSON must parse, and carry real content
- every figure it cites must already appear in the data it was given
  (rounding and K/M re-scaling are tolerated; a figure with no counterpart in
  the data is not)

Anything that fails validation is dropped, and the deterministic template
text is used for that slide instead. The agent is therefore a bonus, never a
blocker: **without a configured provider the deck is still produced in full,
from the templates.**

One deck build makes **one** provider request, so the document does not
change how many requests a day are spent — it changes what the model sees.

The provider is OpenRouter's OpenAI-compatible API, configured in `.env`:

```
OPENROUTER_BASE_URL=https://openrouter.ai/api/v1
OPENROUTER_API_KEY=...
OPENROUTER_MODEL=nvidia/nemotron-3-ultra-550b-a55b:free

# Google AI Studio (preferred when LLM_PROVIDER=gemini)
LLM_PROVIDER=gemini
GEMINI_API_KEY=...
GEMINI_MODEL=gemini-2.5-flash-lite
```

`src/core/llm.py` reads those three settings. The base URL and model fall back to
sensible defaults (OpenRouter's public endpoint, `openai/gpt-4o-mini`), and if
the variables are spelled differently the `.env` file is scanned and the
OpenRouter variables are recognised by name.

Two details of the request matter:

- **`max_tokens` is always set.** OpenRouter reserves the model's entire
  context window against the account's credit balance when no cap is given,
  and rejects the request when the balance cannot cover it. The deck agent
  caps the reply at 3,000 tokens, which is ample for the narrative.
- **Retries are disabled** (`max_retries=0`). The SDK retries a 429 twice by
  default, so one failed call would spend three of the daily free-model
  requests instead of one. A quota that is exhausted for the day will not
  clear inside the SDK's backoff window, so the retries are pure waste.

When the provider refuses a request, the failure is recorded rather than
swallowed: the deck plan carries `narrative_source` (`"agent"` or
`"template"`) and, when the agent could not be used, `narrative_error`.

### Regenerating with the requester's suggestions

`POST /presentations/generate` accepts an optional `suggestions` field. The
text is the requester's own instructions about narrative or slide structure.
The slide planner can reorder or omit existing slides and add grounded chart
slides using exact dataset columns:

```bash
curl -X POST http://localhost:8000/presentations/generate \
  -F "suggestions=Add a slide comparing Sales by Region and lead with Furniture."
```

The backend still computes every chart value and KPI from the data. The model
can choose structure and request an analysis, but a requested column is
validated against the detected schema before it is rendered. Send the current
deck plan as `current_deck` when regenerating an existing deck so the planner
can preserve, remove, reorder or extend it. The text is trimmed and bounded
at 2,000 characters.

### Editing a deck directly

`POST /presentations/jobs/{job_id}/edit` applies the requester's own changes
to a generated deck and re-renders it:

```bash
curl -X POST http://localhost:8000/presentations/jobs/{job_id}/edit \
  -H "Content-Type: application/json" \
  -d '{"edits": [{"slide": 1, "field": "banner_text", "value": "A new highlight."}]}'
```

Each edit names a slide by its number and a field by its name. The response
carries the edited deck, the edits that were applied, and the edits that were
rejected (each with a reason).

Only the *narrative* fields are editable — `src/presentation/deck_editor.py` holds the
map:

| Slide type | Editable fields |
|------------|-----------------|
| `title` | `title`, `subtitle`, `banner_label`, `banner_text` |
| `summary` | `title`, `category`, `findings` |
| `chart` | `title`, `category`, `caption` |
| `insights` | `title`, `category`, `insights`, `recommendations` |

The slide structure, the chart data, the categories and the KPI tiles are
computed from the dataset, so an edit that tries to touch one of them is
rejected rather than silently applied. The edited plan is written to a new
`.pptx`, so the export always matches what is on screen and the original deck
stays downloadable.

The edits are applied to the deck as it was *first* generated, which makes
the operation repeatable: sending the same edit twice gives the same result.

To build a deck without calling the LLM at all:

```python
generate_presentation_with_plan(df, output_path, use_agent=False)
```

## Running

```bash
pip install -r requirements.txt
uvicorn app:app --reload
```

Generated presentations are written to `data/presentations/`.

## Tests

```bash
.venv/bin/python3 tests/test_presentation_integration.py
.venv/bin/python3 tests/test_deck_agent.py
.venv/bin/python3 tests/test_dataset_document.py
.venv/bin/python3 tests/test_deck_editor.py
.venv/bin/python3 tests/test_llm_provider.py
```

`test_presentation_integration.py` covers the upload pipeline, dashboard
endpoints, presentation generation (file / `dataset_id` / active session),
job progress, PPTX validity, download, error handling and chart variety
across datasets.

`test_deck_agent.py` covers the deck agent: the prompt it sends (including
the dataset document), how it parses and validates the response, how
invented figures are detected and dropped, and how the deck plan falls back
to the templates when the agent is unavailable.

`test_dataset_document.py` covers the document that is sent to the model: its
shape, the column profiles, the sample rows, the size cap and the trimming.

`test_llm_provider.py` covers the OpenRouter client: that Gemini is gone,
that the model and prompt are sent correctly, and how configuration and
provider failures are surfaced.

`test_deck_editor.py` covers the live editor: which fields of which slide
type may be edited, that the data-derived fields are rejected, that the text
is bounded, that the plan is never mutated, and that an edited plan renders
to a real `.pptx` carrying the new text.
