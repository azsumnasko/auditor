'use client';

import { Suspense, useState } from 'react';
import { useRouter, useSearchParams } from 'next/navigation';

function LoginForm() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const rawFrom = searchParams.get('from') || '/';
  const from = rawFrom.startsWith('/') && !rawFrom.startsWith('//') ? rawFrom : '/';
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);
    setLoading(true);
    try {
      const res = await fetch('/api/auth/login', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ email, password }),
      });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) {
        setError(data.error || data.message || (typeof data === 'string' ? data : 'Login failed'));
        return;
      }
      router.push(from);
      router.refresh();
    } catch {
      setError('Login failed');
    } finally {
      setLoading(false);
    }
  };

  return (
    <main>
      <p><a href="/">Jira Analytics</a></p>
      <h1>Log in</h1>
      <p><a href="/signup">Sign up</a> if you don’t have an account.</p>
      {error && <p style={{ color: 'crimson' }}>{error}</p>}
      <form onSubmit={handleSubmit} style={{ display: 'flex', flexDirection: 'column', gap: '0.75rem' }}>
        <label>
          Email
          <input type="email" value={email} onChange={(e) => setEmail(e.target.value)} required style={{ display: 'block', width: '100%', marginTop: 2, padding: 6 }} />
        </label>
        <label>
          Password
          <input type="password" value={password} onChange={(e) => setPassword(e.target.value)} required style={{ display: 'block', width: '100%', marginTop: 2, padding: 6 }} />
        </label>
        <button type="submit" disabled={loading} style={{ padding: '8px 12px', cursor: loading ? 'wait' : 'pointer' }}>{loading ? 'Logging in…' : 'Log in'}</button>
      </form>
    </main>
  );
}

export default function LoginPage() {
  return (
    <Suspense fallback={<main><p><a href="/">Jira Analytics</a></p><h1>Log in</h1><p>Loading…</p></main>}>
      <LoginForm />
    </Suspense>
  );
}
