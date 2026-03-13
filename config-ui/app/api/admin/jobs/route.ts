import { NextResponse } from 'next/server';
import { getSessionUser } from '@/lib/auth';
import * as db from '@/lib/db';

export async function GET(request: Request) {
  const session = await getSessionUser();
  if (!session) return NextResponse.json({ error: 'Unauthorized' }, { status: 401 });
  if (session.role !== 'admin') return NextResponse.json({ error: 'Forbidden' }, { status: 403 });
  const { searchParams } = new URL(request.url);
  const status = searchParams.get('status') || undefined;
  const validStatuses = ['pending', 'running', 'done', 'failed'];
  const statusFilter = status && validStatuses.includes(status) ? status : undefined;
  const jobs = db.getAllJobs(statusFilter);
  return NextResponse.json(jobs);
}
