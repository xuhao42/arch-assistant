// Vite 类型声明：让 TypeScript 识别 import.meta.env 等客户端类型。
/// <reference types="vite/client" />

// 允许 .vue 单文件组件被 TypeScript import，并按 Vue 组件类型处理。
declare module '*.vue' {
  import type { DefineComponent } from 'vue'
  const component: DefineComponent<{}, {}, any>
  export default component
}
