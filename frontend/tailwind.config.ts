import type { Config } from "tailwindcss";
const config: Config = {
  content: ["./app/**/*.{ts,tsx}", "./lib/**/*.{ts,tsx}"],
  theme: {
    extend: {
      fontFamily: {
        sans: ["Inter", "system-ui", "sans-serif"],
      },
      colors: {
        // Warm beige background (main canvas)
        panel: {
          DEFAULT: "#f0efeb",
          dark: "#e8e6e1",
          border: "#dddad4",
        },
        // Dark charcoal sidebar
        sidebar: {
          DEFAULT: "#1c1c1e",
          hover: "#2a2a2d",
          active: "#2d2d30",
          border: "#3a3a3d",
          text: "#8e8e93",
          "text-active": "#ffffff",
        },
        // White cards
        card: {
          DEFAULT: "#ffffff",
          hover: "#fafaf8",
          border: "#e8e5e0",
          shadow: "rgba(0,0,0,0.06)",
        },
        // Right panel
        rpanel: {
          DEFAULT: "#ffffff",
          border: "#eeebe5",
        },
        // Status / accent colors (softened)
        mint: {
          DEFAULT: "#3cb371",
          light: "#e8f5ee",
          dark: "#267a4e",
        },
        gold: {
          DEFAULT: "#c8a84b",
          light: "#fdf6e3",
          hover: "#d4b55e",
          dark: "#8a7030",
        },
        danger: {
          DEFAULT: "#e05252",
          light: "#fdeaea",
        },
        olive: {
          DEFAULT: "#6b7c5c",
          light: "#eef1ea",
          card: "#c5cfb8",
        },
        periwinkle: {
          DEFAULT: "#7b82d4",
          light: "#eeeffe",
          card: "#b8bcee",
        },
        // Legacy (keep for any missed references)
        midnight: {
          DEFAULT: "#1c1c1e",
          lighter: "#2a2a2d",
          card: "#242427",
          border: "#3a3a3d",
        },
      },
      boxShadow: {
        card: "0 2px 12px rgba(0,0,0,0.06), 0 1px 3px rgba(0,0,0,0.04)",
        "card-hover": "0 6px 24px rgba(0,0,0,0.10), 0 2px 6px rgba(0,0,0,0.06)",
        sidebar: "2px 0 12px rgba(0,0,0,0.15)",
      },
      borderRadius: {
        "2xl": "1rem",
        "3xl": "1.25rem",
      },
    },
  },
  plugins: [],
};
export default config;
