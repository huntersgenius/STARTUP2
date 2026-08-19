import type { Config } from 'tailwindcss';

const config: Config = {
  content: ['./src/**/*.{ts,tsx}'],
  theme: {
    extend: {
      colors: {
        brand: { DEFAULT: '#00695c', dark: '#004d40' },
        danger: '#b3261e',
        warn: '#b25b00',
        ok: '#1b7f4b',
      },
    },
  },
  plugins: [],
};

export default config;
