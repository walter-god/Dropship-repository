import axios from 'axios';

const API_URL = process.env.REACT_APP_API_URL || 'http://localhost:8000/api';

const api = axios.create({
  baseURL: API_URL,
  headers: { 'Content-Type': 'application/json' },
});

api.interceptors.request.use((config) => {
  const token = localStorage.getItem('access_token');
  if (token) config.headers.Authorization = `Bearer ${token}`;
  return config;
});

api.interceptors.response.use(
  (response) => response,
  async (error) => {
    const original = error.config;
    if (error.response?.status === 401 && !original._retry) {
      original._retry = true;
      const refresh = localStorage.getItem('refresh_token');
      if (refresh) {
        try {
          const { data } = await axios.post(`${API_URL}/auth/token/refresh/`, { refresh });
          localStorage.setItem('access_token', data.access);
          original.headers.Authorization = `Bearer ${data.access}`;
          return api(original);
        } catch {
          localStorage.removeItem('access_token');
          localStorage.removeItem('refresh_token');
          window.location.href = '/login';
        }
      } else {
        localStorage.removeItem('access_token');
        window.location.href = '/login';
      }
    }
    return Promise.reject(error);
  }
);

// Auth
export const authAPI = {
  register: (data) => api.post('/auth/register/', data),
  login: (data) => api.post('/auth/login/', data),
  logout: (refresh) => api.post('/auth/logout/', { refresh }),
  getProfile: () => api.get('/auth/profile/'),
  updateProfile: (data) => api.patch('/auth/profile/', data),
  changePassword: (data) => api.post('/auth/change-password/', data),
  getUsers: (params) => api.get('/auth/users/', { params }),
  updateUser: (id, data) => api.patch(`/auth/users/${id}/`, data),
  deleteUser: (id) => api.delete(`/auth/users/${id}/`),
  verifyUser: (id) => api.post(`/auth/users/${id}/verify/`),
  deactivateUser: (id) => api.post(`/auth/users/${id}/deactivate/`),
  activateUser: (id) => api.post(`/auth/users/${id}/activate/`),
};

// Marketplace
export const marketplaceAPI = {
  getApps: (params) => api.get('/marketplace/apps/', { params }),
  getApp: (id) => api.get(`/marketplace/apps/${id}/`),
  getFeaturedApps: () => api.get('/marketplace/apps/featured/'),
  getMyApps: () => api.get('/marketplace/apps/my-apps/'),
  createApp: (data) => api.post('/marketplace/apps/', data, { headers: { 'Content-Type': 'multipart/form-data' } }),
  updateApp: (id, data) => api.patch(`/marketplace/apps/${id}/`, data, { headers: { 'Content-Type': 'multipart/form-data' } }),
  deleteApp: (id) => api.delete(`/marketplace/apps/${id}/`),
  detectStack: (sourceCodeFile) => {
    const form = new FormData();
    form.append('source_code', sourceCodeFile);
    return api.post('/marketplace/apps/detect-stack/', form, {
      headers: { 'Content-Type': 'multipart/form-data' },
    });
  },
  downloadApp: (id) => api.post(`/marketplace/apps/${id}/download/`),
  approveApp: (id) => api.post(`/marketplace/apps/${id}/approve/`),
  rejectApp: (id, reason) => api.post(`/marketplace/apps/${id}/reject/`, { reason }),
  getCategories: () => api.get('/marketplace/categories/'),
  getCategory: (id) => api.get(`/marketplace/categories/${id}/`),
  getReviews: (params) => api.get('/marketplace/reviews/', { params }),
  createReview: (data) => api.post('/marketplace/reviews/', data),
  updateReview: (id, data) => api.patch(`/marketplace/reviews/${id}/`, data),
  deleteReview: (id) => api.delete(`/marketplace/reviews/${id}/`),
};

// Subscriptions
export const subscriptionsAPI = {
  getPlans: () => api.get('/subscriptions/plans/'),
  getPlan: (id) => api.get(`/subscriptions/plans/${id}/`),
  getMySubscriptions: () => api.get('/subscriptions/my-subscriptions/'),
  subscribe: (data) => api.post('/subscriptions/subscribe/', data),
  cancelSubscription: (id) => api.post(`/subscriptions/cancel/${id}/`),
  getAllSubscriptions: (params) => api.get('/subscriptions/my-subscriptions/', { params }),
};

// Payments
export const paymentsAPI = {
  getPayments: (params) => api.get('/payments/', { params }),
  getPayment: (id) => api.get(`/payments/${id}/`),
  initiatePayment: (data) => api.post('/payments/initiate/', data),
  getStats: () => api.get('/payments/stats/'),
};

export default api;
