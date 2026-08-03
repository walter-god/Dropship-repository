import React from 'react';

const LABELS = {
  not_deployed: 'Not deployed',
  queued: 'Queued',
  building: 'Building',
  starting: 'Starting',
  live: 'Live',
  paused: 'Paused',
  stopped: 'Stopped',
  failed: 'Failed',
};

export default function StatusPill({ status }) {
  const label = LABELS[status] || status;
  return (
    <span className={`status-pill status-pill-${status}`}>
      <span className="status-pill-dot" />
      {label}
    </span>
  );
}
