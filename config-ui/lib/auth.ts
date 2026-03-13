import { SignJWT, jwtVerify } from 'jose';
import { cookies } from 'next/headers';
import * as db from './db';

const COOKIE_NAME = 'session';
const DEFAULT_SECRET = 'dev-secret-change-in-production';

function getSecret(): Uint8Array {
  const raw =
    process.env.SESSION_SECRET && process.env.SESSION_SECRET !== DEFAULT_SECRET
      ? process.env.SESSION_SECRET
      : process.env.NODE_ENV === 'production'
        ? null
        : DEFAULT_SECRET;
  if (raw === null) throw new Error('SESSION_SECRET must be set in production');
  return new TextEncoder().encode(raw);
}
const MAX_AGE = 60 * 60 * 24 * 7; // 7 days

export async function createSession(userId: number): Promise<string> {
  return new SignJWT({ sub: String(userId) })
    .setProtectedHeader({ alg: 'HS256' })
    .setExpirationTime(`${MAX_AGE}s`)
    .setIssuedAt()
    .sign(getSecret());
}

export async function getSessionUserId(): Promise<number | null> {
  const cookieStore = await cookies();
  const token = cookieStore.get(COOKIE_NAME)?.value;
  if (!token) return null;
  try {
    const { payload } = await jwtVerify(token, getSecret());
    const sub = payload.sub;
    if (!sub || typeof sub !== 'string') return null;
    const id = parseInt(sub, 10);
    if (!Number.isInteger(id) || id < 1) return null;
    return id;
  } catch {
    return null;
  }
}

export type SessionUser = { id: number; email: string; role: string };

export async function getSessionUser(): Promise<SessionUser | null> {
  const userId = await getSessionUserId();
  if (!userId) return null;
  const user = db.getUserById(userId);
  if (!user) return null;
  return { id: user.id, email: user.email, role: user.role };
}

export function getSessionCookieName(): string {
  return COOKIE_NAME;
}

export function getSessionMaxAge(): number {
  return MAX_AGE;
}
