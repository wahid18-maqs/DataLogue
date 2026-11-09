# Frontend

React + Vite + Tailwind CSS frontend for Datalogue.

### Resizable chart cards

Every chart card carries a grip in its bottom-right corner. Drag it to resize
the card with the mouse; double-click the grip to reset it. Sizes are stored
in `localStorage`, so a tuned layout survives a reload.

| Component | Role |
|-----------|------|
| `Resizable.jsx` | `usePanelSize` (persisted size state) and `ResizeHandle` (the drag grip) |
| `ResizableCard.jsx` | Wrapper that applies a card's size and renders the grip |

The chart layouts use flex-wrap rather than CSS grid so each card can be sized
independently — a resized card is no longer tied to a grid track.

## Pages

- **Dashboard** — upload a CSV or Excel file, explore KPIs, charts and the
  latest records. The upload card collapses to a slim bar once a dataset is
  loaded, so the charts get the room. The *Recent Orders & Activity* table
  shows the first 10 records inline; the remainder is listed behind a
  *Show next N* dropdown. Below that table sits a **Generate Presentation**
  panel: one click builds a deck from
  the active dataset and previews every slide in place. The AI Summary and AI
  Chat panels are not shown in the UI.

There is no separate *Presentations* page — presentations are generated from
the dashboard and previewed there.

### Presentation components

| Component | Role |
|-----------|------|
| `DashboardPresentation.jsx` | Source selection, generation, polling, slide preview, export |
| `Presentations/PresentationToolbar.jsx` | *Generate Presentation*, *Regenerate Presentation*, *Edit*, *Export PPTX* |
| `Presentations/SuggestionsPanel.jsx` | The field the requester types their suggestions into |
| `Presentations/StageIndicator.jsx` | The five generation stages and their progress |
| `Presentations/SlideThumbnailRail.jsx` | Left rail of slide thumbnails |
| `Presentations/ScaledSlide.jsx` | Fits a slide into the space it is given |
| `Presentations/SlidePreview.jsx` | Large 16:9 slide canvas |
| `Presentations/SlideCanvas.jsx` | Renders one slide from the backend deck plan, editable in place |
| `Presentations/editableFields.js` | Which fields of which slide type may be edited |
| `Presentations/ExportDialog.jsx` | Export confirmation and download |

### How the dashboard generate button works

1. The panel's *Generate Presentation* button calls
   `POST /presentations/generate` with no source, so the backend uses the
   dataset already active on the dashboard.
2. The client polls `GET /presentations/jobs/{job_id}` and renders the stage
   the server reports (`reading_spreadsheet` → `detecting_columns` →
   `analyzing_data` → `writing_narrative` → `generating_slides` →
   `preparing_powerpoint`). The stages reflect real work, not a timer.
3. The response includes a `deck` plan describing every slide. The preview
   renders that plan as a thumbnail rail plus a large 16:9 canvas, so it
   matches the `.pptx` the backend writes.

### How regeneration works

Once a deck exists, the toolbar shows a *Regenerate Presentation* button.
Clicking it reveals the suggestions panel, where the requester types what
they would like changed. Submitting sends the text to the backend as the
`suggestions` field of `POST /presentations/generate`, and the deck agent
rewrites the narrative to follow it.

The suggestions shape the wording, emphasis and angle of the prose. They
cannot change the slide structure, the charts, the KPI tiles or any figure —
those are computed from the data — and the panel says so.

The panel is a separate step rather than an always-visible field so the
regeneration cost is never incurred by accident: each regeneration is one
more provider request.

### How live editing works

Once a deck exists, the toolbar shows an *Edit* button. Clicking it puts the
**slide itself** into edit mode: the requester clicks a heading, a finding
or a bullet and types directly on the slide, exactly where it will appear in
the exported file. The text keeps the slide's own typography, so editing
never changes the layout.

The changes are kept in a draft until the requester presses *Save Changes*.
Saving sends only the text that actually changed to
`POST /presentations/{filename}/edit`, and the backend re-renders the deck
into a new `.pptx` and returns the edited plan — so the export always
matches what is on screen.

The deck is addressed by the file it was written to, not by the job that
produced it. The job registry lives in memory and is emptied when the
server restarts, but the deck file and its plan do not, so a deck can still
be edited after a restart.

Only the *narrative* text is editable. The slide structure, the chart data,
the categories and the KPI tiles are computed from the dataset, so an edit
that tries to touch one of them is rejected and the reason is reported back.

### How the slide preview scales

Slides are authored at a fixed 1280×720 (16:9) design size. `ScaledSlide`
measures the space it is given and applies one uniform `transform: scale()` to
the whole slide, so the padding, KPI tiles, fonts and the executive summary
box all grow together and the slide keeps its exact proportions. The preview
pane measures itself and passes the scale down, which is what lets the
*Previous / Slide X of N / Next* controls sit directly beneath the slide at
any size. The deck area is `80vh` tall, so the canvas fills most of the
viewport on a large display instead of sitting in a short band.
4. *Export PPTX* downloads the server-generated file via
   `GET /presentations/download/{filename}`.

### How generation works

1. `POST /presentations/generate` starts the job on the server and returns a
   `job_id`. The source is a directly uploaded file, a previously uploaded
   `dataset_id`, or the active dataset.
2. The client polls `GET /presentations/jobs/{job_id}` and renders the stage
   the server reports (`reading_spreadsheet` → `detecting_columns` →
   `analyzing_data` → `writing_narrative` → `generating_slides` →
   `preparing_powerpoint`). The stages reflect real work, not a timer.
3. The response includes a `deck` plan describing every slide. The preview
   renders that plan, so it matches the `.pptx` the backend writes.
4. *Export PPTX* downloads the server-generated file via
   `GET /presentations/download/{filename}`.

All API calls live in `src/services/api.js`; components never call the API
directly.

## Commands

```bash
npm install
npm run dev              # dev server on :5173
npm run build            # production build
npm run check:components # render every component and assert on the output
npm run check:integration # end-to-end generate -> poll -> download against a live backend
```

`check:integration` expects the backend on `http://localhost:8130`:

```bash
cd ../backend && .venv/bin/python3 -m uvicorn app:app --port 8130
```

Set `VITE_API_BASE_URL` if the backend does not run on `http://localhost:8000`.
