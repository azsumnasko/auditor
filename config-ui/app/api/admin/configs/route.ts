import { NextResponse } from 'next/server';
import { getSessionUser } from '@/lib/auth';
import * as db from '@/lib/db';

function maskToken(token: string): string {
  if (!token || token.length <= 4) return '***';
  return '***' + token.slice(-4);
}

export async function GET() {
  const session = await getSessionUser();
  if (!session) return NextResponse.json({ error: 'Unauthorized' }, { status: 401 });
  if (session.role !== 'admin') return NextResponse.json({ error: 'Forbidden' }, { status: 403 });
  const configs = db.getAllConfigs();
  const list = configs.map((c) => ({
    user_id: c.user_id,
    user_email: c.user_email,
    jira_base_url: c.jira_base_url,
    jira_email: c.jira_email,
    jira_token: maskToken(c.jira_token),
    jira_project_keys: c.jira_project_keys,
  }));
  return NextResponse.json(list);
}
