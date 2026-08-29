/** @type {import('tailwindcss').Config} */
export default {
  content: [
    "./index.html",
    "./src/**/*.{js,ts,jsx,tsx}",
  ],
  theme: {
    extend: {
      colors: {
        primary: "#111111",
        secondary: "#FAFAFA",
        border: "#E5E5E5",
        textPrimary: "#111111",
        textSecondary: "#6B7280",
        hoverBg: "#F5F5F5",
        success: "#16A34A",
        warning: "#D97706",
        danger: "#DC2626",
      },
      borderRadius: {
        'custom': '2px',
      },
      boxShadow: {
        'soft': 'none',
        'premium': 'none',
      },
      fontFamily: {
        sans: ['Inter', 'sans-serif'],
      },
    },
  },
  plugins: [],
}
