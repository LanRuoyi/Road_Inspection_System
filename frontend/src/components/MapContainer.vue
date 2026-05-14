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
import L from 'leaflet'

// 解决插件依赖全局L的问题
if (typeof window !== 'undefined') {
  window.L = L

  // 修复 Canvas willReadFrequently 警告
  const originalGetContext = HTMLCanvasElement.prototype.getContext;
  HTMLCanvasElement.prototype.getContext = function(type, attributes) {
    if (type === '2d') {
      attributes = { ...attributes, willReadFrequently: true };
    }
    return originalGetContext.call(this, type, attributes);
  };
}

import 'leaflet/dist/leaflet.css'
import 'leaflet.markercluster';
import 'leaflet.heat';
import { ZoomIn, ZoomOut, Refresh } from '@element-plus/icons-vue'
import { fetchMapTypes, fetchRecords, fetchSystemSettings, apiClient } from '../api';
import FloatingWindow from './FloatingWindow.vue';

import { FALLBACK_CENTER, DEFAULT_MAP_TYPES, HEATMAP_GRADIENT, HEATMAP_DEFAULTS } from '../utils/constants'
import { sleep, requestWithRetry, isValidLatLon, isZeroLikeLocation, toFiniteNumber, parseRecordTimeMs, parseDayStartMs, parseDayEndMs, isRecordWithinTimeRange } from '../utils/helpers'
import { useMapCore } from '../composables/useMapCore'

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
  diseaseType: {
    type: String,
    default: 'all'
  },
  startDate: {
    type: String,
    default: ''
  },
  endDate: {
    type: String,
    default: ''
  },
  showHeatmap: {
    type: Boolean,
    default: false
  },
  sidebarWidth: {
    type: Number,
    default: 300
  },
  initialView: {
    type: Object,
    default: () => ({
      lat: null,
      lon: null,
      zoom: null,
    })
  },
  settingsVersion: {
    type: Number,
    default: 0
  }
})

const emit = defineEmits(['viewStateChange'])

const {
  currentLat,
  currentLng,
  mapTypes,
  getInitialView,
  emitViewState,
} = useMapCore()

// 地图 Leaflet 实例（非响应式）
let map = null
let currentLayer = null
let heatLayer = null
let heatBgLayer = null

// 存储所有病害记录
const diseaseRecords = ref([])

// 存储所有标记点
const markers = ref([])

// 存储筛选后的标记点
const filteredMarkers = ref([])

// 标记点聚合组
let markerClusterGroup = null

// 悬浮窗状态
const floatingWindowVisible = ref(false)
const selectedDisease = ref(null)

// 监听筛选条件变化，重新筛选标记点
watch(() => [props.diseaseType, props.startDate, props.endDate], ([newType, startDate, endDate]) => {
  console.log('病害筛选变化:', { type: newType, startDate, endDate })
  filterMarkersByType(newType, startDate, endDate)
})

// 创建带图片缩略图的标记点图标
const createThumbnailMarker = (recordId, diseaseType) => {
  // 使用API基础URL构建图片URL
  const imageUrl = `${apiClient.defaults.baseURL}/image/${recordId}`;
  
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
    iconSize: [50, 60], // 固定尺寸：宽50px，高60px (50px正方形 + 10px三角形)
    iconAnchor: [25, 60], // 锚点：X轴居中(25)，Y轴最底部(60) -> 确保三角形尖端对准坐标
    popupAnchor: [0, -60] // 弹窗位置：顶部上方
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
    iconSize: [50, 60], // 固定尺寸：与普通标记点一致
    iconAnchor: [25, 60] // 锚点：X轴居中(25)，Y轴最底部(60) -> 确保三角形尖端对准坐标
  });
};

// 获取地图类型配置
const fetchMapTypesData = async () => {
  try {
    const response = await requestWithRetry(() => fetchMapTypes(), {
      retries: 2,
      delayMs: 1200,
      label: '获取地图类型'
    });
    mapTypes.value = Array.isArray(response.data) ? response.data : [];
    if (mapTypes.value.length === 0) {
      mapTypes.value = [...DEFAULT_MAP_TYPES];
    }
    if (map) {
      switchMapLayer(props.mapType);
    }
  } catch (error) {
    console.error('获取地图类型失败:', error);
    mapTypes.value = [...DEFAULT_MAP_TYPES];
    if (map) {
      switchMapLayer(props.mapType);
    }
  }
};

const initCenterFromBrowserLocation = async () => {
  const remembered = getInitialView(props.initialView)
  if (remembered) {
    if (isValidLatLon(remembered.lat, remembered.lon) && !isZeroLikeLocation(remembered.lat, remembered.lon)) {
      currentLat.value = remembered.lat
      currentLng.value = remembered.lon
      return
    }
  }

  try {
    const settingsResp = await fetchSystemSettings()
    const location = settingsResp?.data?.default_location
    if (Array.isArray(location) && location.length >= 2) {
      const lat = Number(location[0])
      const lon = Number(location[1])
      if (isValidLatLon(lat, lon) && !isZeroLikeLocation(lat, lon)) {
        currentLat.value = lat
        currentLng.value = lon
      }
    }
  } catch (error) {
    // 后端不可用时使用本地默认中心
    currentLat.value = FALLBACK_CENTER.lat
    currentLng.value = FALLBACK_CENTER.lon
  }

  if (!navigator.geolocation) {
    return;
  }

  await new Promise((resolve) => {
    navigator.geolocation.getCurrentPosition(
      (position) => {
        const lat = Number(position?.coords?.latitude);
        const lon = Number(position?.coords?.longitude);
        if (isValidLatLon(lat, lon) && !isZeroLikeLocation(lat, lon)) {
          currentLat.value = lat;
          currentLng.value = lon;
        }
        resolve();
      },
      () => resolve(),
      {
        enableHighAccuracy: false,
        timeout: 3000,
        maximumAge: 300000,
      }
    );
  });
};

// 加载病害记录并在地图上显示标记点
const loadDiseaseRecords = async () => {
  try {
    console.log('开始加载病害记录...');
    const response = await requestWithRetry(() => fetchRecords(), {
      retries: 2,
      delayMs: 1200,
      label: '加载病害记录'
    });
    diseaseRecords.value = Array.isArray(response.data) ? response.data : [];
    console.log('成功加载病害记录:', diseaseRecords.value);
    
    // 在地图上显示标记点
    if (map) {
      addMarkersToMap();
    }
  } catch (error) {
    console.error('加载病害记录失败:', error);
    diseaseRecords.value = [];
    clearMarkers();
  }
};

// 根据病害类型筛选标记点
const filterMarkersByType = (type, startDate = props.startDate, endDate = props.endDate) => {
  console.log(`开始筛选标记点，类型: ${type}`);
  
  // 先清除地图上的所有标记点
  if (markerClusterGroup && map) {
    map.removeLayer(markerClusterGroup);
    markerClusterGroup.clearLayers();
  }
  
  // 根据类型筛选标记点
  if (type === 'all') {
    // 分布页选择全部时展示全部记录（包含无病害条目），仅受时间范围限制。
    filteredMarkers.value = markers.value.filter(marker => {
      const record = marker.options.record;
      return isRecordWithinTimeRange(record, startDate, endDate);
    });
  } else {
    // 只显示指定类型的标记点
    filteredMarkers.value = markers.value.filter(marker => {
      const record = marker.options.record;
      if (!record) return false;
      if (!isRecordWithinTimeRange(record, startDate, endDate)) return false;
      const types = Array.isArray(record.types) ? record.types.filter(Boolean) : [];
      if (types.length > 0) {
        return types.includes(type);
      }
      return record.type === type;
    });
  }
  
  console.log(`筛选结果: 总共 ${markers.value.length} 个标记点，筛选后 ${filteredMarkers.value.length} 个`);
  
  // 重新创建聚合组
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
  
  // 将筛选后的标记点添加到聚合组
  filteredMarkers.value.forEach(marker => {
    markerClusterGroup.addLayer(marker);
  });
  
  // 将聚合组添加到地图
  if (map && markerClusterGroup) {
    if (!map.hasLayer(markerClusterGroup) && filteredMarkers.value.length > 0) {
      map.addLayer(markerClusterGroup);
    }
  }

  // 总是更新图层可见性以处理筛选后的热力图显示
  updateLayersVisibility();
};

// 更新图层显隐（控制 Marker 和 热力图）
const updateLayersVisibility = () => {
  if (!map) return;

  // 缩略图预览始终保留，热力图只做叠加层。
  if (markerClusterGroup && !map.hasLayer(markerClusterGroup) && filteredMarkers.value.length > 0) {
    map.addLayer(markerClusterGroup);
  }

  // 1. 处理热力图
  if (props.showHeatmap) {
    // 清理旧层
    if (heatLayer) {
      map.removeLayer(heatLayer);
      heatLayer = null;
    }
    if (heatBgLayer) {
      map.removeLayer(heatBgLayer);
      heatBgLayer = null;
    }
    
    // 准备热力图数据: [lat, lng, intensity]
    // 使用 filteredMarkers (筛选后的点)
    let maxIntensity = 0;
    const heatData = filteredMarkers.value.map(marker => {
      // 获取记录信息，marker.options.record 应该包含后端数据
      const record = marker.options.record;
      if (!record) return [marker.getLatLng().lat, marker.getLatLng().lng, 1.0];
      
      // 使用后端传来的 area 作为权重
      const intensity = record.area ? record.area : 1.0; 
      if (intensity > maxIntensity) maxIntensity = intensity;

      return [record.lat, record.lon, intensity];
    });

    console.log('准备渲染热力图，数据点数量:', heatData.length, '最大权重:', maxIntensity);
    if (heatData.length > 0) {
      // 检查L.heatLayer是否存在
      if (typeof L.heatLayer !== 'function') {
        console.error('L.heatLayer 未定义，leaflet.heat 插件可能未能正确加载');
        return;
      }
      
      try {
        const finalMax = maxIntensity > 0 ? maxIntensity : 1.0;

        // 1. 添加背景层：覆盖全图的半透明蓝色矩形
        // 确保背景层在热力图之下：创建一个自定义 Pane 或者使用 bringToBack
        if (!map.getPane('heatBackgroundPane')) {
            map.createPane('heatBackgroundPane');
            // TilePane is 200, OverlayPane is 400. 
            // 设置为 350 保证在地图之上，但在热力图(400)之下
            map.getPane('heatBackgroundPane').style.zIndex = 350;
            // 解决鼠标事件穿透问题（防止遮挡底图交互）
            map.getPane('heatBackgroundPane').style.pointerEvents = 'none'; 
        }

        const bounds = [[-90, -180], [90, 180]];
        heatBgLayer = L.rectangle(bounds, {
          pane: 'heatBackgroundPane', // 指定 Pane
          color: 'blue',       
          weight: 0,           
          fillColor: 'blue',   
          fillOpacity: 0.3, // 基础底色透明度
          interactive: false   
        });
        heatBgLayer.addTo(map);
        
        // 2. 添加热力图层 (默认在 overlayPane, zIndex 400)
        heatLayer = L.heatLayer(heatData, {
          radius: HEATMAP_DEFAULTS.radius,
          blur: HEATMAP_DEFAULTS.blur,
          maxZoom: HEATMAP_DEFAULTS.maxZoom,
          max: finalMax * HEATMAP_DEFAULTS.maxMultiplier,
          minOpacity: HEATMAP_DEFAULTS.minOpacity,
          gradient: HEATMAP_GRADIENT,
        });
        
        heatLayer.addTo(map);
        
        console.log('热力图层及背景已添加到地图');
           
      } catch (e) {
        console.error('创建热力图层失败:', e);
      }
    } else {
        console.warn('热力图数据为空');
        // 如果数据为空但也想显示蓝色底色，可以在这里解开注释
        /*
        const bounds = [[-90, -180], [90, 180]];
        heatBgLayer = L.rectangle(bounds, {
          color: 'blue', weight: 0, fillColor: 'blue', fillOpacity: 0.3, interactive: false   
        });
        heatBgLayer.addTo(map);
        */
    }
  } else {
      // 关闭热力图
      if (heatLayer) {
        map.removeLayer(heatLayer);
        heatLayer = null;
      }
      if (heatBgLayer) {
        map.removeLayer(heatBgLayer);
        heatBgLayer = null;
      }
      // 标记图层保持常驻，无需额外处理。
  }
}
// 监听热力图开关
watch(() => props.showHeatmap, (val) => {
  console.log('热力图开关:', val);
  updateLayersVisibility();
});

// 在地图上添加标记点
const addMarkersToMap = () => {
  // 先清除现有的标记点
  clearMarkers();
  
  // 创建标记点聚合组
  if (!markerClusterGroup) {
    markerClusterGroup = L.markerClusterGroup({
      chunkedLoading: true,
      maxClusterRadius: 20,
      spiderfyOnMaxZoom: true,
      showCoverageOnHover: false,
      zoomToBoundsOnClick: true,
      iconCreateFunction: createClusterIcon
    });
  }
  
  diseaseRecords.value.forEach(record => {
    try {
      const lat = toFiniteNumber(record.lat)
      const lon = toFiniteNumber(record.lon)
      if (lat === null || lon === null) {
        return;
      }

      record.lat = lat
      record.lon = lon

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
  
  // 初始筛选标记点
  filterMarkersByType(props.diseaseType, props.startDate, props.endDate);
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
  const mapConfig = mapTypes.value.find((item) => item.value === type) || mapTypes.value[0];
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
      maxNativeZoom: 18,
      maxZoom: 22,
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
      zoom: getInitialView(props.initialView)?.zoom || 13,
      zoomControl: false,
      maxZoom: 22
    })

    // 使用后端配置初始化底图图层
    switchMapLayer(props.mapType)

    // 添加缩放控件
    L.control.zoom({
      position: 'topright'
    }).addTo(map)

    // 监听地图移动事件
    map.on('move', updateCoordinates)
    map.on('moveend', () => emitViewState(map, emit))
    map.on('zoomend', () => emitViewState(map, emit))

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
    const remembered = getInitialView(props.initialView)
    if (remembered) {
      map.setView([remembered.lat, remembered.lon], remembered.zoom)
    } else {
      map.setView([currentLat.value, currentLng.value], 13)
    }
  }
}

// 关闭悬浮窗
const closeFloatingWindow = () => {
  floatingWindowVisible.value = false;
  selectedDisease.value = null;
}

const refreshMapViewport = () => {
  if (!map) return
  const center = map.getCenter()
  const zoom = map.getZoom()
  map.invalidateSize({ pan: false, animate: false })
  map.setView(center, zoom, { animate: false })
  currentLat.value = center.lat
  currentLng.value = center.lng
}

watch(
  () => [props.sidebarCollapsed, props.sidebarWidth],
  async () => {
    await nextTick()
    setTimeout(() => {
      refreshMapViewport()
    }, 60)
    setTimeout(() => {
      refreshMapViewport()
    }, 320)
  }
)

// 监听地图类型变化
watch(() => props.mapType, (newType) => {
  if (map) {
    switchMapLayer(newType)
  }
})

watch(() => props.settingsVersion, async () => {
  await fetchMapTypesData()
})

// 生命周期
onMounted(() => {
  console.log('MapContainer组件已挂载')
  // 先获取配置，再初始化地图
  fetchMapTypesData().then(async () => {
    await initCenterFromBrowserLocation()
    // 配置获取完成后初始化地图
    initMap()

    setTimeout(() => {
      emitViewState(map, emit)
    }, 120)
    
    // 地图初始化完成后加载病害记录
    setTimeout(() => {
      loadDiseaseRecords();
    }, 500);
  })
})

onUnmounted(() => {
  emitViewState(map, emit)
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
}

:deep(.marker-square) {
  width: 50px;
  height: 50px;
  background: white;
  border: 2px solid #ffffff; /* 白色边框 */
  border-radius: 8px;
  box-shadow: 0 2px 6px rgba(0,0,0,0.3);
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
  top: 2px;
  right: 2px;
  background: rgba(255, 255, 255, 0.95);
  color: #333;
  font-size: 10px;
  padding: 1px 4px;
  border-radius: 3px;
  font-weight: bold;
  border: 1px solid #f0f0f0;
}

:deep(.marker-triangle) {
  width: 0;
  height: 0;
  border-left: 8px solid transparent;
  border-right: 8px solid transparent;
  border-top: 10px solid #ffffff;
  margin-top: -1px;
  filter: drop-shadow(0 2px 1px rgba(0,0,0,0.1));
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