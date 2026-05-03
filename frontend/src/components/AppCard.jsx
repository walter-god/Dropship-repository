import React from 'react';
import { useNavigate } from 'react-router-dom';
import StarRating from './StarRating';

function formatCount(n) {
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(1)}M`;
  if (n >= 1_000) return `${(n / 1_000).toFixed(1)}K`;
  return String(n);
}

export default function AppCard({ app }) {
  const navigate = useNavigate();

  return (
    <div className="app-card" onClick={() => navigate(`/apps/${app.id}`)} role="button" tabIndex={0}
      onKeyDown={(e) => e.key === 'Enter' && navigate(`/apps/${app.id}`)}>
      <div className="app-card-icon">
        {app.icon
          ? <img src={app.icon} alt={app.name} />
          : <div className="app-icon-placeholder">{app.name?.charAt(0).toUpperCase()}</div>
        }
      </div>
      <div className="app-card-body">
        <h4 className="app-card-name">{app.name}</h4>
        <p className="app-card-developer">{app.developer?.username || 'UDOM'}</p>
        <div className="app-card-meta">
          {app.average_rating && <StarRating value={app.average_rating} size="sm" />}
          <span className="app-card-downloads">{formatCount(app.downloads_count || 0)} downloads</span>
        </div>
        <div className="app-card-footer">
          <span className="app-card-category">{app.category_name || 'App'}</span>
          <span className={`badge ${app.is_free ? 'badge-free' : 'badge-paid'}`}>
            {app.is_free ? 'FREE' : `TZS ${Number(app.price).toLocaleString()}`}
          </span>
        </div>
      </div>
    </div>
  );
}
