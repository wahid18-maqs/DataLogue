import json
import logging
import threading
import tempfile
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import pandas as pd
from fastapi import FastAPI, File, Form, HTTPException, Query, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response
from pydantic import BaseModel
from plotly.utils import PlotlyJSONEncoder

from src.presentation.chart_generator import generate_charts
from src.ingestion.csv_loader import CorruptedCSVError, EmptyCSVError, load_csv
from src.presentation.deck_editor import DeckEditError, apply_deck_edits
from src.presentation.kpi_generator import generate_kpis
from src.presentation.presentation_generator import (
    GENERATION_STAGES,
    generate_presentation_with_plan,
    load_deck_plan,
    normalize_detail_level,
    normalize_theme,
    render_plan_to_pptx,
)
from src.assistant.query_engine import answer_question
from src.assistant.query_guardrails import GuardrailError
from src.ingestion.schema_detector import detect_schema
from src.presentation.summary_generator import generate_summary
from src.core.utils import (
    ensure_upload_dir,
    generate_unique_filename,
    sanitize_filename,
    validate_csv_extension,
)
from src.workbook.workbook_cache import WorkbookCache
from src.ingestion.workbook_processor import SheetError, process_workbook
from src.workbook.workbook_service import WorkbookNotFound, WorkbookService
from src.workbook.workbook_store import WorkbookStore
from src.presentation.presentation_store import PresentationStore

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
)
logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = PROJECT_ROOT / "data"
BASE_DIR = PROJECT_ROOT / "backend"
PRESENTATIONS_DIR = DATA_DIR / "presentations"
WORKBOOK_DB_PATH = DATA_DIR / "workbooks" / "workbooks.db"
PRESENTATIONS_DB_PATH = DATA_DIR / "presentations" / "presentations.db"

# Longest suggestion text the deck agent will accept. The suggestions are
# the requester's own words and end up in a prompt, so the length is bounded.
MAX_SUGGESTION_CHARS = 2000

app = FastAPI(
    title="Datalogue API",
    description="Backend API for uploading spreadsheets and turning them into presentations.",
    version="0.1.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# In-memory application state holding the most recently uploaded dataset.
# A single-dataset session is sufficient for this assessment's scope.
app.state.current_dataframe = None
app.state.current_filename = None
app.state.current_workbook_id = None

# In-memory registry of presentation generation jobs, used to report genuine
# pipeline progress to the client while a deck is being built.
app.state.presentation_jobs = {}

# The workbook service: the metadata store (SQLite, on disk), the parsed
# dataframe cache (in memory) and the processing pipeline that fills them.
app.state.workbook_store = None
app.state.workbook_cache = None
app.state.workbooks = None
app.state.presentations = None


def _store_rendered_presentation(
    output_path: Path, filename: str, plan: dict
) -> None:
    """Persist a rendered temporary PPTX and its plan in presentations.db."""
    if app.state.presentations is None:
        app.state.presentations = PresentationStore(PRESENTATIONS_DB_PATH)
        imported = app.state.presentations.import_legacy_directory(PRESENTATIONS_DIR)
        if imported:
            logger.info("Imported %d legacy presentation artifact(s) into the database.", imported)
    try:
        app.state.presentations.save(filename, output_path.read_bytes(), plan)
    finally:
        output_path.unlink(missing_ok=True)
        output_path.with_suffix(".plan.json").unlink(missing_ok=True)


class PresentationJob:
    """Tracks the progress of a single presentation generation request."""

    def __init__(self, job_id: str) -> None:
        self.job_id = job_id
        self.stage = "queued"
        self.message = "Queued"
        self.status = "running"
        self.error: Optional[str] = None
        self.filename: Optional[str] = None
        self.download_url: Optional[str] = None
        self.deck: Optional[dict] = None
        # The plan as it was first generated. Live edits are always applied to
        # this baseline, so a client that sends the same edit twice gets the
        # same result.
        self.base_deck: Optional[dict] = None
        # Full history of the stages this job passed through, so a client that
        # polls infrequently still sees the complete pipeline.
        self.stage_history: list[str] = []

    def update(self, stage: str, message: str) -> None:
        """Record the current pipeline stage."""
        self.stage = stage
        self.message = message
        if not self.stage_history or self.stage_history[-1] != stage:
            self.stage_history.append(stage)

    def to_dict(self) -> dict:
        """Serialise the job state for the client."""
        return {
            "job_id": self.job_id,
            "stage": self.stage,
            "message": self.message,
            "status": self.status,
            "error": self.error,
            "filename": self.filename,
            "download_url": self.download_url,
            "deck": self.deck,
            "stage_history": list(self.stage_history),
        }


class DeckEditRequest(BaseModel):
    """Body for ``POST /presentations/jobs/{job_id}/edit``."""

    # The edits to apply: [{"slide": 2, "field": "caption", "value": "..."}].
    edits: list[dict] = []


class QueryRequest(BaseModel):
    """Request body for POST /query."""

    question: str


@app.on_event("startup")
def on_startup() -> None:
    """Ensure required directories exist on application startup."""
    ensure_upload_dir(PRESENTATIONS_DIR)
    logger.info("Uploaded files are stored in SQLite at %s", WORKBOOK_DB_PATH)
    logger.info("Presentation artifacts are stored in SQLite at %s", PRESENTATIONS_DB_PATH)

    # The workbook store is on disk, so it survives a restart. The parsed
    # dataframe cache is in memory, so it does not: every workbook that was
    # parsed is marked stale, and is re-parsed the next time it is used.
    app.state.workbook_store = WorkbookStore(WORKBOOK_DB_PATH)
    app.state.workbook_cache = WorkbookCache()
    app.state.workbooks = WorkbookService(
        app.state.workbook_store, app.state.workbook_cache
    )
    app.state.presentations = PresentationStore(PRESENTATIONS_DB_PATH)
    stale = app.state.workbooks.mark_stale()
    logger.info(
        "Workbook store ready at %s (%d workbook(s) marked stale).",
        WORKBOOK_DB_PATH,
        stale,
    )


def _get_current_dataframe() -> pd.DataFrame:
    """
    Return the currently loaded dataset, or raise HTTP 400 if none has
    been uploaded yet.
    """
    dataframe = app.state.current_dataframe
    if dataframe is None:
        raise HTTPException(
            status_code=400,
            detail="No CSV file has been uploaded yet. Please upload a CSV via /upload first.",
        )
    return dataframe


def _get_workbook_query_frame(
    workbook_id: str, include_source_sheet: bool = True
) -> pd.DataFrame:
    """Combine every parsed workbook sheet for whole-file consumers."""
    workbook = app.state.workbooks.get(workbook_id)
    if workbook is None:
        raise WorkbookNotFound(f"No workbook with id '{workbook_id}'.")

    frames = []
    for sheet in workbook.get("sheets", []):
        if sheet.get("status") != "parsed":
            continue
        frame = app.state.workbooks.get_frame(workbook_id, sheet["id"]).copy()
        if include_source_sheet:
            frame["__source_sheet"] = sheet.get("name") or sheet["id"]
        frames.append(frame)

    if not frames:
        raise ValueError("This workbook has no parsed sheets to query.")
    return pd.concat(frames, ignore_index=True, sort=False)


def _get_current_dashboard_dataframe() -> pd.DataFrame:
    """Return all parsed sheets for dashboard-wide workbook rendering."""
    if app.state.workbooks is not None:
        workbook_id = app.state.current_workbook_id
        if workbook_id and app.state.workbooks.get(workbook_id) is None:
            workbook_id = None
        if workbook_id is None:
            stored = next(
                (
                    workbook
                    for workbook in app.state.workbook_store.list_workbooks()
                    if workbook.get("status") in {"parsed", "partially_parsed"}
                ),
                None,
            )
            if stored:
                workbook_id = stored["id"]
                app.state.current_workbook_id = workbook_id
        if workbook_id:
            return _get_workbook_query_frame(workbook_id, include_source_sheet=False)
    return _get_current_dataframe()


def _json_safe(payload):
    """Normalize pandas, NumPy, and Plotly values before API serialization."""
    return json.loads(json.dumps(payload, cls=PlotlyJSONEncoder))


@app.get("/")
def read_root() -> dict:
    """Basic service info endpoint."""
    return {
        "service": "Datalogue API",
        "status": "running",
    }


@app.get("/health")
def health_check() -> dict:
    """Health check endpoint."""
    return {"status": "ok"}


@app.post("/upload")
async def upload_csv(file: UploadFile = File(...)) -> dict:
    """
    Accept a CSV file upload, persist it to disk, load it into memory as
    the active dataset, and return the dataset schema detected from its
    contents.
    """
    safe_filename = sanitize_filename(file.filename or "")

    if not validate_csv_extension(safe_filename):
        logger.warning("Rejected upload with invalid extension: %s", safe_filename)
        raise HTTPException(status_code=400, detail="Only .csv and .xlsx/.xls files are supported.")

    stored_filename = generate_unique_filename(safe_filename)

    try:
        contents = await file.read()
        logger.info("Saved upload '%s' as '%s'", safe_filename, stored_filename)
    except Exception as exc:
        logger.exception("Failed to read uploaded file '%s'", safe_filename)
        raise HTTPException(status_code=500, detail="Failed to save uploaded file.") from exc
    finally:
        await file.close()

    try:
        with tempfile.NamedTemporaryFile(
            suffix=Path(safe_filename).suffix,
        ) as temporary:
            temporary.write(contents)
            temporary.flush()
            dataframe = load_csv(temporary.name)
        schema = detect_schema(dataframe)
    except (EmptyCSVError, CorruptedCSVError) as exc:
        logger.warning("Rejected invalid CSV '%s': %s", safe_filename, exc)
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:  # noqa: BLE001 - guard against unexpected parsing failures
        logger.exception("Unexpected error while processing CSV '%s'", safe_filename)
        raise HTTPException(status_code=500, detail="Failed to process CSV file.") from exc

    app.state.current_dataframe = dataframe
    app.state.current_filename = safe_filename
    logger.info("Active dataset set to '%s' (%d rows).", safe_filename, schema["total_rows"])

    # The same file is also registered as a workbook, so it appears in the
    # Workbooks list with its sheets, schema and findings already computed.
    workbook = None
    service = app.state.workbooks
    if service is not None:
        try:
            record = service.create(
                file_name=safe_filename,
                storage_path=f"db://{stored_filename}",
                file_type=Path(safe_filename).suffix.lower().lstrip("."),
                file_data=contents,
            )
            workbook = service.get(record["id"])
            app.state.current_workbook_id = record["id"]
        except Exception as exc:  # noqa: BLE001 - the upload itself already succeeded
            logger.warning("Could not register the upload as a workbook: %s", exc)

    return {
        "message": "File uploaded and processed successfully.",
        "original_filename": safe_filename,
        "stored_filename": stored_filename,
        "schema": schema,
        "workbook": workbook,
    }


@app.get("/datasets")
def list_datasets() -> dict:
    """
    List previously uploaded datasets available for presentation generation.

    Returns the workbook id (used as ``dataset_id``), display name, size in
    bytes and upload timestamp for every file stored in SQLite.
    """
    if app.state.workbook_store is None:
        on_startup()

    datasets = []
    for workbook in app.state.workbook_store.list_workbooks():
        file_name = workbook["file_name"]
        datasets.append({
            "dataset_id": workbook["id"],
            "display_name": Path(file_name).stem,
            "extension": workbook["file_type"],
            "size_bytes": len(workbook.get("file_data") or b""),
            "uploaded_at": workbook["uploaded_at"],
        })

    return {"datasets": datasets}


@app.get("/kpis")
def get_kpis() -> dict:
    """Return generated KPIs for the currently uploaded dataset."""
    dataframe = _get_current_dashboard_dataframe()

    try:
        return generate_kpis(dataframe)
    except Exception as exc:  # noqa: BLE001 - guard against unexpected analysis failures
        logger.exception("Failed to generate KPIs for '%s'", app.state.current_filename)
        raise HTTPException(status_code=500, detail="Failed to generate KPIs.") from exc


@app.get("/charts")
def get_charts() -> list:
    """Return recommended chart configurations for the currently uploaded dataset."""
    dataframe = _get_current_dashboard_dataframe()

    try:
        return generate_charts(dataframe)
    except Exception as exc:  # noqa: BLE001 - guard against unexpected analysis failures
        logger.exception("Failed to generate charts for '%s'", app.state.current_filename)
        raise HTTPException(status_code=500, detail="Failed to generate charts.") from exc


@app.get("/dashboard-plan")
@app.get("/plan")
def get_dashboard_plan() -> dict:
    """Return structured ecommerce-style dashboard layout plan for the currently uploaded dataset."""
    from src.presentation.dashboard_planner import plan_dashboard

    dataframe = _get_current_dashboard_dataframe()
    try:
        return plan_dashboard(dataframe)
    except Exception as exc:  # noqa: BLE001 - guard against unexpected analysis failures
        logger.exception("Failed to plan dashboard for '%s'", app.state.current_filename)
        raise HTTPException(status_code=500, detail="Failed to plan dashboard layout.") from exc


@app.get("/dashboard")
def get_dashboard() -> dict:
    """
    Return the complete ecommerce dashboard payload in one request:
      - quick_stats
      - kpis
      - main_chart (Total Sells time-series, multi-series support)
      - secondary_charts (up to 4 small metric/chart datasets)
      - latest_table (recent orders/reviews with dynamic columns)
    """
    from src.presentation.dashboard_planner import generate_dashboard

    dataframe = _get_current_dashboard_dataframe()

    try:
        return _json_safe(generate_dashboard(dataframe))
    except Exception as exc:  # noqa: BLE001 - guard against unexpected analysis failures
        logger.exception("Failed to generate dashboard for '%s'", app.state.current_filename)
        raise HTTPException(status_code=500, detail="Failed to generate dashboard.") from exc


@app.get("/summary")
def get_summary() -> dict:
    """Return the AI-generated business summary for the currently uploaded dataset."""
    dataframe = _get_current_dashboard_dataframe()

    try:
        return generate_summary(dataframe)
    except Exception as exc:  # noqa: BLE001 - guard against unexpected LLM/analysis failures
        logger.exception("Failed to generate summary for '%s'", app.state.current_filename)
        raise HTTPException(status_code=500, detail="Failed to generate summary.") from exc


@app.post("/presentations/generate")
async def generate_presentation_endpoint(
    request: Request,
    file: Optional[UploadFile] = File(None),
    dataset_id: Optional[str] = Form(None),
    suggestions: Optional[str] = Form(None),
    theme: Optional[str] = Form(None),
    detail_level: Optional[str] = Form(None),
    ai_narrative: Optional[bool] = Form(None),
    current_deck: Optional[str] = Form(None),
) -> dict:
    """
    Start generation of an editable PowerPoint presentation (.pptx).

    The source dataset is resolved from, in order of preference: a directly
    uploaded file, a previously uploaded ``dataset_id``, or the currently
    active in-memory dataset.

    Generation runs in a background thread so the client can poll
    ``GET /presentations/jobs/{job_id}`` for genuine pipeline progress. The
    dataset identifier may be supplied as a multipart form field or as a query
    string parameter.

    ``suggestions`` carries free-text instructions from the requester about
    narrative and slide structure. The planner may add, remove, or reorder
    grounded slides, while all chart figures remain computed from the data.

    ``theme``, ``detail_level`` and ``ai_narrative`` come from the requester's
    Settings. They are applied at generation time: the theme decides the
    colours, the detail level decides how much each slide carries, and
    ``ai_narrative`` turns the agent's prose on or off.

    Returns:
      - job_id: Identifier used to poll progress
      - status: "running"
      - stage: The stage the job starts in
      - stages: The ordered list of pipeline stages
    """
    if not dataset_id:
        dataset_id = request.query_params.get("dataset_id")

    # The suggestions are the requester's own words, but they end up in a
    # prompt, so the length is bounded and the text is trimmed.
    suggestions = (suggestions or "").strip()[:MAX_SUGGESTION_CHARS] or None
    current_plan = None
    if current_deck:
        try:
            parsed_deck = json.loads(current_deck)
        except (TypeError, ValueError, json.JSONDecodeError) as exc:
            raise HTTPException(status_code=400, detail="current_deck must be valid JSON.") from exc
        if isinstance(parsed_deck, dict):
            current_plan = parsed_deck

    # The generation settings come from the requester's Settings. An
    # unknown theme or detail level falls back to the default rather than
    # failing the request.
    theme_name = normalize_theme(theme)
    detail_level_name = normalize_detail_level(detail_level)
    use_agent = True if ai_narrative is None else bool(ai_narrative)

    dataframe: Optional[pd.DataFrame] = None
    source_name = "dataset"

    # Case 1: Direct file upload provided in request
    if file is not None and file.filename:
        safe_name = sanitize_filename(file.filename)
        if not validate_csv_extension(safe_name):
            raise HTTPException(status_code=400, detail="Only .csv and .xlsx/.xls files are supported.")

        try:
            contents = await file.read()
            with tempfile.NamedTemporaryFile(suffix=Path(safe_name).suffix) as temporary:
                temporary.write(contents)
                temporary.flush()
                if Path(safe_name).suffix.lower() in {".xlsx", ".xls"}:
                    parsed = process_workbook(temporary.name)
                    frames = [
                        frame
                        for sheet_id, frame in parsed["frames"].items()
                        if any(
                            sheet["id"] == sheet_id and sheet["status"] == "parsed"
                            for sheet in parsed["sheets"]
                        )
                    ]
                    if not frames:
                        raise EmptyCSVError(f"Excel file contains no usable sheets: {safe_name}")
                    dataframe = pd.concat(frames, ignore_index=True, sort=False)
                else:
                    dataframe = load_csv(temporary.name)
            source_name = Path(safe_name).stem
        except (EmptyCSVError, CorruptedCSVError) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except Exception as exc:
            logger.exception("Failed to parse dataset for presentation: %s", exc)
            raise HTTPException(status_code=500, detail="Failed to process dataset file.") from exc
        finally:
            await file.close()

        app.state.current_dataframe = dataframe
        app.state.current_filename = safe_name
        if app.state.workbooks is not None:
            try:
                record = app.state.workbooks.create(
                    file_name=safe_name,
                    storage_path=f"db://{uuid.uuid4().hex}",
                    file_type=Path(safe_name).suffix.lower().lstrip("."),
                    file_data=contents,
                )
                app.state.current_workbook_id = record["id"]
            except Exception:
                logger.exception("Failed to register direct presentation upload '%s'.", safe_name)
                raise HTTPException(
                    status_code=500,
                    detail="Failed to store the uploaded dataset.",
                )

    # Case 2: Specific dataset id stored in SQLite
    elif dataset_id:
        workbook = app.state.workbook_store.get_workbook(dataset_id)
        if workbook is None:
            raise HTTPException(status_code=404, detail=f"Dataset not found: {dataset_id}")
        try:
            with tempfile.NamedTemporaryFile(suffix=Path(workbook["file_name"]).suffix) as temporary:
                temporary.write(workbook["file_data"] or b"")
                temporary.flush()
                dataframe = load_csv(temporary.name)
            source_name = Path(workbook["file_name"]).stem
        except Exception as exc:
            raise HTTPException(status_code=400, detail=f"Failed to load dataset: {exc}") from exc

    # Case 3: Currently active in-memory dataset
    else:
        dataframe = _get_current_dataframe()
        source_name = Path(app.state.current_filename or "dataset").stem

    if dataframe is None or dataframe.empty:
        raise HTTPException(status_code=400, detail="Cannot generate presentation: dataset is empty.")

    clean_stem = "".join(c if c.isalnum() or c in ("-", "_") else "_" for c in source_name).strip("_")
    presentation_filename = f"{clean_stem}_{uuid.uuid4().hex[:8]}.pptx"
    output_path = Path(tempfile.mktemp(suffix=".pptx"))

    job = PresentationJob(uuid.uuid4().hex)
    app.state.presentation_jobs[job.job_id] = job
    job.update("reading_spreadsheet", "Reading spreadsheet")

    def _run() -> None:
        """Generate the deck off the request thread, recording real progress."""
        try:
            _, deck_plan = generate_presentation_with_plan(
                dataframe,
                output_path,
                progress=job.update,
                suggestions=suggestions,
                use_agent=use_agent,
                theme=theme_name,
                detail_level=detail_level_name,
                current_plan=current_plan,
            )
            _store_rendered_presentation(output_path, presentation_filename, deck_plan)
            job.deck = deck_plan
            job.base_deck = deck_plan
            job.filename = presentation_filename
            job.download_url = f"/presentations/download/{presentation_filename}"
            job.status = "completed"
            job.update("completed", "Presentation ready")
        except Exception as exc:  # noqa: BLE001 - surfaced to the client via the job
            logger.exception("Failed to generate PowerPoint presentation: %s", exc)
            job.status = "failed"
            job.error = "Failed to generate PowerPoint presentation."
            job.update("failed", job.error)

    thread = threading.Thread(target=_run, name=f"presentation-{job.job_id}", daemon=True)
    thread.start()

    return {
        "job_id": job.job_id,
        "status": job.status,
        "stage": job.stage,
        "message": job.message,
        "stages": GENERATION_STAGES,
    }


@app.get("/presentations/jobs/{job_id}")
def get_presentation_job(job_id: str) -> dict:
    """Return the current progress of a presentation generation job."""
    job = app.state.presentation_jobs.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Presentation job not found.")
    return job.to_dict()


@app.post("/presentations/jobs/{job_id}/edit")
def edit_presentation(job_id: str, payload: DeckEditRequest) -> dict:
    """
    Apply the requester's live edits to a generated deck and re-render it.

    The edits address a slide by its number and a field by its name, e.g.
    ``{"slide": 2, "field": "caption", "value": "Revenue climbed through Q3."}``.
    Only the narrative fields of a slide may be edited — the structure, the
    charts and the KPI tiles are computed from the dataset, so an edit that
    tries to touch one of them is rejected and reported back.

    The edited plan is written to a new .pptx and the job now points at it,
    so the download and the preview stay in step.

    Returns:
      - deck: The edited deck plan, as the preview renders it
      - applied: The edits that were applied
      - rejected: The edits that were not, each with a reason
    """
    job = app.state.presentation_jobs.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Presentation job not found.")

    base_deck = job.base_deck or job.deck
    if not base_deck:
        raise HTTPException(status_code=400, detail="The presentation is not ready to edit yet.")

    return _apply_edits_to_deck(base_deck, payload.edits, job=job)


@app.post("/presentations/{filename}/edit")
def edit_presentation_by_file(filename: str, payload: DeckEditRequest) -> dict:
    """
    Apply the requester's live edits to a deck file and re-render it.

    This is the durable counterpart of ``/presentations/jobs/{job_id}/edit``:
    it addresses the deck by the file it was written to, so a deck can still
    be edited after the server has restarted and the in-memory job registry
    has been emptied.
    """
    safe_name = sanitize_filename(filename)
    if not safe_name.lower().endswith(".pptx"):
        raise HTTPException(status_code=400, detail="Invalid presentation file request.")

    if app.state.presentations is None:
        app.state.presentations = PresentationStore(PRESENTATIONS_DB_PATH)
    base_artifact = app.state.presentations.get(safe_name)
    if base_artifact is None:
        raise HTTPException(status_code=404, detail="Presentation not found.")

    base_deck = base_artifact[1]
    if not base_deck:
        raise HTTPException(
            status_code=400,
            detail="The plan for this presentation is no longer available, so it cannot be edited.",
        )

    return _apply_edits_to_deck(base_deck, payload.edits, filename=safe_name)


def _apply_edits_to_deck(
    base_deck: dict,
    edits: list,
    job: Optional[PresentationJob] = None,
    filename: Optional[str] = None,
) -> dict:
    """
    Apply a set of edits to a deck plan and write the edited deck to a file.

    The edits are applied to the deck as it was first generated, which makes
    the operation repeatable: sending the same edit twice gives the same
    result.
    """
    if not edits:
        raise HTTPException(status_code=400, detail="No edits were supplied.")

    try:
        edited_plan, applied, rejected = apply_deck_edits(base_deck, edits)
    except DeckEditError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    if not applied:
        reasons = "; ".join(item["reason"] for item in rejected)
        raise HTTPException(status_code=400, detail=f"No edits could be applied. {reasons}".strip())

    # The edited deck is written to a new file, so the original deck stays
    # downloadable and the export always matches what is on screen.
    source = Path(filename or (job.filename if job else "presentation")).stem
    clean_stem = "".join(c if c.isalnum() or c in ("-", "_") else "_" for c in source).strip("_")
    edited_filename = f"{clean_stem}_edited_{uuid.uuid4().hex[:8]}.pptx"
    output_path = Path(tempfile.mktemp(suffix=".pptx"))

    try:
        render_plan_to_pptx(edited_plan, output_path)
        _store_rendered_presentation(output_path, edited_filename, edited_plan)
    except Exception as exc:  # noqa: BLE001 - surfaced to the client
        logger.exception("Failed to render the edited presentation: %s", exc)
        raise HTTPException(status_code=500, detail="Failed to render the edited presentation.") from exc

    if job is not None:
        job.deck = edited_plan
        job.filename = edited_filename
        job.download_url = f"/presentations/download/{edited_filename}"

    return {
        "job_id": job.job_id if job is not None else None,
        "status": job.status if job is not None else "completed",
        "filename": edited_filename,
        "download_url": f"/presentations/download/{edited_filename}",
        "deck": edited_plan,
        "applied": applied,
        "rejected": rejected,
    }


@app.get("/presentations/download/{filename}")
def download_presentation(filename: str):
    """Download a generated PowerPoint presentation by filename."""
    safe_name = sanitize_filename(filename)
    if not safe_name.lower().endswith(".pptx"):
        raise HTTPException(status_code=400, detail="Invalid presentation file request.")

    if app.state.presentations is None:
        app.state.presentations = PresentationStore(PRESENTATIONS_DB_PATH)
    content = app.state.presentations.get_pptx(safe_name)
    if content is None:
        raise HTTPException(status_code=404, detail="Presentation not found.")

    return Response(
        content=content,
        media_type="application/vnd.openxmlformats-officedocument.presentationml.presentation",
        headers={"Content-Disposition": f'attachment; filename="{safe_name}"'},
    )


@app.post("/query")
def post_query(request: QueryRequest) -> dict:
    """Answer a natural language question about the currently uploaded dataset."""
    workbook_id = app.state.current_workbook_id
    if app.state.workbooks is not None:
        if workbook_id and app.state.workbooks.get(workbook_id) is None:
            workbook_id = None
        if workbook_id is None:
            stored = next(
                (
                    workbook
                    for workbook in app.state.workbook_store.list_workbooks()
                    if workbook.get("status") in {"parsed", "partially_parsed"}
                ),
                None,
            )
            if stored:
                workbook_id = stored["id"]
                app.state.current_workbook_id = workbook_id

    dataframe = (
        _get_workbook_query_frame(workbook_id)
        if workbook_id
        else _get_current_dataframe()
    )

    try:
        return answer_question(dataframe, request.question)
    except GuardrailError as exc:
        # A refusal by the guardrails: the question never reached the model.
        raise HTTPException(status_code=400, detail=exc.message) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:  # noqa: BLE001 - guard against unexpected LLM/analysis failures
        logger.exception("Failed to answer query for '%s'", app.state.current_filename)
        raise HTTPException(status_code=500, detail="Failed to answer query.") from exc


# ---------------------------------------------------------------------------
# Workbooks
#
# A workbook is the central data object: one record per uploaded
# spreadsheet, with one sheet record per tabular sheet inside it. The
# processing pipeline runs once per upload, and both consumers — the PPT
# generator and the AI Assistant — read the schema and the cached dataframe
# rather than re-parsing the file.
# ---------------------------------------------------------------------------


class ActiveSheetRequest(BaseModel):
    """Body for ``PATCH /workbooks/{id}/active-sheet``."""

    sheet_id: str


class ActivateWorkbookRequest(BaseModel):
    """Body for ``POST /workbooks/{id}/activate``."""

    sheet_id: Optional[str] = None


class WorkbookQueryRequest(BaseModel):
    """Body for ``POST /workbooks/{id}/query``."""

    question: str
    sheet_id: Optional[str] = None


class WorkbookGenerateRequest(BaseModel):
    """Body for ``POST /workbooks/{id}/generate``."""

    sheet_id: Optional[str] = None
    suggestions: Optional[str] = None
    # The generation settings, passed in from the requester's Settings.
    theme: Optional[str] = None
    detail_level: Optional[str] = None
    ai_narrative: Optional[bool] = None
    current_deck: Optional[dict] = None


class RetentionRequest(BaseModel):
    """Body for ``POST /workbooks/purge``."""

    # How many days a workbook is kept. Zero or less is ignored, because
    # it would purge everything.
    retention_days: int = 30


def _workbook_service() -> WorkbookService:
    """The workbook service, or a 500 when it has not been set up."""
    service = app.state.workbooks
    if service is None:
        raise HTTPException(
            status_code=500, detail="The workbook service is not available."
        )
    return service


@app.post("/workbooks")
async def create_workbook(file: UploadFile = File(...)) -> dict:
    """
    Upload a spreadsheet, process it, and return the workbook record.

    The pipeline runs inline, so the response already carries the sheets,
    the schema and the findings. A file that cannot be parsed still
    produces a workbook — in the ``needs_attention`` state, with the
    reason — rather than failing the request.
    """
    safe_filename = sanitize_filename(file.filename or "")

    if not validate_csv_extension(safe_filename):
        logger.warning("Rejected workbook with invalid extension: %s", safe_filename)
        raise HTTPException(
            status_code=400, detail="Only .csv and .xlsx/.xls files are supported."
        )

    stored_filename = generate_unique_filename(safe_filename)

    try:
        contents = await file.read()
    except Exception as exc:
        logger.exception("Failed to read workbook '%s'", safe_filename)
        raise HTTPException(status_code=500, detail="Failed to save the file.") from exc
    finally:
        await file.close()

    service = _workbook_service()
    workbook = service.create(
        file_name=safe_filename,
        storage_path=f"db://{stored_filename}",
        file_type=Path(safe_filename).suffix.lower().lstrip("."),
        file_data=contents,
    )

    return {
        "workbook": service.get(workbook["id"]),
        "stored_filename": stored_filename,
    }


@app.get("/workbooks")
def list_workbooks() -> dict:
    """List the workbooks, newest first."""
    service = _workbook_service()
    return {"workbooks": service.list()}


@app.get("/workbooks/search")
def search_workbooks(q: str = Query(""), limit: int = 200) -> dict:
    """
    Search the workbooks, from the outside in.

    The keyword is matched against the workbook names, the sheet names, the
    column names and the cell values, and the matches come back with where
    they were found, so the caller can point at the right row.
    """
    service = _workbook_service()
    return service.search(q, limit=limit)


@app.get("/workbooks/{workbook_id}")
def get_workbook(workbook_id: str) -> dict:
    """One workbook, with its sheets, schema and findings."""
    service = _workbook_service()
    try:
        return {"workbook": service.get(workbook_id)}
    except WorkbookNotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.get("/workbooks/{workbook_id}/sheets/{sheet_id}")
def get_workbook_sheet(workbook_id: str, sheet_id: str) -> dict:
    """One sheet of a workbook, with its schema and findings."""
    service = _workbook_service()
    try:
        return {"sheet": service.get_sheet(workbook_id, sheet_id)}
    except WorkbookNotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.patch("/workbooks/{workbook_id}/active-sheet")
def set_active_sheet(workbook_id: str, request: ActiveSheetRequest) -> dict:
    """Choose which sheet the consumers work with by default."""
    service = _workbook_service()
    try:
        service.set_active_sheet(workbook_id, request.sheet_id)
    except WorkbookNotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    return {"workbook": service.get(workbook_id)}


@app.post("/workbooks/{workbook_id}/activate")
def activate_workbook(workbook_id: str, request: ActivateWorkbookRequest = None) -> dict:
    """
    Make a workbook's sheet the active dataset.

    The dashboard draws from whichever dataset is active, so this is how a
    workbook that was uploaded earlier gets looked at: the sheet is read,
    it becomes the active dataset, and the dashboard endpoints start
    describing it.
    """
    service = _workbook_service()

    try:
        frame = service.get_frame(workbook_id, request.sheet_id if request else None)
    except WorkbookNotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    if frame is None or frame.empty:
        raise HTTPException(
            status_code=400, detail="This sheet is empty, so there is nothing to show."
        )

    workbook = service.get(workbook_id)
    sheet_id = request.sheet_id if request else workbook.get("active_sheet_id")

    app.state.current_dataframe = frame
    app.state.current_filename = workbook["file_name"]
    app.state.current_workbook_id = workbook_id
    logger.info(
        "Active dataset set to workbook %s (sheet %s, %d rows).",
        workbook_id,
        sheet_id,
        len(frame),
    )

    return {
        "message": "Workbook is now the active dataset.",
        "original_filename": workbook["file_name"],
        "stored_filename": Path(workbook["storage_path"]).name,
        "schema": detect_schema(frame),
        "workbook": workbook,
    }


@app.put("/workbooks/{workbook_id}")
async def replace_workbook(
    workbook_id: str, file: UploadFile = File(...)
) -> dict:
    """
    Replace a workbook's file and re-run the pipeline.

    The cached frames are dropped and the derived records are rebuilt, so
    nothing can be computed against the old version of the data.
    """
    safe_filename = sanitize_filename(file.filename or "")

    if not validate_csv_extension(safe_filename):
        raise HTTPException(
            status_code=400, detail="Only .csv and .xlsx/.xls files are supported."
        )

    service = _workbook_service()
    try:
        service.get(workbook_id)
    except WorkbookNotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    stored_filename = generate_unique_filename(safe_filename)

    try:
        contents = await file.read()
    except Exception as exc:
        logger.exception("Failed to read replacement workbook '%s'", safe_filename)
        raise HTTPException(status_code=500, detail="Failed to save the file.") from exc
    finally:
        await file.close()

    workbook = service.replace(
        workbook_id,
        file_name=safe_filename,
        storage_path=f"db://{stored_filename}",
        file_type=Path(safe_filename).suffix.lower().lstrip("."),
        file_data=contents,
    )

    return {"workbook": service.get(workbook["id"])}


@app.delete("/workbooks/{workbook_id}")
def delete_workbook(workbook_id: str) -> dict:
    """Remove a workbook, its raw file and its cache entry."""
    service = _workbook_service()
    try:
        service.delete(workbook_id)
    except WorkbookNotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    return {"deleted": workbook_id}


@app.delete("/workbooks")
def delete_all_workbooks() -> dict:
    """
    Remove every workbook, its raw file and its cache entry.

    This backs the "Clear all workbooks" action in Settings. It is
    destructive and covers every workbook in one call, so the client asks
    for confirmation before it is sent.
    """
    service = _workbook_service()
    removed = service.delete_all()
    return {"deleted": removed}


@app.post("/workbooks/purge")
def purge_workbooks(request: RetentionRequest) -> dict:
    """
    Remove the workbooks that are older than the retention window.

    The window comes from the requester's Settings, and the client
    triggers the cleanup rather than a backend cron, so nothing is
    removed until it is asked for. A retention of zero or less is
    ignored: it would purge everything.
    """
    service = _workbook_service()
    removed = service.purge_older_than(request.retention_days)
    return {"deleted": len(removed), "deleted_ids": removed}


@app.post("/workbooks/{workbook_id}/query")
def query_workbook(workbook_id: str, request: WorkbookQueryRequest) -> dict:
    """
    Answer a question about a workbook's data.

    The same pipeline the assistant uses, scoped to a workbook and a
    sheet, and run against the cached dataframe.
    """
    service = _workbook_service()

    try:
        frame = (
            _get_workbook_query_frame(workbook_id)
            if request.sheet_id is None
            else service.get_frame(workbook_id, request.sheet_id)
        )
    except WorkbookNotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    try:
        return answer_question(frame, request.question)
    except GuardrailError as exc:
        raise HTTPException(status_code=400, detail=exc.message) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:  # noqa: BLE001 - guard against unexpected failures
        logger.exception("Failed to answer query for workbook %s", workbook_id)
        raise HTTPException(status_code=500, detail="Failed to answer query.") from exc


@app.post("/workbooks/{workbook_id}/generate")
def generate_from_workbook(workbook_id: str, request: WorkbookGenerateRequest) -> dict:
    """
    Generate a deck from a workbook.

    By default, all parsed sheets are combined so the deck represents the
    uploaded file. An explicit sheet_id limits generation to one sheet.
    The job runs in a background thread, exactly as the standalone
    generation endpoint does.
    """
    service = _workbook_service()

    try:
        frame = (
            service.get_frame(workbook_id, request.sheet_id)
            if request.sheet_id
            else _get_workbook_query_frame(workbook_id, include_source_sheet=False)
        )
    except WorkbookNotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    if frame is None or frame.empty:
        raise HTTPException(
            status_code=400, detail="Cannot generate a deck: the workbook has no usable data."
        )

    source_name = Path(service.get(workbook_id)["file_name"]).stem
    clean_stem = "".join(
        c if c.isalnum() or c in ("-", "_") else "_" for c in source_name
    ).strip("_")
    presentation_filename = f"{clean_stem}_{uuid.uuid4().hex[:8]}.pptx"
    output_path = Path(tempfile.mktemp(suffix=".pptx"))

    job = PresentationJob(uuid.uuid4().hex)
    app.state.presentation_jobs[job.job_id] = job
    job.update("reading_spreadsheet", "Reading spreadsheet")

    suggestions = (request.suggestions or "").strip()[:MAX_SUGGESTION_CHARS] or None

    # The generation settings come from the requester's Settings.
    theme_name = normalize_theme(request.theme)
    detail_level_name = normalize_detail_level(request.detail_level)
    use_agent = True if request.ai_narrative is None else bool(request.ai_narrative)

    def _run() -> None:
        """Generate the deck off the request thread, recording real progress."""
        try:
            _, deck_plan = generate_presentation_with_plan(
                frame,
                output_path,
                progress=job.update,
                suggestions=suggestions,
                use_agent=use_agent,
                theme=theme_name,
                detail_level=detail_level_name,
                current_plan=request.current_deck,
            )
            _store_rendered_presentation(output_path, presentation_filename, deck_plan)
            job.deck = deck_plan
            job.base_deck = deck_plan
            job.filename = presentation_filename
            job.download_url = f"/presentations/download/{presentation_filename}"
            job.status = "completed"
            job.update("completed", "Presentation ready")
        except Exception as exc:  # noqa: BLE001 - surfaced to the client via the job
            logger.exception("Failed to generate a deck for workbook %s", workbook_id)
            job.status = "failed"
            job.error = "Failed to generate PowerPoint presentation."
            job.update("failed", job.error)

    thread = threading.Thread(
        target=_run, name=f"workbook-presentation-{job.job_id}", daemon=True
    )
    thread.start()

    return {
        "job_id": job.job_id,
        "status": job.status,
        "stage": job.stage,
        "stages": list(GENERATION_STAGES),
    }
