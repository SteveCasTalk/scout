"use client";
import { exportCase as exportVersionedCase } from '@/lib/execution-contract';
import { readStoredItem } from '@/lib/browser-storage';
import { useCallback, useEffect, useRef, useState } from 'react';
import Link from 'next/link';
import { brand } from '@/lib/brand';
import { FlaskConical, Files, Play, Smartphone, Plus, ArrowUpRight, CircleDot, FolderOpen, Search, ArrowLeft, Upload, Download, Image as ImageIcon, Film, FileText, Pencil, RefreshCw, CheckCircle2, XCircle, Clock3, Layers, Workflow, ChartNoAxesCombined, Settings, BookOpen } from 'lucide-react';
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
import { caseInput, statuses, type TestCase, type Run, type Evidence, type Checkpoint, type CheckpointResult, type CheckpointReview, type ReviewNote } from '@/lib/contracts';
import { CheckpointEditor, CheckpointReport, checkpointResults } from '@/components/checkpoints';
import { StartingConditionsEditor, StartingConditionsReport, emptyStartingConditions, startingConditionResults } from '@/components/starting-conditions';
import { Insights } from '@/components/insights';
import { RunSession } from '@/components/run-session';
import { ExecutionEvidence } from '@/components/execution-evidence';
import { ScenarioMatrixPanel } from '@/components/scenario-matrix';
import { CompareRuns, BugDraft } from '@/components/run-review';
import { TestCaseLibrary } from '@/components/test-case-library';
import { RunOutcome } from '@/components/run-outcome';
import { RunLogs, DeviceInfo, NotesPanel } from '@/components/run-diagnostics';
import { RunRecordings } from '@/components/run-recordings';
import { SandboxSettings, SandboxPicker, SandboxEvidence } from '@/components/sandbox';
import { FlowCanvas } from '@/components/flow-canvas';
type Workspace = { id: string; name: string; created: string };
const blank = { execution: null as import("@/lib/execution-contract").Execution | null, sandbox: null as import("@/lib/sandbox-contract").SandboxScenario | null, comparison_key: '', starting_conditions: emptyStartingConditions, checkpoints: [] as Checkpoint[], workspace_id: '', project: 'General', ticket_key: '', app_id: '', title: '', platform: 'Android' as 'Android' | 'iOS', suite: 'Smoke tests', goal: '', preconditions: '', steps: '', expected: '', assertion_text: '' };
const LOCAL_RUNNER = 'http://127.0.0.1:8765';
const nav = [{ label: 'Test cases', icon: Files }, { label: 'Insight', icon: ChartNoAxesCombined }, { label: 'Settings', icon: Settings }];
async function api<T>(path: string, init?: RequestInit): Promise<T> { const headers=new Headers(init?.headers);headers.set('X-Scout-Contract','2');const r = await fetch(path, {...init,headers}); const data = await r.json(); if (!r.ok)
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
    const [selectedRun, setSelectedRun] = useState<Run | null>(null), [selectedFile, setSelectedFile] = useState<Evidence | null>(null), [uploading, setUploading] = useState(false), [selectedCanvasCaseId, setSelectedCanvasCaseId] = useState(''), [selectedCanvasRunId, setSelectedCanvasRunId] = useState('');
    const [requestedRuns, setRequestedRuns] = useState<TestCase[] | null>(null);
    const [matrixCase, setMatrixCase] = useState<TestCase | null>(null);
    const [reviewNotes, setReviewNotes] = useState<ReviewNote[]>([]);
    const [checkpointReviews, setCheckpointReviews] = useState<CheckpointReview[]>([]);
    const [reviewMode, setReviewMode] = useState<'compare' | 'bug' | null>(null);
    const [localRunnerReady, setLocalRunnerReady] = useState(false), [runningCaseId, setRunningCaseId] = useState<string | null>(null);
    const fileInput = useRef<HTMLInputElement>(null);
    const [refreshing, setRefreshing] = useState(false);
    const refreshInFlight = useRef(false);
    const casesRef = useRef<TestCase[]>([]);
    const deepLinkHandled = useRef(false);
    const syncPromptRunsRef = useRef<(runId?: string) => Promise<void>>(async () => {});
    const load = useCallback(async () => { setLoading(true); setError(''); try {
        const [w, c, r, e] = await Promise.all([api<Workspace[]>('/api/workspaces'), api<TestCase[]>('/api/cases'), api<Run[]>('/api/runs'), api<Evidence[]>('/api/evidence')]);
        setWorkspaces(w);
        let chosen = selectedWorkspaceId && w.some(item => item.id === selectedWorkspaceId) ? selectedWorkspaceId : '';
        if (!chosen) {
            const params = new URLSearchParams(window.location.search);
            const requested = params.get('workspace') || params.get('project') || readStoredItem(localStorage, 'scout-workspace-id');
            chosen = w.find(item => item.id === requested || item.name.toLowerCase() === requested?.toLowerCase())?.id || w[0]?.id || '';
            if (chosen) { setSelectedWorkspaceId(chosen); localStorage.setItem('scout-workspace-id', chosen); }
            if (!w.length) setWorkspaceDialog(true);
        }
        casesRef.current = c;
        setCases(c);
        setRuns(r);
        setEvidence(e);
        return true;
    }
    catch (e) {
        setError((e as Error).message);
        return false;
    }
    finally {
        setLoading(false);
    } }, [selectedWorkspaceId]);
    // eslint-disable-next-line react-hooks/set-state-in-effect
    useEffect(() => { void load(); }, [load]);
    useEffect(() => { if (!selectedWorkspaceId) return; let active = true; void api<CheckpointReview[]>(`/api/checkpoint-reviews?workspace=${encodeURIComponent(selectedWorkspaceId)}`).then(items => { if (active) setCheckpointReviews(items); }).catch(error => { if (active) toast.error(`Could not load checkpoint reviews: ${(error as Error).message}`); }); return () => { active = false; }; }, [selectedWorkspaceId]);
    async function saveCheckpointReview(item: CheckpointResult, decision: 'accept' | 'dispute', explanation: string) { if (!selectedRun) throw new Error('Open a saved run to review its checkpoint.'); const review = await api<CheckpointReview>('/api/checkpoint-reviews', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ run_id: selectedRun.id, checkpoint_id: item.id, decision, explanation }) }); setCheckpointReviews(old => [review, ...old]); toast.success('Checkpoint review saved'); }
    useEffect(() => { if (!selectedWorkspaceId) return; let active = true; void api<ReviewNote[]>(`/api/notes?workspace=${encodeURIComponent(selectedWorkspaceId)}`).then(items => { if (active) setReviewNotes(items); }).catch(error => { if (active) toast.error(`Could not load notes: ${(error as Error).message}`); }); return () => { active = false; }; }, [selectedWorkspaceId]);
    async function createNote(type: 'case' | 'run', id: string, body: string) { const note = await api<ReviewNote>('/api/notes', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ target_type: type, target_id: id, body }) }); setReviewNotes(old => [note, ...old]); }
    async function updateNote(note: ReviewNote, body: string) { const saved = await api<Pick<ReviewNote, 'id' | 'body' | 'updated'>>('/api/notes', { method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ id: note.id, body }) }); setReviewNotes(old => old.map(item => item.id === saved.id ? { ...item, ...saved } : item)); }
    async function deleteNote(note: ReviewNote) { await api('/api/notes', { method: 'DELETE', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ id: note.id }) }); setReviewNotes(old => old.filter(item => item.id !== note.id)); }
    useEffect(() => { let active = true; const check = async () => { try { const response = await fetch(LOCAL_RUNNER + '/health'); if (active) setLocalRunnerReady(response.ok); } catch { if (active) setLocalRunnerReady(false); } }; void check(); const timer = setInterval(check, 10000); return () => { active = false; clearInterval(timer); }; }, []);
    function go(v: string) { setReviewMode(null); setView(v); setSelectedRun(null); setSelectedFile(null); setQuery(''); setPlatform('All platforms'); }
    function edit(c?: TestCase) { if (runningCaseId) { toast.error('Wait for the active run to finish before changing case definitions.'); return; } setEditing(c || null); setDraft(c ? { execution: c.execution || null, sandbox: c.sandbox || null, comparison_key: c.comparison_key || '', starting_conditions: c.starting_conditions || emptyStartingConditions, checkpoints: c.checkpoints || [], workspace_id: c.workspace_id, project: c.project || 'General', ticket_key: c.ticket_key || '', app_id: c.app_id || '', title: c.title, platform: c.platform, suite: c.suite, goal: c.goal, preconditions: c.preconditions, steps: c.steps, expected: c.expected, assertion_text: c.assertion_text || '' } : { ...blank, workspace_id: selectedWorkspaceId, project: selectedWorkspace?.name || 'General' }); setFormError(''); setCaseDialog(true); }
    async function createPlatformVariant() {
        if (!editing) return;
        if(draft.execution){setFormError("Execution actions currently require Android. Create and adapt a separate case for the other platform.");return;}
        setSaving(true); setFormError('');
        try {
            const body = caseInput.parse({ ...draft, comparison_key: draft.comparison_key || `scenario_${editing.id.replaceAll('-', '')}` });
            const saved = await api<TestCase>('/api/cases', { method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ ...body, id: editing.id, revision: editing.revision }) });
            casesRef.current = [saved, ...casesRef.current.filter(item => item.id !== saved.id)]; setCases(casesRef.current);
            setEditing(null); setDraft({ ...body, execution: body.execution || null, platform: body.platform === 'Android' ? 'iOS' : 'Android', app_id: '' });
            toast.success('Source revision saved. Set the other platform’s app ID and adapt its steps before creating the variant.');
        } catch (error) { setFormError((error as Error).message); } finally { setSaving(false); }
    }
    async function saveCase(event: React.FormEvent) { event.preventDefault(); setSaving(true); setFormError(''); try {
        const body = caseInput.parse(draft);
        const c = await api<TestCase>('/api/cases', { method: editing ? 'PUT' : 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(editing ? { ...body, id: editing.id, revision: editing.revision } : body) });
        casesRef.current = [c, ...casesRef.current.filter(x => x.id !== c.id)];
        setCases(casesRef.current);
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
        setView('Test cases');
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
    function exportCase(c: TestCase) { downloadJson(`scout-case-${c.id}-v${c.revision}.json`, exportVersionedCase({ ...c, review_notes: reviewNotes.filter(note => note.target_type === 'case' && note.target_id === c.id) })); }
    async function saveScoutResult(result: Record<string, unknown>, localArtifacts?: { runId: string; artifacts: string[] }, options: { quiet?: boolean; throwOnError?: boolean; openReport?: boolean } = {}): Promise<{ saved: boolean; attachedEvidence: number; evidenceFailures: string[] }> {
        setSaving(true);
        try {
            if (result.schema_version !== 1 || !['Scout Android runner', 'Scout iOS runner', 'Jev Android runner', 'Jev iOS runner'].includes(String(result.source))) throw new Error('Choose a result.json created by the Scout mobile runner.');
            const resultPlatform = result.platform === 'iOS' ? 'iOS' : result.platform === 'Android' || (result.platform == null && ['Scout Android runner', 'Jev Android runner'].includes(String(result.source))) ? 'Android' : null;
            if (!resultPlatform) throw new Error('Result has an unsupported platform.');
            const promptRun = String(result.case_id || '').startsWith('prompt-');
            const existingRun = localArtifacts && runs.find(run => run.external_run_id === localArtifacts.runId);
            let selectedCase = casesRef.current.find(c => c.id === result.case_id) || (existingRun ? casesRef.current.find(c => c.id === existingRun.case_id) || existingRun.snapshot : undefined);
            if (!selectedCase && promptRun) {
                const synthetic = caseInput.parse({ execution: (result.execution as {definition?:unknown}|undefined)?.definition || null, sandbox: result.sandbox_scenario || null, starting_conditions: result.starting_conditions || emptyStartingConditions, checkpoints: result.checkpoints || [], workspace_id: selectedWorkspaceId, project: String(result.project || selectedWorkspace?.name || 'General'), app_id: String(result.package || ''), title: String(result.case_title || 'Prompt-driven test'), platform: resultPlatform, suite: String(result.suite || 'Prompt runs'), ticket_key: String(result.ticket_key || ''), goal: String(result.goal || 'Run initiated from an assistant prompt.'), preconditions: String(result.preconditions || 'Executed from a prompt-driven MCP request.'), steps: String(result.case_steps || 'See the run trace.'), expected: String(result.expected_result || 'Review the run evidence.'), assertion_text: String(result.expected_text || '') });
                selectedCase = casesRef.current.find(c => c.platform === synthetic.platform && c.workspace_id === synthetic.workspace_id && c.project === synthetic.project && c.app_id === synthetic.app_id && c.suite === synthetic.suite && c.title === synthetic.title && c.goal === synthetic.goal && c.steps === synthetic.steps && c.expected === synthetic.expected && c.assertion_text === synthetic.assertion_text && JSON.stringify(c.checkpoints || []) === JSON.stringify(synthetic.checkpoints) && JSON.stringify(c.starting_conditions || emptyStartingConditions) === JSON.stringify(synthetic.starting_conditions) && JSON.stringify(c.sandbox || null) === JSON.stringify(synthetic.sandbox) && JSON.stringify(c.execution || null) === JSON.stringify(synthetic.execution || null));
                if (!selectedCase) {
                    selectedCase = await api<TestCase>('/api/cases', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(synthetic) });
                    casesRef.current = [selectedCase!, ...casesRef.current];
                    setCases(casesRef.current);
                }
            }
            if (!selectedCase) throw new Error('This result has no matching test case.');
            if (selectedCase.revision !== result.revision && !promptRun && !result.matrix) throw new Error('The test case was revised after this run. Export and run its current revision.');
            if(JSON.stringify(selectedCase.execution||null)!==JSON.stringify((result.execution as {definition?:unknown}|undefined)?.definition||null))throw new Error('The result execution definition must match the saved revision.');
            if (selectedCase.platform !== resultPlatform) throw new Error('The result platform must match the test case.');
            if (!statuses.includes(result.status as typeof statuses[number])) throw new Error('Runner result has an invalid status.');
            if (!Array.isArray(result.steps)) throw new Error('Runner result is missing its action trace.');
            const trace = result.steps.map(item => {
                const step = item as Record<string, unknown>;
                const rawAudit = step.jev as { request?: { model?: string; questions?: Record<string, { type?: string; criteria?: Record<string, unknown> }> }; response?: unknown; latency_ms?: number } | undefined;
                const compactAudit = rawAudit?.request && rawAudit.response ? { request: { model: rawAudit.request.model || '', questions: Object.fromEntries(Object.entries(rawAudit.request.questions || {}).map(([name, question]) => [name, { type: question.type || '', criteria: question.criteria || {} }])) }, response: rawAudit.response, latency_ms: Number(rawAudit.latency_ms || 0) } : undefined;
                return { step: Number(step.step), operation: String(step.operation || ''), label: step.label == null ? null : String(step.label), elapsed_ms: Number(step.elapsed_ms || 0), screenshot: step.screenshot == null ? null : String(step.screenshot), ...(step.verification ? { verification: step.verification } : {}), ...(step.checkpoint_results ? { checkpoint_results: step.checkpoint_results } : {}), ...(step.starting_condition_results ? { starting_condition_results: step.starting_condition_results } : {}), ...(compactAudit ? { jev: compactAudit } : {}) };
            });
            const verification = result.verification as { status?: string; method?: string; expected_text?: string; observed_text?: string } | undefined;
            if (verification && !trace.some(step => step.operation === 'VERIFY_RESULT')) {
                trace.push({ step: Number(result.steps.length), operation: 'VERIFY_RESULT', label: null, elapsed_ms: Number(result.elapsed_ms || 0), screenshot: null, verification: { status: ['passed', 'failed', 'inconclusive', 'not_run'].includes(verification.status || '') ? verification.status : 'not_run', method: String(verification.method || 'exact_visible_text'), expected_text: String(verification.expected_text || ''), observed_text: String(verification.observed_text || '') } });
            }
            const body = { caseId: selectedCase.id, revision: Number(result.revision), externalRunId: localArtifacts?.runId, status: result.status, build: String(result.build || 'unknown'), device: String(result.device || 'unknown'), device_info: result.device_info || {}, app_logs: String(result.app_logs || ''), notes: String(result.notes || 'No runner notes.'), source: promptRun ? 'Prompt run' : 'Scout import', trace };
            let saved: Run & { duplicate?: boolean };
            if (result.matrix) {
                const linked = await api<{id:string;duplicate?:boolean}>('/api/library', {method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({action:'save_run',workspace:selectedCase.workspace_id,run:{...body,matrix:result.matrix}})});
                const detail = await api<{run:Run}>(`/api/library?action=run&workspace=${selectedCase.workspace_id}&run_id=${linked.id}`);
                saved = {...detail.run,duplicate:linked.duplicate};
            } else saved = await api<Run & { duplicate?: boolean }>('/api/runs', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) });
            const runId = saved.id;
            if (!saved.duplicate) {
                setRuns(old => [saved, ...old]);
                if (options.openReport !== false) {
                    setView('Test cases');
                    setSelectedRun(saved);
                }
            }
            const savedEvidence: Evidence[] = [];
            const failedEvidence: string[] = [];
            async function attachEvidence(evidenceFile: File) {
                let lastError: unknown;
                for (let attempt = 0; attempt < 3; attempt++) {
                    try {
                        const form = new FormData();
                        form.append('file', evidenceFile);
                        form.append('runId', runId);
                        savedEvidence.push(await api<Evidence>('/api/evidence', { method: 'POST', body: form }));
                        return;
                    } catch (error) {
                        lastError = error;
                        if (attempt < 2) await new Promise(resolve => setTimeout(resolve, 300 * (attempt + 1)));
                    }
                }
                throw lastError;
            }
            if (localArtifacts) {
                const existingNames = new Set(evidence.filter(item => item.run_id === runId).map(item => item.name));
                for (const name of localArtifacts.artifacts.filter(name => name !== 'result.json' && !existingNames.has(name))) {
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
            if (savedEvidence[0] && !saved.duplicate && options.openReport !== false) setSelectedFile(savedEvidence[0]);
            if (failedEvidence.length) {
                if (!options.quiet) toast.error('Run saved, but some evidence could not be attached: ' + failedEvidence.join(', '));
            } else if (!options.quiet && !saved.duplicate) toast.success(`${promptRun ? 'Prompt run' : 'Scout run'} saved under ${selectedCase.project}`);
            return { saved: !saved.duplicate, attachedEvidence: savedEvidence.length, evidenceFailures: failedEvidence };
        } catch (error) {
            if (options.throwOnError) throw error;
            toast.error((error as Error).message);
            return { saved: false, attachedEvidence: 0, evidenceFailures: [] };
        }
        finally { setSaving(false); }
    }
    async function syncPromptRuns(runId?: string) {
        if (!localRunnerReady) return;
        try {
            const promptRuns: { run_id: string; result: Record<string, unknown>; artifacts: string[] }[] = [];
            let cursor: string | undefined;
            do {
                const path = LOCAL_RUNNER + '/runs' + (cursor ? `?before=${encodeURIComponent(cursor)}` : '');
                const response = await fetch(path);
                const data = await response.json() as { runs?: { run_id: string; result: Record<string, unknown>; artifacts: string[] }[]; next_cursor?: string | null; error?: string };
                if (!response.ok) throw new Error(data.error || 'Could not list local MCP runs.');
                promptRuns.push(...(data.runs || []).filter(localRun => !runId || localRun.run_id === runId));
                cursor = data.next_cursor || undefined;
            } while (cursor && (!runId || !promptRuns.length));
            if (!promptRuns.length) { toast.info(runId ? 'That MCP run was not found locally.' : 'No local prompt-driven MCP runs were found.'); return; }
            let imported = 0, repairedEvidence = 0;
            const failures: string[] = [], evidenceFailures: string[] = [];
            for (const localRun of promptRuns) {
                const existing = runs.find(run => run.external_run_id === localRun.run_id);
                try {
                    const outcome = await saveScoutResult(localRun.result, { runId: localRun.run_id, artifacts: localRun.artifacts }, { quiet: true, throwOnError: true, openReport: !!runId });
                    if (existing) repairedEvidence += outcome.attachedEvidence;
                    else if (outcome.saved) imported++;
                    if (outcome.evidenceFailures.length) evidenceFailures.push(`${String(localRun.result.case_title || localRun.run_id)}: ${outcome.evidenceFailures.join(', ')}`);
                } catch (error) { failures.push(`${String(localRun.result.case_title || localRun.run_id)}: ${(error as Error).message}`); }
            }
            const freshRuns = await api<Run[]>('/api/runs');
            setRuns(freshRuns);
            const newestImported = freshRuns.find(run => promptRuns.some(localRun => run.external_run_id === localRun.run_id));
            if (newestImported) {
                const freshEvidence = await api<Evidence[]>('/api/evidence');
                setEvidence(freshEvidence);
                if (runId) {
                    setView('Test cases');
                    setSelectedRun(newestImported);
                    setSelectedFile(freshEvidence.find(item => item.run_id === newestImported.id) || null);
                }
            }
            if (failures.length || evidenceFailures.length) toast.error(`${imported} run(s) synced; ${failures.length} run(s) failed and ${evidenceFailures.length} still have missing evidence. ${[...failures, ...evidenceFailures].slice(0, 2).join(' · ')}`);
            else if (imported) toast.success(`${imported} prompt run(s) synced${repairedEvidence ? `; restored ${repairedEvidence} evidence file(s)` : ''}.`);
            else toast.success(`MCP run history is up to date${repairedEvidence ? `; restored ${repairedEvidence} evidence file(s)` : ''}.`);
        } catch (error) { toast.error((error as Error).message); }
    }
    async function refreshWorkspace() {
        if (refreshInFlight.current) return;
        refreshInFlight.current = true;
        setRefreshing(true);
        try {
            const loaded = await load();
            if (loaded && localRunnerReady) await syncPromptRuns();
        } finally {
            refreshInFlight.current = false;
            setRefreshing(false);
        }
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
                setView('Test cases');
                setSelectedRun(report);
                setSelectedFile(freshEvidence.find(item => item.run_id === report.id) || null);
                toast.success(`Opened ${report.snapshot.project} test report`);
            } else toast.error('The prompt run could not be found in the dashboard. Use Refresh in Test cases to retry.');
            window.history.replaceState(null, '', window.location.pathname);
        })();
    }, [loading, localRunnerReady]);
    useEffect(() => {
        if (loading || deepLinkHandled.current) return;
        const id = new URLSearchParams(window.location.search).get('run');
        const target = id && runs.find(run => run.id === id && run.workspace_id === selectedWorkspaceId);
        if (target) { deepLinkHandled.current = true; setSelectedRun(target); setSelectedFile(evidence.find(file => file.run_id === target.id) || null); setView('Test cases'); }
    }, [loading, runs, evidence, selectedWorkspaceId]);
    function runOnDashboard(testCase: TestCase) { setRequestedRuns([testCase]); }
    async function assignSuite(selected: TestCase[], suite: string) {
        try {
            for (const test of selected) {
                const updated = await api<TestCase>('/api/cases', { method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ ...test, suite }) });
                casesRef.current = casesRef.current.map(item => item.id === updated.id ? updated : item);
                setCases(casesRef.current);
            }
            toast.success(`Moved ${selected.length} cases into ${suite}`);
        } catch (error) { await load(); throw error; }
    }
    function openRun(r: Run, file?: Evidence) {
        setReviewMode(null); setView('Test cases'); setSelectedRun(r); setSelectedFile(file || null);
        if (file?.mime.startsWith('video/')) requestAnimationFrame(() => document.getElementById(`recording-${file.id}`)?.scrollIntoView({ behavior: 'smooth', block: 'center' }));
    }
    function exportRun() { if (!selectedRun)
        return; const bundle = { ...selectedRun, review_notes: reviewNotes.filter(note => note.target_type === 'run' && note.target_id === selectedRun.id), checkpoint_reviews: checkpointReviews.filter(review => review.run_id === selectedRun.id), evidence: evidence.filter(e => e.run_id === selectedRun.id).map(e => ({ ...e, url: new URL(`/api/evidence/${e.id}`, location.origin).href })) }; const a = document.createElement('a'); a.href = URL.createObjectURL(new Blob([JSON.stringify(bundle, null, 2)], { type: 'application/json' })); a.download = `scout-run-${selectedRun.id}.json`; a.click(); setTimeout(() => URL.revokeObjectURL(a.href), 1000); }
    useEffect(() => { const context = (document as unknown as {
        modelContext?: {
            registerTool: (tool: unknown, options: {
                signal: AbortSignal;
            }) => Promise<void> | void;
        };
    }).modelContext; if (!context?.registerTool)
        return; const lifecycle = new AbortController(); try {
        void Promise.resolve(context.registerTool({ name: 'navigate_test_workspace', description: 'Navigate to Test cases, Insight, or Settings. Insight summarizes verification findings; Settings includes a local HTTP/WebSocket sandbox scenario library. Canvas is available inside each case. Does not create or execute a test.', inputSchema: { type: 'object', properties: { view: { type: 'string', enum: ['Test cases', 'Insight', 'Settings'] } }, required: ['view'], additionalProperties: false }, annotations: { readOnlyHint: true }, execute: async (input: unknown) => { const value = (input as {
                view?: string;
            })?.view; if (!value || !nav.some(n => n.label === value))
                throw new Error('Choose Test cases, Insight, or Settings.'); setView(value); setSelectedRun(null); setSelectedFile(null); setQuery(''); setPlatform('All platforms'); await new Promise<void>(resolve => requestAnimationFrame(() => requestAnimationFrame(() => resolve()))); return { view: value }; } }, { signal: lifecycle.signal })).catch(console.error);
    }
    catch (e) {
        console.error(e);
    } return () => lifecycle.abort(); }, []);
    const selectedWorkspace = workspaces.find(item => item.id === selectedWorkspaceId);
    function switchWorkspace(id: string) { setSelectedWorkspaceId(id); setProjectFilter('All projects'); setQuery(''); setSelectedRun(null); setSelectedFile(null); const url = new URL(window.location.href); url.searchParams.set('workspace', id); url.searchParams.delete('project'); url.searchParams.delete('syncRun'); window.history.replaceState(null, '', url); localStorage.setItem('scout-workspace-id', id); }
    const workspaceCases = cases.filter(c => c.workspace_id === selectedWorkspaceId);
    const workspaceRuns = runs.filter(r => r.workspace_id === selectedWorkspaceId);
    const workspaceEvidence = evidence.filter(e => e.workspace_id === selectedWorkspaceId);
    const projectNames = Array.from(new Set([...workspaceCases.map(c => c.project || 'General'), ...workspaceRuns.map(r => r.snapshot.project || 'General')])).sort((a,b) => a.localeCompare(b));
    const canvasProjectName = (c: TestCase) => c.app_id === 'com.torilab.twomi.uat' && ['AI Avatar', 'Twomi', 'Twomi UAT'].includes(c.project) ? 'Custom Avatar' : c.project || 'General';
    const filteredCases = workspaceCases.filter(c => (projectFilter === 'All projects' || canvasProjectName(c) === projectFilter) && (platform === 'All platforms' || c.platform === platform) && `${c.title} ${c.suite} ${c.project} ${c.ticket_key || ''}`.toLowerCase().includes(query.toLowerCase()));
    const filteredRuns = workspaceRuns.filter(r => (projectFilter === 'All projects' || (r.snapshot.project || 'General') === projectFilter) && `${r.snapshot.title} ${r.snapshot.project} ${r.build} ${r.status}`.toLowerCase().includes(query.toLowerCase()));
    const filteredEvidence = workspaceEvidence.filter(e => e.name.toLowerCase().includes(query.toLowerCase()) && (projectFilter === 'All projects' || workspaceRuns.find(r => r.id === e.run_id)?.snapshot.project === projectFilter));
    const runFiles = evidence.filter(e => e.run_id === selectedRun?.id);
    const canvasProjects = Array.from(new Set(workspaceCases.map(canvasProjectName))).sort((a,b) => a.localeCompare(b)).map(project => ({ project, tickets: Array.from(new Set(workspaceCases.filter(c => canvasProjectName(c) === project).map(c => c.ticket_key?.trim().toUpperCase() || c.title.match(/\b[A-Z][A-Z0-9]+-\d+\b/i)?.[0].toUpperCase() || 'Unlinked'))).sort((a,b) => a.localeCompare(b)).map(ticket => ({ ticket, cases: workspaceCases.filter(c => canvasProjectName(c) === project && (c.ticket_key?.trim().toUpperCase() || c.title.match(/\b[A-Z][A-Z0-9]+-\d+\b/i)?.[0].toUpperCase() || 'Unlinked') === ticket) })) }));
    const selectedCanvasCase = workspaceCases.find(c => c.id === selectedCanvasCaseId) || workspaceCases[0] || null;
    const canvasRuns = selectedCanvasCase ? workspaceRuns.filter(r => r.case_id === selectedCanvasCase.id).sort((a,b) => b.created.localeCompare(a.created)) : [];
    const activeCanvasRun = canvasRuns.find(r => r.id === selectedCanvasRunId) || canvasRuns[0] || null;
    const canvasRunFiles = activeCanvasRun ? evidence.filter(e => e.run_id === activeCanvasRun.id) : [];
    return <SidebarProvider className="studio-workspace"><Toaster richColors position="bottom-right"/><Sidebar><SidebarHeader><Link className="brand" href="/"><img src="/favicon.svg" alt="" width="34" height="34"/><span>{brand.name}<small>Studio</small></span></Link><div className="workspace"><span className="project-icon"><Layers size={17}/></span><div className="workspace-picker"><Choice value={selectedWorkspace?.name || ''} onChange={name => { const match = workspaces.find(item => item.name === name); if (match) switchWorkspace(match.id); }} items={workspaces.map(item => item.name)} label="Select workspace"/><small>{workspaceCases.length} tests · {workspaceRuns.length} runs</small></div><Button size="icon" variant="ghost" aria-label="Create workspace" title="Create workspace" onClick={() => { setWorkspaceName(''); setFormError(''); setWorkspaceDialog(true); }}><Plus size={17}/></Button></div></SidebarHeader><SidebarContent><div className="nav-label">WORKSPACE</div><SidebarMenu>{nav.map(({ label, icon: Icon }) => <SidebarMenuItem key={label}><SidebarMenuButton isActive={view === label || (label === 'Test cases' && view === 'Canvas')} onClick={() => go(label)}><Icon /><span>{label}</span>{label === 'Test cases' && <span className="nav-count">{workspaceCases.length}</span>}</SidebarMenuButton></SidebarMenuItem>)}</SidebarMenu><div className="nav-label">RESOURCES</div><SidebarMenu><SidebarMenuItem><SidebarMenuButton asChild><Link href="/docs"><BookOpen/><span>Documentation</span></Link></SidebarMenuButton></SidebarMenuItem></SidebarMenu></SidebarContent><SidebarFooter><div className="runner-note"><Smartphone size={20}/><b>Device connection</b><p>{localRunnerReady ? "Your local runner is connected." : "Start the local bridge to run mobile tests."}</p><span>{localRunnerReady ? 'Device runner ready' : 'Device runner offline'}</span></div><div className="profile"><span>{brand.initials}</span><div>{brand.name}<small>{selectedWorkspace?.name || 'Private testing workspace'}</small></div></div></SidebarFooter></Sidebar><SidebarInset><header className="topbar"><div><SidebarTrigger /><span>{selectedWorkspace?.name || 'Workspace'}</span><span className="slash">/</span><b>{view === 'Canvas' ? 'Test cases' : view}</b>{view === 'Canvas' && <><span className="slash">/</span><span className="breadcrumb-case">{selectedCanvasCase?.title || 'Case'} · Canvas</span></>}{selectedRun && <><span className="slash">/</span><span className="breadcrumb-case">{selectedRun.snapshot.title}</span></>}</div><span className="phase"><CircleDot size={14}/> Mobile runner · {localRunnerReady ? 'Ready' : 'Bridge offline'}</span></header><div className="studio-body">{(view === 'Test cases' || view === 'Canvas') && <aside className="studio-tree" aria-label="Project test cases"><div className="sidebar-projects"><div className="studio-tree-heading"><b>Test cases</b><Button variant="outline" size="icon" aria-label="New test case" title="New test case" disabled={loading || refreshing || saving || !!error || !!runningCaseId} onClick={() => edit()}><Plus size={16}/></Button></div><label className="studio-tree-search"><Search size={14}/><Input aria-label="Search project tree" placeholder="Find a test case…" value={query} onChange={event => setQuery(event.target.value)}/></label>{canvasProjects.map(group => <details key={group.project} open className="sidebar-project"><summary><Layers size={14}/>{group.project}</summary>{group.tickets.map(ticket => <details key={ticket.ticket} open className="sidebar-ticket"><summary>{ticket.ticket === 'Unlinked' ? 'No ticket' : ticket.ticket}</summary>{ticket.cases.filter(c => `${c.title} ${group.project} ${ticket.ticket}`.toLowerCase().includes(query.toLowerCase())).map(c => <button key={c.id} type="button" className={selectedRun?.case_id === c.id || (view === 'Canvas' && selectedCanvasCase?.id === c.id) ? 'sidebar-case selected' : 'sidebar-case'} onClick={() => { const latest = workspaceRuns.filter(r => r.case_id === c.id).sort((a, b) => b.created.localeCompare(a.created))[0]; if (latest && view !== 'Canvas') openRun(latest); else { setView('Canvas'); setSelectedRun(null); setSelectedCanvasCaseId(c.id); setSelectedCanvasRunId(''); } }}><Files size={14}/><span>{c.title}</span></button>)}</details>)}</details>)}</div></aside>}<main className={`content ${selectedRun ? "run-content" : view === "Canvas" ? "canvas-content" : "library-content"}`}>
 <ScenarioMatrixPanel test={matrixCase} onClose={() => setMatrixCase(null)} onOpenRun={openRun} onRefresh={async () => { await load(); }} onBusy={setRunningCaseId} disabled={!localRunnerReady || !!runningCaseId || saving}/>
 <RunSession requested={requestedRuns} onClose={() => setRequestedRuns(null)} onBusy={setRunningCaseId} onComplete={async job => { if (!job.result) throw new Error('Runner completed without a result.'); const saved = await saveScoutResult(job.result, { runId: job.run_id, artifacts: job.artifacts || [] }, { quiet: true, throwOnError: true }); if (saved.evidenceFailures.length) throw new Error('Run saved, but evidence sync failed. Retrying: ' + saved.evidenceFailures.join(', ')); }}/>
 {selectedRun && reviewMode === 'compare' && <CompareRuns key={selectedRun.id} run={selectedRun} runs={workspaceRuns} cases={workspaceCases} files={workspaceEvidence} onClose={() => setReviewMode(null)}/>}
 {selectedRun && reviewMode === 'bug' && <BugDraft key={selectedRun.id} run={selectedRun} files={runFiles} reviews={checkpointReviews} onClose={() => setReviewMode(null)}/>}

 {view === 'Insight' ? <Insights runs={workspaceRuns} reviews={checkpointReviews} onOpen={openRun}/> : view === 'Settings' ? <SandboxSettings/> : selectedRun ? <><button className="back" onClick={() => setSelectedRun(null)}><ArrowLeft size={15}/> {view === 'Canvas' ? 'Back to canvas' : 'Back to test cases'}</button><div className="heading"><div><div className="eyebrow">{(workspaceCases.find(c => c.id === selectedRun.case_id) ? canvasProjectName(workspaceCases.find(c => c.id === selectedRun.case_id)!) : selectedRun.snapshot.project || 'General')} · RUN {selectedRun.id.slice(0, 8).toUpperCase()} · {selectedRun.source === 'Prompt run' ? 'PROMPT RUN' : ['Scout import', 'Jev import'].includes(selectedRun.source) ? 'SCOUT RUNNER IMPORT' : 'MANUALLY RECORDED'}</div><div className="studio-run-title"><span className="studio-title-icon"><FileText size={25}/></span><h1>{selectedRun.snapshot.title}</h1><Status value={selectedRun.status}/></div><p className="studio-run-goal">{selectedRun.snapshot.goal}</p>{selectedRun.snapshot.matrix && <p className="matrix-run-label">Scenario: {selectedRun.snapshot.matrix.variant_label} · Matrix v{selectedRun.snapshot.matrix.matrix_revision}</p>}<div className="run-meta"><span>{selectedRun.snapshot.platform} · {selectedRun.device}</span><span>Build {selectedRun.build}</span></div></div><div className="heading-actions">{workspaceCases.some(c => c.id === selectedRun.case_id) && <Button onClick={() => { const current = workspaceCases.find(c => c.id === selectedRun.case_id); if (current) void runOnDashboard(current); }} disabled={!localRunnerReady || !!runningCaseId || saving}><Play size={15}/>{runningCaseId === selectedRun.case_id ? 'Running…' : 'Run again'}</Button>}<Button variant="outline" onClick={() => setReviewMode('compare')}>Compare runs</Button>{selectedRun.status !== 'Passed' && <Button variant="outline" onClick={() => setReviewMode('bug')}>Draft bug report</Button>}<Button variant="outline" onClick={exportRun}><Download size={16}/> Export run</Button></div></div><RunOutcome run={selectedRun} files={runFiles} onEvidence={file => { setSelectedFile(file); requestAnimationFrame(() => document.querySelector('.evidence-preview-details')?.scrollIntoView({ behavior: 'smooth', block: 'center' })); }}/><ExecutionEvidence definition={selectedRun.snapshot.execution} files={runFiles}/><StartingConditionsReport defined={selectedRun.snapshot.starting_conditions} results={startingConditionResults(selectedRun.trace)}/><CheckpointReport definitions={selectedRun.snapshot.checkpoints} results={checkpointResults(selectedRun)} run={selectedRun} files={runFiles} onEvidence={file => { setSelectedFile(file); requestAnimationFrame(() => document.querySelector('.evidence-preview-details')?.scrollIntoView({ behavior: 'smooth', block: 'center' })); }} reviews={checkpointReviews} onReview={saveCheckpointReview}/><Tabs key={selectedRun.id} defaultValue="evidence" className="studio-run-tabs"><TabsList><TabsTrigger value="evidence">Evidence</TabsTrigger><TabsTrigger value="details">Run details</TabsTrigger><TabsTrigger value="network">Network</TabsTrigger><TabsTrigger value="logs">Logs</TabsTrigger><TabsTrigger value="device">Device info</TabsTrigger><TabsTrigger value="notes">Notes</TabsTrigger></TabsList><TabsContent value="evidence"><div className="run-layout"><section className="panel evidence-panel"><div className="panel-heading"><h2>Canvas</h2><Button size="sm" onClick={() => fileInput.current?.click()} disabled={uploading}>{uploading ? 'Uploading…' : <><Upload size={14}/> Attach evidence</>}</Button><input ref={fileInput} type="file" hidden accept="image/png,image/jpeg,image/webp,video/mp4,video/webm,video/quicktime,audio/mpeg,audio/wav,audio/x-wav,text/plain,application/json" onChange={e => void upload(e.target.files?.[0])}/></div><FlowCanvas key={selectedRun.id} run={selectedRun} files={runFiles}/>{!selectedFile?.mime.startsWith('video/') && <details key={selectedFile?.id} open={!!selectedFile} className="evidence-preview-details"><summary>Preview selected evidence</summary><div className="viewer">{selectedFile ? selectedFile.mime.startsWith('image/') ? <img src={`/api/evidence/${selectedFile.id}`} alt={selectedFile.name}/> : <div className="file-preview"><FileText size={44}/><h2>{selectedFile.name}</h2><a href={`/api/evidence/${selectedFile.id}`} download>Download file <Download size={14}/></a></div> : <div className="empty"><span className="empty-icon"><Film size={28}/></span><h2>The evidence belongs here</h2><p>Attach a device recording, screenshot, or log.<br />PNG, JPEG, WebP, MP4, WebM, MOV, MP3, WAV, TXT, JSON · Up to 25 MB</p></div>}</div></details>}{runFiles.length > 0 && <div className="file-strip">{runFiles.map(f => <button className={selectedFile?.id === f.id ? 'file-chip selected' : 'file-chip'} key={f.id} onClick={() => { setSelectedFile(f); if (f.mime.startsWith('video/')) document.getElementById(`recording-${f.id}`)?.scrollIntoView({ behavior: 'smooth', block: 'center' }); }}>{f.mime.startsWith('video/') ? <Film size={16}/> : f.mime.startsWith('image/') ? <ImageIcon size={16}/> : <FileText size={16}/>}<span>{f.name}<small>{bytes(f.size)}</small></span></button>)}</div>}</section><RunRecordings files={runFiles}/></div></TabsContent><TabsContent value="details"><section className="panel run-side"><Tabs defaultValue="result"><TabsList><TabsTrigger value="result">Result</TabsTrigger><TabsTrigger value="test">Test snapshot</TabsTrigger></TabsList><TabsContent value="result"><div className="detail-label">RUN DETAILS</div><dl><dt>Recorded</dt><dd>{date(selectedRun.created)}</dd><dt>Test revision</dt><dd>v{selectedRun.snapshot.revision}</dd><dt>Source</dt><dd>{selectedRun.source === 'Prompt run' ? 'Prompt-driven MCP run' : ['Scout import', 'Jev import'].includes(selectedRun.source) ? 'Scout mobile runner import' : 'Manual report'}</dd><dt>Evidence</dt><dd>{runFiles.length} files</dd></dl>{selectedRun.trace?.length > 0 && <><div className="detail-label">ACTION TIMELINE</div><div className="action-timeline">{selectedRun.trace.map(step => <div key={step.step} className="timeline-entry"><button type="button" className="timeline-step" onClick={() => { const match = runFiles.find(f => f.name === step.screenshot); if (match) setSelectedFile(match); }}><span className="timeline-index">{step.step}</span><span><b>{step.operation}</b>{step.label && <> · {step.label}</>}<small>{step.elapsed_ms == null ? '' : `${(step.elapsed_ms / 1000).toFixed(1)}s`}{step.screenshot && runFiles.some(f => f.name === step.screenshot) ? ' · screenshot' : ''}</small></span></button>{step.jev && <JevAuditView audit={step.jev}/>}</div>)}</div></>}</TabsContent><TabsContent value="test"><div className="detail-label">GOAL</div><p className="preserve">{selectedRun.snapshot.goal}</p><div className="detail-label">PRECONDITIONS</div><p className="preserve">{selectedRun.snapshot.preconditions || 'None specified'}</p><div className="detail-label">TEST STEPS</div><ol className="steps">{selectedRun.snapshot.steps.split('\n').filter(Boolean).map((s, i) => <li key={i}>{s}</li>)}</ol><p className="snapshot-note">Saved with this run. Later test edits do not change this snapshot. These are intended steps, not a captured execution trace.</p></TabsContent></Tabs></section></TabsContent><TabsContent value="network"><SandboxEvidence key={selectedRun.id} scenario={selectedRun.snapshot.sandbox} files={runFiles}/></TabsContent><TabsContent value="logs"><RunLogs run={selectedRun} files={runFiles} onEvidence={setSelectedFile}/></TabsContent><TabsContent value="device"><DeviceInfo run={selectedRun}/></TabsContent><TabsContent value="notes"><NotesPanel key={selectedRun.id} targetType="run" targetId={selectedRun.id} notes={reviewNotes} onCreate={createNote} onUpdate={updateNote} onDelete={deleteNote}/></TabsContent></Tabs></> : <>
 {view === 'Canvas' && <button className="back" onClick={() => go('Test cases')}><ArrowLeft size={15}/>Back to test cases</button>}
 <div className="heading"><div><div className="eyebrow">TESTING WORKSPACE</div><h1>{view === 'Canvas' ? 'Case canvas' : view}</h1><p>{view === 'Test cases' ? 'Organize suites, run cases, and review every outcome in one place.' : view === 'Test runs' ? 'Every outcome, tied to the exact test that produced it.' : view === 'Canvas' ? 'Explore this case’s captured steps, recordings, and run history.' : 'The recordings, screenshots, and logs behind your results.'}</p></div><div className="heading-actions"><Button variant="outline" onClick={() => void refreshWorkspace()} disabled={loading || refreshing || saving} title={localRunnerReady ? 'Reload dashboard data and sync local MCP runs and evidence' : 'Reload dashboard data. Connect the local runner to sync MCP runs.'}><RefreshCw size={16} className={refreshing ? 'animate-spin' : undefined}/>{refreshing ? 'Refreshing…' : 'Refresh'}</Button></div></div>
 <div className="stats">{[['Test cases', workspaceCases.length, 'In this workspace'], ['Recorded runs', workspaceRuns.length, `${workspaceRuns.filter(r => r.status === 'Passed').length} passed · ${workspaceRuns.filter(r => r.status === 'Failed').length} failed`], ['Evidence files', workspaceEvidence.length, 'Stored with workspace runs']].map(([label, n, note]) => <div className="stat" key={String(label)}><span>{label}</span><strong>{loading ? '—' : n}</strong><small>{note}</small></div>)}</div>
 {error ? <div className="error-panel" role="alert"><h2>Workspace unavailable</h2><p>{error}</p><Button variant="outline" onClick={() => void load()}>Try again</Button><a href="/signin-with-chatgpt?return_to=/" target="_top">Sign in again</a></div> : <section className="panel"><div className="panel-heading"><h2>{view === 'Test cases' ? 'Test library' : view === 'Test runs' ? 'Run history' : view === 'Canvas' ? 'Case canvas' : 'Evidence library'}</h2><span>{view === 'Test cases' ? 'Android & iOS · grouped by project' : view === 'Test runs' ? 'Manual, Jev, and prompt runs' : view === 'Canvas' ? 'Projects → tickets → test cases' : 'Stored with each run'}</span></div><div className="toolbar"><label className="search"><Search size={16}/><Input value={query} onChange={e => setQuery(e.target.value)} placeholder={`Search ${view.toLowerCase()}…`} aria-label={`Search ${view.toLowerCase()}`}/></label><Choice value={projectFilter} onChange={setProjectFilter} items={['All projects', ...(view === 'Canvas' || view === 'Test cases' ? canvasProjects.map(group => group.project) : projectNames)]} label="Filter project"/>{view === 'Test cases' && <Choice value={platform} onChange={setPlatform} items={['All platforms', 'Android', 'iOS']} label="Filter platform"/>}</div>
 {loading ? <div className="loading">{[1, 2, 3].map(i => <Skeleton className="h-14 w-full" key={i}/>)}</div> : view === 'Canvas' ? <div className="canvas-workspace"><aside className="canvas-tree-panel"><div className="canvas-tree-heading"><b>Test map</b><span>{workspaceCases.length} cases</span></div>{canvasProjects.filter(group => projectFilter === 'All projects' || group.project === projectFilter).map(group => <details className="canvas-project" key={group.project} open><summary><Layers size={15}/><b>{group.project}</b><span>{group.tickets.reduce((n, ticket) => n + ticket.cases.length, 0)}</span></summary>{group.tickets.map(ticket => <details className="canvas-ticket" key={ticket.ticket} open><summary><span className="ticket-badge">{ticket.ticket === 'Unlinked' ? 'No ticket' : ticket.ticket}</span><span>{ticket.cases.length}</span></summary><div className="canvas-case-list">{ticket.cases.filter(c => (platform === 'All platforms' || c.platform === platform) && `${c.title} ${c.suite} ${c.project} ${c.ticket_key || ''}`.toLowerCase().includes(query.toLowerCase())).map(c => <button type="button" key={c.id} className={selectedCanvasCase?.id === c.id ? 'canvas-case-link selected' : 'canvas-case-link'} onClick={() => { setSelectedCanvasCaseId(c.id); setSelectedCanvasRunId(''); }}><Files size={14}/><span>{c.title}</span><small>{workspaceRuns.filter(r => r.case_id === c.id).length}</small></button>)}</div></details>)}</details>)}</aside><section className="canvas-stage">{selectedCanvasCase ? <><div className="canvas-stage-heading"><div><div className="eyebrow">{canvasProjectName(selectedCanvasCase)} · {selectedCanvasCase.ticket_key || selectedCanvasCase.title.match(/\b[A-Z][A-Z0-9]+-\d+\b/i)?.[0] || 'No ticket linked'}</div><h2>{selectedCanvasCase.title}</h2><p>{selectedCanvasCase.suite} · {selectedCanvasCase.platform} · Revision {selectedCanvasCase.revision}</p></div><Button size="sm" variant="outline" onClick={() => edit(selectedCanvasCase)}><Pencil size={14}/> Edit case</Button></div>{canvasRuns.length > 0 && <div className="canvas-run-picker"><span>Run history</span>{canvasRuns.map(run => <button type="button" key={run.id} className={activeCanvasRun?.id === run.id ? 'canvas-run-chip selected' : 'canvas-run-chip'} onClick={() => setSelectedCanvasRunId(run.id)}><Status value={run.status}/><small>{date(run.created)}</small></button>)}</div>}{activeCanvasRun ? <><div className="canvas-active-run"><div><b>Run {activeCanvasRun.id.slice(0, 8).toUpperCase()}</b><span>{activeCanvasRun.device} · Build {activeCanvasRun.build} · {date(activeCanvasRun.created)}</span></div><Status value={activeCanvasRun.status}/><Button size="sm" variant="ghost" onClick={() => openRun(activeCanvasRun)}>Run details <ArrowUpRight size={14}/></Button></div><RunOutcome run={activeCanvasRun} files={canvasRunFiles} onEvidence={file => openRun(activeCanvasRun, file)}/><div className="canvas-evidence-layout"><FlowCanvas key={activeCanvasRun.id} run={activeCanvasRun} files={canvasRunFiles}/><RunRecordings files={canvasRunFiles}/></div></> : <div className="canvas-no-selection"><Workflow size={30}/><h3>No runs for this test case yet</h3><p>Run this case or record a manual run to populate its canvas.</p>{['Android', 'iOS'].includes(selectedCanvasCase.platform) && <Button onClick={() => void runOnDashboard(selectedCanvasCase)} disabled={!localRunnerReady || runningCaseId === selectedCanvasCase.id || saving}><Play size={14}/>{runningCaseId === selectedCanvasCase.id ? 'Running…' : 'Run'}</Button>}</div>}</> : <div className="canvas-no-selection"><Workflow size={30}/><h3>No test cases in this workspace</h3><p>Create a test case and it will appear in the tree.</p></div>}</section></div> : view === 'Test cases' ? filteredCases.length ? <TestCaseLibrary key={selectedWorkspaceId} cases={filteredCases} allCases={workspaceCases} onAssignSuite={assignSuite} onRunSuite={setRequestedRuns} onCreate={(suite, project) => { edit(); setDraft(old => ({ ...old, suite, project })); }} runs={workspaceRuns} evidence={workspaceEvidence} runnerReady={localRunnerReady} runningCaseId={runningCaseId} saving={saving} projectName={canvasProjectName} onEdit={edit} onExport={exportCase} onRun={test => void runOnDashboard(test)} onMatrix={setMatrixCase} onRecord={record} onOpenRun={openRun} notes={reviewNotes} onCreateNote={createNote} onUpdateNote={updateNote} onDeleteNote={deleteNote} onCanvas={test => { setSelectedCanvasCaseId(test.id); setSelectedCanvasRunId(''); setView('Canvas'); setSelectedRun(null); }}/> : <Empty icon={Files} title={workspaceCases.length ? 'No matching tests' : 'A home for your first test'} text={workspaceCases.length ? 'Try another search, project or platform.' : 'Describe a flow, define what success looks like, and keep the evidence together.'}></Empty> : view === 'Test runs' ? filteredRuns.length ? <Table><TableHeader><TableRow><TableHead>Test / build</TableHead><TableHead>Outcome</TableHead><TableHead>Device</TableHead><TableHead>Recorded</TableHead><TableHead>Evidence</TableHead></TableRow></TableHeader><TableBody>{filteredRuns.map(r => <TableRow key={r.id}><TableCell><button className="case-title" onClick={() => openRun(r)}><span className="row-icon"><Play size={15}/></span><span>{r.snapshot.title}<small>{r.snapshot.project || 'General'} · Build {r.build} · v{r.snapshot.revision} · {r.source === 'Prompt run' ? 'Prompt' : r.source === 'Jev import' ? 'Scout runner' : 'Manual'}</small></span></button></TableCell><TableCell><Status value={r.status}/></TableCell><TableCell>{r.device}<small className="cell-small">{r.snapshot.platform}</small></TableCell><TableCell className="muted">{date(r.created)}</TableCell><TableCell><Button variant="ghost" size="sm" onClick={() => openRun(r)}>{evidence.filter(e => e.run_id === r.id).length} files <ArrowUpRight size={14}/></Button></TableCell></TableRow>)}</TableBody></Table> : <Empty icon={Play} title={runs.length ? 'No matching runs' : 'Your next run starts with a test'} text="Record a manual result from the test library, then attach the evidence."><Button variant="outline" onClick={() => go('Test cases')}>Open test library <ArrowUpRight size={15}/></Button></Empty> : filteredEvidence.length ? <div className="evidence-grid">{filteredEvidence.map(e => <button className="evidence-card" key={e.id} onClick={() => { const r = runs.find(r => r.id === e.run_id); if (r) {
                openRun(r);
                setSelectedFile(e);
            } }}><div className="evidence-thumb">{e.mime.startsWith('image/') ? <img src={`/api/evidence/${e.id}`} alt={e.name}/> : e.mime.startsWith('video/') ? <Film size={34}/> : <FileText size={34}/>}</div><b>{e.name}</b><small>{bytes(e.size)} · {date(e.created)}</small><span>View in run <ArrowUpRight size={13}/></span></button>)}</div> : <Empty icon={FolderOpen} title={evidence.length ? 'No matching evidence' : 'More than a pass or fail'} text="Attach recordings, screenshots, and logs to a run. They will appear here."><Button variant="outline" onClick={() => go('Test cases')}>View test runs <ArrowUpRight size={15}/></Button></Empty>}
 </section>}<div className="bottom-note"><FlaskConical size={16}/> Built for observable, repeatable mobile testing.</div></>}
 </main></div></SidebarInset>
 <Dialog open={workspaceDialog} onOpenChange={open => { if (!saving) setWorkspaceDialog(open); }}><DialogContent className="form-dialog"><DialogHeader><DialogTitle>Create a workspace</DialogTitle><DialogDescription>Keep test cases, runs, and evidence together for one app, team, or environment.</DialogDescription></DialogHeader><form onSubmit={createWorkspace}><label>Workspace name<Input required autoFocus maxLength={100} value={workspaceName} onChange={event => setWorkspaceName(event.target.value)} placeholder="Twomi UAT"/></label>{formError && <p className="form-error" role="alert">{formError}</p>}<div className="form-footer"><Button type="button" variant="outline" onClick={() => setWorkspaceDialog(false)} disabled={saving}>Cancel</Button><Button type="submit" disabled={saving || !workspaceName.trim()}>{saving ? 'Creating…' : 'Create workspace'}</Button></div></form></DialogContent></Dialog>
 <Dialog open={caseDialog} onOpenChange={open => { if (!saving)
        setCaseDialog(open); }}><DialogContent className="form-dialog"><DialogHeader><DialogTitle>{editing ? 'Edit test case' : 'New test case'}</DialogTitle><DialogDescription>{editing ? `Saving creates revision ${editing.revision + 1}. Existing runs keep their original snapshot.` : 'Define a repeatable flow and the result you expect.'}</DialogDescription></DialogHeader><form onSubmit={saveCase}><label>Project<Input required maxLength={100} value={draft.project} onChange={e => setDraft({ ...draft, project: e.target.value })} placeholder="Arcana"/></label><label>Ticket key <span className="muted">· optional</span><Input maxLength={40} value={draft.ticket_key} onChange={e => setDraft({ ...draft, ticket_key: e.target.value.toUpperCase() })} placeholder="CA-4492"/></label><label>Android package / iOS bundle ID <span className="muted">· required for non-default apps</span><Input maxLength={240} value={draft.app_id} onChange={e => setDraft({ ...draft, app_id: e.target.value })} placeholder="com.example.arcana"/></label><label>Test name<Input required maxLength={160} value={draft.title} onChange={e => setDraft({ ...draft, title: e.target.value })} placeholder="Sign in with an invalid password"/></label><div className="form-row"><label>Platform<Choice value={draft.platform} onChange={v => setDraft({ ...draft, platform: v as 'Android' | 'iOS' })} items={['Android', 'iOS']} label="Platform"/></label><label>Suite<Input required maxLength={80} value={draft.suite} onChange={e => setDraft({ ...draft, suite: e.target.value })}/></label></div><label>Cross-platform scenario key <span className="muted">· optional</span><Input maxLength={80} pattern="[A-Za-z0-9_-]*" value={draft.comparison_key} onChange={e => setDraft({ ...draft, comparison_key: e.target.value })} placeholder="email_login"/></label><p className="snapshot-note">Use the same key and checkpoint IDs for Android and iOS versions of this scenario in this project. Each version keeps its own app ID and steps. Saved runs keep their original definitions.</p><label>Goal<Textarea required maxLength={4000} value={draft.goal} onChange={e => setDraft({ ...draft, goal: e.target.value })} placeholder="Verify that an invalid password is rejected."/></label><label>Preconditions <span className="muted">(optional)</span><Textarea maxLength={4000} value={draft.preconditions} onChange={e => setDraft({ ...draft, preconditions: e.target.value })} placeholder="App installed; signed out; test account available."/></label><label>Steps <span className="muted">· one per line</span><Textarea required maxLength={8000} rows={4} value={draft.steps} onChange={e => setDraft({ ...draft, steps: e.target.value })} placeholder={'Open the sign-in screen\nEnter the test email\nEnter an invalid password\nTap Sign in'}/></label><label>Expected result<Textarea required maxLength={4000} value={draft.expected} onChange={e => setDraft({ ...draft, expected: e.target.value })} placeholder="An incorrect-password error appears. The user stays signed out."/></label>{draft.execution && <details><summary>Execution definition · version 2</summary><pre>{JSON.stringify(draft.execution,null,2)}</pre><p>Edit typed actions through Scout case authoring. These settings are preserved when saving this form.</p></details>}<SandboxPicker project={draft.project} value={draft.sandbox} onChange={sandbox => setDraft({ ...draft, sandbox })}/><StartingConditionsEditor value={draft.starting_conditions} onChange={starting_conditions => setDraft({ ...draft, starting_conditions })}/><CheckpointEditor value={draft.checkpoints} onChange={checkpoints => setDraft({ ...draft, checkpoints })}/><label>Legacy text assertion <span className="muted">(optional)</span><Input maxLength={240} value={draft.assertion_text} onChange={e => setDraft({ ...draft, assertion_text: e.target.value })} placeholder="Incorrect password"/></label><p className="snapshot-note">Used only when no checkpoints are defined. This checks a case-insensitive substring on the final screen. Without checkpoints or a text assertion, a completed run is inconclusive.</p>{formError && <p className="form-error" role="alert">{formError}</p>}<div className="form-footer">{editing && <Button type="button" variant="outline" disabled={saving} onClick={() => void createPlatformVariant()}>Save and prepare {draft.platform === 'Android' ? 'iOS' : 'Android'} variant</Button>}<Button type="button" variant="outline" onClick={() => setCaseDialog(false)} disabled={saving}>Cancel</Button><Button type="submit" disabled={saving}>{saving ? 'Saving…' : editing ? 'Save revision' : 'Create test case'}</Button></div></form></DialogContent></Dialog>
 <Dialog open={!!runCase} onOpenChange={open => { if (!open && !saving)
        setRunCase(null); }}><DialogContent className="form-dialog"><DialogHeader><DialogTitle>Record a manual run</DialogTitle><DialogDescription>{runCase?.title} · revision {runCase?.revision}. This saves your observations; it does not execute the app.</DialogDescription></DialogHeader><form onSubmit={saveRun}><label>App build<Input required maxLength={120} value={runDraft.build} onChange={e => setRunDraft({ ...runDraft, build: e.target.value })} placeholder="1.0.0 (142)"/></label><label>Device and OS<Input required maxLength={160} value={runDraft.device} onChange={e => setRunDraft({ ...runDraft, device: e.target.value })} placeholder={runCase?.platform === 'iOS' ? 'iPhone 16 · iOS 18' : 'Pixel 9 · Android 15'}/></label><label>Outcome<Choice value={runDraft.status} onChange={status => setRunDraft({ ...runDraft, status })} items={[...statuses]} label="Run outcome"/></label><label>Observed result<Textarea required rows={5} maxLength={8000} value={runDraft.notes} onChange={e => setRunDraft({ ...runDraft, notes: e.target.value })} placeholder="What happened? Include any failed expectations and relevant timing."/></label><p className="snapshot-note">Attach evidence after saving. Use “Blocked” when a prerequisite is missing, “Inconclusive” when the outcome cannot be verified, or “Execution error” for runner failures.</p>{formError && <p className="form-error" role="alert">{formError}</p>}<div className="form-footer"><Button type="button" variant="outline" disabled={saving} onClick={() => setRunCase(null)}>Cancel</Button><Button type="submit" disabled={saving}>{saving ? 'Saving…' : 'Save run'}</Button></div></form></DialogContent></Dialog>
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
    })}<details className="jev-json"><summary>Decision summary JSON · full audit is in jev-output.json evidence</summary><pre>{JSON.stringify(audit, null, 2)}</pre></details></div></details>;
}
