import React, { useState, useEffect, useRef, useCallback } from 'react';
import { useNavigate } from 'react-router-dom';
import { marketplaceAPI } from '../api';

function useDebounce(value, delay) {
  const [debounced, setDebounced] = useState(value);
  useEffect(() => {
    const t = setTimeout(() => setDebounced(value), delay);
    return () => clearTimeout(t);
  }, [value, delay]);
  return debounced;
}

export default function SearchBar({ placeholder = 'Search apps…', onSearch }) {
  const [query, setQuery] = useState('');
  const [results, setResults] = useState([]);
  const [open, setOpen] = useState(false);
  const [loading, setLoading] = useState(false);
  const debouncedQuery = useDebounce(query, 400);
  const navigate = useNavigate();
  const containerRef = useRef(null);

  const search = useCallback(async (q) => {
    if (!q.trim()) { setResults([]); return; }
    setLoading(true);
    try {
      const { data } = await marketplaceAPI.getApps({ search: q, page_size: 6 });
      setResults(data.results || data);
    } catch {
      setResults([]);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { search(debouncedQuery); }, [debouncedQuery, search]);

  useEffect(() => {
    const handler = (e) => { if (!containerRef.current?.contains(e.target)) setOpen(false); };
    document.addEventListener('mousedown', handler);
    return () => document.removeEventListener('mousedown', handler);
  }, []);

  const handleSubmit = (e) => {
    e.preventDefault();
    if (query.trim()) {
      setOpen(false);
      if (onSearch) onSearch(query);
      else navigate(`/apps?search=${encodeURIComponent(query)}`);
    }
  };

  const pickResult = (app) => {
    setOpen(false);
    setQuery('');
    navigate(`/apps/${app.id}`);
  };

  return (
    <div className="search-bar-container" ref={containerRef}>
      <form className="search-bar" onSubmit={handleSubmit}>
        <span className="search-icon">🔍</span>
        <input
          type="text"
          value={query}
          onChange={(e) => { setQuery(e.target.value); setOpen(true); }}
          onFocus={() => query && setOpen(true)}
          placeholder={placeholder}
          className="search-input"
          autoComplete="off"
        />
        {query && (
          <button type="button" className="search-clear" onClick={() => { setQuery(''); setResults([]); }}>✕</button>
        )}
      </form>
      {open && (query.length > 0) && (
        <div className="search-dropdown">
          {loading && <div className="search-loading">Searching…</div>}
          {!loading && results.length === 0 && <div className="search-empty">No results for "{query}"</div>}
          {results.map((app) => (
            <div key={app.id} className="search-result-item" onClick={() => pickResult(app)}>
              <div className="search-result-icon">
                {app.icon ? <img src={app.icon} alt={app.name} /> : <span>{app.name?.charAt(0)}</span>}
              </div>
              <div className="search-result-info">
                <span className="search-result-name">{app.name}</span>
                <span className="search-result-cat">{app.category_name}</span>
              </div>
              <span className={`badge ${app.is_free ? 'badge-free' : 'badge-paid'}`}>
                {app.is_free ? 'FREE' : 'PAID'}
              </span>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
