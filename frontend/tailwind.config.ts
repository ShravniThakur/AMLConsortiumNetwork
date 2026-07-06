import type { Config } from "tailwindcss";
const config: Config = {
  content: ["./app/**/*.{ts,tsx}", "./lib/**/*.{ts,tsx}"],
  theme: { 
    extend: {
      colors: {
        midnight: {
          DEFAULT: '#0a0a0a',
          lighter: '#1a1a1a',
          card: '#121212',
          border: '#333333',
        },
        mint: {
          DEFAULT: '#7bf1a8',
          hover: '#5ee994',
          dark: '#1e3b2b',
        },
        gold: {
          DEFAULT: '#d4af37',
          hover: '#e5c158',
          dark: '#3b321a',
        }
      }
    } 
  },
  plugins: [],
};
export default config;
