import { UNKNOWN_TYPE_SET } from './constants'

// 将值转换为有限数，失败返回回退值
export const toFiniteNumber = (v) => {
  const n = Number(v)
  return Number.isFinite(n) ? n : null
}

// 检查经纬度是否在有效范围内
export const isValidLatLon = (lat, lon) => {
  return Number.isFinite(lat) && Number.isFinite(lon)
    && lat >= -90 && lat <= 90
    && lon >= -180 && lon <= 180
}

// 检查坐标是否接近原点 (0, 0)
export const isZeroLikeLocation = (lat, lon) => {
  return Math.abs(lat) < 1e-6 && Math.abs(lon) < 1e-6
}

// 检查病害类型值是否有效（非未知/空值）
export const isValidDiseaseTypeValue = (value) => {
  if (typeof value !== 'string') return false
  const cleaned = value.trim()
  if (!cleaned) return false
  return !UNKNOWN_TYPE_SET.has(cleaned.toLowerCase())
}

// 解析记录的创建时间戳（ms），返回 null 表示无法解析
export const parseRecordTimeMs = (record) => {
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

    // 紧凑格式: "YYYYMMDDThhmmss"
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

// 解析日期字符串 "YYYY-MM-DD" 为当天起始毫秒时间戳
export const parseDayStartMs = (dateText) => {
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

// 解析日期字符串 "YYYY-MM-DD" 为当天结束毫秒时间戳
export const parseDayEndMs = (dateText) => {
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

// 判断记录是否在给定的日期范围内
export const isRecordWithinTimeRange = (record, startDate, endDate) => {
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

export const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms))

export const requestWithRetry = async (requestFn, { retries = 2, delayMs = 1200, label = '请求' } = {}) => {
  let lastError = null
  for (let attempt = 0; attempt <= retries; attempt++) {
    try {
      return await requestFn()
    } catch (error) {
      lastError = error
      if (attempt >= retries) {
        break
      }
      console.warn(`${label} 失败，${delayMs}ms 后重试（${attempt + 1}/${retries}）`, error)
      await sleep(delayMs)
    }
  }
  throw lastError
}

// 统一的日期字符串规范化 ("YYYY-MM-DD")
export const normalizeDayText = (value) => {
  if (typeof value !== 'string') {
    return ''
  }
  const text = value.trim()
  if (!text) {
    return ''
  }
  return /^\d{4}-\d{2}-\d{2}$/.test(text) ? text : ''
}
