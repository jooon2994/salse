/** @type {import('tailwindcss').Config} */
module.exports = {
  darkMode: 'class',
  content: ["./templates/**/*.html"],
  theme: {
    extend: {
      colors: {
        'custom-blue': {
          light: '#3b82f6', // A nice blue for light mode
          DEFAULT: '#2563eb',
          dark: '#1e40af',  // A deeper blue for dark mode
        },
        'light-bg': '#ffffff',
        'light-text': '#1f2937',
        'dark-bg': '#111827',
        'dark-text': '#f9fafb',
      },
    },
  },
  plugins: [],
}