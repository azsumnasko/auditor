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
      jira_project_keys TEXT NOT NULL
    );
    CREATE TABLE IF NOT EXISTS jobs (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
      status TEXT NOT NULL CHECK(status IN ('pending','running','done','failed')),
      created_at TEXT NOT NULL DEFAULT (datetime('now')),
      updated_at TEXT NOT NULL DEFAULT (datetime('now')),
      error_message TEXT
    );
  `);
}

export type User = { id: number; email: string; password_hash: string; created_at: string; role: string };
export type ConfigRow = { user_id: number; jira_base_url: string; jira_email: string; jira_token: string; jira_project_keys: string };
export type JobRow = { id: number; user_id: number; status: string; created_at: string; updated_at: string; error_message: string | null };

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
  return database.prepare('SELECT user_id, jira_base_url, jira_email, jira_token, jira_project_keys FROM config WHERE user_id = ?').get(userId) as ConfigRow | undefined;
}

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

export function createJob(userId: number): number {
  const database = getDb();
  const result = database.prepare('INSERT INTO jobs (user_id, status) VALUES (?, ?)').run(userId, 'pending');
  return result.lastInsertRowid as number;
}

export function getLatestJob(userId: number): { id: number; status: string; created_at: string; updated_at: string; error_message: string | null } | undefined {
  const database = getDb();
  return database.prepare(
    'SELECT id, status, created_at, updated_at, error_message FROM jobs WHERE user_id = ? ORDER BY id DESC LIMIT 1'
  ).get(userId) as { id: number; status: string; created_at: string; updated_at: string; error_message: string | null } | undefined;
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
  database.prepare('UPDATE jobs SET status = ?, updated_at = datetime(\'now\') WHERE id = ?').run('done', jobId);
}

export function setJobFailed(jobId: number, errorMessage: string): void {
  const database = getDb();
  database.prepare('UPDATE jobs SET status = ?, updated_at = datetime(\'now\'), error_message = ? WHERE id = ?').run('failed', errorMessage, jobId);
}

export function getConfigForUser(userId: number): ConfigRow | undefined {
  return getConfig(userId);
}

export type JobWithUser = { id: number; user_id: number; user_email: string; status: string; created_at: string; updated_at: string; error_message: string | null };

const JOB_STATUSES = ['pending', 'running', 'done', 'failed'] as const;

export function getAllJobs(statusFilter?: string): JobWithUser[] {
  const database = getDb();
  if (statusFilter && JOB_STATUSES.includes(statusFilter as (typeof JOB_STATUSES)[number])) {
    return database.prepare(`
      SELECT j.id, j.user_id, u.email as user_email, j.status, j.created_at, j.updated_at, j.error_message
      FROM jobs j JOIN users u ON j.user_id = u.id
      WHERE j.status = ?
      ORDER BY j.created_at DESC
    `).all(statusFilter) as JobWithUser[];
  }
  return database.prepare(`
    SELECT j.id, j.user_id, u.email as user_email, j.status, j.created_at, j.updated_at, j.error_message
    FROM jobs j JOIN users u ON j.user_id = u.id
    ORDER BY j.created_at DESC
  `).all() as JobWithUser[];
}

export type ConfigWithUser = { user_id: number; user_email: string; jira_base_url: string; jira_email: string; jira_token: string; jira_project_keys: string };

export function getAllConfigs(): ConfigWithUser[] {
  const database = getDb();
  return database.prepare(`
    SELECT c.user_id, u.email as user_email, c.jira_base_url, c.jira_email, c.jira_token, c.jira_project_keys
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
