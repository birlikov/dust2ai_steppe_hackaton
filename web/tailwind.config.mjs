/** @type {import('tailwindcss').Config} */
export default {
  content: ["./src/**/*.{astro,html,js,jsx,md,mdx,svelte,ts,tsx,vue}"],
  theme: {
    extend: {
      colors: {
        "happy-blue": {
          900: "#0E2A3C",
          700: "#1B4868",
          500: "#3B7BA8",
          200: "#BFD8E8",
        },
        cream: {
          50: "#FBF6E8",
          100: "#F4ECD3",
          200: "#E9DBB4",
        },
        "accent-coral": "#E08066",
        "accent-green": "#6E9D74",
        "text-primary": "#1A1816",
        "text-on-blue": "#FBF6E8",
      },
      fontFamily: {
        display: ['"Cormorant Garamond"', "Georgia", "serif"],
        body: ["Inter", "system-ui", "sans-serif"],
      },
      fontSize: {
        "display-1": ["48px", { lineHeight: "1.05" }],
        "display-2": ["32px", { lineHeight: "1.15" }],
        "display-3": ["22px", { lineHeight: "1.25" }],
        base: ["16px", { lineHeight: "1.6" }],
        sm: ["13px", { lineHeight: "1.5" }],
      },
      borderColor: {
        DEFAULT: "rgba(14,42,60,0.20)",
      },
    },
  },
  plugins: [],
};
