<template>
  <div class="sidebar" :class="{ 'collapsed': collapsed }">
    <!-- 系统标题 -->
    <div class="sidebar-header">
      <h1 class="system-title" :class="{ 'collapsed': collapsed }">道路病害检测系统</h1>
      <div class="system-icon" :class="{ 'collapsed': !collapsed }">
        <el-icon :size="24"><MapLocation /></el-icon>
      </div>
    </div>
    
    <!-- 功能选择菜单 -->
    <div class="menu-section">
      <el-menu
        :default-active="activeTab"
        class="function-menu"
        @select="handleMenuSelect"
        :collapse="collapsed"
      >
        <el-menu-item index="disease-distribution">
          <el-icon><MapLocation /></el-icon>
          <span class="menu-text" :class="{ 'collapsed': collapsed }">病害分布</span>
        </el-menu-item>
        
        <el-menu-item index="real-time-monitor">
          <el-icon><VideoCamera /></el-icon>
          <span class="menu-text" :class="{ 'collapsed': collapsed }">实时监看</span>
        </el-menu-item>
        
        <el-menu-item index="parameter-config">
          <el-icon><Setting /></el-icon>
          <span class="menu-text" :class="{ 'collapsed': collapsed }">参数配置</span>
        </el-menu-item>
      </el-menu>
    </div>
    
    <!-- 功能内容区域（根据选择的功能动态变化） -->
    <div class="content-section" v-show="!collapsed">
      <!-- 病害分布功能内容 -->
      <div v-if="activeTab === 'disease-distribution'" class="function-content">
        <h4>病害分布设置</h4>
        <el-divider />
        <div class="setting-item">
          <span class="label">地图类型：</span>
          <el-select v-model="mapType" size="small" style="width: 120px">
            <el-option 
              v-for="type in mapTypes" 
              :key="type.value"
              :label="type.label" 
              :value="type.value" 
            />
          </el-select>
        </div>
        <div class="setting-item">
          <span class="label">病害类型：</span>
          <el-select v-model="diseaseType" size="small" style="width: 120px">
            <el-option 
              v-for="type in diseaseTypes" 
              :key="type.value"
              :label="type.label" 
              :value="type.value" 
            />
          </el-select>
        </div>
      </div>
      
      <!-- 实时监看功能内容 -->
      <div v-else-if="activeTab === 'real-time-monitor'" class="function-content">
        <h4>实时监看设置</h4>
        <el-divider />
        <div class="setting-item">
          <el-button type="primary" size="small" style="width: 100%">
            <el-icon><VideoPlay /></el-icon>
            开始监看
          </el-button>
        </div>
        <div class="setting-item">
          <span class="label">监看设备：</span>
          <el-select v-model="cameraDevice" size="small" style="width: 120px">
            <el-option label="摄像头1" value="camera1" />
            <el-option label="摄像头2" value="camera2" />
          </el-select>
        </div>
      </div>
      
      <!-- 参数配置功能内容 -->
      <div v-else-if="activeTab === 'parameter-config'" class="function-content">
        <h4>系统参数配置</h4>
        <el-divider />
        <div class="setting-item">
          <span class="label">检测灵敏度：</span>
          <el-slider v-model="sensitivity" :min="1" :max="10" size="small" />
        </div>
        <div class="setting-item">
          <span class="label">自动保存：</span>
          <el-switch v-model="autoSave" />
        </div>
        <div class="setting-item">
          <el-button type="primary" size="small" style="width: 100%">保存配置</el-button>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, onMounted, watch, onUnmounted } from 'vue'
import axios from 'axios'
import {
  MapLocation,
  VideoCamera,
  Setting,
  VideoPlay
} from '@element-plus/icons-vue'
import { fetchMapTypes, fetchDiseaseTypes } from '../api'

const props = defineProps({
  activeTab: {
    type: String,
    default: 'disease-distribution'
  },
  collapsed: {
    type: Boolean,
    default: false
  }
})

// 定义事件
const emit = defineEmits(['tabChange', 'mapTypeChange', 'sidebarWidthChange', 'diseaseTypeChange'])

// 功能设置数据
const mapType = ref('normal')
const diseaseType = ref('all')
const cameraDevice = ref('camera1')
const sensitivity = ref(5)
const autoSave = ref(true)

// 监听地图类型变化
watch(mapType, (newType) => {
  emit('mapTypeChange', newType)
})

// 监听病害类型变化
watch(diseaseType, (newType) => {
  emit('diseaseTypeChange', newType)
})

// API数据
const mapTypes = ref([])
const diseaseTypes = ref([])

// 获取地图和病害类型数据
const fetchMapAndDiseaseTypes = async () => {
  try {
    const [mapResponse, diseaseResponse] = await Promise.all([
      fetchMapTypes(),
      fetchDiseaseTypes()
    ]);
    mapTypes.value = mapResponse.data;
    diseaseTypes.value = diseaseResponse.data;
  } catch (error) {
    console.error('获取数据失败:', error);
  }
};

// 生命周期
onMounted(() => {
  fetchMapAndDiseaseTypes()
})

// 处理菜单选择
const handleMenuSelect = (index) => {
  emit('tabChange', index)
}

const sidebarWidth = ref(0);

const updateSidebarWidth = () => {
  const sidebarElement = document.querySelector('.sidebar');
  if (sidebarElement) {
    sidebarWidth.value = sidebarElement.offsetWidth;
    emit('sidebarWidthChange', sidebarWidth.value);
  }
};

onMounted(() => {
  updateSidebarWidth();
  const resizeObserver = new ResizeObserver(updateSidebarWidth);
  const sidebarElement = document.querySelector('.sidebar');
  if (sidebarElement) {
    resizeObserver.observe(sidebarElement);
  }
});

onUnmounted(() => {
  const sidebarElement = document.querySelector('.sidebar');
  if (sidebarElement) {
    const resizeObserver = new ResizeObserver(updateSidebarWidth);
    resizeObserver.unobserve(sidebarElement);
  }
});
</script>

<style scoped>
.sidebar {
  height: 100%;
  display: flex;
  flex-direction: column;
  background-color: #fff;
}

.sidebar-header {
  padding: 20px;
  text-align: center;
  border-bottom: 1px solid #e6e6e6;
  position: relative;
  height: 60px;
  display: flex;
  align-items: center;
  justify-content: center;
}

.system-title {
  margin: 0;
  font-size: 18px;
  font-weight: 600;
  color: #333;
  transition: all 0.3s ease 0.1s;
  opacity: 1;
  max-width: 200px;
  white-space: nowrap;
  overflow: hidden;
  position: absolute;
  cursor: default;
  user-select: none;
  -webkit-user-select: none;
  -moz-user-select: none;
  -ms-user-select: none;
}

.system-title.collapsed {
  opacity: 0;
  max-width: 0;
  transition: all 0.1s ease;
}

.system-icon {
  display: flex;
  align-items: center;
  justify-content: center;
  transition: all 0.3s ease 0.1s;
  opacity: 1;
  position: absolute;
}

.system-icon.collapsed {
  opacity: 0;
  transition: all 0.1s ease;
}

.menu-section {
  padding: 20px 0;
  border-bottom: 1px solid #e6e6e6;
}

.menu-title {
  margin: 0 20px 10px;
  font-size: 14px;
  color: #666;
  font-weight: 500;
}

.function-menu {
  border-right: none;
}

.menu-text {
  transition: opacity 0.2s ease 0.1s, max-width 0.3s ease;
  opacity: 1;
  max-width: 100px;
  white-space: nowrap;
  overflow: hidden;
  display: inline-block;
  vertical-align: middle;
  cursor: default;
  user-select: none;
  -webkit-user-select: none;
  -moz-user-select: none;
  -ms-user-select: none;
}

.menu-text.collapsed {
  opacity: 0;
  max-width: 0;
  margin-left: 0;
  transition: opacity 0.1s ease, max-width 0.3s ease 0.1s;
}

:deep(.el-menu--collapse .el-menu-item) {
  padding: 0 20px !important;
}

:deep(.el-menu--collapse .el-menu-item .el-icon) {
  margin-right: 0 !important;
}

.content-section {
  flex: 1;
  padding: 20px;
  overflow-y: auto;
}

.function-content h4 {
  margin: 0 0 15px 0;
  font-size: 16px;
  color: #333;
  font-weight: 500;
  cursor: default;
  user-select: none;
  -webkit-user-select: none;
  -moz-user-select: none;
  -ms-user-select: none;
}

.setting-item {
  margin-bottom: 15px;
  display: flex;
  align-items: center;
  justify-content: space-between;
}

.label {
  font-size: 14px;
  color: #666;
  cursor: default;
  user-select: none;
  -webkit-user-select: none;
  -moz-user-select: none;
  -ms-user-select: none;
  min-width: 80px;
}

:deep(.el-divider) {
  margin: 15px 0;
}
</style>