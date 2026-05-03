import React, { useState, useEffect, useCallback } from 'react';
import { useNavigate } from 'react-router-dom';

const COLORS = [
  ['#006633', '#003366'],
  ['#003366', '#1a1a2e'],
  ['#1a1a2e', '#006633'],
  ['#0d1b2a', '#003366'],
  ['#004d26', '#0055a5'],
];

export default function FeaturedBanner({ apps = [] }) {
  const [current, setCurrent] = useState(0);
  const navigate = useNavigate();

  const next = useCallback(() => setCurrent((c) => (c + 1) % Math.max(apps.length, 1)), [apps.length]);
  const prev = () => setCurrent((c) => (c - 1 + apps.length) % apps.length);

  useEffect(() => {
    if (apps.length < 2) return;
    const timer = setInterval(next, 5000);
    return () => clearInterval(timer);
  }, [apps.length, next]);

  if (!apps.length) {
    return (
      <div className="featured-banner featured-banner-empty">
        <div className="featured-placeholder">
          <span>🎓</span>
          <p>Featured apps loading…</p>
        </div>
      </div>
    );
  }

  const app = apps[current];
  const [from, to] = COLORS[current % COLORS.length];

  return (
    <div className="featured-banner" style={{ background: `linear-gradient(135deg, ${from} 0%, ${to} 100%)` }}>
      <div className="featured-content">
        <div className="featured-app-info">
          <div className="featured-badge">⭐ FEATURED</div>
          <h2 className="featured-title">{app.name}</h2>
          <p className="featured-desc">{app.short_description || app.description?.slice(0, 120)}</p>
          <div className="featured-meta">
            <span className="featured-category">{app.category_name}</span>
            <span className={`badge ${app.is_free ? 'badge-free' : 'badge-paid'}`}>
              {app.is_free ? 'FREE' : `TZS ${Number(app.price).toLocaleString()}`}
            </span>
          </div>
          <button className="btn btn-accent featured-cta" onClick={() => navigate(`/apps/${app.id}`)}>
            View App →
          </button>
        </div>
        <div className="featured-app-icon">
          {app.icon
            ? <img src={app.icon} alt={app.name} className="featured-icon-img" />
            : <div className="featured-icon-placeholder">{app.name?.charAt(0)}</div>
          }
        </div>
      </div>

      {apps.length > 1 && (
        <>
          <button className="banner-arrow banner-arrow-left" onClick={prev}>‹</button>
          <button className="banner-arrow banner-arrow-right" onClick={next}>›</button>
          <div className="banner-dots">
            {apps.map((_, i) => (
              <button key={i} className={`dot ${i === current ? 'dot-active' : ''}`} onClick={() => setCurrent(i)} />
            ))}
          </div>
        </>
      )}
    </div>
  );
}
