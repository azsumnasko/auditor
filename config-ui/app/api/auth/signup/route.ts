import { NextRequest, NextResponse } from 'next/server';
import { hash } from 'bcryptjs';
import * as db from '@/lib/db';
import { createSession, getSessionCookieName, getSessionMaxAge } from '@/lib/auth';

export async function POST(request: NextRequest) {
  let body: { email?: string; password?: string };
  try {
    body = await request.json();
  } catch {
    return NextResponse.json({ error: 'Invalid JSON' }, { status: 400 });
  }
  const email = typeof body.email === 'string' ? body.email.trim().toLowerCase() : '';
  const password = typeof body.password === 'string' ? body.password : '';
  if (!email || !password) {
    return NextResponse.json({ error: 'Email and password required' }, { status: 400 });
  }
  if (!/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email)) {
    return NextResponse.json({ error: 'Invalid email format' }, { status: 400 });
  }
  if (password.length < 8) {
    return NextResponse.json({ error: 'Password must be at least 8 characters' }, { status: 400 });
  }
  const existing = db.getUserByEmail(email);
  if (existing) {
    return NextResponse.json({ error: 'Email already registered' }, { status: 409 });
  }
  const passwordHash = await hash(password, 10);
  let id: number;
  try {
    const result = db.createUser(email, passwordHash);
    id = result.id;
  } catch (e) {
    const err = e as { code?: string; message?: string };
    if (err?.code === 'SQLITE_CONSTRAINT_UNIQUE' || err?.message?.includes('UNIQUE')) {
      return NextResponse.json({ error: 'Email already registered' }, { status: 409 });
    }
    throw e;
  }
  const token = await createSession(id);
  const res = NextResponse.json({ ok: true });
  res.cookies.set(getSessionCookieName(), token, {
    httpOnly: true,
    secure: process.env.NODE_ENV === 'production',
    sameSite: 'lax',
    maxAge: getSessionMaxAge(),
    path: '/',
  });
  return res;
}
