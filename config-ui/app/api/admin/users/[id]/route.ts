import { NextResponse } from 'next/server';
import { getSessionUser } from '@/lib/auth';
import * as db from '@/lib/db';
import { unlink, rm } from 'fs/promises';
import path from 'path';

const DATA_DIR = process.env.DATA_DIR || '/data';
const USERS_DIR = path.resolve(DATA_DIR, 'users');

export async function PATCH(
  _request: Request,
  { params }: { params: Promise<{ id: string }> }
) {
  const session = await getSessionUser();
  if (!session) return NextResponse.json({ error: 'Unauthorized' }, { status: 401 });
  if (session.role !== 'admin') return NextResponse.json({ error: 'Forbidden' }, { status: 403 });
  const id = parseInt((await params).id, 10);
  if (!Number.isInteger(id) || id < 1) return NextResponse.json({ error: 'Bad request' }, { status: 400 });
  let body: { role?: string };
  try {
    body = await (await _request.json()) as { role?: string };
  } catch {
    return NextResponse.json({ error: 'Invalid JSON' }, { status: 400 });
  }
  const role = body.role === 'admin' ? 'admin' : body.role === 'user' ? 'user' : undefined;
  if (!role) return NextResponse.json({ error: 'role must be "user" or "admin"' }, { status: 400 });
  const user = db.getUserById(id);
  if (!user) return NextResponse.json({ error: 'User not found' }, { status: 404 });
  if (user.role === 'admin' && role === 'user') {
    const otherAdmins = db.countOtherAdmins(id);
    if (otherAdmins < 1) return NextResponse.json({ error: 'Cannot demote the last admin' }, { status: 400 });
  }
  db.updateUserRole(id, role);
  return NextResponse.json({ ok: true });
}

export async function DELETE(
  _request: Request,
  { params }: { params: Promise<{ id: string }> }
) {
  const session = await getSessionUser();
  if (!session) return NextResponse.json({ error: 'Unauthorized' }, { status: 401 });
  if (session.role !== 'admin') return NextResponse.json({ error: 'Forbidden' }, { status: 403 });
  const id = parseInt((await params).id, 10);
  if (!Number.isInteger(id) || id < 1) return NextResponse.json({ error: 'Bad request' }, { status: 400 });
  if (id === session.id) return NextResponse.json({ error: 'Cannot delete yourself' }, { status: 400 });
  const user = db.getUserById(id);
  if (!user) return NextResponse.json({ error: 'User not found' }, { status: 404 });
  const reportPath = path.resolve(USERS_DIR, String(id), 'jira_dashboard.html');
  const userDir = path.resolve(USERS_DIR, String(id));
  if (reportPath.startsWith(USERS_DIR + path.sep) || reportPath.startsWith(USERS_DIR + '/')) {
    try {
      await unlink(reportPath);
    } catch {
      // ignore
    }
    try {
      await rm(userDir, { recursive: true });
    } catch {
      // ignore
    }
  }
  db.deleteUser(id);
  return NextResponse.json({ ok: true });
}
