import React, { useState, useEffect } from 'react';
import { useNavigate, Link } from 'react-router-dom';
import { useAuth } from '../context/AuthContext';
import { subscriptionsAPI, paymentsAPI } from '../api';

function PlanCard({ plan, selected, onSelect, recommended }) {
  return (
    <div className={`plan-card ${selected ? 'plan-card-selected' : ''} ${recommended ? 'plan-card-recommended' : ''}`}
      onClick={() => onSelect(plan)}>
      {recommended && <div className="plan-badge">⭐ Best Value</div>}
      <h3 className="plan-name">{plan.name}</h3>
      <div className="plan-price">
        <span className="plan-amount">TZS {Number(plan.price).toLocaleString()}</span>
        <span className="plan-period">/ {plan.duration_days} days</span>
      </div>
      <p className="plan-desc">{plan.description}</p>
      <ul className="plan-features">
        {Object.entries(plan.features || {}).map(([key, val]) => (
          <li key={key} className={val ? 'feature-yes' : 'feature-no'}>
            {val ? '✓' : '✗'} {key.replace(/_/g, ' ')}
          </li>
        ))}
      </ul>
      <div className={`plan-select-indicator ${selected ? 'selected' : ''}`}>
        {selected ? '● Selected' : 'Select Plan'}
      </div>
    </div>
  );
}

export default function SubscriptionPage() {
  const { isAuthenticated, isExternal, hasActiveSubscription, refreshUser } = useAuth();
  const navigate = useNavigate();
  const [plans, setPlans] = useState([]);
  const [mySubscription, setMySubscription] = useState(null);
  const [selectedPlan, setSelectedPlan] = useState(null);
  const [paymentMethod, setPaymentMethod] = useState('mobile_money');
  const [phone, setPhone] = useState('');
  const [loading, setLoading] = useState(true);
  const [submitting, setSubmitting] = useState(false);
  const [message, setMessage] = useState('');
  const [error, setError] = useState('');
  const [step, setStep] = useState('plans'); // plans | payment | success

  useEffect(() => {
    async function load() {
      try {
        const [plansRes] = await Promise.all([subscriptionsAPI.getPlans()]);
        const p = plansRes.data.results || plansRes.data;
        setPlans(p);
        if (p.length > 1) setSelectedPlan(p[1]); // default to middle plan

        if (isAuthenticated) {
          const subRes = await subscriptionsAPI.getMySubscriptions();
          const subs = subRes.data.results || subRes.data;
          const active = subs.find((s) => s.is_valid);
          setMySubscription(active || null);
        }
      } catch {
        setError('Failed to load subscription plans.');
      } finally {
        setLoading(false);
      }
    }
    load();
  }, [isAuthenticated]);

  const handleSubscribe = async () => {
    if (!isAuthenticated) { navigate('/login'); return; }
    if (!selectedPlan) { setError('Please select a plan.'); return; }
    setSubmitting(true);
    setError('');
    try {
      const { data } = await subscriptionsAPI.subscribe({
        plan_id: selectedPlan.id,
        payment_method: paymentMethod,
        auto_renew: false,
      });
      // Initiate payment
      await paymentsAPI.initiatePayment({
        subscription_id: data.subscription.id,
        payment_method: paymentMethod,
        phone_number: phone,
      });
      setStep('success');
      setMessage(`Your subscription has been initiated! Transaction ID: ${data.payment.transaction_id}. Complete payment via ${paymentMethod.replace('_', ' ')} to activate.`);
      await refreshUser();
    } catch (err) {
      setError(err.response?.data?.detail || err.response?.data?.non_field_errors?.[0] || 'Subscription failed. Please try again.');
    } finally {
      setSubmitting(false);
    }
  };

  if (loading) return <div className="loading-fullscreen"><div className="spinner"></div></div>;

  return (
    <div className="page-subscription">
      <div className="subscription-header">
        <h1>Unlock Full Access</h1>
        <p>Subscribe to access all applications in the UDOM e-Store marketplace.</p>
      </div>

      {/* Current Subscription */}
      {mySubscription && hasActiveSubscription && (
        <div className="current-sub-card">
          <span className="sub-active-badge">✓ Active Subscription</span>
          <p>Plan: <strong>{mySubscription.plan?.name}</strong></p>
          <p>Expires: <strong>{new Date(mySubscription.end_date).toLocaleDateString()}</strong></p>
          <p>{mySubscription.days_remaining} days remaining</p>
          <p className="renew-hint">Want to extend? Select a plan below to renew.</p>
        </div>
      )}

      {step === 'success' ? (
        <div className="success-panel">
          <div className="success-icon">🎉</div>
          <h2>Subscription Initiated!</h2>
          <p>{message}</p>
          <p className="success-note">Your subscription will be activated once payment is confirmed.</p>
          <div className="success-actions">
            <Link to="/apps" className="btn btn-primary btn-lg">Browse Apps</Link>
            <Link to="/dashboard" className="btn btn-outline">Go to Dashboard</Link>
          </div>
        </div>
      ) : step === 'payment' ? (
        <div className="payment-panel">
          <h2>Complete Payment</h2>
          <div className="selected-plan-summary">
            <strong>{selectedPlan?.name}</strong> — TZS {Number(selectedPlan?.price).toLocaleString()}
          </div>

          <div className="payment-methods">
            <h3>Payment Method</h3>
            {['mobile_money', 'card', 'bank_transfer'].map((m) => (
              <label key={m} className={`payment-method-option ${paymentMethod === m ? 'selected' : ''}`}>
                <input type="radio" name="payment_method" value={m} checked={paymentMethod === m}
                  onChange={(e) => setPaymentMethod(e.target.value)} />
                <span className="method-icon">
                  {m === 'mobile_money' ? '📱' : m === 'card' ? '💳' : '🏦'}
                </span>
                <span>{m.replace('_', ' ').replace(/\b\w/g, (c) => c.toUpperCase())}</span>
              </label>
            ))}
          </div>

          {paymentMethod === 'mobile_money' && (
            <div className="form-group">
              <label className="form-label">Phone Number (M-Pesa / Tigo Pesa / Airtel)</label>
              <input type="tel" className="input-field" value={phone}
                onChange={(e) => setPhone(e.target.value)} placeholder="+255 7XX XXX XXX" />
            </div>
          )}

          {error && <div className="alert alert-error">{error}</div>}

          <div className="payment-actions">
            <button className="btn btn-outline" onClick={() => setStep('plans')}>← Back</button>
            <button className="btn btn-primary btn-lg" onClick={handleSubscribe} disabled={submitting}>
              {submitting ? 'Processing…' : `Pay TZS ${Number(selectedPlan?.price).toLocaleString()}`}
            </button>
          </div>
        </div>
      ) : (
        <>
          {error && <div className="alert alert-error">{error}</div>}

          {/* Plans Grid */}
          <div className="plans-grid">
            {plans.map((plan, idx) => (
              <PlanCard key={plan.id} plan={plan} selected={selectedPlan?.id === plan.id}
                onSelect={setSelectedPlan} recommended={idx === 1} />
            ))}
          </div>

          {/* Internal User Notice */}
          {!isExternal && isAuthenticated && (
            <div className="alert alert-info internal-notice">
              🏛️ As an internal UDOM user, you already have free access to all applications! Subscriptions are for external users only.
            </div>
          )}

          {!isAuthenticated && (
            <div className="alert alert-info">
              <Link to="/register">Create an account</Link> or <Link to="/login">login</Link> to subscribe.
            </div>
          )}

          {(isAuthenticated && (isExternal || !isExternal)) && (
            <div className="subscribe-action">
              <button className="btn btn-primary btn-xl" onClick={() => {
                if (!selectedPlan) { setError('Please select a plan first.'); return; }
                setStep('payment');
              }}>
                Continue with {selectedPlan?.name} Plan →
              </button>
            </div>
          )}
        </>
      )}

      {/* Feature Comparison */}
      <div className="feature-comparison">
        <h2>Why Subscribe?</h2>
        <div className="comparison-grid">
          <div className="comparison-col">
            <h4>🆓 Free (Internal)</h4>
            <ul>
              <li>✓ Browse all apps</li>
              <li>✓ Download any app</li>
              <li>✓ Full platform access</li>
              <li>✓ Submit applications</li>
              <li>✓ Rate &amp; review apps</li>
            </ul>
          </div>
          <div className="comparison-col comparison-col-premium">
            <h4>⭐ Subscribed (External)</h4>
            <ul>
              <li>✓ Browse all apps</li>
              <li>✓ Download any app</li>
              <li>✓ Full platform access</li>
              <li>✓ Rate &amp; review apps</li>
              <li>✓ Priority support</li>
              <li>✓ Early access (Annual)</li>
              <li>✓ API access (Annual)</li>
            </ul>
          </div>
        </div>
      </div>
    </div>
  );
}
