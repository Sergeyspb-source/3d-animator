import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';

// dev: `npm run dev` on 5173 with the API of a running server (SF3D_API, default 7890)
const api = process.env.SF3D_API || 'http://127.0.0.1:7890';
export default defineConfig({
  plugins: [react()],
  server: { port: 5173, proxy: { '/api': { target: api, changeOrigin: false } } },
  build: { outDir: 'dist', emptyOutDir: true, chunkSizeWarningLimit: 1600 },
});
