<template>
  <div class="transfer-page">
    <el-row :gutter="16">
      <el-col :span="12">
        <el-card>
          <template #header>
            <div class="card-header">
              <span>本地已接收数据</span>
              <el-button size="small" @click="refreshLocal">刷新</el-button>
            </div>
          </template>

          <el-table :data="localRecords" height="460" size="small">
            <el-table-column prop="item_id" label="ID" min-width="160" />
            <el-table-column label="类型" min-width="100">
              <template #default="scope">
                {{ scope.row.metadata?.type || '-' }}
              </template>
            </el-table-column>
            <el-table-column label="经纬度" min-width="160">
              <template #default="scope">
                <span>{{ formatLatLon(scope.row.metadata) }}</span>
              </template>
            </el-table-column>
            <el-table-column label="图片" width="70">
              <template #default="scope">
                <el-tag size="small" :type="scope.row.has_image ? 'success' : 'warning'">
                  {{ scope.row.has_image ? '有' : '无' }}
                </el-tag>
              </template>
            </el-table-column>
          </el-table>
        </el-card>
      </el-col>

      <el-col :span="12">
        <el-card>
          <template #header>
            <div class="card-header">
              <span>无人机文件清单</span>
              <div class="header-actions">
                <el-select v-model="selectedDevice" placeholder="选择设备" size="small" style="width: 160px;">
                  <el-option v-for="d in devices" :key="d" :label="d" :value="d" />
                </el-select>
                <el-button size="small" :disabled="!selectedDevice || !rosConnected" @click="refreshManifest">同步清单</el-button>
              </div>
            </div>
          </template>

          <el-table
            :data="remoteItems"
            height="410"
            size="small"
            @selection-change="onSelectionChange"
          >
            <el-table-column type="selection" width="40" />
            <el-table-column prop="item_id" label="ID" min-width="170" />
            <el-table-column prop="state" label="状态" min-width="90" />
            <el-table-column prop="created_at" label="创建时间" min-width="160" />
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
            <el-tag size="small" :type="rosConnected ? 'success' : 'warning'">
              {{ rosConnected ? '无人机链路已连接' : '无人机链路未连接' }}
            </el-tag>
          </div>
        </el-card>
      </el-col>
    </el-row>
  </div>
</template>

<script setup>
import { onMounted, ref } from 'vue'
import { ElMessage } from 'element-plus'
import {
  fetchLocalUAVRecords,
  fetchUAVDevices,
  fetchUAVDeviceManifest,
  startUAVPullTransfer,
} from '../api'

const props = defineProps({
  rosConnected: {
    type: Boolean,
    default: false,
  },
})

const localRecords = ref([])
const devices = ref([])
const selectedDevice = ref('')
const remoteItems = ref([])
const selectedRemoteIds = ref([])

const formatLatLon = (metadata) => {
  const lat = metadata?.lat
  const lon = metadata?.lon
  if (typeof lat === 'number' && typeof lon === 'number') {
    return `${lat.toFixed(6)}, ${lon.toFixed(6)}`
  }
  return '-'
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
    devices.value = resp.data.devices || []
    if (!selectedDevice.value && devices.value.length > 0) {
      selectedDevice.value = devices.value[0]
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
    const resp = await fetchUAVDeviceManifest(selectedDevice.value)
    remoteItems.value = resp.data.items || []
    selectedRemoteIds.value = []
  } catch (error) {
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

onMounted(async () => {
  await refreshLocal()
  await refreshDevices()
  if (selectedDevice.value) {
    await refreshManifest()
  }
})
</script>

<style scoped>
.transfer-page {
  padding: 16px;
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
