// Centralized Axios client and backend API calls.
//
// Backend contract (single in-memory "current" dataset, set by POST /upload):
//   POST /upload   multipart file   -> { message, original_filename, stored_filename, schema }
//   GET  /datasets                  -> { datasets: [{ dataset_id, display_name, ... }] }
//   GET  /kpis                      -> kpi_generator.generate_kpis() JSON
//   GET  /charts                    -> chart_generator.generate_charts() JSON (list)
//   GET  /dashboard                 -> dashboard_planner.generate_dashboard() JSON
//   GET  /summary                   -> summary_generator.generate_summary() JSON
//   POST /query    { question }     -> query_engine.answer_question() JSON
//   POST /presentations/generate    -> { job_id, status, stage, stages }
//   GET  /presentations/jobs/{job_id} -> { status, stage, filename, download_url, deck }
//   GET  /presentations/download/{filename} -> .pptx binary

import axios from "axios";

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL || "http://localhost:8000";

const client = axios.create({
  baseURL: API_BASE_URL,
});

/** Extract a human-readable error message from an Axios/JS error. */
export function getErrorMessage(error) {
  return (
    error?.response?.data?.detail ||
    error?.message ||
    "Something went wrong. Please try again."
  );
}

/**
 * Upload a dataset (CSV or Excel), reporting progress via onProgress(percent).
 * The uploaded file also becomes the backend's active dataset.
 */
export async function uploadDataset(file, onProgress) {
  const formData = new FormData();
  formData.append("file", file);

  const response = await client.post("/upload", formData, {
    onUploadProgress: (event) => {
      if (onProgress && event.total) {
        onProgress(Math.round((event.loaded * 100) / event.total));
      }
    },
  });

  return response.data;
}

/** Fetch generated KPIs for the currently uploaded dataset. */
export async function fetchKPIs() {
  const response = await client.get("/kpis");
  return response.data;
}

/** Fetch recommended chart configurations for the currently uploaded dataset. */
export async function fetchCharts() {
  const response = await client.get("/charts");
  return response.data;
}

/** Fetch unified ecommerce dashboard payload for the currently uploaded dataset. */
export async function getDashboard() {
  const response = await client.get("/dashboard");
  return response.data;
}

/** Fetch the AI-generated business summary for the currently uploaded dataset. */
export async function fetchSummary() {
  const response = await client.get("/summary");
  return response.data;
}

/** Ask a natural language question about the currently uploaded dataset. */
export async function sendQuery(question) {
  const response = await client.post("/query", { question });
  return response.data;
}

/**
 * Ask the AI assistant a question about the active dataset.
 *
 * The backend answers by computing over the data, not by asking the model
 * for a number: it classifies the intent, has the model write a query plan,
 * runs the plan against the real dataframe, and has the model phrase the
 * computed result. The response carries the answer, a confidence level, the
 * rows and numbers behind it, and the plan that was run.
 *
 * @param {string} question
 * @returns {Promise<{answer, confidence, supporting_data, intent, plan}>}
 */
export async function askAssistant(question) {
  const response = await client.post("/query", { question });
  return response.data;
}

/** List previously uploaded datasets that can be turned into presentations. */
export async function listDatasets() {
  const response = await client.get("/datasets");
  return response.data;
}

// ---------------------------------------------------------------------------
// Workbooks
//
// A workbook is the central data object: one record per uploaded
// spreadsheet, with one sheet record per tabular sheet inside it. The
// processing pipeline runs once per upload, and the AI Assistant and the
// PPT generator both read the workbook rather than re-parsing the file.
// ---------------------------------------------------------------------------

/** Upload a spreadsheet and process it into a workbook. */
export async function createWorkbook(file) {
  const formData = new FormData();
  formData.append("file", file);

  const response = await client.post("/workbooks", formData);
  return response.data;
}

/** List the workbooks, newest first. */
export async function listWorkbooks() {
  const response = await client.get("/workbooks");
  return response.data;
}

/** Fetch one workbook, with its sheets, schema and findings. */
export async function getWorkbook(workbookId) {
  const response = await client.get(`/workbooks/${workbookId}`);
  return response.data;
}

/**
 * Make a workbook the active dataset, so the dashboard draws from it.
 *
 * The sheet is optional: without one, the workbook's own active sheet is
 * used.
 */
export async function activateWorkbook(workbookId, sheetId = null) {
  const response = await client.post(`/workbooks/${workbookId}/activate`, {
    sheet_id: sheetId,
  });
  return response.data;
}

/**
 * Search the workbooks, from the outside in.
 *
 * The keyword is matched against the workbook names, the sheet names, the
 * column names and the cell values, so a search finds what is inside a
 * workbook and not just what it is called.
 */
export async function searchWorkbooks(keyword, limit = 200) {
  const response = await client.get("/workbooks/search", {
    params: { q: keyword, limit },
  });
  return response.data;
}

/** Choose which sheet the consumers work with by default. */
export async function setActiveSheet(workbookId, sheetId) {
  const response = await client.patch(`/workbooks/${workbookId}/active-sheet`, {
    sheet_id: sheetId,
  });
  return response.data;
}

/** Replace a workbook's file and re-run the pipeline over it. */
export async function replaceWorkbook(workbookId, file) {
  const formData = new FormData();
  formData.append("file", file);

  const response = await client.put(`/workbooks/${workbookId}`, formData);
  return response.data;
}

/** Remove a workbook, its raw file and its cache entry. */
export async function deleteWorkbook(workbookId) {
  const response = await client.delete(`/workbooks/${workbookId}`);
  return response.data;
}

/**
 * Remove every workbook, its raw file and its cache entry.
 *
 * This backs the "Clear all workbooks" action in Settings. It is
 * destructive and covers everything at once, so the client confirms with
 * the user before sending it.
 */
export async function deleteAllWorkbooks() {
  const response = await client.delete("/workbooks");
  return response.data;
}

/**
 * Remove the workbooks that are older than the retention window.
 *
 * The window comes from the requester's Settings. The cleanup is
 * client-triggered rather than run on a backend cron, so nothing is
 * removed until it is asked for.
 *
 * @param {number} retentionDays  How many days a workbook is kept.
 */
export async function purgeWorkbooks(retentionDays) {
  const response = await client.post("/workbooks/purge", {
    retention_days: retentionDays,
  });
  return response.data;
}

/** Ask a question about a workbook's data. */
export async function queryWorkbook(workbookId, question, sheetId) {
  const response = await client.post(`/workbooks/${workbookId}/query`, {
    question,
    sheet_id: sheetId || undefined,
  });
  return response.data;
}

/**
 * Start a PowerPoint deck generation on the backend.
 *
 * The backend runs the work in a background thread and reports genuine
 * pipeline progress, so this returns a job id rather than the finished deck.
 *
 * @param {object} options
 * @param {File} [options.file]        Optional direct file upload.
 * @param {string} [options.datasetId]  Optional id of a previously uploaded dataset.
 * @param {string} [options.suggestions] Optional free-text instructions for the
 *   agent about narrative or slide structure changes. Any figures remain
 *   computed from the active dataset.
 * @param {string} [options.theme]      The theme the deck is drawn in.
 * @param {string} [options.detailLevel] How much each slide carries.
 * @param {boolean} [options.aiNarrative] Whether the agent writes the narrative.
 * @param {object} [options.currentDeck] Existing deck plan for regeneration.
 * @returns {Promise<{job_id, status, stage, message, stages}>}
 */
export async function generatePresentation({
  file,
  datasetId,
  suggestions,
  theme,
  detailLevel,
  aiNarrative,
  currentDeck,
  feedbackHistory,
} = {}) {
  const formData = new FormData();

  if (file) {
    formData.append("file", file);
  }
  if (datasetId) {
    formData.append("dataset_id", datasetId);
  }
  if (suggestions && suggestions.trim()) {
    formData.append("suggestions", suggestions.trim());
  }
  if (theme) {
    formData.append("theme", theme);
  }
  if (detailLevel) {
    formData.append("slide_detail_level", detailLevel);
    formData.append("detail_level", detailLevel);
  }
  if (aiNarrative !== undefined && aiNarrative !== null) {
    formData.append("ai_narrative", aiNarrative ? "true" : "false");
  }
  if (currentDeck) {
    formData.append("current_deck", JSON.stringify(currentDeck));
  }
  if (feedbackHistory) {
    formData.append("feedback_history", JSON.stringify(feedbackHistory));
  }

  const response = await client.post("/presentations/generate", formData);

  return response.data;
}

/** Fetch the current progress of a presentation generation job. */
export async function getPresentationJob(jobId) {
  const response = await client.get(`/presentations/jobs/${jobId}`);
  return response.data;
}

/** Load the latest durable presentation associated with a workbook. */
export async function getWorkbookPresentation(workbookId) {
  const response = await client.get(`/workbooks/${workbookId}/presentation`);
  return response.data;
}

/**
 * Apply the requester's live edits to a generated deck.
 *
 * The deck is addressed by the file it was written to, not by the job that
 * produced it: the job registry lives in memory and is emptied when the
 * server restarts, but the deck file and its plan do not. That way a deck
 * can still be edited after a restart.
 *
 * The backend re-renders the edited plan into a new .pptx and returns it, so
 * the download always matches what is on screen.
 *
 * @param {string} filename   The .pptx filename of the deck being edited.
 * @param {Array}  edits      [{ slide, field, value }] — slide is 1-based.
 * @returns {Promise<{deck, applied, rejected, filename, download_url}>}
 */
export async function editPresentation(filename, edits) {
  const response = await client.post(`/presentations/${filename}/edit`, { edits });
  return response.data;
}

/** Absolute URL of a generated presentation file on the backend. */
function getPresentationDownloadUrl(downloadUrl) {
  if (!downloadUrl) return null;
  if (/^https?:\/\//i.test(downloadUrl)) return downloadUrl;
  return `${API_BASE_URL.replace(/\/$/, "")}${downloadUrl}`;
}

/**
 * Download a generated presentation as binary data.
 *
 * The bytes always come from the backend-generated .pptx, never from the
 * browser. Uses "arraybuffer" (rather than "blob") because that response type
 * is honoured by every axios adapter, and wraps the result in a Blob for the
 * browser.
 */
export async function downloadPresentation(downloadUrl) {
  const url = getPresentationDownloadUrl(downloadUrl);
  if (!url) throw new Error("No presentation file available to download.");

  try {
    const response = await client.get(url, { responseType: "arraybuffer" });
    const data = response.data;

    if (data instanceof Blob) return data;
    if (typeof Blob !== "undefined") return new Blob([data]);
    return data;
  } catch (error) {
    // Binary responses hide FastAPI's JSON error body, so surface the status.
    const status = error?.response?.status;
    if (status === 404) {
      throw new Error("The presentation file is no longer available on the server.");
    }
    if (status) {
      throw new Error(`Download failed (HTTP ${status}).`);
    }
    throw error;
  }
}

export default client;
