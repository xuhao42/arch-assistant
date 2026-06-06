// Vite 配置：负责 Vue 插件、Tailwind 插件和开发服务器代理。
import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'
import tailwindcss from '@tailwindcss/vite'

export default defineConfig({
  plugins: [vue(), tailwindcss()],
  server: {
    port: 5173,
    proxy: {
      '/api': {
        // 开发模式下把 API 请求代理到 API Gateway，避免浏览器跨域问题。
        target: 'http://localhost:3000',
        changeOrigin: true,
      }
    }
  }
})
