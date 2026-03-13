'use client';

import { useState, useEffect } from 'react';

type User = { id: number; email: string; role: string; created_at: string };

export default function AdminUsersPage() {
  const [users, setUsers] = useState<User[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [updatingId, setUpdatingId] = useState<number | null>(null);
  const [deletingId, setDeletingId] = useState<number | null>(null);

  const fetchUsers = () => {
    fetch('/api/admin/users', { credentials: 'include' })
      .then((r) => {
        if (r.status === 403) window.location.href = '/dashboard';
        return r.json();
      })
      .then((data) => {
        if (Array.isArray(data)) setUsers(data);
        else setError('Failed to load users');
      })
      .catch(() => setError('Failed to load users'))
      .finally(() => setLoading(false));
  };

  useEffect(() => {
    fetchUsers();
  }, []);

  const setRole = (id: number, role: 'user' | 'admin') => {
    setUpdatingId(id);
    fetch(`/api/admin/users/${id}`, {
      method: 'PATCH',
      credentials: 'include',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ role }),
    })
      .then((r) => r.json().then((d) => ({ ok: r.ok, data: d })))
      .then(({ ok, data }) => {
        if (ok) {
          setError(null);
          fetchUsers();
        } else setError(data.error || 'Failed to update');
      })
      .finally(() => setUpdatingId(null));
  };

  const deleteUser = (id: number, email: string) => {
    if (!confirm(`Delete user ${email}? This will remove their config and jobs.`)) return;
    setDeletingId(id);
    fetch(`/api/admin/users/${id}`, { method: 'DELETE', credentials: 'include' })
      .then((r) => r.json().then((d) => ({ ok: r.ok, data: d })))
      .then(({ ok, data }) => {
        if (ok) {
          setError(null);
          fetchUsers();
        } else setError(data.error || 'Failed to delete');
      })
      .finally(() => setDeletingId(null));
  };

  return (
    <>
      <h1 className="dashboard-title">Admin – Users</h1>
        <p className="text-muted" style={{ marginBottom: '1rem' }}>
          <a href="/admin">Admin</a> → Users
        </p>
        {error && <p className="text-error">{error}</p>}
        {loading ? (
          <p className="text-muted">Loading…</p>
        ) : (
          <section className="card">
            <table style={{ width: '100%', borderCollapse: 'collapse' }}>
              <thead>
                <tr style={{ borderBottom: '1px solid var(--border)', textAlign: 'left' }}>
                  <th style={{ padding: '8px' }}>Email</th>
                  <th style={{ padding: '8px' }}>Role</th>
                  <th style={{ padding: '8px' }}>Created</th>
                  <th style={{ padding: '8px' }}>Actions</th>
                </tr>
              </thead>
              <tbody>
                {users.map((u) => (
                  <tr key={u.id} style={{ borderBottom: '1px solid var(--border)' }}>
                    <td style={{ padding: '8px' }}>{u.email}</td>
                    <td style={{ padding: '8px' }}>{u.role}</td>
                    <td style={{ padding: '8px', color: 'var(--text-secondary)' }}>{u.created_at}</td>
                    <td style={{ padding: '8px' }}>
                      <select
                        value={u.role}
                        disabled={updatingId === u.id}
                        onChange={(e) => setRole(u.id, e.target.value as 'user' | 'admin')}
                        style={{ marginRight: '8px' }}
                      >
                        <option value="user">user</option>
                        <option value="admin">admin</option>
                      </select>
                      <button
                        type="button"
                        disabled={deletingId === u.id}
                        onClick={() => deleteUser(u.id, u.email)}
                        className="text-error"
                        style={{ background: 'none', border: 'none', cursor: 'pointer', padding: 0 }}
                      >
                        Delete
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </section>
        )}
    </>
  );
}
