<template>
  <div class="map-container">
    <!-- 地图工具栏 -->
    <div class="map-toolbar">
      <el-button-group>
        <el-button size="small" @click="zoomIn">
          <el-icon><ZoomIn /></el-icon>
        </el-button>
        <el-button size="small" @click="zoomOut">
          <el-icon><ZoomOut /></el-icon>
        </el-button>
      </el-button-group>
      
      <el-button size="small" @click="resetView">
        <el-icon><Refresh /></el-icon>
        重置视图
      </el-button>
      
      <div class="coordinate-display">
        经度: {{ currentLng.toFixed(6) }}, 纬度: {{ currentLat.toFixed(6) }}
      </div>
    </div>
    
    <!-- 地图容器 -->
    <div id="map" class="map"></div>
    
    <!-- 悬浮窗 -->
    <FloatingWindow
      v-if="floatingWindowVisible"
      :data="selectedDisease"
      :visible="floatingWindowVisible"
      :sidebar-width="props.sidebarWidth"
      @close="closeFloatingWindow"
    />

  </div>
</template>

<script setup>
import { ref, onMounted, onUnmounted, watch, nextTick } from 'vue'
import axios from 'axios'
import L from 'leaflet'
import 'leaflet/dist/leaflet.css'
import 'leaflet.markercluster';
import * as LeafletMarkerCluster from 'leaflet.markercluster'

// 正确导入 MarkerClusterGroup
const MarkerClusterGroup = LeafletMarkerCluster.default || LeafletMarkerCluster
import {
  ZoomIn,
  ZoomOut,
  Refresh
} from '@element-plus/icons-vue'
import { fetchMapTypes, fetchDiseaseImages, fetchRecords, apiClient } from '../api';
import FloatingWindow from './FloatingWindow.vue';

// 组件属性
const props = defineProps({
  sidebarCollapsed: {
    type: Boolean,
    default: false
  },
  mapType: {
    type: String,
    default: 'normal'
  },
  sidebarWidth: {
    type: Number,
    default: 300
  }
})

// 地图实例
let map = null
let currentLayer = null

// 当前坐标
const currentLng = ref(116.3974)
const currentLat = ref(39.9093)

// 地图类型配置
const mapTypes = ref([])

// 存储所有病害记录
const diseaseRecords = ref([])

// 存储所有标记点
const markers = ref([])

// 标记点聚合组
let markerClusterGroup = null

// 悬浮窗状态
const floatingWindowVisible = ref(false)
const selectedDisease = ref(null)

// 创建带图片缩略图的标记点图标
const createThumbnailMarker = (recordId, diseaseType) => {
  // 使用API基础URL构建图片URL
  const imageUrl = `${apiClient.defaults.baseURL}/image/${recordId}`;
  
  // 使用相对单位（vw）定义尺寸
  const squareSize = '4vw'; // 正方形大小（相对于视口宽度）
  const triangleHeight = '1.5vw'; // 三角形高度
  const totalHeight = `calc(${squareSize} + ${triangleHeight})`;
  
  // 标记点HTML结构：上面是正方形图片，下面是指向三角形
  const html = `
    <div class="thumbnail-marker">
      <div class="marker-square">
        <img src="${imageUrl}" alt="病害图片" class="thumbnail-image" />
      </div>
      <div class="marker-triangle"></div>
    </div>
  `;
  
  return L.divIcon({
    html: html,
    className: 'thumbnail-marker-container',
    iconSize: [80, 100], // 使用固定像素作为基础尺寸，CSS会覆盖
    iconAnchor: [40, 90] // 锚点在三角形顶点
  });
};

// 默认标记点图标（用于没有图片的情况）
const defaultIcons = {
  crack: L.divIcon({
    html: '<div style="background-color: #f56c6c; width: 20px; height: 20px; border-radius: 50%; border: 2px solid white; box-shadow: 0 2px 4px rgba(0,0,0,0.3);"></div>',
    className: 'disease-marker',
    iconSize: [20, 20],
    iconAnchor: [10, 10]
  }),
  pothole: L.divIcon({
    html: '<div style="background-color: #e6a23c; width: 20px; height: 20px; border-radius: 50%; border: 2px solid white; box-shadow: 0 2px 4px rgba(0,0,0,0.3);"></div>',
    className: 'disease-marker',
    iconSize: [20, 20],
    iconAnchor: [10, 10]
  }),
  subsidence: L.divIcon({
    html: '<div style="background-color: #67c23a; width: 20px; height: 20px; border-radius: 50%; border: 2px solid white; box-shadow: 0 2px 4px rgba(0,0,0,0.3);"></div>',
    className: 'disease-marker',
    iconSize: [20, 20],
    iconAnchor: [10, 10]
  })
};

// 创建聚合标记点图标
const createClusterIcon = (cluster) => {
  const childCount = cluster.getChildCount();

  // 获取第一个标记点的图片作为缩略图
  let thumbnailUrl = '';
  const childMarkers = cluster.getAllChildMarkers();
  if (childMarkers.length > 0) {
    const firstRecord = childMarkers[0].options.record;
    if (firstRecord) {
      thumbnailUrl = `${apiClient.defaults.baseURL}/image/${firstRecord.id}`;
    }
  }

  // 聚合图标HTML结构，移除外围圆形样式
  const html = `
    <div class="thumbnail-marker">
      <div class="marker-square">
        ${thumbnailUrl ? `<img src="${thumbnailUrl}" alt="聚合缩略图" class="thumbnail-image" />` : ''}
      </div>
      <div class="marker-triangle"></div>
      <div class="cluster-count">${childCount}</div>
    </div>
  `;

  return L.divIcon({
    html: html,
    className: 'thumbnail-marker-container',
    iconSize: [80, 100], // 使用与离散标记点相同的尺寸
    iconAnchor: [40, 90] // 锚点在三角形顶点
  });
};

// 获取地图类型配置
const fetchMapTypesData = async () => {
  try {
    const response = await fetchMapTypes();
    mapTypes.value = response.data;
    if (map) {
      switchMapLayer(props.mapType);
    }
  } catch (error) {
    console.error('获取地图类型失败:', error);
  }
};

// 加载病害记录并在地图上显示标记点
const loadDiseaseRecords = async () => {
  try {
    console.log('开始加载病害记录...');
    const response = await fetchRecords();
    diseaseRecords.value = response.data;
    console.log('成功加载病害记录:', diseaseRecords.value);
    
    // 在地图上显示标记点
    if (map) {
      addMarkersToMap();
    }
  } catch (error) {
    console.error('加载病害记录失败:', error);
  }
};

// 在地图上添加标记点
const addMarkersToMap = () => {
  // 先清除现有的标记点
  clearMarkers();
  
  // 创建标记点聚合组
  if (!markerClusterGroup) {
    markerClusterGroup = L.markerClusterGroup({
      chunkedLoading: true,
      maxClusterRadius: 80,
      spiderfyOnMaxZoom: true,
      showCoverageOnHover: false,
      zoomToBoundsOnClick: true,
      iconCreateFunction: createClusterIcon
    });
  }
  
  diseaseRecords.value.forEach(record => {
    try {
      // 创建标记点（使用缩略图样式）
      const marker = L.marker([record.lat, record.lon], {
        icon: createThumbnailMarker(record.id, record.type),
        record: record // 保存记录信息用于聚合图标
      });
      
      // 添加点击事件，显示悬浮窗
      marker.on('click', () => {
        console.log(`点击了病害标记: ${record.id} (${record.type})`);
        selectedDisease.value = record;
        floatingWindowVisible.value = true;
      });
      
      // 添加到聚合组
      markerClusterGroup.addLayer(marker);
      markers.value.push(marker);
      
      console.log(`成功添加标记点: ${record.id} (${record.lat}, ${record.lon})`);
    } catch (error) {
      console.error(`添加标记点失败 (${record.id}):`, error);
      // 如果缩略图标记失败，使用默认标记点
      try {
        const fallbackMarker = L.marker([record.lat, record.lon], {
          icon: defaultIcons[record.type] || defaultIcons.crack,
          record: record
        });
        markerClusterGroup.addLayer(fallbackMarker);
        markers.value.push(fallbackMarker);
        console.log(`使用默认标记点: ${record.id}`);
      } catch (fallbackError) {
        console.error(`默认标记点也失败 (${record.id}):`, fallbackError);
      }
    }
  });
  
  // 将聚合组添加到地图
  if (map && markerClusterGroup) {
    map.addLayer(markerClusterGroup);
  }
  
  console.log(`总共添加了 ${markers.value.length} 个标记点`);
};

// 清除所有标记点
const clearMarkers = () => {
  if (markerClusterGroup && map) {
    map.removeLayer(markerClusterGroup);
    markerClusterGroup.clearLayers();
  }
  markers.value = [];
};

// 切换地图图层
const switchMapLayer = (type) => {
  console.log(`切换地图图层，目标类型: ${type}`);

  // 移除当前图层
  if (currentLayer) {
    try {
      map.removeLayer(currentLayer);
      console.log('成功移除当前图层');
    } catch (error) {
      console.warn('移除当前图层失败:', error);
    }
  } else {
    console.log('当前没有图层需要移除');
  }

  // 查找对应的地图配置
  const mapConfig = mapTypes.value.find((item) => item.value === type);
  if (!mapConfig || !mapConfig.url) {
    console.warn('未找到对应的地图配置或 URL 无效:', type);
    return;
  }

  try {
    // 替换动态占位符 {s}，确保 subdomains 有效
    const subdomain = mapConfig.subdomains && mapConfig.subdomains.length > 0 ? mapConfig.subdomains[0] : '';
    const url = mapConfig.url.replace('{s}', subdomain);
    console.log(`生成的地图 URL: ${url}`);

    // 创建新的瓦片图层
    currentLayer = L.tileLayer(url, {
      subdomains: mapConfig.subdomains || [],
      attribution: mapConfig.attribution || '&copy; <a href="https://www.amap.com/">高德地图</a>',
    });

    // 添加到地图
    currentLayer.addTo(map);
    console.log(`成功切换到地图图层: ${type}`);
  } catch (error) {
    console.error('切换地图图层失败:', error);
  }
}

// 初始化地图
const initMap = () => {
  // 确保DOM元素存在
  const mapElement = document.getElementById('map')
  if (!mapElement) {
    console.error('地图容器元素未找到')
    // 延迟重试
    setTimeout(initMap, 100)
    return
  }

  // 检查地图是否已经初始化
  if (map) {
    console.log('地图已经初始化，跳过重复初始化')
    return
  }

  try {
    console.log('开始初始化地图...')
    
    // 创建地图实例
    map = L.map('map', {
      center: [currentLat.value, currentLng.value],
      zoom: 13,
      zoomControl: false
    })

    // 添加默认图层（使用默认配置）
    const defaultLayer = L.tileLayer(
      'https://webrd01.is.autonavi.com/appmaptile?lang=zh_cn&size=1&scale=1&style=8&x={x}&y={y}&z={z}',
      {
        subdomains: ['1', '2', '3', '4'],
        attribution: '&copy; <a href="https://www.amap.com/">高德地图</a>'
      }
    )
    
    defaultLayer.addTo(map)
    currentLayer = defaultLayer

    // 添加缩放控件
    L.control.zoom({
      position: 'topright'
    }).addTo(map)

    // 监听地图移动事件
    map.on('move', updateCoordinates)

    // 强制刷新地图尺寸
    setTimeout(() => {
      if (map) {
        map.invalidateSize()
      }
    }, 100)
    
    console.log('地图初始化成功')
  } catch (error) {
    console.error('地图初始化失败:', error)
  }
}

// 更新坐标显示
const updateCoordinates = () => {
  if (map) {
    const center = map.getCenter()
    currentLat.value = center.lat
    currentLng.value = center.lng
  }
}

// 地图操作函数
const zoomIn = () => {
  if (map) map.zoomIn()
}

const zoomOut = () => {
  if (map) map.zoomOut()
}

const resetView = () => {
  if (map) {
    map.setView([currentLat.value, currentLng.value], 13)
  }
}

// 关闭悬浮窗
const closeFloatingWindow = () => {
  floatingWindowVisible.value = false;
  selectedDisease.value = null;
}

// 辅助函数
const getDiseaseTypeTag = (type) => {
  const typeMap = {
    crack: 'danger',
    pothole: 'warning',
    subsidence: 'success'
  }
  return typeMap[type] || 'info'
}

// 监听侧边栏折叠状态变化
watch(() => props.sidebarCollapsed, async () => {
  // 等待DOM更新完成
  await nextTick()
  
  // 延迟执行，确保容器尺寸已经更新
  setTimeout(() => {
    if (map) {
      // 不再调用invalidateSize()，避免地图中心点重置
      // 地图容器已经扩展到最大宽度，通过CSS平移实现动画效果
      // 这样地图中心点会自然保持，不会强制恢复
      
      // 更新坐标显示为当前实际中心点
      const center = map.getCenter()
      currentLat.value = center.lat
      currentLng.value = center.lng
    }
  }, 300) // 等待侧边栏动画完成
})

// 监听地图类型变化
watch(() => props.mapType, (newType) => {
  if (map) {
    switchMapLayer(newType)
  }
})

// 生命周期
onMounted(() => {
  console.log('MapContainer组件已挂载')
  // 先获取配置，再初始化地图
  fetchMapTypesData().then(() => {
    // 配置获取完成后初始化地图
    initMap()
    
    // 地图初始化完成后加载病害记录
    setTimeout(() => {
      loadDiseaseRecords();
    }, 500);
  })
})

onUnmounted(() => {
  if (map) {
    map.remove()
  }
  if (markerClusterGroup) {
    markerClusterGroup.clearLayers();
  }
})
</script>

<style scoped>
.map-container {
  position: relative;
  height: 100%;
  width: 100%;
}

.map-toolbar {
  position: absolute;
  top: 10px;
  left: 10px;
  z-index: 1000;
  background: white;
  padding: 8px;
  border-radius: 4px;
  box-shadow: 0 2px 8px rgba(0, 0, 0, 0.15);
  display: flex;
  align-items: center;
  gap: 10px;
}

.coordinate-display {
  font-size: 12px;
  color: #666;
  margin-left: 10px;
}

.map {
  height: 100%;
  width: 100%;
}



:deep(.disease-marker) {
  background: transparent !important;
  border: none !important;
}

/* 缩略图标记点样式 - 白色主题，相对大小 */
:deep(.thumbnail-marker-container) {
  background: transparent !important;
  border: none !important;
}

:deep(.thumbnail-marker) {
  position: relative;
  display: flex;
  flex-direction: column;
  align-items: center;
  font-size: 1vw; /* 基础字体大小，用于相对单位计算 */
}

:deep(.marker-square) {
  width: 3vw; /* 相对于视口宽度 */
  height: 3vw;
  min-width: 40px; /* 最小尺寸 */
  min-height: 40px;
  max-width: 80px; /* 最大尺寸 */
  max-height: 80px;
  background: white;
  border: 2px solid #ffffff; /* 白色边框 */
  border-radius: 8px;
  /* 取消阴影 */
  overflow: hidden;
  position: relative;
}

:deep(.thumbnail-image) {
  width: 100%;
  height: 100%;
  object-fit: cover;
}

:deep(.disease-badge) {
  position: absolute;
  top: 0.2vw;
  right: 0.2vw;
  background: rgba(255, 255, 255, 0.95); /* 白色背景 */
  color: #333; /* 深色文字 */
  font-size: 0.8vw;
  padding: 0.2vw 0.5vw;
  border-radius: 3px;
  font-weight: bold;
  border: 1px solid #f0f0f0;
}

:deep(.marker-triangle) {
  width: 0;
  height: 0;
  border-left: 1.1vw solid transparent; /* 加宽底部 */
  border-right: 1.1vw solid transparent;
  border-top: 0.7vw solid #ffffff; /* 降低高度 */
  margin-top: -1px;
}

/* 聚合标记点样式 */
:deep(.cluster-marker-container) {
  background: transparent !important;
  border: none !important;
}

:deep(.cluster-marker) {
  position: relative;
  display: flex;
  align-items: center;
  justify-content: center;
}

:deep(.cluster-thumbnail) {
  width: 60px;
  height: 60px;
  background: white;
  border: 3px solid #1890ff;
  border-radius: 50%;
  box-shadow: 0 4px 12px rgba(0, 0, 0, 0.3);
  overflow: hidden;
  position: relative;
  display: flex;
  align-items: center;
  justify-content: center;
}

:deep(.cluster-image) {
  width: 100%;
  height: 100%;
  object-fit: cover;
  border-radius: 50%;
}

:deep(.cluster-placeholder) {
  width: 100%;
  height: 100%;
  background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
  border-radius: 50%;
}

:deep(.cluster-count) {
  position: absolute;
  top: -5px;
  right: -5px;
  background: #ff4d4f;
  color: white;
  font-size: 12px;
  font-weight: bold;
  min-width: 20px;
  height: 20px;
  border-radius: 10px;
  display: flex;
  align-items: center;
  justify-content: center;
  border: 2px solid white;
  box-shadow: 0 2px 4px rgba(0, 0, 0, 0.3);
}
</style>