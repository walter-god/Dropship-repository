import React, { useState } from 'react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { Link } from 'react-router-dom';
import deployerAPI from '../api/deployer';
import StatusPill from '../components/StatusPill';
import DeployDrawer from '../components/DeployDrawer';
import DeploymentLogModal from '../components/DeploymentLogModal';
import SessionsDrawer from '../components/SessionsDrawer';

const BUSY_STATUSES = ['queued', 'building', 'starting'];

function formatDate(iso) {
  if (!iso) return '—';
  return new Date(iso).toLocaleString(undefined, {
    month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit',
  });
}

export default function AdminHostedAppsPage() {
  const queryClient = useQueryClient();
  const [deployTarget, setDeployTarget] = useState(null);   // hosted app row, or null
  const [logsTarget, setLogsTarget] = useState(null);
  const [sessionsTarget, setSessionsTarget] = useState(null);
  const [actionError, setActionError] = useState('');

  const { data: rows = [], isLoading, isFetching } = useQuery({
    queryKey: ['hosted-apps'],
    queryFn: async () => {
      const { data } = await deployerAPI.listHostedApps();
      return data.results || data;
    },
    // Poll aggressively only while something is actually building; otherwise
    // the table is inert and there's nothing to refresh for.
    refetchInterval: (query) => {
      const current = query.state.data || [];
      return current.some((r) => BUSY_STATUSES.includes(r.status)) ? 3000 : false;
    },
  });

  const invalidate = () => queryClient.invalidateQueries({ queryKey: ['hosted-apps'] });

  const simpleAction = useMutation({
    mutationFn: ({ action, appId }) => {
      if (action === 'stop') return deployerAPI.stop(appId);
      if (action === 'restart') return deployerAPI.restart(appId);
      if (action === 'publish') return deployerAPI.publish(appId);
      if (action === 'redeploy') return deployerAPI.redeploy(appId, {});
      return Promise.reject(new Error(`Unknown action: ${action}`));
    },
    onSuccess: () => { setActionError(''); invalidate(); },
    onError: (err) => setActionError(err.response?.data?.error || 'Action failed.'),
  });

  const handleAction = (action, row) => {
    if (action === 'deploy') { setDeployTarget(row); return; }
    if (action === 'logs') { setLogsTarget(row); return; }
    if (action === 'sessions') { setSessionsTarget(row); return; }
    if (action === 'redeploy') {
      simpleAction.mutate({ action: 'redeploy', appId: row.application });
      setLogsTarget(row);
      return;
    }
    simpleAction.mutate({ action, appId: row.application });
  };

  const actionsFor = (row) => {
    const actions = [];
    if (row.status === 'not_deployed' || row.status === 'stopped') {
      actions.push({ key: 'deploy', label: 'Deploy', variant: 'primary' });
    }
    if (BUSY_STATUSES.includes(row.status)) {
      actions.push({ key: 'logs', label: 'View Logs', variant: 'primary' });
    }
    if (row.status === 'live') {
      actions.push({ key: 'logs', label: 'View Logs' });
      actions.push({ key: 'restart', label: 'Restart' });
      actions.push({ key: 'stop', label: 'Stop', variant: 'danger' });
      actions.push({ key: 'redeploy', label: 'Redeploy' });
      if (row.application_status !== 'published') {
        actions.push({ key: 'publish', label: 'Publish', variant: 'success' });
      }
      actions.push({ key: 'sessions', label: `Sessions (${row.active_session_count})` });
    }
    if (row.status === 'paused') {
      actions.push({ key: 'restart', label: 'Resume', variant: 'primary' });
      actions.push({ key: 'logs', label: 'View Logs' });
      actions.push({ key: 'sessions', label: `Sessions (${row.active_session_count})` });
    }
    if (row.status === 'stopped') {
      actions.push({ key: 'restart', label: 'Restart' });
      actions.push({ key: 'redeploy', label: 'Redeploy' });
      actions.push({ key: 'logs', label: 'View Logs' });
    }
    if (row.status === 'failed') {
      actions.push({ key: 'logs', label: 'View Logs', variant: 'primary' });
      actions.push({ key: 'redeploy', label: 'Retry' });
    }
    return actions;
  };

  return (
    <div className="page-hosted-apps">
      <div className="hosted-apps-header">
        <div>
          <h1>🚀 Hosted Applications</h1>
          <p>Deploy, monitor, and manage running student projects.</p>
        </div>
        <div className="hosted-apps-toolbar">
          {isFetching && (
            <span className="refresh-indicator"><span className="refresh-dot" /> live</span>
          )}
          <Link to="/admin" className="btn btn-outline btn-sm">← Admin Panel</Link>
        </div>
      </div>

      {actionError && <div className="alert alert-error">{actionError}</div>}

      {isLoading ? (
        <div className="loading-center"><div className="spinner" /></div>
      ) : rows.length === 0 ? (
        <div className="empty-state">
          <span className="empty-icon">📭</span>
          <h3>No approved or published projects yet</h3>
          <p>Projects appear here once an admin approves them in the Apps tab.</p>
        </div>
      ) : (
        <div className="hosted-apps-table-wrapper">
          <table className="hosted-apps-table">
            <thead>
              <tr>
                <th>Project</th><th>Developer</th><th>Runtime</th><th>Status</th>
                <th>Last Deployed</th><th>Sessions</th><th>Actions</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((row) => (
                <tr key={row.id}>
                  <td>
                    <div className="project-title-cell">
                      <span className="project-title-name">{row.application_name}</span>
                      <span className="project-title-meta">
                        {row.application_slug}
                        {row.application_status === 'published' && (
                          <span className="badge badge-free">Published</span>
                        )}
                      </span>
                    </div>
                  </td>
                  <td>{row.developer_username}</td>
                  <td>
                    {row.runtime_template
                      ? <span className="runtime-chip">{row.runtime_template.display_name}</span>
                      : row.detected_runtime_key
                        ? <span className="runtime-chip">{row.detected_runtime_key}</span>
                        : <span className="runtime-chip runtime-chip-none">not detected</span>
                    }
                  </td>
                  <td><StatusPill status={row.status} /></td>
                  <td>{formatDate(row.last_deployment?.created_at)}</td>
                  <td>
                    <span className={`session-count-badge ${row.active_session_count > 0 ? 'has-sessions' : ''}`}>
                      {row.active_session_count > 0 ? '🟢' : '—'} {row.active_session_count}
                    </span>
                  </td>
                  <td>
                    <div className="row-actions">
                      {actionsFor(row).map((a) => (
                        <button key={a.key} className={`row-action-btn ${a.variant || ''}`}
                          disabled={simpleAction.isPending}
                          onClick={() => handleAction(a.key, row)}>
                          {a.label}
                        </button>
                      ))}
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {deployTarget && (
        <DeployDrawer
          hostedApp={deployTarget}
          onClose={() => setDeployTarget(null)}
          onDeployed={() => { setLogsTarget(deployTarget); setDeployTarget(null); invalidate(); }}
        />
      )}

      {logsTarget && (
        <DeploymentLogModal
          hostedApp={logsTarget}
          onClose={() => { setLogsTarget(null); invalidate(); }}
          onRetry={(row) => { simpleAction.mutate({ action: 'redeploy', appId: row.application }); }}
          onEditEnv={(row) => { setLogsTarget(null); setDeployTarget(row); }}
        />
      )}

      {sessionsTarget && (
        <SessionsDrawer hostedApp={sessionsTarget} onClose={() => setSessionsTarget(null)} />
      )}
    </div>
  );
}
