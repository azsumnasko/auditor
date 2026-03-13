import { NextResponse } from 'next/server';
import * as db from '@/lib/db';
import { getSessionUserId } from '@/lib/auth';

export async function GET() {
  const userId = await getSessionUserId();
  if (!userId) return NextResponse.json({ error: 'Unauthorized' }, { status: 401 });
  const job = db.getLatestJob(userId);
  if (!job) {
    return NextResponse.json({ status: null, jobId: null, errorMessage: null, createdAt: null });
  }
  return NextResponse.json({
    status: job.status,
    jobId: job.id,
    errorMessage: job.error_message ?? null,
    createdAt: job.created_at,
  });
}
