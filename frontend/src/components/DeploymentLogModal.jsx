import React, { useEffect, useRef } from 'react';
import { useQuery } from '@tanstack/react-query';
import deployerAPI from '../api/deployer';

const BUSY_STATUSES = ['queued', 'building', 'starting'];

export default function DeploymentLogModal({ hostedApp, onClose, onRetry, onEditEnv }) {
  const logRef = useRef(null);

  const { data } = useQuery({
    queryKey: ['deployment-logs', hostedApp.application],
    queryFn: () => deployerAPI.getLogs(hostedApp.application).then((r) => r.data),
    // Poll only while the build is actually running — once it lands on
    // live/failed there's nothing left to stream.
    refetchInterval: (query) => {
      const status = query.state.data?.hosted_app_status;
      return BUSY_STATUSES.includes(status) ? 2000 : false;
    },
  });

  const status = data?.hosted_app_status || hostedApp.status;
  const deployment = data?.deployment;
  const buildLog = data?.build_log || '';
  const containerLogs = data?.container_logs || '';
  const combinedLog = [buildLog, containerLogs && `\n===== container logs =====\n${containerLogs}`]
    .filter(Boolean).join('');

  useEffect(() => {
    if (logRef.current) logRef.current.scrollTop = logRef.current.scrollHeight;
  }, [combinedLog]);

  const isLive = status === 'live';
  const isFailed = status === 'failed';
  const isBusy = BUSY_STATUSES.includes(status);

  return (
    <div className="log-modal-overlay" onClick={onClose}>
      <div className="log-modal" onClick={(e) => e.stopPropagation()}>
        <div className="log-modal-header">
          <div className="log-modal-title">
            <h3>{hostedApp.application_name}</h3>
            {isBusy && <span className="badge badge-new">{status}…</span>}
            {isLive && <span className="badge badge-free">live</span>}
            {isFailed && <span className="badge badge-paid" style={{ color: 'var(--error)' }}>failed</span>}
          </div>
          <button className="drawer-close" onClick={onClose} aria-label="Close">✕</button>
        </div>

        {isFailed && deployment?.error_summary && (
          <div className="log-modal-error-banner">
            <strong>Error:</strong> {deployment.error_summary}
          </div>
        )}

        <div className="log-viewer" ref={logRef}>
          {combinedLog ? combinedLog : (
            <div className="log-empty-state">
              {isBusy ? 'Waiting for build output…' : 'No log output for this deployment.'}
            </div>
          )}
        </div>

        <div className="log-modal-footer">
          {isLive && (
            <button className="btn btn-publish" onClick={async () => {
              await deployerAPI.publish(hostedApp.application);
              onClose();
            }}>
              ✓ Publish to Marketplace
            </button>
          )}
          {isFailed && (
            <>
              <button className="btn btn-outline" onClick={() => onEditEnv(hostedApp)}>
                Edit Env Vars
              </button>
              <button className="btn btn-primary" onClick={() => onRetry(hostedApp)}>
                🔄 Retry
              </button>
            </>
          )}
          {!isLive && !isFailed && (
            <button className="btn btn-outline" onClick={onClose}>Close</button>
          )}
        </div>
      </div>
    </div>
  );
}
