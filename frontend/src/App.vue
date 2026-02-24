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
          @tab-change="handleTabChange"
          @map-type-change="handleMapTypeChange"
          @disease-type-change="handleDiseaseTypeChange"
          :collapsed="isCollapsed"
        />
      </el-aside>
      
      <!-- 右侧主内容区域 -->
      <el-main 
        class="main-container" 
        :style="{ 
          transform: isCollapsed ? 'translateX(' + getCollapsedWidth() + 'px)' : 'translateX(' + sidebarWidth + 'px)' 
        }"
      >
        <!-- 病害分布功能 -->
        <div v-if="activeTab === 'disease-distribution'" class="content-area">
          <MapContainer 
          :sidebar-collapsed="isCollapsed" 
          :map-type="currentMapType" 
          :disease-type="currentDiseaseType"
          :sidebar-width="isCollapsed ? getCollapsedWidth() : sidebarWidth"
        />
        </div>
        
        <!-- 实时监看功能 -->
        <div v-else-if="activeTab === 'real-time-monitor'" class="content-area">
          <div class="placeholder-content">
            <el-empty description="实时监看功能开发中" />
          </div>
        </div>
        
        <!-- 参数配置功能 -->
        <div v-else-if="activeTab === 'parameter-config'" class="content-area">
          <div class="placeholder-content">
            <el-empty description="参数配置功能开发中" />
          </div>
        </div>
      </el-main>
    </el-container>
  </div>
</template>

<script setup>
import { ref, onMounted, onUnmounted } from 'vue'
import Sidebar from './components/Sidebar.vue'
import MapContainer from './components/MapContainer.vue'
import { Expand, Fold } from '@element-plus/icons-vue'

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
  const baseWidth = window.innerWidth * 0.2
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

// 计算折叠后的侧边栏宽度（基于视口宽度）
const getCollapsedWidth = () => {
  return Math.max(64, window.innerWidth * 0.04) // 4vw，最小64px
}

// 处理标签切换
const handleTabChange = (tabName) => {
  activeTab.value = tabName
}

// 处理地图类型变化
const handleMapTypeChange = (type) => {
  currentMapType.value = type
}

// 处理病害类型变化
const handleDiseaseTypeChange = (type) => {
  currentDiseaseType.value = type
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
  height: 100vh;
  background-color: #f5f5f5;
  position: relative;
  overflow: hidden;
}

.sidebar-container {
  background-color: #fff;
  box-shadow: 2px 0 6px rgba(0, 0, 0, 0.1);
  z-index: 1000;
  position: relative;
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
  transition: transform 0.3s ease-in-out;
  position: absolute;
  top: 0;
  left: 0;
  width: 100%;
  height: 100%;
  margin: 0 !important;
}

.content-area {
  height: 100%;
  width: 100%;
}

.placeholder-content {
  display: flex;
  justify-content: center;
  align-items: center;
  height: 100%;
  background-color: #fff;
}
</style>