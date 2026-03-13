'use client';

import { useState, useEffect } from 'react';
import AppNav from '@/app/components/AppNav';

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
    <div className="dashboard">
      <AppNav activePage="dashboard" />

      <div className="dashboard-content">
        <h1 className="dashboard-title">Dashboard</h1>

        <section className="card dashboard-actions">
          <div className="dashboard-actions-row">
            <button
              onClick={handleGenerate}
              disabled={generating || isPending}
              className="btn-primary"
            >
              {isPending ? 'Generating…' : generating ? 'Starting…' : 'Generate report'}
            </button>
            {jobStatus?.status === 'failed' && jobStatus.errorMessage && (
              <span className="text-error msg-inline">Error: {jobStatus.errorMessage}</span>
            )}
            {generateError && (
              <span className="text-error msg-inline">{generateError}</span>
            )}
          </div>
          {jobStatus?.status === 'done' && (
            <p className="report-ready text-success">
              Report ready. View below or <a href="/dashboard/report" target="_blank" rel="noopener">open in new tab</a>.
            </p>
          )}
        </section>

        <section className="report-container card">
          <iframe
            src="/dashboard/report"
            title="Jira report"
            className="report-iframe"
            onLoad={(e) => {
              const iframe = e.currentTarget;
              try {
                setReportExists(iframe.contentWindow?.document.body?.innerHTML?.length ? true : false);
              } catch {
                setReportExists(false);
              }
            }}
          />
        </section>

        {reportExists === false && !isPending && jobStatus?.status !== 'done' && (
          <p className="text-muted report-placeholder">
            No report yet. Configure Jira on the Config page, then click Generate report.
          </p>
        )}
      </div>
    </div>
  );
}
