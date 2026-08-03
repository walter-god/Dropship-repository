import React, { useState, useRef } from 'react';
import { useNavigate, Link } from 'react-router-dom';
import { marketplaceAPI } from '../api';

const CONFIDENCE_META = {
  high: { icon: '✅', label: 'Recognized', cls: 'high' },
  low: { icon: '⚠️', label: 'Needs a Dockerfile', cls: 'low' },
  none: { icon: '❓', label: 'Not recognized', cls: 'none' },
};

// A short worked example per unsupported-but-detected language, shown inline
// so a student isn't left guessing what a "Dockerfile" even looks like.
// The full versions with explanations live on DockerfileHelpPage.
const WORKED_EXAMPLES = {
  'java-maven': `FROM eclipse-temurin:21-jre-alpine\nWORKDIR /app\nCOPY target/*.jar app.jar\nEXPOSE 8080\nCMD ["java", "-jar", "app.jar"]`,
  'java-gradle': `FROM eclipse-temurin:21-jre-alpine\nWORKDIR /app\nCOPY build/libs/*.jar app.jar\nEXPOSE 8080\nCMD ["java", "-jar", "app.jar"]`,
  dotnet: `FROM mcr.microsoft.com/dotnet/aspnet:8.0\nWORKDIR /app\nCOPY . .\nEXPOSE 8080\nCMD ["dotnet", "YourApp.dll"]`,
  go: `FROM golang:1.22-alpine AS build\nWORKDIR /app\nCOPY . .\nRUN go build -o server .\n\nFROM alpine\nCOPY --from=build /app/server /server\nEXPOSE 8080\nCMD ["/server"]`,
  'ruby-rails': `FROM ruby:3.3-slim\nWORKDIR /app\nCOPY . .\nRUN bundle install\nEXPOSE 3000\nCMD ["rails", "server", "-b", "0.0.0.0"]`,
  rust: `FROM rust:1.75 AS build\nWORKDIR /app\nCOPY . .\nRUN cargo build --release\n\nFROM debian:bookworm-slim\nCOPY --from=build /app/target/release/app /app\nEXPOSE 8080\nCMD ["/app"]`,
};

const LANGUAGE_NAMES = {
  'java-maven': 'Java (Maven)', 'java-gradle': 'Java (Gradle)', dotnet: '.NET',
  go: 'Go', 'ruby-rails': 'Ruby (Rails)', rust: 'Rust',
};

export default function UploadProjectPage() {
  const navigate = useNavigate();
  const fileInputRef = useRef(null);

  const [file, setFile] = useState(null);
  const [dragActive, setDragActive] = useState(false);
  const [detecting, setDetecting] = useState(false);
  const [detection, setDetection] = useState(null);
  const [detectError, setDetectError] = useState('');

  const [form, setForm] = useState({ name: '', short_description: '', description: '' });
  const [categories, setCategories] = useState([]);
  const [categoryId, setCategoryId] = useState('');
  const [submitError, setSubmitError] = useState('');
  const [submitting, setSubmitting] = useState(false);
  const [saved, setSaved] = useState(false);

  React.useEffect(() => {
    marketplaceAPI.getCategories().then(({ data }) => {
      const list = data.results || data;
      setCategories(list);
      if (list.length) setCategoryId(String(list[0].id));
    }).catch(() => {});
  }, []);

  const runDetection = async (selectedFile) => {
    setDetecting(true);
    setDetectError('');
    setDetection(null);
    try {
      const { data } = await marketplaceAPI.detectStack(selectedFile);
      setDetection(data);
    } catch (err) {
      setDetectError(err.response?.data?.error || 'Could not analyze this file.');
    } finally {
      setDetecting(false);
    }
  };

  const handleFile = (selectedFile) => {
    if (!selectedFile) return;
    setFile(selectedFile);
    runDetection(selectedFile);
  };

  const handleSubmit = async (mode) => {
    // mode: 'draft' | 'submit'. Both create the same underlying project —
    // there's no separate draft state in this system — but 'submit' is
    // blocked while a recognized-but-unsupported stack has no Dockerfile yet,
    // whereas 'draft' always lets the student save their progress.
    setSubmitError('');
    if (!form.name.trim()) { setSubmitError('Please give your project a name.'); return; }
    if (!file) { setSubmitError('Please select a source archive.'); return; }

    setSubmitting(true);
    try {
      const fd = new FormData();
      fd.append('name', form.name);
      fd.append('category', categoryId);
      fd.append('description', form.description || form.name);
      fd.append('short_description', form.short_description);
      fd.append('source_code', file);
      await marketplaceAPI.createApp(fd);
      setSaved(true);
    } catch (err) {
      const data = err.response?.data;
      setSubmitError(
        (data && typeof data === 'object' && Object.values(data).flat()[0]) || 'Upload failed.'
      );
    } finally {
      setSubmitting(false);
    }
  };

  const blockedBecauseNeedsDockerfile = detection?.needs_dockerfile
    && detection.runtime_key !== 'custom'; // 'custom' already ships its own Dockerfile

  if (saved) {
    return (
      <div className="page-upload-project">
        <div className="success-panel">
          <div className="success-icon">🎉</div>
          <h2>Project saved!</h2>
          <p>It will appear in your apps list, pending admin review and deployment.</p>
          <div className="success-actions">
            <Link to="/my-apps" className="btn btn-primary btn-lg">View My Apps</Link>
          </div>
        </div>
      </div>
    );
  }

  return (
    <div className="page-upload-project">
      <h1>Upload a Project</h1>
      <p style={{ color: 'var(--text-muted)', marginBottom: 28 }}>
        Upload your project's source code as a .zip — we'll detect your stack automatically.
      </p>

      {/* Dropzone */}
      <div
        className={`upload-dropzone ${dragActive ? 'drag-active' : ''}`}
        onClick={() => fileInputRef.current?.click()}
        onDragOver={(e) => { e.preventDefault(); setDragActive(true); }}
        onDragLeave={() => setDragActive(false)}
        onDrop={(e) => {
          e.preventDefault();
          setDragActive(false);
          handleFile(e.dataTransfer.files?.[0]);
        }}
      >
        <div className="upload-dropzone-icon">📦</div>
        <p>Drag and drop your project .zip here, or click to browse</p>
        {file && <p className="upload-file-name">{file.name}</p>}
        <input
          ref={fileInputRef} type="file" accept=".zip" style={{ display: 'none' }}
          onChange={(e) => handleFile(e.target.files?.[0])}
        />
      </div>

      {detecting && <p style={{ marginTop: 16, color: 'var(--text-muted)' }}>Analyzing your project…</p>}
      {detectError && <div className="alert alert-error" style={{ marginTop: 16 }}>{detectError}</div>}

      {/* Detection result */}
      {detection && (
        <div className={`detection-result-card ${CONFIDENCE_META[detection.confidence]?.cls || 'none'}`}>
          <div className="detection-result-title">
            <span>{CONFIDENCE_META[detection.confidence]?.icon}</span>
            {detection.confidence === 'high' && (
              <span>Detected: {detection.runtime_key === 'custom' ? 'Custom (Dockerfile found)' : detection.runtime_key}</span>
            )}
            {detection.confidence === 'low' && (
              <span>Detected: {LANGUAGE_NAMES[detection.runtime_key] || detection.runtime_key}</span>
            )}
            {detection.confidence === 'none' && <span>Stack not recognized</span>}
          </div>
          <div className="detection-result-body">
            {detection.confidence === 'high' && (
              <>Your app can be deployed automatically. {detection.reason}</>
            )}
            {detection.confidence === 'low' && (
              <>
                Your stack needs a Dockerfile in your project root so we can run it.
                {WORKED_EXAMPLES[detection.runtime_key] && (
                  <div className="detection-worked-example">
                    <pre>{WORKED_EXAMPLES[detection.runtime_key]}</pre>
                  </div>
                )}
                <Link to="/help/dockerfile" className="detection-help-link">
                  📖 See the full Dockerfile guide →
                </Link>
              </>
            )}
            {detection.confidence === 'none' && (
              <>
                We couldn't recognize this project's structure. Add a <code>Dockerfile</code> to
                your project root, or check the <Link to="/help/dockerfile" className="detection-help-link" style={{ marginTop: 0 }}>Dockerfile guide</Link> for your stack.
              </>
            )}
          </div>
        </div>
      )}

      {/* Project details */}
      <div className="form-group" style={{ marginTop: 28 }}>
        <label className="form-label">Project Name *</label>
        <input className="input-field" value={form.name}
          onChange={(e) => setForm((p) => ({ ...p, name: e.target.value }))} placeholder="My Project" />
      </div>

      <div className="form-group">
        <label className="form-label">Category</label>
        <select className="select-field" style={{ width: '100%' }} value={categoryId}
          onChange={(e) => setCategoryId(e.target.value)}>
          {categories.map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}
        </select>
      </div>

      <div className="form-group">
        <label className="form-label">Short Description</label>
        <input className="input-field" value={form.short_description}
          onChange={(e) => setForm((p) => ({ ...p, short_description: e.target.value }))}
          placeholder="One line about your project" />
      </div>

      <div className="form-group">
        <label className="form-label">Description</label>
        <textarea className="input-field textarea-field" rows={4} value={form.description}
          onChange={(e) => setForm((p) => ({ ...p, description: e.target.value }))}
          placeholder="What does your project do?" />
      </div>

      {submitError && <div className="alert alert-error">{submitError}</div>}

      <div className="form-actions">
        <button className="btn btn-outline" disabled={submitting} onClick={() => handleSubmit('draft')}>
          {submitting ? 'Saving…' : 'Save as Draft'}
        </button>
        <button
          className="btn btn-primary"
          disabled={submitting || blockedBecauseNeedsDockerfile}
          title={blockedBecauseNeedsDockerfile ? 'Add a Dockerfile and re-upload before submitting.' : ''}
          onClick={() => handleSubmit('submit')}
        >
          {submitting ? 'Submitting…' : 'Submit for Review'}
        </button>
      </div>
      {blockedBecauseNeedsDockerfile && (
        <p className="form-hint" style={{ marginTop: 8 }}>
          Submission is blocked until you add a Dockerfile and re-upload — but you can still save
          your progress as a draft.
        </p>
      )}
    </div>
  );
}
