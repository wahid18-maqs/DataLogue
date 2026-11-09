// Drives the dashboard presentation flow against a running backend to verify
// the end-to-end behaviour: generate -> poll -> preview -> download.
//
// Requires the backend on http://localhost:8130.
// Run: node scripts/workspace-integration-check.jsx

import React from "react";
import { renderToStaticMarkup } from "react-dom/server";

import SlideCanvas from "../src/components/Presentations/SlideCanvas.jsx";
import AssistantSidebar from "../src/components/AssistantSidebar.jsx";
import { generatePresentation, getPresentationJob, downloadPresentation, editPresentation, uploadDataset, askAssistant } from "../src/services/api.js";

const API = "http://localhost:8130";

const failures = [];
function check(name, condition, detail = "") {
  if (condition) {
    console.log(`  PASS  ${name}`);
  } else {
    failures.push(name);
    console.log(`  FAIL  ${name} ${detail}`);
  }
}

/**
 * Poll a generation job until it finishes.
 *
 * A deck build may call the LLM, and a large model can take a minute or
 * more to answer, so the wait is generous: 600 iterations at 500ms.
 */
async function pollUntilComplete(jobId) {
  let state = null;
  for (let i = 0; i < 600; i += 1) {
    state = await getPresentationJob(jobId);
    if (state.status !== "running") break;
    await new Promise((r) => setTimeout(r, 500));
  }
  return state;
}

async function main() {
  console.log("\n[1] Generate via the API service (file upload)");
  const csv = await (await fetch(`${API}/datasets`)).json();
  check("GET /datasets returns datasets", Array.isArray(csv.datasets) && csv.datasets.length > 0);

  const job = await generatePresentation({ datasetId: csv.datasets[0].dataset_id });
  check("generatePresentation returns a job id", Boolean(job.job_id));
  check("generatePresentation returns stages", job.stages?.length === 6, JSON.stringify(job.stages));

  console.log("\n[2] Poll the job to completion");
  const state = await pollUntilComplete(job.job_id);
  check("Job completes", state?.status === "completed", state?.error || "");
  check("Job exposes a deck plan", Boolean(state?.deck));
  check("Deck has slides", state?.deck?.slide_count >= 4, String(state?.deck?.slide_count));
  check("Deck slides carry an index and title",
    state?.deck?.slides?.every((s) => s.index && s.title) ?? false);
  check("Deck slides carry a type",
    state?.deck?.slides?.every((s) => ["title", "summary", "chart", "insights"].includes(s.type)) ?? false);
  check("Chart slides carry categories and series",
    state?.deck?.slides?.filter((s) => s.type === "chart")
      .every((s) => Array.isArray(s.categories) && Array.isArray(s.series) && s.series.length > 0) ?? false);
  check("Title slide carries KPI tiles", (state?.deck?.slides?.[0]?.kpis?.length ?? 0) > 0);

  console.log("\n[3] Download the real PPTX through the service");
  const blob = await downloadPresentation(state.download_url);
  // The service always returns a Blob (browser and Node alike).
  check("Download returns a Blob", blob instanceof Blob, Object.prototype.toString.call(blob));
  check("Downloaded file is non-empty", blob.size > 10000, String(blob.size));

  const bytes = new Uint8Array(await blob.arrayBuffer());
  check("Downloaded bytes are a real PPTX (PK zip header)", bytes[0] === 0x50 && bytes[1] === 0x4b);
  check("Downloaded file name matches the job", state.filename.endsWith(".pptx"));

  console.log("\n[4] Error surface for a missing presentation");
  try {
    await downloadPresentation("/presentations/download/nope-does-not-exist.pptx");
    check("Missing file raises an error", false, "expected a throw");
  } catch (error) {
    check("Missing file raises an error", Boolean(error?.message), error?.message);
    check("Missing file error is user-readable", /no longer available|HTTP/i.test(error.message), error.message);
  }

  console.log("\n[5] Dashboard flow: upload -> auto-generate from the active dataset");
  const salesCsv = [
    "Date,Category,Region,Sales,Quantity,Customer,Status",
    "2025-01-05,Technology,North,1200,4,Acme,Completed",
    "2025-01-18,Office,South,860,7,Globex,Completed",
    "2025-02-03,Technology,East,1540,5,Initech,Completed",
    "2025-02-21,Office,West,720,3,Umbrella,Pending",
    "2025-03-07,Technology,North,1980,6,Acme,Completed",
    "2025-03-25,Furniture,South,1430,2,Globex,Completed",
    "2025-04-02,Office,East,980,5,Initech,Completed",
    "2025-04-19,Technology,West,2210,8,Umbrella,Completed",
  ].join("\n");

  const form = new FormData();
  form.append("file", new Blob([salesCsv], { type: "text/csv" }), "dashboard_sales.csv");
  const uploaded = await uploadDataset(form.get("file"));
  check("Dashboard upload succeeds", Boolean(uploaded?.stored_filename), JSON.stringify(uploaded));

  // The dashboard button calls generatePresentation() with no source at all,
  // so the backend must fall back to the active session dataset.
  const activeJob = await generatePresentation();
  check("Active-session generation starts", Boolean(activeJob?.job_id));

  const activeState = await pollUntilComplete(activeJob.job_id);
  check("Active-session job completes", activeState?.status === "completed", activeState?.error || "");
  check("Active-session deck has slides", (activeState?.deck?.slide_count ?? 0) >= 4);

  console.log("\n[6] Every slide in the generated deck renders a preview");
  const slides = activeState?.deck?.slides || [];
  let previewFailures = 0;
  for (const slide of slides) {
    const html = renderToStaticMarkup(<SlideCanvas slide={slide} />);
    if (!html || html.length < 50) previewFailures += 1;
  }
  check("All generated slides render a preview", previewFailures === 0, `${previewFailures} failed`);

  const activeBlob = await downloadPresentation(activeState.download_url);
  const activeBytes = new Uint8Array(await activeBlob.arrayBuffer());
  check("Dashboard-generated file is a real PPTX",
    activeBytes[0] === 0x50 && activeBytes[1] === 0x4b);

  console.log("\n[7] Backend dataset_id path (still supported by the API)");
  const listed = await (await fetch(`${API}/datasets`)).json();
  const pick = listed.datasets[0];
  const pickedJob = await generatePresentation({ datasetId: pick.dataset_id });
  const pickedState = await pollUntilComplete(pickedJob.job_id);
  check("Picked-dataset job completes", pickedState?.status === "completed", pickedState?.error || "");
  check("Picked-dataset deck has slides", (pickedState?.deck?.slide_count ?? 0) >= 4);

  console.log("\n[8] Regenerate with the requester's suggestions");
  const suggestion = "Lead with the highest-value segment and use a cautious tone.";
  const regenJob = await generatePresentation({ suggestions: suggestion });
  check("Regenerate returns a job id", Boolean(regenJob?.job_id));
  const regenState = await pollUntilComplete(regenJob.job_id);
  check("Regenerate job completes", regenState?.status === "completed", regenState?.error || "");
  check("Regenerated deck has slides", (regenState?.deck?.slide_count ?? 0) >= 4);
  check("Regenerated deck records its narrative source",
    ["agent", "template"].includes(regenState?.deck?.narrative_source),
    String(regenState?.deck?.narrative_source));
  const regenSlides = regenState?.deck?.slides || [];
  const regenHtml = regenSlides.length
    ? renderToStaticMarkup(<SlideCanvas slide={regenSlides[0]} />)
    : "";
  check("The regenerated first slide renders", regenHtml.length > 50, String(regenHtml.length));

  console.log("\n[9] Edit the deck live");
  const editableJob = await generatePresentation();
  const editableState = await pollUntilComplete(editableJob.job_id);
  check("The deck to edit completes", editableState?.status === "completed", editableState?.error || "");
  const editableFilename = editableState?.filename;
  check("The deck has a file to edit", Boolean(editableFilename), String(editableFilename));

  const banner = editableState?.deck?.slides?.[0]?.banner_text || "";
  const editResult = await editPresentation(editableFilename, [
    { slide: 1, field: "banner_text", value: "Edited live by the requester." },
  ]);
  check("The edit is accepted", Boolean(editResult?.deck), JSON.stringify(editResult).slice(0, 120));
  check("The edit is reported as applied",
    editResult?.applied?.length === 1, JSON.stringify(editResult?.applied));
  check("The edited deck carries the new text",
    editResult?.deck?.slides?.[0]?.banner_text === "Edited live by the requester.",
    String(editResult?.deck?.slides?.[0]?.banner_text));
  check("The original text is gone",
    editResult?.deck?.slides?.[0]?.banner_text !== banner);
  check("The edited deck points at a new file",
    editResult?.download_url && editResult?.download_url !== editableState?.download_url,
    String(editResult?.download_url));

  const editedBlob = await downloadPresentation(editResult.download_url);
  const editedBytes = new Uint8Array(await editedBlob.arrayBuffer());
  check("The edited file is a real PPTX",
    editedBytes[0] === 0x50 && editedBytes[1] === 0x4b);

  const editedHtml = renderToStaticMarkup(
    <SlideCanvas slide={editResult.deck.slides[0]} editing onEdit={() => {}} />
  );
  check("The edited slide renders as an editable slide",
    editedHtml.includes("Edited live by the requester.") && editedHtml.includes("contenteditable"),
    String(editedHtml.length));

  let rejected = null;
  try {
    await editPresentation(editableFilename, [
      { slide: 1, field: "series", value: "not editable" },
    ]);
  } catch (error) {
    rejected = error;
  }
  check("An edit to a computed field is rejected", Boolean(rejected), "expected a throw");
  check("The rejection is user-readable",
    /not an editable field/i.test(rejected?.response?.data?.detail || rejected?.message || ""),
    rejected?.response?.data?.detail || rejected?.message || "");

  console.log("\n[10] Ask the assistant a question about the data");
  const assistant = await askAssistant("What is the total sales?");
  check("The assistant answers", Boolean(assistant?.answer), JSON.stringify(assistant).slice(0, 160));
  check("The answer carries a confidence",
    ["low", "medium", "high"].includes(assistant?.confidence), String(assistant?.confidence));
  check("The answer carries supporting data",
    Boolean(assistant?.supporting_data), JSON.stringify(assistant?.supporting_data).slice(0, 120));
  check("The supporting data is a computed table",
    assistant?.supporting_data?.kind === "table"
    && Array.isArray(assistant?.supporting_data?.rows)
    && assistant?.supporting_data?.rows?.length > 0,
    JSON.stringify(assistant?.supporting_data).slice(0, 200));
  check("The query plan is reported",
    Boolean(assistant?.plan), JSON.stringify(assistant?.plan).slice(0, 160));

  const rendered = renderToStaticMarkup(
    <AssistantSidebar
      isOpen
      onClose={() => {}}
      dataset={{ stored_filename: "assistant_check.csv" }}
      hasDataset
      initialMessages={[{
        role: "assistant",
        content: assistant.answer,
        confidence: assistant.confidence,
        supportingData: assistant.supporting_data,
        plan: assistant.plan,
      }]}
    />
  );
  check("The answer renders in the panel",
    rendered.includes(assistant.answer.slice(0, 20)), String(rendered.length));
  check("The confidence renders in the panel",
    rendered.includes(`${assistant.confidence} confidence`), String(rendered.length));
  check("The supporting rows render in the panel",
    rendered.includes("Supporting data"), String(rendered.length));

  console.log(`\n${"=".repeat(50)}`);
  if (failures.length) {
    console.log(`FAILED: ${failures.length}`);
    failures.forEach((f) => console.log(`  - ${f}`));
    process.exit(1);
  }
  console.log("All workspace integration checks passed.");
}

main().catch((error) => {
  console.error("\nIntegration run failed:", error);
  process.exit(1);
});
