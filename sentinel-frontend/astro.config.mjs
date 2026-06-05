import { defineConfig } from 'astro/config';

export default defineConfig({
  // Build to static files that FastAPI can serve
  output: 'static',
  build: {
    assets: '_assets',
  },
});
