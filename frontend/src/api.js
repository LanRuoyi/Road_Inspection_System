import axios from 'axios';

const apiClient = axios.create({
  baseURL: 'http://localhost:8000/api',
  timeout: 10000,
});

export const fetchMapTypes = () => apiClient.get('/map-types');
export const fetchDiseaseTypes = () => apiClient.get('/disease-types');
export const fetchDiseaseImages = () => apiClient.get('/disease-images');
export const fetchRecords = () => apiClient.get('/records');

export { apiClient };