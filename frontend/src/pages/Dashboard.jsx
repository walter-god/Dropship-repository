import React, { useState, useEffect } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import { useAuth } from '../context/AuthContext';
import { authAPI, marketplaceAPI, subscriptionsAPI } from '../api';

export default function Dashboard() {
  const { user, isAdmin, isExternal, hasActiveSubscription, refreshUser } = useAuth();
  const navigate = useNavigate();
  const [downloads, setDownloads] = useState([]);
  const [subscription, setSubscription] = useState(null);
  const [profileForm, setProfileForm] = useState({ first_name: '', last_name: '', bio: '' });
  const [pwForm, setPwForm] = useState({ old_password: '', new_password: '', confirm_new: '' });
  const [profileMsg, setProfileMsg] = useState('');
  const [pwMsg, setPwMsg] = useState('');
  const [activeTab, setActiveTab] = useState('overview');

  useEffect(() => {
    if (user) {
      setProfileForm({ first_name: user.first_name || '', last_name: user.last_name || '', bio: user.bio || '' });
    }
  }, [user]);

  useEffect(() => {
    marketplaceAPI.getApps({ ordering: '-created_at', page_size: 5 })
      .then(({ data }) => setDownloads(data.results || data))
      .catch(() => {});

    if (isExternal) {
      subscriptionsAPI.getMySubscriptions()
        .then(({ data }) => {
          const subs = data.results || data;
          const active = subs.find((s) => s.is_valid);
          setSubscription(active || subs[0] || null);
        })
        .catch(() => {});
    }
  }, [isExternal]);

  const handleProfileSave = async (e) => {
    e.preventDefault();
    setProfileMsg('');
    try {
      await authAPI.updateProfile(profileForm);
      await refreshUser();
      setProfileMsg('Profile updated successfully!');
    } catch {
      setProfileMsg('Failed to update profile.');
    }
  };

  const handlePasswordChange = async (e) => {
    e.preventDefault();
    setPwMsg('');
    if (pwForm.new_password !== pwForm.confirm_new) {
      setPwMsg('New passwords do not match.'); return;
    }
    try {
      await authAPI.changePassword({ old_password: pwForm.old_password, new_password: pwForm.new_password });
      setPwMsg('Password changed. Please log in again.');
      setPwForm({ old_password: '', new_password: '', confirm_new: '' });
    } catch (err) {
      setPwMsg(err.response?.data?.old_password?.[0] || 'Failed to change password.');
    }
  };

  return (
    <div className="page-dashboard">
      <div className="dashboard-header">
        <div className="dashboard-welcome">
          <div className="dashboard-avatar">
            {user?.profile_picture
              ? <img src={user.profile_picture} alt={user?.username} />
              : <span>{user?.username?.charAt(0).toUpperCase()}</span>
            }
          </div>
          <div>
            <h1>Welcome back, {user?.first_name || user?.username}!</h1>
            <p>
              <span className={`role-badge role-${user?.role}`}>{user?.role}</span>
              {user?.email}
            </p>
          </div>
        </div>
        {isAdmin && (
          <Link to="/admin" className="btn btn-primary">Go to Admin Panel →</Link>
        )}
      </div>

      {/* Stats Cards */}
      <div className="dashboard-stats">
        <div className="dash-stat-card">
          <span className="dash-stat-icon">📥</span>
          <div><span className="dash-stat-num">{downloads.length}</span><span className="dash-stat-label">Recent Downloads</span></div>
        </div>
        {isExternal && (
          <div className="dash-stat-card">
            <span className="dash-stat-icon">⭐</span>
            <div>
              <span className="dash-stat-num">{hasActiveSubscription ? 'Active' : 'None'}</span>
              <span className="dash-stat-label">Subscription</span>
            </div>
          </div>
        )}
        <div className="dash-stat-card">
          <span className="dash-stat-icon">👤</span>
          <div><span className="dash-stat-num">{user?.role}</span><span className="dash-stat-label">Account Type</span></div>
        </div>
      </div>

      {/* Tabs */}
      <div className="dashboard-tabs">
        {['overview', 'profile', 'password'].map((t) => (
          <button key={t} className={`tab-btn ${activeTab === t ? 'active' : ''}`} onClick={() => setActiveTab(t)}>
            {t.charAt(0).toUpperCase() + t.slice(1)}
          </button>
        ))}
      </div>

      <div className="dashboard-content">
        {activeTab === 'overview' && (
          <div>
            {/* Subscription Status */}
            {isExternal && (
              <div className="subscription-status-card">
                <h3>⭐ Subscription Status</h3>
                {subscription && subscription.is_valid ? (
                  <div className="sub-active">
                    <span className="sub-status-badge">Active</span>
                    <p>Plan: <strong>{subscription.plan?.name}</strong></p>
                    <p>Expires: {new Date(subscription.end_date).toLocaleDateString()}</p>
                    <p>Days remaining: <strong>{subscription.days_remaining}</strong></p>
                  </div>
                ) : (
                  <div className="sub-inactive">
                    <p>You don't have an active subscription.</p>
                    <Link to="/subscription" className="btn btn-primary btn-sm">View Plans</Link>
                  </div>
                )}
              </div>
            )}

            {/* Recent Activity */}
            <div className="recent-section">
              <h3>Recent Apps</h3>
              <div className="apps-grid apps-grid-sm">
                {downloads.map((app) => (
                  <div key={app.id} className="app-card-mini" onClick={() => navigate(`/apps/${app.id}`)}>
                    <div className="app-mini-icon">
                      {app.icon ? <img src={app.icon} alt={app.name} /> : <span>{app.name?.charAt(0)}</span>}
                    </div>
                    <div className="app-mini-info">
                      <span className="app-mini-name">{app.name}</span>
                      <span className="app-mini-cat">{app.category_name}</span>
                    </div>
                  </div>
                ))}
              </div>
            </div>
          </div>
        )}

        {activeTab === 'profile' && (
          <form className="settings-form" onSubmit={handleProfileSave}>
            <h3>Edit Profile</h3>
            <div className="form-row">
              <div className="form-group">
                <label className="form-label">First Name</label>
                <input className="input-field" value={profileForm.first_name}
                  onChange={(e) => setProfileForm((p) => ({ ...p, first_name: e.target.value }))} />
              </div>
              <div className="form-group">
                <label className="form-label">Last Name</label>
                <input className="input-field" value={profileForm.last_name}
                  onChange={(e) => setProfileForm((p) => ({ ...p, last_name: e.target.value }))} />
              </div>
            </div>
            <div className="form-group">
              <label className="form-label">Bio</label>
              <textarea className="input-field textarea-field" value={profileForm.bio}
                onChange={(e) => setProfileForm((p) => ({ ...p, bio: e.target.value }))}
                placeholder="Tell us about yourself…" rows={4} />
            </div>
            {profileMsg && <div className={`alert ${profileMsg.includes('success') ? 'alert-success' : 'alert-error'}`}>{profileMsg}</div>}
            <button type="submit" className="btn btn-primary">Save Changes</button>
          </form>
        )}

        {activeTab === 'password' && (
          <form className="settings-form" onSubmit={handlePasswordChange}>
            <h3>Change Password</h3>
            <div className="form-group">
              <label className="form-label">Current Password</label>
              <input type="password" className="input-field" value={pwForm.old_password}
                onChange={(e) => setPwForm((p) => ({ ...p, old_password: e.target.value }))} required />
            </div>
            <div className="form-group">
              <label className="form-label">New Password</label>
              <input type="password" className="input-field" value={pwForm.new_password}
                onChange={(e) => setPwForm((p) => ({ ...p, new_password: e.target.value }))} required />
            </div>
            <div className="form-group">
              <label className="form-label">Confirm New Password</label>
              <input type="password" className="input-field" value={pwForm.confirm_new}
                onChange={(e) => setPwForm((p) => ({ ...p, confirm_new: e.target.value }))} required />
            </div>
            {pwMsg && <div className={`alert ${pwMsg.includes('changed') ? 'alert-success' : 'alert-error'}`}>{pwMsg}</div>}
            <button type="submit" className="btn btn-primary">Change Password</button>
          </form>
        )}
      </div>
    </div>
  );
}
