import React, { useState, useEffect, useCallback } from 'react';
import { useNavigate, Link } from 'react-router-dom';
import { useAuth } from '../context/AuthContext';
import { authAPI, marketplaceAPI, subscriptionsAPI, paymentsAPI } from '../api';

function StatsCard({ icon, label, value, color }) {
  return (
    <div className="stats-card" style={{ borderTop: `3px solid ${color}` }}>
      <span className="stats-card-icon">{icon}</span>
      <div><span className="stats-card-value">{value}</span><span className="stats-card-label">{label}</span></div>
    </div>
  );
}

const STATUS_COLORS = { pending: '#ff9800', approved: '#00c853', rejected: '#f44336' };
const PAYMENT_COLORS = { pending: '#ff9800', completed: '#00c853', failed: '#f44336', refunded: '#2196f3' };

export default function AdminPanel() {
  const { isAdmin } = useAuth();
  const navigate = useNavigate();
  const [tab, setTab] = useState('overview');
  const [users, setUsers] = useState([]);
  const [apps, setApps] = useState([]);
  const [subscriptions, setSubscriptions] = useState([]);
  const [payments, setPayments] = useState([]);
  const [stats, setStats] = useState({});
  const [loading, setLoading] = useState(false);
  const [userSearch, setUserSearch] = useState('');
  const [userRoleFilter, setUserRoleFilter] = useState('');

  useEffect(() => {
    if (!isAdmin) { navigate('/'); return; }
  }, [isAdmin, navigate]);

  const loadData = useCallback(async () => {
    setLoading(true);
    try {
      const [usersRes, appsRes, subsRes, paymentsRes] = await Promise.all([
        authAPI.getUsers({ page_size: 50 }),
        marketplaceAPI.getApps({ page_size: 50 }),
        subscriptionsAPI.getAllSubscriptions({ page_size: 50 }),
        paymentsAPI.getPayments({ page_size: 50 }),
      ]);
      const u = usersRes.data.results || usersRes.data;
      const a = appsRes.data.results || appsRes.data;
      const s = subsRes.data.results || subsRes.data;
      const p = paymentsRes.data.results || paymentsRes.data;
      setUsers(u);
      setApps(a);
      setSubscriptions(s);
      setPayments(p);
      setStats({
        totalUsers: usersRes.data.count || u.length,
        adminUsers: u.filter((x) => x.role === 'admin').length,
        internalUsers: u.filter((x) => x.role === 'internal').length,
        externalUsers: u.filter((x) => x.role === 'external').length,
        totalApps: appsRes.data.count || a.length,
        pendingApps: a.filter((x) => x.status === 'pending').length,
        activeSubscriptions: s.filter((x) => x.is_valid).length,
        totalPayments: paymentsRes.data.count || p.length,
        completedPayments: p.filter((x) => x.status === 'completed').length,
      });
    } catch (err) {
      console.error(err);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { loadData(); }, [loadData]);

  const filteredUsers = users.filter((u) => {
    const matchSearch = !userSearch || u.username.toLowerCase().includes(userSearch.toLowerCase()) ||
      u.email.toLowerCase().includes(userSearch.toLowerCase());
    const matchRole = !userRoleFilter || u.role === userRoleFilter;
    return matchSearch && matchRole;
  });

  const handleApprove = async (id) => {
    await marketplaceAPI.approveApp(id);
    loadData();
  };
  const handleReject = async (id) => {
    const reason = prompt('Reason for rejection:');
    if (reason !== null) { await marketplaceAPI.rejectApp(id, reason); loadData(); }
  };
  const handleDeactivate = async (id) => {
    await authAPI.deactivateUser(id);
    loadData();
  };
  const handleActivate = async (id) => {
    await authAPI.activateUser(id);
    loadData();
  };

  return (
    <div className="page-admin">
      <div className="admin-header">
        <h1>⚙️ Admin Panel</h1>
        <p className="admin-subtitle">Manage users, applications, subscriptions, and payments</p>
      </div>

      {/* Admin Tabs */}
      <div className="admin-tabs">
        {['overview', 'users', 'apps', 'subscriptions', 'payments'].map((t) => (
          <button key={t} className={`tab-btn ${tab === t ? 'active' : ''}`} onClick={() => setTab(t)}>
            {t === 'overview' && '📊 '}
            {t === 'users' && '👥 '}
            {t === 'apps' && '📦 '}
            {t === 'subscriptions' && '⭐ '}
            {t === 'payments' && '💳 '}
            {t.charAt(0).toUpperCase() + t.slice(1)}
          </button>
        ))}
        <Link to="/admin/hosted-apps" className="tab-btn">🚀 Hosted Apps</Link>
      </div>

      <div className="admin-content">
        {loading && <div className="loading-overlay"><div className="spinner"></div></div>}

        {/* Overview */}
        {tab === 'overview' && (
          <div>
            <div className="admin-stats-grid">
              <StatsCard icon="👥" label="Total Users" value={stats.totalUsers || 0} color="#2196f3" />
              <StatsCard icon="🏛️" label="Internal Users" value={stats.internalUsers || 0} color="#006633" />
              <StatsCard icon="🌍" label="External Users" value={stats.externalUsers || 0} color="#003366" />
              <StatsCard icon="📦" label="Total Apps" value={stats.totalApps || 0} color="#9c27b0" />
              <StatsCard icon="⏳" label="Pending Review" value={stats.pendingApps || 0} color="#ff9800" />
              <StatsCard icon="⭐" label="Active Subscriptions" value={stats.activeSubscriptions || 0} color="#00c853" />
              <StatsCard icon="💳" label="Total Payments" value={stats.totalPayments || 0} color="#f44336" />
              <StatsCard icon="✅" label="Completed Payments" value={stats.completedPayments || 0} color="#00c853" />
            </div>

            {stats.pendingApps > 0 && (
              <div className="alert alert-warning">
                ⚠️ {stats.pendingApps} app{stats.pendingApps > 1 ? 's' : ''} awaiting review.
                <button className="btn btn-sm btn-outline" style={{ marginLeft: 12 }} onClick={() => setTab('apps')}>
                  Review Now
                </button>
              </div>
            )}
          </div>
        )}

        {/* Users */}
        {tab === 'users' && (
          <div>
            <div className="admin-toolbar">
              <input className="input-field" placeholder="Search users…" value={userSearch}
                onChange={(e) => setUserSearch(e.target.value)} />
              <select className="select-field" value={userRoleFilter} onChange={(e) => setUserRoleFilter(e.target.value)}>
                <option value="">All Roles</option>
                <option value="admin">Admin</option>
                <option value="internal">Internal</option>
                <option value="external">External</option>
              </select>
            </div>
            <div className="admin-table-wrapper">
              <table className="admin-table">
                <thead>
                  <tr><th>User</th><th>Email</th><th>Role</th><th>Status</th><th>Joined</th><th>Actions</th></tr>
                </thead>
                <tbody>
                  {filteredUsers.map((u) => (
                    <tr key={u.id}>
                      <td><div className="user-cell"><div className="user-cell-avatar">{u.username?.charAt(0).toUpperCase()}</div><span>{u.username}</span></div></td>
                      <td>{u.email}</td>
                      <td><span className={`role-badge role-${u.role}`}>{u.role}</span></td>
                      <td>
                        <span className={`status-dot ${u.is_active ? 'status-active' : 'status-inactive'}`}>
                          {u.is_active ? 'Active' : 'Inactive'}
                        </span>
                      </td>
                      <td>{new Date(u.date_joined).toLocaleDateString()}</td>
                      <td>
                        {u.is_active
                          ? <button className="btn btn-sm btn-danger" onClick={() => handleDeactivate(u.id)}>Deactivate</button>
                          : <button className="btn btn-sm btn-success" onClick={() => handleActivate(u.id)}>Activate</button>
                        }
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        )}

        {/* Apps */}
        {tab === 'apps' && (
          <div className="admin-table-wrapper">
            <table className="admin-table">
              <thead>
                <tr><th>App</th><th>Developer</th><th>Category</th><th>Status</th><th>Downloads</th><th>Actions</th></tr>
              </thead>
              <tbody>
                {apps.map((app) => (
                  <tr key={app.id}>
                    <td>
                      <div className="app-cell">
                        <div className="app-cell-icon">{app.icon ? <img src={app.icon} alt="" /> : app.name?.charAt(0)}</div>
                        <div>
                          <span className="app-cell-name">{app.name}</span>
                          <span className="app-cell-ver">v{app.version}</span>
                        </div>
                      </div>
                    </td>
                    <td>{app.developer?.username}</td>
                    <td>{app.category_name || '—'}</td>
                    <td>
                      <span className="status-badge" style={{ color: STATUS_COLORS[app.status] }}>
                        ● {app.status}
                      </span>
                    </td>
                    <td>{(app.downloads_count || 0).toLocaleString()}</td>
                    <td className="actions-cell">
                      {app.status === 'pending' && (
                        <>
                          <button className="btn btn-sm btn-success" onClick={() => handleApprove(app.id)}>✓ Approve</button>
                          <button className="btn btn-sm btn-danger" onClick={() => handleReject(app.id)}>✗ Reject</button>
                        </>
                      )}
                      {app.status !== 'pending' && (
                        <span className="text-muted">—</span>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}

        {/* Subscriptions */}
        {tab === 'subscriptions' && (
          <div className="admin-table-wrapper">
            <table className="admin-table">
              <thead>
                <tr><th>User</th><th>Plan</th><th>Start</th><th>End</th><th>Status</th></tr>
              </thead>
              <tbody>
                {subscriptions.map((s) => (
                  <tr key={s.id}>
                    <td>{s.user?.username || '—'}</td>
                    <td>{s.plan?.name}</td>
                    <td>{new Date(s.start_date).toLocaleDateString()}</td>
                    <td>{new Date(s.end_date).toLocaleDateString()}</td>
                    <td>
                      <span className={`status-dot ${s.is_valid ? 'status-active' : 'status-inactive'}`}>
                        {s.is_valid ? 'Valid' : 'Expired'}
                      </span>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}

        {/* Payments */}
        {tab === 'payments' && (
          <div className="admin-table-wrapper">
            <table className="admin-table">
              <thead>
                <tr><th>Transaction ID</th><th>User</th><th>Amount</th><th>Method</th><th>Status</th><th>Date</th></tr>
              </thead>
              <tbody>
                {payments.map((p) => (
                  <tr key={p.id}>
                    <td><code className="txn-id">{p.transaction_id}</code></td>
                    <td>{p.username}</td>
                    <td>{p.currency} {Number(p.amount).toLocaleString()}</td>
                    <td>{p.method_display}</td>
                    <td>
                      <span className="status-badge" style={{ color: PAYMENT_COLORS[p.status] }}>
                        ● {p.status_display}
                      </span>
                    </td>
                    <td>{new Date(p.created_at).toLocaleDateString()}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </div>
  );
}
