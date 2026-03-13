import './globals.css';

export const metadata = {
  title: 'Jira Analytics Config',
  description: 'Configure Jira connection for analytics',
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="en">
      <body>
        {children}
      </body>
    </html>
  );
}
