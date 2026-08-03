import React from 'react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import deployerAPI from '../api/deployer';
import Drawer from './Drawer';

function formatDate(iso) {
  if (!iso) return '—';
  return new Date(iso).toLocaleString(undefined, {
    month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit',
  });
}

export default function SessionsDrawer({ hostedApp, onClose }) {
  const queryClient = useQueryClient();

  const { data: sessions = [], isLoading } = useQuery({
    queryKey: ['app-sessions', hostedApp.application],
    queryFn: () => deployerAPI.getSessions(hostedApp.application).then((r) => r.data),
  });

  const revoke = useMutation({
    mutationFn: (sessionId) => deployerAPI.revokeSession(hostedApp.application, sessionId),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['app-sessions', hostedApp.application] }),
  });

  return (
    <Drawer title={`Active Sessions — ${hostedApp.application_name}`} onClose={onClose}>
      {isLoading ? (
        <div className="loading-center"><div className="spinner" /></div>
      ) : sessions.length === 0 ? (
        <p className="no-sessions-msg">No active sessions right now.</p>
      ) : (
        sessions.map((s) => (
          <div className="session-row" key={s.id}>
            <div className="session-row-info">
              <div className="session-row-user">{s.username}</div>
              <div className="session-row-meta">
                <span>Started {formatDate(s.started_at)}</span>
                <span>Last seen {formatDate(s.last_seen_at)}</span>
                <span>IP {s.ip_address || '—'}</span>
              </div>
            </div>
            <button
              className="session-row-revoke"
              disabled={revoke.isPending}
              onClick={() => revoke.mutate(s.id)}
            >
              Revoke
            </button>
          </div>
        ))
      )}
    </Drawer>
  );
}
