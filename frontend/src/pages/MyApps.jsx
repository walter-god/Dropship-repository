import React, { useState, useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
import { marketplaceAPI } from '../api';
import { useAuth } from '../context/AuthContext';

const STATUS_LABELS = { pending: '⏳ Pending Review', approved: '✅ Approved', rejected: '❌ Rejected' };
const STATUS_COLORS = { pending: '#ff9800', approved: '#00c853', rejected: '#f44336' };

export default function MyApps() {
  const { isAuthenticated, isInternal, isAdmin } = useAuth();
  const navigate = useNavigate();
  const [apps, setApps] = useState([]);
  const [loading, setLoading] = useState(true);
  const [showForm, setShowForm] = useState(false);
  const [categories, setCategories] = useState([]);
  const [submitError, setSubmitError] = useState('');
  const [submitSuccess, setSubmitSuccess] = useState('');
  const [submitting, setSubmitting] = useState(false);
  const [form, setForm] = useState({
    name: '', category: '', description: '', short_description: '',
    version: '1.0.0', price: '0', min_os_version: '', tags: '',
  });
  const [appFile, setAppFile] = useState(null);
  const [iconFile, setIconFile] = useState(null);

  useEffect(() => {
    if (!isAuthenticated) { navigate('/login'); return; }
    if (!isInternal && !isAdmin) { navigate('/'); return; }
    marketplaceAPI.getMyApps()
      .then(({ data }) => setApps(data.results || data))
      .catch(() => {})
      .finally(() => setLoading(false));
    marketplaceAPI.getCategories()
      .then(({ data }) => setCategories(data.results || data))
      .catch(() => {});
  }, [isAuthenticated, isInternal, isAdmin, navigate]);

  const handleSubmit = async (e) => {
    e.preventDefault();
    setSubmitError('');
    setSubmitSuccess('');
    if (!appFile) { setSubmitError('Please select an app file.'); return; }
    setSubmitting(true);
    try {
      const fd = new FormData();
      Object.entries(form).forEach(([k, v]) => { if (v) fd.append(k, v); });
      fd.append('app_file', appFile);
      if (iconFile) fd.append('icon', iconFile);
      await marketplaceAPI.createApp(fd);
      setSubmitSuccess('App submitted successfully! It will be reviewed by an administrator.');
      setShowForm(false);
      setForm({ name: '', category: '', description: '', short_description: '', version: '1.0.0', price: '0', min_os_version: '', tags: '' });
      setAppFile(null);
      setIconFile(null);
      const { data } = await marketplaceAPI.getMyApps();
      setApps(data.results || data);
    } catch (err) {
      const d = err.response?.data;
      if (d && typeof d === 'object') {
        setSubmitError(Object.values(d).flat().join(' '));
      } else {
        setSubmitError('Submission failed. Please try again.');
      }
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div className="page-my-apps">
      <div className="my-apps-header">
        <div>
          <h1>My Applications</h1>
          <p>Manage and track your submitted apps</p>
        </div>
        <button className="btn btn-primary" onClick={() => setShowForm(!showForm)}>
          {showForm ? '✕ Cancel' : '+ Submit New App'}
        </button>
      </div>

      {/* Submit Form */}
      {showForm && (
        <div className="submit-app-form">
          <h3>Submit New Application</h3>
          {submitError && <div className="alert alert-error">{submitError}</div>}
          {submitSuccess && <div className="alert alert-success">{submitSuccess}</div>}
          <form onSubmit={handleSubmit}>
            <div className="form-row">
              <div className="form-group">
                <label className="form-label">App Name *</label>
                <input className="input-field" value={form.name} required
                  onChange={(e) => setForm((p) => ({ ...p, name: e.target.value }))} placeholder="My Application" />
              </div>
              <div className="form-group">
                <label className="form-label">Category *</label>
                <select className="select-field" value={form.category} required
                  onChange={(e) => setForm((p) => ({ ...p, category: e.target.value }))}>
                  <option value="">Select category</option>
                  {categories.map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}
                </select>
              </div>
            </div>

            <div className="form-group">
              <label className="form-label">Short Description</label>
              <input className="input-field" value={form.short_description} maxLength={300}
                onChange={(e) => setForm((p) => ({ ...p, short_description: e.target.value }))}
                placeholder="Brief one-line description…" />
            </div>

            <div className="form-group">
              <label className="form-label">Full Description *</label>
              <textarea className="input-field textarea-field" value={form.description} required rows={5}
                onChange={(e) => setForm((p) => ({ ...p, description: e.target.value }))}
                placeholder="Describe your application in detail…" />
            </div>

            <div className="form-row">
              <div className="form-group">
                <label className="form-label">Version</label>
                <input className="input-field" value={form.version}
                  onChange={(e) => setForm((p) => ({ ...p, version: e.target.value }))} placeholder="1.0.0" />
              </div>
              <div className="form-group">
                <label className="form-label">Price (TZS) — 0 for free</label>
                <input type="number" className="input-field" value={form.price} min="0"
                  onChange={(e) => setForm((p) => ({ ...p, price: e.target.value }))} />
              </div>
            </div>

            <div className="form-row">
              <div className="form-group">
                <label className="form-label">App File * (APK, ZIP, etc.)</label>
                <input type="file" className="input-field" onChange={(e) => setAppFile(e.target.files[0])} required />
              </div>
              <div className="form-group">
                <label className="form-label">App Icon (PNG, 512×512 recommended)</label>
                <input type="file" accept="image/*" className="input-field" onChange={(e) => setIconFile(e.target.files[0])} />
              </div>
            </div>

            <div className="form-group">
              <label className="form-label">Tags (comma-separated)</label>
              <input className="input-field" value={form.tags}
                onChange={(e) => setForm((p) => ({ ...p, tags: e.target.value }))}
                placeholder="education, tools, productivity" />
            </div>

            <div className="form-actions">
              <button type="submit" className="btn btn-primary" disabled={submitting}>
                {submitting ? 'Submitting…' : 'Submit for Review'}
              </button>
            </div>
          </form>
        </div>
      )}

      {/* App List */}
      {loading ? (
        <div className="loading-center"><div className="spinner"></div></div>
      ) : apps.length === 0 ? (
        <div className="empty-state">
          <span className="empty-icon">📦</span>
          <h3>No apps submitted yet</h3>
          <p>Submit your first application to the UDOM marketplace.</p>
          <button className="btn btn-primary" onClick={() => setShowForm(true)}>Submit an App</button>
        </div>
      ) : (
        <div className="my-apps-list">
          {apps.map((app) => (
            <div key={app.id} className="my-app-row" onClick={() => navigate(`/apps/${app.id}`)}>
              <div className="my-app-icon">
                {app.icon ? <img src={app.icon} alt={app.name} /> : <span>{app.name?.charAt(0)}</span>}
              </div>
              <div className="my-app-info">
                <h4>{app.name}</h4>
                <p>{app.short_description || app.category_name}</p>
                <div className="my-app-meta">
                  <span>v{app.version}</span>
                  <span>📥 {(app.downloads_count || 0).toLocaleString()}</span>
                  <span>📅 {new Date(app.created_at).toLocaleDateString()}</span>
                </div>
              </div>
              <div className="my-app-status">
                <span className="status-badge" style={{ color: STATUS_COLORS[app.status] }}>
                  {STATUS_LABELS[app.status]}
                </span>
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
