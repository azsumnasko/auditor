import { NextRequest, NextResponse } from 'next/server';
import * as db from '@/lib/db';
import { getSessionUserId } from '@/lib/auth';

function maskEmail(email: string): string {
  if (!email || email.length < 3) return '***';
  return email[0] + '***' + email[email.length - 1];
}

export async function GET() {
  const userId = await getSessionUserId();
  if (!userId) return NextResponse.json({ error: 'Unauthorized' }, { status: 401 });
  const config = db.getConfig(userId);
  if (!config) {
    return NextResponse.json({ configured: false });
  }
  return NextResponse.json({
    configured: true,
    emailHint: maskEmail(config.jira_email),
    JIRA_BASE_URL: config.jira_base_url,
    JIRA_PROJECT_KEYS: config.jira_project_keys,
  });
}

export async function POST(request: NextRequest) {
  const userId = await getSessionUserId();
  if (!userId) return NextResponse.json({ error: 'Unauthorized' }, { status: 401 });
  let body: Record<string, string>;
  try {
    body = await request.json();
  } catch {
    return NextResponse.json({ error: 'Invalid JSON' }, { status: 400 });
  }
  const KEYS = ['JIRA_BASE_URL', 'JIRA_EMAIL', 'JIRA_TOKEN', 'JIRA_PROJECT_KEYS'] as const;
  const MAX_LEN: Record<string, number> = { JIRA_BASE_URL: 2048, JIRA_EMAIL: 256, JIRA_TOKEN: 2048, JIRA_PROJECT_KEYS: 500 };
  const values: Record<string, string> = {};
  for (const key of KEYS) {
    const value = body[key];
    if (value == null || typeof value !== 'string') {
      return NextResponse.json({ error: `Missing or invalid: ${key}` }, { status: 400 });
    }
    const trimmed = value.trim();
    if (!trimmed) return NextResponse.json({ error: `${key} is required` }, { status: 400 });
    if (trimmed.length > (MAX_LEN[key] ?? 2048)) {
      return NextResponse.json({ error: `${key} is too long` }, { status: 400 });
    }
    values[key] = trimmed;
  }
  try {
    new URL(values.JIRA_BASE_URL.startsWith('http') ? values.JIRA_BASE_URL : `https://${values.JIRA_BASE_URL}`);
  } catch {
    return NextResponse.json({ error: 'JIRA Base URL must be a valid URL' }, { status: 400 });
  }
  try {
    db.upsertConfig(
      userId,
      values.JIRA_BASE_URL,
      values.JIRA_EMAIL,
      values.JIRA_TOKEN,
      values.JIRA_PROJECT_KEYS
    );
    return NextResponse.json({ ok: true });
  } catch (e) {
    return NextResponse.json({ error: 'Failed to save config' }, { status: 500 });
  }
}
