import React, { useState } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import { useAuth } from '../context/AuthContext';

function PasswordStrength({ password }) {
  const checks = [
    { label: 'At least 8 characters', ok: password.length >= 8 },
    { label: 'Contains uppercase', ok: /[A-Z]/.test(password) },
    { label: 'Contains number', ok: /\d/.test(password) },
    { label: 'Contains special character', ok: /[^a-zA-Z0-9]/.test(password) },
  ];
  const strength = checks.filter((c) => c.ok).length;
  const labels = ['', 'Weak', 'Fair', 'Good', 'Strong'];
  const colors = ['', '#f44336', '#ff9800', '#2196f3', '#00c853'];
  return (
    <div className="password-strength">
      <div className="strength-bar">
        {checks.map((_, i) => (
          <div key={i} className="strength-segment" style={{ background: i < strength ? colors[strength] : '#2a2a4a' }} />
        ))}
      </div>
      {password && <span className="strength-label" style={{ color: colors[strength] }}>{labels[strength]}</span>}
    </div>
  );
}

export default function Register() {
  const { register } = useAuth();
  const navigate = useNavigate();
  const [form, setForm] = useState({
    username: '', email: '', first_name: '', last_name: '',
    password: '', confirm_password: '', role: 'external', university_id: '',
  });
  const [showPass, setShowPass] = useState(false);
  const [error, setError] = useState('');
  const [fieldErrors, setFieldErrors] = useState({});
  const [loading, setLoading] = useState(false);
  const [agreed, setAgreed] = useState(false);

  const handleChange = (e) => {
    setForm((p) => ({ ...p, [e.target.name]: e.target.value }));
    setFieldErrors((p) => ({ ...p, [e.target.name]: '' }));
  };

  const handleSubmit = async (e) => {
    e.preventDefault();
    setError('');
    setFieldErrors({});

    if (form.password !== form.confirm_password) {
      setFieldErrors({ confirm_password: 'Passwords do not match.' });
      return;
    }
    if (form.role === 'internal' && !form.university_id.trim()) {
      setFieldErrors({ university_id: 'University ID is required for internal users.' });
      return;
    }
    if (!agreed) {
      setError('You must agree to the terms to register.');
      return;
    }

    setLoading(true);
    try {
      const payload = { ...form };
      delete payload.confirm_password;
      if (form.role !== 'internal') delete payload.university_id;
      await register(payload);
      navigate('/');
    } catch (err) {
      const data = err.response?.data;
      if (data && typeof data === 'object') {
        const firstMsg = Object.values(data).flat()[0];
        setError(typeof firstMsg === 'string' ? firstMsg : 'Registration failed. Please check your details.');
        setFieldErrors(data);
      } else {
        setError('Registration failed. Please try again.');
      }
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="auth-page">
      <div className="auth-brand">
        <div className="auth-brand-content">
          <div className="auth-brand-logo">🎓</div>
          <h1>Join UDOM e-Store</h1>
          <p>Create your account and access hundreds of university-built applications.</p>
          <div className="auth-brand-roles">
            <div className={`role-info ${form.role === 'internal' ? 'role-info-active' : ''}`}>
              <h4>🏛️ Internal (Students/Staff)</h4>
              <p>Free access to all campus applications with your university ID.</p>
            </div>
            <div className={`role-info ${form.role === 'external' ? 'role-info-active' : ''}`}>
              <h4>🌍 External Users</h4>
              <p>Subscribe to access premium applications and PaaS solutions.</p>
            </div>
          </div>
        </div>
      </div>

      <div className="auth-form-panel">
        <div className="auth-form-card auth-form-card-wide">
          <h2 className="auth-title">Create Account</h2>
          <p className="auth-subtitle">Join the UDOM community marketplace</p>

          {error && <div className="alert alert-error">{error}</div>}

          <form onSubmit={handleSubmit} className="auth-form">
            {/* Role Selection */}
            <div className="role-selector">
              <label className={`role-option ${form.role === 'internal' ? 'selected' : ''}`}>
                <input type="radio" name="role" value="internal" checked={form.role === 'internal'} onChange={handleChange} />
                🏛️ Internal (UDOM student/staff)
              </label>
              <label className={`role-option ${form.role === 'external' ? 'selected' : ''}`}>
                <input type="radio" name="role" value="external" checked={form.role === 'external'} onChange={handleChange} />
                🌍 External User
              </label>
            </div>

            {form.role === 'external' && (
              <div className="alert alert-info">
                External users can browse all apps for free, but need a subscription to download paid content.
              </div>
            )}

            <div className="form-row">
              <div className="form-group">
                <label className="form-label">First Name</label>
                <input type="text" name="first_name" value={form.first_name} onChange={handleChange}
                  className="input-field" placeholder="John" />
              </div>
              <div className="form-group">
                <label className="form-label">Last Name</label>
                <input type="text" name="last_name" value={form.last_name} onChange={handleChange}
                  className="input-field" placeholder="Doe" />
              </div>
            </div>

            <div className="form-group">
              <label className="form-label">Username *</label>
              <input type="text" name="username" value={form.username} onChange={handleChange}
                className={`input-field ${fieldErrors.username ? 'input-error' : ''}`} placeholder="johndoe" required />
              {fieldErrors.username && <span className="field-error">{fieldErrors.username}</span>}
            </div>

            <div className="form-group">
              <label className="form-label">Email *</label>
              <input type="email" name="email" value={form.email} onChange={handleChange}
                className={`input-field ${fieldErrors.email ? 'input-error' : ''}`} placeholder="john@udom.ac.tz" required />
              {fieldErrors.email && <span className="field-error">{fieldErrors.email}</span>}
            </div>

            {form.role === 'internal' && (
              <div className="form-group">
                <label className="form-label">University ID *</label>
                <input type="text" name="university_id" value={form.university_id} onChange={handleChange}
                  className={`input-field ${fieldErrors.university_id ? 'input-error' : ''}`} placeholder="T/UDOM/2024/001" />
                {fieldErrors.university_id && <span className="field-error">{fieldErrors.university_id}</span>}
              </div>
            )}

            <div className="form-group">
              <label className="form-label">Password *</label>
              <div className="input-with-icon">
                <input type={showPass ? 'text' : 'password'} name="password" value={form.password}
                  onChange={handleChange} className="input-field" placeholder="Min. 8 characters" required />
                <button type="button" className="input-icon-btn" onClick={() => setShowPass(!showPass)}>
                  {showPass ? '🙈' : '👁'}
                </button>
              </div>
              <PasswordStrength password={form.password} />
            </div>

            <div className="form-group">
              <label className="form-label">Confirm Password *</label>
              <input type="password" name="confirm_password" value={form.confirm_password}
                onChange={handleChange} className={`input-field ${fieldErrors.confirm_password ? 'input-error' : ''}`}
                placeholder="Repeat password" required />
              {fieldErrors.confirm_password && <span className="field-error">{fieldErrors.confirm_password}</span>}
            </div>

            <label className="checkbox-label">
              <input type="checkbox" checked={agreed} onChange={(e) => setAgreed(e.target.checked)} />
              I agree to the <a href="#terms">Terms of Use</a> and <a href="#privacy">Privacy Policy</a>
            </label>

            <button type="submit" className="btn btn-primary btn-full" disabled={loading}>
              {loading ? 'Creating account…' : 'Create Account'}
            </button>
          </form>

          <div className="auth-divider"><span>or</span></div>
          <p className="auth-switch">Already have an account? <Link to="/login">Sign in</Link></p>
        </div>
      </div>
    </div>
  );
}
