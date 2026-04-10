<template>
  <div class="map-container">
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

      <div class="toolbar-hint">
        右键建点，ESC 结束绘制，Delete 删除选中
      </div>

      <div class="coordinate-display">
        经度: {{ currentLng.toFixed(6) }}, 纬度: {{ currentLat.toFixed(6) }}
      </div>
    </div>

    <div id="analysis-map" class="map"></div>

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
import * as turf from '@turf/turf'
import 'leaflet/dist/leaflet.css'
import 'leaflet.heat'
import { ZoomIn, ZoomOut, Refresh } from '@element-plus/icons-vue'
import { ElMessage } from 'element-plus'
import {
  fetchMapTypes,
  fetchRecords,
  fetchSystemSettings,
  assessAnalysisSegments,
  fetchAnalysisInstances,
  saveAnalysisInstances,
  deleteAnalysisInstances,
} from '../api'
import FloatingWindow from './FloatingWindow.vue'

const FALLBACK_CENTER = {
  lat: 39.9042,
  lon: 116.4074,
}

if (typeof window !== 'undefined') {
  window.L = L
}

const MIXED_VALUE_TOKEN = '__MIXED__'

const DEFAULT_MAP_TYPES = [
  {
    value: 'normal',
    label: '标准地图',
    url: 'https://webrd0{s}.is.autonavi.com/appmaptile?lang=zh_cn&size=1&scale=1&style=8&x={x}&y={y}&z={z}',
    subdomains: ['1', '2', '3', '4']
  },
  {
    value: 'satellite',
    label: '卫星地图',
    url: 'https://webst0{s}.is.autonavi.com/appmaptile?style=6&x={x}&y={y}&z={z}',
    subdomains: ['1', '2', '3', '4']
  },
  {
    value: 'terrain',
    label: '地形地图',
    url: 'https://webst0{s}.is.autonavi.com/appmaptile?style=7&x={x}&y={y}&z={z}',
    subdomains: ['1', '2', '3', '4']
  }
]

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
  analysisConfig: {
    type: Object,
    default: () => ({
      instance_defaults: {},
      param_schema: [],
      status_colors: {}
    })
  },
  analysisCommand: {
    type: Object,
    default: () => ({
      seq: 0,
      type: 'noop'
    })
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

const emit = defineEmits(['analysisSelectionChange', 'viewStateChange'])

let map = null
let currentLayer = null
let mapClickLock = false
const mapTypes = ref([])
let heatLayer = null
let heatBgLayer = null

const currentLng = ref(116.3974)
const currentLat = ref(39.9093)

const diseaseRecords = ref([])
const filteredRecords = ref([])
const assessableRecords = ref([])
const recordLayer = L.layerGroup()

const instances = ref([])
const selectedInstanceIds = ref([])
const selectedEndpoint = ref(null)
const drawingState = ref({
  active: false,
  instanceId: null
})

const instanceLayers = new Map()

const floatingWindowVisible = ref(false)
const selectedDisease = ref(null)

const UNKNOWN_TYPE_SET = new Set(['unknown', 'unknow', 'none', 'null', 'n/a', 'na', '-', '--'])

let keyboardHandler = null
let assessTimer = null
let persistTimer = null
let persistInFlight = false
let persistPending = false
let lastPersistErrorAt = 0

const previewInstanceId = ref('')

const toFiniteNumber = (v) => {
  const n = Number(v)
  return Number.isFinite(n) ? n : null
}

const isValidLatLon = (lat, lon) => {
  return Number.isFinite(lat) && Number.isFinite(lon)
    && lat >= -90 && lat <= 90
    && lon >= -180 && lon <= 180
}

const isZeroLikeLocation = (lat, lon) => {
  return Math.abs(lat) < 1e-6 && Math.abs(lon) < 1e-6
}

const getInitialView = () => {
  const lat = toFiniteNumber(props.initialView?.lat)
  const lon = toFiniteNumber(props.initialView?.lon)
  const zoom = toFiniteNumber(props.initialView?.zoom)
  if (lat == null || lon == null || zoom == null) {
    return null
  }
  return {
    lat,
    lon,
    zoom,
  }
}

const emitViewState = () => {
  if (!map) return
  const center = map.getCenter()
  emit('viewStateChange', {
    lat: center.lat,
    lon: center.lng,
    zoom: map.getZoom(),
  })
}

const getNowId = () => `${Date.now()}_${Math.random().toString(16).slice(2, 8)}`

const getDefaultParams = () => {
  const defaults = props.analysisConfig?.instance_defaults || {}
  return {
    section_width_m: 7.5,
    prediction_years: 3,
    aadtt_k_per_day: 2,
    traffic_growth_rate: 0.02,
    lane_distribution_factor: 0.8,
    surface_type: 'AC',
    asphalt_thickness_m: 0.15,
    base_thickness_m: 0.3,
    subgrade_modulus_mpa: 50,
    observed_pci_drop: 5,
    observed_years: 1,
    ...defaults
  }
}

const getStatusColor = (status) => {
  const colorMap = props.analysisConfig?.status_colors || {}
  if (status && colorMap[status]) {
    return colorMap[status]
  }

  const fallback = {
    no_data: 'rgba(128, 128, 128, 0.35)',
    healthy: 'rgba(46, 204, 113, 0.35)',
    warning: 'rgba(241, 196, 15, 0.40)',
    danger: 'rgba(231, 76, 60, 0.42)'
  }
  return fallback[status] || fallback.warning
}

const createEndpointIcon = (isSelected) => {
  const size = isSelected ? 14 : 10
  const border = isSelected ? '#409eff' : '#ffffff'
  const bg = isSelected ? '#ffd666' : '#1f78ff'
  const html = `<div style="width:${size}px;height:${size}px;border-radius:50%;background:${bg};border:2px solid ${border};box-shadow:0 1px 3px rgba(0,0,0,0.4);"></div>`

  return L.divIcon({
    html,
    className: 'analysis-endpoint-icon',
    iconSize: [size, size],
    iconAnchor: [size / 2, size / 2]
  })
}

const getRecordMarkerColor = (record) => {
  const t = String(record?.type || '').toLowerCase()
  if (t.includes('fatigue') || t.includes('crack')) return '#ff4d4f'
  if (t.includes('pothole')) return '#fa8c16'
  if (t.includes('rut')) return '#fadb14'
  if (t.includes('patch')) return '#52c41a'
  if (t.includes('bleeding')) return '#13c2c2'
  if (t.includes('raveling')) return '#722ed1'
  return '#1677ff'
}

const isValidDiseaseTypeValue = (value) => {
  if (typeof value !== 'string') return false
  const cleaned = value.trim()
  if (!cleaned) return false
  return !UNKNOWN_TYPE_SET.has(cleaned.toLowerCase())
}

const parseRecordTimeMs = (record) => {
  const parseRawTime = (raw) => {
    if (raw == null) {
      return null
    }

    if (typeof raw === 'number') {
      if (!Number.isFinite(raw)) {
        return null
      }
      return raw > 1e12 ? raw : raw * 1000
    }

    const text = String(raw).trim()
    if (!text) {
      return null
    }

    if (/^\d+$/.test(text)) {
      const num = Number(text)
      if (!Number.isFinite(num)) {
        return null
      }
      return num > 1e12 ? num : num * 1000
    }

    const compactMatch = text.match(/^(\d{8})T(\d{6})/)
    if (compactMatch) {
      const d = compactMatch[1]
      const t = compactMatch[2]
      const y = Number(d.slice(0, 4))
      const m = Number(d.slice(4, 6))
      const day = Number(d.slice(6, 8))
      const hh = Number(t.slice(0, 2))
      const mm = Number(t.slice(2, 4))
      const ss = Number(t.slice(4, 6))
      const ms = new Date(y, m - 1, day, hh, mm, ss, 0).getTime()
      return Number.isFinite(ms) ? ms : null
    }

    const parsed = Date.parse(text)
    return Number.isFinite(parsed) ? parsed : null
  }

  const directCandidates = [
    record?.created_at,
    record?.timestamp,
    record?.record_time,
  ]

  for (const candidate of directCandidates) {
    const parsed = parseRawTime(candidate)
    if (parsed != null) {
      return parsed
    }
  }

  return parseRawTime(record?.id)
}

const parseDayStartMs = (dateText) => {
  if (typeof dateText !== 'string') {
    return null
  }
  const text = dateText.trim()
  if (!text) {
    return null
  }
  const [y, m, d] = text.split('-').map(Number)
  if (!Number.isFinite(y) || !Number.isFinite(m) || !Number.isFinite(d)) {
    return null
  }
  const ms = new Date(y, m - 1, d, 0, 0, 0, 0).getTime()
  return Number.isFinite(ms) ? ms : null
}

const parseDayEndMs = (dateText) => {
  if (typeof dateText !== 'string') {
    return null
  }
  const text = dateText.trim()
  if (!text) {
    return null
  }
  const [y, m, d] = text.split('-').map(Number)
  if (!Number.isFinite(y) || !Number.isFinite(m) || !Number.isFinite(d)) {
    return null
  }
  const ms = new Date(y, m - 1, d, 23, 59, 59, 999).getTime()
  return Number.isFinite(ms) ? ms : null
}

const isRecordWithinTimeRange = (record, startDate, endDate) => {
  const startMs = parseDayStartMs(startDate)
  const endMs = parseDayEndMs(endDate)
  if (startMs == null && endMs == null) {
    return true
  }

  const recordMs = parseRecordTimeMs(record)
  if (recordMs == null) {
    return false
  }

  if (startMs != null && recordMs < startMs) {
    return false
  }
  if (endMs != null && recordMs > endMs) {
    return false
  }
  return true
}

const hasSupportedDisease = (record) => {
  const primaryType = isValidDiseaseTypeValue(record?.type) ? String(record.type).trim() : ''
  const types = Array.isArray(record?.types)
    ? record.types.filter((item) => isValidDiseaseTypeValue(item)).map((item) => String(item).trim())
    : []
  return Boolean(primaryType) || types.length > 0
}

const normalizePointList = (points) => {
  if (!Array.isArray(points)) return []
  return points
    .map((p) => {
      const lat = toFiniteNumber(p?.lat)
      const lon = toFiniteNumber(p?.lon)
      if (lat == null || lon == null) return null
      return {
        id: String(p?.id || getNowId()),
        lat,
        lon
      }
    })
    .filter(Boolean)
}

const filteredRecordsByType = (records, diseaseType, startDate, endDate) => {
  if (!Array.isArray(records)) return []

  return records.filter((record) => {
    if (!isRecordWithinTimeRange(record, startDate, endDate)) {
      return false
    }

    const primaryType = isValidDiseaseTypeValue(record?.type) ? String(record.type).trim() : ''
    const types = Array.isArray(record?.types)
      ? record.types.filter((item) => isValidDiseaseTypeValue(item)).map((item) => String(item).trim())
      : []

    if (!primaryType && types.length === 0) {
      return false
    }

    if (!diseaseType || diseaseType === 'all') {
      return true
    }

    if (types.length > 0) {
      return types.includes(diseaseType)
    }
    return primaryType === diseaseType
  })
}

const filteredRecordsForAssessment = (records, startDate, endDate) => {
  if (!Array.isArray(records)) return []
  return records.filter((record) => {
    if (!isRecordWithinTimeRange(record, startDate, endDate)) {
      return false
    }
    return hasSupportedDisease(record)
  })
}

const updateHeatLayer = () => {
  if (!map) return

  if (heatLayer) {
    map.removeLayer(heatLayer)
    heatLayer = null
  }

  if (heatBgLayer) {
    map.removeLayer(heatBgLayer)
    heatBgLayer = null
  }

  if (!props.showHeatmap) {
    return
  }

  if (typeof L.heatLayer !== 'function') {
    console.warn('leaflet.heat 未正确加载，病害分析热力图不可用')
    return
  }

  let maxIntensity = 0
  const heatData = filteredRecords.value
    .map((record) => {
      const lat = toFiniteNumber(record?.lat)
      const lon = toFiniteNumber(record?.lon)
      if (lat == null || lon == null) return null
      const weight = Math.max(1, Number(record?.area || 1))
      if (weight > maxIntensity) {
        maxIntensity = weight
      }
      return [lat, lon, weight]
    })
    .filter(Boolean)

  if (heatData.length === 0) {
    return
  }

  const finalMax = maxIntensity > 0 ? maxIntensity : 1.0

  if (!map.getPane('heatBackgroundPane')) {
    map.createPane('heatBackgroundPane')
    map.getPane('heatBackgroundPane').style.zIndex = 350
    map.getPane('heatBackgroundPane').style.pointerEvents = 'none'
  }

  const bounds = [[-90, -180], [90, 180]]
  heatBgLayer = L.rectangle(bounds, {
    pane: 'heatBackgroundPane',
    color: 'blue',
    weight: 0,
    fillColor: 'blue',
    fillOpacity: 0.3,
    interactive: false
  })
  heatBgLayer.addTo(map)

  heatLayer = L.heatLayer(heatData, {
    radius: 50,
    blur: 35,
    maxZoom: 18,
    max: finalMax * 0.8,
    minOpacity: 0.0,
    gradient: {
      0.0: 'rgba(0,0,255,0)',
      0.2: 'rgba(0,0,255,0.8)',
      0.4: 'cyan',
      0.6: 'lime',
      0.8: 'yellow',
      1.0: 'red'
    }
  })
  heatLayer.addTo(map)
}

const buildPersistPayload = () => {
  return instances.value.map((inst) => ({
    id: inst.id,
    points: inst.points,
    parameters: inst.parameters,
    status: inst.status,
    color: inst.color,
    metrics: inst.metrics || null
  }))
}

const flushPersistInstances = async () => {
  persistTimer = null

  if (persistInFlight) {
    persistPending = true
    return
  }

  persistInFlight = true
  try {
    await saveAnalysisInstances(buildPersistPayload())
  } catch (error) {
    console.error('保存路段实例失败:', error)
    const now = Date.now()
    if (now - lastPersistErrorAt > 5000) {
      ElMessage.warning('后端不可用，路段实例暂未保存')
      lastPersistErrorAt = now
    }
  } finally {
    persistInFlight = false
    if (persistPending) {
      persistPending = false
      persistInstances()
    }
  }
}

const persistInstances = () => {
  if (persistTimer) {
    clearTimeout(persistTimer)
  }
  persistTimer = setTimeout(() => {
    flushPersistInstances()
  }, 150)
}

const normalizeLoadedInstances = (rawList) => {
  const defaults = getDefaultParams()
  return rawList
    .map((inst) => {
      const id = String(inst?.id || getNowId())
      const points = normalizePointList(inst?.points || [])
      return {
        id,
        points,
        parameters: {
          ...defaults,
          ...(inst?.parameters || {})
        },
        matchedRecordIds: [],
        polygonAreaM2: 0,
        polygonGeoJSON: null,
        status: String(inst?.status || 'no_data'),
        color: String(inst?.color || getStatusColor('no_data')),
        metrics: inst?.metrics || null
      }
    })
    .filter((inst) => inst.points.length > 0)
}

const loadInstances = async () => {
  try {
    const resp = await fetchAnalysisInstances()
    const list = Array.isArray(resp?.data?.instances) ? resp.data.instances : []
    instances.value = normalizeLoadedInstances(list)
  } catch (error) {
    console.error('加载路段实例失败:', error)
    instances.value = []
  }
}

const clearFloatingWindow = () => {
  floatingWindowVisible.value = false
  selectedDisease.value = null
}

const closeFloatingWindow = () => {
  clearFloatingWindow()
}

const updateCoordinates = () => {
  if (!map) return
  const center = map.getCenter()
  currentLat.value = center.lat
  currentLng.value = center.lng
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

const fetchMapTypesData = async () => {
  try {
    const response = await fetchMapTypes()
    mapTypes.value = Array.isArray(response?.data) ? response.data : []
    if (mapTypes.value.length === 0) {
      mapTypes.value = [...DEFAULT_MAP_TYPES]
    }
    if (map) {
      switchMapLayer(props.mapType)
    }
  } catch (error) {
    console.error('获取地图类型失败:', error)
    mapTypes.value = [...DEFAULT_MAP_TYPES]
    if (map) {
      switchMapLayer(props.mapType)
    }
  }
}

const switchMapLayer = (type) => {
  if (!map) return

  if (currentLayer) {
    try {
      map.removeLayer(currentLayer)
    } catch (error) {
      console.warn('移除旧地图图层失败:', error)
    }
  }

  const config = mapTypes.value.find((item) => item.value === type) || mapTypes.value[0]
  if (!config || !config.url) {
    return
  }

  try {
    const subdomain = config.subdomains && config.subdomains.length > 0 ? config.subdomains[0] : ''
    const url = config.url.replace('{s}', subdomain)
    currentLayer = L.tileLayer(url, {
      subdomains: config.subdomains || [],
      attribution: config.attribution || '&copy; <a href="https://www.amap.com/">高德地图</a>'
    })
    currentLayer.addTo(map)
  } catch (error) {
    console.error('切换地图图层失败:', error)
  }
}

const initCenterFromBrowserLocation = async () => {
  const remembered = getInitialView()
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
    currentLat.value = FALLBACK_CENTER.lat
    currentLng.value = FALLBACK_CENTER.lon
  }

  if (!navigator.geolocation) {
    return
  }

  await new Promise((resolve) => {
    navigator.geolocation.getCurrentPosition(
      (position) => {
        const lat = toFiniteNumber(position?.coords?.latitude)
        const lon = toFiniteNumber(position?.coords?.longitude)
        if (lat != null && lon != null && isValidLatLon(lat, lon) && !isZeroLikeLocation(lat, lon)) {
          currentLat.value = lat
          currentLng.value = lon
        }
        resolve()
      },
      () => resolve(),
      {
        enableHighAccuracy: false,
        timeout: 3000,
        maximumAge: 300000
      }
    )
  })
}

const fetchDiseaseRecords = async () => {
  try {
    const response = await fetchRecords()
    diseaseRecords.value = Array.isArray(response?.data) ? response.data : []
    refreshDiseaseMarkers()
    recomputeAllInstanceMatches()
    scheduleAssess()
  } catch (error) {
    console.error('加载病害记录失败:', error)
  }
}

const refreshDiseaseMarkers = () => {
  if (!map) return

  recordLayer.clearLayers()
  filteredRecords.value = filteredRecordsByType(
    diseaseRecords.value,
    props.diseaseType,
    props.startDate,
    props.endDate
  )
  assessableRecords.value = filteredRecordsForAssessment(
    diseaseRecords.value,
    props.startDate,
    props.endDate
  )

  filteredRecords.value.forEach((record) => {
    const lat = toFiniteNumber(record?.lat)
    const lon = toFiniteNumber(record?.lon)
    if (lat == null || lon == null) return

    const marker = L.circleMarker([lat, lon], {
      radius: 5,
      color: '#ffffff',
      weight: 1,
      fillColor: getRecordMarkerColor(record),
      fillOpacity: 0.95
    })

    marker.on('click', () => {
      selectedDisease.value = record
      floatingWindowVisible.value = true
    })

    recordLayer.addLayer(marker)
  })

  updateHeatLayer()
}

const initMap = () => {
  const mapElement = document.getElementById('analysis-map')
  if (!mapElement) {
    setTimeout(initMap, 80)
    return
  }

  if (map) return

  map = L.map('analysis-map', {
    center: [currentLat.value, currentLng.value],
    zoom: getInitialView()?.zoom || 13,
    zoomControl: false
  })

  switchMapLayer(props.mapType)

  L.control.zoom({ position: 'topright' }).addTo(map)
  map.on('move', updateCoordinates)
  map.on('moveend', emitViewState)
  map.on('zoomend', emitViewState)
  map.on('contextmenu', handleMapRightClick)
  map.on('click', () => {
    if (mapClickLock) {
      mapClickLock = false
      return
    }
    selectedEndpoint.value = null
    emitSelectionChange()
    refreshInstanceStyles()
  })

  recordLayer.addTo(map)

  setTimeout(() => {
    if (map) map.invalidateSize()
  }, 100)
}

const ensureInstanceLayer = (instance) => {
  if (!map) return null

  let layerRef = instanceLayers.get(instance.id)
  if (layerRef) return layerRef

  const polyline = L.polyline([], {
    color: '#34495e',
    weight: 3,
    opacity: 0.95
  }).addTo(map)

  const polygon = L.polygon([], {
    color: '#666666',
    weight: 1,
    fillColor: instance.color || getStatusColor(instance.status),
    fillOpacity: 0.45
  }).addTo(map)

  polyline.on('click', (event) => {
    mapClickLock = true
    onInstanceClicked(instance.id, event)
  })

  polygon.on('click', (event) => {
    mapClickLock = true
    onInstanceClicked(instance.id, event)
  })

  layerRef = {
    polyline,
    polygon,
    endpointMarkers: []
  }

  instanceLayers.set(instance.id, layerRef)
  return layerRef
}

const removeInstanceLayer = (instanceId) => {
  const layerRef = instanceLayers.get(instanceId)
  if (!layerRef || !map) return

  layerRef.endpointMarkers.forEach((marker) => {
    map.removeLayer(marker)
  })
  layerRef.endpointMarkers = []

  map.removeLayer(layerRef.polyline)
  map.removeLayer(layerRef.polygon)
  instanceLayers.delete(instanceId)
}

const buildBufferedPolygon = (instance) => {
  if (!instance || !Array.isArray(instance.points) || instance.points.length < 2) {
    return null
  }

  const widthM = Math.max(0.1, Number(instance.parameters?.section_width_m || 7.5))
  const lineCoords = instance.points.map((p) => [p.lon, p.lat])

  try {
    const line = turf.lineString(lineCoords)
    const buffered = turf.buffer(line, widthM / 2, {
      units: 'meters',
      steps: 16
    })

    if (!buffered?.geometry?.coordinates?.length) {
      return null
    }

    const ring = buffered.geometry.coordinates[0]
    const latLngs = ring.map((coord) => [coord[1], coord[0]])
    const area = turf.area(buffered)

    return {
      feature: buffered,
      latLngs,
      areaM2: area
    }
  } catch (error) {
    console.error('生成路段面失败:', error)
    return null
  }
}

const recomputeInstanceMatches = (instance) => {
  if (!instance) return

  const polygonData = buildBufferedPolygon(instance)
  if (!polygonData) {
    instance.matchedRecordIds = []
    instance.polygonAreaM2 = 0
    instance.polygonGeoJSON = null
    return
  }

  instance.polygonAreaM2 = polygonData.areaM2
  instance.polygonGeoJSON = polygonData.feature

  const matchedIds = []
  assessableRecords.value.forEach((record) => {
    const lat = toFiniteNumber(record?.lat)
    const lon = toFiniteNumber(record?.lon)
    if (lat == null || lon == null) return

    try {
      const point = turf.point([lon, lat])
      if (turf.booleanPointInPolygon(point, polygonData.feature)) {
        matchedIds.push(String(record.id))
      }
    } catch (error) {
      // Ignore malformed point-level geometry errors and continue.
    }
  })

  instance.matchedRecordIds = matchedIds
}

const recomputeAllInstanceMatches = () => {
  instances.value.forEach((instance) => {
    recomputeInstanceMatches(instance)
    renderOneInstance(instance)
  })
}

const renderEndpointMarkers = (instance, layerRef) => {
  if (!map) return

  layerRef.endpointMarkers.forEach((marker) => {
    map.removeLayer(marker)
  })
  layerRef.endpointMarkers = []

  instance.points.forEach((point, index) => {
    const isSelectedPoint = selectedEndpoint.value
      && selectedEndpoint.value.instanceId === instance.id
      && selectedEndpoint.value.pointIndex === index

    const marker = L.marker([point.lat, point.lon], {
      icon: createEndpointIcon(Boolean(isSelectedPoint)),
      draggable: true,
      keyboard: false
    })

    marker.on('click', (event) => {
      mapClickLock = true
      L.DomEvent.stopPropagation(event)
      selectSingleInstance(instance.id)
      selectedEndpoint.value = {
        instanceId: instance.id,
        pointIndex: index
      }
      refreshInstanceStyles()
      emitSelectionChange()
    })

    marker.on('drag', (event) => {
      const latlng = event.target.getLatLng()
      const target = getInstance(instance.id)
      if (!target || !target.points[index]) return

      target.points[index].lat = latlng.lat
      target.points[index].lon = latlng.lng
      renderOneInstance(target, { skipMarkerRefresh: true, skipMatch: true })
    })

    marker.on('dragend', (event) => {
      const latlng = event.target.getLatLng()
      const target = getInstance(instance.id)
      if (!target || !target.points[index]) return

      target.points[index].lat = latlng.lat
      target.points[index].lon = latlng.lng
      recomputeInstanceMatches(target)
      renderOneInstance(target)
      persistInstances()
      scheduleAssess()
    })

    marker.addTo(map)
    layerRef.endpointMarkers.push(marker)
  })
}

const renderOneInstance = (instance, options = {}) => {
  const layerRef = ensureInstanceLayer(instance)
  if (!layerRef) return

  const lineLatLngs = instance.points.map((p) => [p.lat, p.lon])
  layerRef.polyline.setLatLngs(lineLatLngs)

  let polygonData = null
  if (!options.skipMatch) {
    polygonData = buildBufferedPolygon(instance)
    if (polygonData) {
      instance.polygonAreaM2 = polygonData.areaM2
      instance.polygonGeoJSON = polygonData.feature
      layerRef.polygon.setLatLngs(polygonData.latLngs)
    } else {
      instance.polygonAreaM2 = 0
      instance.polygonGeoJSON = null
      layerRef.polygon.setLatLngs([])
    }
  } else if (instance.polygonGeoJSON?.geometry?.coordinates?.length) {
    const ring = instance.polygonGeoJSON.geometry.coordinates[0]
    layerRef.polygon.setLatLngs(ring.map((coord) => [coord[1], coord[0]]))
  }

  if (!options.skipMarkerRefresh) {
    renderEndpointMarkers(instance, layerRef)
  }

  const fillColor = instance.color || getStatusColor(instance.status)
  layerRef.polygon.setStyle({
    fillColor,
    color: '#666666',
    weight: 1,
    fillOpacity: 0.45
  })
}

const renderAllInstances = () => {
  const activeIdSet = new Set(instances.value.map((inst) => inst.id))

  Array.from(instanceLayers.keys()).forEach((id) => {
    if (!activeIdSet.has(id)) {
      removeInstanceLayer(id)
    }
  })

  instances.value.forEach((instance) => {
    renderOneInstance(instance)
  })

  refreshInstanceStyles()
}

const refreshInstanceStyles = () => {
  const selectedSet = new Set(selectedInstanceIds.value)

  instances.value.forEach((instance) => {
    const layerRef = instanceLayers.get(instance.id)
    if (!layerRef) return

    const isSelected = selectedSet.has(instance.id)
    const isPreview = previewInstanceId.value && previewInstanceId.value === instance.id
    const fillColor = instance.color || getStatusColor(instance.status)

    layerRef.polyline.setStyle({
      color: isSelected ? '#1f6feb' : (isPreview ? '#f59e0b' : '#34495e'),
      weight: isSelected ? 4 : (isPreview ? 4 : 3),
      opacity: 0.96
    })

    layerRef.polygon.setStyle({
      color: isSelected ? '#1f6feb' : (isPreview ? '#f59e0b' : '#666666'),
      weight: isSelected ? 2 : (isPreview ? 2 : 1),
      fillColor,
      fillOpacity: isPreview ? 0.58 : 0.45
    })

    layerRef.endpointMarkers.forEach((marker, idx) => {
      const selected = selectedEndpoint.value
        && selectedEndpoint.value.instanceId === instance.id
        && selectedEndpoint.value.pointIndex === idx
      marker.setIcon(createEndpointIcon(Boolean(selected)))
    })
  })
}

const getInstance = (instanceId) => {
  return instances.value.find((item) => item.id === instanceId)
}

const selectSingleInstance = (instanceId) => {
  selectedInstanceIds.value = [instanceId]
}

const toggleInstanceSelection = (instanceId) => {
  const set = new Set(selectedInstanceIds.value)
  if (set.has(instanceId)) {
    set.delete(instanceId)
  } else {
    set.add(instanceId)
  }
  selectedInstanceIds.value = Array.from(set)
}

const onInstanceClicked = (instanceId, event) => {
  const ctrlPressed = Boolean(event?.originalEvent?.ctrlKey)
  if (ctrlPressed) {
    toggleInstanceSelection(instanceId)
  } else {
    selectSingleInstance(instanceId)
  }

  selectedEndpoint.value = null
  refreshInstanceStyles()
  emitSelectionChange()
}

const pushPointToInstance = (instanceId, lat, lon, anchorPoint = null) => {
  const instance = getInstance(instanceId)
  if (!instance) return

  const point = {
    id: getNowId(),
    lat,
    lon
  }

  if (!anchorPoint) {
    instance.points.push(point)
    selectedEndpoint.value = {
      instanceId,
      pointIndex: instance.points.length - 1
    }
  } else {
    const index = Number(anchorPoint.pointIndex)
    if (!Number.isInteger(index) || index < 0 || index >= instance.points.length) {
      instance.points.push(point)
      selectedEndpoint.value = {
        instanceId,
        pointIndex: instance.points.length - 1
      }
    } else if (index === 0) {
      instance.points.unshift(point)
      selectedEndpoint.value = {
        instanceId,
        pointIndex: 0
      }
    } else {
      instance.points.splice(index + 1, 0, point)
      selectedEndpoint.value = {
        instanceId,
        pointIndex: index + 1
      }
    }
  }

  drawingState.value.active = true
  drawingState.value.instanceId = instanceId

  recomputeInstanceMatches(instance)
  renderOneInstance(instance)
  refreshInstanceStyles()
  persistInstances()
  scheduleAssess()
  emitSelectionChange()
}

const createNewInstanceWithPoint = (lat, lon) => {
  const id = `seg_${getNowId()}`
  const defaults = getDefaultParams()
  const instance = {
    id,
    points: [],
    parameters: { ...defaults },
    matchedRecordIds: [],
    polygonAreaM2: 0,
    polygonGeoJSON: null,
    status: 'no_data',
    color: getStatusColor('no_data'),
    metrics: null
  }

  instances.value.push(instance)
  selectSingleInstance(id)
  selectedEndpoint.value = null

  pushPointToInstance(id, lat, lon)
}

const handleMapRightClick = (event) => {
  if (!event?.latlng) return

  const lat = Number(event.latlng.lat)
  const lon = Number(event.latlng.lng)
  if (!Number.isFinite(lat) || !Number.isFinite(lon)) return

  const endpoint = selectedEndpoint.value
  if (endpoint?.instanceId) {
    pushPointToInstance(endpoint.instanceId, lat, lon, endpoint)
    return
  }

  if (drawingState.value.active && drawingState.value.instanceId) {
    pushPointToInstance(drawingState.value.instanceId, lat, lon)
    return
  }

  createNewInstanceWithPoint(lat, lon)
}

const deleteSelectedEndpoint = () => {
  if (!selectedEndpoint.value) return

  const instance = getInstance(selectedEndpoint.value.instanceId)
  if (!instance) {
    selectedEndpoint.value = null
    return
  }

  const idx = Number(selectedEndpoint.value.pointIndex)
  if (!Number.isInteger(idx) || idx < 0 || idx >= instance.points.length) {
    selectedEndpoint.value = null
    return
  }

  instance.points.splice(idx, 1)
  selectedEndpoint.value = null

  if (instance.points.length === 0) {
    instances.value = instances.value.filter((item) => item.id !== instance.id)
    selectedInstanceIds.value = selectedInstanceIds.value.filter((id) => id !== instance.id)
    removeInstanceLayer(instance.id)
  } else {
    recomputeInstanceMatches(instance)
    renderOneInstance(instance)
  }

  persistInstances()
  scheduleAssess()
  emitSelectionChange()
  refreshInstanceStyles()
}

const deleteInstanceIds = async (instanceIds = []) => {
  const ids = Array.isArray(instanceIds) ? instanceIds.filter(Boolean) : []
  if (!ids.length) return

  const removeSet = new Set(ids)
  instances.value = instances.value.filter((item) => !removeSet.has(item.id))
  Array.from(removeSet).forEach((id) => removeInstanceLayer(id))

  selectedInstanceIds.value = selectedInstanceIds.value.filter((id) => !removeSet.has(id))
  if (selectedEndpoint.value && removeSet.has(selectedEndpoint.value.instanceId)) {
    selectedEndpoint.value = null
  }

  if (drawingState.value.instanceId && removeSet.has(drawingState.value.instanceId)) {
    drawingState.value = { active: false, instanceId: null }
  }

  if (previewInstanceId.value && removeSet.has(previewInstanceId.value)) {
    previewInstanceId.value = ''
  }

  persistInstances()
  try {
    await deleteAnalysisInstances(ids)
  } catch (error) {
    console.error('后端删除路段实例失败:', error)
  }

  if (instances.value.length > 0) {
    scheduleAssess()
  }
  emitSelectionChange()
  refreshInstanceStyles()
}

const deleteSelectedInstances = async () => {
  if (!selectedInstanceIds.value.length) return
  const ids = [...selectedInstanceIds.value]
  selectedInstanceIds.value = []
  await deleteInstanceIds(ids)
}

const clearSelection = () => {
  selectedInstanceIds.value = []
  selectedEndpoint.value = null
  emitSelectionChange()
  refreshInstanceStyles()
}

const focusInstanceById = (instanceId) => {
  if (!map) return
  const target = getInstance(instanceId)
  if (!target) return

  const layerRef = instanceLayers.get(instanceId)
  if (!layerRef) return

  let bounds = null
  try {
    const polygonBounds = layerRef.polygon.getBounds()
    if (polygonBounds.isValid()) {
      bounds = polygonBounds
    }
  } catch (error) {
    bounds = null
  }

  if (!bounds) {
    try {
      const lineBounds = layerRef.polyline.getBounds()
      if (lineBounds.isValid()) {
        bounds = lineBounds
      }
    } catch (error) {
      bounds = null
    }
  }

  if (bounds) {
    map.fitBounds(bounds, {
      padding: [36, 36],
      maxZoom: 17,
      animate: true
    })
  } else if (target.points.length > 0) {
    map.setView([target.points[0].lat, target.points[0].lon], Math.max(map.getZoom(), 15), {
      animate: true
    })
  }
}

const setPreviewInstance = (instanceId) => {
  previewInstanceId.value = String(instanceId || '')
  refreshInstanceStyles()
  if (previewInstanceId.value) {
    focusInstanceById(previewInstanceId.value)
  }
}

const handleKeyboard = (event) => {
  if (event.key === 'Escape') {
    drawingState.value.active = false
    drawingState.value.instanceId = null
    clearSelection()
    return
  }

  if (event.key === 'Delete') {
    if (selectedEndpoint.value) {
      deleteSelectedEndpoint()
      return
    }
    if (selectedInstanceIds.value.length > 0) {
      deleteSelectedInstances()
    }
  }
}

const applyParamToSelectedInstances = (key, value) => {
  if (!key || selectedInstanceIds.value.length === 0) return

  const selectedSet = new Set(selectedInstanceIds.value)
  let touched = 0

  instances.value.forEach((instance) => {
    if (!selectedSet.has(instance.id)) return
    instance.parameters = {
      ...instance.parameters,
      [key]: value
    }
    touched += 1
    recomputeInstanceMatches(instance)
    renderOneInstance(instance)
  })

  if (touched > 0) {
    persistInstances()
    scheduleAssess()
    emitSelectionChange()
    refreshInstanceStyles()
  }
}

const buildInstanceSummary = (instance) => {
  const points = Array.isArray(instance?.points) ? instance.points : []
  let centerLat = null
  let centerLon = null

  if (points.length > 0) {
    const total = points.reduce((acc, point) => {
      acc.lat += Number(point.lat) || 0
      acc.lon += Number(point.lon) || 0
      return acc
    }, { lat: 0, lon: 0 })
    centerLat = total.lat / points.length
    centerLon = total.lon / points.length
  }

  return {
    id: instance.id,
    status: instance.status || 'no_data',
    pointCount: points.length,
    matchedRecordCount: Array.isArray(instance.matchedRecordIds) ? instance.matchedRecordIds.length : 0,
    centerLat,
    centerLon,
  }
}

const emitSelectionChange = () => {
  const selectedList = instances.value.filter((inst) => selectedInstanceIds.value.includes(inst.id))
  const schema = Array.isArray(props.analysisConfig?.param_schema) ? props.analysisConfig.param_schema : []
  const resultSchema = Array.isArray(props.analysisConfig?.result_schema) ? props.analysisConfig.result_schema : []
  const values = {}
  const resultValues = {}

  schema.forEach((item) => {
    const key = item?.key
    if (!key) return
    if (selectedList.length === 0) {
      values[key] = null
      return
    }

    const first = selectedList[0]?.parameters?.[key]
    const allEqual = selectedList.every((inst) => inst?.parameters?.[key] === first)
    values[key] = allEqual ? first : null
  })

  resultSchema.forEach((item) => {
    const key = item?.key
    if (!key) return
    if (selectedList.length === 0) {
      resultValues[key] = null
      return
    }

    const first = selectedList[0]?.metrics?.[key]
    const allEqual = selectedList.every((inst) => inst?.metrics?.[key] === first)
    resultValues[key] = allEqual ? first : MIXED_VALUE_TOKEN
  })

  emit('analysisSelectionChange', {
    selectedCount: selectedList.length,
    selectedIds: selectedList.map((item) => item.id),
    instanceList: instances.value.map((instance) => buildInstanceSummary(instance)),
    values,
    resultValues
  })
}

const scheduleAssess = () => {
  if (assessTimer) {
    clearTimeout(assessTimer)
  }
  assessTimer = setTimeout(() => {
    runAssessment()
  }, 160)
}

const runAssessment = async () => {
  assessTimer = null

  if (instances.value.length === 0) {
    return
  }

  const payload = instances.value.map((instance) => ({
    instance_id: instance.id,
    points: instance.points.map((p) => [p.lat, p.lon]),
    record_ids: Array.isArray(instance.matchedRecordIds) ? instance.matchedRecordIds : [],
    parameters: instance.parameters || {}
  }))

  try {
    const response = await assessAnalysisSegments(payload)
    const results = Array.isArray(response?.data?.results) ? response.data.results : []
    const resultMap = new Map(results.map((item) => [String(item.instance_id), item]))

    instances.value.forEach((instance) => {
      const result = resultMap.get(instance.id)
      if (!result) return
      instance.status = String(result.status || 'warning')
      instance.color = String(result.color || getStatusColor(instance.status))
      instance.metrics = result
    })

    renderAllInstances()
    persistInstances()
    emitSelectionChange()
  } catch (error) {
    console.error('路段评估失败:', error)
    ElMessage.warning('路段评估失败，稍后重试')
  }
}

const handleAnalysisCommand = () => {
  const command = props.analysisCommand || {}
  if (!command.type || command.type === 'noop') return

  if (command.type === 'apply-params') {
    const params = command.params && typeof command.params === 'object' ? command.params : {}
    Object.keys(params).forEach((key) => {
      applyParamToSelectedInstances(key, params[key])
    })
    return
  }

  if (command.type === 'delete-selected') {
    deleteSelectedInstances()
    return
  }

  if (command.type === 'delete-instance-ids') {
    const ids = Array.isArray(command.instanceIds) ? command.instanceIds : []
    deleteInstanceIds(ids)
    return
  }

  if (command.type === 'preview-instance') {
    setPreviewInstance(command.instanceId)
    return
  }

  if (command.type === 'clear-preview') {
    setPreviewInstance('')
  }
}

const zoomIn = () => {
  if (map) map.zoomIn()
}

const zoomOut = () => {
  if (map) map.zoomOut()
}

const resetView = () => {
  if (map) {
    const remembered = getInitialView()
    if (remembered) {
      map.setView([remembered.lat, remembered.lon], remembered.zoom)
    } else {
      map.setView([currentLat.value, currentLng.value], 13)
    }
  }
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

watch(
  () => props.mapType,
  (newType) => {
    if (map) {
      switchMapLayer(newType)
    }
  }
)

watch(
  () => props.settingsVersion,
  async () => {
    await fetchMapTypesData()
  }
)

watch(
  () => props.diseaseType,
  () => {
    refreshDiseaseMarkers()
  }
)

watch(
  () => [props.startDate, props.endDate],
  () => {
    refreshDiseaseMarkers()
    recomputeAllInstanceMatches()
    scheduleAssess()
  }
)

watch(
  () => props.showHeatmap,
  () => {
    updateHeatLayer()
  }
)

watch(
  () => props.analysisConfig?.instance_defaults,
  () => {
    const defaults = getDefaultParams()
    instances.value.forEach((instance) => {
      instance.parameters = {
        ...defaults,
        ...(instance.parameters || {})
      }
      recomputeInstanceMatches(instance)
      renderOneInstance(instance)
    })
    emitSelectionChange()
    scheduleAssess()
  },
  { deep: true }
)

watch(
  () => props.analysisCommand?.seq,
  () => {
    handleAnalysisCommand()
  }
)

onMounted(async () => {
  await fetchMapTypesData()
  await initCenterFromBrowserLocation()
  initMap()

  setTimeout(() => {
    emitViewState()
  }, 120)

  await loadInstances()
  renderAllInstances()

  await fetchDiseaseRecords()

  keyboardHandler = (event) => handleKeyboard(event)
  window.addEventListener('keydown', keyboardHandler)

  emitSelectionChange()
})

onUnmounted(() => {
  emitViewState()

  if (keyboardHandler) {
    window.removeEventListener('keydown', keyboardHandler)
    keyboardHandler = null
  }

  if (assessTimer) {
    clearTimeout(assessTimer)
    assessTimer = null
  }

  if (persistTimer) {
    clearTimeout(persistTimer)
    persistTimer = null
  }

  Array.from(instanceLayers.keys()).forEach((id) => {
    removeInstanceLayer(id)
  })

  if (map) {
    if (heatLayer) {
      map.removeLayer(heatLayer)
      heatLayer = null
    }
    if (heatBgLayer) {
      map.removeLayer(heatBgLayer)
      heatBgLayer = null
    }
    map.remove()
    map = null
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
  flex-wrap: wrap;
}

.toolbar-hint {
  font-size: 12px;
  color: #666;
}

.coordinate-display {
  font-size: 12px;
  color: #666;
}

.map {
  height: 100%;
  width: 100%;
}

:deep(.analysis-endpoint-icon) {
  background: transparent;
  border: none;
}
</style>
