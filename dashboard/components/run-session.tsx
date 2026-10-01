'use client';
import { useEffect, useRef, useState } from 'react';
import { Play, RefreshCw, Square } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogDescription } from '@/components/ui/dialog';
import { CheckpointReport } from './checkpoints';
import type { CheckpointResult, TestCase } from '@/lib/contracts';
const BRIDGE = 'http://127.0.0.1:8765';
type Job = { checkpoint_results?: CheckpointResult[]; run_id: string; status: string; steps: { step: number; operation: string; label?: string; screenshot?: string; elapsed_ms?: number }[]; text_request?: { field: { label: string }; instruction: string }; result?: Record<string, unknown>; artifacts?: string[]; error?: string };
type Session = { cases: TestCase[]; index: number; serial: string; mode: string; limit: number; jobId: string; outcomes: string[] };
async function bridge<T = Record<string, unknown>>(path: string, body?: unknown) {
    const response = await fetch(BRIDGE + path, body === undefined ? {} : { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) });
    const data = await response.json() as T & { error?: string };
    if (!response.ok) throw new Error((response.status === 404 ? 'SESSION_MISSING: ' : '') + (data.error || 'Local runner request failed.'));
    return data;
}
export function RunSession({ requested, onClose, onComplete, onBusy }: { requested: TestCase[] | null; onClose: () => void; onComplete: (job: Job) => Promise<void>; onBusy: (id: string | null) => void }) {
    const [ordered, setOrdered] = useState<TestCase[]>([]);
    const [devices, setDevices] = useState<string[]>([]), [serial, setSerial] = useState(''), [mode, setMode] = useState('current'), [limit, setLimit] = useState(40), [confirmed, setConfirmed] = useState(false);
    const [session, setSession] = useState<Session | null>(null), [job, setJob] = useState<Job | null>(null), [error, setError] = useState(''), [pending, setPending] = useState(false), [text, setText] = useState(''), [stopping, setStopping] = useState(false);
    const completion = useRef(onComplete), busy = useRef(onBusy), processing = useRef(false);
    completion.current = onComplete; busy.current = onBusy;
    useEffect(() => { try { const saved = sessionStorage.getItem('jev-run-session'); if (saved) setSession(JSON.parse(saved)); } catch { sessionStorage.removeItem('jev-run-session'); } }, []);
    useEffect(() => { if (session) sessionStorage.setItem('jev-run-session', JSON.stringify(session)); else sessionStorage.removeItem('jev-run-session'); busy.current(session?.cases[session.index]?.id || null); }, [session]);
    async function refreshDevices() { setError(''); try { const data = await bridge<{ devices: string[] }>('/devices'); setDevices(data.devices || []); setSerial(''); } catch (e) { setError((e as Error).message); } }
    useEffect(() => { if (requested) { setOrdered(requested); setConfirmed(false); setError(''); void refreshDevices(); } }, [requested]);
    async function launch(next: Session) {
        const test = next.cases[next.index];
        const data = await bridge<{ run_id: string }>('/jobs', { case: test, serial: next.serial, start_mode: next.mode, max_steps: next.limit, conditions_confirmed: true });
        setJob(null); setText(''); setSession({ ...next, jobId: data.run_id });
    }
    async function start() {
        if (!requested?.length || !serial || !confirmed || pending || session) return;
        setPending(true); setError(''); setStopping(false);
        try { await launch({ cases: ordered, index: 0, serial, mode, limit, jobId: '', outcomes: [] }); onClose(); } catch (e) { setError((e as Error).message); } finally { setPending(false); }
    }
    useEffect(() => {
        if (!session?.jobId) return;
        let disposed = false; let timer: ReturnType<typeof setTimeout>;
        async function poll() {
            try {
                const current: Job = await bridge<Job>('/jobs/' + session!.jobId);
                if (disposed) return;
                setJob(current); setError('');
                if (current.status === 'completed' && !processing.current) {
                    processing.current = true;
                    try {
                        await completion.current(current);
                        const outcomes = [...session!.outcomes, `${session!.cases[session!.index].title}: ${current.result?.status || 'Complete'}`];
                        if (session!.index + 1 < session!.cases.length && !stopping && current.result?.status === 'Passed') {
                            await launch({ ...session!, index: session!.index + 1, outcomes });
                        } else {
                            setSession(null); setJob({ ...current, error: outcomes.join('\n') + (session!.index + 1 < session!.cases.length ? '\nRemaining cases were not run. Review the last outcome and starting conditions before retrying.' : '') });
                        }
                    } finally { processing.current = false; }
                    return;
                }
                if (current.status === 'error') { setError(current.error || 'Runner failed.'); return; }
            } catch (e) { if (!disposed) { const message = (e as Error).message; setError(message); if (message.startsWith('SESSION_MISSING:')) { setJob({ run_id: session!.jobId, status: 'error', steps: [], error: 'The bridge restarted or this session is no longer available. Any completed result can be recovered by importing its result.json.' }); return; } } }
            if (!disposed) timer = setTimeout(poll, 2000);
        }
        void poll(); return () => { disposed = true; clearTimeout(timer); };
    }, [session, stopping]);
    async function input() { setPending(true); try { await bridge(`/jobs/${session!.jobId}/input`, { text }); setText(''); setJob(old => old ? { ...old, status: 'running' } : old); } catch (e) { setError((e as Error).message); } finally { setPending(false); } }
    async function stop() { if (!session) return; setPending(true); try { await bridge(`/jobs/${session.jobId}/stop`, {}); setStopping(true); } catch (e) { setError((e as Error).message); } finally { setPending(false); } }
    const last = job?.steps?.at(-1);
    const invalid = requested?.some(test => test.platform !== 'Android' || !test.app_id);
    return <>
        <Dialog open={!!requested} onOpenChange={open => { if (!open && !pending) onClose(); }}><DialogContent className="form-dialog"><DialogHeader><DialogTitle>{requested?.length === 1 ? 'Run again' : `Run suite · ${requested?.length || 0} cases`}</DialogTitle><DialogDescription>Select an Android device and confirm the starting conditions. Suite cases run in order and stop on the first non-passing outcome.</DialogDescription></DialogHeader>
            <div className="run-setup"><label>Device<select value={serial} onChange={e => setSerial(e.target.value)}><option value="">Choose a connected device</option>{devices.map(device => <option key={device}>{device}</option>)}</select></label><Button size="sm" variant="outline" onClick={() => void refreshDevices()}><RefreshCw size={13}/>Refresh devices</Button>
            <label>Starting state<select value={mode} onChange={e => setMode(e.target.value)}><option value="current">Open app in its existing state</option><option value="relaunch">Force-stop and relaunch before each case</option></select></label><p>Relaunch preserves account and app data. Prepare login, permissions, and test data on the device before starting.</p>
            <label>Maximum actions per case<input type="number" min={1} max={100} value={limit} onChange={e => setLimit(Number(e.target.value))}/></label>
            <ol className="setup-cases">{ordered.map((test, index) => <li key={test.id}><b>{test.title}</b><p>{test.preconditions || 'No starting conditions specified.'}</p><small>{test.app_id || 'Android package ID missing'}</small>{ordered.length > 1 && <div className="row-actions"><Button size="sm" variant="ghost" disabled={index === 0} onClick={() => { setOrdered(old => { const next = [...old]; [next[index-1], next[index]] = [next[index], next[index-1]]; return next; }); setConfirmed(false); }}>Move up</Button><Button size="sm" variant="ghost" disabled={index === ordered.length-1} onClick={() => { setOrdered(old => { const next = [...old]; [next[index+1], next[index]] = [next[index], next[index+1]]; return next; }); setConfirmed(false); }}>Move down</Button></div>}</li>)}</ol>
            <label className="setup-confirm"><input type="checkbox" checked={confirmed} onChange={e => setConfirmed(e.target.checked)}/>I have prepared the listed starting conditions. Later cases can safely follow earlier ones.</label>
            {invalid && <p className="form-error">Every selected case needs an Android platform and package ID. Edit the case first.</p>}{error && <p role="alert" className="form-error">{error}</p>}
            <Button onClick={() => void start()} disabled={pending || !!session || !confirmed || !serial || invalid || !Number.isInteger(limit) || limit < 1 || limit > 100}><Play size={15}/>{pending ? 'Starting…' : 'Start run'}</Button></div>
        </DialogContent></Dialog>
        {(session || job) && <section className="live-session" aria-label="Live run progress"><header><div><b>{session ? `Live run · ${session.index + 1} / ${session.cases.length}` : 'Run finished'}</b><p>{session?.cases[session.index]?.title}</p></div><span>{stopping ? 'Stopping after current action…' : job?.status?.replaceAll('_', ' ') || 'Starting…'}</span>{session && <Button size="sm" variant="outline" disabled={pending || stopping} onClick={() => void stop()}><Square size={12}/>Stop</Button>}{!session && <Button variant="ghost" onClick={() => setJob(null)}>Dismiss</Button>}</header>
            {error && <p className="form-error" role="alert">{error}</p>}
            <div className="live-content"><div>{last?.screenshot && session ? <img crossOrigin="anonymous" src={`${BRIDGE}/runs/${session.jobId}/artifacts/${last.screenshot}`} alt="Latest guarded device capture"/> : <p>No current safe capture available. Credential screens may be withheld.</p>}<small>Latest captured step, updated as Jev progresses.</small></div><div><ol>{job?.steps?.map(step => <li key={step.step}><span>{step.step + 1}</span>{step.operation} {step.label && `· ${step.label}`}</li>)}</ol>
            {job?.status === 'awaiting_input' && session && <div className="live-input"><b>Jev needs your help: {job.text_request?.field.label || 'Text field'}</b><p>Provide the non-sensitive text to enter. Use local credential configuration for passwords and codes.</p><input aria-label="Text for Jev" maxLength={200} value={text} onChange={e => setText(e.target.value)}/><Button disabled={pending || !text.trim()} onClick={() => void input()}>Enter text & resume</Button></div>}
            <CheckpointReport definitions={session?.cases[session.index]?.checkpoints} results={job?.checkpoint_results || []}/>{job?.error && <p className="preserve">{job.error}</p>}
            {session && (job?.status === 'error' || (error && job?.status === 'completed')) && <Button variant="outline" onClick={() => { setSession(null); setJob(null); }}>End session · keep local results</Button>}
            </div></div></section>}
    </>;
}
