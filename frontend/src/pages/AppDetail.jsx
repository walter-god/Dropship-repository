import React, { useState, useEffect } from 'react';
import { useParams, useNavigate, Link } from 'react-router-dom';
import { marketplaceAPI } from '../api';
import { useAuth } from '../context/AuthContext';
import StarRating from '../components/StarRating';

function InfoRow({ label, value }) {
  return (
    <div className="info-row">
      <span className="info-label">{label}</span>
      <span className="info-value">{value || '—'}</span>
    </div>
  );
}

export default function AppDetail() {
  const { id } = useParams();
  const navigate = useNavigate();
  const { isAuthenticated, isAdmin, isInternal, isExternal, hasActiveSubscription, user } = useAuth();

  const [app, setApp] = useState(null);
  const [loading, setLoading] = useState(true);
  const [tab, setTab] = useState('description');
  const [downloading, setDownloading] = useState(false);
  const [downloadMsg, setDownloadMsg] = useState('');
  const [reviewForm, setReviewForm] = useState({ rating: 5, comment: '' });
  const [reviewError, setReviewError] = useState('');
  const [reviewSuccess, setReviewSuccess] = useState('');
  const [selectedImg, setSelectedImg] = useState(null);

  useEffect(() => {
    marketplaceAPI.getApp(id)
      .then(({ data }) => { setApp(data); })
      .catch(() => navigate('/apps'))
      .finally(() => setLoading(false));
  }, [id, navigate]);

  const canDownload = () => {
    if (!isAuthenticated) return false;
    if (isAdmin || isInternal) return true;
    if (isExternal && app?.is_free) return true;
    if (isExternal && hasActiveSubscription) return true;
    return false;
  };

  const handleDownload = async () => {
    if (!isAuthenticated) { navigate('/login'); return; }
    if (!canDownload()) { navigate('/subscription'); return; }
    setDownloading(true);
    setDownloadMsg('');
    try {
      const { data } = await marketplaceAPI.downloadApp(id);
      if (data.download_url) {
        window.open(data.download_url, '_blank');
      }
      setDownloadMsg('Download started!');
      setApp((prev) => prev ? { ...prev, downloads_count: (prev.downloads_count || 0) + 1 } : prev);
    } catch (err) {
      setDownloadMsg(err.response?.data?.error || 'Download failed. Please try again.');
    } finally {
      setDownloading(false);
    }
  };

  const handleReview = async (e) => {
    e.preventDefault();
    setReviewError('');
    setReviewSuccess('');
    try {
      await marketplaceAPI.createReview({ app: Number(id), ...reviewForm });
      setReviewSuccess('Review submitted!');
      const { data } = await marketplaceAPI.getApp(id);
      setApp(data);
      setReviewForm({ rating: 5, comment: '' });
    } catch (err) {
      setReviewError(err.response?.data?.non_field_errors?.[0] || 'Failed to submit review.');
    }
  };

  const formatSize = (bytes) => {
    if (!bytes) return '—';
    if (bytes >= 1_000_000) return `${(bytes / 1_000_000).toFixed(1)} MB`;
    return `${(bytes / 1_000).toFixed(0)} KB`;
  };

  if (loading) return <div className="loading-fullscreen"><div className="spinner"></div></div>;
  if (!app) return null;

  const userHasReviewed = app.reviews?.some((r) => r.user?.id === user?.id);

  return (
    <div className="page-app-detail">
      {/* Header */}
      <div className="app-detail-header">
        <div className="app-detail-hero">
          <div className="app-detail-icon">
            {app.icon
              ? <img src={app.icon} alt={app.name} />
              : <div className="icon-placeholder-lg">{app.name?.charAt(0)}</div>
            }
          </div>
          <div className="app-detail-info">
            <h1 className="app-detail-name">{app.name}</h1>
            <p className="app-detail-developer">
              by <Link to={`/apps?search=${app.developer?.username}`}>{app.developer?.username}</Link>
            </p>
            <div className="app-detail-badges">
              {app.category && <span className="badge badge-category">{app.category.name}</span>}
              <span className={`badge ${app.is_free ? 'badge-free' : 'badge-paid'}`}>
                {app.is_free ? 'FREE' : `TZS ${Number(app.price).toLocaleString()}`}
              </span>
              <span className="badge badge-version">v{app.version}</span>
            </div>
            <div className="app-detail-stats">
              {app.average_rating && (
                <div className="stat-chip">
                  <StarRating value={app.average_rating} size="sm" />
                  <span>{app.average_rating} ({app.review_count} reviews)</span>
                </div>
              )}
              <div className="stat-chip">📥 {(app.downloads_count || 0).toLocaleString()} downloads</div>
              <div className="stat-chip">👁 {(app.views_count || 0).toLocaleString()} views</div>
            </div>

            {/* Download Button */}
            <div className="download-section">
              <button
                className={`btn btn-primary btn-lg ${!canDownload() ? 'btn-locked' : ''}`}
                onClick={handleDownload}
                disabled={downloading}
              >
                {downloading ? 'Preparing…' : canDownload() ? '⬇ Download' : isAuthenticated ? '🔒 Subscribe to Download' : '🔒 Login to Download'}
              </button>
              {!isAuthenticated && <p className="download-hint">Login required to download</p>}
              {isExternal && !hasActiveSubscription && !app.is_free && (
                <p className="download-hint">
                  External users need a <Link to="/subscription">subscription</Link> for paid apps.
                </p>
              )}
              {downloadMsg && <p className={`download-msg ${downloadMsg.includes('failed') ? 'error' : 'success'}`}>{downloadMsg}</p>}
            </div>
          </div>
        </div>
      </div>

      {/* Screenshots */}
      {app.screenshots?.length > 0 && (
        <div className="screenshots-section">
          <div className="screenshots-scroll">
            {app.screenshots.map((s) => (
              <img key={s.id} src={s.image} alt={s.caption || 'Screenshot'} className="screenshot-thumb"
                onClick={() => setSelectedImg(s.image)} />
            ))}
          </div>
        </div>
      )}

      {/* Modal */}
      {selectedImg && (
        <div className="img-modal" onClick={() => setSelectedImg(null)}>
          <img src={selectedImg} alt="Screenshot" />
        </div>
      )}

      {/* Tabs */}
      <div className="app-tabs">
        {['description', 'reviews', 'versions'].map((t) => (
          <button key={t} className={`tab-btn ${tab === t ? 'active' : ''}`} onClick={() => setTab(t)}>
            {t.charAt(0).toUpperCase() + t.slice(1)}
          </button>
        ))}
      </div>

      <div className="app-tabs-content">
        {tab === 'description' && (
          <div className="tab-description">
            <p className="app-full-desc">{app.description}</p>
            <div className="app-info-grid">
              <InfoRow label="Version" value={app.version} />
              <InfoRow label="Size" value={formatSize(app.size_bytes)} />
              <InfoRow label="Category" value={app.category?.name} />
              <InfoRow label="Min OS" value={app.min_os_version} />
              <InfoRow label="Updated" value={new Date(app.updated_at).toLocaleDateString()} />
              <InfoRow label="Downloads" value={(app.downloads_count || 0).toLocaleString()} />
            </div>
            {app.tag_list?.length > 0 && (
              <div className="app-tags">
                {app.tag_list.map((tag) => <span key={tag} className="tag-chip">{tag}</span>)}
              </div>
            )}
          </div>
        )}

        {tab === 'reviews' && (
          <div className="tab-reviews">
            {isAuthenticated && !userHasReviewed && (
              <form className="review-form" onSubmit={handleReview}>
                <h4>Write a Review</h4>
                <StarRating value={reviewForm.rating} interactive onChange={(v) => setReviewForm((p) => ({ ...p, rating: v }))} size="lg" />
                <textarea className="review-textarea" placeholder="Share your experience…" value={reviewForm.comment}
                  onChange={(e) => setReviewForm((p) => ({ ...p, comment: e.target.value }))} />
                {reviewError && <p className="error-msg">{reviewError}</p>}
                {reviewSuccess && <p className="success-msg">{reviewSuccess}</p>}
                <button type="submit" className="btn btn-primary">Submit Review</button>
              </form>
            )}

            {app.reviews?.length === 0 && <p className="no-reviews">No reviews yet. Be the first!</p>}

            {app.reviews?.map((r) => (
              <div key={r.id} className="review-card">
                <div className="review-header">
                  <div className="reviewer-avatar">{r.user?.username?.charAt(0).toUpperCase()}</div>
                  <div className="reviewer-info">
                    <span className="reviewer-name">{r.user?.full_name || r.user?.username}</span>
                    {r.is_verified_purchase && <span className="verified-badge">✓ Verified</span>}
                    <span className="review-date">{new Date(r.created_at).toLocaleDateString()}</span>
                  </div>
                  <StarRating value={r.rating} size="sm" />
                </div>
                {r.comment && <p className="review-comment">{r.comment}</p>}
              </div>
            ))}
          </div>
        )}

        {tab === 'versions' && (
          <div className="tab-versions">
            {app.versions?.length === 0 && <p className="no-versions">No version history available.</p>}
            {app.versions?.map((v) => (
              <div key={v.id} className={`version-card ${v.is_current ? 'version-current' : ''}`}>
                <div className="version-header">
                  <span className="version-number">v{v.version_number}</span>
                  {v.is_current && <span className="current-badge">Current</span>}
                  <span className="version-date">{new Date(v.created_at).toLocaleDateString()}</span>
                </div>
                {v.changelog && <p className="version-changelog">{v.changelog}</p>}
              </div>
            ))}
          </div>
        )}
      </div>

      {/* Admin Actions */}
      {isAdmin && app.status === 'pending' && (
        <div className="admin-actions">
          <h4>Admin Actions</h4>
          <button className="btn btn-success" onClick={async () => {
            await marketplaceAPI.approveApp(id);
            setApp((p) => p ? { ...p, status: 'approved' } : p);
          }}>✓ Approve</button>
          <button className="btn btn-danger" onClick={async () => {
            const reason = prompt('Reason for rejection:');
            if (reason !== null) {
              await marketplaceAPI.rejectApp(id, reason);
              setApp((p) => p ? { ...p, status: 'rejected' } : p);
            }
          }}>✗ Reject</button>
        </div>
      )}
    </div>
  );
}
