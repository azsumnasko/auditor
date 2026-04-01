'use client';

import { useState, useEffect } from 'react';

type ConfigRow = { user_id: number; user_email: string; jira_base_url: string; jira_email: string; jira_token: string; jira_project_keys: string };
type JobRow = {
  id: number;
  user_id: number;
  user_email: string;
  status: string;
  created_at: string;
  updated_at: string;
  error_message: string | null;
  progress_message: string | null;
};
type ReportRow = { user_id: number; user_email: string; has_report: boolean };

export default function AdminAssetsPage() {
  const [configs, setConfigs] = useState<ConfigRow[]>([]);
  const [jobs, setJobs] = useState<JobRow[]>([]);
  const [jobsFilter, setJobsFilter] = useState<string>('');
  const [reports, setReports] = useState<ReportRow[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [cancellingId, setCancellingId] = useState<number | null>(null);
  const [deletingReportUserId, setDeletingReportUserId] = useState<number | null>(null);
  const [deletingConfigUserId, setDeletingConfigUserId] = useState<number | null>(null);
  const [tab, setTab] = useState<'configs' | 'jobs' | 'reports'>('configs');

  const fetchConfigs = () => {
    fetch('/api/admin/configs', { credentials: 'include' })
      .then((r) => (r.ok ? r.json() : []))
      .then(setConfigs)
      .catch(() => setConfigs([]));
  };
  const fetchJobs = () => {
    const q = jobsFilter ? `?status=${encodeURIComponent(jobsFilter)}` : '';
    fetch(`/api/admin/jobs${q}`, { credentials: 'include' })
      .then((r) => (r.ok ? r.json() : []))
      .then(setJobs)
      .catch(() => setJobs([]));
  };
  const fetchReports = () => {
    fetch('/api/admin/reports', { credentials: 'include' })
      .then((r) => (r.ok ? r.json() : []))
      .then(setReports)
      .catch(() => setReports([]));
  };

  useEffect(() => {
    setLoading(true);
    Promise.all([
      fetch('/api/admin/configs', { credentials: 'include' }).then((r) => (r.ok ? r.json() : [])),
      fetch('/api/admin/jobs', { credentials: 'include' }).then((r) => (r.ok ? r.json() : [])),
      fetch('/api/admin/reports', { credentials: 'include' }).then((r) => (r.ok ? r.json() : [])),
    ])
      .then(([c, j, r]) => {
        setConfigs(c);
        setJobs(j);
        setReports(r);
      })
      .catch(() => setError('Failed to load'))
      .finally(() => setLoading(false));
  }, []);

  useEffect(() => {
    if (tab === 'jobs') fetchJobs();
  }, [tab, jobsFilter]);

  const cancelJob = (id: number) => {
    setCancellingId(id);
    fetch(`/api/admin/jobs/${id}/cancel`, { method: 'POST', credentials: 'include' })
      .then((r) => r.json().then((d) => ({ ok: r.ok, data: d })))
      .then(({ ok }) => {
        if (ok) {
          setError(null);
          fetchJobs();
        } else setError('Failed to cancel');
      })
      .finally(() => setCancellingId(null));
  };

  const deleteReport = (userId: number) => {
    if (!confirm('Delete this user’s report file?')) return;
    setDeletingReportUserId(userId);
    fetch(`/api/admin/reports/${userId}`, { method: 'DELETE', credentials: 'include' })
      .then((r) => r.json().then((d) => ({ ok: r.ok, data: d })))
      .then(({ ok }) => {
        if (ok) {
          setError(null);
          fetchReports();
        } else setError('Failed to delete report');
      })
      .finally(() => setDeletingReportUserId(null));
  };

  const deleteConfig = (userId: number) => {
    if (!confirm('Delete this user’s Jira config?')) return;
    setDeletingConfigUserId(userId);
    fetch(`/api/admin/configs/${userId}`, { method: 'DELETE', credentials: 'include' })
      .then((r) => r.json().then((d) => ({ ok: r.ok, data: d })))
      .then(({ ok }) => {
        if (ok) {
          setError(null);
          fetchConfigs();
        } else setError('Failed to delete config');
      })
      .finally(() => setDeletingConfigUserId(null));
  };

  const tableStyle = { width: '100%' as const, borderCollapse: 'collapse' as const };
  const thStyle = { borderBottom: '1px solid var(--border)', textAlign: 'left' as const, padding: '8px' };
  const tdStyle = { borderBottom: '1px solid var(--border)', padding: '8px' };

  return (
    <>
      <h1 className="dashboard-title">Admin – Assets</h1>
      <p className="text-muted" style={{ marginBottom: '1rem' }}>
        <a href="/admin">Admin</a> → Assets
      </p>
      <p style={{ marginBottom: '1rem' }}>
        <a href="/admin/users">Users</a> | <a href="/admin/assets">Assets</a>
      </p>
      {error && <p className="text-error">{error}</p>}
      <div style={{ display: 'flex', gap: '8px', marginBottom: '1rem' }}>
        <button type="button" className={tab === 'configs' ? 'btn-primary' : ''} onClick={() => setTab('configs')}>Configs</button>
        <button type="button" className={tab === 'jobs' ? 'btn-primary' : ''} onClick={() => setTab('jobs')}>Jobs</button>
        <button type="button" className={tab === 'reports' ? 'btn-primary' : ''} onClick={() => setTab('reports')}>Reports</button>
      </div>
      {loading ? (
        <p className="text-muted">Loading…</p>
      ) : (
        <section className="card">
          {tab === 'configs' && (
            <table style={tableStyle}>
              <thead>
                <tr>
                  <th style={thStyle}>User</th>
                  <th style={thStyle}>Jira URL</th>
                  <th style={thStyle}>Token</th>
                  <th style={thStyle}>Actions</th>
                </tr>
              </thead>
              <tbody>
                {configs.length === 0 ? (
                  <tr><td colSpan={4} style={tdStyle} className="text-muted">No configs</td></tr>
                ) : (
                  configs.map((c) => (
                    <tr key={c.user_id}>
                      <td style={tdStyle}>{c.user_email}</td>
                      <td style={tdStyle}>{c.jira_base_url}</td>
                      <td style={tdStyle}>{c.jira_token}</td>
                      <td style={tdStyle}>
                        <button type="button" disabled={deletingConfigUserId === c.user_id} onClick={() => deleteConfig(c.user_id)}>Delete</button>
                      </td>
                    </tr>
                  ))
                )}
              </tbody>
            </table>
          )}
          {tab === 'jobs' && (
            <>
              <p style={{ marginBottom: '8px' }}>
                Filter: <select value={jobsFilter} onChange={(e) => setJobsFilter(e.target.value)}>
                  <option value="">All</option>
                  <option value="pending">pending</option>
                  <option value="running">running</option>
                  <option value="done">done</option>
                  <option value="failed">failed</option>
                </select>
              </p>
              <table style={tableStyle}>
                <thead>
                  <tr>
                    <th style={thStyle}>ID</th>
                    <th style={thStyle}>User</th>
                    <th style={thStyle}>Status</th>
                    <th style={thStyle}>Progress</th>
                    <th style={thStyle}>Created</th>
                    <th style={thStyle}>Actions</th>
                  </tr>
                </thead>
                <tbody>
                  {jobs.length === 0 ? (
                    <tr><td colSpan={6} style={tdStyle} className="text-muted">No jobs</td></tr>
                  ) : (
                    jobs.map((j) => (
                      <tr key={j.id}>
                        <td style={tdStyle}>{j.id}</td>
                        <td style={tdStyle}>{j.user_email}</td>
                        <td style={tdStyle}>{j.status}</td>
                        <td style={tdStyle} className="text-muted">{j.progress_message ?? '—'}</td>
                        <td style={tdStyle} className="text-muted">{j.created_at}</td>
                        <td style={tdStyle}>
                          {(j.status === 'pending' || j.status === 'running') && (
                            <button type="button" disabled={cancellingId === j.id} onClick={() => cancelJob(j.id)}>Cancel</button>
                          )}
                        </td>
                      </tr>
                    ))
                  )}
                </tbody>
              </table>
            </>
          )}
          {tab === 'reports' && (
            <table style={tableStyle}>
              <thead>
                <tr>
                  <th style={thStyle}>User</th>
                  <th style={thStyle}>Has report</th>
                  <th style={thStyle}>Actions</th>
                </tr>
              </thead>
              <tbody>
                {reports.length === 0 ? (
                  <tr><td colSpan={3} style={tdStyle} className="text-muted">No report files</td></tr>
                ) : (
                  reports.map((r) => (
                    <tr key={r.user_id}>
                      <td style={tdStyle}>{r.user_email || r.user_id}</td>
                      <td style={tdStyle}>{r.has_report ? 'Yes' : 'No'}</td>
                      <td style={tdStyle}>
                        {r.has_report && (
                          <button type="button" disabled={deletingReportUserId === r.user_id} onClick={() => deleteReport(r.user_id)}>Delete file</button>
                        )}
                      </td>
                    </tr>
                  ))
                )}
              </tbody>
            </table>
          )}
        </section>
      )}
    </>
  );
}
