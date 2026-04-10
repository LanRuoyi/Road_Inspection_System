import axios from 'axios';

const resolvedBaseUrl = (import.meta.env.VITE_API_BASE_URL || 'http://127.0.0.1:8001/api').replace(/\/$/, '');

const apiClient = axios.create({
  baseURL: resolvedBaseUrl,
  timeout: 10000,
});

export const fetchMapTypes = () => apiClient.get('/map-types');
export const fetchDiseaseTypes = () => apiClient.get('/disease-types');
export const fetchRecords = () => apiClient.get('/records');
export const fetchAnalysisConfig = () => apiClient.get('/analysis/config');
export const assessAnalysisSegments = (segments = []) => apiClient.post('/analysis/assess', { segments });
export const fetchAnalysisInstances = () => apiClient.get('/analysis/instances');
export const saveAnalysisInstances = (instances = []) => apiClient.put('/analysis/instances', { instances });
export const deleteAnalysisInstances = (instanceIds = []) => apiClient.delete('/analysis/instances', {
  data: {
    instance_ids: instanceIds
  }
});

export const fetchSystemSettings = () => apiClient.get('/system/settings');
export const saveSystemSettings = (settings = {}) => apiClient.put('/system/settings', settings);
export const resetSystemSettings = () => apiClient.post('/system/settings/reset');

export const connectROS = (payload) => apiClient.post('/ros/connect', payload);
export const disconnectROS = () => apiClient.post('/ros/disconnect');
export const fetchROSStatus = () => apiClient.get('/ros/status');
export const fetchROSTopicTypes = () => apiClient.get('/ros/topic-types');
export const fetchROSTopics = (topicType = '') => {
  if (!topicType) {
    return apiClient.get('/ros/topics');
  }
  return apiClient.get('/ros/topics', {
    params: { topic_type: topicType }
  });
};

export const subscribeROSTopics = (topics = []) => apiClient.post('/ros/subscribe', { topics });

export const fetchROSMessages = (topicNames = []) => apiClient.get('/ros/messages', {
  params: {
    topics: topicNames.join(',')
  }
});

export const fetchLocalUAVRecords = () => apiClient.get('/uav/local-records');
export const fetchUAVDevices = () => apiClient.get('/uav/devices');
export const fetchUAVDeviceManifest = (deviceId) => apiClient.get(`/uav/devices/${encodeURIComponent(deviceId)}/manifest`);
export const startUAVPullTransfer = (deviceId, itemIds = []) => apiClient.post(`/uav/devices/${encodeURIComponent(deviceId)}/pull-start`, {
  item_ids: itemIds
});

export const buildROSWebSocketUrl = () => {
  const absoluteBase = apiClient.defaults.baseURL || resolvedBaseUrl;
  const base = absoluteBase.startsWith('http') ? absoluteBase : `${window.location.origin}${absoluteBase}`;
  const wsBase = base.replace(/^http/i, 'ws');
  return `${wsBase}/ros/ws`;
};

export { apiClient };