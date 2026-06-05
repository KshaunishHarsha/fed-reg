import { defineConfig } from 'astro/config';

export default defineConfig({
  output: 'static',
  build: {
    assets: '_assets',
  },
  vite: {
    server: {
      proxy: {
        '/phase3': 'http://localhost:8000',
        '/demo':   'http://localhost:8000',
        '/run':    'http://localhost:8000',
        '/health': 'http://localhost:8000',
      },
    },
  },
});
