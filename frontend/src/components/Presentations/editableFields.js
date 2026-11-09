// Which fields of which slide type the requester may edit, and how to apply
// an edit to a draft deck.
//
// This mirrors the backend's EDITABLE_FIELDS map (src/deck_editor.py): the
// slide structure, the chart data and the KPI tiles are computed from the
// dataset, so only the narrative text is the requester's to change.
//
// An edit is addressed by a *path* — a list of keys into a slide, e.g.
// ["banner_text"], ["findings", 0, "desc"] or ["insights", 2].

export const EDITABLE_FIELDS = {
  title: ["title", "subtitle", "banner_label", "banner_text"],
  summary: ["title", "category", "findings"],
  chart: ["title", "category", "caption"],
  insights: ["title", "category", "insights", "recommendations"],
};

/** The editable fields of a slide type, or an empty list for an unknown type. */
export function editableFieldsFor(slide) {
  if (!slide?.type) return [];
  return EDITABLE_FIELDS[slide.type] || [];
}

/**
 * Set the value at `path` inside one slide, returning a new deck.
 *
 * The deck is never mutated: the editor works on a draft, and the draft is
 * what the preview renders.
 *
 * The path addresses the text on the slide: ["banner_text"] for a plain
 * field, ["findings", 0, "desc"] for a finding's text, and ["insights", 2]
 * for a bullet.
 */
export function applyPath(deck, slideIndex, path, value) {
  if (!deck || !Array.isArray(path) || !path.length) return deck;

  const slide = deck.slides?.[slideIndex];
  if (!slide) return deck;

  const [head, ...rest] = path;
  const nextSlide = { ...slide };

  if (rest.length === 0) {
    nextSlide[head] = value;
  } else if (head === "findings") {
    // A finding is an object: ["findings", 0, "title"] or ["findings", 0, "desc"].
    const list = Array.isArray(slide.findings) ? slide.findings : [];
    const index = rest[0];
    if (typeof index !== "number" || index < 0 || index >= list.length) return deck;

    const copy = list.slice();
    const item = { ...(copy[index] || {}) };
    item[rest[1]] = value;
    copy[index] = item;
    nextSlide.findings = copy;
  } else if (head === "insights" || head === "recommendations") {
    // A bullet is a plain string: ["insights", 2].
    const list = Array.isArray(slide[head]) ? slide[head] : [];
    const index = rest[0];
    if (typeof index !== "number" || index < 0 || index >= list.length) return deck;

    const copy = list.slice();
    copy[index] = value;
    nextSlide[head] = copy;
  } else {
    return deck;
  }

  const slides = deck.slides.slice();
  slides[slideIndex] = nextSlide;
  return { ...deck, slides };
}

/**
 * The edits that turn `saved` into `draft`, for the editable fields only.
 *
 * The whole plan is never sent to the backend — only the text that actually
 * changed, addressed by slide number and field name.
 */
export function diffDeck(saved, draft) {
  const edits = [];
  const savedSlides = saved?.slides || [];
  const draftSlides = draft?.slides || [];

  draftSlides.forEach((draftSlide, index) => {
    const savedSlide = savedSlides[index];
    if (!savedSlide) return;

    editableFieldsFor(draftSlide).forEach((field) => {
      const before = savedSlide[field];
      const after = draftSlide[field];
      if (JSON.stringify(before ?? null) !== JSON.stringify(after ?? null)) {
        edits.push({ slide: index + 1, field, value: after });
      }
    });
  });

  return edits;
}
