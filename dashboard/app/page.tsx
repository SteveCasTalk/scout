import Dashboard from './workspace';
import { requireChatGPTUser } from './chatgpt-auth';
export const dynamic = 'force-dynamic';
export default async function Home({ searchParams }: { searchParams: Promise<Record<string, string | string[] | undefined>> }) {
    const params = await searchParams;
    const query = new URLSearchParams();
    for (const key of ['workspace', 'project', 'syncRun']) {
        const value = params[key];
        if (typeof value === 'string') query.set(key, value);
    }
    const returnTo = query.size ? `/?${query}` : '/';
    await requireChatGPTUser(returnTo);
    return <Dashboard />;
}
