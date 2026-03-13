'use client';

import { useState, useEffect } from 'react';

type JobStatus = { status: string | null; jobId: number | null; errorMessage: string | null; createdAt: string | null };

export default function DashboardPage() {
  const [jobStatus, setJobStatus] = useState<JobStatus | null>(null);
  const [generating, setGenerating] = useState(false);
  const [generateError, setGenerateError] = useState<string | null>(null);
  const [reportExists, setReportExists] = useState<boolean | null>(null);

  const fetchStatus = () => {
    fetch('/api/reports/status', { credentials: 'include' })
      .then((r) => r.json())
      .then((data) => setJobStatus(data))
      .catch(() => setJobStatus({ status: null, jobId: null, errorMessage: null, createdAt: null }));
  };

  useEffect(() => {
    fetchStatus();
  }, []);

  useEffect(() => {
    if (!jobStatus || (jobStatus.status !== 'pending' && jobStatus.status !== 'running')) return;
    const t = setInterval(fetchStatus, 2000);
    return () => clearInterval(t);
  }, [jobStatus?.status]);

  const handleGenerate = async () => {
    setGenerateError(null);
    setGenerating(true);
    try {
      const res = await fetch('/api/reports/generate', { method: 'POST', credentials: 'include' });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) {
        const msg = data.error || data.message || (typeof data === 'string' ? data : 'Failed to start');
        setGenerateError(msg);
        return;
      }
      fetchStatus();
    } finally {
      setGenerating(false);
    }
  };

  const checkReport = () => {
    fetch('/dashboard/report', { credentials: 'include' })
      .then((r) => setReportExists(r.ok))
      .catch(() => setReportExists(false));
  };

  useEffect(() => {
    if (jobStatus?.status === 'done') checkReport();
  }, [jobStatus?.status]);

  const isPending = jobStatus?.status === 'pending' || jobStatus?.status === 'running';

  return (
    <main>
      <nav style={{ marginBottom: '1rem' }}>
        <a href="/">Config</a> | <a href="/dashboard">Dashboard</a> |{' '}
        <button type="button" onClick={() => fetch('/api/auth/logout', { method: 'POST', credentials: 'include' }).then(() => { window.location.href = '/login'; })}>Logout</button>
      </nav>
      <h1>Dashboard</h1>
      <p>
        <button onClick={handleGenerate} disabled={generating || isPending} style={{ padding: '8px 12px', cursor: generating || isPending ? 'wait' : 'pointer' }}>
          {isPending ? 'Generating…' : generating ? 'Starting…' : 'Generate report'}
        </button>
        {jobStatus?.status === 'failed' && jobStatus.errorMessage && (
          <span style={{ color: 'crimson', marginLeft: 8 }}>Error: {jobStatus.errorMessage}</span>
        )}
        {generateError && (
          <span style={{ color: 'crimson', marginLeft: 8 }}>{generateError}</span>
        )}
      </p>
      {jobStatus?.status === 'done' && (
        <p style={{ color: 'green' }}>Report ready. View below or <a href="/dashboard/report" target="_blank" rel="noopener">open in new tab</a>.</p>
      )}
      <iframe
        src="/dashboard/report"
        title="Jira report"
        style={{ width: '100%', minHeight: 600, border: '1px solid #ccc' }}
        onLoad={(e) => {
          const iframe = e.currentTarget;
          try {
            setReportExists(iframe.contentWindow?.document.body?.innerHTML?.length ? true : false);
          } catch {
            setReportExists(false);
          }
        }}
      />
      {reportExists === false && !isPending && jobStatus?.status !== 'done' && (
        <p style={{ color: '#666' }}>No report yet. Configure Jira on the Config page, then click Generate report.</p>
      )}
    </main>
  );
}
