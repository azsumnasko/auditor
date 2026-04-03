'use client';

import { useState, useEffect } from 'react';
import AppNav from '@/app/components/AppNav';

type ConfigStatus = { configured: boolean; tokenSaved?: boolean } | null;
type RepoEntry = { repo: string; branch: string; octopus: string; exclude_regex: string };

const EMPTY_REPO: RepoEntry = { repo: '', branch: 'stable', octopus: '', exclude_regex: '' };

export default function ConfigPage() {
  const [status, setStatus] = useState<ConfigStatus>(null);
  const [saved, setSaved] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [changingToken, setChangingToken] = useState(false);
  const [form, setForm] = useState({
    JIRA_BASE_URL: '',
    JIRA_EMAIL: '',
    JIRA_TOKEN: '',
    JIRA_PROJECT_KEYS: '',
    GIT_PROVIDER: 'github',
    GIT_BASE_URL: '',
    GIT_TOKEN: '',
    GIT_ORG: '',
    GIT_REPOS: '',
    CICD_PROVIDER: 'github_actions',
    CICD_DEPLOY_WORKFLOW: '',
    OCTOPUS_SERVER_URL: '',
    OCTOPUS_API_KEY: '',
    OCTOPUS_ENVIRONMENT: 'Ontario',
  });
  const [repoConfig, setRepoConfig] = useState<RepoEntry[]>([]);
  const [gitTokenSaved, setGitTokenSaved] = useState(false);
  const [octopusTokenSaved, setOctopusTokenSaved] = useState(false);
  const [changingGitToken, setChangingGitToken] = useState(false);
  const [changingOctopusToken, setChangingOctopusToken] = useState(false);

  const tokenSaved = status?.tokenSaved ?? false;

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
        if (data?.JIRA_BASE_URL || data?.JIRA_PROJECT_KEYS || data?.JIRA_EMAIL) {
          setForm((f) => ({
            ...f,
            JIRA_BASE_URL: data.JIRA_BASE_URL ?? f.JIRA_BASE_URL,
            JIRA_EMAIL: data.JIRA_EMAIL ?? f.JIRA_EMAIL,
            JIRA_PROJECT_KEYS: data.JIRA_PROJECT_KEYS ?? f.JIRA_PROJECT_KEYS,
            GIT_PROVIDER: data.GIT_PROVIDER || f.GIT_PROVIDER,
            GIT_BASE_URL: data.GIT_BASE_URL || f.GIT_BASE_URL,
            GIT_ORG: data.GIT_ORG || f.GIT_ORG,
            GIT_REPOS: data.GIT_REPOS || f.GIT_REPOS,
            CICD_PROVIDER: data.CICD_PROVIDER || f.CICD_PROVIDER,
            CICD_DEPLOY_WORKFLOW: data.CICD_DEPLOY_WORKFLOW || f.CICD_DEPLOY_WORKFLOW,
            OCTOPUS_SERVER_URL: data.OCTOPUS_SERVER_URL || f.OCTOPUS_SERVER_URL,
            OCTOPUS_ENVIRONMENT: data.OCTOPUS_ENVIRONMENT || f.OCTOPUS_ENVIRONMENT,
          }));
          setGitTokenSaved(!!data.GIT_TOKEN_SAVED);
          setOctopusTokenSaved(!!data.OCTOPUS_TOKEN_SAVED);
          try {
            const parsed = JSON.parse(data.REPO_CONFIG || '[]');
            let repos: RepoEntry[] = Array.isArray(parsed) ? parsed : [];
            // Migrate OCTOPUS_REPO_MAP entries into the repo table
            const rawMap = (data.OCTOPUS_REPO_MAP || '').trim();
            if (rawMap) {
              try {
                const mapObj = JSON.parse(rawMap);
                if (mapObj && typeof mapObj === 'object' && !Array.isArray(mapObj)) {
                  for (const [repoName, octProj] of Object.entries(mapObj)) {
                    if (!repoName || !octProj) continue;
                    const existing = repos.find((r) => r.repo === repoName);
                    if (existing) {
                      if (!existing.octopus) existing.octopus = String(octProj);
                    } else {
                      repos = [...repos, { repo: repoName, branch: 'stable', octopus: String(octProj), exclude_regex: '' }];
                    }
                  }
                }
              } catch { /* ignore bad OCTOPUS_REPO_MAP JSON */ }
            }
            if (repos.length > 0) setRepoConfig(repos);
          } catch { /* ignore bad JSON */ }
        }
      })
      .catch(() => setStatus({ configured: false }));
  }, []);

  const tokenRequired = !tokenSaved || changingToken;

  const validate = (): string | null => {
    const url = form.JIRA_BASE_URL.trim();
    if (!url) return 'JIRA Base URL is required';
    try {
      new URL(url.startsWith('http') ? url : `https://${url}`);
    } catch {
      return 'JIRA Base URL must be a valid URL (e.g. https://company.atlassian.net)';
    }
    if (!form.JIRA_EMAIL.trim()) return 'JIRA Email is required';
    if (tokenRequired && !form.JIRA_TOKEN.trim()) return 'JIRA Token is required';
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
      const cleanRepos = repoConfig.filter((r) => r.repo.trim());
      const payload: Record<string, string> = {
        JIRA_BASE_URL: form.JIRA_BASE_URL.trim(),
        JIRA_EMAIL: form.JIRA_EMAIL.trim(),
        JIRA_PROJECT_KEYS: form.JIRA_PROJECT_KEYS.trim(),
        GIT_PROVIDER: form.GIT_PROVIDER,
        GIT_BASE_URL: form.GIT_BASE_URL.trim(),
        GIT_ORG: form.GIT_ORG.trim(),
        GIT_REPOS: form.GIT_REPOS.trim(),
        CICD_PROVIDER: form.CICD_PROVIDER,
        CICD_DEPLOY_WORKFLOW: form.CICD_DEPLOY_WORKFLOW.trim(),
        OCTOPUS_SERVER_URL: form.OCTOPUS_SERVER_URL.trim(),
        OCTOPUS_ENVIRONMENT: form.OCTOPUS_ENVIRONMENT.trim(),
        OCTOPUS_REPO_MAP: '',
        REPO_CONFIG: JSON.stringify(cleanRepos),
      };
      if (tokenRequired) {
        payload.JIRA_TOKEN = form.JIRA_TOKEN.trim();
      }
      if (changingGitToken || !gitTokenSaved) {
        if (form.GIT_TOKEN.trim()) payload.GIT_TOKEN = form.GIT_TOKEN.trim();
      }
      if (changingOctopusToken || !octopusTokenSaved) {
        if (form.OCTOPUS_API_KEY.trim()) payload.OCTOPUS_API_KEY = form.OCTOPUS_API_KEY.trim();
      }
      const res = await fetch('/api/config', {
        method: 'POST',
        credentials: 'include',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
      });
      if (!res.ok) {
        const data = await res.json().catch(() => ({}));
        throw new Error(data.error || (typeof data === 'string' ? data : `Save failed: ${res.status}`));
      }
      setSaved(true);
      setStatus({ configured: true, tokenSaved: true });
      setChangingToken(false);
      if (changingGitToken || (!gitTokenSaved && form.GIT_TOKEN.trim())) setGitTokenSaved(true);
      if (changingOctopusToken || (!octopusTokenSaved && form.OCTOPUS_API_KEY.trim())) setOctopusTokenSaved(true);
      setChangingGitToken(false);
      setChangingOctopusToken(false);
      setForm((f) => ({ ...f, JIRA_TOKEN: '', GIT_TOKEN: '', OCTOPUS_API_KEY: '' }));
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Save failed');
    } finally {
      setLoading(false);
    }
  };

  return (
    <main className="config-page">
      <AppNav activePage="config" />
      <div className="config-content">
        <h1>Jira Analytics – Config</h1>
        <p>
          <a href="/dashboard">Open dashboard</a> (after saving config, generate report on demand)
        </p>
        {status && (
          <p className="text-muted">
            {status.configured ? 'Config saved. Worker will use these values.' : 'Not configured yet.'}
          </p>
        )}
        <form onSubmit={handleSubmit} className="config-form">
        <label>
          JIRA Base URL
          <input
            type="url"
            value={form.JIRA_BASE_URL}
            onChange={(e) => setForm((f) => ({ ...f, JIRA_BASE_URL: e.target.value }))}
            placeholder="https://company.atlassian.net"
            required
            className="config-input"
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
            className="config-input"
          />
        </label>
        <label>
          JIRA API Token
          {tokenSaved && !changingToken ? (
            <div className="token-saved-row">
              <span className="text-success">API token is saved</span>
              <button type="button" className="btn-link" onClick={() => setChangingToken(true)}>
                Change
              </button>
            </div>
          ) : (
            <input
              type="password"
              value={form.JIRA_TOKEN}
              onChange={(e) => setForm((f) => ({ ...f, JIRA_TOKEN: e.target.value }))}
              placeholder="••••••••"
              required={tokenRequired}
              autoComplete="off"
              className="config-input"
            />
          )}
        </label>
        <label>
          Project keys (comma-separated)
          <input
            type="text"
            value={form.JIRA_PROJECT_KEYS}
            onChange={(e) => setForm((f) => ({ ...f, JIRA_PROJECT_KEYS: e.target.value }))}
            placeholder="BETTY,OZN"
            required
            className="config-input"
          />
        </label>

        <hr style={{ margin: '24px 0', borderColor: '#30363d' }} />
        <h2>Git Configuration</h2>
        <label>
          Provider
          <select value={form.GIT_PROVIDER} onChange={(e) => setForm((f) => ({ ...f, GIT_PROVIDER: e.target.value }))} className="config-input">
            <option value="github">GitHub</option>
            <option value="gitlab">GitLab</option>
          </select>
        </label>
        <label>
          API Base URL <span className="text-muted">(leave blank for default)</span>
          <input type="url" value={form.GIT_BASE_URL} onChange={(e) => setForm((f) => ({ ...f, GIT_BASE_URL: e.target.value }))} placeholder="https://api.github.com" className="config-input" />
        </label>
        <label>
          Git Token (PAT)
          {gitTokenSaved && !changingGitToken ? (
            <div className="token-saved-row">
              <span className="text-success">Git token is saved</span>
              <button type="button" className="btn-link" onClick={() => setChangingGitToken(true)}>Change</button>
            </div>
          ) : (
            <input type="password" value={form.GIT_TOKEN} onChange={(e) => setForm((f) => ({ ...f, GIT_TOKEN: e.target.value }))} placeholder="ghp_..." autoComplete="off" className="config-input" />
          )}
        </label>
        <label>
          Organization / Owner
          <input type="text" value={form.GIT_ORG} onChange={(e) => setForm((f) => ({ ...f, GIT_ORG: e.target.value }))} placeholder="Betty-Gaming" className="config-input" />
        </label>
        <label>
          Repos <span className="text-muted">(comma-separated, or * for all)</span>
          <input type="text" value={form.GIT_REPOS} onChange={(e) => setForm((f) => ({ ...f, GIT_REPOS: e.target.value }))} placeholder="*" className="config-input" />
        </label>

        <div style={{ marginTop: '16px', padding: '16px', background: '#161b22', border: '1px solid #30363d', borderRadius: '8px' }}>
          <h3 style={{ margin: '0 0 8px', fontSize: '1em' }}>Repository Configuration</h3>
          <p className="text-muted" style={{ fontSize: '0.85em', marginBottom: '12px' }}>
            Define each repo&apos;s default branch, Octopus project mapping, and optional commit-message exclude pattern.
            Leave empty to auto-discover from the Git org.
          </p>
          <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: '0.85em' }}>
            <thead>
              <tr style={{ borderBottom: '1px solid #30363d' }}>
                <th style={{ textAlign: 'left', padding: '4px 6px', color: '#8b949e' }}>Repo name</th>
                <th style={{ textAlign: 'left', padding: '4px 6px', color: '#8b949e', width: '100px' }}>Branch</th>
                <th style={{ textAlign: 'left', padding: '4px 6px', color: '#8b949e' }}>Octopus project</th>
                <th style={{ textAlign: 'left', padding: '4px 6px', color: '#8b949e' }}>Exclude regex</th>
                <th style={{ width: '36px' }}></th>
              </tr>
            </thead>
            <tbody>
              {repoConfig.map((entry, i) => (
                <tr key={i} style={{ borderBottom: '1px solid #21262d' }}>
                  <td style={{ padding: '3px 4px' }}>
                    <input
                      type="text" value={entry.repo} placeholder="e.g. Gateway"
                      onChange={(e) => { const v = e.target.value; setRepoConfig((rc) => rc.map((r, idx) => idx === i ? { ...r, repo: v } : r)); }}
                      style={{ width: '100%', background: '#0d1117', border: '1px solid #30363d', borderRadius: '4px', padding: '4px 6px', color: '#c9d1d9', fontSize: '0.9em' }}
                    />
                  </td>
                  <td style={{ padding: '3px 4px' }}>
                    <select
                      value={entry.branch}
                      onChange={(e) => { const v = e.target.value; setRepoConfig((rc) => rc.map((r, idx) => idx === i ? { ...r, branch: v } : r)); }}
                      style={{ width: '100%', background: '#0d1117', border: '1px solid #30363d', borderRadius: '4px', padding: '4px 6px', color: '#c9d1d9', fontSize: '0.9em' }}
                    >
                      <option value="main">main</option>
                      <option value="stable">stable</option>
                      <option value="master">master</option>
                      <option value="develop">develop</option>
                    </select>
                  </td>
                  <td style={{ padding: '3px 4px' }}>
                    <input
                      type="text" value={entry.octopus} placeholder="(none)"
                      onChange={(e) => { const v = e.target.value; setRepoConfig((rc) => rc.map((r, idx) => idx === i ? { ...r, octopus: v } : r)); }}
                      style={{ width: '100%', background: '#0d1117', border: '1px solid #30363d', borderRadius: '4px', padding: '4px 6px', color: '#c9d1d9', fontSize: '0.9em' }}
                    />
                  </td>
                  <td style={{ padding: '3px 4px' }}>
                    <input
                      type="text" value={entry.exclude_regex} placeholder="(none)"
                      onChange={(e) => { const v = e.target.value; setRepoConfig((rc) => rc.map((r, idx) => idx === i ? { ...r, exclude_regex: v } : r)); }}
                      style={{ width: '100%', background: '#0d1117', border: '1px solid #30363d', borderRadius: '4px', padding: '4px 6px', color: '#c9d1d9', fontSize: '0.9em' }}
                    />
                  </td>
                  <td style={{ padding: '3px 4px', textAlign: 'center' }}>
                    <button type="button" onClick={() => setRepoConfig((rc) => rc.filter((_, idx) => idx !== i))}
                      style={{ background: 'none', border: 'none', color: '#f85149', cursor: 'pointer', fontSize: '1.1em', padding: '2px 6px' }}
                      title="Remove repo"
                    >&times;</button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          <button type="button" onClick={() => setRepoConfig((rc) => [...rc, { ...EMPTY_REPO }])}
            style={{ marginTop: '8px', background: '#21262d', border: '1px solid #30363d', borderRadius: '6px', color: '#58a6ff', padding: '6px 14px', cursor: 'pointer', fontSize: '0.85em' }}
          >+ Add repo</button>
        </div>

        <hr style={{ margin: '24px 0', borderColor: '#30363d' }} />
        <h2>CI/CD Configuration</h2>
        <label>
          Provider
          <select value={form.CICD_PROVIDER} onChange={(e) => setForm((f) => ({ ...f, CICD_PROVIDER: e.target.value }))} className="config-input">
            <option value="github_actions">GitHub Actions</option>
            <option value="jenkins">Jenkins</option>
            <option value="none">None</option>
          </select>
        </label>
        <label>
          Deploy workflow file <span className="text-muted">(e.g. deploy.yml)</span>
          <input type="text" value={form.CICD_DEPLOY_WORKFLOW} onChange={(e) => setForm((f) => ({ ...f, CICD_DEPLOY_WORKFLOW: e.target.value }))} placeholder="deploy.yml" className="config-input" />
        </label>

        <hr style={{ margin: '24px 0', borderColor: '#30363d' }} />
        <h2>Octopus Deploy Configuration</h2>
        <label>
          Server URL
          <input type="url" value={form.OCTOPUS_SERVER_URL} onChange={(e) => setForm((f) => ({ ...f, OCTOPUS_SERVER_URL: e.target.value }))} placeholder="https://company.octopus.app" className="config-input" />
        </label>
        <label>
          API Key
          {octopusTokenSaved && !changingOctopusToken ? (
            <div className="token-saved-row">
              <span className="text-success">Octopus API key is saved</span>
              <button type="button" className="btn-link" onClick={() => setChangingOctopusToken(true)}>Change</button>
            </div>
          ) : (
            <input type="password" value={form.OCTOPUS_API_KEY} onChange={(e) => setForm((f) => ({ ...f, OCTOPUS_API_KEY: e.target.value }))} placeholder="API-..." autoComplete="off" className="config-input" />
          )}
        </label>
        <label>
          Environment name
          <input type="text" value={form.OCTOPUS_ENVIRONMENT} onChange={(e) => setForm((f) => ({ ...f, OCTOPUS_ENVIRONMENT: e.target.value }))} placeholder="Ontario" className="config-input" />
        </label>
        <p className="text-muted" style={{ fontSize: '0.85em', marginTop: '8px' }}>
          Repo-to-project mapping is configured in the <strong>Repository Configuration</strong> table above (Octopus project column).
        </p>

        {error && <p className="text-error">{error}</p>}
        {saved && <p className="text-success">Saved.</p>}
        <button type="submit" disabled={loading} className="btn-primary">
          {loading ? 'Saving…' : 'Save'}
        </button>
      </form>
      </div>
    </main>
  );
}
