import React, { useState, useEffect } from 'react';
import { Link } from 'react-router-dom';
import FeaturedBanner from '../components/FeaturedBanner';
import CategoryRow from '../components/CategoryRow';
import AppCard from '../components/AppCard';
import { marketplaceAPI } from '../api';

export default function Home() {
  const [featuredApps, setFeaturedApps] = useState([]);
  const [newApps, setNewApps] = useState([]);
  const [popularApps, setPopularApps] = useState([]);
  const [categories, setCategories] = useState([]);
  const [loading, setLoading] = useState(true);
  const [stats, setStats] = useState({ apps: 0, categories: 0 });

  useEffect(() => {
    async function load() {
      try {
        const [featuredRes, newRes, popularRes, catRes] = await Promise.all([
          marketplaceAPI.getFeaturedApps(),
          marketplaceAPI.getApps({ ordering: '-created_at', page_size: 12 }),
          marketplaceAPI.getApps({ ordering: '-downloads_count', page_size: 12 }),
          marketplaceAPI.getCategories(),
        ]);
        const featured = featuredRes.data.results || featuredRes.data;
        const newA = newRes.data.results || newRes.data;
        const popular = popularRes.data.results || popularRes.data;
        const cats = catRes.data.results || catRes.data;
        setFeaturedApps(featured);
        setNewApps(newA);
        setPopularApps(popular);
        setCategories(cats);
        setStats({ apps: newRes.data.count || newA.length, categories: cats.length });
      } catch (err) {
        console.error(err);
      } finally {
        setLoading(false);
      }
    }
    load();
  }, []);

  const CATEGORY_ICONS = {
    Education: '📚', Productivity: '⚡', Research: '🔬', Communication: '💬',
    Finance: '💰', Health: '🏥', Entertainment: '🎮', Utilities: '🛠️',
    PaaS: '☁️', 'Developer Tools': '💻',
  };

  return (
    <div className="page-home">
      {/* Featured Banner */}
      <FeaturedBanner apps={featuredApps} />

      {/* Stats Bar */}
      <div className="stats-bar">
        <div className="stat-item"><span className="stat-number">{stats.apps}+</span><span className="stat-label">Applications</span></div>
        <div className="stat-divider" />
        <div className="stat-item"><span className="stat-number">{stats.categories}</span><span className="stat-label">Categories</span></div>
        <div className="stat-divider" />
        <div className="stat-item"><span className="stat-number">UDOM</span><span className="stat-label">Community Built</span></div>
        <div className="stat-divider" />
        <div className="stat-item"><span className="stat-number">Free</span><span className="stat-label">For Campus Users</span></div>
      </div>

      {/* Categories Grid */}
      <section className="section categories-section">
        <div className="section-header">
          <h2>Browse by Category</h2>
          <Link to="/apps" className="see-all-link">All Apps →</Link>
        </div>
        <div className="categories-grid">
          {loading
            ? Array.from({ length: 8 }).map((_, i) => (
                <div key={i} className="category-chip skeleton-chip" />
              ))
            : categories.slice(0, 10).map((cat) => (
                <Link key={cat.id} to={`/apps?category=${cat.id}`} className="category-chip">
                  <span className="category-chip-icon">{CATEGORY_ICONS[cat.name] || '📁'}</span>
                  <span className="category-chip-name">{cat.name}</span>
                  <span className="category-chip-count">{cat.app_count}</span>
                </Link>
              ))
          }
        </div>
      </section>

      {/* Popular Apps */}
      <section className="section">
        <CategoryRow
          title="🔥 Most Popular"
          apps={popularApps}
          loading={loading}
          seeAllLink="/apps?ordering=-downloads_count"
        />
      </section>

      {/* New Releases */}
      <section className="section">
        <CategoryRow
          title="🆕 New Releases"
          apps={newApps}
          loading={loading}
          seeAllLink="/apps?ordering=-created_at"
        />
      </section>

      {/* CTA Banner */}
      <section className="cta-banner">
        <div className="cta-content">
          <h2>Are you a UDOM student or lecturer?</h2>
          <p>Get free access to all campus applications with your university credentials.</p>
          <div className="cta-buttons">
            <Link to="/register" className="btn btn-accent btn-lg">Get Started Free</Link>
            <Link to="/apps" className="btn btn-outline btn-lg">Browse Apps</Link>
          </div>
        </div>
      </section>
    </div>
  );
}
