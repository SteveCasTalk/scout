'use client';

import { useEffect, useState } from 'react';
import { Circle, FilePenLine, RefreshCw, Square } from 'lucide-react';
import { Button } from './ui/button';
import { Input } from './ui/input';
import { Textarea } from './ui/textarea';
import { sandboxScenario, type SandboxScenario } from '@/lib/sandbox-contract';

type Capture = {
    id: string; protocol: 'http' | 'websocket'; host: string; path: string;
    method?: string; status?: number; after_ms?: number; delay_ms?: number;
    elapsed_ms: number; redactions: number; body?: string;
};
type Recording = {
    id: string; status: string; started_at: string; record_count: number;
    options: { name: string; project: string; hosts: string[]; duration_seconds: number };
    stats: { captured?: number; skipped?: number; redacted_fields?: number; errors?: number; limit_reached?: boolean };
    records?: Capture[];
};
const endpoint = 'http://127.0.0.1:8765/sandbox/recordings';
const lines = (text: string) => text.split('\n').map(s => s.trim()).filter(Boolean);
const running = (recording: Recording | null) => !!recording && ['starting', 'recording'].includes(recording.status);

async function request<T>(path = '', body?: unknown): Promise<T> {
    const response = await fetch(endpoint + path, body === undefined ? {} : {
        method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body),
    });
    const value = await response.json() as T & { error?: string };
    if (!response.ok) throw new Error(value.error || 'Could not manage the recording.');
    return value;
}

export function SandboxRecorder({ onDraft }: { onDraft: (scenario: SandboxScenario) => void }) {
    const [recordings, setRecordings] = useState<Recording[]>([]);
    const [selectedId, setSelectedId] = useState('');
    const [recording, setRecording] = useState<Recording | null>(null);
    const [selected, setSelected] = useState<string[]>([]);
    const [name, setName] = useState('Baseline capture'), [project, setProject] = useState('');
    const [hosts, setHosts] = useState(''), [paths, setPaths] = useState('');
    const [duration, setDuration] = useState(300), [websocket, setWebsocket] = useState(true);
    const [redactKeys, setRedactKeys] = useState('');
    const [scenarioId, setScenarioId] = useState(''), [scenarioName, setScenarioName] = useState('');
    const [busy, setBusy] = useState(false), [error, setError] = useState('');
    const active = running(recording) ? recording : recordings.find(r => running(r)) || null;

    async function refresh() {
        try {
            const value = await request<{ recordings: Recording[] }>();
            setRecordings(value.recordings);
            setSelectedId(current => current || value.recordings.find(r => running(r))?.id || '');
        } catch (e) { setError((e as Error).message || 'Start the updated local bridge to record responses.'); }
    }
    useEffect(() => { void refresh(); }, []);
    useEffect(() => {
        setRecording(null); setSelected([]);
        if (!selectedId) return;
        let cancelled = false;
        let timer: ReturnType<typeof setTimeout>;
        async function poll() {
            try {
                let value = await request<Recording>('/' + selectedId + '?bodies=0');
                if (!running(value)) value = await request<Recording>('/' + selectedId);
                if (cancelled) return;
                setRecording(value);
                setRecordings(current => [value, ...current.filter(r => r.id !== value.id)]);
                if (running(value)) timer = setTimeout(poll, 2000);
            } catch (e) {
                if (!cancelled) setError((e as Error).message);
            }
        }
        setScenarioId('fixture_' + selectedId.replace(/^record-/, '').replace(/-/g, '_'));
        setScenarioName('');
        void poll();
        return () => { cancelled = true; clearTimeout(timer); };
    }, [selectedId]);

    async function start() {
        setBusy(true); setError('');
        try {
            const value = await request<Recording>('', {
                name: name.trim(), project: project.trim(), hosts: lines(hosts), paths: lines(paths),
                capture_websocket: websocket, duration_seconds: duration, redact_keys: lines(redactKeys),
            });
            setRecordings(current => [value, ...current]); setSelectedId(value.id);
        } catch (e) { setError((e as Error).message); }
        finally { setBusy(false); }
    }
    async function stop() {
        if (!recording) return;
        setBusy(true); setError('');
        try {
            const value = await request<Recording>('/' + recording.id + '/stop', {});
            setRecording(value); await refresh();
        } catch (e) { setError((e as Error).message); }
        finally { setBusy(false); }
    }
    async function createDraft() {
        if (!recording) return;
        setBusy(true); setError('');
        try {
            const value = await request<unknown>('/' + recording.id + '/draft', {
                capture_ids: selected, scenario_id: scenarioId.trim(),
                name: scenarioName.trim() || recording.options.name + ' replay',
            });
            onDraft(sandboxScenario.parse(value));
        } catch (e) { setError((e as Error).message); }
        finally { setBusy(false); }
    }

    const captures = recording?.records || [];
    return <section className="panel sandbox-recorder">
        <div className="panel-heading"><div><div className="eyebrow">RECORD → EDIT → REPLAY</div><h2>Build fixtures from real responses</h2></div>
            <Button variant="outline" onClick={() => { setError(''); void refresh(); }}><RefreshCw size={15} />Refresh captures</Button></div>
        <p className="sandbox-recorder-intro">Capture a baseline, choose responses, then change their values in the scenario editor. Recording forwards traffic to the real server; app actions still have their usual effects.</p>
        <div className="capture-workflow"><span><b>1</b> Record selected hosts</span><span><b>2</b> Review & edit a draft</span><span><b>3</b> Save & attach to a case</span></div>
        <div className="capture-layout">
            <div className="sandbox-form capture-form">
                <h3>New recording</h3>
                <div className="form-row"><label>Project<Input value={project} disabled={!!active} onChange={e => setProject(e.target.value)} placeholder="Your UAT project" maxLength={100} /></label>
                    <label>Capture name<Input value={name} disabled={!!active} onChange={e => setName(e.target.value)} maxLength={120} /></label></div>
                <label>API hosts <small>· exact hostname, one per line</small><Textarea aria-label="Recording API hosts" value={hosts} disabled={!!active} onChange={e => setHosts(e.target.value)} placeholder="api.your-app.example" rows={2} /></label>
                <details><summary>Scope, duration & redaction</summary><div className="capture-options">
                    <label>Only these paths <small>· optional, one per line; queries ignored</small><Textarea value={paths} disabled={!!active} onChange={e => setPaths(e.target.value)} placeholder="/feed" rows={2} /></label>
                    <label>Stop automatically after (seconds)<input type="number" min={30} max={900} value={duration} disabled={!!active} onChange={e => setDuration(Number(e.target.value))} /></label>
                    <label className="capture-checkbox"><input type="checkbox" checked={websocket} disabled={!!active} onChange={e => setWebsocket(e.target.checked)} />Include server JSON WebSocket messages</label>
                    <label>Additional keys to redact <small>· one JSON field name per line</small><Textarea value={redactKeys} disabled={!!active} onChange={e => setRedactKeys(e.target.value)} placeholder="customer_id" rows={2} /></label>
                </div></details>
                <p className="snapshot-note">Configure the device proxy and test CA first. JSON only, up to 100 responses or messages, 64 KB each. Common sensitive fields are redacted before saving; review for remaining private data.</p>
                <Button disabled={busy || !!active || !project.trim() || !name.trim() || !lines(hosts).length} onClick={() => void start()}><Circle size={14} />{busy ? 'Working…' : 'Start recording'}</Button>
                {active && active.id !== selectedId && <Button variant="outline" onClick={() => setSelectedId(active.id)}>View active recording</Button>}
            </div>
            <div className="capture-history"><h3>Local captures</h3>
                {recordings.length ? <label>Recording<select aria-label="Select recording" value={selectedId} onChange={e => { setError(''); setSelectedId(e.target.value); }}><option value="">Select a recording</option>
                    {recordings.map(r => <option key={r.id} value={r.id}>{r.options.name} · {r.status} · {r.record_count} captured</option>)}
                </select></label> : <div className="capture-empty"><Circle size={24} /><b>No recordings yet</b><p>Start a recording, then use the app to capture its responses. Captures stay on this machine.</p></div>}
                {recording && <><div className="capture-summary"><span className="status">{running(recording) ? 'Recording · proxy active' : recording.status}</span>
                    {running(recording) && <Button variant="outline" disabled={busy} onClick={() => void stop()}><Square size={12} />Stop recording</Button>}</div>
                    <p className="snapshot-note">{recording.options.project} · {recording.options.hosts.join(', ')}<br />{recording.record_count} captured · {recording.stats.redacted_fields || 0} fields redacted · {recording.stats.skipped || 0} skipped · {recording.stats.errors || 0} network errors</p>
                    {recording.stats.limit_reached && <p className="sandbox-notice">Capture limit reached. Stop recording to review the saved responses.</p>}
                    {['interrupted', 'error'].includes(recording.status) && <p className="sandbox-notice">The proxy stopped unexpectedly. Saved responses are retained; this capture may be incomplete.</p>}
                    {running(recording) && <p className="snapshot-note">Use the app now. Response previews and fixture creation become available after stopping. The proxy stops automatically after {recording.options.duration_seconds} seconds.</p>}
                    {!running(recording) && !captures.length && <p>No eligible responses captured. Check host scope, device routing, CA trust, and whether the app sends JSON responses.</p>}
                    {!!captures.length && <><div className="capture-select"><b>{captures.length} responses / messages</b><Button size="sm" variant="ghost" disabled={running(recording)} onClick={() => setSelected(selected.length === captures.length ? [] : captures.map(r => r.id))}>{selected.length === captures.length ? 'Clear selection' : 'Select all'}</Button></div>
                        <div className="capture-responses">{captures.map(c => <div className="capture-response" key={c.id}>
                            <label className="capture-response-heading"><input type="checkbox" disabled={running(recording)} checked={selected.includes(c.id)} onChange={e => setSelected(current => e.target.checked ? [...current, c.id] : current.filter(id => id !== c.id))} />
                                <span><b>{c.method || 'WS'} {c.path}</b><small>{c.host} · {c.protocol === 'http' ? `HTTP ${c.status} · ${c.delay_ms} ms` : `${((c.after_ms || 0) / 1000).toFixed(1)}s after connection`} · {c.redactions} redacted</small></span></label>
                            {c.body !== undefined && <details><summary>View sanitized response</summary><pre>{c.body}</pre></details>}
                        </div>)}</div>
                        {!running(recording) && <div className="capture-draft sandbox-form"><div className="form-row"><label>Fixture ID<Input value={scenarioId} onChange={e => setScenarioId(e.target.value)} maxLength={60} /></label><label>Fixture name<Input value={scenarioName} onChange={e => setScenarioName(e.target.value)} placeholder={recording.options.name + ' replay'} maxLength={120} /></label></div>
                            <p className="snapshot-note">Review redacted placeholders before saving. Repeated endpoints become sequences; queries are ignored. Unmatched requests use the real server. WS drafts replace server text with selected frames from one connection within its first 60 seconds.</p>
                            <Button disabled={busy || !selected.length || !scenarioId.trim()} onClick={() => void createDraft()}><FilePenLine size={15} />Edit fixture draft · {selected.length} selected</Button></div>}
                    </>}
                </>}
            </div>
        </div>
        {error && <p role="alert" className="form-error">{error}</p>}
    </section>;
}
