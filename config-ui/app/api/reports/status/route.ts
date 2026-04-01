import path from 'path';
import { readFile } from 'fs/promises';
import { NextResponse } from 'next/server';
import * as db from '@/lib/db';
import { getSessionUserId } from '@/lib/auth';

const DATA_DIR = process.env.DATA_DIR || '/data';
const USERS_DIR = path.resolve(DATA_DIR, 'users');

async function readPipelineWarnings(userId: number): Promise<string[] | null> {
  const warningsPath = path.resolve(DATA_DIR, 'users', String(userId), 'pipeline_warnings_latest.json');
  if (!warningsPath.startsWith(USERS_DIR + path.sep) && !warningsPath.startsWith(USERS_DIR + '/')) {
    return null;
  }
  try {
    const raw = await readFile(warningsPath, 'utf-8');
    const parsed = JSON.parse(raw) as unknown;
    if (Array.isArray(parsed)) {
      return parsed.length ? (parsed as string[]) : null;
    }
    if (parsed && typeof parsed === 'object' && 'warnings' in parsed) {
      const w = (parsed as { warnings?: unknown }).warnings;
      if (Array.isArray(w) && w.length) {
        return w.filter((x): x is string => typeof x === 'string');
      }
    }
    return null;
  } catch {
    return null;
  }
}

export async function GET() {
  const userId = await getSessionUserId();
  if (!userId) return NextResponse.json({ error: 'Unauthorized' }, { status: 401 });
  const job = db.getLatestJob(userId);
  if (!job) {
    return NextResponse.json({
      status: null,
      jobId: null,
      errorMessage: null,
      createdAt: null,
      pipelineWarnings: null,
    });
  }
  let pipelineWarnings: string[] | null = null;
  if (job.status === 'done') {
    pipelineWarnings = await readPipelineWarnings(userId);
  }
  return NextResponse.json({
    status: job.status,
    jobId: job.id,
    errorMessage: job.error_message ?? null,
    createdAt: job.created_at,
    pipelineWarnings,
  });
}
