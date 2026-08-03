import React from 'react';
import { BrowserRouter, Routes, Route } from 'react-router-dom';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { AuthProvider } from './context/AuthContext';
import Navbar from './components/Navbar';
import Footer from './components/Footer';
import ProtectedRoute from './components/ProtectedRoute';

import Home from './pages/Home';
import AppList from './pages/AppList';
import AppDetail from './pages/AppDetail';
import CategoryPage from './pages/CategoryPage';
import Login from './pages/Login';
import Register from './pages/Register';
import Dashboard from './pages/Dashboard';
import AdminPanel from './pages/AdminPanel';
import AdminHostedAppsPage from './pages/AdminHostedAppsPage';
import SubscriptionPage from './pages/SubscriptionPage';
import MyApps from './pages/MyApps';
import UploadProjectPage from './pages/UploadProjectPage';
import DockerfileHelpPage from './pages/DockerfileHelpPage';

// A single shared client so admin pages that both touch hosted-app data
// (the table and the log modal) invalidate each other's cache correctly.
const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      refetchOnWindowFocus: false,
      retry: 1,
    },
  },
});

export default function App() {
  return (
    <QueryClientProvider client={queryClient}>
      <BrowserRouter>
        <AuthProvider>
          <div className="app-shell">
            <Navbar />
            <main className="main-content">
              <Routes>
                <Route path="/" element={<Home />} />
                <Route path="/apps" element={<AppList />} />
                <Route path="/apps/:id" element={<AppDetail />} />
                <Route path="/category/:slug" element={<CategoryPage />} />
                <Route path="/subscription" element={<SubscriptionPage />} />
                <Route path="/login" element={<Login />} />
                <Route path="/register" element={<Register />} />
                <Route path="/dashboard" element={
                  <ProtectedRoute><Dashboard /></ProtectedRoute>
                } />
                <Route path="/admin" element={
                  <ProtectedRoute requiredRole="admin"><AdminPanel /></ProtectedRoute>
                } />
                <Route path="/admin/hosted-apps" element={
                  <ProtectedRoute requiredRole="admin"><AdminHostedAppsPage /></ProtectedRoute>
                } />
                <Route path="/my-apps" element={
                  <ProtectedRoute><MyApps /></ProtectedRoute>
                } />
                <Route path="/upload-project" element={
                  <ProtectedRoute><UploadProjectPage /></ProtectedRoute>
                } />
                <Route path="/help/dockerfile" element={<DockerfileHelpPage />} />
                <Route path="*" element={
                  <div className="not-found">
                    <h1>404</h1>
                    <p>Page not found</p>
                    <a href="/" className="btn btn-primary">Go Home</a>
                  </div>
                } />
              </Routes>
            </main>
            <Footer />
          </div>
        </AuthProvider>
      </BrowserRouter>
    </QueryClientProvider>
  );
}
