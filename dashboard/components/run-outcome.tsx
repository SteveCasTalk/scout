import { checkpointResults } from './checkpoints';
import type { Evidence, Run } from '@/lib/contracts';

function explanation(run: Run) {
    const checks = checkpointResults(run);
    if (checks.length) return run.status === 'Execution error' ? 'Execution stopped. Checkpoint evidence collected before the error is shown below.' : `${checks.filter(item => item.required && item.verdict === 'satisfied').length} of ${checks.filter(item => item.required).length} required checkpoints satisfied. Decisions and supporting observations are listed below; possible violations need review.`;
    const notes = run.notes.toLowerCase();
    if (run.source === 'Manual') return 'This outcome was recorded manually. The notes below explain the assessment.';
    if (run.status === 'Passed') return 'Jev verified the configured assertion. This result covers that assertion, not every behavior in the app.';
    if (run.status === 'Failed') return 'The configured check did not match the observed result. Review the expectation and evidence before treating this as an app bug.';
    if (run.status === 'Execution error') return 'The runner could not complete the test. This is an execution problem; the app behavior has not been established by this result.';
    if (/cycle|repeating|no observable screen change/.test(notes)) return 'Jev stopped because navigation repeated without making progress toward the expected result. The intended outcome remains unverified.';
    if (/maximum.*actions|step limit/.test(notes)) return 'Jev reached its action limit before verifying the expected result.';
    if (/no exact visible-text assertion/.test(notes)) return 'Navigation finished, but no exact text assertion was configured, so Jev could not assign a verified pass or fail.';
    return 'Jev did not collect enough evidence to verify a pass or fail. The recorded reason below explains where it stopped.';
}

export function RunOutcome({ run, files, onEvidence }: { run: Run; files: Evidence[]; onEvidence: (file: Evidence) => void }) {
    const trace = run.trace || [];
    const check = [...trace].reverse().find(step => step.verification)?.verification;
    const lastAction = [...trace].reverse().find(step => !['VERIFY_RESULT', 'DONE'].includes(step.operation));
    const screenshotStep = [...trace].reverse().find(step => step.screenshot && files.some(file => file.name === step.screenshot));
    const screenshot = screenshotStep && files.find(file => file.name === screenshotStep.screenshot);
    return <section className={`run-outcome outcome-${run.status.toLowerCase().replaceAll(' ', '-')}`} aria-label="Result explanation">
        <div className="outcome-summary">
            <div className="outcome-heading"><h2>Why this run is {run.status.toLowerCase()}</h2><p>{explanation(run)}</p></div>
            <div className="outcome-comparison"><b>Expected</b><p>{check?.expected_text || run.snapshot.assertion_text || run.snapshot.expected || 'No expectation was saved.'}</p></div>
            <div className="outcome-comparison"><b>Observed</b><p>{check?.observed_text || 'No final screen text was saved.'}</p></div>
        </div>
        <details className="outcome-more"><summary>Recorded reason & verification</summary>
            <div className="outcome-reason"><b>{run.source === 'Manual' ? 'Recorded reason' : 'Jev’s recorded reason'}</b><p>{run.notes || 'No reason was saved for this run.'}</p></div>
            <div className="outcome-facts">
                <div><b>Verification</b><p>{check ? `${check.status.replaceAll('_', ' ')} · ${check.method.replaceAll('_', ' ')}` : 'No verification result was saved.'}</p></div>
                <div><b>Last recorded action</b><p>{lastAction ? `Step ${lastAction.step + 1} · ${lastAction.operation.replaceAll('_', ' ')}${lastAction.label ? ` · ${lastAction.label}` : ''}` : 'No action trace was saved.'}</p></div>
            </div>
            {screenshot && <button type="button" className="outcome-evidence-link" onClick={() => onEvidence(screenshot)}>View last captured screen · Step {screenshotStep!.step + 1}</button>}
        </details>
    </section>;
}
