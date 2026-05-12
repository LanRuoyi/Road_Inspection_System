import { ref } from 'vue'
import L from 'leaflet'
import { fetchMapTypes, fetchSystemSettings } from '../api'
import { FALLBACK_CENTER, DEFAULT_MAP_TYPES } from '../utils/constants'
import { toFiniteNumber, isValidLatLon, isZeroLikeLocation } from '../utils/helpers'

/**
 * 共享的地图核心逻辑 composable。
 * 管理 currentLat/currentLng/mapTypes 等响应式状态，
 * 提供图层切换、坐标解析、视口管理等工具方法。
 */
export function useMapCore() {
  const currentLat = ref(0)
  const currentLng = ref(0)
  const mapTypes = ref([])

  const getInitialView = (initialView) => {
    const lat = toFiniteNumber(initialView?.lat)
    const lon = toFiniteNumber(initialView?.lon)
    const zoom = toFiniteNumber(initialView?.zoom)
    if (lat === null || lon === null || zoom === null) return null
    return { lat, lon, zoom }
  }

  const emitViewState = (map, emit) => {
    if (!map) return
    const center = map.getCenter()
    emit('viewStateChange', {
      lat: center.lat,
      lon: center.lng,
      zoom: map.getZoom(),
    })
  }

  // 切换瓦片图层，返回新的 tileLayer 实例（旧层由调用方负责清理）
  const switchMapLayer = (map, currentLayer, type) => {
    if (!map) return currentLayer
    if (currentLayer) {
      try { map.removeLayer(currentLayer) } catch (e) { /* ignore */ }
    }
    const config = mapTypes.value.find((item) => item.value === type) || mapTypes.value[0]
    if (!config?.url) return null

    try {
      const subdomain = config.subdomains?.[0] || ''
      const layer = L.tileLayer(config.url.replace('{s}', subdomain), {
        subdomains: config.subdomains || [],
        attribution: config.attribution || '&copy; <a href="https://www.amap.com/">高德地图</a>'
      })
      layer.addTo(map)
      return layer
    } catch (e) {
      console.error('切换图层失败:', e)
      return null
    }
  }

  const fetchMapTypesData = async (map, activeMapType, switchFn) => {
    try {
      const resp = await fetchMapTypes()
      mapTypes.value = Array.isArray(resp?.data) ? resp.data : []
      if (mapTypes.value.length === 0) mapTypes.value = [...DEFAULT_MAP_TYPES]
      if (map) switchFn?.(activeMapType)
    } catch (e) {
      console.error('获取地图类型失败:', e)
      mapTypes.value = [...DEFAULT_MAP_TYPES]
      if (map) switchFn?.(activeMapType)
    }
  }

  const initCenterFromBrowserLocation = async (initialView) => {
    const remembered = getInitialView(initialView)
    if (remembered && isValidLatLon(remembered.lat, remembered.lon) && !isZeroLikeLocation(remembered.lat, remembered.lon)) {
      currentLat.value = remembered.lat
      currentLng.value = remembered.lon
      return
    }

    try {
      const resp = await fetchSystemSettings()
      const loc = resp?.data?.default_location
      if (Array.isArray(loc) && loc.length >= 2) {
        const lat = Number(loc[0])
        const lon = Number(loc[1])
        if (isValidLatLon(lat, lon) && !isZeroLikeLocation(lat, lon)) {
          currentLat.value = lat
          currentLng.value = lon
        }
      }
    } catch (e) {
      currentLat.value = FALLBACK_CENTER.lat
      currentLng.value = FALLBACK_CENTER.lon
    }

    if (!navigator.geolocation) return

    await new Promise((resolve) => {
      navigator.geolocation.getCurrentPosition(
        (pos) => {
          const lat = pos.coords.latitude
          const lon = pos.coords.longitude
          if (isValidLatLon(lat, lon) && !isZeroLikeLocation(lat, lon)) {
            currentLat.value = lat
            currentLng.value = lon
          }
          resolve()
        },
        () => resolve(),
        { timeout: 5000, enableHighAccuracy: false }
      )
    })
  }

  return {
    currentLat,
    currentLng,
    mapTypes,
    getInitialView,
    emitViewState,
  }
}
