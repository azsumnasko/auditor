'use client';

import { useState, useEffect } from 'react';
import AppNav from '@/app/components/AppNav';

type JobStatus = {
  status: string | null;
  jobId: number | null;
  errorMessage: string | null;
  createdAt: string | null;
  pipelineWarnings: string[] | null;
  progressMessage: string | null;
};

const EMPTY_JOB_STATUS: JobStatus = {
  status: null,
  jobId: null,
  errorMessage: null,
  createdAt: null,
  pipelineWarnings: null,
  progressMessage: null,
};

function normalizeJobStatus(raw: unknown): JobStatus {
  if (!raw || typeof raw !== 'object') return { ...EMPTY_JOB_STATUS };
  const o = raw as Record<string, unknown>;
  const pw = o.pipelineWarnings;
  let pipelineWarnings: string[] | null = null;
  if (pw === null) {
    pipelineWarnings = null;
  } else if (Array.isArray(pw)) {
    const strings = pw.filter((x): x is string => typeof x === 'string');
    pipelineWarnings = strings.length ? strings : null;
  }
  return {
    status: o.status === null || typeof o.status === 'string' ? (o.status as string | null) : null,
    jobId: typeof o.jobId === 'number' ? o.jobId : null,
    errorMessage:
      o.errorMessage === null || typeof o.errorMessage === 'string' ? (o.errorMessage as string | null) : null,
    createdAt: o.createdAt === null || typeof o.createdAt === 'string' ? (o.createdAt as string | null) : null,
    pipelineWarnings,
    progressMessage:
      o.progressMessage === null || typeof o.progressMessage === 'string'
        ? (o.progressMessage as string | null)
        : null,
  };
}

export default function DashboardPage() {
  const [jobStatus, setJobStatus] = useState<JobStatus | null>(null);
  const [generating, setGenerating] = useState(false);
  const [generateError, setGenerateError] = useState<string | null>(null);
  const [reportExists, setReportExists] = useState<boolean | null>(null);

  const fetchStatus = () => {
    fetch('/api/reports/status', { credentials: 'include' })
      .then(async (r) => {
        if (!r.ok) {
          setJobStatus({ ...EMPTY_JOB_STATUS });
          return;
        }
        let raw: unknown;
        try {
          raw = await r.json();
        } catch {
          setJobStatus({ ...EMPTY_JOB_STATUS });
          return;
        }
        setJobStatus(normalizeJobStatus(raw));
      })
      .catch(() => setJobStatus({ ...EMPTY_JOB_STATUS }));
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

  const progressLabel =
    jobStatus?.status === 'pending'
      ? 'Queued—waiting for worker…'
      : jobStatus?.status === 'running'
        ? jobStatus.progressMessage?.trim() || 'Running…'
        : null;

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
              {isPending ? 'Working…' : generating ? 'Starting…' : 'Generate report'}
            </button>
            {jobStatus?.status === 'failed' && jobStatus.errorMessage && (
              <span className="text-error msg-inline">Error: {jobStatus.errorMessage}</span>
            )}
            {generateError && (
              <span className="text-error msg-inline">{generateError}</span>
            )}
            {isPending && progressLabel && (
              <span className="generation-status-badge" role="status">
                {progressLabel}
              </span>
            )}
          </div>
          {jobStatus?.status === 'done' && (
            <>
              {jobStatus.pipelineWarnings && jobStatus.pipelineWarnings.length > 0 && (
                <div
                  className="pipeline-warnings-banner"
                  role="status"
                  style={{
                    marginTop: '0.75rem',
                    padding: '0.75rem 1rem',
                    borderRadius: 8,
                    border: '1px solid #d29922',
                    background: 'rgba(210, 153, 34, 0.12)',
                    fontSize: '0.875rem',
                  }}
                >
                  <strong>Partial data</strong>
                  <p style={{ margin: '0.35rem 0 0', color: 'var(--muted, #8b949e)' }}>
                    Some optional sources did not complete:</p>
                  <ul style={{ margin: '0.35rem 0 0', paddingLeft: '1.25rem' }}>
                    {jobStatus.pipelineWarnings.map((w, i) => (
                      <li key={i}>{w}</li>
                    ))}
                  </ul>
                </div>
              )}
              <p className="report-ready text-success">
                Report ready. View below or <a href="/dashboard/report" target="_blank" rel="noopener">open in new tab</a>.
              </p>
            </>
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
