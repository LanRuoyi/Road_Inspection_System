<template>
  <div class="transfer-page">
    <el-row :gutter="16" class="transfer-row">
      <el-col :span="12" class="transfer-col">
        <el-card class="pane-card">
          <template #header>
            <div class="card-header">
              <span>本地已接收数据</span>
              <el-button size="small" @click="refreshLocal">刷新</el-button>
            </div>
          </template>

          <el-table :data="localRecords" height="100%" size="small" class="pane-table" border>
            <el-table-column prop="item_id" label="ID" min-width="160" :resizable="true" />
            <el-table-column label="类型" min-width="100" :resizable="true">
              <template #default="scope">
                {{ formatTypes(scope.row.metadata) }}
              </template>
            </el-table-column>
            <el-table-column label="经纬度" min-width="160" :resizable="true">
              <template #default="scope">
                <span>{{ formatLatLon(scope.row.metadata) }}</span>
              </template>
            </el-table-column>
            <el-table-column label="图片" width="70" :resizable="true">
              <template #default="scope">
                <el-tag size="small" :type="scope.row.has_image ? 'success' : 'warning'">
                  {{ scope.row.has_image ? '有' : '无' }}
                </el-tag>
              </template>
            </el-table-column>
          </el-table>
        </el-card>
      </el-col>

      <el-col :span="12" class="transfer-col">
        <el-card class="pane-card">
          <template #header>
            <div class="card-header">
              <span>无人机文件清单</span>
              <div class="header-actions">
                <el-select v-model="selectedDevice" placeholder="选择设备" size="small" style="width: 160px;">
                  <el-option v-for="d in devices" :key="d" :label="d" :value="d" />
                </el-select>
                <el-button size="small" :disabled="!selectedDevice" @click="refreshManifest">同步清单</el-button>
              </div>
            </div>
          </template>

          <el-table
            ref="remoteTableRef"
            :data="remoteItems"
            row-key="item_id"
            height="100%"
            size="small"
            class="pane-table"
            border
            @selection-change="onSelectionChange"
          >
            <el-table-column type="selection" :reserve-selection="true" width="40" :resizable="true" />
            <el-table-column prop="item_id" label="ID" min-width="170" :resizable="true" />
            <el-table-column prop="state" label="状态" min-width="90" :resizable="true" />
            <el-table-column prop="created_at" label="创建时间" min-width="160" :resizable="true" />
          </el-table>

          <div class="ops-row">
            <el-button
              type="primary"
              size="small"
              :disabled="!selectedDevice || selectedRemoteIds.length === 0"
              @click="startPull"
            >
              开始回传所选 ({{ selectedRemoteIds.length }})
            </el-button>
            <el-tag size="small" :type="uavLinkConnected ? 'success' : 'warning'">
              {{ uavLinkConnected ? '无人机链路已连接' : '无人机链路未连接' }}
            </el-tag>
          </div>
        </el-card>
      </el-col>
    </el-row>
  </div>
</template>

<script setup>
import { computed, nextTick, onMounted, onUnmounted, ref, watch } from 'vue'
import { ElMessage } from 'element-plus'
import {
  fetchLocalUAVRecords,
  fetchUAVDevices,
  fetchUAVDeviceManifest,
  startUAVPullTransfer,
} from '../api'
import { UNKNOWN_TYPE_SET, POLLING } from '../utils/constants'
import { toFiniteNumber } from '../utils/helpers'

defineProps({})

const localRecords = ref([])
const devices = ref([])
const selectedDevice = ref('')
const remoteItems = ref([])
const selectedRemoteIds = ref([])
const lastManifestUpdatedAt = ref(0)
const nowSec = ref(Date.now() / 1000)
const remoteTableRef = ref(null)

let localPollingTimer = null
let devicePollingTimer = null
let heartbeatTimer = null

const uavLinkConnected = computed(() => {
  if (lastManifestUpdatedAt.value > 0) {
    return (nowSec.value - lastManifestUpdatedAt.value) <= POLLING.UAV_LINK_STALE_SECONDS
  }
  return devices.value.length > 0
})

const formatLatLon = (metadata) => {
  let lat = toFiniteNumber(metadata?.lat)
  let lon = toFiniteNumber(metadata?.lon)

  if (lat === null || lon === null) {
    lat = toFiniteNumber(metadata?.flight_state?.lat)
    lon = toFiniteNumber(metadata?.flight_state?.lon)
  }

  if (lat !== null && lon !== null) {
    return `${lat.toFixed(6)}, ${lon.toFixed(6)}`
  }
  return '-'
}

const formatTypes = (metadata) => {
  const typeOrder = []
  const typeSet = new Set()

  const pushType = (raw) => {
    if (typeof raw !== 'string') {
      return
    }
    const cleaned = raw.trim()
    if (!cleaned) {
      return
    }
    if (UNKNOWN_TYPE_SET.has(cleaned.toLowerCase())) {
      return
    }
    if (!typeSet.has(cleaned)) {
      typeSet.add(cleaned)
      typeOrder.push(cleaned)
    }
  }

  if (Array.isArray(metadata?.types)) {
    metadata.types.forEach(pushType)
  }

  if (typeof metadata?.type === 'string') {
    pushType(metadata.type)
  }

  const targets = metadata?.detection?.targets
  if (Array.isArray(targets)) {
    targets.forEach((target) => {
      if (!target || typeof target !== 'object') {
        return
      }
      pushType(target.type)
      if (Array.isArray(target.rois)) {
        target.rois.forEach((roi) => {
          if (!roi || typeof roi !== 'object') {
            return
          }
          pushType(roi.type)
        })
      }
    })
  }

  if (typeOrder.length > 0) {
    return typeOrder.join(', ')
  }
  return ''
}

const refreshLocal = async () => {
  try {
    const resp = await fetchLocalUAVRecords()
    localRecords.value = resp.data.records || []
  } catch (error) {
    ElMessage.error('加载本地记录失败')
    console.error(error)
  }
}

const refreshDevices = async () => {
  try {
    const resp = await fetchUAVDevices()
    const nextDevices = Array.isArray(resp.data.devices) ? resp.data.devices : []
    devices.value = nextDevices

    if (selectedDevice.value && !nextDevices.includes(selectedDevice.value)) {
      selectedDevice.value = ''
      remoteItems.value = []
      selectedRemoteIds.value = []
      lastManifestUpdatedAt.value = 0
    }

    if (!selectedDevice.value && nextDevices.length > 0) {
      selectedDevice.value = nextDevices[0]
    }
  } catch (error) {
    ElMessage.error('加载设备列表失败')
    console.error(error)
  }
}

const refreshManifest = async () => {
  if (!selectedDevice.value) {
    ElMessage.warning('请先选择设备')
    return
  }
  try {
    const prevSelectedSet = new Set(selectedRemoteIds.value)
    const resp = await fetchUAVDeviceManifest(selectedDevice.value)
    remoteItems.value = Array.isArray(resp?.data?.items) ? resp.data.items : []

    await nextTick()

    const nextSelectedIds = []
    remoteItems.value.forEach((item) => {
      const id = item?.item_id
      if (!id || !prevSelectedSet.has(id)) return
      nextSelectedIds.push(id)
      if (remoteTableRef.value?.toggleRowSelection) {
        remoteTableRef.value.toggleRowSelection(item, true)
      }
    })
    selectedRemoteIds.value = nextSelectedIds

    lastManifestUpdatedAt.value = Number(resp.data.updated_at || 0)
    nowSec.value = Date.now() / 1000
  } catch (error) {
    lastManifestUpdatedAt.value = 0
    nowSec.value = Date.now() / 1000
    ElMessage.error('同步无人机清单失败')
    console.error(error)
  }
}

const onSelectionChange = (rows) => {
  selectedRemoteIds.value = rows.map((x) => x.item_id).filter(Boolean)
}

const startPull = async () => {
  if (!selectedDevice.value || selectedRemoteIds.value.length === 0) {
    return
  }
  try {
    await startUAVPullTransfer(selectedDevice.value, selectedRemoteIds.value)
    ElMessage.success(`已下发回传任务 ${selectedRemoteIds.value.length} 条`)
  } catch (error) {
    ElMessage.error('下发回传任务失败')
    console.error(error)
  }
}

const startAutoPolling = () => {
  heartbeatTimer = setInterval(() => {
    nowSec.value = Date.now() / 1000
  }, 1000)

  localPollingTimer = setInterval(() => {
    refreshLocal()
  }, 8000)

  devicePollingTimer = setInterval(() => {
    refreshDevices()
  }, 5000)
}

const stopAutoPolling = () => {
  if (heartbeatTimer) {
    clearInterval(heartbeatTimer)
    heartbeatTimer = null
  }
  if (localPollingTimer) {
    clearInterval(localPollingTimer)
    localPollingTimer = null
  }
  if (devicePollingTimer) {
    clearInterval(devicePollingTimer)
    devicePollingTimer = null
  }
}

watch(selectedDevice, async (next, prev) => {
  if (!next || next === prev) {
    return
  }
  selectedRemoteIds.value = []
  await refreshManifest()
})

onMounted(async () => {
  await refreshLocal()
  await refreshDevices()
  if (selectedDevice.value) {
    await refreshManifest()
  }
  startAutoPolling()
})

onUnmounted(() => {
  stopAutoPolling()
})
</script>

<style scoped>
.transfer-page {
  padding: 16px 16px 12px;
  height: 100%;
  box-sizing: border-box;
  overflow: hidden;
}

.transfer-row {
  height: 100%;
}

.transfer-col {
  height: 100%;
  min-width: 0;
}

:deep(.transfer-col .el-card) {
  height: 100%;
}

:deep(.pane-card .el-card__body) {
  height: calc(100% - 56px);
  display: flex;
  flex-direction: column;
}

.pane-table {
  flex: 1;
}

.card-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
}

.header-actions {
  display: flex;
  gap: 8px;
  align-items: center;
}

.ops-row {
  margin-top: 12px;
  display: flex;
  justify-content: space-between;
  align-items: center;
}
</style>
