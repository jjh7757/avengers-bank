import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

// 개발 서버는 /api 요청을 FastAPI(8000)로 넘긴다. 브라우저는 같은 출처로 보내므로 CORS 설정이 필요 없다.
// 다른 포트의 백엔드에 붙이려면 API_TARGET=http://127.0.0.1:8001 처럼 지정한다.
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      '/api': {
        target: process.env.API_TARGET ?? 'http://127.0.0.1:8000',
        changeOrigin: true,
        rewrite: (path) => path.replace(/^\/api/, ''),
      },
    },
  },
})
