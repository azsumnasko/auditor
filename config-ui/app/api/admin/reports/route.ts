import { NextResponse } from 'next/server';
import { getSessionUser } from '@/lib/auth';
import { readdir, access } from 'fs/promises';
import path from 'path';
import * as db from '@/lib/db';

const DATA_DIR = process.env.DATA_DIR || '/data';
const USERS_DIR = path.resolve(DATA_DIR, 'users');

export async function GET() {
  const session = await getSessionUser();
  if (!session) return NextResponse.json({ error: 'Unauthorized' }, { status: 401 });
  if (session.role !== 'admin') return NextResponse.json({ error: 'Forbidden' }, { status: 403 });
  const list: { user_id: number; user_email: string; has_report: boolean }[] = [];
  try {
    const userIds = await readdir(USERS_DIR);
    for (const uid of userIds) {
      const id = parseInt(uid, 10);
      if (!Number.isInteger(id) || id < 1 || String(id) !== uid) continue;
      const reportPath = path.join(USERS_DIR, String(id), 'jira_dashboard.html');
      let hasReport = false;
      try {
        await access(reportPath);
        hasReport = true;
      } catch {
        // no report file
      }
      const user = db.getUserById(id);
      list.push({ user_id: id, user_email: user?.email ?? '', has_report: hasReport });
    }
  } catch {
    // directory may not exist
  }
  list.sort((a, b) => a.user_id - b.user_id);
  return NextResponse.json(list);
}
