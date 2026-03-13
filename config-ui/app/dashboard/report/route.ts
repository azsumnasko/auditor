import { NextResponse } from 'next/server';
import { readFile } from 'fs/promises';
import path from 'path';
import { getSessionUserId } from '@/lib/auth';

const DATA_DIR = process.env.DATA_DIR || '/data';
const USERS_DIR = path.resolve(DATA_DIR, 'users');

export async function GET() {
  const userId = await getSessionUserId();
  if (!userId) return NextResponse.json({ error: 'Unauthorized' }, { status: 401 });
  if (!Number.isInteger(userId) || userId < 1) return NextResponse.json({ error: 'Bad request' }, { status: 400 });
  const reportPath = path.resolve(DATA_DIR, 'users', String(userId), 'jira_dashboard.html');
  if (!reportPath.startsWith(USERS_DIR + path.sep) && !reportPath.startsWith(USERS_DIR + '/')) {
    return NextResponse.json({ error: 'Forbidden' }, { status: 403 });
  }
  try {
    const html = await readFile(reportPath, 'utf-8');
    return new NextResponse(html, {
      headers: { 'Content-Type': 'text/html; charset=utf-8' },
    });
  } catch {
    return new NextResponse('No report yet. Generate one from the dashboard.', {
      status: 404,
      headers: { 'Content-Type': 'text/plain; charset=utf-8' },
    });
  }
}
