import { capableClient } from '@/lib/execution-contract';
// Public readiness only; workspace data still requires authentication.
export function GET() {
    return Response.json({ service: 'scout-dashboard', status: 'ready', capabilities: {...capableClient,build:{component:'scout-dashboard',source_sha256:process.env.SCOUT_DASHBOARD_SOURCE_SHA256||'unverified'}} }, {
        headers: { 'Cache-Control': 'no-store' },
    });
}
