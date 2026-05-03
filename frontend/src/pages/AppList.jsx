import React, { useState, useEffect, useCallback } from 'react';
import { useSearchParams } from 'react-router-dom';
import AppCard from '../components/AppCard';
import { marketplaceAPI } from '../api';

const SORT_OPTIONS = [
  { value: '-created_at', label: 'Newest First' },
  { value: '-downloads_count', label: 'Most Downloaded' },
  { value: '-views_count', label: 'Most Viewed' },
  { value: 'name', label: 'Name A–Z' },
  { value: 'price', label: 'Price: Low to High' },
];

export default function AppList() {
  const [searchParams, setSearchParams] = useSearchParams();
  const [apps, setApps] = useState([]);
  const [categories, setCategories] = useState([]);
  const [loading, setLoading] = useState(true);
  const [count, setCount] = useState(0);
  const [page, setPage] = useState(1);
  const [hasNext, setHasNext] = useState(false);

  const search = searchParams.get('search') || '';
  const category = searchParams.get('category') || '';
  const ordering = searchParams.get('ordering') || '-created_at';

  const loadApps = useCallback(async (p = 1) => {
    setLoading(true);
    try {
      const params = { page: p, page_size: 24, ordering };
      if (search) params.search = search;
      if (category) params.category = category;
      const { data } = await marketplaceAPI.getApps(params);
      const results = data.results || data;
      setApps(p === 1 ? results : (prev) => [...prev, ...results]);
      setCount(data.count || results.length);
      setHasNext(!!data.next);
      setPage(p);
    } catch (err) {
      console.error(err);
    } finally {
      setLoading(false);
    }
  }, [search, category, ordering]);

  useEffect(() => { loadApps(1); }, [loadApps]);

  useEffect(() => {
    marketplaceAPI.getCategories().then(({ data }) => setCategories(data.results || data)).catch(() => {});
  }, []);

  const updateParam = (key, value) => {
    const p = new URLSearchParams(searchParams);
    if (value) p.set(key, value); else p.delete(key);
    setSearchParams(p);
  };

  return (
    <div className="page-app-list">
      <div className="app-list-header">
        <h1>Browse Apps</h1>
        <p>{count} application{count !== 1 ? 's' : ''} available</p>
      </div>

      <div className="app-list-layout">
        {/* Sidebar Filters */}
        <aside className="filter-sidebar">
          <h3>Categories</h3>
          <button className={`filter-cat-btn ${!category ? 'active' : ''}`} onClick={() => updateParam('category', '')}>
            All Categories
          </button>
          {categories.map((cat) => (
            <button key={cat.id} className={`filter-cat-btn ${category === String(cat.id) ? 'active' : ''}`}
              onClick={() => updateParam('category', String(cat.id))}>
              {cat.name} <span className="cat-count">{cat.app_count}</span>
            </button>
          ))}
        </aside>

        {/* Main Content */}
        <div className="app-list-main">
          {/* Toolbar */}
          <div className="app-list-toolbar">
            <div className="search-inline">
              <input type="text" defaultValue={search} placeholder="Search apps…"
                onKeyDown={(e) => e.key === 'Enter' && updateParam('search', e.target.value)}
                className="input-field" />
            </div>
            <select className="select-field" value={ordering} onChange={(e) => updateParam('ordering', e.target.value)}>
              {SORT_OPTIONS.map((o) => <option key={o.value} value={o.value}>{o.label}</option>)}
            </select>
          </div>

          {/* Grid */}
          {loading && apps.length === 0 ? (
            <div className="apps-grid">
              {Array.from({ length: 12 }).map((_, i) => (
                <div key={i} className="app-card app-card-skeleton">
                  <div className="skeleton skeleton-icon" />
                  <div className="skeleton skeleton-line" />
                  <div className="skeleton skeleton-line-sm" />
                </div>
              ))}
            </div>
          ) : apps.length === 0 ? (
            <div className="empty-state">
              <span className="empty-icon">📭</span>
              <h3>No apps found</h3>
              <p>Try adjusting your search or filters.</p>
            </div>
          ) : (
            <div className="apps-grid">
              {apps.map((app) => <AppCard key={app.id} app={app} />)}
            </div>
          )}

          {hasNext && (
            <div className="load-more">
              <button className="btn btn-outline" onClick={() => loadApps(page + 1)} disabled={loading}>
                {loading ? 'Loading…' : 'Load More'}
              </button>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
