import React, { useRef } from 'react';
import { Link } from 'react-router-dom';
import AppCard from './AppCard';

export default function CategoryRow({ title, apps = [], seeAllLink, loading = false }) {
  const scrollRef = useRef(null);

  const scroll = (dir) => {
    if (scrollRef.current) {
      scrollRef.current.scrollBy({ left: dir * 280, behavior: 'smooth' });
    }
  };

  return (
    <section className="category-row">
      <div className="category-row-header">
        <h3 className="category-row-title">{title}</h3>
        {seeAllLink && (
          <Link to={seeAllLink} className="see-all-link">See all →</Link>
        )}
      </div>

      <div className="category-row-wrapper">
        <button className="scroll-btn scroll-btn-left" onClick={() => scroll(-1)} aria-label="Scroll left">‹</button>

        <div className="category-row-scroll" ref={scrollRef}>
          {loading
            ? Array.from({ length: 5 }).map((_, i) => (
                <div key={i} className="app-card app-card-skeleton">
                  <div className="skeleton skeleton-icon" />
                  <div className="skeleton skeleton-line" />
                  <div className="skeleton skeleton-line-sm" />
                </div>
              ))
            : apps.length > 0
              ? apps.map((app) => <AppCard key={app.id} app={app} />)
              : <p className="no-apps">No apps in this category yet.</p>
          }
        </div>

        <button className="scroll-btn scroll-btn-right" onClick={() => scroll(1)} aria-label="Scroll right">›</button>
      </div>
    </section>
  );
}
