import { NextResponse } from 'next/server';
import { getSessionUser } from '@/lib/auth';
import * as db from '@/lib/db';

/** Heartbeat newer than this counts as "online" (worker loop sleeps 60s between runs). */
const ONLINE_MS = 3 * 60 * 1000;

function parseLastSeen(iso: string): number {
  const t = Date.parse(iso.includes('T') ? iso : iso.replace(' ', 'T'));
  return Number.isNaN(t) ? 0 : t;
}

export async function GET() {
  const session = await getSessionUser();
  if (!session) return NextResponse.json({ error: 'Unauthorized' }, { status: 401 });
  if (session.role !== 'admin') return NextResponse.json({ error: 'Forbidden' }, { status: 403 });

  const workers = db.getAllWorkerInstances();
  const now = Date.now();
  const enriched = workers.map((w) => {
    const last = parseLastSeen(w.last_seen);
    // Busy workers may run longer than ONLINE_MS without a new heartbeat row update.
    const online = w.state === 'busy' || (last > 0 && now - last < ONLINE_MS);
    return {
      ...w,
      online,
      stopRequested: w.stop_requested === 1,
    };
  });

  const onlineRows = enriched.filter((w) => w.online);
  const totalOnline = onlineRows.length;
  const free = onlineRows.filter((w) => w.state === 'idle' && !w.stopRequested).length;
  const busy = onlineRows.filter((w) => w.state === 'busy').length;
  const stopped = onlineRows.filter((w) => w.stopRequested).length;

  return NextResponse.json({
    workers: enriched,
    summary: {
      totalRegistered: workers.length,
      totalOnline,
      free,
      busy,
      stopped,
    },
  });
}
