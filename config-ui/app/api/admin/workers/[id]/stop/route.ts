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
  const id = decodeURIComponent((await params).id);
  if (!id) return NextResponse.json({ error: 'Bad request' }, { status: 400 });
  const w = db.getWorkerInstanceById(id);
  if (!w) return NextResponse.json({ error: 'Worker not found' }, { status: 404 });
  const ok = db.setWorkerStopRequested(id, true);
  if (!ok) return NextResponse.json({ error: 'Update failed' }, { status: 500 });
  return NextResponse.json({ ok: true });
}
