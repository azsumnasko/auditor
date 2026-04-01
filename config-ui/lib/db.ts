import Database from 'better-sqlite3';
import { mkdirSync } from 'fs';
import path from 'path';

const DATA_DIR = process.env.DATA_DIR || '/data';
const DB_PATH = path.join(DATA_DIR, 'app.db');

let db: Database.Database | null = null;

function getDb(): Database.Database {
  if (db) return db;
  mkdirSync(DATA_DIR, { recursive: true });
  db = new Database(DB_PATH);
  initSchema(db);
  return db;
}

function initSchema(database: Database.Database) {
  database.pragma('journal_mode = WAL');
  database.exec(`
    CREATE TABLE IF NOT EXISTS users (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      email TEXT UNIQUE NOT NULL,
      password_hash TEXT NOT NULL,
      created_at TEXT NOT NULL DEFAULT (datetime('now')),
      role TEXT NOT NULL DEFAULT 'user' CHECK(role IN ('user','admin'))
    );
  `);
  // Migration: add role column to existing DBs that don't have it
  const tableInfo = database.prepare("PRAGMA table_info(users)").all() as { name: string }[];
  if (tableInfo && !tableInfo.some((c) => c.name === 'role')) {
    database.exec(`ALTER TABLE users ADD COLUMN role TEXT NOT NULL DEFAULT 'user'`);
  }
  database.exec(`
    CREATE TABLE IF NOT EXISTS config (
      user_id INTEGER PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
      jira_base_url TEXT NOT NULL,
      jira_email TEXT NOT NULL,
      jira_token TEXT NOT NULL,
      jira_project_keys TEXT NOT NULL,
      git_provider TEXT DEFAULT NULL,
      git_base_url TEXT DEFAULT NULL,
      git_token TEXT DEFAULT NULL,
      git_org TEXT DEFAULT NULL,
      git_repos TEXT DEFAULT NULL,
      cicd_provider TEXT DEFAULT NULL,
      cicd_deploy_workflow TEXT DEFAULT NULL,
      octopus_server_url TEXT DEFAULT NULL,
      octopus_api_key TEXT DEFAULT NULL,
      octopus_environment TEXT DEFAULT 'Ontario',
      octopus_repo_map TEXT DEFAULT NULL,
      repo_config TEXT DEFAULT NULL
    );
    CREATE TABLE IF NOT EXISTS jobs (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
      status TEXT NOT NULL CHECK(status IN ('pending','running','done','failed')),
      created_at TEXT NOT NULL DEFAULT (datetime('now')),
      updated_at TEXT NOT NULL DEFAULT (datetime('now')),
      error_message TEXT,
      progress_message TEXT
    );
  `);
  const jobsCols = database.prepare("PRAGMA table_info(jobs)").all() as { name: string }[];
  if (jobsCols && !jobsCols.some((c) => c.name === 'progress_message')) {
    database.exec(`ALTER TABLE jobs ADD COLUMN progress_message TEXT`);
  }
  // Migration: add Git/CI-CD/Octopus columns to existing config tables that lack them
  const configCols = database.prepare("PRAGMA table_info(config)").all() as { name: string }[];
  const configColNames = new Set(configCols.map((c) => c.name));
  const newCols: [string, string][] = [
    ['git_provider', 'TEXT DEFAULT NULL'],
    ['git_base_url', 'TEXT DEFAULT NULL'],
    ['git_token', 'TEXT DEFAULT NULL'],
    ['git_org', 'TEXT DEFAULT NULL'],
    ['git_repos', 'TEXT DEFAULT NULL'],
    ['cicd_provider', 'TEXT DEFAULT NULL'],
    ['cicd_deploy_workflow', 'TEXT DEFAULT NULL'],
    ['octopus_server_url', 'TEXT DEFAULT NULL'],
    ['octopus_api_key', 'TEXT DEFAULT NULL'],
    ['octopus_environment', "TEXT DEFAULT 'Ontario'"],
    ['octopus_repo_map', 'TEXT DEFAULT NULL'],
    ['repo_config', 'TEXT DEFAULT NULL'],
  ];
  for (const [col, def] of newCols) {
    if (!configColNames.has(col)) {
      database.exec(`ALTER TABLE config ADD COLUMN ${col} ${def}`);
    }
  }
}

export type User = { id: number; email: string; password_hash: string; created_at: string; role: string };
export type ConfigRow = {
  user_id: number;
  jira_base_url: string;
  jira_email: string;
  jira_token: string;
  jira_project_keys: string;
  git_provider: string | null;
  git_base_url: string | null;
  git_token: string | null;
  git_org: string | null;
  git_repos: string | null;
  cicd_provider: string | null;
  cicd_deploy_workflow: string | null;
  octopus_server_url: string | null;
  octopus_api_key: string | null;
  octopus_environment: string | null;
  octopus_repo_map: string | null;
  repo_config: string | null;
};
export type JobRow = {
  id: number;
  user_id: number;
  status: string;
  created_at: string;
  updated_at: string;
  error_message: string | null;
  progress_message: string | null;
};

/** Latest job row for a user (from `getLatestJob`). */
export type LatestJobRow = {
  id: number;
  status: string;
  created_at: string;
  updated_at: string;
  error_message: string | null;
  progress_message: string | null;
};

export function createUser(email: string, passwordHash: string): { id: number } {
  const database = getDb();
  const stmt = database.prepare('INSERT INTO users (email, password_hash, role) VALUES (?, ?, ?)');
  const result = stmt.run(email.toLowerCase().trim(), passwordHash, 'user');
  return { id: result.lastInsertRowid as number };
}

export function getUserByEmail(email: string): User | undefined {
  const database = getDb();
  return database.prepare('SELECT id, email, password_hash, created_at, role FROM users WHERE email = ?').get(email.toLowerCase().trim()) as User | undefined;
}

export function getUserById(id: number): User | undefined {
  const database = getDb();
  return database.prepare('SELECT id, email, password_hash, created_at, role FROM users WHERE id = ?').get(id) as User | undefined;
}

export type UserPublic = { id: number; email: string; role: string; created_at: string };

export function getAllUsers(): UserPublic[] {
  const database = getDb();
  return database.prepare('SELECT id, email, role, created_at FROM users ORDER BY id').all() as UserPublic[];
}

export function updateUserRole(id: number, role: 'user' | 'admin'): void {
  const database = getDb();
  database.prepare('UPDATE users SET role = ? WHERE id = ?').run(role, id);
}

export function deleteUser(id: number): void {
  const database = getDb();
  database.prepare('DELETE FROM users WHERE id = ?').run(id);
}

export function countAdmins(): number {
  const database = getDb();
  const row = database.prepare("SELECT COUNT(*) as n FROM users WHERE role = 'admin'").get() as { n: number };
  return row?.n ?? 0;
}

/** Count admins excluding one user (for safe demotion check – avoids TOCTOU). */
export function countOtherAdmins(excludeUserId: number): number {
  const database = getDb();
  const row = database.prepare("SELECT COUNT(*) as n FROM users WHERE role = 'admin' AND id != ?").get(excludeUserId) as { n: number };
  return row?.n ?? 0;
}

export function getConfig(userId: number): ConfigRow | undefined {
  const database = getDb();
  return database.prepare('SELECT * FROM config WHERE user_id = ?').get(userId) as ConfigRow | undefined;
}

export type ConfigInput = {
  jira_base_url: string;
  jira_email: string;
  jira_token?: string;
  jira_project_keys: string;
  git_provider?: string | null;
  git_base_url?: string | null;
  git_token?: string | null;
  git_org?: string | null;
  git_repos?: string | null;
  cicd_provider?: string | null;
  cicd_deploy_workflow?: string | null;
  octopus_server_url?: string | null;
  octopus_api_key?: string | null;
  octopus_environment?: string | null;
  octopus_repo_map?: string | null;
  repo_config?: string | null;
};

export function upsertConfig(userId: number, jiraBaseUrl: string, jiraEmail: string, jiraToken: string, jiraProjectKeys: string): void {
  const database = getDb();
  database.prepare(`
    INSERT INTO config (user_id, jira_base_url, jira_email, jira_token, jira_project_keys)
    VALUES (?, ?, ?, ?, ?)
    ON CONFLICT(user_id) DO UPDATE SET
      jira_base_url = excluded.jira_base_url,
      jira_email = excluded.jira_email,
      jira_token = excluded.jira_token,
      jira_project_keys = excluded.jira_project_keys
  `).run(userId, jiraBaseUrl, jiraEmail, jiraToken, jiraProjectKeys);
}

export function updateConfigKeepToken(userId: number, jiraBaseUrl: string, jiraEmail: string, jiraProjectKeys: string): void {
  const database = getDb();
  database.prepare(`
    UPDATE config SET
      jira_base_url = ?,
      jira_email = ?,
      jira_project_keys = ?
    WHERE user_id = ?
  `).run(jiraBaseUrl, jiraEmail, jiraProjectKeys, userId);
}

export function updateConfigExtras(userId: number, extras: Partial<ConfigInput>): void {
  const database = getDb();
  const fields: string[] = [];
  const values: (string | null)[] = [];
  const allowed = ['git_provider','git_base_url','git_token','git_org','git_repos','cicd_provider','cicd_deploy_workflow','octopus_server_url','octopus_api_key','octopus_environment','octopus_repo_map','repo_config'] as const;
  for (const key of allowed) {
    if (key in extras) {
      fields.push(`${key} = ?`);
      values.push((extras as Record<string, string | null | undefined>)[key] ?? null);
    }
  }
  if (fields.length === 0) return;
  values.push(String(userId));
  database.prepare(`UPDATE config SET ${fields.join(', ')} WHERE user_id = ?`).run(...values);
}

export function createJob(userId: number): number {
  const database = getDb();
  const result = database.prepare('INSERT INTO jobs (user_id, status) VALUES (?, ?)').run(userId, 'pending');
  return result.lastInsertRowid as number;
}

export function getLatestJob(userId: number): LatestJobRow | undefined {
  const database = getDb();
  return database
    .prepare(
      'SELECT id, status, created_at, updated_at, error_message, progress_message FROM jobs WHERE user_id = ? ORDER BY id DESC LIMIT 1'
    )
    .get(userId) as LatestJobRow | undefined;
}

/** Count jobs created by this user in the last 60 minutes (for rate limiting). */
export function countJobsCreatedInLastHour(userId: number): number {
  const database = getDb();
  const row = database.prepare(
    `SELECT COUNT(*) as n FROM jobs WHERE user_id = ? AND created_at >= datetime('now', '-1 hour')`
  ).get(userId) as { n: number };
  return row?.n ?? 0;
}

export function claimNextPendingJob(): { id: number; user_id: number } | undefined {
  const database = getDb();
  const row = database.prepare(
    'SELECT id, user_id FROM jobs WHERE status = ? ORDER BY created_at ASC LIMIT 1'
  ).get('pending') as { id: number; user_id: number } | undefined;
  if (!row) return undefined;
  database.prepare('UPDATE jobs SET status = ?, updated_at = datetime(\'now\') WHERE id = ?').run('running', row.id);
  return row;
}

export function setJobDone(jobId: number): void {
  const database = getDb();
  database
    .prepare(
      `UPDATE jobs SET status = ?, updated_at = datetime('now'), progress_message = NULL WHERE id = ?`
    )
    .run('done', jobId);
}

export function setJobFailed(jobId: number, errorMessage: string): void {
  const database = getDb();
  database
    .prepare(
      `UPDATE jobs SET status = ?, updated_at = datetime('now'), error_message = ?, progress_message = NULL WHERE id = ?`
    )
    .run('failed', errorMessage, jobId);
}

export function getConfigForUser(userId: number): ConfigRow | undefined {
  return getConfig(userId);
}

export type JobWithUser = {
  id: number;
  user_id: number;
  user_email: string;
  status: string;
  created_at: string;
  updated_at: string;
  error_message: string | null;
  progress_message: string | null;
};

const JOB_STATUSES = ['pending', 'running', 'done', 'failed'] as const;

export function getAllJobs(statusFilter?: string): JobWithUser[] {
  const database = getDb();
  if (statusFilter && JOB_STATUSES.includes(statusFilter as (typeof JOB_STATUSES)[number])) {
    return database.prepare(`
      SELECT j.id, j.user_id, u.email as user_email, j.status, j.created_at, j.updated_at, j.error_message, j.progress_message
      FROM jobs j JOIN users u ON j.user_id = u.id
      WHERE j.status = ?
      ORDER BY j.created_at DESC
    `).all(statusFilter) as JobWithUser[];
  }
  return database.prepare(`
    SELECT j.id, j.user_id, u.email as user_email, j.status, j.created_at, j.updated_at, j.error_message, j.progress_message
    FROM jobs j JOIN users u ON j.user_id = u.id
    ORDER BY j.created_at DESC
  `).all() as JobWithUser[];
}

export type ConfigWithUser = ConfigRow & { user_email: string };

export function getAllConfigs(): ConfigWithUser[] {
  const database = getDb();
  return database.prepare(`
    SELECT c.*, u.email as user_email
    FROM config c JOIN users u ON c.user_id = u.id
    ORDER BY c.user_id
  `).all() as ConfigWithUser[];
}

export function deleteConfig(userId: number): void {
  const database = getDb();
  database.prepare('DELETE FROM config WHERE user_id = ?').run(userId);
}

export function getJobById(id: number): { id: number; user_id: number; status: string } | undefined {
  const database = getDb();
  return database.prepare('SELECT id, user_id, status FROM jobs WHERE id = ?').get(id) as { id: number; user_id: number; status: string } | undefined;
}
