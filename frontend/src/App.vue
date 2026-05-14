<template>
  <div id="app">
    <el-container class="app-container">
      <!-- 左侧侧边栏 -->
      <el-aside 
          :width="sidebarWidth + 'px'" 
          class="sidebar-container"
          :class="{ 'collapsed': isCollapsed }"
        >
        <!-- 折叠按钮 -->
        <div 
          class="collapse-btn" 
          @click="toggleSidebar"
        >
          <span class="collapse-icon">{{ isCollapsed ? '>' : '<' }}</span>
        </div>
        
        <!-- 宽度调整手柄 -->
        <div 
          class="resize-handle" 
          @mousedown="startResize"
          v-if="!isCollapsed"
        ></div>
        
        <Sidebar 
          :active-tab="activeTab" 
          :analysis-config="analysisConfig"
          :analysis-selection="analysisSelection"
          :settings-version="settingsVersion"
          @tab-change="handleTabChange"
          @map-type-change="handleMapTypeChange"
          @disease-type-change="handleDiseaseTypeChange"
          @time-range-change="handleTimeRangeChange"
          @heatmap-change="handleHeatmapChange"
          @analysis-param-update="handleAnalysisParamUpdate"
          @analysis-delete-selected="handleAnalysisDeleteSelected"
          @analysis-delete-instances="handleAnalysisDeleteInstances"
          @analysis-preview-instance="handleAnalysisPreviewInstance"
          @ros-connection-change="handleROSConnectionChange"
          @ros-subscriptions-change="handleROSSubscriptionsChange"
          :collapsed="isCollapsed"
        />
      </el-aside>
      
      <!-- 右侧主内容区域 -->
      <el-main class="main-container">
        <!-- 病害分布功能 -->
        <div v-if="activeTab === 'disease-distribution'" class="content-area">
          <MapContainer 
          :sidebar-collapsed="isCollapsed" 
          :map-type="currentMapType" 
          :disease-type="currentDiseaseType"
          :start-date="currentStartDate"
          :end-date="currentEndDate"
          :show-heatmap="showHeatmap"
          :sidebar-width="isCollapsed ? getCollapsedWidth() : sidebarWidth"
          :initial-view="distributionViewState"
          :settings-version="settingsVersion"
          @view-state-change="handleDistributionViewStateChange"
        />
        </div>

        <!-- 病害分析功能 -->
        <div v-else-if="activeTab === 'disease-analysis'" class="content-area">
          <RoadAnalysisContainer
            :sidebar-collapsed="isCollapsed"
            :map-type="currentMapType"
            :disease-type="currentDiseaseType"
            :start-date="currentStartDate"
            :end-date="currentEndDate"
            :show-heatmap="showHeatmap"
            :sidebar-width="isCollapsed ? getCollapsedWidth() : sidebarWidth"
            :analysis-config="analysisConfig"
            :analysis-command="analysisCommand"
            @analysis-selection-change="handleAnalysisSelectionChange"
            :initial-view="analysisViewState"
            :settings-version="settingsVersion"
            @view-state-change="handleAnalysisViewStateChange"
          />
        </div>
        
        <!-- 实时监看功能 -->
        <div v-else-if="activeTab === 'real-time-monitor'" class="content-area">
          <ROSRealtimeViewer
            :ros-connected="rosConnected"
            :selected-topics="selectedROSTopics"
          />
        </div>
        
        <!-- 参数配置功能 -->
        <div v-else-if="activeTab === 'parameter-config'" class="content-area">
          <SettingsConfigPanel @settings-saved="handleSettingsSaved" />
        </div>

        <div v-else-if="activeTab === 'data-transfer'" class="content-area">
          <DataTransferManager />
        </div>
      </el-main>
    </el-container>
  </div>
</template>

<script setup>
import { ref, onMounted, onUnmounted } from 'vue'
import Sidebar from './components/Sidebar.vue'
import MapContainer from './components/MapContainer.vue'
import RoadAnalysisContainer from './components/RoadAnalysisContainer.vue'
import ROSRealtimeViewer from './components/ROSRealtimeViewer.vue'
import DataTransferManager from './components/DataTransferManager.vue'
import SettingsConfigPanel from './components/SettingsConfigPanel.vue'
import { fetchAnalysisConfig } from './api'
import { ANALYSIS_INSTANCE_DEFAULTS } from './utils/constants'
import { parseDayStartMs, normalizeDayText } from './utils/helpers'

// 当前激活的功能标签
const activeTab = ref('disease-distribution')

// 侧边栏状态
const isCollapsed = ref(false)
const sidebarWidth = ref(0) // 初始为0，将在mounted中计算
const minWidth = 200
const maxWidth = 400

// 计算侧边栏宽度（基于视口宽度的相对大小）
const calculateSidebarWidth = () => {
  // 使用视口宽度的20%作为基础，限制在minWidth和maxWidth之间
  const baseWidth = window.innerWidth * 0.15
  const calculatedWidth = Math.max(minWidth, Math.min(maxWidth, baseWidth))
  sidebarWidth.value = calculatedWidth
  // console.log('侧边栏宽度计算:', {
  //   windowWidth: window.innerWidth,
  //   baseWidth: baseWidth,
  //   calculatedWidth: calculatedWidth,
  //   isCollapsed: isCollapsed.value
  // })
}

// 地图类型
const currentMapType = ref('normal')

// 当前病害类型
const currentDiseaseType = ref('all')

// 时间范围（YYYY-MM-DD），空字符串表示不限制
const currentStartDate = ref('')
const currentEndDate = ref('')

// 热力图开关
const showHeatmap = ref(false)

// ROS 连接状态
const rosConnected = ref(false)
const selectedROSTopics = ref([])

// 病害分析配置与交互状态
const analysisConfig = ref({
  instance_defaults: { ...ANALYSIS_INSTANCE_DEFAULTS },
  param_schema: [],
  result_schema: [],
  thresholds: {},
  status_colors: {}
})

const analysisSelection = ref({
  selectedCount: 0,
  selectedIds: [],
  instanceList: [],
  values: {},
  resultValues: {}
})

const analysisCommand = ref({
  seq: 0,
  type: 'noop'
})

const settingsVersion = ref(0)

const distributionViewState = ref({
  lat: null,
  lon: null,
  zoom: null,
})

const analysisViewState = ref({
  lat: null,
  lon: null,
  zoom: null,
})

// 计算折叠后的侧边栏宽度（基于视口宽度）
const getCollapsedWidth = () => {
  return Math.max(64, window.innerWidth * 0.04) // 4vw，最小64px
}

// 处理标签切换
const handleTabChange = (tabName) => {
  activeTab.value = tabName
}

const pushAnalysisCommand = (payload) => {
  const nextSeq = Number(analysisCommand.value?.seq || 0) + 1
  analysisCommand.value = {
    seq: nextSeq,
    ...payload
  }
}

const handleAnalysisSelectionChange = (payload) => {
  analysisSelection.value = {
    selectedCount: Number(payload?.selectedCount || 0),
    selectedIds: Array.isArray(payload?.selectedIds) ? payload.selectedIds : [],
    instanceList: Array.isArray(payload?.instanceList) ? payload.instanceList : [],
    values: payload?.values && typeof payload.values === 'object' ? payload.values : {},
    resultValues: payload?.resultValues && typeof payload.resultValues === 'object' ? payload.resultValues : {}
  }
}

const handleAnalysisParamUpdate = ({ key, value }) => {
  if (!key) return
  pushAnalysisCommand({
    type: 'apply-params',
    params: {
      [key]: value
    }
  })
}

const handleAnalysisDeleteSelected = () => {
  pushAnalysisCommand({ type: 'delete-selected' })
}

const handleAnalysisDeleteInstances = (instanceIds) => {
  pushAnalysisCommand({
    type: 'delete-instance-ids',
    instanceIds: Array.isArray(instanceIds) ? instanceIds : []
  })
}

const handleAnalysisPreviewInstance = (payload) => {
  const active = Boolean(payload?.active)
  const instanceId = String(payload?.instanceId || '')
  if (!active || !instanceId) {
    pushAnalysisCommand({ type: 'clear-preview' })
    return
  }
  pushAnalysisCommand({
    type: 'preview-instance',
    instanceId
  })
}

const handleSettingsSaved = (settings) => {
  const source = settings && typeof settings === 'object' ? settings : {}
  settingsVersion.value += 1
  // instance_defaults/thresholds/status_colors 全部替换（不用 spread-merge），
  // 避免旧 key 在 settings.py 更新后仍然残留。
  analysisConfig.value = {
    ...analysisConfig.value,
    instance_defaults: source.analysis_instance_defaults && typeof source.analysis_instance_defaults === 'object'
      ? { ...source.analysis_instance_defaults }
      : analysisConfig.value.instance_defaults,
    param_schema: Array.isArray(source.analysis_param_schema)
      ? source.analysis_param_schema
      : analysisConfig.value.param_schema,
    result_schema: Array.isArray(source.analysis_result_schema)
      ? source.analysis_result_schema
      : analysisConfig.value.result_schema,
    thresholds: source.analysis_thresholds && typeof source.analysis_thresholds === 'object'
      ? { ...source.analysis_thresholds }
      : analysisConfig.value.thresholds,
    status_colors: source.analysis_status_colors && typeof source.analysis_status_colors === 'object'
      ? { ...source.analysis_status_colors }
      : analysisConfig.value.status_colors,
  }
}

const normalizeViewStatePayload = (payload) => {
  const lat = Number(payload?.lat)
  const lon = Number(payload?.lon)
  const zoom = Number(payload?.zoom)
  if (!Number.isFinite(lat) || !Number.isFinite(lon) || !Number.isFinite(zoom)) {
    return null
  }
  if (Math.abs(lat) > 90 || Math.abs(lon) > 180) {
    return null
  }
  if (zoom < 1 || zoom > 22) {
    return null
  }
  if (Math.abs(lat) < 1e-6 && Math.abs(lon) < 1e-6) {
    return null
  }
  return {
    lat,
    lon,
    zoom,
  }
}

const handleDistributionViewStateChange = (payload) => {
  const normalized = normalizeViewStatePayload(payload)
  if (!normalized) return
  distributionViewState.value = normalized
}

const handleAnalysisViewStateChange = (payload) => {
  const normalized = normalizeViewStatePayload(payload)
  if (!normalized) return
  analysisViewState.value = normalized
}

// 处理地图类型变化
const handleMapTypeChange = (type) => {
  currentMapType.value = type
}

// 处理病害类型变化
const handleDiseaseTypeChange = (type) => {
  currentDiseaseType.value = type
}

const handleTimeRangeChange = (payload) => {
  let startDate = normalizeDayText(payload?.startDate || '')
  let endDate = normalizeDayText(payload?.endDate || '')

  const startMs = parseDayStartMs(startDate)
  const endMs = parseDayStartMs(endDate)
  if (startMs != null && endMs != null && startMs > endMs) {
    const tmp = startDate
    startDate = endDate
    endDate = tmp
  }

  currentStartDate.value = startDate
  currentEndDate.value = endDate
}

// 处理热力图开关变化
const handleHeatmapChange = (val) => {
  showHeatmap.value = val
}

const handleROSConnectionChange = (payload) => {
  rosConnected.value = Boolean(payload?.connected)
  if (!rosConnected.value) {
    selectedROSTopics.value = []
  }
}

const handleROSSubscriptionsChange = (topics) => {
  selectedROSTopics.value = Array.isArray(topics) ? topics : []
}

// 切换侧边栏折叠状态
const toggleSidebar = () => {
  isCollapsed.value = !isCollapsed.value
}

// 监听窗口大小变化
const handleWindowResize = () => {
  if (!isCollapsed.value) {
    calculateSidebarWidth()
  }
}

// 组件挂载时计算初始宽度
onMounted(() => {
  calculateSidebarWidth()
  window.addEventListener('resize', handleWindowResize)

  fetchAnalysisConfig()
    .then((resp) => {
      if (resp?.data && typeof resp.data === 'object') {
        // 直接替换整个 analysisConfig，不用 spread-merge instance_defaults，
        // 避免旧的 observed_pci_drop / observed_years 等字段永久残留。
        const data = resp.data
        analysisConfig.value = {
          instance_defaults: data.instance_defaults && typeof data.instance_defaults === 'object'
            ? { ...data.instance_defaults }
            : analysisConfig.value.instance_defaults,
          param_schema: Array.isArray(data.param_schema)
            ? data.param_schema
            : analysisConfig.value.param_schema,
          result_schema: Array.isArray(data.result_schema)
            ? data.result_schema
            : analysisConfig.value.result_schema,
          thresholds: data.thresholds && typeof data.thresholds === 'object'
            ? { ...data.thresholds }
            : analysisConfig.value.thresholds,
          status_colors: data.status_colors && typeof data.status_colors === 'object'
            ? { ...data.status_colors }
            : analysisConfig.value.status_colors,
        }
      }
    })
    .catch((error) => {
      console.error('获取病害分析配置失败，使用前端默认值:', error)
    })
})

// 组件卸载时移除监听器
onUnmounted(() => {
  window.removeEventListener('resize', handleWindowResize)
})

// 宽度调整相关变量
let isResizing = false
let startX = 0
let startWidth = 0

// 开始调整宽度
const startResize = (e) => {
  isResizing = true
  startX = e.clientX
  startWidth = sidebarWidth.value
  
  // 添加resizing类禁用动画
  const sidebarEl = document.querySelector('.sidebar-container')
  if (sidebarEl) {
    sidebarEl.classList.add('resizing')
  }
  
  document.addEventListener('mousemove', handleResize)
  document.addEventListener('mouseup', stopResize)
  
  // 防止文本选中
  e.preventDefault()
}

// 处理宽度调整
const handleResize = (e) => {
  if (!isResizing) return
  
  const deltaX = e.clientX - startX
  let newWidth = startWidth + deltaX
  
  // 限制宽度范围
  if (newWidth < minWidth) newWidth = minWidth
  if (newWidth > maxWidth) newWidth = maxWidth
  
  sidebarWidth.value = newWidth
}

// 停止调整宽度
const stopResize = () => {
  isResizing = false
  
  // 移除resizing类恢复动画
  const sidebarEl = document.querySelector('.sidebar-container')
  if (sidebarEl) {
    sidebarEl.classList.remove('resizing')
  }
  
  document.removeEventListener('mousemove', handleResize)
  document.removeEventListener('mouseup', stopResize)
}

// 组件卸载时清理事件监听器
onUnmounted(() => {
  document.removeEventListener('mousemove', handleResize)
  document.removeEventListener('mouseup', stopResize)
})
</script>

<style scoped>
.app-container {
  height: 100%;
  width: 100%;
  background-color: #f5f5f5;
  position: relative;
  overflow: hidden;
}

.sidebar-container {
  background-color: #fff;
  box-shadow: 2px 0 6px rgba(0, 0, 0, 0.1);
  z-index: 1000;
  position: relative;
  overflow: hidden;
  transition: width 0.3s ease-in-out;
}

.sidebar-container.resizing {
  transition: none !important;
}

.sidebar-container.resizing + .main-container {
  transition: none !important;
}

.sidebar-container.collapsed {
  width: 4vw !important;
  min-width: 64px;
}

.collapse-btn {
  position: absolute;
  top: 50%;
  right: -12px; /* 固定偏移，基于按钮宽度的一半 */
  width: 24px;
  height: 24px;
  min-width: 24px;
  min-height: 24px;
  display: flex;
  align-items: center;
  justify-content: center;
  background-color: #fff;
  border: 1px solid #e6e6e6;
  border-radius: 50%;
  cursor: pointer;
  z-index: 1001;
  transition: all 0.3s ease;
  transform: translateY(-50%);
  box-shadow: 0 1px 3px rgba(0, 0, 0, 0.1);
  opacity: 0;
  user-select: none;
  -webkit-user-select: none;
  -moz-user-select: none;
  -ms-user-select: none;
  outline: none;
}

.collapse-btn:focus {
  outline: none;
  border-color: #409eff;
}

.sidebar-container:hover .collapse-btn {
  opacity: 1;
}

.collapse-btn.hover-visible {
  opacity: 1;
}

.collapse-btn:hover {
  background-color: #f5f5f5;
  border-color: #409eff;
}

.collapse-icon {
  font-size: 10px;
  font-weight: bold;
  color: #666;
  line-height: 1;
  display: flex;
  align-items: center;
  justify-content: center;
  width: 100%;
  height: 100%;
  transform: translateX(-20%);
  transition: transform 0.3s ease;
}

.sidebar-container.collapsed .collapse-icon {
  transform: translateX(-20%);
}

.resize-handle {
  position: absolute;
  top: 0;
  right: 0;
  width: 0.25vw;
  min-width: 4px;
  height: 100%;
  cursor: col-resize;
  background-color: transparent;
  z-index: 1002;
}

.resize-handle:hover {
  background-color: #409eff;
}

.resize-handle:active {
  background-color: #337ecc;
}

.main-container {
  padding: 0;
  background-color: #f0f2f5;
  transition: all 0.3s ease-in-out;
  position: relative;
  flex: 1;
  min-width: 0;
  height: 100%;
  margin: 0 !important;
  overflow: hidden;
}

.content-area {
  height: 100%;
  width: 100%;
  overflow: hidden;
}

.placeholder-content {
  display: flex;
  justify-content: center;
  align-items: center;
  height: 100%;
  background-color: #fff;
}
</style>