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
    return NextResponse.json({ configured: false, tokenSaved: false });
  }
  return NextResponse.json({
    configured: true,
    tokenSaved: true,
    emailHint: maskEmail(config.jira_email),
    JIRA_BASE_URL: config.jira_base_url,
    JIRA_EMAIL: config.jira_email,
    JIRA_PROJECT_KEYS: config.jira_project_keys,
    GIT_PROVIDER: config.git_provider || '',
    GIT_BASE_URL: config.git_base_url || '',
    GIT_ORG: config.git_org || '',
    GIT_REPOS: config.git_repos || '',
    GIT_TOKEN_SAVED: !!config.git_token,
    CICD_PROVIDER: config.cicd_provider || '',
    CICD_DEPLOY_WORKFLOW: config.cicd_deploy_workflow || '',
    OCTOPUS_SERVER_URL: config.octopus_server_url || '',
    OCTOPUS_ENVIRONMENT: config.octopus_environment || 'Ontario',
    OCTOPUS_REPO_MAP: config.octopus_repo_map || '',
    OCTOPUS_TOKEN_SAVED: !!config.octopus_api_key,
    REPO_CONFIG: config.repo_config || '[]',
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
  const MAX_LEN: Record<string, number> = { JIRA_BASE_URL: 2048, JIRA_EMAIL: 256, JIRA_TOKEN: 2048, JIRA_PROJECT_KEYS: 500 };
  const REQUIRED_KEYS = ['JIRA_BASE_URL', 'JIRA_EMAIL', 'JIRA_PROJECT_KEYS'] as const;
  const values: Record<string, string> = {};
  for (const key of REQUIRED_KEYS) {
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
  const tokenValue = (body.JIRA_TOKEN ?? '').trim();
  if (tokenValue && tokenValue.length > MAX_LEN.JIRA_TOKEN) {
    return NextResponse.json({ error: 'JIRA_TOKEN is too long' }, { status: 400 });
  }
  try {
    new URL(values.JIRA_BASE_URL.startsWith('http') ? values.JIRA_BASE_URL : `https://${values.JIRA_BASE_URL}`);
  } catch {
    return NextResponse.json({ error: 'JIRA Base URL must be a valid URL' }, { status: 400 });
  }
  try {
    const existing = db.getConfig(userId);
    if (tokenValue) {
      db.upsertConfig(userId, values.JIRA_BASE_URL, values.JIRA_EMAIL, tokenValue, values.JIRA_PROJECT_KEYS);
    } else if (existing) {
      db.updateConfigKeepToken(userId, values.JIRA_BASE_URL, values.JIRA_EMAIL, values.JIRA_PROJECT_KEYS);
    } else {
      return NextResponse.json({ error: 'JIRA_TOKEN is required for initial setup' }, { status: 400 });
    }
    // Save Git/CI-CD/Octopus extras (only update non-token fields always; tokens only when provided)
    const extras: Record<string, string | null> = {};
    const stringFields = ['GIT_PROVIDER','GIT_BASE_URL','GIT_ORG','GIT_REPOS','CICD_PROVIDER','CICD_DEPLOY_WORKFLOW','OCTOPUS_SERVER_URL','OCTOPUS_ENVIRONMENT','OCTOPUS_REPO_MAP','REPO_CONFIG'] as const;
    const fieldMap: Record<string, string> = {
      GIT_PROVIDER: 'git_provider', GIT_BASE_URL: 'git_base_url', GIT_ORG: 'git_org',
      GIT_REPOS: 'git_repos', CICD_PROVIDER: 'cicd_provider', CICD_DEPLOY_WORKFLOW: 'cicd_deploy_workflow',
      OCTOPUS_SERVER_URL: 'octopus_server_url', OCTOPUS_ENVIRONMENT: 'octopus_environment', OCTOPUS_REPO_MAP: 'octopus_repo_map',
      REPO_CONFIG: 'repo_config',
    };
    for (const key of stringFields) {
      if (key in body) {
        extras[fieldMap[key]] = (body[key] ?? '').trim() || null;
      }
    }
    if (body.GIT_TOKEN && (body.GIT_TOKEN as string).trim()) extras.git_token = (body.GIT_TOKEN as string).trim();
    if (body.OCTOPUS_API_KEY && (body.OCTOPUS_API_KEY as string).trim()) extras.octopus_api_key = (body.OCTOPUS_API_KEY as string).trim();
    if (Object.keys(extras).length > 0) {
      db.updateConfigExtras(userId, extras);
    }
    return NextResponse.json({ ok: true });
  } catch (e) {
    return NextResponse.json({ error: 'Failed to save config' }, { status: 500 });
  }
}
