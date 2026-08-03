import React, { useState } from 'react';
import { useQuery, useMutation } from '@tanstack/react-query';
import deployerAPI from '../api/deployer';
import Drawer from './Drawer';

const CONFIDENCE_ICON = { high: '✅', low: '⚠️', none: '❓' };

export default function DeployDrawer({ hostedApp, onClose, onDeployed }) {
  const detected = hostedApp.runtime_template?.id ?? '';
  const [runtimeId, setRuntimeId] = useState(detected);
  const [provisionDb, setProvisionDb] = useState(
    hostedApp.runtime_template?.needs_database ?? hostedApp.needs_database ?? false
  );
  const [memory, setMemory] = useState(hostedApp.memory_limit_mb || 512);
  const [cpu, setCpu] = useState(hostedApp.cpu_limit || 0.5);
  const [envVars, setEnvVars] = useState(
    Object.entries(hostedApp.env_vars || {}).map(([key, value]) => ({ key, value }))
  );
  const [advancedOpen, setAdvancedOpen] = useState(false);
  const [portOverride, setPortOverride] = useState('');
  const [error, setError] = useState('');

  const { data: templates = [] } = useQuery({
    queryKey: ['runtime-templates'],
    queryFn: () => deployerAPI.getRuntimeTemplates().then((r) => r.data),
  });

  const deployMutation = useMutation({
    mutationFn: (overrides) => deployerAPI.deploy(hostedApp.application, overrides),
    onSuccess: () => onDeployed(),
    onError: (err) => setError(
      err.response?.data?.error
      || Object.values(err.response?.data || {}).flat()[0]
      || 'Deploy failed.'
    ),
  });

  const addEnvVar = () => setEnvVars((prev) => [...prev, { key: '', value: '' }]);
  const updateEnvVar = (idx, field, value) =>
    setEnvVars((prev) => prev.map((v, i) => (i === idx ? { ...v, [field]: value } : v)));
  const removeEnvVar = (idx) => setEnvVars((prev) => prev.filter((_, i) => i !== idx));

  const handleDeploy = () => {
    setError('');
    const envObject = {};
    for (const { key, value } of envVars) {
      if (key.trim()) envObject[key.trim()] = value;
    }
    const overrides = {
      memory_limit_mb: memory,
      cpu_limit: cpu,
      env_vars: envObject,
    };
    if (runtimeId) overrides.runtime_template_id = Number(runtimeId);
    overrides.provision_database = provisionDb;
    if (portOverride) overrides.container_port = Number(portOverride);

    deployMutation.mutate(overrides);
  };

  const confidence = hostedApp.detection_confidence || (hostedApp.needs_dockerfile ? 'low' : 'high');

  return (
    <Drawer
      title={`Deploy ${hostedApp.application_name}`}
      onClose={onClose}
      footer={
        <button className="btn btn-primary btn-full" onClick={handleDeploy} disabled={deployMutation.isPending}>
          {deployMutation.isPending ? 'Deploying…' : '🚀 Deploy'}
        </button>
      }
    >
      {error && <div className="alert alert-error">{error}</div>}

      {/* Detection result */}
      <div className={`detection-banner detection-banner-${confidence}`}>
        <span className="detection-banner-icon">{CONFIDENCE_ICON[confidence] || '❓'}</span>
        <span>
          {hostedApp.runtime_template
            ? <>Detected: <strong>{hostedApp.runtime_template.display_name}</strong>. {hostedApp.detection_reason}</>
            : hostedApp.detection_reason || 'Runtime not yet detected — select one below or deploy to auto-detect.'
          }
        </span>
      </div>

      {/* Runtime override */}
      <div className="drawer-field-group">
        <label className="drawer-field-label">Runtime</label>
        <select className="select-field" style={{ width: '100%' }} value={runtimeId}
          onChange={(e) => {
            setRuntimeId(e.target.value);
            const t = templates.find((t) => String(t.id) === e.target.value);
            if (t) setProvisionDb(t.needs_database);
          }}>
          <option value="">Auto-detect</option>
          {templates.map((t) => (
            <option key={t.id} value={t.id}>{t.display_name}</option>
          ))}
        </select>
      </div>

      {/* Database checkbox */}
      <div className="drawer-field-group">
        <label className="drawer-checkbox-row">
          <input type="checkbox" checked={provisionDb} onChange={(e) => setProvisionDb(e.target.checked)} />
          Provision a Postgres database automatically
        </label>
      </div>

      {/* Resource sliders */}
      <div className="drawer-field-group">
        <div className="slider-row">
          <div className="slider-row-header"><span>Memory limit</span><span>{memory} MB</span></div>
          <input type="range" className="slider-input" min="128" max="4096" step="128"
            value={memory} onChange={(e) => setMemory(Number(e.target.value))} />
        </div>
        <div className="slider-row">
          <div className="slider-row-header"><span>CPU limit</span><span>{cpu.toFixed(1)} cores</span></div>
          <input type="range" className="slider-input" min="0.1" max="4" step="0.1"
            value={cpu} onChange={(e) => setCpu(Number(e.target.value))} />
        </div>
      </div>

      {/* Advanced (collapsible) */}
      <div className="collapsible-section">
        <div className="collapsible-header" onClick={() => setAdvancedOpen((o) => !o)}>
          <span>⚙️ Advanced</span>
          <span className={`collapsible-arrow ${advancedOpen ? 'open' : ''}`}>▶</span>
        </div>
        {advancedOpen && (
          <div className="collapsible-body">
            <div className="drawer-field-group">
              <label className="drawer-field-label">Environment variables</label>
              {envVars.map((v, idx) => (
                <div className="env-var-row" key={idx}>
                  <input placeholder="KEY" value={v.key} onChange={(e) => updateEnvVar(idx, 'key', e.target.value)} />
                  <input placeholder="value" value={v.value} onChange={(e) => updateEnvVar(idx, 'value', e.target.value)} />
                  <button className="env-var-remove" onClick={() => removeEnvVar(idx)}>✕</button>
                </div>
              ))}
              <button className="env-var-add-btn" onClick={addEnvVar}>+ Add variable</button>
            </div>

            {hostedApp.needs_dockerfile && (
              <div className="drawer-field-group">
                <label className="drawer-field-label">Container port override</label>
                <input type="number" className="input-field" placeholder="e.g. 8080"
                  value={portOverride} onChange={(e) => setPortOverride(e.target.value)} />
                <p className="form-hint" style={{ marginTop: 6 }}>
                  Required if this project's Dockerfile has no EXPOSE instruction.
                </p>
              </div>
            )}
          </div>
        )}
      </div>

      {/* Read-only developer notes */}
      <div className="drawer-field-group">
        <label className="drawer-field-label">Developer's deployment notes</label>
        <div className={`readonly-info-box ${!hostedApp.deployment_notes ? 'empty' : ''}`}>
          {hostedApp.deployment_notes || 'No notes provided.'}
        </div>
      </div>
      <div className="drawer-field-group">
        <label className="drawer-field-label">Demo credentials</label>
        <div className={`readonly-info-box ${!hostedApp.demo_credentials ? 'empty' : ''}`}>
          {hostedApp.demo_credentials || 'None provided.'}
        </div>
      </div>
    </Drawer>
  );
}
