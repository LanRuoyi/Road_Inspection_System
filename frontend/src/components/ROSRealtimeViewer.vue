<template>
  <div class="ros-viewer">
    <div class="viewer-header">
      <div class="status-group">
        <el-tag :type="rosConnected ? 'success' : 'warning'" size="small">
          ROS {{ rosConnected ? '已连接' : '未连接' }}
        </el-tag>
        <el-tag :type="wsConnected ? 'success' : 'info'" size="small">
          WS {{ wsConnected ? '已连接' : '未连接' }}
        </el-tag>
      </div>
      <el-button size="small" @click="requestCatalog">刷新话题目录</el-button>
    </div>

    <div v-if="!selectedTopics.length" class="empty-wrap">
      <el-empty description="请在侧边栏选择并应用话题订阅" />
    </div>

    <div v-else ref="viewerCanvasRef" class="topic-canvas">
      <div
        v-for="topic in layeredTopics"
        :key="topic.name"
        class="topic-window"
        :style="getWindowStyle(topic.name)"
        @mousedown="bringToFront(topic.name)"
      >
        <div class="card-header" @mousedown="startMove(topic.name, $event)">
          <span class="topic-name">{{ topic.name }}</span>
          <el-tag size="small">{{ topic.type }}</el-tag>
        </div>

        <div class="card-body">
          <img
            v-if="topicImages[topic.name]"
            :src="topicImages[topic.name]"
            :alt="`topic-${topic.name}`"
            class="topic-image"
          />

          <div v-else class="json-fallback">
            <div class="json-title">最新消息（非图像）</div>
            <pre>{{ formatMessage(topicMessages[topic.name]) }}</pre>
          </div>
        </div>

        <div class="card-footer">
          <span class="timestamp">{{ formatTime(topicTimestamps[topic.name]) }}</span>
        </div>

        <div class="resize-handle right" @mousedown="startResize(topic.name, 'right', $event)"></div>
        <div class="resize-handle bottom" @mousedown="startResize(topic.name, 'bottom', $event)"></div>
        <div class="resize-handle corner" @mousedown="startResize(topic.name, 'corner', $event)"></div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { computed, onMounted, onUnmounted, ref, watch } from 'vue'
import { ElMessage } from 'element-plus'
import { buildROSWebSocketUrl, subscribeROSTopics, fetchROSMessages } from '../api'

const props = defineProps({
  selectedTopics: {
    type: Array,
    default: () => []
  },
  rosConnected: {
    type: Boolean,
    default: false
  }
})

const wsConnected = ref(false)
const topicMessages = ref({})
const topicImages = ref({})
const topicTimestamps = ref({})
const viewerCanvasRef = ref(null)
const windowStates = ref({})

let ws = null
let reconnectTimer = null
let pollingTimer = null
let reconnectDelay = 1000
let wsFailureCount = 0
let zSeed = 10
const objectUrlMap = new Map()
const usingPolling = ref(false)
const wsHintShown = ref(false)
let interactionState = null

const MIN_WINDOW_WIDTH = 280
const MIN_WINDOW_HEIGHT = 220

const layeredTopics = computed(() => {
  return [...props.selectedTopics].sort((a, b) => {
    const za = windowStates.value[a.name]?.z || 0
    const zb = windowStates.value[b.name]?.z || 0
    return za - zb
  })
})

const clamp = (value, min, max) => Math.max(min, Math.min(max, value))

const getCanvasSize = () => {
  const el = viewerCanvasRef.value
  if (!el) {
    return { width: 1280, height: 720 }
  }
  return {
    width: el.clientWidth || 1280,
    height: el.clientHeight || 720
  }
}

const ensureWindowState = (topicName, index = 0) => {
  if (windowStates.value[topicName]) return
  zSeed += 1
  windowStates.value[topicName] = {
    x: 20 + (index % 6) * 26,
    y: 20 + Math.floor(index / 6) * 26,
    width: 360,
    height: 300,
    z: zSeed
  }
}

const normalizeWindowBounds = () => {
  const { width: canvasWidth, height: canvasHeight } = getCanvasSize()

  Object.keys(windowStates.value).forEach((topicName) => {
    const state = windowStates.value[topicName]
    if (!state) return

    const maxWidth = Math.max(MIN_WINDOW_WIDTH, canvasWidth)
    const maxHeight = Math.max(MIN_WINDOW_HEIGHT, canvasHeight)

    state.width = clamp(state.width, MIN_WINDOW_WIDTH, maxWidth)
    state.height = clamp(state.height, MIN_WINDOW_HEIGHT, maxHeight)

    const maxX = Math.max(0, canvasWidth - state.width)
    const maxY = Math.max(0, canvasHeight - state.height)

    state.x = clamp(state.x, 0, maxX)
    state.y = clamp(state.y, 0, maxY)
  })
}

const syncWindowStates = (topics) => {
  const nextNames = new Set((topics || []).map(item => item.name))

  Object.keys(windowStates.value).forEach((topicName) => {
    if (!nextNames.has(topicName)) {
      delete windowStates.value[topicName]
    }
  })

  ;(topics || []).forEach((item, index) => {
    ensureWindowState(item.name, index)
  })

  normalizeWindowBounds()
}

const bringToFront = (topicName) => {
  const state = windowStates.value[topicName]
  if (!state) return
  zSeed += 1
  state.z = zSeed
}

const getWindowStyle = (topicName) => {
  const state = windowStates.value[topicName]
  if (!state) {
    return {
      left: '20px',
      top: '20px',
      width: '360px',
      height: '300px',
      zIndex: 1
    }
  }

  return {
    left: `${state.x}px`,
    top: `${state.y}px`,
    width: `${state.width}px`,
    height: `${state.height}px`,
    zIndex: state.z
  }
}

const bindPointerListeners = () => {
  document.addEventListener('mousemove', handlePointerMove)
  document.addEventListener('mouseup', stopInteraction)
}

const unbindPointerListeners = () => {
  document.removeEventListener('mousemove', handlePointerMove)
  document.removeEventListener('mouseup', stopInteraction)
}

const startMove = (topicName, event) => {
  const state = windowStates.value[topicName]
  if (!state) return

  bringToFront(topicName)
  interactionState = {
    type: 'move',
    topicName,
    startX: event.clientX,
    startY: event.clientY,
    originX: state.x,
    originY: state.y,
    originWidth: state.width,
    originHeight: state.height
  }

  bindPointerListeners()
  event.preventDefault()
  event.stopPropagation()
}

const startResize = (topicName, direction, event) => {
  const state = windowStates.value[topicName]
  if (!state) return

  bringToFront(topicName)
  interactionState = {
    type: `resize-${direction}`,
    topicName,
    startX: event.clientX,
    startY: event.clientY,
    originX: state.x,
    originY: state.y,
    originWidth: state.width,
    originHeight: state.height
  }

  bindPointerListeners()
  event.preventDefault()
  event.stopPropagation()
}

const handlePointerMove = (event) => {
  if (!interactionState) return

  const state = windowStates.value[interactionState.topicName]
  if (!state) return

  const dx = event.clientX - interactionState.startX
  const dy = event.clientY - interactionState.startY
  const { width: canvasWidth, height: canvasHeight } = getCanvasSize()

  if (interactionState.type === 'move') {
    const maxX = Math.max(0, canvasWidth - state.width)
    const maxY = Math.max(0, canvasHeight - state.height)
    state.x = clamp(interactionState.originX + dx, 0, maxX)
    state.y = clamp(interactionState.originY + dy, 0, maxY)
    return
  }

  if (interactionState.type === 'resize-right' || interactionState.type === 'resize-corner') {
    const maxWidth = Math.max(MIN_WINDOW_WIDTH, canvasWidth - state.x)
    state.width = clamp(interactionState.originWidth + dx, MIN_WINDOW_WIDTH, maxWidth)
  }

  if (interactionState.type === 'resize-bottom' || interactionState.type === 'resize-corner') {
    const maxHeight = Math.max(MIN_WINDOW_HEIGHT, canvasHeight - state.y)
    state.height = clamp(interactionState.originHeight + dy, MIN_WINDOW_HEIGHT, maxHeight)
  }
}

const stopInteraction = () => {
  interactionState = null
  unbindPointerListeners()
}

const guessMimeType = (message) => {
  const format = (message?.format || '').toLowerCase()
  const encoding = (message?.encoding || '').toLowerCase()
  if (format.includes('png')) return 'image/png'
  if (format.includes('jpg') || format.includes('jpeg')) return 'image/jpeg'
  if (encoding.includes('png')) return 'image/png'
  if (encoding.includes('rgb') || encoding.includes('bgr')) return 'image/raw'
  return 'image/jpeg'
}

const replaceTopicImage = (topicName, nextUrl) => {
  const prevUrl = objectUrlMap.get(topicName)
  if (prevUrl && prevUrl.startsWith('blob:')) {
    URL.revokeObjectURL(prevUrl)
  }

  if (nextUrl) {
    objectUrlMap.set(topicName, nextUrl)
    topicImages.value[topicName] = nextUrl
  } else {
    objectUrlMap.delete(topicName)
    delete topicImages.value[topicName]
  }
}

const bytesToObjectUrl = (bytes, mimeType) => {
  if (!bytes?.length) return ''
  const blob = new Blob([bytes], { type: mimeType || 'image/jpeg' })
  return URL.createObjectURL(blob)
}

const rawImageToDataUrl = (item) => {
  const width = Number(item?.width || 0)
  const height = Number(item?.height || 0)
  const encoding = String(item?.encoding || '').toLowerCase()
  const data = item?.data

  if (!width || !height || !Array.isArray(data) || !encoding) {
    return ''
  }

  const canvas = document.createElement('canvas')
  canvas.width = width
  canvas.height = height
  const ctx = canvas.getContext('2d')
  if (!ctx) return ''

  const rgba = new Uint8ClampedArray(width * height * 4)

  if (encoding === 'rgb8' || encoding === 'bgr8') {
    const channels = 3
    if (data.length < width * height * channels) return ''
    for (let i = 0, p = 0; p < width * height; p++, i += channels) {
      const base = p * 4
      if (encoding === 'rgb8') {
        rgba[base] = data[i]
        rgba[base + 1] = data[i + 1]
        rgba[base + 2] = data[i + 2]
      } else {
        rgba[base] = data[i + 2]
        rgba[base + 1] = data[i + 1]
        rgba[base + 2] = data[i]
      }
      rgba[base + 3] = 255
    }
  } else if (encoding === 'rgba8' || encoding === 'bgra8') {
    const channels = 4
    if (data.length < width * height * channels) return ''
    for (let i = 0, p = 0; p < width * height; p++, i += channels) {
      const base = p * 4
      if (encoding === 'rgba8') {
        rgba[base] = data[i]
        rgba[base + 1] = data[i + 1]
        rgba[base + 2] = data[i + 2]
        rgba[base + 3] = data[i + 3]
      } else {
        rgba[base] = data[i + 2]
        rgba[base + 1] = data[i + 1]
        rgba[base + 2] = data[i]
        rgba[base + 3] = data[i + 3]
      }
    }
  } else {
    return ''
  }

  const imageData = new ImageData(rgba, width, height)
  ctx.putImageData(imageData, 0, 0)
  return canvas.toDataURL('image/jpeg', 0.9)
}

const extractImageDataUrl = (message) => {
  if (!message || typeof message !== 'object') return ''

  const candidates = [message, message.image, message.msg]
  for (const item of candidates) {
    if (!item || typeof item !== 'object') continue

    if (typeof item.url === 'string' && item.url.startsWith('data:image')) {
      return item.url
    }

    if (typeof item.data === 'string' && item.data.length > 100) {
      if (item.data.startsWith('data:image')) {
        return item.data
      }
      const mimeType = guessMimeType(item)
      if (!['image/jpeg', 'image/png'].includes(mimeType)) {
        continue
      }
      return `data:${mimeType};base64,${item.data}`
    }

    if (Array.isArray(item.data) && item.data.length > 100) {
      const mimeType = guessMimeType(item)
      if (!['image/jpeg', 'image/png'].includes(mimeType)) {
        continue
      }
      const typed = new Uint8Array(item.data)
      return bytesToObjectUrl(typed, mimeType)
    }

    const rawUrl = rawImageToDataUrl(item)
    if (rawUrl) {
      return rawUrl
    }
  }

  return ''
}

const formatMessage = (message) => {
  if (!message) return '暂无消息'
  try {
    return JSON.stringify(message, null, 2)
  } catch {
    return String(message)
  }
}

const formatTime = (timestamp) => {
  if (!timestamp) return '未收到消息'
  try {
    return new Date(timestamp).toLocaleTimeString()
  } catch {
    return '未收到消息'
  }
}

const sendSubscriptions = () => {
  if (!props.rosConnected) return
  if (usingPolling.value) return
  if (!ws || ws.readyState !== WebSocket.OPEN) return

  ws.send(JSON.stringify({
    action: 'set_subscriptions',
    topics: props.selectedTopics
  }))
}

const ensureRESTSubscriptions = async () => {
  if (!props.rosConnected || !props.selectedTopics.length) return
  try {
    await subscribeROSTopics(props.selectedTopics)
  } catch (error) {
    console.error('REST 订阅失败:', error)
  }
}

const handleIncomingTopicData = (data) => {
  Object.entries(data || {}).forEach(([topicName, message]) => {
    topicMessages.value[topicName] = message
    topicTimestamps.value[topicName] = Date.now()

    const dataUrl = extractImageDataUrl(message)
    if (dataUrl) {
      replaceTopicImage(topicName, dataUrl)
    }
  })
}

const startPolling = async () => {
  if (!props.rosConnected || !props.selectedTopics.length) return
  clearInterval(pollingTimer)

  await ensureRESTSubscriptions()

  pollingTimer = setInterval(async () => {
    try {
      const topicNames = props.selectedTopics.map(item => item.name)
      if (!topicNames.length) return
      const response = await fetchROSMessages(topicNames)
      handleIncomingTopicData(response?.data?.data || {})
    } catch (error) {
      console.error('轮询 ROS 消息失败:', error)
    }
  }, 500)
}

const stopPolling = () => {
  clearInterval(pollingTimer)
  pollingTimer = null
}

const requestCatalog = () => {
  if (!ws || ws.readyState !== WebSocket.OPEN) return
  ws.send(JSON.stringify({ action: 'catalog' }))
}

const closeWebSocket = () => {
  clearTimeout(reconnectTimer)
  reconnectTimer = null

  if (ws) {
    try {
      ws.close()
    } catch {
      // noop
    }
    ws = null
  }
  wsConnected.value = false
}

const scheduleReconnect = () => {
  if (!props.rosConnected) return
  clearTimeout(reconnectTimer)
  reconnectTimer = setTimeout(() => {
    connectWebSocket()
  }, reconnectDelay)
  reconnectDelay = Math.min(reconnectDelay * 2, 8000)
}

const connectWebSocket = () => {
  if (!props.rosConnected) return
  if (usingPolling.value) return

  if (ws && (ws.readyState === WebSocket.OPEN || ws.readyState === WebSocket.CONNECTING)) {
    return
  }

  ws = new WebSocket(buildROSWebSocketUrl())

  ws.onopen = () => {
    wsConnected.value = true
    wsFailureCount = 0
    reconnectDelay = 1000
    stopPolling()
    sendSubscriptions()
  }

  ws.onmessage = (event) => {
    try {
      const payload = JSON.parse(event.data)
      if (payload.event === 'message') {
        handleIncomingTopicData(payload.data || {})
      } else if (payload.event === 'error' && payload.message) {
        console.error('WS 返回错误:', payload.message)
      }
    } catch (error) {
      console.error('解析 WebSocket 消息失败:', error)
    }
  }

  ws.onclose = () => {
    wsConnected.value = false
    wsFailureCount += 1

    if (wsFailureCount >= 2) {
      usingPolling.value = true
      if (!wsHintShown.value) {
        wsHintShown.value = true
        ElMessage.warning('WebSocket 不可用，已自动切换到 HTTP 轮询模式')
      }
      startPolling()
      return
    }

    scheduleReconnect()
  }

  ws.onerror = () => {
    wsConnected.value = false
  }
}

watch(
  () => props.selectedTopics,
  async (topics) => {
    syncWindowStates(topics)

    const selected = new Set((topics || []).map(item => item.name))
    Object.keys(topicImages.value).forEach((topicName) => {
      if (!selected.has(topicName)) {
        replaceTopicImage(topicName, '')
        delete topicMessages.value[topicName]
        delete topicTimestamps.value[topicName]
      }
    })

    await ensureRESTSubscriptions()

    if (usingPolling.value) {
      if (topics?.length) {
        await startPolling()
      } else {
        stopPolling()
      }
    }

    sendSubscriptions()
  },
  { deep: true }
)

watch(
  () => props.rosConnected,
  (connected) => {
    if (connected) {
      if (usingPolling.value) {
        startPolling()
      } else {
        connectWebSocket()
      }
      ensureRESTSubscriptions()
    } else {
      stopPolling()
      usingPolling.value = false
      wsFailureCount = 0
      closeWebSocket()
      ElMessage.warning('ROS 未连接，暂时无法收到实时话题消息')
    }
  },
  { immediate: true }
)

watch(
  () => props.selectedTopics.length,
  (count) => {
    if (count > 0 && props.rosConnected) {
      if (usingPolling.value) {
        startPolling()
      } else {
        connectWebSocket()
      }
    }
  }
)

onMounted(() => {
  syncWindowStates(props.selectedTopics)
  window.addEventListener('resize', normalizeWindowBounds)

  if (props.rosConnected) {
    ensureRESTSubscriptions()
    if (usingPolling.value) {
      startPolling()
    } else {
      connectWebSocket()
    }
  }
})

onUnmounted(() => {
  window.removeEventListener('resize', normalizeWindowBounds)
  stopInteraction()
  closeWebSocket()
  stopPolling()
  objectUrlMap.forEach((url) => {
    if (url.startsWith('blob:')) {
      URL.revokeObjectURL(url)
    }
  })
  objectUrlMap.clear()
})
</script>

<style scoped>
.ros-viewer {
  height: 100%;
  background: #fff;
  padding: 16px;
  box-sizing: border-box;
  overflow: auto;
}

.viewer-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 16px;
}

.status-group {
  display: flex;
  align-items: center;
  gap: 8px;
}

.empty-wrap {
  height: calc(100% - 60px);
  display: flex;
  align-items: center;
  justify-content: center;
}

.topic-canvas {
  position: relative;
  height: calc(100% - 60px);
  min-height: 360px;
  overflow: hidden;
  border: 1px solid #ebeef5;
  border-radius: 8px;
  background: #fafafa;
}

.topic-window {
  position: absolute;
  background: #fff;
  border: 1px solid #e4e7ed;
  border-radius: 8px;
  box-shadow: 0 2px 8px rgba(0, 0, 0, 0.12);
  display: flex;
  flex-direction: column;
  overflow: hidden;
}

.card-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  padding: 10px 12px;
  border-bottom: 1px solid #f0f0f0;
  background: #f7f9fc;
  cursor: move;
  user-select: none;
}

.topic-name {
  font-size: 13px;
  color: #333;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  max-width: 220px;
}

.card-body {
  flex: 1;
  min-height: 120px;
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 10px;
  overflow: hidden;
}

.topic-image {
  width: 100%;
  height: 100%;
  max-height: none;
  object-fit: contain;
  border-radius: 4px;
  border: 1px solid #e6e6e6;
}

.json-fallback {
  width: 100%;
  height: 100%;
  display: flex;
  flex-direction: column;
}

.json-title {
  font-size: 12px;
  color: #666;
  margin-bottom: 8px;
}

.json-fallback pre {
  margin: 0;
  flex: 1;
  height: 100%;
  overflow: auto;
  background: #f5f7fa;
  padding: 8px;
  border-radius: 4px;
  font-size: 12px;
}

.card-footer {
  border-top: 1px solid #f0f0f0;
  padding: 8px 12px;
  font-size: 12px;
  color: #999;
  text-align: right;
}

.resize-handle {
  position: absolute;
  background: transparent;
}

.resize-handle.right {
  top: 10px;
  right: 0;
  width: 8px;
  height: calc(100% - 20px);
  cursor: ew-resize;
}

.resize-handle.bottom {
  left: 10px;
  bottom: 0;
  width: calc(100% - 20px);
  height: 8px;
  cursor: ns-resize;
}

.resize-handle.corner {
  width: 14px;
  height: 14px;
  right: 0;
  bottom: 0;
  cursor: nwse-resize;
}
</style>
