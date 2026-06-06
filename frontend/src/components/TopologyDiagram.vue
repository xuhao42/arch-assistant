<script setup lang="ts">
// 架构拓扑组件：优先渲染后端按需求生成的动态拓扑，缺失时回退到内置静态 SVG 模板。
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'

export interface TopologyNode {
  // 后端拓扑节点：x/y 是 SVG 画布坐标，hint 用于展示节点职责摘要。
  id: string
  label: string
  type: string
  hint?: string
  x: number
  y: number
}

export interface TopologyEdge {
  // 后端拓扑边：from/to 引用节点 id，type 决定线条颜色和虚实样式。
  from: string
  to: string
  label?: string
  type?: string
}

export interface RequirementTopology {
  // 完整需求拓扑模型，由 Agent Runtime 根据首选架构和需求特征生成。
  title: string
  style_key: string
  arch_name: string
  requirements?: string[]
  nodes: TopologyNode[]
  edges: TopologyEdge[]
}

const props = defineProps<{ archName: string; topology?: RequirementTopology | null }>()
const isExpanded = ref(false)
const diagramFrame = ref<HTMLElement | null>(null)

const hasDynamicTopology = computed(() => Boolean(props.topology?.nodes?.length))
// dynamicNodeMap 和 dynamicEdges 把后端边的 from/to id 解析为真实节点，便于计算贝塞尔路径。
const dynamicNodeMap = computed(() => new Map((props.topology?.nodes || []).map(node => [node.id, node])))
const dynamicEdges = computed(() => (props.topology?.edges || [])
  .map(edge => ({ ...edge, source: dynamicNodeMap.value.get(edge.from), target: dynamicNodeMap.value.get(edge.to) }))
  .filter(edge => edge.source && edge.target))

function nodeFill(type: string) {
  // 根据节点类型选择渐变填充，让存储、事件、守卫和参与者在图上可区分。
  if (type === 'store') return 'url(#dyn-green)'
  if (type === 'agent') return 'url(#dyn-violet)'
  if (type === 'event') return 'url(#dyn-amber)'
  if (type === 'guard') return 'url(#dyn-rose)'
  if (type === 'actor' || type === 'endpoint' || type === 'output') return 'url(#dyn-blue)'
  return 'url(#dyn-cyan)'
}

function edgeStroke(type = 'sync') {
  // 根据边类型选择颜色：事件/流、命令、消息和同步调用分别强调。
  if (type === 'event' || type === 'stream') return '#34d399'
  if (type === 'command') return '#fbbf24'
  if (type === 'message') return '#c4b5fd'
  return '#67e8f9'
}

function shortText(value = '', limit = 13) {
  // SVG 文本不自动换行，过长标签需要截断，避免节点和边标签重叠。
  return value.length > limit ? `${value.slice(0, limit - 1)}…` : value
}

function edgePath(edge: { source?: TopologyNode; target?: TopologyNode }) {
  // 用三次贝塞尔曲线连接节点，竖向距离较小时加大控制点避免线条贴边。
  if (!edge.source || !edge.target) return ''
  const dx = Math.abs(edge.target.x - edge.source.x)
  if (dx < 80) {
    const midY = (edge.source.y + edge.target.y) / 2
    return `M${edge.source.x} ${edge.source.y} C${edge.source.x + 120} ${midY}, ${edge.target.x - 120} ${midY}, ${edge.target.x} ${edge.target.y}`
  }
  const offset = edge.source.y === edge.target.y ? 0 : 28
  return `M${edge.source.x} ${edge.source.y} C${edge.source.x + dx / 2} ${edge.source.y - offset}, ${edge.target.x - dx / 2} ${edge.target.y + offset}, ${edge.target.x} ${edge.target.y}`
}

const defs = `
  <defs>
    <pattern id="grid" width="24" height="24" patternUnits="userSpaceOnUse">
      <path d="M24 0H0V24" fill="none" stroke="#1e3a5f" stroke-width=".7" opacity=".35"/>
    </pattern>
    <marker id="arrow-cyan" markerWidth="10" markerHeight="10" refX="8.5" refY="5" orient="auto">
      <path d="M0,0 L10,5 L0,10 Z" fill="#67e8f9"/>
    </marker>
    <marker id="arrow-amber" markerWidth="10" markerHeight="10" refX="8.5" refY="5" orient="auto">
      <path d="M0,0 L10,5 L0,10 Z" fill="#fbbf24"/>
    </marker>
    <marker id="arrow-green" markerWidth="10" markerHeight="10" refX="8.5" refY="5" orient="auto">
      <path d="M0,0 L10,5 L0,10 Z" fill="#34d399"/>
    </marker>
    <marker id="arrow-violet" markerWidth="10" markerHeight="10" refX="8.5" refY="5" orient="auto">
      <path d="M0,0 L10,5 L0,10 Z" fill="#c4b5fd"/>
    </marker>
    <linearGradient id="bg-panel" x1="0" y1="0" x2="1" y2="1">
      <stop offset="0%" stop-color="#071426"/>
      <stop offset="58%" stop-color="#0b1930"/>
      <stop offset="100%" stop-color="#08111f"/>
    </linearGradient>
    <linearGradient id="node-blue" x1="0" x2="1">
      <stop offset="0%" stop-color="#0891b2"/>
      <stop offset="100%" stop-color="#2563eb"/>
    </linearGradient>
    <linearGradient id="node-amber" x1="0" x2="1">
      <stop offset="0%" stop-color="#b45309"/>
      <stop offset="100%" stop-color="#f59e0b"/>
    </linearGradient>
    <linearGradient id="node-green" x1="0" x2="1">
      <stop offset="0%" stop-color="#059669"/>
      <stop offset="100%" stop-color="#0d9488"/>
    </linearGradient>
    <linearGradient id="node-violet" x1="0" x2="1">
      <stop offset="0%" stop-color="#7c3aed"/>
      <stop offset="100%" stop-color="#4f46e5"/>
    </linearGradient>
    <linearGradient id="node-rose" x1="0" x2="1">
      <stop offset="0%" stop-color="#be123c"/>
      <stop offset="100%" stop-color="#e11d48"/>
    </linearGradient>
    <filter id="soft-shadow" x="-20%" y="-20%" width="140%" height="140%">
      <feDropShadow dx="0" dy="10" stdDeviation="8" flood-color="#020617" flood-opacity=".42"/>
    </filter>
    <filter id="glow-cyan" x="-40%" y="-40%" width="180%" height="180%">
      <feGaussianBlur stdDeviation="3" result="blur"/>
      <feColorMatrix in="blur" type="matrix" values="0 0 0 0 0.2 0 0 0 0 0.85 0 0 0 0 0.95 0 0 0 .55 0"/>
      <feMerge><feMergeNode/><feMergeNode in="SourceGraphic"/></feMerge>
    </filter>
  </defs>
`

function shell(title: string, subtitle: string, body: string) {
  // 静态模板外壳：统一背景、标题栏和图例，body 只负责具体架构图形。
  return `
    ${defs}
    <rect x="16" y="16" width="928" height="508" rx="22" fill="url(#bg-panel)" stroke="#244564"/>
    <rect x="16" y="16" width="928" height="508" rx="22" fill="url(#grid)" opacity=".55"/>
    <rect x="44" y="42" width="872" height="58" rx="16" fill="rgba(12,31,53,.86)" stroke="#315b78"/>
    <text x="68" y="68" fill="#e0f2fe" font-size="17" font-weight="900">${title}</text>
    <text x="68" y="90" fill="#93c5fd" font-size="12">${subtitle}</text>
    ${body}
    <g transform="translate(694 466)">
      <rect x="0" y="0" width="202" height="34" rx="17" fill="#0f172a" stroke="#334155"/>
      <circle cx="18" cy="17" r="5" fill="#67e8f9"/><text x="30" y="21" fill="#cbd5e1" font-size="11">同步调用</text>
      <circle cx="94" cy="17" r="5" fill="#fbbf24"/><text x="106" y="21" fill="#cbd5e1" font-size="11">写入/命令</text>
      <circle cx="166" cy="17" r="5" fill="#34d399"/><text x="178" y="21" fill="#cbd5e1" font-size="11">事件/异步</text>
    </g>
  `
}

const diagrams: Record<string, string> = {
  event: shell('事件驱动架构拓扑', '发布订阅、异步解耦、实时消息与后续能力扩展', `
    <rect x="54" y="134" width="180" height="282" rx="18" fill="#0f1e33" stroke="#284b68"/>
    <text x="78" y="162" fill="#bae6fd" font-size="13" font-weight="800">生产端</text>
    <rect x="82" y="190" width="124" height="48" rx="14" fill="url(#node-blue)" filter="url(#soft-shadow)"/>
    <text x="144" y="219" text-anchor="middle" fill="#fff" font-size="13" font-weight="800">Web / App</text>
    <rect x="82" y="270" width="124" height="48" rx="14" fill="url(#node-blue)" filter="url(#soft-shadow)"/>
    <text x="144" y="299" text-anchor="middle" fill="#fff" font-size="13" font-weight="800">消息服务</text>
    <rect x="82" y="350" width="124" height="42" rx="13" fill="#172554" stroke="#3b82f6"/>
    <text x="144" y="376" text-anchor="middle" fill="#bfdbfe" font-size="12">Outbox</text>

    <rect x="352" y="196" width="256" height="96" rx="22" fill="url(#node-violet)" stroke="#c4b5fd" filter="url(#glow-cyan)"/>
    <text x="480" y="236" text-anchor="middle" fill="#fff" font-size="18" font-weight="900">Event Bus</text>
    <text x="480" y="260" text-anchor="middle" fill="#ddd6fe" font-size="12">Kafka / RabbitMQ / WebSocket Fanout</text>

    <rect x="720" y="134" width="180" height="282" rx="18" fill="#0f1e33" stroke="#284b68"/>
    <text x="744" y="162" fill="#bbf7d0" font-size="13" font-weight="800">消费端</text>
    <rect x="748" y="188" width="124" height="44" rx="13" fill="url(#node-green)" filter="url(#soft-shadow)"/>
    <text x="810" y="215" text-anchor="middle" fill="#fff" font-size="12" font-weight="800">通知推送</text>
    <rect x="748" y="254" width="124" height="44" rx="13" fill="url(#node-green)" filter="url(#soft-shadow)"/>
    <text x="810" y="281" text-anchor="middle" fill="#fff" font-size="12" font-weight="800">在线状态</text>
    <rect x="748" y="320" width="124" height="44" rx="13" fill="url(#node-green)" filter="url(#soft-shadow)"/>
    <text x="810" y="347" text-anchor="middle" fill="#fff" font-size="12" font-weight="800">视频通话</text>
    <rect x="748" y="386" width="124" height="42" rx="13" fill="#052e2b" stroke="#2dd4bf"/>
    <text x="810" y="412" text-anchor="middle" fill="#99f6e4" font-size="12">Read Model</text>

    <path d="M206 214 C282 210, 308 220, 352 232" fill="none" stroke="#67e8f9" stroke-width="2.4" marker-end="url(#arrow-cyan)"/>
    <path d="M206 294 C284 300, 316 270, 352 258" fill="none" stroke="#67e8f9" stroke-width="2.4" marker-end="url(#arrow-cyan)"/>
    <path d="M206 371 C290 382, 330 284, 352 270" fill="none" stroke="#fbbf24" stroke-width="2.2" marker-end="url(#arrow-amber)"/>
    <path d="M608 236 C664 206, 690 206, 748 210" fill="none" stroke="#34d399" stroke-width="2.3" marker-end="url(#arrow-green)"/>
    <path d="M608 250 C672 255, 696 273, 748 276" fill="none" stroke="#34d399" stroke-width="2.3" marker-end="url(#arrow-green)"/>
    <path d="M608 266 C672 306, 692 336, 748 342" fill="none" stroke="#34d399" stroke-width="2.3" marker-end="url(#arrow-green)"/>
    <path d="M608 281 C664 384, 702 404, 748 407" fill="none" stroke="#34d399" stroke-width="2.1" stroke-dasharray="7 6" marker-end="url(#arrow-green)"/>
  `),

  microservices: shell('微服务架构拓扑', '按业务能力拆分服务，独立部署、独立扩容、独立演进', `
    <rect x="74" y="136" width="812" height="64" rx="18" fill="#0f1e33" stroke="#315b78"/>
    <rect x="396" y="148" width="168" height="40" rx="14" fill="url(#node-blue)" filter="url(#soft-shadow)"/>
    <text x="480" y="173" text-anchor="middle" fill="#fff" font-size="14" font-weight="900">API Gateway</text>
    <rect x="92" y="246" width="150" height="76" rx="18" fill="url(#node-green)" filter="url(#soft-shadow)"/>
    <text x="167" y="279" text-anchor="middle" fill="#fff" font-size="14" font-weight="900">用户服务</text>
    <text x="167" y="299" text-anchor="middle" fill="#d1fae5" font-size="11">Profile / Auth</text>
    <rect x="298" y="246" width="150" height="76" rx="18" fill="url(#node-green)" filter="url(#soft-shadow)"/>
    <text x="373" y="279" text-anchor="middle" fill="#fff" font-size="14" font-weight="900">消息服务</text>
    <text x="373" y="299" text-anchor="middle" fill="#d1fae5" font-size="11">Chat / History</text>
    <rect x="504" y="246" width="150" height="76" rx="18" fill="url(#node-green)" filter="url(#soft-shadow)"/>
    <text x="579" y="279" text-anchor="middle" fill="#fff" font-size="14" font-weight="900">音视频服务</text>
    <text x="579" y="299" text-anchor="middle" fill="#d1fae5" font-size="11">Call / Media</text>
    <rect x="710" y="246" width="150" height="76" rx="18" fill="url(#node-green)" filter="url(#soft-shadow)"/>
    <text x="785" y="279" text-anchor="middle" fill="#fff" font-size="14" font-weight="900">通知服务</text>
    <text x="785" y="299" text-anchor="middle" fill="#d1fae5" font-size="11">Push / SMS</text>
    <rect x="104" y="380" width="744" height="48" rx="16" fill="#111c31" stroke="#334155"/>
    <text x="476" y="409" text-anchor="middle" fill="#cbd5e1" font-size="12">服务发现 · 配置中心 · 容器编排 · 可观测性 · 熔断限流</text>
    <path d="M480 188 L167 246 M480 188 L373 246 M480 188 L579 246 M480 188 L785 246" stroke="#67e8f9" stroke-width="2.2" marker-end="url(#arrow-cyan)"/>
    <path d="M167 322 L167 380 M373 322 L373 380 M579 322 L579 380 M785 322 L785 380" stroke="#34d399" stroke-width="2" stroke-dasharray="6 6" marker-end="url(#arrow-green)"/>
  `),

  cqrs: shell('CQRS 读写分离拓扑', '命令侧保证业务一致性，查询侧承接高频读取，通过事件投影同步读模型', `
    <rect x="74" y="134" width="172" height="286" rx="18" fill="#0f1e33" stroke="#284b68"/>
    <text x="102" y="164" fill="#bae6fd" font-size="13" font-weight="800">入口层</text>
    <rect x="103" y="202" width="114" height="52" rx="14" fill="url(#node-blue)" filter="url(#soft-shadow)"/>
    <text x="160" y="233" text-anchor="middle" fill="#fff" font-size="13" font-weight="800">Client API</text>
    <rect x="316" y="138" width="204" height="92" rx="20" fill="url(#node-amber)" filter="url(#soft-shadow)"/>
    <text x="418" y="176" text-anchor="middle" fill="#fff7ed" font-size="15" font-weight="900">命令处理层</text>
    <text x="418" y="199" text-anchor="middle" fill="#fde68a" font-size="12">Command / Domain</text>
    <rect x="316" y="302" width="204" height="70" rx="18" fill="#111c31" stroke="#f59e0b" filter="url(#soft-shadow)"/>
    <text x="418" y="332" text-anchor="middle" fill="#fde68a" font-size="14" font-weight="800">Write DB</text>
    <text x="418" y="354" text-anchor="middle" fill="#94a3b8" font-size="11">事务边界 / 审计日志</text>
    <rect x="650" y="138" width="204" height="92" rx="20" fill="url(#node-green)" filter="url(#soft-shadow)"/>
    <text x="752" y="176" text-anchor="middle" fill="#ecfdf5" font-size="15" font-weight="900">查询服务层</text>
    <text x="752" y="199" text-anchor="middle" fill="#a7f3d0" font-size="12">Query API / Read Model</text>
    <rect x="650" y="302" width="204" height="70" rx="18" fill="#111c31" stroke="#2dd4bf" filter="url(#soft-shadow)"/>
    <text x="752" y="332" text-anchor="middle" fill="#a7f3d0" font-size="14" font-weight="800">Read DB / Cache</text>
    <text x="752" y="354" text-anchor="middle" fill="#94a3b8" font-size="11">投影视图 / 聚合查询</text>
    <rect x="504" y="430" width="260" height="38" rx="19" fill="#312e81" stroke="#818cf8"/>
    <text x="634" y="454" text-anchor="middle" fill="#ddd6fe" font-size="12" font-weight="800">Domain Events / Projection</text>
    <path d="M217 218 C258 172, 282 164, 316 171" fill="none" stroke="#fbbf24" stroke-width="2.4" marker-end="url(#arrow-amber)"/>
    <path d="M217 236 C336 318, 534 138, 650 168" fill="none" stroke="#67e8f9" stroke-width="2.2" stroke-dasharray="7 6" marker-end="url(#arrow-cyan)"/>
    <path d="M418 230 L418 302" fill="none" stroke="#fbbf24" stroke-width="2.5" marker-end="url(#arrow-amber)"/>
    <path d="M752 230 L752 302" fill="none" stroke="#34d399" stroke-width="2.5" marker-end="url(#arrow-green)"/>
    <path d="M520 336 C585 365, 630 292, 650 336" fill="none" stroke="#fbbf24" stroke-width="2.2" stroke-dasharray="8 7" marker-end="url(#arrow-amber)"/>
    <path d="M418 372 C430 434, 480 450, 504 450" fill="none" stroke="#fbbf24" stroke-width="2" marker-end="url(#arrow-amber)"/>
    <path d="M764 430 C806 402, 816 374, 790 372" fill="none" stroke="#34d399" stroke-width="2" marker-end="url(#arrow-green)"/>
  `),

  pipe: shell('管道-过滤器架构拓扑', '将处理流程拆为可替换过滤器，适合转码、ETL、CI/CD 和批处理流水线', `
    <rect x="70" y="188" width="126" height="70" rx="18" fill="url(#node-blue)" filter="url(#soft-shadow)"/>
    <text x="133" y="229" text-anchor="middle" fill="#fff" font-size="14" font-weight="900">输入源</text>
    <rect x="260" y="174" width="128" height="98" rx="20" fill="url(#node-violet)" filter="url(#soft-shadow)"/>
    <text x="324" y="213" text-anchor="middle" fill="#fff" font-size="14" font-weight="900">过滤器 A</text>
    <text x="324" y="235" text-anchor="middle" fill="#ddd6fe" font-size="11">转码 / 清洗</text>
    <rect x="444" y="174" width="128" height="98" rx="20" fill="url(#node-violet)" filter="url(#soft-shadow)"/>
    <text x="508" y="213" text-anchor="middle" fill="#fff" font-size="14" font-weight="900">过滤器 B</text>
    <text x="508" y="235" text-anchor="middle" fill="#ddd6fe" font-size="11">水印 / 校验</text>
    <rect x="628" y="174" width="128" height="98" rx="20" fill="url(#node-violet)" filter="url(#soft-shadow)"/>
    <text x="692" y="213" text-anchor="middle" fill="#fff" font-size="14" font-weight="900">过滤器 C</text>
    <text x="692" y="235" text-anchor="middle" fill="#ddd6fe" font-size="11">审核 / 索引</text>
    <rect x="812" y="188" width="86" height="70" rx="18" fill="url(#node-green)" filter="url(#soft-shadow)"/>
    <text x="855" y="229" text-anchor="middle" fill="#fff" font-size="14" font-weight="900">输出</text>
    <path d="M196 223 L260 223 M388 223 L444 223 M572 223 L628 223 M756 223 L812 223" stroke="#67e8f9" stroke-width="2.6" marker-end="url(#arrow-cyan)"/>
    <rect x="238" y="344" width="520" height="54" rx="18" fill="#111c31" stroke="#334155"/>
    <text x="498" y="376" text-anchor="middle" fill="#cbd5e1" font-size="12">每个过滤器独立部署、独立扩容、独立替换，失败步骤可重试或补偿</text>
    <path d="M324 272 L324 344 M508 272 L508 344 M692 272 L692 344" stroke="#34d399" stroke-width="2" stroke-dasharray="6 6" marker-end="url(#arrow-green)"/>
  `),

  hexagonal: shell('六边形架构 / 端口适配器拓扑', '核心领域模型位于中心，外部系统通过端口与适配器接入', `
    <polygon points="480,142 604,213 604,354 480,426 356,354 356,213" fill="#111c31" stroke="#67e8f9" stroke-width="2.5" filter="url(#glow-cyan)"/>
    <text x="480" y="274" text-anchor="middle" fill="#e0f2fe" font-size="18" font-weight="900">Domain Core</text>
    <text x="480" y="298" text-anchor="middle" fill="#93c5fd" font-size="12">用例 · 实体 · 领域服务</text>
    <rect x="86" y="174" width="150" height="58" rx="16" fill="url(#node-blue)" filter="url(#soft-shadow)"/>
    <text x="161" y="208" text-anchor="middle" fill="#fff" font-size="13" font-weight="800">Web Adapter</text>
    <rect x="86" y="330" width="150" height="58" rx="16" fill="url(#node-green)" filter="url(#soft-shadow)"/>
    <text x="161" y="364" text-anchor="middle" fill="#fff" font-size="13" font-weight="800">DB Adapter</text>
    <rect x="724" y="174" width="150" height="58" rx="16" fill="url(#node-amber)" filter="url(#soft-shadow)"/>
    <text x="799" y="208" text-anchor="middle" fill="#fff" font-size="13" font-weight="800">Payment API</text>
    <rect x="724" y="330" width="150" height="58" rx="16" fill="url(#node-rose)" filter="url(#soft-shadow)"/>
    <text x="799" y="364" text-anchor="middle" fill="#fff" font-size="13" font-weight="800">Audit System</text>
    <path d="M236 203 L356 238 M236 359 L356 336 M604 238 L724 203 M604 336 L724 359" stroke="#67e8f9" stroke-width="2.3" marker-end="url(#arrow-cyan)"/>
    <text x="303" y="210" fill="#93c5fd" font-size="11">Input Port</text>
    <text x="303" y="390" fill="#93c5fd" font-size="11">Output Port</text>
    <text x="638" y="210" fill="#fde68a" font-size="11">Output Port</text>
    <text x="638" y="390" fill="#fecdd3" font-size="11">Audit Port</text>
  `),

  layered: shell('分层架构拓扑', '表示层、业务层、数据访问层逐层依赖，适合简单稳定的企业应用', `
    <rect x="164" y="132" width="632" height="70" rx="18" fill="url(#node-blue)" filter="url(#soft-shadow)"/>
    <text x="480" y="173" text-anchor="middle" fill="#fff" font-size="16" font-weight="900">表示层 / Controller / View</text>
    <rect x="164" y="238" width="632" height="70" rx="18" fill="url(#node-violet)" filter="url(#soft-shadow)"/>
    <text x="480" y="279" text-anchor="middle" fill="#fff" font-size="16" font-weight="900">业务逻辑层 / Service</text>
    <rect x="164" y="344" width="632" height="70" rx="18" fill="url(#node-green)" filter="url(#soft-shadow)"/>
    <text x="480" y="385" text-anchor="middle" fill="#fff" font-size="16" font-weight="900">数据访问层 / Repository / DAO</text>
    <path d="M480 202 L480 238 M480 308 L480 344" stroke="#67e8f9" stroke-width="2.6" marker-end="url(#arrow-cyan)"/>
    <text x="820" y="170" fill="#93c5fd" font-size="12">只依赖下层</text>
    <text x="820" y="276" fill="#c4b5fd" font-size="12">封装业务规则</text>
    <text x="820" y="382" fill="#a7f3d0" font-size="12">隔离数据库细节</text>
  `),

  default: shell('通用架构拓扑', '核心组件、接口、数据存储与外部集成关系', `
    <rect x="112" y="190" width="168" height="70" rx="18" fill="url(#node-blue)" filter="url(#soft-shadow)"/>
    <text x="196" y="231" text-anchor="middle" fill="#fff" font-size="15" font-weight="900">接口层</text>
    <rect x="396" y="166" width="168" height="118" rx="22" fill="url(#node-violet)" filter="url(#soft-shadow)"/>
    <text x="480" y="218" text-anchor="middle" fill="#fff" font-size="16" font-weight="900">核心组件</text>
    <text x="480" y="243" text-anchor="middle" fill="#ddd6fe" font-size="12">业务规则 / 编排</text>
    <rect x="680" y="190" width="168" height="70" rx="18" fill="url(#node-green)" filter="url(#soft-shadow)"/>
    <text x="764" y="231" text-anchor="middle" fill="#fff" font-size="15" font-weight="900">数据层</text>
    <path d="M280 225 L396 225 M564 225 L680 225" stroke="#67e8f9" stroke-width="2.5" marker-end="url(#arrow-cyan)"/>
    <rect x="260" y="352" width="440" height="54" rx="18" fill="#111c31" stroke="#334155"/>
    <text x="480" y="384" text-anchor="middle" fill="#cbd5e1" font-size="12">可按具体候选架构进一步细化为服务、事件、端口或处理管道</text>
  `),
}

function pickKey(name: string) {
  // 把候选架构名称映射到内置静态图模板键。
  const normalized = name.toLowerCase()
  if (normalized.includes('cqrs')) return 'cqrs'
  if (normalized.includes('microservice') || name.includes('微服务')) return 'microservices'
  if (normalized.includes('event') || name.includes('事件')) return 'event'
  if (normalized.includes('pipe') || name.includes('管道') || name.includes('过滤器')) return 'pipe'
  if (normalized.includes('hexagonal') || name.includes('六边形') || name.includes('端口适配器')) return 'hexagonal'
  if (normalized.includes('layered') || name.includes('分层')) return 'layered'
  return 'default'
}

const selectedSVG = computed(() => diagrams[pickKey(props.archName)] ?? diagrams.default)

async function openExpanded() {
  // 展开大图时优先请求浏览器全屏，失败也保留组件内放大状态。
  isExpanded.value = true
  await diagramFrame.value?.requestFullscreen?.()
}

function closeExpanded() {
  // 关闭大图时同步退出浏览器全屏，避免 UI 状态和 fullscreenElement 不一致。
  isExpanded.value = false
  if (document.fullscreenElement) {
    void document.exitFullscreen()
  }
}

function handleKeydown(event: KeyboardEvent) {
  // 支持 Escape 快捷关闭大图，符合常见弹层交互预期。
  if (event.key === 'Escape') closeExpanded()
}

function handleFullscreenChange() {
  // 用户按浏览器快捷键退出全屏时，同步更新组件展开状态。
  isExpanded.value = document.fullscreenElement === diagramFrame.value
}

onMounted(() => window.addEventListener('keydown', handleKeydown))
onMounted(() => document.addEventListener('fullscreenchange', handleFullscreenChange))
onBeforeUnmount(() => {
  // 组件卸载时移除全局监听，避免路由切换后残留事件处理器。
  window.removeEventListener('keydown', handleKeydown)
  document.removeEventListener('fullscreenchange', handleFullscreenChange)
})
</script>

<template>
  <section class="glass p-5 animate-in">
    <div class="mb-4">
      <p class="text-xs font-semibold uppercase tracking-[0.16em] text-cyan-200">Topology</p>
      <h3 class="mt-1 text-lg font-bold text-white">{{ topology?.title || '架构拓扑图' }}</h3>
      <p class="mt-1 text-xs text-slate-400">{{ archName }}</p>
    </div>
    <div
      ref="diagramFrame"
      class="diagram-frame topology-click-target overflow-hidden rounded-lg border border-white/10 bg-slate-950/50"
      :class="{ 'topology-expanded': isExpanded }"
      role="button"
      tabindex="0"
      :aria-label="isExpanded ? '关闭架构拓扑大图' : '查看架构拓扑大图'"
      @click="!isExpanded && openExpanded()"
      @keydown.enter.prevent="openExpanded"
      @keydown.space.prevent="openExpanded"
    >
      <div v-if="!isExpanded" class="topology-expand-hint">点击查看大图</div>
      <button v-if="isExpanded" class="topology-close-button" type="button" aria-label="关闭大图" @click.stop="closeExpanded">
        关闭
      </button>
      <svg v-if="hasDynamicTopology" viewBox="0 0 960 540" class="h-auto w-full topology-svg" role="img" aria-label="需求定制架构拓扑图">
        <defs>
          <marker id="dyn-arrow" markerWidth="10" markerHeight="10" refX="8.5" refY="5" orient="auto">
            <path d="M0,0 L10,5 L0,10 Z" fill="#67e8f9"/>
          </marker>
          <linearGradient id="dyn-bg" x1="0" y1="0" x2="1" y2="1">
            <stop offset="0%" stop-color="#071426"/>
            <stop offset="100%" stop-color="#0f172a"/>
          </linearGradient>
          <linearGradient id="dyn-blue" x1="0" x2="1"><stop offset="0%" stop-color="#0891b2"/><stop offset="100%" stop-color="#2563eb"/></linearGradient>
          <linearGradient id="dyn-cyan" x1="0" x2="1"><stop offset="0%" stop-color="#0e7490"/><stop offset="100%" stop-color="#14b8a6"/></linearGradient>
          <linearGradient id="dyn-green" x1="0" x2="1"><stop offset="0%" stop-color="#059669"/><stop offset="100%" stop-color="#0d9488"/></linearGradient>
          <linearGradient id="dyn-violet" x1="0" x2="1"><stop offset="0%" stop-color="#7c3aed"/><stop offset="100%" stop-color="#4f46e5"/></linearGradient>
          <linearGradient id="dyn-amber" x1="0" x2="1"><stop offset="0%" stop-color="#b45309"/><stop offset="100%" stop-color="#f59e0b"/></linearGradient>
          <linearGradient id="dyn-rose" x1="0" x2="1"><stop offset="0%" stop-color="#be123c"/><stop offset="100%" stop-color="#e11d48"/></linearGradient>
          <filter id="dyn-shadow" x="-20%" y="-20%" width="140%" height="140%">
            <feDropShadow dx="0" dy="10" stdDeviation="8" flood-color="#020617" flood-opacity=".42"/>
          </filter>
        </defs>

        <rect x="16" y="16" width="928" height="508" rx="22" fill="url(#dyn-bg)" stroke="#244564"/>
        <g opacity=".45">
          <path v-for="x in [64, 112, 160, 208, 256, 304, 352, 400, 448, 496, 544, 592, 640, 688, 736, 784, 832, 880]" :key="`vx-${x}`" :d="`M${x} 28V512`" stroke="#1e3a5f" stroke-width=".7"/>
          <path v-for="y in [64, 112, 160, 208, 256, 304, 352, 400, 448, 496]" :key="`hy-${y}`" :d="`M28 ${y}H932`" stroke="#1e3a5f" stroke-width=".7"/>
        </g>

        <g>
          <path
            v-for="edge in dynamicEdges"
            :key="`${edge.from}-${edge.to}-${edge.label}`"
            :d="edgePath(edge)"
            fill="none"
            :stroke="edgeStroke(edge.type)"
            stroke-width="2.4"
            stroke-linecap="round"
            marker-end="url(#dyn-arrow)"
            :stroke-dasharray="edge.type === 'event' || edge.type === 'message' ? '7 6' : undefined"
          />
          <text
            v-for="edge in dynamicEdges"
            :key="`${edge.from}-${edge.to}-${edge.label}-label`"
            :x="((edge.source?.x || 0) + (edge.target?.x || 0)) / 2"
            :y="((edge.source?.y || 0) + (edge.target?.y || 0)) / 2 - 10"
            text-anchor="middle"
            fill="#bae6fd"
            font-size="11"
          >
            {{ shortText(edge.label || '') }}
          </text>
        </g>

        <g v-for="node in topology?.nodes || []" :key="node.id" :transform="`translate(${node.x - 66} ${node.y - 30})`">
          <rect width="132" height="60" rx="14" :fill="nodeFill(node.type)" stroke="rgba(255,255,255,.28)" filter="url(#dyn-shadow)"/>
          <text x="66" y="28" text-anchor="middle" fill="#fff" font-size="13" font-weight="900">{{ shortText(node.label, 12) }}</text>
          <text x="66" y="46" text-anchor="middle" fill="#dbeafe" font-size="10">{{ shortText(node.hint || node.type, 18) }}</text>
        </g>

        <g v-if="topology?.requirements?.length" transform="translate(48 458)">
          <rect x="0" y="0" width="864" height="42" rx="14" fill="#0f172a" stroke="#334155"/>
          <text x="20" y="26" fill="#93c5fd" font-size="12" font-weight="800">需求信号</text>
          <text x="96" y="26" fill="#cbd5e1" font-size="12">{{ topology.requirements.slice(0, 5).join(' / ') }}</text>
        </g>
      </svg>
      <svg v-else viewBox="0 0 960 540" class="h-auto w-full topology-svg" v-html="selectedSVG" />
    </div>
  </section>
</template>
