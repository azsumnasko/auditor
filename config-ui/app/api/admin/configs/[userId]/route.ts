import { NextResponse } from 'next/server';
import { getSessionUser } from '@/lib/auth';
import * as db from '@/lib/db';

export async function DELETE(
  _request: Request,
  { params }: { params: Promise<{ userId: string }> }
) {
  const session = await getSessionUser();
  if (!session) return NextResponse.json({ error: 'Unauthorized' }, { status: 401 });
  if (session.role !== 'admin') return NextResponse.json({ error: 'Forbidden' }, { status: 403 });
  const userId = parseInt((await params).userId, 10);
  if (!Number.isInteger(userId) || userId < 1) return NextResponse.json({ error: 'Bad request' }, { status: 400 });
  const config = db.getConfig(userId);
  if (!config) return NextResponse.json({ error: 'Config not found' }, { status: 404 });
  db.deleteConfig(userId);
  return NextResponse.json({ ok: true });
}
