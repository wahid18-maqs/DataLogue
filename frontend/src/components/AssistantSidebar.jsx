// The right-hand AI Assistant panel.
//
// It answers questions about the active dataset. Every answer is computed
// over the data on the server — the panel shows the rows and numbers the
// answer was drawn from, so the user can check it.
//
// The panel is a drawer on small screens and a fixed column on large ones.

import { useCallback, useEffect, useRef, useState } from "react";
import { askAssistant, getErrorMessage, queryWorkbook } from "../services/api";

// The questions offered when the panel is empty, so the user can start
// without having to think of one.
const SUGGESTED_QUESTIONS = [
  "What is the total sales?",
  "What are the top 5 categories by sales?",
  "How many orders are in each region?",
];

// How many messages are kept in the thread.
const MAX_MESSAGES = 40;

const CONFIDENCE_STYLES = {
  high: "bg-emerald-100 text-emerald-700",
  medium: "bg-amber-100 text-amber-700",
  low: "bg-fill text-slate-600",
};

function ConfidenceBadge({ confidence }) {
  const level = (confidence || "low").toLowerCase();
  return (
    <span
      className={`rounded-full px-2 py-0.5 text-[9px] font-bold uppercase tracking-wider ${
        CONFIDENCE_STYLES[level] || CONFIDENCE_STYLES.low
      }`}
    >
      {level} confidence
    </span>
  );
}

/**
 * The rows and numbers the answer was drawn from.
 *
 * Showing them is the point: the answer comes from a computation on the
 * real data, and the user can see the computation's output.
 */
function SupportingData({ data }) {
  // The rows are open by default: seeing the numbers is the point of the
  // panel, so the user can check the answer without a click.
  const [isOpen, setIsOpen] = useState(true);

  if (!data) return null;

  // Verified facts, not computed rows: this is what backs an answer about
  // the assistant itself. There is no heading — the answer is the answer,
  // and this is the evidence behind it.
  if (data.kind === "facts" && Array.isArray(data.facts)) {
    if (!data.facts.length) return null;
    return (
      <dl className="mt-2 space-y-1 rounded-lg border border-slate-200 bg-slate-50 px-3 py-2">
        {data.facts.map((fact) => (
          <div key={fact.label} className="flex gap-2">
            <dt className="w-20 shrink-0 text-[10px] font-semibold text-slate-500">
              {fact.label}
            </dt>
            <dd className="min-w-0 flex-1 break-words font-mono text-[11px] text-slate-700">
              {fact.value}
            </dd>
          </div>
        ))}
      </dl>
    );
  }

  const rows = Array.isArray(data.rows) ? data.rows : null;
  const columns = Array.isArray(data.columns) ? data.columns : null;

  if (!rows || !columns || !rows.length) {
    // A scalar or an empty table: show the value plainly.
    const value = data.value;
    if (value === undefined || value === null) return null;
    return (
      <div className="mt-2 rounded-lg border border-slate-200 bg-slate-50 px-3 py-2">
        <p className="text-[9px] font-bold uppercase tracking-wider text-slate-400">
          Computed value
        </p>
        <p className="mt-1 font-mono text-sm font-semibold text-slate-800">
          {String(value)}
        </p>
      </div>
    );
  }

  return (
    <div className="mt-2 rounded-lg border border-slate-200 bg-surface">
      <button
        type="button"
        onClick={() => setIsOpen((open) => !open)}
        className="flex w-full items-center justify-between gap-2 px-3 py-2 text-left transition-colors hover:bg-slate-50"
      >
        <span className="text-[9px] font-bold uppercase tracking-wider text-slate-400">
          Supporting data ({data.row_count ?? rows.length}
          {data.truncated ? "+" : ""} rows)
        </span>
        <span className="text-[10px] font-semibold text-blue-600">
          {isOpen ? "Hide" : "Show"}
        </span>
      </button>

      {isOpen && (
        <div className="overflow-x-auto border-t border-slate-200">
          <table className="w-full text-left text-[11px]">
            <thead>
              <tr className="bg-slate-50">
                {columns.map((column) => (
                  <th
                    key={column}
                    className="whitespace-nowrap px-2.5 py-1.5 font-semibold text-slate-500"
                  >
                    {column}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {rows.map((row, index) => (
                <tr key={index} className="border-t border-slate-100">
                  {columns.map((column) => (
                    <td
                      key={column}
                      className="whitespace-nowrap px-2.5 py-1.5 font-mono text-slate-700"
                    >
                      {row[column] === null || row[column] === undefined
                        ? "—"
                        : String(row[column])}
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

/** The query plan that was run, so the user can see how the answer was made. */
function PlanDetails({ plan }) {
  const [isOpen, setIsOpen] = useState(false);

  if (!plan || typeof plan !== "object") return null;

  const hasSomething = Object.values(plan).some(
    (value) => value !== null && value !== undefined && !(Array.isArray(value) && !value.length)
  );
  if (!hasSomething) return null;

  return (
    <details className="mt-2">
      <summary className="cursor-pointer text-[10px] font-semibold text-slate-400 hover:text-slate-600">
        How this was computed
      </summary>
      <pre className="mt-1.5 overflow-x-auto rounded-lg bg-code px-2.5 py-2 text-[10px] leading-relaxed text-code-text">
        {JSON.stringify(plan, null, 2)}
      </pre>
    </details>
  );
}

function Message({ message, showSupportingData = true }) {
  if (message.role === "user") {
    return (
      <div className="flex justify-end">
        <p className="max-w-[85%] rounded-2xl rounded-br-sm bg-blue-600 px-3.5 py-2 text-xs leading-relaxed text-on-accent">
          {message.content}
        </p>
      </div>
    );
  }

  return (
    <div className="flex flex-col gap-2">
      <div className="flex items-center gap-2">
        <span className="flex h-6 w-6 shrink-0 items-center justify-center rounded-lg bg-blue-600 text-on-accent">
          <svg className="h-3.5 w-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
            <path
              strokeLinecap="round"
              strokeLinejoin="round"
              strokeWidth={2}
              d="M13 10V3L4 14h7v7l9-11h-7z"
            />
          </svg>
        </span>
        <span className="text-[10px] font-semibold uppercase tracking-wider text-slate-400">
          Assistant
        </span>
        {message.confidence && <ConfidenceBadge confidence={message.confidence} />}
      </div>

      <div className="max-w-[92%] rounded-2xl rounded-tl-sm border border-slate-200 bg-surface px-3.5 py-2.5">
        {message.error ? (
          <p className="text-xs leading-relaxed text-rose-600">{message.content}</p>
        ) : message.refused ? (
          <p className="whitespace-pre-line text-xs leading-relaxed text-slate-600">
            {message.content}
          </p>
        ) : (
          <p className="whitespace-pre-line text-xs leading-relaxed text-slate-700">
            {message.content}
          </p>
        )}

        {showSupportingData && message.supportingData?.kind !== "facts" && (
          <SupportingData data={message.supportingData} />
        )}
        <PlanDetails plan={message.plan} />
      </div>
    </div>
  );
}

export default function AssistantSidebar({
  isOpen,
  onClose,
  dataset = null,
  hasDataset = false,
  workbook = null,
  initialMessages = [],
  // The requester can turn the supporting rows off in Settings. The answer
  // is still given; the evidence behind it is what goes away.
  showSupportingData = true,
}) {
  const [messages, setMessages] = useState(initialMessages);
  const [question, setQuestion] = useState("");
  const [isThinking, setIsThinking] = useState(false);
  const scrollRef = useRef(null);
  const inputRef = useRef(null);

  // Focus the field when the panel opens, so the user can type straight away.
  useEffect(() => {
    if (isOpen) inputRef.current?.focus();
  }, [isOpen]);

  // A new dataset means the old thread is about different data.
  useEffect(() => {
    setMessages([]);
  }, [dataset?.stored_filename]);

  // So does a change of workbook: the answers were about the old one.
  useEffect(() => {
    setMessages([]);
  }, [workbook?.id]);

  // Keep the newest message in view.
  useEffect(() => {
    const node = scrollRef.current;
    if (node) node.scrollTop = node.scrollHeight;
  }, [messages, isThinking]);

  const ask = useCallback(
    async (text) => {
      const trimmed = (text || "").trim();
      if (!trimmed || isThinking) return;

      setQuestion("");
      setMessages((current) => [
        ...current,
        { role: "user", content: trimmed },
        { role: "assistant", content: "", pending: true },
      ]);
      setIsThinking(true);

      try {
        // A chosen workbook is queried through its own endpoint, so the
        // answer is computed over that workbook's sheet.
        const result = workbook?.id
          ? await queryWorkbook(workbook.id, trimmed, workbook.active_sheet_id)
          : await askAssistant(trimmed);

        setMessages((current) => {
          const next = current.slice();
          next[next.length - 1] = {
            role: "assistant",
            content: result.answer || "I could not answer that.",
            confidence: result.confidence,
            supportingData: result.supporting_data,
            plan: result.plan,
            // An out-of-scope answer comes back as a normal response with
            // the refusal already worded, rather than as an error.
            refused: Boolean(result.refused),
          };
          return next.slice(-MAX_MESSAGES);
        });
      } catch (err) {
        // A refusal by the guardrails comes back as a 400 with a message
        // meant for the user. That is the assistant declining, not a
        // failure, so it is shown as a refusal rather than as an error.
        const status = err?.response?.status;
        const refused = status === 400 || status === 403;
        setMessages((current) => {
          const next = current.slice();
          next[next.length - 1] = {
            role: "assistant",
            content: getErrorMessage(err),
            error: !refused,
            refused,
          };
          return next;
        });
      } finally {
        setIsThinking(false);
      }
    },
    [isThinking, workbook]
  );

  const handleSubmit = useCallback(
    (event) => {
      event.preventDefault();
      ask(question);
    },
    [ask, question]
  );

  return (
    <>
      {/* The scrim behind the panel, on small screens. */}
      {isOpen && (
        <div
          className="fixed inset-0 z-30 bg-scrim/30 backdrop-blur-[2px] lg:hidden"
          onClick={onClose}
          aria-hidden="true"
        />
      )}

      <aside
        className={`fixed top-0 bottom-0 right-0 z-40 flex w-full shrink-0 flex-col border-l border-slate-200 bg-drawer shadow-2xl transition-transform duration-300 sm:w-[26rem] lg:sticky lg:top-0 lg:z-auto lg:h-screen lg:w-[26rem] lg:translate-x-0 lg:shadow-none ${
          isOpen ? "translate-x-0" : "translate-x-full lg:hidden"
        }`}
        aria-label="AI Assistant"
      >
        <header className="flex shrink-0 items-center justify-between gap-3 border-b border-slate-200 bg-surface px-4 py-3">
          <div className="flex min-w-0 items-center gap-2.5">
            <span className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-blue-600 text-on-accent">
              <svg className="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                <path
                  strokeLinecap="round"
                  strokeLinejoin="round"
                  strokeWidth={2}
                  d="M13 10V3L4 14h7v7l9-11h-7z"
                />
              </svg>
            </span>
            <div className="min-w-0">
              <h2 className="truncate text-sm font-bold text-slate-800">AI Assistant</h2>
              <p className="truncate text-[10px] text-slate-400">
                {workbook?.file_name
                  ? `Answering from ${workbook.file_name}`
                  : hasDataset
                    ? "Answers computed from your data"
                    : "Upload a dataset to begin"}
              </p>
            </div>
          </div>

          <button
            type="button"
            onClick={onClose}
            title="Close the assistant"
            className="flex h-7 w-7 shrink-0 items-center justify-center rounded-lg text-slate-400 transition-colors hover:bg-slate-100 hover:text-slate-600"
          >
            ✕
          </button>
        </header>

        {/* The thread. */}
        <div ref={scrollRef} className="min-h-0 flex-1 space-y-4 overflow-y-auto px-4 py-4">
          {!messages.length && (
            <div className="rounded-xl border border-dashed border-slate-300 bg-surface px-4 py-5 text-center">
              <p className="text-xs font-semibold text-slate-700">
                {hasDataset ? "Ask about your data" : "No dataset yet"}
              </p>
              <p className="mt-1 text-[11px] leading-relaxed text-slate-400">
                {hasDataset
                  ? "Every answer is computed from your rows, and the numbers behind it are shown so you can check."
                  : "Upload a CSV or Excel file and this assistant will answer questions about it."}
              </p>
            </div>
          )}

          {messages.map((message, index) => (
            <Message key={index} message={message} showSupportingData={showSupportingData} />
          ))}

          {isThinking && (
            <div className="flex items-center gap-2 text-[11px] text-slate-400">
              <span className="flex h-6 w-6 items-center justify-center rounded-lg bg-fill text-slate-500">
                <svg className="h-3.5 w-3.5 animate-pulse" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                  <path
                    strokeLinecap="round"
                    strokeLinejoin="round"
                    strokeWidth={2}
                    d="M13 10V3L4 14h7v7l9-11h-7z"
                  />
                </svg>
              </span>
              Computing the answer from your data…
            </div>
          )}

          {!messages.length && hasDataset && (
            <div className="space-y-2">
              <p className="text-[10px] font-semibold uppercase tracking-wider text-slate-400">
                Try asking
              </p>
              {SUGGESTED_QUESTIONS.map((suggestion) => (
                <button
                  key={suggestion}
                  type="button"
                  onClick={() => ask(suggestion)}
                  className="block w-full rounded-lg border border-slate-200 bg-surface px-3 py-2 text-left text-xs text-slate-600 transition-colors hover:border-blue-300 hover:bg-blue-50/50 hover:text-blue-700"
                >
                  {suggestion}
                </button>
              ))}
            </div>
          )}
        </div>

        {/* The composer. */}
        <form
          onSubmit={handleSubmit}
          className="shrink-0 border-t border-slate-200 bg-surface px-4 py-3"
        >
          <div className="flex items-end gap-2">
            <textarea
              ref={inputRef}
              value={question}
              onChange={(event) => setQuestion(event.target.value)}
              onKeyDown={(event) => {
                if (event.key === "Enter" && !event.shiftKey) {
                  event.preventDefault();
                  ask(question);
                }
              }}
              rows={2}
              disabled={!hasDataset || isThinking}
              placeholder={
                hasDataset ? "Ask about your data…" : "Upload a dataset first"
              }
              className="min-h-[2.75rem] flex-1 resize-none rounded-xl border border-slate-300 bg-surface px-3 py-2 text-xs text-slate-700 shadow-sm outline-none transition-colors placeholder:text-slate-400 focus:border-blue-400 focus:ring-2 focus:ring-blue-100 disabled:cursor-not-allowed disabled:bg-slate-50"
            />
            <button
              type="submit"
              disabled={!hasDataset || isThinking || !question.trim()}
              title="Ask"
              className="flex h-11 w-11 shrink-0 items-center justify-center rounded-xl bg-blue-600 text-on-accent shadow-sm transition-colors hover:bg-blue-700 disabled:cursor-not-allowed disabled:opacity-40"
            >
              <svg className="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                <path
                  strokeLinecap="round"
                  strokeLinejoin="round"
                  strokeWidth={2}
                  d="M5 12h14m-7-7l7 7-7 7"
                />
              </svg>
            </button>
          </div>
        </form>
      </aside>
    </>
  );
}
