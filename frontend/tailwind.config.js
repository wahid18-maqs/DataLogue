/** Tailwind CSS configuration. */

/**
 * The palette is driven by CSS custom properties, so the whole app can be
 * flipped between light and dark by changing the variables on the root
 * element.
 *
 * The colours are stored as raw red/green/blue channels rather than as hex,
 * which is what lets Tailwind's opacity modifiers (`bg-slate-50/70`) keep
 * working against a variable.
 */
const channel = (name) => `rgb(var(--${name}) / <alpha-value>)`;

/**
 * A hue whose shades are all driven by variables.
 *
 * The light values are Tailwind's own; the dark values are in index.css,
 * where the scale is turned over so the tints go dark and the text shades
 * go light.
 */
const hue = (name, shades) => {
  const out = {};
  for (const [shade, key] of Object.entries(shades)) {
    out[shade] = channel(`${name}-${key}`);
  }
  return out;
};

export default {
  content: ["./index.html", "./src/**/*.{js,jsx}"],
  darkMode: ["class", '[data-theme="dark"]'],
  theme: {
    extend: {
      colors: {
        page: channel("page"),
        surface: channel("surface"),
        // Raised chrome panels such as the assistant drawer. The sidebar uses
        // the page color so it joins the main content as one continuous shell.
        panel: channel("panel"),
        "panel-alt": channel("panel-alt"),
        drawer: channel("drawer"),
        // The small filled shapes — a progress track, an inactive step, a
        // badge. They are not hairlines, so they are not the border colour.
        fill: channel("fill"),
        "text-primary": channel("text-primary"),
        "text-secondary": channel("text-secondary"),
        "text-muted": channel("text-muted"),
        // The dimming layer behind a modal, and the code block. Both stay
        // dark whatever the theme, so they get their own tokens.
        scrim: channel("scrim"),
        code: channel("code"),
        "code-text": channel("code-text"),
        // The text on a solid accent. It is white on a light theme, and
        // near-black on a dark one, where the accents are brighter.
        "on-accent": channel("on-accent"),
        ringOffsetColor: {
          page: channel("page"),
        },
        slate: hue("slate", {
          50: "50",
          100: "100",
          200: "200",
          300: "300",
          400: "400",
          500: "500",
          600: "600",
          700: "700",
          800: "800",
          900: "900",
        }),
        blue: hue("blue", {
          50: "50",
          100: "100",
          200: "200",
          300: "300",
          400: "400",
          500: "500",
          600: "600",
          700: "700",
        }),
        rose: hue("rose", {
          50: "50",
          100: "100",
          200: "200",
          500: "500",
          600: "600",
          700: "700",
        }),
        emerald: hue("emerald", {
          50: "50",
          100: "100",
          200: "200",
          500: "500",
          600: "600",
          700: "700",
        }),
        amber: hue("amber", {
          50: "50",
          100: "100",
          200: "200",
          600: "600",
          700: "700",
          800: "800",
        }),
        indigo: hue("indigo", {
          50: "50",
          500: "500",
          600: "600",
          700: "700",
        }),
      },
    },
  },
  plugins: [],
};
