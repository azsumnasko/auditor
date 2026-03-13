import { redirect } from 'next/navigation';
import { getSessionUser } from '@/lib/auth';
import AppNav from '@/app/components/AppNav';

export default async function AdminLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  const user = await getSessionUser();
  if (!user || user.role !== 'admin') {
    redirect('/dashboard');
  }
  return (
    <div className="dashboard">
      <AppNav activePage="admin" showAdminLink={true} />
      <div className="dashboard-content" style={{ maxWidth: '1200px' }}>
        {children}
      </div>
    </div>
  );
}
