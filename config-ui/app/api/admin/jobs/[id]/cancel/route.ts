import { NextResponse } from 'next/server';
import { getSessionUser } from '@/lib/auth';
import * as db from '@/lib/db';

export async function POST(
  _request: Request,
  { params }: { params: Promise<{ id: string }> }
) {
  const session = await getSessionUser();
  if (!session) return NextResponse.json({ error: 'Unauthorized' }, { status: 401 });
  if (session.role !== 'admin') return NextResponse.json({ error: 'Forbidden' }, { status: 403 });
  const id = parseInt((await params).id, 10);
  if (!Number.isInteger(id) || id < 1) return NextResponse.json({ error: 'Bad request' }, { status: 400 });
  const job = db.getJobById(id);
  if (!job) return NextResponse.json({ error: 'Job not found' }, { status: 404 });
  if (job.status !== 'pending' && job.status !== 'running') {
    return NextResponse.json({ error: 'Job cannot be cancelled' }, { status: 400 });
  }
  db.setJobFailed(id, 'Cancelled by admin');
  return NextResponse.json({ ok: true });
}
