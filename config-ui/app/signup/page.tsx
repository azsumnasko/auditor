'use client';

import { useState } from 'react';
import { useRouter } from 'next/navigation';

export default function SignupPage() {
  const router = useRouter();
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);
    setLoading(true);
    try {
      const res = await fetch('/api/auth/signup', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ email, password }),
      });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) {
        setError(data.error || data.message || (typeof data === 'string' ? data : 'Sign up failed'));
        return;
      }
      router.push('/');
      router.refresh();
    } catch {
      setError('Sign up failed');
    } finally {
      setLoading(false);
    }
  };

  return (
    <main>
      <p><a href="/">Jira Analytics</a></p>
      <h1>Sign up</h1>
      <p><a href="/login">Log in</a> if you already have an account.</p>
      {error && <p style={{ color: 'crimson' }}>{error}</p>}
      <form onSubmit={handleSubmit} style={{ display: 'flex', flexDirection: 'column', gap: '0.75rem' }}>
        <label>
          Email
          <input type="email" value={email} onChange={(e) => setEmail(e.target.value)} required style={{ display: 'block', width: '100%', marginTop: 2, padding: 6 }} />
        </label>
        <label>
          Password (min 8 characters)
          <input type="password" value={password} onChange={(e) => setPassword(e.target.value)} required minLength={8} style={{ display: 'block', width: '100%', marginTop: 2, padding: 6 }} />
        </label>
        <button type="submit" disabled={loading} style={{ padding: '8px 12px', cursor: loading ? 'wait' : 'pointer' }}>{loading ? 'Signing up…' : 'Sign up'}</button>
      </form>
    </main>
  );
}
