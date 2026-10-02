'use client';
import { useState } from 'react';
import { Button } from '@/components/ui/button';
import type { CheckpointReview, Run } from '@/lib/contracts';
import { checkpointResults } from './checkpoints';
function category(run: Run) {
    if (run.status === 'Execution error') return 'Runner issues';
    if (run.status === 'Blocked') return 'Blocked';
    const checks = checkpointResults(run);
    if (checks.some(item => item.required && item.verdict === 'violated')) return 'Possible bugs';
    if (run.status === 'Failed' && !checks.length) return 'Legacy failures';
    if (run.status === 'Inconclusive' || checks.some(item => item.required && ['not_reached','not_observable'].includes(item.verdict))) return 'Verification gaps';
    return 'Passed';
}
const categories = ['Possible bugs', 'Verification gaps', 'Blocked', 'Runner issues', 'Legacy failures', 'Passed'];
export function Insights({ runs, reviews, onOpen }: { runs: Run[]; reviews: CheckpointReview[]; onOpen: (run: Run) => void }) {
    const [filter, setFilter] = useState('All');
    const seen = new Set<string>();
    const latest = [...runs].sort((a,b) => b.created.localeCompare(a.created)).filter(run => { if (seen.has(run.case_id)) return false; seen.add(run.case_id); return true; });
    const visible = latest.filter(run => filter === 'All' || category(run) === filter);
    return <section className="insights"><div className="heading"><div><div className="eyebrow">EVIDENCE REVIEW</div><h1>Insight</h1><p>Latest run per case in this workspace. Possible bugs need human triage; classification is not confirmation.</p></div></div><div className="insight-summary">{categories.map(value => <button key={value} aria-pressed={filter === value} onClick={() => setFilter(filter === value ? 'All' : value)}><span>{value}</span><strong>{latest.filter(run => category(run) === value).length}</strong></button>)}</div><div className="case-filter-bar"><b>{filter} · {visible.length} cases</b>{filter !== 'All' && <Button variant="ghost" onClick={() => setFilter('All')}>Show all</Button>}</div>{visible.map(run => { const relevant = checkpointResults(run).filter(item => item.verdict !== 'satisfied'); const runReviews = reviews.filter(review => review.run_id === run.id); const latestReviews = new Map<string, CheckpointReview>(); for (const review of [...runReviews].sort((a,b) => b.created.localeCompare(a.created))) if (!latestReviews.has(review.checkpoint_id)) latestReviews.set(review.checkpoint_id, review); return <article className="insight-item" key={run.id}><div><span className="ticket-badge">{category(run)}</span><h2>{run.snapshot.title}</h2><small>{run.snapshot.suite} · {run.device} · Build {run.build} · {new Date(run.created).toLocaleString()}</small><p>{relevant.length ? relevant.map(item => `${item.id}: ${item.verdict.replaceAll('_',' ')}${latestReviews.get(item.id) ? ` · human ${latestReviews.get(item.id)!.decision === 'accept' ? 'accepted' : 'disputed'}` : ' · awaiting review'} — ${item.expected}`).join('\n') : run.notes}</p>{!checkpointResults(run).length && <small>No checkpoint report; categorized from the recorded legacy outcome.</small>}</div><Button size="sm" variant="outline" onClick={() => onOpen(run)}>Review evidence</Button></article>; })}{!visible.length && <div className="empty"><h2>No runs in this category</h2><p>Run cases with checkpoints to collect verifiable evidence.</p></div>}</section>;
}
