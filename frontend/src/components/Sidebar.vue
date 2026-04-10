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

        <el-menu-item index="disease-analysis">
          <el-icon><Histogram /></el-icon>
          <span class="menu-text" :class="{ 'collapsed': collapsed }">病害分析</span>
        </el-menu-item>
        
        <el-menu-item index="real-time-monitor">
          <el-icon><VideoCamera /></el-icon>
          <span class="menu-text" :class="{ 'collapsed': collapsed }">实时监看</span>
        </el-menu-item>
        
        <el-menu-item index="parameter-config">
          <el-icon><Setting /></el-icon>
          <span class="menu-text" :class="{ 'collapsed': collapsed }">参数配置</span>
        </el-menu-item>

        <el-menu-item index="data-transfer">
          <el-icon><Upload /></el-icon>
          <span class="menu-text" :class="{ 'collapsed': collapsed }">回传管理</span>
        </el-menu-item>
      </el-menu>
    </div>
    
    <!-- 功能内容区域（根据选择的功能动态变化） -->
    <div class="content-section" v-show="!collapsed">
      <!-- 病害分布功能内容 -->
      <div v-if="activeTab === 'disease-distribution' || activeTab === 'disease-analysis'" class="function-content">
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
        <div class="setting-item">
          <span class="label">热力图：</span>
          <el-switch v-model="heatmapEnabled" size="small" />
        </div>
        <div class="setting-item vertical-item">
          <span class="label">时间范围：</span>
          <div class="date-range-fields">
            <el-date-picker
              v-model="filterStartDate"
              type="date"
              size="small"
              clearable
              placeholder="开始日期"
              format="YYYY-MM-DD"
              value-format="YYYY-MM-DD"
              style="width: 100%"
            />
            <el-date-picker
              v-model="filterEndDate"
              type="date"
              size="small"
              clearable
              placeholder="结束日期"
              format="YYYY-MM-DD"
              value-format="YYYY-MM-DD"
              style="width: 100%"
            />
          </div>
        </div>

        <template v-if="activeTab === 'disease-analysis'">
          <el-divider />
          <div class="analysis-header-row">
            <h4 style="margin: 0;">病害分析设置</h4>
            <el-radio-group v-model="analysisPanelMode" size="small">
              <el-radio-button label="params">参数设置</el-radio-button>
              <el-radio-button label="instances">实例管理</el-radio-button>
            </el-radio-group>
          </div>
          <el-divider />
          <template v-if="analysisPanelMode === 'params'">
            <div class="setting-item vertical-item">
              <span class="label">选中实例：</span>
              <span style="font-size: 12px; color: #888; line-height: 1.5;">
                {{ analysisSelectedCount > 0 ? `已选 ${analysisSelectedCount} 个路段实例` : '未选中实例（点击地图路段后显示参数）' }}
              </span>
            </div>

            <template v-if="analysisSelectedCount > 0">
              <div class="setting-item vertical-item">
                <span class="sub-title">手动设置参数</span>
                <span class="sub-hint">这些参数由你输入，修改后会触发后端重新评估。</span>
              </div>

              <div
                class="setting-item"
                v-for="item in analysisParamSchema"
                :key="item.key"
              >
                <div class="label-with-tip">
                  <span class="label">{{ item.label }}：</span>
                  <el-tooltip
                    v-if="item.description"
                    :content="item.description"
                    placement="top"
                    :show-after="100"
                  >
                    <el-icon class="help-icon"><QuestionFilled /></el-icon>
                  </el-tooltip>
                </div>

                <el-select
                  v-if="item.input === 'select'"
                  :model-value="analysisValues[item.key] ?? null"
                  clearable
                  size="small"
                  placeholder="多实例值不同"
                  style="width: 150px"
                  @change="(value) => handleAnalysisParamChange(item, value)"
                >
                  <el-option
                    v-for="opt in item.options || []"
                    :key="opt.value"
                    :label="opt.label"
                    :value="opt.value"
                  />
                </el-select>

                <el-input-number
                  v-else-if="item.input === 'number'"
                  :model-value="analysisValues[item.key] == null ? undefined : Number(analysisValues[item.key])"
                  size="small"
                  :min="item.min"
                  :max="item.max"
                  :step="item.step || 1"
                  controls-position="right"
                  style="width: 150px"
                  @change="(value) => handleAnalysisParamChange(item, value)"
                />

                <el-input
                  v-else
                  :model-value="analysisValues[item.key] == null ? '' : String(analysisValues[item.key])"
                  size="small"
                  :placeholder="analysisValues[item.key] == null ? '多实例值不同' : ''"
                  style="width: 150px"
                  @change="(value) => handleAnalysisParamChange(item, value)"
                />
              </div>

              <el-divider />

              <div class="setting-item vertical-item">
                <span class="sub-title">后端计算结果</span>
                <span class="sub-hint">这些字段来自后端模型计算，为只读结果。</span>
              </div>

              <div
                class="setting-item"
                v-for="item in analysisResultSchema"
                :key="`result-${item.key}`"
              >
                <div class="label-with-tip">
                  <span class="label">{{ item.label }}：</span>
                  <el-tooltip
                    v-if="item.description"
                    :content="item.description"
                    placement="top"
                    :show-after="100"
                  >
                    <el-icon class="help-icon"><QuestionFilled /></el-icon>
                  </el-tooltip>
                </div>

                <el-tag size="small" type="info">
                  {{ formatResultValue(analysisResultValues[item.key]) }}
                </el-tag>
              </div>

              <div class="setting-item">
                <el-button type="danger" size="small" style="width: 100%" @click="handleDeleteSelected">
                  删除选中路段
                </el-button>
              </div>
            </template>
          </template>

          <template v-else>
            <div class="setting-item vertical-item">
              <span class="sub-title">实例列表</span>
              <span class="sub-hint">悬浮某行会在右侧地图定位并高亮该实例。</span>
            </div>

            <el-table
              ref="analysisInstanceTableRef"
              :data="analysisInstanceList"
              row-key="id"
              size="small"
              height="280"
              border
              @selection-change="handleInstanceSelectionChange"
              @cell-mouse-enter="handleInstanceCellEnter"
              @cell-mouse-leave="handleInstanceCellLeave"
            >
              <el-table-column type="selection" width="40" :reserve-selection="true" />
              <el-table-column prop="id" label="实例ID" min-width="110" show-overflow-tooltip />
              <el-table-column label="状态" width="76">
                <template #default="scope">
                  <el-tag size="small" :type="getInstanceStatusTagType(scope.row.status)">
                    {{ formatInstanceStatus(scope.row.status) }}
                  </el-tag>
                </template>
              </el-table-column>
              <el-table-column prop="pointCount" label="点数" width="58" />
              <el-table-column prop="matchedRecordCount" label="病害" width="58" />
            </el-table>

            <div class="setting-item" style="margin-top: 10px;">
              <el-button
                type="danger"
                size="small"
                style="width: 49%"
                :disabled="managedInstanceIds.length === 0"
                @click="handleDeleteManagedInstances"
              >
                删除勾选
              </el-button>
              <el-button
                size="small"
                style="width: 49%"
                :disabled="analysisInstanceList.length === 0"
                @click="handleDeleteAllInstances"
              >
                清空全部
              </el-button>
            </div>
          </template>
        </template>
      </div>
      
      <!-- 实时监看功能内容 -->
      <div v-else-if="activeTab === 'real-time-monitor'" class="function-content">
        <h4>实时监看设置</h4>
        <el-divider />
        <div class="setting-item">
          <span class="label">ROS 地址：</span>
          <div class="inline-fields">
            <el-input v-model="rosHost" size="small" placeholder="host" style="width: 90px" />
            <el-input-number
              v-model="rosPort"
              size="small"
              :min="1"
              :max="65535"
              :step="1"
              controls-position="right"
              style="width: 90px"
            />
          </div>
        </div>
        <div class="setting-item">
          <el-button type="primary" size="small" style="width: 49%" @click="handleROSConnect">
            <el-icon><VideoPlay /></el-icon>
            连接
          </el-button>
          <el-button size="small" style="width: 49%" @click="handleROSDisconnect">
            断开
          </el-button>
        </div>
        <div class="setting-item">
          <span class="label">连接状态：</span>
          <el-tag :type="rosConnected ? 'success' : 'info'" size="small">
            {{ rosConnected ? '已连接' : '未连接' }}
          </el-tag>
        </div>
        <div class="setting-item">
          <span class="label">话题类型：</span>
          <el-select
            v-model="selectedTopicType"
            size="small"
            style="width: 130px"
            clearable
            placeholder="全部"
            :disabled="!rosConnected"
          >
            <el-option
              v-for="item in rosTopicTypes"
              :key="item"
              :label="item"
              :value="item"
            />
          </el-select>
        </div>
        <div class="setting-item vertical-item">
          <span class="label">已有话题：</span>
          <el-select
            v-model="selectedTopicNames"
            multiple
            collapse-tags
            collapse-tags-tooltip
            size="small"
            placeholder="请选择话题"
            style="width: 100%"
            :disabled="!rosConnected"
          >
            <el-option
              v-for="topic in visibleRosTopics"
              :key="topic.name"
              :label="`${topic.name} (${topic.type})`"
              :value="topic.name"
            />
          </el-select>
        </div>
        <div class="setting-item">
          <el-button type="primary" size="small" style="width: 100%" :disabled="!rosConnected" @click="applySubscriptions">
            应用订阅
          </el-button>
        </div>
      </div>
      
      <!-- 参数配置功能内容 -->
      <div v-else-if="activeTab === 'parameter-config'" class="function-content">
        <h4>参数配置</h4>
        <el-divider />
        <div class="setting-item vertical-item">
          <span class="label">说明：</span>
          <span style="font-size: 12px; color: #888; line-height: 1.5;">
            参数配置已移动到右侧主界面，可直接浏览和编辑后端 settings 参数。
          </span>
        </div>
      </div>

      <div v-else-if="activeTab === 'data-transfer'" class="function-content">
        <h4>回传管理</h4>
        <el-divider />
        <div class="setting-item vertical-item">
          <span class="label">说明：</span>
          <span style="font-size: 12px; color: #888; line-height: 1.5;">在主面板中查看本地记录、无人机清单并发起回传。</span>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { computed, ref, onMounted, watch, onUnmounted } from 'vue'
import { ElMessage } from 'element-plus'
import {
  MapLocation,
  Histogram,
  VideoCamera,
  Setting,
  VideoPlay,
  Upload,
  QuestionFilled
} from '@element-plus/icons-vue'
import {
  fetchMapTypes,
  fetchDiseaseTypes,
  connectROS,
  disconnectROS,
  fetchROSTopicTypes,
  fetchROSTopics
} from '../api'

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

const DEFAULT_DISEASE_TYPES = [
  { value: 'all', label: '全部' },
  { value: 'fatigue_cracking', label: '疲劳裂缝' },
  { value: 'rutting', label: '车辙' },
  { value: 'potholes', label: '坑洞' },
  { value: 'longitudinal_cracking', label: '纵向裂缝' },
  { value: 'transverse_cracking', label: '横向裂缝' },
  { value: 'block_cracking', label: '块状裂缝' },
  { value: 'edge_cracking', label: '边缘裂缝' },
  { value: 'patching', label: '修补' },
  { value: 'bleeding', label: '泛油' },
  { value: 'raveling', label: '松散/剥落' }
]

const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms))

const requestWithRetry = async (requestFn, { retries = 2, delayMs = 1200, label = '请求' } = {}) => {
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

const props = defineProps({
  activeTab: {
    type: String,
    default: 'disease-distribution'
  },
  collapsed: {
    type: Boolean,
    default: false
  },
  analysisConfig: {
    type: Object,
    default: () => ({
      param_schema: [],
      result_schema: []
    })
  },
  analysisSelection: {
    type: Object,
    default: () => ({
      selectedCount: 0,
      instanceList: [],
      values: {},
      resultValues: {}
    })
  },
  settingsVersion: {
    type: Number,
    default: 0
  }
})

// 定义事件
const emit = defineEmits([
  'tabChange',
  'mapTypeChange',
  'sidebarWidthChange',
  'diseaseTypeChange',
  'timeRangeChange',
  'heatmapChange',
  'analysisParamUpdate',
  'analysisDeleteSelected',
  'analysisDeleteInstances',
  'analysisPreviewInstance',
  'rosConnectionChange',
  'rosSubscriptionsChange'
])

// 功能设置数据
const mapType = ref('normal')
const diseaseType = ref('all')
const filterStartDate = ref('')
const filterEndDate = ref('')
const heatmapEnabled = ref(false)
const analysisPanelMode = ref('params')
const analysisInstanceTableRef = ref(null)
const managedInstanceIds = ref([])
const hoveredInstanceId = ref('')
let previewLeaveTimer = null

const rosHost = ref('100.68.153.103')
const rosPort = ref(9090)
const rosConnected = ref(false)
const rosTopicTypes = ref([])
const rosTopics = ref([])
const selectedTopicType = ref('')
const selectedTopicNames = ref([])
let sidebarResizeObserver = null
const MIXED_VALUE_TOKEN = '__MIXED__'
const UNKNOWN_TYPE_SET = new Set(['unknown', 'unknow', 'none', 'null', 'n/a', 'na', '-', '--'])

const isValidDiseaseType = (value) => {
  if (typeof value !== 'string') {
    return false
  }
  const cleaned = value.trim()
  if (!cleaned) {
    return false
  }
  return !UNKNOWN_TYPE_SET.has(cleaned.toLowerCase())
}

const visibleRosTopics = computed(() => {
  const allTopics = Array.isArray(rosTopics.value) ? rosTopics.value : []
  if (!selectedTopicType.value) {
    return allTopics
  }

  const selectedNameSet = new Set(selectedTopicNames.value)
  return allTopics.filter((topic) => {
    if (!topic || !topic.name) return false
    if (selectedNameSet.has(topic.name)) return true
    return topic.type === selectedTopicType.value
  })
})

const analysisParamSchema = computed(() => {
  const schema = props.analysisConfig?.param_schema
  return Array.isArray(schema) ? schema : []
})

const analysisResultSchema = computed(() => {
  const schema = props.analysisConfig?.result_schema
  return Array.isArray(schema) ? schema : []
})

const analysisSelectedCount = computed(() => {
  return Number(props.analysisSelection?.selectedCount || 0)
})

const analysisValues = computed(() => {
  const values = props.analysisSelection?.values
  return values && typeof values === 'object' ? values : {}
})

const analysisResultValues = computed(() => {
  const values = props.analysisSelection?.resultValues
  return values && typeof values === 'object' ? values : {}
})

const analysisInstanceList = computed(() => {
  const list = props.analysisSelection?.instanceList
  return Array.isArray(list) ? list : []
})

const handleAnalysisParamChange = (item, rawValue) => {
  if (!item?.key) return

  if (item.input === 'select') {
    if (rawValue == null || rawValue === '') return
    emit('analysisParamUpdate', {
      key: item.key,
      value: rawValue
    })
    return
  }

  if (item.input === 'number') {
    if (rawValue == null || rawValue === '') return
    const numericValue = Number(rawValue)
    if (!Number.isFinite(numericValue)) {
      ElMessage.warning(`${item.label} 请输入数字`)
      return
    }
    emit('analysisParamUpdate', {
      key: item.key,
      value: numericValue
    })
    return
  }

  const trimmed = String(rawValue ?? '').trim()
  if (!trimmed) return
  const numeric = Number(trimmed)
  if (!Number.isFinite(numeric)) {
    ElMessage.warning(`${item.label} 请输入数字`)
    return
  }

  emit('analysisParamUpdate', {
    key: item.key,
    value: numeric
  })
}

const formatResultValue = (value) => {
  if (value === MIXED_VALUE_TOKEN) return '多实例值不同'
  if (value == null) return '无数据'
  if (typeof value === 'number') {
    if (!Number.isFinite(value)) return '--'
    if (Math.abs(value) >= 100) return value.toFixed(1)
    return value.toFixed(3).replace(/\.0+$/, '').replace(/(\.\d*[1-9])0+$/, '$1')
  }
  const text = String(value).trim()
  return text || '--'
}

const formatInstanceStatus = (status) => {
  const key = String(status || '').toLowerCase()
  const map = {
    no_data: '无数据',
    healthy: '健康',
    warning: '预警',
    danger: '危险'
  }
  return map[key] || '未知'
}

const getInstanceStatusTagType = (status) => {
  const key = String(status || '').toLowerCase()
  if (key === 'healthy') return 'success'
  if (key === 'warning') return 'warning'
  if (key === 'danger') return 'danger'
  return 'info'
}

const handleInstanceSelectionChange = (rows) => {
  managedInstanceIds.value = rows.map((row) => row?.id).filter(Boolean)
}

const clearPreviewLeaveTimer = () => {
  if (!previewLeaveTimer) return
  clearTimeout(previewLeaveTimer)
  previewLeaveTimer = null
}

const handleInstanceCellEnter = (row) => {
  if (!row?.id) return
  clearPreviewLeaveTimer()
  const instanceId = String(row.id)
  if (hoveredInstanceId.value === instanceId) {
    return
  }
  hoveredInstanceId.value = instanceId
  emit('analysisPreviewInstance', {
    active: true,
    instanceId,
  })
}

const handleInstanceCellLeave = (row) => {
  if (!row?.id) return
  const instanceId = String(row.id)
  clearPreviewLeaveTimer()
  previewLeaveTimer = setTimeout(() => {
    if (hoveredInstanceId.value !== instanceId) {
      return
    }
    hoveredInstanceId.value = ''
    emit('analysisPreviewInstance', {
      active: false,
      instanceId,
    })
  }, 40)
}

const handleDeleteManagedInstances = () => {
  if (managedInstanceIds.value.length === 0) {
    ElMessage.warning('请先勾选要删除的实例')
    return
  }
  emit('analysisDeleteInstances', [...managedInstanceIds.value])
  managedInstanceIds.value = []
}

const handleDeleteAllInstances = () => {
  if (analysisInstanceList.value.length === 0) {
    ElMessage.warning('当前没有可删除的实例')
    return
  }
  const ids = analysisInstanceList.value.map((item) => item?.id).filter(Boolean)
  emit('analysisDeleteInstances', ids)
  managedInstanceIds.value = []
}

const handleDeleteSelected = () => {
  emit('analysisDeleteSelected')
}

// 监听地图类型变化
watch(mapType, (newType) => {
  emit('mapTypeChange', newType)
})

// 监听病害类型变化
watch(diseaseType, (newType) => {
  emit('diseaseTypeChange', newType)
})

watch([filterStartDate, filterEndDate], ([startDate, endDate]) => {
  emit('timeRangeChange', {
    startDate: startDate || '',
    endDate: endDate || ''
  })
})

// 监听热力图状态变化
watch(heatmapEnabled, (val) => {
  emit('heatmapChange', val)
})

// API数据
const mapTypes = ref([])
const diseaseTypes = ref([])

// 获取地图和病害类型数据
const fetchMapAndDiseaseTypes = async () => {
  try {
    const [mapResponse, diseaseResponse] = await Promise.all([
      requestWithRetry(() => fetchMapTypes(), {
        retries: 2,
        delayMs: 1200,
        label: '获取地图类型'
      }),
      requestWithRetry(() => fetchDiseaseTypes(), {
        retries: 2,
        delayMs: 1200,
        label: '获取病害类型'
      })
    ])

    mapTypes.value = Array.isArray(mapResponse.data) ? mapResponse.data : []
    diseaseTypes.value = (Array.isArray(diseaseResponse.data) ? diseaseResponse.data : [])
      .filter((item) => item && isValidDiseaseType(item.value))
  } catch (error) {
    console.error('获取地图/病害类型失败，使用前端默认配置:', error)
    ElMessage.warning('后端配置暂不可用，已使用本地默认设置')
    mapTypes.value = [...DEFAULT_MAP_TYPES]
    diseaseTypes.value = [...DEFAULT_DISEASE_TYPES]
  }

  if (!Array.isArray(mapTypes.value) || mapTypes.value.length === 0) {
    mapTypes.value = [...DEFAULT_MAP_TYPES]
  }
  if (!Array.isArray(diseaseTypes.value) || diseaseTypes.value.length === 0) {
    diseaseTypes.value = [...DEFAULT_DISEASE_TYPES]
  }

  if (!mapTypes.value.some((item) => item.value === mapType.value)) {
    mapType.value = mapTypes.value[0]?.value || 'normal'
  }

  if (!diseaseTypes.value.some((item) => item.value === diseaseType.value)) {
    diseaseType.value = 'all'
  }
}

const fetchROSTopicCatalog = async () => {
  if (!rosConnected.value) {
    rosTopicTypes.value = []
    rosTopics.value = []
    return
  }

  try {
    const [typesResp, topicsResp] = await Promise.all([
      fetchROSTopicTypes(),
      fetchROSTopics()
    ])

    rosTopicTypes.value = typesResp.data.topic_types || []
    rosTopics.value = topicsResp.data.topics || []
  } catch (error) {
    console.error('获取 ROS 话题目录失败:', error)
    ElMessage.error('获取 ROS 话题目录失败')
  }
}

const handleROSConnect = async () => {
  try {
    await connectROS({
      host: rosHost.value,
      port: Number(rosPort.value)
    })
    rosConnected.value = true
    emit('rosConnectionChange', {
      connected: true,
      host: rosHost.value,
      port: Number(rosPort.value)
    })
    await fetchROSTopicCatalog()
    ElMessage.success('ROS 连接成功')
  } catch (error) {
    rosConnected.value = false
    emit('rosConnectionChange', {
      connected: false,
      host: rosHost.value,
      port: Number(rosPort.value)
    })
    console.error('ROS 连接失败:', error)
    ElMessage.error('ROS 连接失败，请确认 rosbridge 服务可用')
  }
}

const handleROSDisconnect = async () => {
  try {
    await disconnectROS()
  } catch (error) {
    console.error('ROS 断开时发生错误:', error)
  }

  rosConnected.value = false
  rosTopicTypes.value = []
  rosTopics.value = []
  selectedTopicNames.value = []
  emit('rosConnectionChange', {
    connected: false,
    host: rosHost.value,
    port: Number(rosPort.value)
  })
  emit('rosSubscriptionsChange', [])
  ElMessage.info('ROS 已断开')
}

const applySubscriptions = () => {
  const topicMap = new Map(rosTopics.value.map(item => [item.name, item.type]))
  const selectedTopics = selectedTopicNames.value
    .map(name => ({ name, type: topicMap.get(name) }))
    .filter(item => item.type)

  emit('rosSubscriptionsChange', selectedTopics)
  ElMessage.success(`已应用 ${selectedTopics.length} 个订阅话题`)
}

watch(selectedTopicType, async () => {
  if (!rosConnected.value) return
  await fetchROSTopicCatalog()
})

watch(analysisPanelMode, (mode) => {
  if (mode === 'instances') {
    return
  }
  clearPreviewLeaveTimer()
  hoveredInstanceId.value = ''
  managedInstanceIds.value = []
  emit('analysisPreviewInstance', {
    active: false,
    instanceId: ''
  })
})

watch(() => props.activeTab, (tab) => {
  if (tab === 'disease-analysis') {
    return
  }
  analysisPanelMode.value = 'params'
  clearPreviewLeaveTimer()
  hoveredInstanceId.value = ''
  managedInstanceIds.value = []
  emit('analysisPreviewInstance', {
    active: false,
    instanceId: ''
  })
})

watch(analysisInstanceList, (list) => {
  const idSet = new Set((Array.isArray(list) ? list : []).map((item) => item?.id).filter(Boolean))
  managedInstanceIds.value = managedInstanceIds.value.filter((id) => idSet.has(id))
})

watch(() => props.settingsVersion, () => {
  fetchMapAndDiseaseTypes()
})

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
  sidebarResizeObserver = new ResizeObserver(updateSidebarWidth);
  const sidebarElement = document.querySelector('.sidebar');
  if (sidebarElement) {
    sidebarResizeObserver.observe(sidebarElement);
  }
});

onUnmounted(() => {
  clearPreviewLeaveTimer()
  hoveredInstanceId.value = ''
  emit('analysisPreviewInstance', {
    active: false,
    instanceId: ''
  })
  if (sidebarResizeObserver) {
    sidebarResizeObserver.disconnect();
    sidebarResizeObserver = null;
  }
});
</script>

<style scoped>
.sidebar {
  height: 100%;
  display: flex;
  flex-direction: column;
  background-color: #fff;
  overflow-x: hidden;
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
  overflow-x: hidden;
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

.analysis-header-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
}

.setting-item {
  margin-bottom: 15px;
  display: flex;
  align-items: center;
  justify-content: space-between;
}

.vertical-item {
  align-items: flex-start;
  flex-direction: column;
  gap: 8px;
}

.inline-fields {
  display: flex;
  align-items: center;
  justify-content: flex-end;
  gap: 8px;
}

.date-range-fields {
  width: 100%;
  display: flex;
  flex-direction: column;
  gap: 8px;
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

.label-with-tip {
  display: flex;
  align-items: center;
  gap: 4px;
}

.help-icon {
  color: #909399;
  cursor: pointer;
}

.sub-title {
  font-size: 13px;
  font-weight: 600;
  color: #303133;
}

.sub-hint {
  font-size: 12px;
  color: #909399;
  line-height: 1.4;
}

:deep(.el-divider) {
  margin: 15px 0;
}
</style>