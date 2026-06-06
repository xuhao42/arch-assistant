// Vue 前端入口：加载全局样式并把主应用挂载到 index.html 的 #app。
import { createApp } from 'vue'
import './style.css'
import App from './App.vue'

// createApp 只在浏览器端执行，Vite 会从这里开始构建依赖图。
createApp(App).mount('#app')
