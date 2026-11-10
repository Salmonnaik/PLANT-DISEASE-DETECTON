/** @type {import('tailwindcss').Config} */

/**
 * Design system for the dashboard.
 *
 * The palette is built around two greens - `leaf` for the agricultural identity
 * and `bark` as a green-tinted neutral for text and surfaces - plus red/amber
 * for disease and uncertainty. Defining them here (instead of scattering hex
 * values through components) is what keeps a disease the same colour in the
 * sidebar badge, the result card and every chart.
 */
export default {
  content: ['./index.html', './src/**/*.{js,ts,jsx,tsx}'],
  theme: {
    extend: {
      colors: {
        leaf: {
          50: '#f0fdf4',
          100: '#dcfce7',
          200: '#bbf7d0',
          300: '#86efac',
          400: '#4ade80',
          500: '#22c55e',
          600: '#16a34a',
          700: '#15803d',
          800: '#166534',
          900: '#14532d',
          950: '#082f18',
        },
        bark: {
          50: '#f6f7f6',
          100: '#e3e8e4',
          200: '#c7d1c9',
          300: '#9faea3',
          400: '#75876f',
          500: '#587055',
          600: '#415640',
          700: '#334434',
          800: '#26332a',
          900: '#1a241d',
          950: '#0d1410',
        },
        harvest: {
          50: '#fffbeb',
          100: '#fef3c7',
          300: '#fcd34d',
          500: '#f59e0b',
          600: '#d97706',
          700: '#b45309',
        },
        blight: {
          50: '#fef2f2',
          100: '#fee2e2',
          300: '#fca5a5',
          500: '#ef4444',
          600: '#dc2626',
          700: '#b91c1c',
        },
      },
      fontFamily: {
        sans: [
          'Inter',
          'ui-sans-serif',
          'system-ui',
          '-apple-system',
          'Segoe UI',
          'Roboto',
          'Helvetica Neue',
          'Arial',
          'sans-serif',
        ],
        mono: ['JetBrains Mono', 'ui-monospace', 'SFMono-Regular', 'Consolas', 'monospace'],
      },
      fontSize: {
        '2xs': ['0.6875rem', { lineHeight: '1rem' }],
      },
      boxShadow: {
        card: '0 1px 2px 0 rgb(13 20 16 / 0.04), 0 4px 16px -2px rgb(13 20 16 / 0.06)',
        'card-hover': '0 2px 4px 0 rgb(13 20 16 / 0.06), 0 12px 28px -4px rgb(13 20 16 / 0.12)',
        panel: '0 24px 48px -12px rgb(13 20 16 / 0.18)',
        'glow-leaf': '0 0 0 1px rgb(22 163 74 / 0.18), 0 8px 24px -6px rgb(22 163 74 / 0.35)',
        'inner-top': 'inset 0 1px 0 0 rgb(255 255 255 / 0.08)',
      },
      backgroundImage: {
        'leaf-gradient': 'linear-gradient(135deg, #16a34a 0%, #15803d 45%, #14532d 100%)',
        'leaf-gradient-soft': 'linear-gradient(135deg, #f0fdf4 0%, #dcfce7 55%, #bbf7d0 100%)',
        'hero-mesh':
          'radial-gradient(at 12% 18%, rgb(34 197 94 / 0.22) 0px, transparent 55%), ' +
          'radial-gradient(at 88% 8%, rgb(21 128 61 / 0.26) 0px, transparent 50%), ' +
          'radial-gradient(at 70% 92%, rgb(13 148 136 / 0.18) 0px, transparent 48%)',
        'grid-faint':
          'linear-gradient(to right, rgb(13 20 16 / 0.045) 1px, transparent 1px), ' +
          'linear-gradient(to bottom, rgb(13 20 16 / 0.045) 1px, transparent 1px)',
      },
      backgroundSize: {
        'grid-24': '24px 24px',
      },
      borderRadius: {
        '4xl': '2rem',
      },
      keyframes: {
        'fade-in': {
          from: { opacity: '0' },
          to: { opacity: '1' },
        },
        'fade-in-up': {
          from: { opacity: '0', transform: 'translateY(12px)' },
          to: { opacity: '1', transform: 'translateY(0)' },
        },
        'fade-in-left': {
          from: { opacity: '0', transform: 'translateX(-12px)' },
          to: { opacity: '1', transform: 'translateX(0)' },
        },
        'scale-in': {
          from: { opacity: '0', transform: 'scale(0.96)' },
          to: { opacity: '1', transform: 'scale(1)' },
        },
        'pulse-ring': {
          '0%': { transform: 'scale(0.85)', opacity: '0.7' },
          '70%': { transform: 'scale(1.6)', opacity: '0' },
          '100%': { transform: 'scale(1.6)', opacity: '0' },
        },
        shimmer: {
          '100%': { transform: 'translateX(100%)' },
        },
        'bar-grow': {
          from: { transform: 'scaleX(0)' },
          to: { transform: 'scaleX(1)' },
        },
        'scan-sweep': {
          '0%': { top: '0%', opacity: '0.1' },
          '50%': { opacity: '0.85' },
          '100%': { top: '100%', opacity: '0.1' },
        },
        float: {
          '0%, 100%': { transform: 'translateY(0)' },
          '50%': { transform: 'translateY(-8px)' },
        },
      },
      animation: {
        'fade-in': 'fade-in 0.35s ease-out both',
        'fade-in-up': 'fade-in-up 0.45s cubic-bezier(0.22, 1, 0.36, 1) both',
        'fade-in-left': 'fade-in-left 0.4s cubic-bezier(0.22, 1, 0.36, 1) both',
        'scale-in': 'scale-in 0.3s cubic-bezier(0.22, 1, 0.36, 1) both',
        'pulse-ring': 'pulse-ring 2s cubic-bezier(0.24, 0, 0.38, 1) infinite',
        shimmer: 'shimmer 1.8s infinite',
        'bar-grow': 'bar-grow 0.8s cubic-bezier(0.22, 1, 0.36, 1) both',
        'scan-sweep': 'scan-sweep 2.2s ease-in-out infinite',
        float: 'float 6s ease-in-out infinite',
      },
      transitionTimingFunction: {
        spring: 'cubic-bezier(0.22, 1, 0.36, 1)',
      },
    },
  },
  plugins: [],
};
