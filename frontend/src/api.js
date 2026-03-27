import axios from 'axios';

const apiClient = axios.create({
  baseURL: 'http://localhost:8000/api',
  timeout: 10000,
});

export const fetchMapTypes = () => apiClient.get('/map-types');
export const fetchDiseaseTypes = () => apiClient.get('/disease-types');
export const fetchDiseaseImages = () => apiClient.get('/disease-images');
export const fetchRecords = () => apiClient.get('/records');

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

export const buildROSWebSocketUrl = () => {
  const base = apiClient.defaults.baseURL || 'http://localhost:8000/api';
  const wsBase = base.replace(/^http/i, 'ws');
  return `${wsBase}/ros/ws`;
};

export { apiClient };