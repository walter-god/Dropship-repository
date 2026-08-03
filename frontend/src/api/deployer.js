import api from './index';

// Every function here maps 1:1 to an /api/deployer/ endpoint (see
// backend/deployer/urls.py). Deploy/redeploy accept the same optional
// overrides object — { runtime_template_id, provision_database,
// memory_limit_mb, cpu_limit, env_vars, container_port } — so the deploy
// drawer's single button can drive either action identically.

export const deployerAPI = {
  // Hosted apps (keyed by the marketplace Application id).
  // list() returns one row per approved/published project — the admin table.
  listHostedApps: (params) => api.get('/deployer/apps/', { params }),
  getHostedApp: (appId) => api.get(`/deployer/apps/${appId}/`),

  deploy: (appId, overrides = {}) => api.post(`/deployer/apps/${appId}/deploy/`, overrides),
  redeploy: (appId, overrides = {}) => api.post(`/deployer/apps/${appId}/redeploy/`, overrides),
  stop: (appId) => api.post(`/deployer/apps/${appId}/stop/`),
  restart: (appId) => api.post(`/deployer/apps/${appId}/restart/`),
  publish: (appId) => api.post(`/deployer/apps/${appId}/publish/`),
  destroy: (appId, dropDatabase = false) =>
    api.post(`/deployer/apps/${appId}/destroy_deployment/`, { drop_database: dropDatabase }),

  getLogs: (appId, tail = 200) => api.get(`/deployer/apps/${appId}/logs/`, { params: { tail } }),
  getDeployments: (appId, params) => api.get(`/deployer/apps/${appId}/deployments/`, { params }),
  getDeploymentDetail: (appId, deploymentId) =>
    api.get(`/deployer/apps/${appId}/deployments/${deploymentId}/`),

  updateEnv: (appId, payload) => api.patch(`/deployer/apps/${appId}/env/`, payload),
  uploadDockerfile: (appId, dockerfileText) =>
    api.patch(`/deployer/apps/${appId}/dockerfile/`, { dockerfile: dockerfileText }),

  getSessions: (appId, activeOnly = true) =>
    api.get(`/deployer/apps/${appId}/sessions/`, { params: { active_only: activeOnly } }),
  revokeSession: (appId, sessionId) =>
    api.post(`/deployer/apps/${appId}/sessions/${sessionId}/revoke/`),

  // Runtime templates — a short, unpaginated catalogue for the drawer's
  // override dropdown.
  getRuntimeTemplates: () => api.get('/deployer/runtime-templates/'),
};

export default deployerAPI;
