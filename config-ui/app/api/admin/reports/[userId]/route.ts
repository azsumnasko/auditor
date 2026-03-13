import { NextResponse } from 'next/server';
import { getSessionUser } from '@/lib/auth';
import { unlink, rm } from 'fs/promises';
import path from 'path';

const DATA_DIR = process.env.DATA_DIR || '/data';
const USERS_DIR = path.resolve(DATA_DIR, 'users');

export async function DELETE(
  _request: Request,
  { params }: { params: Promise<{ userId: string }> }
) {
  const session = await getSessionUser();
  if (!session) return NextResponse.json({ error: 'Unauthorized' }, { status: 401 });
  if (session.role !== 'admin') return NextResponse.json({ error: 'Forbidden' }, { status: 403 });
  const userIdParam = (await params).userId;
  const id = parseInt(userIdParam, 10);
  if (!Number.isInteger(id) || id < 1 || String(id) !== userIdParam) {
    return NextResponse.json({ error: 'Bad request' }, { status: 400 });
  }
  const safeId = String(id);
  const reportPath = path.join(USERS_DIR, safeId, 'jira_dashboard.html');
  const userDir = path.join(USERS_DIR, safeId);
  if (!reportPath.startsWith(USERS_DIR + path.sep) && !reportPath.startsWith(USERS_DIR + '/')) {
    return NextResponse.json({ error: 'Forbidden' }, { status: 403 });
  }
  try {
    await unlink(reportPath);
  } catch {
    return NextResponse.json({ error: 'Report not found or already deleted' }, { status: 404 });
  }
  try {
    await rm(userDir, { recursive: true });
  } catch {
    // best-effort cleanup of empty dir
  }
  return NextResponse.json({ ok: true });
}
