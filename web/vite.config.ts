import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// https://vite.dev/config/
export default defineConfig({
  plugins: [react()],
  server: {
    // Im Dev-Modus laeuft die Oberflaeche auf 5173, das Backend auf 8000.
    // Der Proxy haelt beide same-origin, sodass keine CORS-Freigabe noetig ist.
    proxy: {
      '/api': {
        target: 'http://127.0.0.1:8000',
        changeOrigin: false,
      },
    },
  },
})
