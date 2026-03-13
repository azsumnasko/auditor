import { NextResponse } from 'next/server';
import * as db from '@/lib/db';
import { getSessionUserId } from '@/lib/auth';

const MAX_REPORTS_PER_HOUR = 10;

export async function POST() {
  const userId = await getSessionUserId();
  if (!userId) return NextResponse.json({ error: 'Unauthorized' }, { status: 401 });
  const config = db.getConfig(userId);
  if (!config) {
    return NextResponse.json({ error: 'Configure Jira first (Config page)' }, { status: 400 });
  }
  const latest = db.getLatestJob(userId);
  if (latest && (latest.status === 'pending' || latest.status === 'running')) {
    return NextResponse.json(
      { error: 'A report is already generating. Wait for it to finish.' },
      { status: 409 }
    );
  }
  const createdLastHour = db.countJobsCreatedInLastHour(userId);
  if (createdLastHour >= MAX_REPORTS_PER_HOUR) {
    return NextResponse.json(
      {
        error: `Rate limit: max ${MAX_REPORTS_PER_HOUR} reports per hour. Try again later.`,
      },
      { status: 429 }
    );
  }
  const jobId = db.createJob(userId);
  return NextResponse.json({ jobId });
}
