import React from 'react';
import { Link } from 'react-router-dom';

export default function Footer() {
  return (
    <footer className="footer">
      <div className="footer-inner">
        <div className="footer-brand">
          <span className="footer-logo">🎓 UDOM e-Store</span>
          <p className="footer-tagline">
            University of Dodoma Digital Marketplace — discover, distribute, and monetize software built by the UDOM community.
          </p>
        </div>

        <div className="footer-links">
          <div className="footer-col">
            <h5>Marketplace</h5>
            <Link to="/apps">Browse Apps</Link>
            <Link to="/apps?featured=true">Featured</Link>
            <Link to="/subscription">Pricing</Link>
          </div>
          <div className="footer-col">
            <h5>Account</h5>
            <Link to="/login">Login</Link>
            <Link to="/register">Register</Link>
            <Link to="/dashboard">Dashboard</Link>
          </div>
          <div className="footer-col">
            <h5>University</h5>
            <a href="https://www.udom.ac.tz" target="_blank" rel="noopener noreferrer">UDOM Website</a>
            <Link to="/apps?category=paas">PaaS Solutions</Link>
            <Link to="/my-apps">Submit an App</Link>
          </div>
        </div>
      </div>

      <div className="footer-bottom">
        <p>© {new Date().getFullYear()} University of Dodoma. All rights reserved.</p>
        <div className="footer-bottom-links">
          <a href="#privacy">Privacy Policy</a>
          <a href="#terms">Terms of Use</a>
          <a href="#contact">Contact</a>
        </div>
      </div>
    </footer>
  );
}
