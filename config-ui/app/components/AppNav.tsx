'use client';

import { useState, useEffect } from 'react';

type Page = 'config' | 'dashboard' | 'admin';

export default function AppNav({ activePage, showAdminLink }: { activePage: Page; showAdminLink?: boolean }) {
  const [isAdmin, setIsAdmin] = useState<boolean | null>(showAdminLink !== undefined ? showAdminLink : null);

  useEffect(() => {
    if (showAdminLink !== undefined) return;
    fetch('/api/me', { credentials: 'include' })
      .then((r) => r.ok ? r.json() : null)
      .then((data) => setIsAdmin(data?.role === 'admin' ?? false))
      .catch(() => setIsAdmin(false));
  }, [showAdminLink]);

  const handleLogout = () => {
    fetch('/api/auth/logout', { method: 'POST', credentials: 'include' }).then(() => {
      window.location.href = '/login';
    });
  };

  const showAdmin = showAdminLink === true || (showAdminLink === undefined && isAdmin === true);

  return (
    <nav className="dashboard-nav">
      <a href="/" className={activePage === 'config' ? 'nav-active' : ''}>Config</a>
      <span className="nav-sep">|</span>
      <a href="/dashboard" className={activePage === 'dashboard' ? 'nav-active' : ''}>Dashboard</a>
      {showAdmin && (
        <>
          <span className="nav-sep">|</span>
          <a href="/admin" className={activePage === 'admin' ? 'nav-active' : ''}>Admin</a>
        </>
      )}
      <span className="nav-sep">|</span>
      <button type="button" onClick={handleLogout}>Logout</button>
    </nav>
  );
}
