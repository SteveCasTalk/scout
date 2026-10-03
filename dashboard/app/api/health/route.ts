// Public readiness only; workspace data still requires authentication.
export function GET() {
    return Response.json({ service: 'scout-dashboard', status: 'ready' }, {
        headers: { 'Cache-Control': 'no-store' },
    });
}
