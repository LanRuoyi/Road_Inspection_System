<template>
  <div v-if="visible" class="floating-window" :style="windowStyle">
    <div class="window-header">
      <h4>病害详情</h4>
      <el-button size="small" text @click="close">
        <el-icon><Close /></el-icon>
      </el-button>
    </div>
    <div class="window-content">
      <!-- 病害信息区域 (固定比例40%) -->
      <div class="info-section">
        <div class="info-item">
          <span class="label">病害类型：</span>
          <span class="value">{{ safeType }}</span>
        </div>
        <div class="info-item">
          <span class="label">类别集合：</span>
          <span class="value">{{ safeTypesText }}</span>
        </div>
        <div class="info-item">
          <span class="label">目标数量：</span>
          <span class="value">{{ safeTargetCount }}</span>
        </div>
        <div class="info-item">
          <span class="label">位置：</span>
          <span class="value">{{ safeLatLon }}</span>
        </div>
        <div class="info-item">
          <span class="label">ID：</span>
          <span class="value">{{ safeId }}</span>
        </div>
      </div>
      
      <!-- 图片显示区域 (固定比例60%) -->
      <div class="image-section">
        <img :src="imageUrl" alt="病害图片" class="preview-image" />
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, computed } from 'vue'
import { Close } from '@element-plus/icons-vue'
import { apiClient } from '../api'
import { UNKNOWN_TYPE_SET } from '../utils/constants'

const props = defineProps({
  data: {
    type: Object,
    default: () => ({})
  },
  visible: {
    type: Boolean,
    default: false
  },
  sidebarWidth: {
    type: Number,
    default: 0
  }
})

const emit = defineEmits(['close'])

const normalizeType = (raw) => {
  if (typeof raw !== 'string') {
    return ''
  }
  const cleaned = raw.trim()
  if (!cleaned) {
    return ''
  }
  if (UNKNOWN_TYPE_SET.has(cleaned.toLowerCase())) {
    return ''
  }
  return cleaned
}

const safeType = computed(() => {
  return normalizeType(props.data?.type)
})

const safeId = computed(() => {
  const v = props.data?.id
  return v == null ? '-' : String(v)
})

const safeTypesText = computed(() => {
  const typeList = Array.isArray(props.data?.types)
    ? props.data.types.map(normalizeType).filter(Boolean)
    : []
  if (typeList.length > 0) {
    return typeList.join(' / ')
  }
  return safeType.value
})

const safeTargetCount = computed(() => {
  const n = Number(props.data?.target_count)
  if (Number.isFinite(n) && n >= 0) {
    return String(Math.floor(n))
  }
  return '0'
})

const safeLatLon = computed(() => {
  const lat = Number(props.data?.lat)
  const lon = Number(props.data?.lon)
  if (Number.isFinite(lat) && Number.isFinite(lon)) {
    return `${lat.toFixed(6)}, ${lon.toFixed(6)}`
  }
  return '-'
})

// 图片URL
const imageUrl = computed(() => {
  if (props.data?.id == null) {
    return ''
  }
  return `${apiClient.defaults.baseURL}/image/${props.data.id}`
})

// 悬浮窗位置和大小计算（基于可用空间比例）
const windowStyle = computed(() => {
  // 计算可用空间
  const availableSpaceWidth = `calc(100% - ${props.sidebarWidth}px)`

  // 悬浮窗大小基于可用空间的比例（确保小于可用空间）
  const windowWidth = `calc(${availableSpaceWidth} * 0.9)`  // 可用空间的80%
  const windowHeight = `calc(90%)` // 可用空间的90%
  
  // 计算水平居中位置：left = (可用空间宽度 - 窗口宽度) / 2
  const left = `calc(${props.sidebarWidth}px + ((${availableSpaceWidth} - ${windowWidth}) / 2))`
  
  return {
    left: left,
    top: '50%',
    transform: 'translateY(-50%)',
    width: windowWidth,
    height: windowHeight
  }
})

const close = () => {
  emit('close')
}
</script>

<style scoped>
.floating-window {
  position: fixed;
  z-index: 2000;
  background: white;
  min-width: 320px; /* 最小宽度 */
  max-width: 1920px; /* 最大宽度 */
  min-height: 300px; /* 最小高度 */
  max-height: 1080px; /* 最大高度 */
  border-radius: 8px;
  box-shadow: 0 4px 16px rgba(0, 0, 0, 0.3);
  border: 1px solid #e6e6e6;
  display: flex;
  flex-direction: column; /* 垂直布局 */
  transition: all 0.3s ease-in-out; /* 添加过渡动画 */
}

.window-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 16px;
  border-bottom: 1px solid #e6e6e6;
  background: #f5f7fa;
  border-radius: 8px 8px 0 0;
}

.window-header h4 {
  margin: 0;
  font-size: 16px;
  color: #333;
  font-weight: 600;
}

.window-content {
  padding: 16px;
  flex: 1; /* 占据剩余空间 */
  display: flex;
  flex-direction: column;
  height: 100%;
}

/* 病害信息区域 (固定比例40%) */
.info-section {
  flex: 0 0 auto;
  display: flex;
  flex-direction: column;
  justify-content: center;
  /* padding-bottom: 16px; */
}

.info-item {
  display: flex;
  align-items: center;
  margin-bottom: 12px;
}

.info-item .label {
  min-width: 80px;
  font-size: 14px;
  color: #666;
  font-weight: 500;
}

.info-item .value {
  font-size: 14px;
  color: #333;
}

/* 图片预览区域 (固定比例60%) */
.image-section {
  flex: 1 0 0; /* 固定60%高度 */
  display: flex;
  /* align-items: center; */
  justify-content: center;
  /* border-top: 1px solid #dfdcdc; */
  /* border-bottom: 1px solid #dfdcdc; */
  /* padding-top: 16px; */
  /* padding-bottom: 16px; */
  overflow: hidden; /* 防止图片溢出 */
}

.preview-image {
  max-width: 100%;
  max-height: 100%; /* 限制在容器高度内 */
  width: auto;
  height: auto;
  object-fit: contain; /* 保持宽高比，完整显示图片 */
  padding: 8px;
  /* border-radius: 4px; */
  /* border: 1px solid #e6e6e6; */
}
</style>