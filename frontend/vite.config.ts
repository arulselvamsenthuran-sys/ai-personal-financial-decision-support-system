import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

// https://vite.dev/config/
export default defineConfig({
  plugins: [react()],
  server: {
    // Rewrite all non-asset paths back to index.html so the SPA can handle
    // OAuth callback routes like /auth/callback/google.
    fs: {
      strict: false,
    },
  },
})
