import React, { createContext, useContext, useState, useEffect, useCallback } from 'react';
import { authAPI, subscriptionsAPI } from '../api';

const AuthContext = createContext(null);

export function AuthProvider({ children }) {
  const [user, setUser] = useState(null);
  const [loading, setLoading] = useState(true);
  const [hasActiveSubscription, setHasActiveSubscription] = useState(false);

  const refreshUser = useCallback(async () => {
    try {
      const { data } = await authAPI.getProfile();
      setUser(data);
      if (data.role === 'external') {
        try {
          const subRes = await subscriptionsAPI.getMySubscriptions();
          const active = (subRes.data.results || subRes.data).some((s) => s.is_valid);
          setHasActiveSubscription(active);
        } catch {
          setHasActiveSubscription(false);
        }
      } else {
        setHasActiveSubscription(true);
      }
    } catch {
      setUser(null);
      setHasActiveSubscription(false);
    }
  }, []);

  useEffect(() => {
    const token = localStorage.getItem('access_token');
    if (token) {
      refreshUser().finally(() => setLoading(false));
    } else {
      setLoading(false);
    }
  }, [refreshUser]);

  const login = async (credentials) => {
    const { data } = await authAPI.login(credentials);
    localStorage.setItem('access_token', data.tokens.access);
    localStorage.setItem('refresh_token', data.tokens.refresh);
    setUser(data.user);
    if (data.user.role === 'external') {
      try {
        const subRes = await subscriptionsAPI.getMySubscriptions();
        const active = (subRes.data.results || subRes.data).some((s) => s.is_valid);
        setHasActiveSubscription(active);
      } catch {
        setHasActiveSubscription(false);
      }
    } else {
      setHasActiveSubscription(true);
    }
    return data;
  };

  const logout = async () => {
    try {
      const refresh = localStorage.getItem('refresh_token');
      if (refresh) await authAPI.logout(refresh);
    } catch {}
    localStorage.removeItem('access_token');
    localStorage.removeItem('refresh_token');
    setUser(null);
    setHasActiveSubscription(false);
  };

  const register = async (formData) => {
    const { data } = await authAPI.register(formData);
    localStorage.setItem('access_token', data.tokens.access);
    localStorage.setItem('refresh_token', data.tokens.refresh);
    setUser(data.user);
    setHasActiveSubscription(data.user.role !== 'external');
    return data;
  };

  const isAuthenticated = !!user;
  const isAdmin = user?.role === 'admin' || user?.is_staff || user?.is_superuser;
  const isInternal = user?.role === 'internal';
  const isExternal = user?.role === 'external';

  return (
    <AuthContext.Provider value={{
      user, loading, isAuthenticated, isAdmin, isInternal, isExternal,
      hasActiveSubscription, login, logout, register, refreshUser,
    }}>
      {children}
    </AuthContext.Provider>
  );
}

export function useAuth() {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error('useAuth must be used inside AuthProvider');
  return ctx;
}
