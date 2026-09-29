"use client";
import { useCallback, useEffect, useRef, useState } from 'react';
import Link from 'next/link';
import { FlaskConical, Files, Play, Smartphone, Plus, ArrowUpRight, CircleDot, FolderOpen, Search, ArrowLeft, Upload, Download, Image as ImageIcon, Film, FileText, Pencil, RefreshCw, CheckCircle2, XCircle, Clock3, Layers } from 'lucide-react';
import { SidebarProvider, Sidebar, SidebarContent, SidebarHeader, SidebarFooter, SidebarMenu, SidebarMenuItem, SidebarMenuButton, SidebarInset, SidebarTrigger } from '@/components/ui/sidebar';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Textarea } from '@/components/ui/textarea';
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogDescription } from '@/components/ui/dialog';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table';
import { Tabs, TabsList, TabsTrigger, TabsContent } from '@/components/ui/tabs';
import { Toaster, toast } from 'sonner';
import { Skeleton } from '@/components/ui/skeleton';
import { caseInput, statuses, type TestCase, type Run, type Evidence } from '@/lib/contracts';
type Workspace = { id: string; name: string; created: string };
const blank = { workspace_id: '', project: 'General', app_id: '', title: '', platform: 'Android' as 'Android' | 'iOS', suite: 'Smoke tests', goal: '', preconditions: '', steps: '', expected: '', assertion_text: '' };
const LOCAL_RUNNER = 'http://127.0.0.1:8765';
const nav = [{ label: 'Test cases', icon: Files }, { label: 'Test runs', icon: Play }, { label: 'Evidence', icon: FolderOpen }];
async function api<T>(path: string, init?: RequestInit): Promise<T> { const r = await fetch(path, init); const data = await r.json(); if (!r.ok)
    throw new Error((data as {
        error?: string;
    }).error || 'Request failed. Please try again.'); return data as T; }
const date = (s: string) => new Date(s).toLocaleString(undefined, { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' });
const bytes = (n: number) => n < 1024 * 1024 ? `${Math.max(1, Math.round(n / 1024))} KB` : `${(n / 1024 / 1024).toFixed(1)} MB`;
function Status({ value }: {
    value: string;
}) { const Icon = value === 'Passed' ? CheckCircle2 : value === 'Failed' ? XCircle : Clock3; return <span className={`status status-${value.toLowerCase().replaceAll(' ', '-')}`}><Icon size={13}/>{value}</span>; }
function Choice({ value, onChange, items, label }: {
    value: string;
    onChange: (v: string) => void;
    items: string[];
    label: string;
}) { return <Select value={value} onValueChange={onChange}><SelectTrigger aria-label={label}><SelectValue /></SelectTrigger><SelectContent>{items.map(i => <SelectItem value={i} key={i}>{i}</SelectItem>)}</SelectContent></Select>; }
export default function Dashboard() {
    const [view, setView] = useState('Test cases'), [cases, setCases] = useState<TestCase[]>([]), [runs, setRuns] = useState<Run[]>([]), [evidence, setEvidence] = useState<Evidence[]>([]), [workspaces, setWorkspaces] = useState<Workspace[]>([]), [selectedWorkspaceId, setSelectedWorkspaceId] = useState(''), [workspaceDialog, setWorkspaceDialog] = useState(false), [workspaceName, setWorkspaceName] = useState(''), [loading, setLoading] = useState(true), [error, setError] = useState(''), [query, setQuery] = useState(''), [platform, setPlatform] = useState('All platforms'), [projectFilter, setProjectFilter] = useState('All projects');
    const [caseDialog, setCaseDialog] = useState(false), [editing, setEditing] = useState<TestCase | null>(null), [draft, setDraft] = useState(blank), [saving, setSaving] = useState(false), [formError, setFormError] = useState('');
    const [runCase, setRunCase] = useState<TestCase | null>(null), [runDraft, setRunDraft] = useState({ build: '', device: '', status: 'Inconclusive', notes: '' });
    const [selectedRun, setSelectedRun] = useState<Run | null>(null), [selectedFile, setSelectedFile] = useState<Evidence | null>(null), [uploading, setUploading] = useState(false);
    const [localRunnerReady, setLocalRunnerReady] = useState(false), [runningCaseId, setRunningCaseId] = useState<string | null>(null);
    const fileInput = useRef<HTMLInputElement>(null);
    const importInput = useRef<HTMLInputElement>(null);
    const deepLinkHandled = useRef(false);
    const syncPromptRunsRef = useRef<(runId?: string) => Promise<void>>(async () => {});
    const load = useCallback(async () => { setLoading(true); setError(''); try {
        const [w, c, r, e] = await Promise.all([api<Workspace[]>('/api/workspaces'), api<TestCase[]>('/api/cases'), api<Run[]>('/api/runs'), api<Evidence[]>('/api/evidence')]);
        setWorkspaces(w);
        let chosen = selectedWorkspaceId && w.some(item => item.id === selectedWorkspaceId) ? selectedWorkspaceId : '';
        if (!chosen) {
            const params = new URLSearchParams(window.location.search);
            const requested = params.get('workspace') || params.get('project') || localStorage.getItem('jev-workspace-id');
            chosen = w.find(item => item.id === requested || item.name.toLowerCase() === requested?.toLowerCase())?.id || w[0]?.id || '';
            if (chosen) { setSelectedWorkspaceId(chosen); localStorage.setItem('jev-workspace-id', chosen); }
            if (!w.length) setWorkspaceDialog(true);
        }
        setCases(c);
        setRuns(r);
        setEvidence(e);
    }
    catch (e) {
        setError((e as Error).message);
    }
    finally {
        setLoading(false);
    } }, [selectedWorkspaceId]);
    // eslint-disable-next-line react-hooks/set-state-in-effect
    useEffect(() => { void load(); }, [load]);
    useEffect(() => { let active = true; const check = async () => { try { const response = await fetch(LOCAL_RUNNER + '/health'); if (active) setLocalRunnerReady(response.ok); } catch { if (active) setLocalRunnerReady(false); } }; void check(); const timer = setInterval(check, 10000); return () => { active = false; clearInterval(timer); }; }, []);
    function go(v: string) { setView(v); setSelectedRun(null); setSelectedFile(null); setQuery(''); setPlatform('All platforms'); }
    function edit(c?: TestCase) { setEditing(c || null); setDraft(c ? { workspace_id: c.workspace_id, project: c.project || 'General', app_id: c.app_id || '', title: c.title, platform: c.platform, suite: c.suite, goal: c.goal, preconditions: c.preconditions, steps: c.steps, expected: c.expected, assertion_text: c.assertion_text || '' } : { ...blank, workspace_id: selectedWorkspaceId, project: selectedWorkspace?.name || 'General' }); setFormError(''); setCaseDialog(true); }
    async function saveCase(event: React.FormEvent) { event.preventDefault(); setSaving(true); setFormError(''); try {
        const body = caseInput.parse(draft);
        const c = await api<TestCase>('/api/cases', { method: editing ? 'PUT' : 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(editing ? { ...body, id: editing.id, revision: editing.revision } : body) });
        setCases(old => [c, ...old.filter(x => x.id !== c.id)]);
        setCaseDialog(false);
        toast.success(editing ? 'New test revision saved' : 'Test case created');
    }
    catch (e) {
        setFormError((e as Error).message);
    }
    finally {
        setSaving(false);
    } }
    async function createWorkspace(event: React.FormEvent) { event.preventDefault(); setSaving(true); try { const created = await api<Workspace>('/api/workspaces', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ name: workspaceName }) }); setWorkspaces(old => [...old, created].sort((a,b) => a.name.localeCompare(b.name))); switchWorkspace(created.id); setWorkspaceName(''); setWorkspaceDialog(false); toast.success(`Workspace “${created.name}” created`); } catch (e) { setFormError((e as Error).message); } finally { setSaving(false); } }
    function record(c: TestCase) { setRunCase(c); setRunDraft({ build: '', device: '', status: 'Inconclusive', notes: '' }); setFormError(''); }
    async function saveRun(event: React.FormEvent) { event.preventDefault(); if (!runCase)
        return; setSaving(true); setFormError(''); try {
        const r = await api<Run>('/api/runs', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ ...runDraft, caseId: runCase.id, revision: runCase.revision }) });
        setRuns(old => [r, ...old]);
        setRunCase(null);
        setView('Test runs');
        setSelectedRun(r);
        toast.success('Run recorded. You can now attach evidence.');
    }
    catch (e) {
        setFormError((e as Error).message);
    }
    finally {
        setSaving(false);
    } }
    async function upload(file?: File) { if (!file || !selectedRun)
        return; if (file.size > 25 * 1024 * 1024) {
        toast.error('Files must be 25 MB or smaller.');
        return;
    } setUploading(true); try {
        const form = new FormData();
        form.append('file', file);
        form.append('runId', selectedRun.id);
        const result = await api<Evidence>('/api/evidence', { method: 'POST', body: form });
        setEvidence(old => [result, ...old]);
        setSelectedFile(result);
        toast.success('Evidence saved');
    }
    catch (e) {
        toast.error((e as Error).message);
    }
    finally {
        setUploading(false);
        if (fileInput.current)
            fileInput.current.value = '';
    } }

    function downloadJson(name: string, value: unknown) {
        const url = URL.createObjectURL(new Blob([JSON.stringify(value, null, 2)], { type: 'application/json' }));
        const link = document.createElement('a');
        link.href = url;
        link.download = name;
        link.click();
        setTimeout(() => URL.revokeObjectURL(url), 1000);
    }
    function exportCase(c: TestCase) { downloadJson(`jev-case-${c.id}-v${c.revision}.json`, c); }
    async function saveJevResult(result: Record<string, unknown>, localArtifacts?: { runId: string; artifacts: string[] }, sourceFile?: File) {
        setSaving(true);
        try {
            if (result.schema_version !== 1 || result.source !== 'Jev Android runner') throw new Error('Choose a result.json created by the Jev Android runner.');
            let selectedCase = cases.find(c => c.id === result.case_id);
            const promptRun = String(result.case_id || '').startsWith('prompt-');
            if (!selectedCase && promptRun) {
                const synthetic = caseInput.parse({ workspace_id: selectedWorkspaceId, project: String(result.project || selectedWorkspace?.name || 'General'), app_id: String(result.package || ''), title: String(result.case_title || 'Prompt-driven test'), platform: 'Android', suite: 'Prompt runs', goal: String(result.goal || 'Run initiated from an assistant prompt.'), preconditions: 'Executed from a prompt-driven MCP request.', steps: String(result.case_steps || 'See the run trace.'), expected: String(result.expected_result || 'Review the run evidence.'), assertion_text: String(result.expected_text || '') });
                selectedCase = await api<TestCase>('/api/cases', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(synthetic) });
                setCases(old => [selectedCase!, ...old]);
            }
            if (!selectedCase) throw new Error('This result has no matching test case.');
            if (selectedCase.revision !== result.revision && !promptRun) throw new Error('The test case was revised after this run. Export and run its current revision.');
            if (selectedCase.platform !== 'Android') throw new Error('The Android runner result must refer to an Android test case.');
            if (!statuses.includes(result.status as typeof statuses[number])) throw new Error('Runner result has an invalid status.');
            if (!Array.isArray(result.steps)) throw new Error('Runner result is missing its action trace.');
            const trace = result.steps.map(item => {
                const step = item as Record<string, unknown>;
                return { step: Number(step.step), operation: String(step.operation || ''), label: step.label == null ? null : String(step.label), elapsed_ms: Number(step.elapsed_ms || 0), screenshot: step.screenshot == null ? null : String(step.screenshot), ...(step.verification ? { verification: step.verification } : {}), ...(step.jev ? { jev: step.jev } : {}) };
            });
            const verification = result.verification as { status?: string; method?: string; expected_text?: string; observed_text?: string } | undefined;
            if (verification && !trace.some(step => step.operation === 'VERIFY_RESULT')) {
                trace.push({ step: Number(result.steps.length), operation: 'VERIFY_RESULT', label: null, elapsed_ms: Number(result.elapsed_ms || 0), screenshot: null, verification: { status: ['passed', 'failed', 'inconclusive', 'not_run'].includes(verification.status || '') ? verification.status : 'not_run', method: String(verification.method || 'exact_visible_text'), expected_text: String(verification.expected_text || ''), observed_text: String(verification.observed_text || '') } });
            }
            const body = { caseId: selectedCase.id, revision: selectedCase.revision, externalRunId: localArtifacts?.runId, status: result.status, build: String(result.build || 'unknown'), device: String(result.device || 'unknown'), notes: String(result.notes || 'No runner notes.'), source: promptRun ? 'Prompt run' : 'Jev import', trace };
            const saved = await api<Run & { duplicate?: boolean }>('/api/runs', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) });
            if (saved.duplicate) return;
            const run = saved;
            setRuns(old => [run, ...old]);
            setView('Test runs');
            setSelectedRun(run);
            const savedEvidence: Evidence[] = [];
            const failedEvidence: string[] = [];
            async function attachEvidence(evidenceFile: File) {
                const form = new FormData();
                form.append('file', evidenceFile);
                form.append('runId', run.id);
                savedEvidence.push(await api<Evidence>('/api/evidence', { method: 'POST', body: form }));
            }
            if (sourceFile) { try { await attachEvidence(sourceFile); } catch { failedEvidence.push(sourceFile.name); } }
            if (localArtifacts) {
                for (const name of localArtifacts.artifacts.filter(name => name !== 'result.json')) {
                    try {
                        const response = await fetch(LOCAL_RUNNER + '/runs/' + encodeURIComponent(localArtifacts.runId) + '/artifacts/' + encodeURIComponent(name));
                        if (!response.ok) throw new Error('Artifact fetch failed');
                        const blob = await response.blob();
                        if (blob.size > 25 * 1024 * 1024) throw new Error('Artifact exceeds the dashboard upload limit');
                        await attachEvidence(new File([blob], name, { type: blob.type || 'application/octet-stream' }));
                    } catch { failedEvidence.push(name); }
                }
            }
            setEvidence(old => [...savedEvidence, ...old]);
            if (savedEvidence[0]) setSelectedFile(savedEvidence[0]);
            if (failedEvidence.length) toast.error('Run saved, but some evidence could not be attached: ' + failedEvidence.join(', '));
            else toast.success(`${promptRun ? 'Prompt run' : 'Jev run'} saved under ${selectedCase.project}`);
        } catch (error) { toast.error((error as Error).message); }
        finally { setSaving(false); }
    }
    async function importJevResult(file?: File, localArtifacts?: { runId: string; artifacts: string[] }) {
        if (!file) return;
        try {
            if (file.size > 1024 * 1024) throw new Error('Runner result must be 1 MB or smaller.');
            await saveJevResult(JSON.parse(await file.text()) as Record<string, unknown>, localArtifacts, file);
        } catch (error) { toast.error((error as Error).message); }
        finally { if (importInput.current) importInput.current.value = ''; }
    }
    async function syncPromptRuns(runId?: string) {
        if (!localRunnerReady) return;
        try {
            const response = await fetch(LOCAL_RUNNER + '/runs');
            const data = await response.json() as { runs?: { run_id: string; result: Record<string, unknown>; artifacts: string[] }[]; error?: string };
            if (!response.ok) throw new Error(data.error || 'Could not list local MCP runs.');
            const alreadyImported = new Set(runs.map(run => run.external_run_id).filter((id): id is string => !!id));
            const promptRuns = (data.runs || []).filter(localRun => (!runId || localRun.run_id === runId) && !alreadyImported.has(localRun.run_id));
            if (!promptRuns.length) { toast.info('No new prompt-driven MCP runs to sync.'); return; }
            for (const localRun of promptRuns) {
                await saveJevResult(localRun.result, { runId: localRun.run_id, artifacts: localRun.artifacts });
            }
            const freshRuns = await api<Run[]>('/api/runs');
            setRuns(freshRuns);
            const newestImported = freshRuns.find(run => promptRuns.some(localRun => run.external_run_id === localRun.run_id));
            if (newestImported) {
                const freshEvidence = await api<Evidence[]>('/api/evidence');
                setEvidence(freshEvidence);
                setView('Test runs');
                setSelectedRun(newestImported);
                setSelectedFile(freshEvidence.find(item => item.run_id === newestImported.id) || null);
            }
        } catch (error) { toast.error((error as Error).message); }
    }
    useEffect(() => { syncPromptRunsRef.current = syncPromptRuns; });
    useEffect(() => {
        if (loading || !localRunnerReady || deepLinkHandled.current) return;
        const params = new URLSearchParams(window.location.search);
        const runId = params.get('syncRun');
        const project = params.get('project');
        if (!runId) return;
        deepLinkHandled.current = true;
        void (async () => {
            if (project) setProjectFilter('All projects');
            await syncPromptRunsRef.current(runId);
            const [freshRuns, freshEvidence] = await Promise.all([api<Run[]>('/api/runs'), api<Evidence[]>('/api/evidence')]);
            setRuns(freshRuns);
            setEvidence(freshEvidence);
            const report = freshRuns.find(run => run.external_run_id === runId);
            if (report) {
                setView('Test runs');
                setSelectedRun(report);
                setSelectedFile(freshEvidence.find(item => item.run_id === report.id) || null);
                toast.success(`Opened ${report.snapshot.project} test report`);
            } else toast.error('The prompt run could not be found in the dashboard. Use Sync MCP runs on Test runs to retry.');
            window.history.replaceState(null, '', window.location.pathname);
        })();
    }, [loading, localRunnerReady]);
    async function runOnDashboard(testCase: TestCase) {
        if (testCase.platform !== 'Android') return;
        if (!testCase.app_id && !['general', 'ai avatar'].includes(testCase.project.trim().toLowerCase())) {
            toast.error(`Set the Android package ID for the ${testCase.project} project before running this case.`);
            return;
        }
        setRunningCaseId(testCase.id);
        try {
            const deviceResponse = await fetch(LOCAL_RUNNER + '/devices');
            const deviceData = await deviceResponse.json() as { devices?: string[]; error?: string };
            if (!deviceResponse.ok) throw new Error(deviceData.error || 'Could not reach the local Jev runner.');
            const devices = deviceData.devices || [];
            if (!devices.length) throw new Error('No authorized Android device found. Connect and unlock your phone, then retry.');
            let serial = devices[0];
            if (devices.length > 1) {
                const selected = window.prompt('Choose device serial from: ' + devices.join(', '), devices[0]);
                if (!selected) return;
                if (!devices.includes(selected.trim())) throw new Error('Choose one of the connected device serials.');
                serial = selected.trim();
            }
            const response = await fetch(LOCAL_RUNNER + '/run', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ case: testCase, package: testCase.app_id || 'com.wallet.walkthedog.uat', serial, max_steps: 40 }) });
            const data = await response.json() as { error?: string; run_id?: string; result?: Record<string, unknown>; artifacts?: string[] };
            if (!response.ok) throw new Error(data.error || 'Jev run failed.');
            const resultFile = new File([JSON.stringify(data.result)], 'result.json', { type: 'application/json' });
            await importJevResult(resultFile, { runId: String(data.run_id), artifacts: data.artifacts || [] });
        } catch (error) {
            toast.error((error as Error).message + ' Start the local runner with: python3 -m jev_mobile.local_server');
        } finally { setRunningCaseId(null); }
    }
    function openRun(r: Run) { setView('Test runs'); setSelectedRun(r); setSelectedFile(evidence.find(e => e.run_id === r.id) || null); }
    function exportRun() { if (!selectedRun)
        return; const bundle = { ...selectedRun, evidence: evidence.filter(e => e.run_id === selectedRun.id).map(e => ({ ...e, url: new URL(`/api/evidence/${e.id}`, location.origin).href })) }; const a = document.createElement('a'); a.href = URL.createObjectURL(new Blob([JSON.stringify(bundle, null, 2)], { type: 'application/json' })); a.download = `jev-run-${selectedRun.id}.json`; a.click(); setTimeout(() => URL.revokeObjectURL(a.href), 1000); }
    useEffect(() => { const context = (document as unknown as {
        modelContext?: {
            registerTool: (tool: unknown, options: {
                signal: AbortSignal;
            }) => Promise<void> | void;
        };
    }).modelContext; if (!context?.registerTool)
        return; const lifecycle = new AbortController(); try {
        void Promise.resolve(context.registerTool({ name: 'navigate_test_workspace', description: 'Navigate to the test case library, run history, or evidence library. Does not create or execute a test.', inputSchema: { type: 'object', properties: { view: { type: 'string', enum: ['Test cases', 'Test runs', 'Evidence'] } }, required: ['view'], additionalProperties: false }, annotations: { readOnlyHint: true }, execute: async (input: unknown) => { const value = (input as {
                view?: string;
            })?.view; if (!value || !nav.some(n => n.label === value))
                throw new Error('Choose Test cases, Test runs, or Evidence.'); setView(value); setSelectedRun(null); setSelectedFile(null); setQuery(''); setPlatform('All platforms'); await new Promise<void>(resolve => requestAnimationFrame(() => requestAnimationFrame(() => resolve()))); return { view: value }; } }, { signal: lifecycle.signal })).catch(console.error);
    }
    catch (e) {
        console.error(e);
    } return () => lifecycle.abort(); }, []);
    const selectedWorkspace = workspaces.find(item => item.id === selectedWorkspaceId);
    function switchWorkspace(id: string) { setSelectedWorkspaceId(id); setProjectFilter('All projects'); setQuery(''); setSelectedRun(null); setSelectedFile(null); const url = new URL(window.location.href); url.searchParams.set('workspace', id); url.searchParams.delete('project'); url.searchParams.delete('syncRun'); window.history.replaceState(null, '', url); localStorage.setItem('jev-workspace-id', id); }
    const workspaceCases = cases.filter(c => c.workspace_id === selectedWorkspaceId);
    const workspaceRuns = runs.filter(r => r.workspace_id === selectedWorkspaceId);
    const workspaceEvidence = evidence.filter(e => e.workspace_id === selectedWorkspaceId);
    const projectNames = Array.from(new Set([...workspaceCases.map(c => c.project || 'General'), ...workspaceRuns.map(r => r.snapshot.project || 'General')])).sort((a,b) => a.localeCompare(b));
    const filteredCases = workspaceCases.filter(c => (projectFilter === 'All projects' || (c.project || 'General') === projectFilter) && (platform === 'All platforms' || c.platform === platform) && `${c.title} ${c.suite} ${c.project}`.toLowerCase().includes(query.toLowerCase()));
    const filteredRuns = workspaceRuns.filter(r => (projectFilter === 'All projects' || (r.snapshot.project || 'General') === projectFilter) && `${r.snapshot.title} ${r.snapshot.project} ${r.build} ${r.status}`.toLowerCase().includes(query.toLowerCase()));
    const filteredEvidence = workspaceEvidence.filter(e => e.name.toLowerCase().includes(query.toLowerCase()) && (projectFilter === 'All projects' || workspaceRuns.find(r => r.id === e.run_id)?.snapshot.project === projectFilter));
    const runFiles = evidence.filter(e => e.run_id === selectedRun?.id);
    return <SidebarProvider><Toaster richColors position="bottom-right"/><Sidebar><SidebarHeader><Link className="brand" href="/"><span className="brand-icon"><FlaskConical size={22}/></span>jev<span className="brand-sub">mobile</span></Link><div className="workspace"><span className="project-icon"><Layers size={17}/></span><div className="workspace-picker"><Choice value={selectedWorkspace?.name || ''} onChange={name => { const match = workspaces.find(item => item.name === name); if (match) switchWorkspace(match.id); }} items={workspaces.map(item => item.name)} label="Select workspace"/><small>{workspaceCases.length} tests · {workspaceRuns.length} runs</small></div><Button size="icon" variant="ghost" aria-label="Create workspace" title="Create workspace" onClick={() => { setWorkspaceName(''); setFormError(''); setWorkspaceDialog(true); }}><Plus size={17}/></Button></div></SidebarHeader><SidebarContent><div className="nav-label">WORKSPACE</div><SidebarMenu>{nav.map(({ label, icon: Icon }) => <SidebarMenuItem key={label}><SidebarMenuButton isActive={view === label} onClick={() => go(label)}><Icon /><span>{label}</span><span className="nav-count">{label === 'Test cases' ? workspaceCases.length : label === 'Test runs' ? workspaceRuns.length : workspaceEvidence.length}</span></SidebarMenuButton></SidebarMenuItem>)}</SidebarMenu></SidebarContent><SidebarFooter><div className="runner-note"><Smartphone size={20}/><b>Your device lab starts here</b><p>Start the local bridge, then run Android cases here with Jev.</p><span>{localRunnerReady ? 'Device runner ready' : 'Device runner offline'}</span></div><div className="profile"><span>JM</span><div>Jev Mobile<small>{selectedWorkspace?.name || 'Private testing workspace'}</small></div></div></SidebarFooter></Sidebar><SidebarInset><header className="topbar"><div><SidebarTrigger /><span>{selectedWorkspace?.name || 'Workspace'}</span><span className="slash">/</span><b>{view}</b></div><span className="phase"><CircleDot size={14}/> Android runner · {localRunnerReady ? 'Ready' : 'Bridge offline'}</span></header><main className="content">
 {selectedRun ? <><button className="back" onClick={() => setSelectedRun(null)}><ArrowLeft size={15}/> All test runs</button><div className="heading"><div><div className="eyebrow">{selectedRun.snapshot.project || 'General'} · RUN {selectedRun.id.slice(0, 8).toUpperCase()} · {selectedRun.source === 'Prompt run' ? 'PROMPT RUN' : selectedRun.source === 'Jev import' ? 'JEV RUNNER IMPORT' : 'MANUALLY RECORDED'}</div><h1>{selectedRun.snapshot.title}</h1><div className="run-meta"><Status value={selectedRun.status}/><span>{selectedRun.snapshot.platform} · {selectedRun.device}</span><span>Build {selectedRun.build}</span></div></div><Button variant="outline" onClick={exportRun}><Download size={16}/> Export run JSON</Button></div><div className="run-layout"><section className="panel"><div className="panel-heading"><h2>Evidence viewer</h2><Button size="sm" onClick={() => fileInput.current?.click()} disabled={uploading}>{uploading ? 'Uploading…' : <><Upload size={14}/> Attach evidence</>}</Button><input ref={fileInput} type="file" hidden accept="image/png,image/jpeg,image/webp,video/mp4,video/webm,text/plain,application/json" onChange={e => void upload(e.target.files?.[0])}/></div><div className="viewer">{selectedFile ? selectedFile.mime.startsWith('video/') ? <video key={selectedFile.id} controls preload="metadata" src={`/api/evidence/${selectedFile.id}`}/> : selectedFile.mime.startsWith('image/') ? <img src={`/api/evidence/${selectedFile.id}`} alt={selectedFile.name}/> : <div className="file-preview"><FileText size={44}/><h2>{selectedFile.name}</h2><a href={`/api/evidence/${selectedFile.id}`} download>Download file <Download size={14}/></a></div> : <div className="empty"><span className="empty-icon"><Film size={28}/></span><h2>The evidence belongs here</h2><p>Attach a device recording, screenshot, or log.<br />PNG, JPEG, WebP, MP4, WebM, TXT, JSON · Up to 25 MB</p></div>}</div>{runFiles.length > 0 && <div className="file-strip">{runFiles.map(f => <button className={selectedFile?.id === f.id ? 'file-chip selected' : 'file-chip'} key={f.id} onClick={() => setSelectedFile(f)}>{f.mime.startsWith('video/') ? <Film size={16}/> : f.mime.startsWith('image/') ? <ImageIcon size={16}/> : <FileText size={16}/>}<span>{f.name}<small>{bytes(f.size)}</small></span></button>)}</div>}</section><section className="panel run-side"><Tabs defaultValue="result"><TabsList><TabsTrigger value="result">Result</TabsTrigger><TabsTrigger value="test">Test snapshot</TabsTrigger></TabsList><TabsContent value="result">{(() => { const check = selectedRun.trace?.find(step => step.operation === 'VERIFY_RESULT')?.verification; return check ? <div className={`verification-card verification-${check.status}`}><div className="detail-label">RESULT VERIFICATION</div><strong>{check.status === 'passed' ? 'Assertion passed' : check.status === 'failed' ? 'Assertion failed' : check.status === 'not_run' ? 'Verification not run' : 'Could not verify'}</strong><small>Method: {check.method.replaceAll('_', ' ')}</small><div className="verification-values"><div><span>Expected</span><p className="preserve">{check.expected_text || 'No exact text assertion configured'}</p></div><div><span>Observed</span><p className="preserve">{check.observed_text || 'No screen text captured'}</p></div></div></div> : null; })()}<div className="detail-label">RECORDED OBSERVATIONS</div><p className="preserve">{selectedRun.notes}</p><div className="detail-label">EXPECTED RESULT</div><p className="preserve">{selectedRun.snapshot.expected}</p><hr /><dl><dt>Recorded</dt><dd>{date(selectedRun.created)}</dd><dt>Test revision</dt><dd>v{selectedRun.snapshot.revision}</dd><dt>Source</dt><dd>{selectedRun.source === 'Prompt run' ? 'Prompt-driven MCP run' : selectedRun.source === 'Jev import' ? 'Jev Android runner import' : 'Manual report'}</dd><dt>Evidence</dt><dd>{runFiles.length} files</dd></dl>{selectedRun.trace?.length > 0 && <><div className="detail-label">ACTION TIMELINE</div><div className="action-timeline">{selectedRun.trace.map(step => <div key={step.step} className="timeline-entry"><button type="button" className="timeline-step" onClick={() => { const match = runFiles.find(f => f.name === step.screenshot); if (match) setSelectedFile(match); }}><span className="timeline-index">{step.step}</span><span><b>{step.operation}</b>{step.label && <> · {step.label}</>}<small>{step.elapsed_ms == null ? '' : `${(step.elapsed_ms / 1000).toFixed(1)}s`}{step.screenshot && runFiles.some(f => f.name === step.screenshot) ? ' · screenshot' : ''}</small></span></button>{step.jev && <JevAuditView audit={step.jev}/>}</div>)}</div></>}</TabsContent><TabsContent value="test"><div className="detail-label">GOAL</div><p className="preserve">{selectedRun.snapshot.goal}</p><div className="detail-label">PRECONDITIONS</div><p className="preserve">{selectedRun.snapshot.preconditions || 'None specified'}</p><div className="detail-label">TEST STEPS</div><ol className="steps">{selectedRun.snapshot.steps.split('\n').filter(Boolean).map((s, i) => <li key={i}>{s}</li>)}</ol><p className="snapshot-note">Saved with this run. Later test edits do not change this snapshot. These are intended steps, not a captured execution trace.</p></TabsContent></Tabs></section></div></> : <>
 <div className="heading"><div><div className="eyebrow">BUILD CONFIDENCE, ONE FLOW AT A TIME</div><h1>{view}</h1><p>{view === 'Test cases' ? 'Define the flow. Set the expectations. Keep every revision.' : view === 'Test runs' ? 'Every outcome, tied to the exact test that produced it.' : 'The recordings, screenshots, and logs behind your results.'}</p></div><div className="heading-actions"><Button variant="outline" size="icon" aria-label="Refresh workspace" onClick={() => void load()} disabled={loading}><RefreshCw size={16}/></Button>{view === 'Test runs' && <><Button variant="outline" onClick={() => void syncPromptRuns()} disabled={!localRunnerReady || saving || !!error}><RefreshCw size={15}/> Sync MCP runs</Button><Button variant="outline" onClick={() => importInput.current?.click()} disabled={loading || saving || !!error}><Upload size={16}/> Import Jev result</Button><input ref={importInput} type="file" accept="application/json,.json" hidden onChange={event => void importJevResult(event.target.files?.[0])}/></>}<Button onClick={() => edit()} disabled={loading || !!error}><Plus size={16}/> New test case</Button></div></div>
 <div className="stats">{[['Test cases', workspaceCases.length, 'In this workspace'], ['Recorded runs', workspaceRuns.length, `${workspaceRuns.filter(r => r.status === 'Passed').length} passed · ${workspaceRuns.filter(r => r.status === 'Failed').length} failed`], ['Evidence files', workspaceEvidence.length, 'Stored with workspace runs']].map(([label, n, note]) => <div className="stat" key={String(label)}><span>{label}</span><strong>{loading ? '—' : n}</strong><small>{note}</small></div>)}</div>
 {error ? <div className="error-panel" role="alert"><h2>Workspace unavailable</h2><p>{error}</p><Button variant="outline" onClick={() => void load()}>Try again</Button><a href="/signin-with-chatgpt?return_to=/" target="_top">Sign in again</a></div> : <section className="panel"><div className="panel-heading"><h2>{view === 'Test cases' ? 'Your test library' : view === 'Test runs' ? 'Run history' : 'Evidence library'}</h2><span>{view === 'Test cases' ? 'Android & iOS · grouped by project' : view === 'Test runs' ? 'Manual, Jev, and prompt runs' : 'Stored with each run'}</span></div><div className="toolbar"><label className="search"><Search size={16}/><Input value={query} onChange={e => setQuery(e.target.value)} placeholder={`Search ${view.toLowerCase()}…`} aria-label={`Search ${view.toLowerCase()}`}/></label><Choice value={projectFilter} onChange={setProjectFilter} items={['All projects', ...projectNames]} label="Filter project"/>{view === 'Test cases' && <Choice value={platform} onChange={setPlatform} items={['All platforms', 'Android', 'iOS']} label="Filter platform"/>}</div>
 {loading ? <div className="loading">{[1, 2, 3].map(i => <Skeleton className="h-14 w-full" key={i}/>)}</div> : view === 'Test cases' ? filteredCases.length ? <Table><TableHeader><TableRow><TableHead>Test case</TableHead><TableHead>Platform</TableHead><TableHead>Suite</TableHead><TableHead>Updated</TableHead><TableHead><span className="sr-only">Actions</span></TableHead></TableRow></TableHeader><TableBody>{filteredCases.map(c => <TableRow key={c.id}><TableCell><button className="case-title" onClick={() => edit(c)}><span className="row-icon"><Files size={17}/></span><span>{c.title}<small>{c.project || 'General'} · Revision {c.revision}</small></span></button></TableCell><TableCell><span className="platform"><Smartphone size={13}/>{c.platform}</span></TableCell><TableCell><span className="suite">{c.suite}</span></TableCell><TableCell className="muted">{date(c.updated)}</TableCell><TableCell><div className="row-actions"><Button variant="ghost" size="icon" onClick={() => edit(c)} aria-label={`Edit ${c.title}`}><Pencil size={14}/></Button><Button variant="ghost" size="sm" onClick={() => exportCase(c)} aria-label={`Export ${c.title} for Jev runner`}><Download size={14}/> Export</Button>{c.platform === 'Android' && <Button variant="outline" size="sm" onClick={() => void runOnDashboard(c)} disabled={!localRunnerReady || runningCaseId === c.id || saving} title={!localRunnerReady ? "Start the local Jev runner to enable device runs" : "Run this Android case with Jev"}><Play size={13}/>{runningCaseId === c.id ? "Running…" : "Run Jev"}</Button>}<Button variant="outline" size="sm" onClick={() => record(c)}>Record run <ArrowUpRight size={13}/></Button></div></TableCell></TableRow>)}</TableBody></Table> : <Empty icon={Files} title={cases.length ? 'No matching tests' : 'A home for your first test'} text={cases.length ? 'Try another search or platform.' : 'Describe a flow, define what success looks like, and keep the evidence together.'}>{!cases.length && <Button onClick={() => edit()}>New test case <Plus size={15}/></Button>}</Empty> : view === 'Test runs' ? filteredRuns.length ? <Table><TableHeader><TableRow><TableHead>Test / build</TableHead><TableHead>Outcome</TableHead><TableHead>Device</TableHead><TableHead>Recorded</TableHead><TableHead>Evidence</TableHead></TableRow></TableHeader><TableBody>{filteredRuns.map(r => <TableRow key={r.id}><TableCell><button className="case-title" onClick={() => openRun(r)}><span className="row-icon"><Play size={15}/></span><span>{r.snapshot.title}<small>{r.snapshot.project || 'General'} · Build {r.build} · v{r.snapshot.revision} · {r.source === 'Prompt run' ? 'Prompt' : r.source === 'Jev import' ? 'Jev runner' : 'Manual'}</small></span></button></TableCell><TableCell><Status value={r.status}/></TableCell><TableCell>{r.device}<small className="cell-small">{r.snapshot.platform}</small></TableCell><TableCell className="muted">{date(r.created)}</TableCell><TableCell><Button variant="ghost" size="sm" onClick={() => openRun(r)}>{evidence.filter(e => e.run_id === r.id).length} files <ArrowUpRight size={14}/></Button></TableCell></TableRow>)}</TableBody></Table> : <Empty icon={Play} title={runs.length ? 'No matching runs' : 'Your next run starts with a test'} text="Record a manual result from the test library, then attach the evidence."><Button variant="outline" onClick={() => go('Test cases')}>Open test library <ArrowUpRight size={15}/></Button></Empty> : filteredEvidence.length ? <div className="evidence-grid">{filteredEvidence.map(e => <button className="evidence-card" key={e.id} onClick={() => { const r = runs.find(r => r.id === e.run_id); if (r) {
                openRun(r);
                setSelectedFile(e);
            } }}><div className="evidence-thumb">{e.mime.startsWith('image/') ? <img src={`/api/evidence/${e.id}`} alt={e.name}/> : e.mime.startsWith('video/') ? <Film size={34}/> : <FileText size={34}/>}</div><b>{e.name}</b><small>{bytes(e.size)} · {date(e.created)}</small><span>View in run <ArrowUpRight size={13}/></span></button>)}</div> : <Empty icon={FolderOpen} title={evidence.length ? 'No matching evidence' : 'More than a pass or fail'} text="Attach recordings, screenshots, and logs to a run. They will appear here."><Button variant="outline" onClick={() => go('Test runs')}>View test runs <ArrowUpRight size={15}/></Button></Empty>}
 </section>}<div className="bottom-note"><FlaskConical size={16}/> Built for observable, repeatable mobile testing.</div></>}
 </main></SidebarInset>
 <Dialog open={workspaceDialog} onOpenChange={open => { if (!saving) setWorkspaceDialog(open); }}><DialogContent className="form-dialog"><DialogHeader><DialogTitle>Create a workspace</DialogTitle><DialogDescription>Keep test cases, runs, and evidence together for one app, team, or environment.</DialogDescription></DialogHeader><form onSubmit={createWorkspace}><label>Workspace name<Input required autoFocus maxLength={100} value={workspaceName} onChange={event => setWorkspaceName(event.target.value)} placeholder="Twomi UAT"/></label>{formError && <p className="form-error" role="alert">{formError}</p>}<div className="form-footer"><Button type="button" variant="outline" onClick={() => setWorkspaceDialog(false)} disabled={saving}>Cancel</Button><Button type="submit" disabled={saving || !workspaceName.trim()}>{saving ? 'Creating…' : 'Create workspace'}</Button></div></form></DialogContent></Dialog>
 <Dialog open={caseDialog} onOpenChange={open => { if (!saving)
        setCaseDialog(open); }}><DialogContent className="form-dialog"><DialogHeader><DialogTitle>{editing ? 'Edit test case' : 'New test case'}</DialogTitle><DialogDescription>{editing ? `Saving creates revision ${editing.revision + 1}. Existing runs keep their original snapshot.` : 'Define a repeatable flow and the result you expect.'}</DialogDescription></DialogHeader><form onSubmit={saveCase}><label>Project<Input required maxLength={100} value={draft.project} onChange={e => setDraft({ ...draft, project: e.target.value })} placeholder="Arcana"/></label><label>Android package / iOS bundle ID <span className="muted">· required for non-default apps</span><Input maxLength={240} value={draft.app_id} onChange={e => setDraft({ ...draft, app_id: e.target.value })} placeholder="com.example.arcana"/></label><label>Test name<Input required maxLength={160} value={draft.title} onChange={e => setDraft({ ...draft, title: e.target.value })} placeholder="Sign in with an invalid password"/></label><div className="form-row"><label>Platform<Choice value={draft.platform} onChange={v => setDraft({ ...draft, platform: v as 'Android' | 'iOS' })} items={['Android', 'iOS']} label="Platform"/></label><label>Suite<Input required maxLength={80} value={draft.suite} onChange={e => setDraft({ ...draft, suite: e.target.value })}/></label></div><label>Goal<Textarea required maxLength={4000} value={draft.goal} onChange={e => setDraft({ ...draft, goal: e.target.value })} placeholder="Verify that an invalid password is rejected."/></label><label>Preconditions <span className="muted">(optional)</span><Textarea maxLength={4000} value={draft.preconditions} onChange={e => setDraft({ ...draft, preconditions: e.target.value })} placeholder="App installed; signed out; test account available."/></label><label>Steps <span className="muted">· one per line</span><Textarea required maxLength={8000} rows={4} value={draft.steps} onChange={e => setDraft({ ...draft, steps: e.target.value })} placeholder={'Open the sign-in screen\nEnter the test email\nEnter an invalid password\nTap Sign in'}/></label><label>Expected result<Textarea required maxLength={4000} value={draft.expected} onChange={e => setDraft({ ...draft, expected: e.target.value })} placeholder="An incorrect-password error appears. The user stays signed out."/></label><label>Exact visible text for automated pass <span className="muted">(optional)</span><Input maxLength={240} value={draft.assertion_text} onChange={e => setDraft({ ...draft, assertion_text: e.target.value })} placeholder="Incorrect password"/></label><p className="snapshot-note">Jev uses this exact on-screen text as an independent pass check. Without it, a completed automated run is inconclusive.</p>{formError && <p className="form-error" role="alert">{formError}</p>}<div className="form-footer"><Button type="button" variant="outline" onClick={() => setCaseDialog(false)} disabled={saving}>Cancel</Button><Button type="submit" disabled={saving}>{saving ? 'Saving…' : editing ? 'Save revision' : 'Create test case'}</Button></div></form></DialogContent></Dialog>
 <Dialog open={!!runCase} onOpenChange={open => { if (!open && !saving)
        setRunCase(null); }}><DialogContent className="form-dialog"><DialogHeader><DialogTitle>Record a manual run</DialogTitle><DialogDescription>{runCase?.title} · revision {runCase?.revision}. This saves your observations; it does not execute the app.</DialogDescription></DialogHeader><form onSubmit={saveRun}><label>App build<Input required maxLength={120} value={runDraft.build} onChange={e => setRunDraft({ ...runDraft, build: e.target.value })} placeholder="1.0.0 (142)"/></label><label>Device and OS<Input required maxLength={160} value={runDraft.device} onChange={e => setRunDraft({ ...runDraft, device: e.target.value })} placeholder={runCase?.platform === 'iOS' ? 'iPhone 16 · iOS 18' : 'Pixel 9 · Android 15'}/></label><label>Outcome<Choice value={runDraft.status} onChange={status => setRunDraft({ ...runDraft, status })} items={[...statuses]} label="Run outcome"/></label><label>Observed result<Textarea required rows={5} maxLength={8000} value={runDraft.notes} onChange={e => setRunDraft({ ...runDraft, notes: e.target.value })} placeholder="What happened? Include any failed expectations and relevant timing."/></label><p className="snapshot-note">Attach evidence after saving. Use “Inconclusive” when the outcome cannot be verified, or “Execution error” for device or runner failures.</p>{formError && <p className="form-error" role="alert">{formError}</p>}<div className="form-footer"><Button type="button" variant="outline" disabled={saving} onClick={() => setRunCase(null)}>Cancel</Button><Button type="submit" disabled={saving}>{saving ? 'Saving…' : 'Save run'}</Button></div></form></DialogContent></Dialog>
 </SidebarProvider>;
}
function Empty({ icon: Icon, title, text, children }: {
    icon: typeof Files;
    title: string;
    text: string;
    children?: React.ReactNode;
}) { return <div className="empty"><span className="empty-icon"><Icon size={28}/></span><h2>{title}</h2><p className="empty-copy">{text}</p>{children}</div>; }

function JevAuditView({ audit }: { audit: NonNullable<Run['trace'][number]['jev']> }) {
    const percent = (value: number) => `${(value * 100).toFixed(1)}%`;
    const operation = audit.response.answers.operation;
    const label = (value: unknown) => {
        if (typeof value === 'string') return value;
        if (value && typeof value === 'object' && 'element' in value) return String(value.element);
        return JSON.stringify(value);
    };
    return <details className="jev-audit"><summary>Jev decision · {operation ? percent(operation.confidence) : '—'} confidence · {audit.latency_ms} ms</summary><div className="jev-audit-body"><div className="jev-audit-meta">Model {audit.response.model || audit.request.model} · {Object.keys(audit.request.questions).length} questions</div>{Object.entries(audit.request.questions).map(([name, question]) => {
        const answer = audit.response.answers[name];
        const options = Object.entries(question.criteria).sort(([left], [right]) => (answer?.probabilities[right] ?? 0) - (answer?.probabilities[left] ?? 0));
        return <section className="jev-question" key={name}><div className="jev-question-heading"><b>{name.replaceAll('_', ' ')}</b><span>{answer ? `Selected ${answer.choice} · ${percent(answer.confidence)} confidence` : 'No answer'}</span></div><div className="jev-options">{options.map(([key, value]) => <div className={answer?.choice === key ? 'jev-option selected' : 'jev-option'} key={key}><span><b>{key}</b> {label(value)}</span><strong>{answer?.probabilities[key] == null ? '—' : percent(answer.probabilities[key])}</strong></div>)}</div></section>;
    })}<details className="jev-json"><summary>Request and Jev output JSON</summary><pre>{JSON.stringify(audit, null, 2)}</pre></details></div></details>;
}
