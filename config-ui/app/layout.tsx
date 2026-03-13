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
      <body style={{ fontFamily: 'system-ui, sans-serif', margin: '1rem 2rem', maxWidth: 560 }}>
        {children}
      </body>
    </html>
  );
}
