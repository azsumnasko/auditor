'use client';

import { useState, useEffect } from 'react';

type ConfigStatus = { configured: boolean; emailHint?: string } | null;

export default function ConfigPage() {
  const [status, setStatus] = useState<ConfigStatus>(null);
  const [saved, setSaved] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [form, setForm] = useState({
    JIRA_BASE_URL: '',
    JIRA_EMAIL: '',
    JIRA_TOKEN: '',
    JIRA_PROJECT_KEYS: '',
  });

  useEffect(() => {
    fetch('/api/config', { credentials: 'include' })
      .then((r) => {
        if (r.status === 401) {
          window.location.href = '/login?from=/';
          return null;
        }
        return r.json();
      })
      .then((data) => {
        if (data == null) return;
        setStatus(data);
        if (data?.JIRA_BASE_URL || data?.JIRA_PROJECT_KEYS) {
          setForm((f) => ({
            ...f,
            JIRA_BASE_URL: data.JIRA_BASE_URL ?? f.JIRA_BASE_URL,
            JIRA_PROJECT_KEYS: data.JIRA_PROJECT_KEYS ?? f.JIRA_PROJECT_KEYS,
          }));
        }
      })
      .catch(() => setStatus({ configured: false }));
  }, []);

  const validate = (): string | null => {
    const url = form.JIRA_BASE_URL.trim();
    if (!url) return 'JIRA Base URL is required';
    try {
      new URL(url.startsWith('http') ? url : `https://${url}`);
    } catch {
      return 'JIRA Base URL must be a valid URL (e.g. https://company.atlassian.net)';
    }
    if (!form.JIRA_EMAIL.trim()) return 'JIRA Email is required';
    if (!form.JIRA_TOKEN.trim()) return 'JIRA Token is required';
    if (!form.JIRA_PROJECT_KEYS.trim()) return 'At least one project key is required';
    return null;
  };

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    const err = validate();
    if (err) {
      setError(err);
      return;
    }
    setError(null);
    setSaved(false);
    setLoading(true);
    try {
      const res = await fetch('/api/config', {
        method: 'POST',
        credentials: 'include',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          JIRA_BASE_URL: form.JIRA_BASE_URL.trim(),
          JIRA_EMAIL: form.JIRA_EMAIL.trim(),
          JIRA_TOKEN: form.JIRA_TOKEN.trim(),
          JIRA_PROJECT_KEYS: form.JIRA_PROJECT_KEYS.trim(),
        }),
      });
      if (!res.ok) {
        const data = await res.json().catch(() => ({}));
        throw new Error(data.error || (typeof data === 'string' ? data : `Save failed: ${res.status}`));
      }
      setSaved(true);
      setStatus({ configured: true });
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Save failed');
    } finally {
      setLoading(false);
    }
  };

  return (
    <main>
      <nav style={{ marginBottom: '1rem' }}>
        <a href="/">Config</a> | <a href="/dashboard">Dashboard</a> |{' '}
        <button type="button" onClick={() => fetch('/api/auth/logout', { method: 'POST', credentials: 'include' }).then(() => { window.location.href = '/login'; })}>Logout</button>
      </nav>
      <h1>Jira Analytics – Config</h1>
      <p>
        <a href="/dashboard">Open dashboard</a> (after saving config, generate report on demand)
      </p>
      {status && (
        <p style={{ color: '#666' }}>
          {status.configured ? 'Config saved. Worker will use these values.' : 'Not configured yet.'}
        </p>
      )}
      <form onSubmit={handleSubmit} style={{ display: 'flex', flexDirection: 'column', gap: '0.75rem' }}>
        <label>
          JIRA Base URL
          <input
            type="url"
            value={form.JIRA_BASE_URL}
            onChange={(e) => setForm((f) => ({ ...f, JIRA_BASE_URL: e.target.value }))}
            placeholder="https://company.atlassian.net"
            required
            style={{ display: 'block', width: '100%', marginTop: 2, padding: 6 }}
          />
        </label>
        <label>
          JIRA Email
          <input
            type="email"
            value={form.JIRA_EMAIL}
            onChange={(e) => setForm((f) => ({ ...f, JIRA_EMAIL: e.target.value }))}
            placeholder="you@company.com"
            required
            style={{ display: 'block', width: '100%', marginTop: 2, padding: 6 }}
          />
        </label>
        <label>
          JIRA API Token
          <input
            type="password"
            value={form.JIRA_TOKEN}
            onChange={(e) => setForm((f) => ({ ...f, JIRA_TOKEN: e.target.value }))}
            placeholder="••••••••"
            required
            autoComplete="off"
            style={{ display: 'block', width: '100%', marginTop: 2, padding: 6 }}
          />
        </label>
        <label>
          Project keys (comma-separated)
          <input
            type="text"
            value={form.JIRA_PROJECT_KEYS}
            onChange={(e) => setForm((f) => ({ ...f, JIRA_PROJECT_KEYS: e.target.value }))}
            placeholder="BETTY,OZN"
            required
            style={{ display: 'block', width: '100%', marginTop: 2, padding: 6 }}
          />
        </label>
        {error && <p style={{ color: 'crimson' }}>{error}</p>}
        {saved && <p style={{ color: 'green' }}>Saved.</p>}
        <button type="submit" disabled={loading} style={{ padding: '8px 12px', cursor: loading ? 'wait' : 'pointer' }}>
          {loading ? 'Saving…' : 'Save'}
        </button>
      </form>
    </main>
  );
}
