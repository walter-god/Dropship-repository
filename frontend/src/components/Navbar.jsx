import React, { useState } from 'react';
import { Link, useNavigate, useLocation } from 'react-router-dom';
import { useAuth } from '../context/AuthContext';
import SearchBar from './SearchBar';

export default function Navbar() {
  const { user, isAuthenticated, isAdmin, logout } = useAuth();
  const navigate = useNavigate();
  const location = useLocation();
  const [menuOpen, setMenuOpen] = useState(false);
  const [dropdownOpen, setDropdownOpen] = useState(false);

  const handleLogout = async () => {
    await logout();
    navigate('/');
    setDropdownOpen(false);
  };

  const isActive = (path) => location.pathname === path || location.pathname.startsWith(path + '/');

  return (
    <nav className="navbar">
      <div className="navbar-inner">
        {/* Logo */}
        <Link to="/" className="navbar-logo">
          <span className="navbar-logo-icon">🎓</span>
          <span className="navbar-logo-text">
            <span className="logo-udom">UDOM</span>
            <span className="logo-store"> e-Store</span>
          </span>
        </Link>

        {/* Search */}
        <div className="navbar-search">
          <SearchBar placeholder="Search apps, tools, PaaS…" />
        </div>

        {/* Nav Links */}
        <div className={`navbar-links ${menuOpen ? 'navbar-links-open' : ''}`}>
          <Link to="/" className={`nav-link ${isActive('/') && location.pathname === '/' ? 'active' : ''}`}
            onClick={() => setMenuOpen(false)}>Home</Link>
          <Link to="/apps" className={`nav-link ${isActive('/apps') ? 'active' : ''}`}
            onClick={() => setMenuOpen(false)}>Apps</Link>
          <Link to="/apps?category=education" className="nav-link" onClick={() => setMenuOpen(false)}>Education</Link>
          <Link to="/subscription" className="nav-link" onClick={() => setMenuOpen(false)}>Pricing</Link>
          {isAdmin && (
            <Link to="/admin" className={`nav-link nav-link-admin ${isActive('/admin') ? 'active' : ''}`}
              onClick={() => setMenuOpen(false)}>Admin</Link>
          )}
        </div>

        {/* Auth */}
        <div className="navbar-auth">
          {isAuthenticated ? (
            <div className="user-menu" onMouseLeave={() => setDropdownOpen(false)}>
              <button className="user-avatar-btn" onClick={() => setDropdownOpen(!dropdownOpen)}>
                <div className="user-avatar">
                  {user?.profile_picture
                    ? <img src={user.profile_picture} alt={user.username} />
                    : <span>{user?.username?.charAt(0).toUpperCase()}</span>
                  }
                </div>
                <span className="user-name">{user?.first_name || user?.username}</span>
                <span className="dropdown-arrow">{dropdownOpen ? '▲' : '▼'}</span>
              </button>
              {dropdownOpen && (
                <div className="user-dropdown">
                  <div className="dropdown-header">
                    <span className="dropdown-username">{user?.username}</span>
                    <span className={`role-badge role-${user?.role}`}>{user?.role}</span>
                  </div>
                  <Link to="/dashboard" className="dropdown-item" onClick={() => setDropdownOpen(false)}>
                    👤 My Profile
                  </Link>
                  <Link to="/my-apps" className="dropdown-item" onClick={() => setDropdownOpen(false)}>
                    📦 My Apps
                  </Link>
                  {user?.role === 'external' && (
                    <Link to="/subscription" className="dropdown-item" onClick={() => setDropdownOpen(false)}>
                      ⭐ Subscription
                    </Link>
                  )}
                  {isAdmin && (
                    <Link to="/admin" className="dropdown-item" onClick={() => setDropdownOpen(false)}>
                      ⚙️ Admin Panel
                    </Link>
                  )}
                  <hr className="dropdown-divider" />
                  <button className="dropdown-item dropdown-logout" onClick={handleLogout}>
                    🚪 Logout
                  </button>
                </div>
              )}
            </div>
          ) : (
            <div className="auth-buttons">
              <Link to="/login" className="btn btn-outline btn-sm">Login</Link>
              <Link to="/register" className="btn btn-primary btn-sm">Sign Up</Link>
            </div>
          )}
        </div>

        {/* Mobile hamburger */}
        <button className="hamburger" onClick={() => setMenuOpen(!menuOpen)}>
          <span /><span /><span />
        </button>
      </div>
    </nav>
  );
}
