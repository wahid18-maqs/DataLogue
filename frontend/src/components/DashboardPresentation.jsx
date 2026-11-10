// Dashboard presentation panel: one-click generation of a PowerPoint deck from
// the active dataset, with the slide previews rendered in place.
//
// The deck is always produced by the backend (POST /presentations/generate);
// this component drives the job, polls for real progress, and previews the
// slide plan the server returns. The source is always the dataset that is
// already active on the dashboard — there is no separate file or dataset
// picker here.

import { useCallback, useEffect, useState } from "react";
import ExportDialog from "./Presentations/ExportDialog";
import StageIndicator, { FIRST_STAGE } from "./Presentations/StageIndicator";
import PresentationToolbar from "./Presentations/PresentationToolbar";
import SlidePreview from "./Presentations/SlidePreview";
import SlideThumbnailRail from "./Presentations/SlideThumbnailRail";
import SuggestionsPanel from "./Presentations/SuggestionsPanel";
import { applyPath, diffDeck } from "./Presentations/editableFields";
import {
  downloadPresentation,
  editPresentation,
  generatePresentation,
  getErrorMessage,
  getPresentationJob,
  getWorkbookPresentation,
} from "../services/api";

// How often the job status is polled while the deck is being built.
const POLL_INTERVAL_MS = 250;

// Upper bound on how long the client waits for a deck before giving up.
const JOB_TIMEOUT_MS = 120000;

export default function DashboardPresentation({ dataset, settings = null }) {
  // A stable identity for the active dataset, so the panel resets whenever a
  // different dataset becomes active.
  const datasetKey = dataset?.stored_filename || dataset?.original_filename || "";
  const workbookId = dataset?.workbook?.id || dataset?.workbook_id || "";

  const [deck, setDeck] = useState(null);
  const [presentation, setPresentation] = useState(null);
  const [activeIndex, setActiveIndex] = useState(0);

  const [isGenerating, setIsGenerating] = useState(false);
  const [currentStage, setCurrentStage] = useState(FIRST_STAGE);
  const [failedStage, setFailedStage] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");

  const [isExportOpen, setIsExportOpen] = useState(false);
  const [isDownloading, setIsDownloading] = useState(false);
  const [downloadError, setDownloadError] = useState("");

  // The regeneration flow: the panel is revealed by the toolbar button, the
  // user types what they want changed, and the agent rewrites the narrative.
  const [isSuggesting, setIsSuggesting] = useState(false);
  const [suggestions, setSuggestions] = useState("");
  const [feedbackHistory, setFeedbackHistory] = useState([]);

  // The live-edit flow: the toolbar button puts the slide itself into edit
  // mode, the requester rewrites the text on the slide, and the changes are
  // kept in a draft until they are saved.
  const [isEditing, setIsEditing] = useState(false);
  const [draft, setDraft] = useState(null);
  const [isSaving, setIsSaving] = useState(false);

  // The preview shows the draft while the slide is being edited, so the
  // requester sees their changes on the slide itself as they type.
  const previewDeck = isEditing && draft ? draft : deck;

  const slides = (previewDeck?.slides || deck?.slides || []);
  const activeSlide = slides[activeIndex] || null;
  const hasDataset = Boolean(datasetKey);

  // Whether the draft differs from the saved deck, so the Save button knows
  // if there is anything to save.
  const hasPendingEdits = Boolean(deck && draft && diffDeck(deck, draft).length > 0);

  // Reset the panel when the active dataset changes, so a stale deck is never
  // attributed to a different dataset.
  useEffect(() => {
    setDeck(null);
    setPresentation(null);
    setActiveIndex(0);
    setError("");
    setNotice("");
    setFailedStage(false);
    setIsSuggesting(false);
    setSuggestions("");
    setIsEditing(false);
    setDraft(null);
    if (!workbookId) return undefined;
    let cancelled = false;
    getWorkbookPresentation(workbookId)
      .then((result) => {
        const saved = result?.presentation;
        if (cancelled || !saved) return;
        setPresentation({
          filename: saved.filename,
          download_url: saved.download_url,
          deck: saved.deck,
          stale: saved.stale,
        });
        setDeck(saved.deck || null);
        setFeedbackHistory(saved.feedback || []);
        if (saved.stale) {
          setNotice("This presentation was generated from an older version of the workbook.");
        }
      })
      .catch(() => {
        // A missing saved deck is a normal first-use state.
      });
    return () => {
      cancelled = true;
    };
  }, [datasetKey, workbookId]);

  /**
   * Poll a generation job until it completes.
   *
   * The backend advances the stage as real work happens, so the UI shows
   * genuine progress rather than an artificial timer.
   */
  const pollUntilComplete = useCallback(async (jobId) => {
    const deadline = Date.now() + JOB_TIMEOUT_MS;

    while (Date.now() < deadline) {
      let job;
      try {
        job = await getPresentationJob(jobId);
      } catch (err) {
        // The job registry lives in memory, so a server restart loses the
        // job. Say so plainly instead of showing a bare 404.
        if (err?.response?.status === 404) {
          throw new Error(
            "The server restarted while the presentation was being generated. Please generate it again."
          );
        }
        throw err;
      }

      if (job.status === "completed") {
        setCurrentStage("completed");
        return job;
      }

      if (job.status === "failed") {
        throw new Error(job.error || "Failed to generate the presentation.");
      }

      setCurrentStage(job.stage);
      await new Promise((resolve) => setTimeout(resolve, POLL_INTERVAL_MS));
    }

    return null;
  }, []);

  // The generation settings, read from Settings. They are passed to the
  // backend at generation time rather than baked into the deck here, so
  // the .pptx and the preview are built the same way.
  const generationSettings = {
    theme: settings?.generation?.default_theme,
    detailLevel: settings?.generation?.slide_detail_level,
    aiNarrative: settings?.generation?.ai_narrative_enabled,
  };

  const handleGenerate = useCallback(async () => {
    if (!hasDataset) {
      setError("Upload a dataset first — the presentation is generated from the active dataset.");
      return;
    }

    setIsGenerating(true);
    setError("");
    setNotice("");
    setFailedStage(false);
    setCurrentStage(FIRST_STAGE);

    try {
      // No file and no dataset id: the backend uses the active dataset.
      const job = await generatePresentation(generationSettings);
      setCurrentStage(job.stage || FIRST_STAGE);

      const result = await pollUntilComplete(job.job_id);
      if (!result) {
        throw new Error("Presentation generation timed out. Please try again.");
      }

      setPresentation({
        filename: result.filename,
        download_url: result.download_url,
        deck: result.deck,
      });
      setDeck(result.deck || null);
      setFeedbackHistory((current) => [
        ...current,
        { text, timestamp: new Date().toISOString() },
      ]);
      setActiveIndex(0);
      setNotice(
        `Presentation ready — ${result.deck?.slide_count || 0} slides generated from ${datasetKey}.`
      );
    } catch (err) {
      setError(getErrorMessage(err));
      setFailedStage(true);
    } finally {
      setIsGenerating(false);
    }
  }, [datasetKey, hasDataset, pollUntilComplete, generationSettings]);

  /**
   * Rebuild the deck, passing the requester's suggestions to the agent so
   * the narrative is rewritten to follow them.
   */
  const handleRegenerate = useCallback(async () => {
    const text = suggestions.trim();
    if (!text || !hasDataset) return;

    setIsGenerating(true);
    setError("");
    setNotice("");
    setFailedStage(false);
    setCurrentStage(FIRST_STAGE);

    try {
      const job = await generatePresentation({
        ...generationSettings,
        suggestions: text,
        currentDeck: deck,
        feedbackHistory: [
          ...feedbackHistory,
          { text, timestamp: new Date().toISOString() },
        ],
      });
      setCurrentStage(job.stage || FIRST_STAGE);

      const result = await pollUntilComplete(job.job_id);
      if (!result) {
        throw new Error("Presentation generation timed out. Please try again.");
      }

      setPresentation({
        filename: result.filename,
        download_url: result.download_url,
        deck: result.deck,
      });
      setDeck(result.deck || null);
      setActiveIndex(0);
      setSuggestions("");
      setIsSuggesting(false);
      setNotice(
        `Presentation updated — ${result.deck?.slide_count || 0} slides rewritten to follow your suggestions.`
      );
    } catch (err) {
      setError(getErrorMessage(err));
      setFailedStage(true);
    } finally {
      setIsGenerating(false);
    }
  }, [
    datasetKey,
    hasDataset,
    pollUntilComplete,
    suggestions,
    generationSettings,
    deck,
    feedbackHistory,
  ]);

  /**
   * Put the slide into edit mode.
   *
   * The deck is copied into a draft: the slide itself becomes editable, and
   * the draft is what the preview renders, so the requester types on the
   * slide. The draft is only sent to the backend when they save it.
   */
  const handleOpenEditor = useCallback(() => {
    if (!deck) return;
    setError("");
    setNotice("");
    setDraft(JSON.parse(JSON.stringify(deck)));
    setIsEditing(true);
  }, [deck]);

  const handleCancelEdit = useCallback(() => {
    setIsEditing(false);
    setDraft(null);
  }, []);

  /**
   * Record a change made on the slide itself.
   *
   * The path addresses the text on the active slide — e.g. ["banner_text"] or
   * ["findings", 0, "desc"] — so the change lands exactly where the
   * requester typed it.
   */
  const handleEditText = useCallback((path, value) => {
    setDraft((current) => {
      if (!current) return current;
      return applyPath(current, activeIndex, path, value);
    });
  }, [activeIndex]);

  /**
   * Save the draft: the changed text is sent to the backend, which re-renders
   * the deck into a new .pptx and returns the edited plan.
   */
  const handleSaveEdits = useCallback(async () => {
    if (!draft || !presentation?.filename) return;

    const edits = diffDeck(deck, draft);
    if (!edits.length) {
      setIsEditing(false);
      setDraft(null);
      return;
    }

    setIsSaving(true);
    setError("");
    setNotice("");

    try {
      const result = await editPresentation(presentation.filename, edits);

      setDeck(result.deck || null);
      setPresentation((current) => ({
        ...(current || {}),
        filename: result.filename || current?.filename,
        download_url: result.download_url || current?.download_url,
        deck: result.deck,
      }));
      setDraft(null);
      setIsEditing(false);
      setNotice(
        `Edits saved — ${result.applied?.length || 0} change${
          (result.applied?.length || 0) === 1 ? "" : "s"
        } applied and the deck re-rendered.`
      );
    } catch (err) {
      setError(getErrorMessage(err));
    } finally {
      setIsSaving(false);
    }
  }, [deck, draft, presentation]);

  const handleDownload = useCallback(async () => {
    if (!presentation?.download_url) return;

    setIsDownloading(true);
    setDownloadError("");

    try {
      const blob = await downloadPresentation(presentation.download_url);
      const objectUrl = window.URL.createObjectURL(blob);
      const anchor = document.createElement("a");
      anchor.href = objectUrl;
      anchor.download = presentation.filename || "presentation.pptx";
      document.body.appendChild(anchor);
      anchor.click();
      document.body.removeChild(anchor);
      // Revoke on the next tick so the browser has started the download.
      window.setTimeout(() => window.URL.revokeObjectURL(objectUrl), 0);
      setIsExportOpen(false);
    } catch (err) {
      setDownloadError(getErrorMessage(err));
    } finally {
      setIsDownloading(false);
    }
  }, [presentation]);

  return (
    <section className="rounded-xl border border-slate-200/80 bg-surface shadow-sm">
      <PresentationToolbar
        isGenerating={isGenerating}
        hasDeck={Boolean(presentation?.download_url)}
        onGenerate={handleGenerate}
        onRegenerate={() => {
          setError("");
          setIsSuggesting(true);
        }}
        onEdit={() => {
          setIsSuggesting(false);
          handleOpenEditor();
        }}
        onExport={() => {
          setDownloadError("");
          setIsExportOpen(true);
        }}
      />

      <div className="px-5 py-4">
        {isGenerating && (
          <div className="rounded-xl border border-blue-100 bg-slate-50/70 p-4">
            <p className="mb-3 text-[11px] font-semibold uppercase tracking-wider text-slate-400">
              Building your presentation
            </p>
            <StageIndicator currentStage={currentStage} failed={failedStage} />
          </div>
        )}

        {!isGenerating && error && (
          <p className="rounded-lg border border-rose-200 bg-rose-50 px-3 py-2 text-xs text-rose-700">
            {error}
          </p>
        )}

        {!isGenerating && notice && !error && (
          <p className="rounded-lg border border-emerald-200 bg-emerald-50 px-3 py-2 text-xs text-emerald-700">
            {notice}
          </p>
        )}

        {!isGenerating && !deck && !error && (
          <p className="rounded-lg border border-dashed border-slate-300 bg-slate-50/70 px-4 py-5 text-center text-xs text-slate-500">
            {hasDataset
              ? "Click “Generate Presentation” and the slides preview here automatically."
              : "Upload a dataset above, then generate a presentation from it."}
          </p>
        )}

        {isSuggesting && deck && (
          <div className="mt-3">
            <SuggestionsPanel
              value={suggestions}
              onChange={setSuggestions}
              onSubmit={handleRegenerate}
              onCancel={() => {
                setIsSuggesting(false);
                setSuggestions("");
              }}
              isGenerating={isGenerating}
            />
          </div>
        )}

        {isEditing && (
          <div className="mt-3 flex flex-wrap items-center justify-between gap-2 rounded-xl border border-blue-100 bg-blue-50/60 px-4 py-2.5">
            <p className="text-[11px] text-slate-600">
              <span className="font-semibold text-slate-700">Editing the slide.</span>{" "}
              Click any text on the slide to change it. The charts and the KPI
              tiles stay as the data dictates.
            </p>
            <div className="flex items-center gap-2">
              <button
                type="button"
                onClick={handleCancelEdit}
                disabled={isSaving}
                className="rounded-lg border border-slate-300 bg-surface px-3 py-1.5 text-xs font-semibold text-slate-600 transition-colors hover:bg-slate-50 disabled:cursor-not-allowed disabled:opacity-50"
              >
                Cancel
              </button>
              <button
                type="button"
                onClick={handleSaveEdits}
                disabled={isSaving || !hasPendingEdits}
                className="rounded-lg bg-blue-600 px-3 py-1.5 text-xs font-semibold text-on-accent shadow-sm transition-colors hover:bg-blue-700 disabled:cursor-not-allowed disabled:opacity-50"
              >
                {isSaving ? "Saving…" : "Save Changes"}
              </button>
            </div>
          </div>
        )}
      </div>

      {previewDeck && (
        // The deck area gets a viewport-relative height so the slide preview
        // can expand to fill the screen instead of sitting in a short band.
        <div className="flex h-[80vh] min-h-[560px] border-t border-slate-200">
          <SlideThumbnailRail
            slides={slides}
            activeIndex={activeIndex}
            onSelect={setActiveIndex}
            deck={previewDeck}
            themeName={settings?.generation?.default_theme}
          />
          <SlidePreview
            slide={activeSlide}
            slideNumber={activeIndex + 1}
            totalSlides={slides.length}
            onPrev={() => setActiveIndex((index) => Math.max(0, index - 1))}
            onNext={() => setActiveIndex((index) => Math.min(slides.length - 1, index + 1))}
            editing={isEditing}
            onEdit={handleEditText}
            deck={previewDeck}
            themeName={settings?.generation?.default_theme}
          />
        </div>
      )}

      <ExportDialog
        open={isExportOpen}
        filename={presentation?.filename}
        downloadUrl={presentation?.download_url}
        slideCount={slides.length}
        isDownloading={isDownloading}
        error={downloadError}
        onDownload={handleDownload}
        onClose={() => setIsExportOpen(false)}
      />
    </section>
  );
}
