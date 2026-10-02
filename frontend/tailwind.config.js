/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        canvas: "#F4F5F7",
        paper: "#FFFFFF",
        ink: "#172033",
        slate: "#586174",
        mute: "#8A93A3",
        rule: "#DFE3E9",
        "rule-strong": "#C6CDD7",
        navy: { DEFAULT: "#1C3D6E", 700: "#15305A", 50: "#EEF2F8", 100: "#DCE5F1" },
        positive: { DEFAULT: "#1B6E4A", soft: "#E7F2EC" },
        caution: { DEFAULT: "#93570A", soft: "#FAF0DF" },
        negative: { DEFAULT: "#AE3A2D", soft: "#FAE9E6" },
        rework: { DEFAULT: "#5A3E9B", soft: "#EFEBF8" },
        neutral: { DEFAULT: "#586174", soft: "#EEF0F3" },
      },
      fontFamily: {
        sans: ['"IBM Plex Sans"', "system-ui", "-apple-system", "Segoe UI", "sans-serif"],
        serif: ['"Source Serif 4"', "Georgia", "Cambria", "serif"],
      },
      fontSize: {
        "2xs": ["0.6875rem", { lineHeight: "1rem" }],
      },
      borderRadius: {
        panel: "6px",
      },
      maxWidth: {
        page: "76rem",
      },
    },
  },
  plugins: [],
};
