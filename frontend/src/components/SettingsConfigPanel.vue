<template>
  <div class="settings-page" v-loading="loading">
    <div class="settings-toolbar">
      <div class="toolbar-title">
        <h2>系统参数配置</h2>
        <span>参数源自后端 settings，保存后即时生效并持久化。</span>
      </div>
      <div class="toolbar-actions">
        <el-button size="small" @click="loadSettings">刷新</el-button>
        <el-button size="small" @click="handleReset">恢复默认覆盖</el-button>
        <el-button type="primary" size="small" :loading="saving" @click="handleSave">
          保存配置
        </el-button>
      </div>
    </div>

    <el-row :gutter="14" class="settings-grid">
      <el-col :xs="24" :lg="12">
        <el-card class="settings-card" shadow="never">
          <template #header>
            <div class="card-head">地图参数</div>
          </template>
          <div class="field-row two-col">
            <div>
              <span class="field-label">默认纬度</span>
              <el-input-number
                v-model="settingsForm.default_lat"
                size="small"
                :min="-90"
                :max="90"
                :step="0.0001"
                controls-position="right"
              />
            </div>
            <div>
              <span class="field-label">默认经度</span>
              <el-input-number
                v-model="settingsForm.default_lon"
                size="small"
                :min="-180"
                :max="180"
                :step="0.0001"
                controls-position="right"
              />
            </div>
          </div>

          <div class="inner-title-row">
            <span>地图类型</span>
            <el-button text size="small" @click="addMapType">新增</el-button>
          </div>
          <el-table :data="settingsForm.map_types" size="small" border height="220">
            <el-table-column label="value" min-width="96">
              <template #default="scope">
                <el-input v-model="scope.row.value" size="small" />
              </template>
            </el-table-column>
            <el-table-column label="label" min-width="88">
              <template #default="scope">
                <el-input v-model="scope.row.label" size="small" />
              </template>
            </el-table-column>
            <el-table-column label="subdomains" min-width="120">
              <template #default="scope">
                <el-input v-model="scope.row.subdomainsText" size="small" placeholder="1,2,3,4" />
              </template>
            </el-table-column>
            <el-table-column label="url" min-width="230">
              <template #default="scope">
                <el-input v-model="scope.row.url" size="small" />
              </template>
            </el-table-column>
            <el-table-column label="操作" width="58" fixed="right">
              <template #default="scope">
                <el-button text type="danger" size="small" @click="removeMapType(scope.$index)">删</el-button>
              </template>
            </el-table-column>
          </el-table>
        </el-card>
      </el-col>

      <el-col :xs="24" :lg="12">
        <el-card class="settings-card" shadow="never">
          <template #header>
            <div class="card-head">病害类型</div>
          </template>
          <div class="inner-title-row">
            <span>病害类别清单</span>
          </div>
          <div class="readonly-tip">后端算法依赖固定病害类型，此处仅展示，不支持增删改。</div>
          <el-table :data="settingsForm.disease_types" size="small" border height="310">
            <el-table-column label="value" min-width="150">
              <template #default="scope">
                <el-input :model-value="scope.row.value" size="small" readonly />
              </template>
            </el-table-column>
            <el-table-column label="label" min-width="120">
              <template #default="scope">
                <el-input :model-value="scope.row.label" size="small" readonly />
              </template>
            </el-table-column>
          </el-table>
        </el-card>
      </el-col>

      <el-col :xs="24" :lg="12">
        <el-card class="settings-card" shadow="never">
          <template #header>
            <div class="card-head">病害分析默认参数</div>
          </template>
          <div class="inner-title-row">
            <span>ANALYSIS_INSTANCE_DEFAULTS</span>
          </div>
          <div class="readonly-tip">参数名为后端固定变量，仅允许调整数值。</div>
          <el-table :data="instanceDefaultRows" size="small" border height="280">
            <el-table-column label="key" min-width="150">
              <template #default="scope">
                <el-input :model-value="scope.row.key" size="small" readonly />
              </template>
            </el-table-column>
            <el-table-column label="value" min-width="130">
              <template #default="scope">
                <el-input v-model="scope.row.value" size="small" />
              </template>
            </el-table-column>
          </el-table>
        </el-card>
      </el-col>

      <el-col :xs="24" :lg="12">
        <el-card class="settings-card" shadow="never">
          <template #header>
            <div class="card-head">阈值与状态颜色</div>
          </template>
          <div class="inner-title-row">
            <span>ANALYSIS_THRESHOLDS</span>
          </div>
          <div class="readonly-tip">阈值变量名为固定字段，仅允许调整阈值。</div>
          <el-table :data="thresholdRows" size="small" border height="160">
            <el-table-column label="key" min-width="160">
              <template #default="scope">
                <el-input :model-value="scope.row.key" size="small" readonly />
              </template>
            </el-table-column>
            <el-table-column label="value" min-width="120">
              <template #default="scope">
                <el-input v-model="scope.row.value" size="small" />
              </template>
            </el-table-column>
          </el-table>

          <div class="inner-title-row" style="margin-top: 10px;">
            <span>ANALYSIS_STATUS_COLORS</span>
          </div>
          <div class="readonly-tip">状态名固定，颜色值可按需调整。</div>
          <el-table :data="statusColorRows" size="small" border height="160">
            <el-table-column label="status" min-width="130">
              <template #default="scope">
                <el-input :model-value="scope.row.key" size="small" readonly />
              </template>
            </el-table-column>
            <el-table-column label="color" min-width="190">
              <template #default="scope">
                <el-input v-model="scope.row.value" size="small" />
              </template>
            </el-table-column>
          </el-table>
        </el-card>
      </el-col>

      <el-col :xs="24">
        <el-card class="settings-card" shadow="never">
          <template #header>
            <div class="card-head">Schema 浏览</div>
          </template>
          <el-row :gutter="14">
            <el-col :xs="24" :lg="12">
              <div class="schema-title">ANALYSIS_PARAM_SCHEMA</div>
              <el-input
                :model-value="schemaParamText"
                type="textarea"
                :rows="12"
                readonly
              />
            </el-col>
            <el-col :xs="24" :lg="12">
              <div class="schema-title">ANALYSIS_RESULT_SCHEMA</div>
              <el-input
                :model-value="schemaResultText"
                type="textarea"
                :rows="12"
                readonly
              />
            </el-col>
          </el-row>
        </el-card>
      </el-col>
    </el-row>
  </div>
</template>

<script setup>
import { computed, onMounted, reactive, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { fetchSystemSettings, saveSystemSettings, resetSystemSettings } from '../api'

const emit = defineEmits(['settingsSaved'])

const loading = ref(false)
const saving = ref(false)

const settingsForm = reactive({
  default_lat: 39.9042,
  default_lon: 116.4074,
  map_types: [],
  disease_types: [],
  analysis_param_schema: [],
  analysis_result_schema: [],
})

const instanceDefaultRows = ref([])
const thresholdRows = ref([])
const statusColorRows = ref([])

const schemaParamText = computed(() => JSON.stringify(settingsForm.analysis_param_schema || [], null, 2))
const schemaResultText = computed(() => JSON.stringify(settingsForm.analysis_result_schema || [], null, 2))

const objectToRows = (obj) => {
  if (!obj || typeof obj !== 'object') return []
  return Object.entries(obj).map(([key, value]) => ({
    key,
    value: value == null ? '' : String(value)
  }))
}

const rowsToObject = (rows, parser = null) => {
  const output = {}
  ;(Array.isArray(rows) ? rows : []).forEach((row) => {
    const key = String(row?.key || '').trim()
    if (!key) return
    const raw = row?.value
    output[key] = typeof parser === 'function' ? parser(raw) : raw
  })
  return output
}

const parseAutoScalar = (value) => {
  const raw = String(value ?? '').trim()
  if (!raw) return ''
  if (raw.toLowerCase() === 'true') return true
  if (raw.toLowerCase() === 'false') return false
  const numeric = Number(raw)
  if (Number.isFinite(numeric)) return numeric
  return raw
}

const fillFormFromSettings = (settings) => {
  const source = settings && typeof settings === 'object' ? settings : {}

  const location = Array.isArray(source.default_location) ? source.default_location : [39.9042, 116.4074]
  settingsForm.default_lat = Number(location[0]) || 39.9042
  settingsForm.default_lon = Number(location[1]) || 116.4074

  settingsForm.map_types = (Array.isArray(source.map_types) ? source.map_types : []).map((item) => ({
    value: String(item?.value || ''),
    label: String(item?.label || ''),
    url: String(item?.url || ''),
    subdomainsText: Array.isArray(item?.subdomains) ? item.subdomains.join(',') : '1,2,3,4',
  }))

  settingsForm.disease_types = (Array.isArray(source.disease_types) ? source.disease_types : []).map((item) => ({
    value: String(item?.value || ''),
    label: String(item?.label || ''),
  }))

  instanceDefaultRows.value = objectToRows(source.analysis_instance_defaults)
  thresholdRows.value = objectToRows(source.analysis_thresholds)
  statusColorRows.value = objectToRows(source.analysis_status_colors)

  settingsForm.analysis_param_schema = Array.isArray(source.analysis_param_schema) ? source.analysis_param_schema : []
  settingsForm.analysis_result_schema = Array.isArray(source.analysis_result_schema) ? source.analysis_result_schema : []
}

const buildSavePayload = () => {
  const mapTypes = settingsForm.map_types
    .map((item) => ({
      value: String(item?.value || '').trim(),
      label: String(item?.label || '').trim(),
      url: String(item?.url || '').trim(),
      subdomains: String(item?.subdomainsText || '')
        .split(',')
        .map((v) => v.trim())
        .filter(Boolean),
    }))
    .filter((item) => item.value && item.label && item.url)

  const diseaseTypes = settingsForm.disease_types
    .map((item) => ({
      value: String(item?.value || '').trim(),
      label: String(item?.label || '').trim(),
    }))
    .filter((item) => item.value && item.label)

  return {
    default_location: [Number(settingsForm.default_lat), Number(settingsForm.default_lon)],
    map_types: mapTypes,
    disease_types: diseaseTypes,
    analysis_instance_defaults: rowsToObject(instanceDefaultRows.value, parseAutoScalar),
    analysis_thresholds: rowsToObject(thresholdRows.value, parseAutoScalar),
    analysis_status_colors: rowsToObject(statusColorRows.value, (value) => String(value ?? '').trim()),
    // analysis_param_schema / analysis_result_schema 由后端 settings.py 定义，
    // 前端仅作只读展示，不在保存时回传，避免覆盖后端的正确 schema。
  }
}

const loadSettings = async () => {
  loading.value = true
  try {
    const resp = await fetchSystemSettings()
    fillFormFromSettings(resp?.data || {})
  } catch (error) {
    console.error('加载系统参数失败:', error)
    ElMessage.error('加载系统参数失败')
  } finally {
    loading.value = false
  }
}

const handleSave = async () => {
  saving.value = true
  try {
    const payload = buildSavePayload()
    const resp = await saveSystemSettings(payload)
    const saved = resp?.data?.settings || payload
    fillFormFromSettings(saved)
    emit('settingsSaved', saved)
    ElMessage.success('参数配置已保存')
  } catch (error) {
    console.error('保存系统参数失败:', error)
    ElMessage.error('保存系统参数失败')
  } finally {
    saving.value = false
  }
}

const handleReset = async () => {
  saving.value = true
  try {
    const resp = await resetSystemSettings()
    const settings = resp?.data?.settings || {}
    fillFormFromSettings(settings)
    emit('settingsSaved', settings)
    ElMessage.success('参数已恢复默认覆盖')
  } catch (error) {
    console.error('恢复参数失败:', error)
    ElMessage.error('恢复参数失败')
  } finally {
    saving.value = false
  }
}

const addMapType = () => {
  settingsForm.map_types.push({
    value: '',
    label: '',
    url: '',
    subdomainsText: '1,2,3,4',
  })
}

const removeMapType = (index) => {
  settingsForm.map_types.splice(index, 1)
}

onMounted(async () => {
  await loadSettings()
})
</script>

<style scoped>
.settings-page {
  height: 100%;
  box-sizing: border-box;
  padding: 14px;
  overflow-y: auto;
  background: #f6f8fb;
}

.settings-toolbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  background: #ffffff;
  border: 1px solid #e8ecf3;
  border-radius: 10px;
  padding: 12px 14px;
  margin-bottom: 12px;
}

.toolbar-title h2 {
  margin: 0;
  font-size: 18px;
  color: #1f2a44;
}

.toolbar-title span {
  display: block;
  margin-top: 4px;
  font-size: 12px;
  color: #7a8699;
}

.toolbar-actions {
  display: flex;
  gap: 8px;
}

.settings-grid {
  padding-bottom: 10px;
}

.settings-card {
  margin-bottom: 12px;
  border-radius: 10px;
}

.card-head {
  font-weight: 600;
  color: #223654;
}

.field-row {
  margin-bottom: 10px;
}

.field-row.two-col {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 10px;
}

.field-label {
  display: block;
  margin-bottom: 6px;
  font-size: 12px;
  color: #677489;
}

.inner-title-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 8px;
  font-size: 13px;
  color: #4b5d7a;
  font-weight: 600;
}

.schema-title {
  margin-bottom: 8px;
  font-size: 13px;
  color: #4b5d7a;
  font-weight: 600;
}

.readonly-tip {
  margin-bottom: 8px;
  font-size: 12px;
  color: #7a8699;
}

@media (max-width: 960px) {
  .settings-toolbar {
    flex-direction: column;
    align-items: flex-start;
    gap: 10px;
  }

  .toolbar-actions {
    width: 100%;
  }

  .field-row.two-col {
    grid-template-columns: 1fr;
  }
}
</style>
