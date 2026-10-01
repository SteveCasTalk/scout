'use client';

import { useMemo, useState } from 'react';
import { ArrowUpRight, ChevronDown, Download, FileText, Film, Image as ImageIcon, Layers, Pencil, Play, Workflow } from 'lucide-react';
import { CheckpointReport } from './checkpoints';
import { Button } from '@/components/ui/button';
import type { Evidence, Run, TestCase } from '@/lib/contracts';

type Props = {
    cases: TestCase[];
    allCases: TestCase[];
    onAssignSuite: (cases: TestCase[], suite: string) => Promise<void>;
    onRunSuite: (cases: TestCase[]) => void;
    onCreate: (suite: string, project: string) => void;
    runs: Run[];
    evidence: Evidence[];
    runnerReady: boolean;
    runningCaseId: string | null;
    saving: boolean;
    projectName: (test: TestCase) => string;
    onEdit: (test: TestCase) => void;
    onExport: (test: TestCase) => void;
    onRun: (test: TestCase) => void;
    onRecord: (test: TestCase) => void;
    onOpenRun: (run: Run, file?: Evidence) => void;
    onCanvas: (test: TestCase) => void;
};
const filters = ['All cases', 'Passed', 'Needs attention', 'Not run'] as const;
const date = (value: string) => new Date(value).toLocaleString(undefined, { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' });
function Outcome({ run }: { run?: Run }) {
    return <span className={`status status-${run ? run.status.toLowerCase().replaceAll(' ', '-') : 'not-run'}`}><span className="case-status-dot"/>{run?.status || 'Not run'}</span>;
}
export function TestCaseLibrary(props: Props) {
    const [filter, setFilter] = useState<typeof filters[number]>('All cases');
    const [sort, setSort] = useState('updated');
    const [grouping, setGrouping] = useState('suite');
    const [organizing, setOrganizing] = useState(false), [selected, setSelected] = useState<string[]>([]);
    const [suiteName, setSuiteName] = useState(''), [assigning, setAssigning] = useState(false), [error, setError] = useState('');
    const busy = assigning || props.saving || !!props.runningCaseId;
    const chosen = props.allCases.filter(test => selected.includes(test.id));
    async function assignSuite() {
        setAssigning(true); setError('');
        try { await props.onAssignSuite(chosen, suiteName.trim()); setSelected([]); setSuiteName(''); }
        catch (error) { setError((error as Error).message); }
        finally { setAssigning(false); }
    }
    const rows = useMemo(() => props.cases.map(test => {
        const runs = props.runs.filter(run => run.case_id === test.id).sort((a, b) => b.created.localeCompare(a.created));
        const ids = new Set(runs.map(run => run.id));
        return { test, runs, latest: runs[0] as Run | undefined, files: props.evidence.filter(file => ids.has(file.run_id)) };
    }), [props.cases, props.runs, props.evidence]);
    const matches = (latest: Run | undefined, value: typeof filters[number]) => value === 'All cases' || (value === 'Not run' ? !latest : value === 'Passed' ? latest?.status === 'Passed' : !!latest && latest.status !== 'Passed');
    const visible = rows.filter(row => matches(row.latest, filter)).sort((a, b) => sort === 'title' ? a.test.title.localeCompare(b.test.title) : sort === 'run' ? (b.latest?.created || '').localeCompare(a.latest?.created || '') : b.test.updated.localeCompare(a.test.updated));
    const projects = Array.from(new Set(visible.map(row => props.projectName(row.test))));
    const ticketKey = (test: TestCase) => test.ticket_key?.trim().toUpperCase() || test.title.match(/\b[A-Z][A-Z0-9]+-\d+\b/i)?.[0].toUpperCase() || 'No ticket';
    const groupKey = (test: TestCase) => grouping === 'suite' ? test.suite || 'Unsorted' : ticketKey(test);
    const suiteCases = (project: string, suite: string) => props.allCases.filter(test => props.projectName(test) === project && (test.suite || 'Unsorted') === suite).sort((a,b) => a.title.localeCompare(b.title));
    return <div className="studio-library">
        <div className="case-group-toolbar"><label className="case-sort">Group by<select value={grouping} onChange={event => setGrouping(event.target.value)}><option value="suite">Suite</option><option value="ticket">Jira ticket</option></select></label><span>Cases, suites, runs and evidence in one library</span><Button size="sm" variant="outline" aria-pressed={organizing} onClick={() => { setOrganizing(!organizing); setSelected([]); setError(''); }}> {organizing ? 'Done organizing' : 'Organize suites'}</Button></div>
        {organizing && <div className="case-suite-organizer"><div><Button variant="outline" size="sm" disabled={busy || !visible.length} onClick={() => setSelected(old => Array.from(new Set([...old, ...visible.map(row => row.test.id)])))}>Select shown</Button><span>{chosen.length} selected (including hidden cases)</span><Button variant="ghost" size="sm" onClick={() => setSelected([])}>Clear</Button></div><div><input aria-label="Destination suite name" list="library-suite-names" placeholder="Choose or create a suite…" maxLength={80} value={suiteName} onChange={event => setSuiteName(event.target.value)}/><datalist id="library-suite-names">{Array.from(new Set(['Authentication', 'Profile', 'Livestream', 'Subscriptions', ...props.allCases.map(test => test.suite)])).map(name => <option value={name} key={name}/>)}</datalist><Button size="sm" disabled={busy || !chosen.length || !suiteName.trim()} onClick={() => void assignSuite()}>{assigning ? 'Moving…' : 'Move to suite'}</Button></div><p>Select cases and choose a suite name. New names create a group; Jira tickets remain optional.</p>{error && <p className="form-error" role="alert">{error}</p>}</div>}
        <div className="case-filter-bar">
            <div className="case-status-filters" aria-label="Filter by latest outcome">{filters.map(value => <button type="button" key={value} aria-pressed={filter === value} onClick={() => setFilter(value)}>{value}<span>{rows.filter(row => matches(row.latest, value)).length}</span></button>)}</div>
            <label className="case-sort">Sort by <select value={sort} onChange={event => setSort(event.target.value)}><option value="updated">Last updated</option><option value="run">Latest run</option><option value="title">Name</option></select></label>
        </div>
        <div className="case-list-caption"><span>{visible.length} {visible.length === 1 ? 'case' : 'cases'} shown · outcomes from each case’s latest run</span><span>Expand a case for steps, history and evidence</span></div>
        {projects.map(project => <section className="studio-case-project" key={project}>
            <div className="case-project-title"><Layers size={16}/><h3>{project}</h3><span>{visible.filter(row => props.projectName(row.test) === project).length} cases</span></div>
            {Array.from(new Set(visible.filter(row => props.projectName(row.test) === project).map(row => groupKey(row.test)))).map(ticket => <section className="studio-case-ticket" key={ticket}>
                <div className="case-ticket-title"><span className="ticket-badge">{ticket}</span><span>{visible.filter(row => props.projectName(row.test) === project && groupKey(row.test) === ticket).length} shown</span>{grouping === 'suite' && <div className="case-group-actions"><Button variant="ghost" size="sm" onClick={() => props.onCreate(ticket, project)}>Add case</Button><Button variant="outline" size="sm" disabled={busy || !props.runnerReady} onClick={() => props.onRunSuite(suiteCases(project, ticket))}><Play size={13}/>Run suite · {suiteCases(project, ticket).length}</Button></div>}</div>
                <div className="case-column-head" aria-hidden="true"><span>Test case</span><span>Latest outcome</span><span>Last run</span><span>Evidence</span></div>
                {visible.filter(row => props.projectName(row.test) === project && groupKey(row.test) === ticket).map(({ test, runs, latest, files }) => <details className="studio-case-row" key={test.id}>
                    <summary><span className="case-row-name">{organizing && <input type="checkbox" aria-label={`Select ${test.title}`} checked={selected.includes(test.id)} disabled={busy} onClick={event => event.stopPropagation()} onKeyDown={event => event.stopPropagation()} onChange={event => setSelected(old => event.target.checked ? [...old, test.id] : old.filter(id => id !== test.id))}/>}<ChevronDown size={15} className="case-expand"/><FileText size={17}/><span><b>{test.title}</b><small>{test.platform} · {grouping === 'suite' ? ticketKey(test) : test.suite} · v{test.revision}</small></span></span><Outcome run={latest}/><span className="case-last-run">{latest ? date(latest.created) : 'Not run yet'}<small>{runs.length} {runs.length === 1 ? 'run' : 'runs'}</small></span><span className="case-evidence-count"><ImageIcon size={13}/>{files.filter(file => file.mime.startsWith('image/')).length}<Film size={13}/>{files.filter(file => file.mime.startsWith('video/')).length}</span></summary>
                    <div className="studio-case-expanded">
                        <div className="case-actions"><Button size="sm" variant="outline" onClick={() => props.onEdit(test)}><Pencil size={13}/>Edit case</Button><Button size="sm" variant="ghost" onClick={() => props.onExport(test)}><Download size={13}/>Export</Button><Button size="sm" variant="ghost" onClick={() => props.onCanvas(test)}><Workflow size={13}/>Canvas</Button><span className="case-action-spacer"/><Button size="sm" variant="outline" onClick={() => props.onRecord(test)}>Record run</Button>{test.platform === 'Android' && <Button size="sm" onClick={() => props.onRun(test)} disabled={!props.runnerReady || !!props.runningCaseId || props.saving} title={!props.runnerReady ? 'Connect the local runner to execute this case' : undefined}><Play size={13}/>{props.runningCaseId === test.id ? 'Running…' : 'Run'}</Button>}</div>
                        <div className="case-definition"><section><h4>Goal</h4><p>{test.goal}</p><h4>Expected result</h4><p>{test.expected}</p></section><section><h4>Steps</h4><ol>{test.steps.split('\n').filter(Boolean).map((step, index) => <li key={index}>{step}</li>)}</ol>{test.preconditions && <><h4>Preconditions</h4><p>{test.preconditions}</p></>}</section></div>
                        <CheckpointReport definitions={test.checkpoints}/><div className="case-history-heading"><h4>Run history</h4><span>{runs.length} runs · {files.length} evidence files</span></div>
                        {runs.length ? runs.map(run => {
                            const artifacts = files.filter(file => file.run_id === run.id);
                            return <div className="case-history-item" key={run.id}><button type="button" className="case-history-open" onClick={() => props.onOpenRun(run)}><Play size={14}/><span><b>{date(run.created)}</b><small>{run.device} · Build {run.build} · v{run.snapshot.revision}</small></span><Outcome run={run}/><ArrowUpRight size={15}/></button>{run.status !== 'Passed' && <p className="case-run-reason">{run.notes || 'No reason was recorded.'}</p>}{artifacts.length > 0 && <details className="case-artifacts"><summary>{artifacts.length} evidence files</summary><div>{artifacts.map(file => <button type="button" key={file.id} onClick={() => props.onOpenRun(run, file)}>{file.mime.startsWith('video/') ? <Film size={14}/> : file.mime.startsWith('image/') ? <ImageIcon size={14}/> : <FileText size={14}/>}<span>{file.name}</span><ArrowUpRight size={12}/></button>)}</div></details>}</div>;
                        }) : <div className="case-history-empty"><Play size={20}/><div><b>Ready for its first run</b><p>Run or record a manual result. Screenshots and recordings will stay with the run.</p></div></div>}
                    </div>
                </details>)}
            </section>)}
        </section>)}
        {!visible.length && <div className="case-filter-empty"><FileText size={28}/><h3>No cases with this outcome</h3><p>Choose another outcome to see cases matching your search and project filters.</p><Button variant="outline" onClick={() => setFilter('All cases')}>Show all outcomes</Button></div>}
    </div>;
}
