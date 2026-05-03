import React, { useState, useEffect } from 'react';
import { useParams, useSearchParams, Link } from 'react-router-dom';
import AppCard from '../components/AppCard';
import { marketplaceAPI } from '../api';

export default function CategoryPage() {
  const { slug } = useParams();
  const [searchParams, setSearchParams] = useSearchParams();
  const [category, setCategory] = useState(null);
  const [apps, setApps] = useState([]);
  const [loading, setLoading] = useState(true);
  const [count, setCount] = useState(0);
  const ordering = searchParams.get('ordering') || '-downloads_count';

  useEffect(() => {
    async function load() {
      setLoading(true);
      try {
        const cats = await marketplaceAPI.getCategories();
        const cat = (cats.data.results || cats.data).find((c) => c.slug === slug);
        if (!cat) { setLoading(false); return; }
        setCategory(cat);
        const appsRes = await marketplaceAPI.getApps({ category: cat.id, ordering, page_size: 24 });
        const a = appsRes.data.results || appsRes.data;
        setApps(a);
        setCount(appsRes.data.count || a.length);
      } catch (err) {
        console.error(err);
      } finally {
        setLoading(false);
      }
    }
    load();
  }, [slug, ordering]);

  if (loading) return <div className="loading-fullscreen"><div className="spinner"></div></div>;
  if (!category) return (
    <div className="empty-state">
      <span className="empty-icon">📭</span>
      <h3>Category not found</h3>
      <Link to="/apps" className="btn btn-primary">Browse All Apps</Link>
    </div>
  );

  return (
    <div className="page-category">
      <div className="category-header">
        <div className="category-header-icon">{category.icon || '📁'}</div>
        <div>
          <h1>{category.name}</h1>
          <p>{category.description || `Browse ${count} ${category.name.toLowerCase()} applications`}</p>
        </div>
      </div>

      <div className="category-toolbar">
        <span>{count} app{count !== 1 ? 's' : ''}</span>
        <select className="select-field" value={ordering}
          onChange={(e) => { const p = new URLSearchParams(searchParams); p.set('ordering', e.target.value); setSearchParams(p); }}>
          <option value="-downloads_count">Most Downloaded</option>
          <option value="-created_at">Newest</option>
          <option value="name">Name A–Z</option>
          <option value="price">Price: Low–High</option>
        </select>
      </div>

      {apps.length === 0
        ? <div className="empty-state"><span className="empty-icon">📭</span><h3>No apps in this category yet.</h3></div>
        : <div className="apps-grid">{apps.map((app) => <AppCard key={app.id} app={app} />)}</div>
      }
    </div>
  );
}
