"""Build a standalone HTML summary of a project's latest saved runs. Reads nothing and runs nothing itself."""
from __future__ import annotations
import base64
import datetime
import html
import re
import shutil
import subprocess
import tempfile
from collections import Counter
from pathlib import Path
from typing import Any, Callable

ORDER = {'Failed': 0, 'Blocked': 1, 'Execution error': 2, 'Inconclusive': 3, 'Not run': 4, 'Passed': 5}
REASONS = {
    'prerequisite_missing': 'test data missing', 'account_not_configured': 'account has no username',
    'account_unverifiable': 'account not verified by this case', 'account_mismatch': 'wrong account signed in',
    'selector_missing': 'control not found', 'path_not_reached': 'path not reached', 'model_unsure': 'model unsure',
    'not_observable': 'not observable', 'evidence_incomplete': 'evidence incomplete', 'execution_blocked': 'blocked by a guard',
    'assertion_violated': 'check failed', 'runner_error': 'runner error', 'cleanup_failed': 'cleanup failed',
}
_SECRET = re.compile(r'eyJ[\w-]{10,}\.[\w-]{10,}\.[\w-]+|(?i:access-auth-token|authorization|password)\s*[:=]\s*\S+')
_REASON = re.compile(r'Reason code: ([a-z_]+)\.')
_FOOTER = re.compile(r'\[generate-test-cases\][^\n]*')
_CSS = r""":root{--bg:#f6f7f9;--card:#fff;--ink:#17202c;--mute:#5d6878;--line:#dfe3ea;--pass:#0b7a4b;--passb:#e0f5ea;--inc:#8a5a00;--incb:#fdf1d7;--no:#556070;--nob:#e9ecf1;--bad:#b3261e;--badb:#fde7e5;--acc:#0f766e;--noteb:#e8f4f8;--noteline:#7fb5c6}
@media(prefers-color-scheme:dark){:root{--bg:#10151c;--card:#19212b;--ink:#e8edf3;--mute:#9ba7b6;--line:#2c3744;--pass:#5fd39b;--passb:#123326;--inc:#efc167;--incb:#3a2d10;--no:#aab5c3;--nob:#2a333f;--bad:#ff8f87;--badb:#401c1a;--acc:#5ed0c4;--noteb:#16303a;--noteline:#3e7a8e}}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--ink);font:15px/1.5 -apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif}main{max-width:1040px;margin:auto;padding:28px 16px 64px}
h1{margin:0;font-size:28px}.sub{color:var(--mute);margin:4px 0 20px}.stats{display:flex;flex-wrap:wrap;gap:10px;margin-bottom:16px}.stat{background:var(--card);color:inherit;border:1px solid var(--line);border-radius:10px;padding:10px 16px;min-width:104px;text-align:left;cursor:pointer;font:inherit}.stat b{display:block;font-size:24px}.stat span{color:var(--mute);font-size:13px}.stat.on{border-color:var(--acc);box-shadow:inset 0 0 0 1px var(--acc)}
input{width:100%;padding:10px 12px;border:1px solid var(--line);border-radius:8px;background:var(--card);color:inherit;font:inherit;margin-bottom:22px}.notice{background:var(--noteb);border-left:3px solid var(--noteline);padding:12px 14px;border-radius:6px;margin-bottom:18px}.notice ul{margin:6px 0 0;padding-left:20px}
h2{font-size:18px;margin:26px 0 10px}h2 small{display:block;font-weight:400;color:var(--mute);font-size:13px;margin-top:2px}.case{background:var(--card);border:1px solid var(--line);border-radius:8px;margin-bottom:6px}summary{cursor:pointer;padding:10px 12px;display:flex;gap:10px;align-items:baseline}.t{overflow-wrap:anywhere}
.s{flex:none;font-size:12px;font-weight:600;padding:1px 8px;border-radius:99px;background:var(--nob);color:var(--no)}.s-passed{background:var(--passb);color:var(--pass)}.s-inconclusive{background:var(--incb);color:var(--inc)}.s-failed,.s-blocked,.s-execution-error{background:var(--badb);color:var(--bad)}
.body{padding:2px 14px 14px;border-top:1px solid var(--line)}.grid{display:grid;grid-template-columns:minmax(0,1fr) 190px;gap:18px}.grid img{width:100%;border-radius:8px;border:1px solid var(--line);margin-top:14px}h4{margin:14px 0 2px;font-size:12px;letter-spacing:.04em;text-transform:uppercase;color:var(--mute)}p{margin:2px 0 8px;overflow-wrap:anywhere}.m{color:var(--mute);font-size:13px}pre{white-space:pre-wrap;overflow-wrap:anywhere;margin:2px 0 8px;font:13px/1.5 ui-monospace,Menlo,monospace}.note{background:var(--noteb);border-left:3px solid var(--noteline);padding:9px 11px;border-radius:5px;margin-top:12px;font-size:14px}
.tw{overflow-x:auto;margin-top:10px}table{border-collapse:collapse;width:100%;font-size:13px}th,td{text-align:left;padding:6px 8px;border-top:1px solid var(--line);vertical-align:top}th{color:var(--mute);font-weight:600;border-top:0}code{font:12px ui-monospace,Menlo,monospace}.v-satisfied{color:var(--pass)}.v-violated{color:var(--bad)}.v-not_observable,.v-not_reached{color:var(--inc)}
@media(max-width:640px){.grid{grid-template-columns:1fr}.grid img{max-width:190px}summary{flex-wrap:wrap}}@media print{.stats,input{display:none}details{break-inside:avoid}}"""
_JS = r"""const q=document.getElementById('q');let f='';function go(){const t=q.value.toLowerCase();let any=false;document.querySelectorAll('section').forEach(s=>{let n=0;s.querySelectorAll('.case').forEach(c=>{const ok=(!f||c.dataset.status===f)&&(!t||c.dataset.text.includes(t));c.hidden=!ok;if(ok)n++});s.hidden=!n;if(n)any=true});document.getElementById('none').hidden=any}
q.addEventListener('input',go);document.querySelectorAll('.stat').forEach(b=>b.onclick=()=>{f=f===b.dataset.f?'':b.dataset.f;document.querySelectorAll('.stat').forEach(x=>x.classList.toggle('on',x.dataset.f===f));go()});"""


def status_of(item: dict[str, Any]) -> str:
    return item.get('latest_run_status') or 'Not run'


def reason_of(notes: Any) -> str:
    match = _REASON.search(str(notes or ''))
    return REASONS.get(match.group(1), match.group(1)) if match else ''


def thumbnail(directory: Path | None) -> str:
    """Base64 JPEG of a run's last screenshot, or nothing when this machine cannot shrink it."""
    if directory is None or not directory.is_dir() or not shutil.which('sips'):
        return ''
    screenshots = sorted(directory.glob('*.png'))
    if not screenshots:
        return ''
    with tempfile.TemporaryDirectory() as folder:
        output = Path(folder) / 'thumbnail.jpg'
        subprocess.run(['sips', '-s', 'format', 'jpeg', '-s', 'formatOptions', '55', '-Z', '520', str(screenshots[-1]), '--out', str(output)], capture_output=True, timeout=30)
        return base64.b64encode(output.read_bytes()).decode() if output.is_file() else ''


def _cleaner(secrets: list[str]) -> Callable[[Any], str]:
    def clean(value: Any) -> str:
        text = _SECRET.sub('[removed]', str(value if value is not None else ''))
        for secret in secrets:
            if secret:
                text = text.replace(secret, '[removed]')
        return text
    return clean


def _checks(case: dict[str, Any], run: dict[str, Any], clean: Callable[[Any], str]) -> str:
    trace = run.get('trace') or []
    results = next((entry['checkpoint_results'] for entry in reversed(trace) if isinstance(entry, dict) and entry.get('checkpoint_results')), None)
    rows = results if results else case.get('checkpoints') or []
    def row(item: dict[str, Any]) -> str:
        verdict = html.escape(str(item.get('verdict') or 'not run'))
        scope = html.escape(str(item.get('scope') or '')) + ('' if item.get('required') else ', optional')
        return f'<tr><td><code>{html.escape(clean(item.get("id")))}</code></td><td>{html.escape(clean(item.get("expected")))}</td><td>{scope}</td><td><span class="v v-{verdict}">{verdict}</span></td><td>{html.escape(clean(item.get("confidence") if item.get("confidence") is not None else ""))}</td></tr>'
    return ''.join(row(item) for item in rows)


def _card(entry: dict[str, Any], clean: Callable[[Any], str]) -> str:
    e = lambda value: html.escape(clean(value))
    item, case, saved = entry['item'], entry.get('case') or {}, entry.get('run') or {}
    run = saved.get('run') or {}
    status = status_of(item)
    reason = reason_of(run.get('notes'))
    preconditions = str(case.get('preconditions') or '')
    footer = _FOOTER.search(preconditions)
    source = footer.group(0) if footer else ''
    preconditions = preconditions.replace(source, '').strip()
    source = re.sub(r'; Source: [0-9a-f]+', '', source.replace('[generate-test-cases] ', ''))
    notes = ''.join(f'<div class="note"><strong>Review note, not a Scout verdict.</strong> {e(str(note.get("body") or ""))}</div>' for note in saved.get('notes') or [])
    details = ' · '.join(e(value) for value in (run.get('build'), run.get('device'), run.get('created')) if value)
    image = entry.get('image') or ''
    parts = [
        notes,
        f'<h4>Expected</h4><p>{e(case.get("expected"))}</p>' if case.get('expected') else '',
        f'<h4>Steps</h4><pre>{e(case.get("steps"))}</pre>' if case.get('steps') else '',
        f'<h4>Preconditions</h4><p>{e(preconditions)}</p>' if preconditions else '',
        f'<p class="m">{e(source)}</p>' if source else '',
        f'<h4>Latest run</h4><p class="m">{details}</p>' if details else '',
        f'<p>{e(str(run.get("notes"))[:900])}</p>' if run.get('notes') else '',
        '<p class="m">This run could not be read.</p>' if entry.get('error') else '',
    ]
    picture = f'<img loading="lazy" alt="Final screenshot of the latest run" src="data:image/jpeg;base64,{image}">' if image else ''
    checks = _checks(case, run, clean)
    table = f'<div class="tw"><table><thead><tr><th>Checkpoint</th><th>Expected</th><th>Scope</th><th>Verdict</th><th>Confidence</th></tr></thead><tbody>{checks}</tbody></table></div>' if checks else ''
    title = str(item.get('title') or 'Untitled case')
    css_status = re.sub(r'\W+', '-', status.lower())
    label = f'{status} · {reason}' if reason else status
    search = e(' '.join([title, str(item.get('suite') or ''), label]).lower())
    return f'<details class="case" data-status="{e(status)}" data-text="{search}"><summary><span class="s s-{css_status}">{e(label)}</span><span class="t">{e(title)}</span></summary><div class="body"><div class="grid"><div>{"".join(parts)}</div>{picture}</div>{table}</div></details>'


def summary(entries: list[dict[str, Any]]) -> dict[str, Any]:
    """Counts plus every case that needs attention, in the order someone should read them."""
    counts = Counter(status_of(entry['item']) for entry in entries)
    attention = [{'title': entry['item'].get('title'), 'status': status_of(entry['item']), 'reason': reason_of(((entry.get('run') or {}).get('run') or {}).get('notes'))}
                 for entry in entries if status_of(entry['item']) not in {'Passed', 'Not run'}]
    attention.sort(key=lambda row: (ORDER.get(row['status'], 9), str(row['title'])))
    return {'total_cases': len(entries), 'counts': dict(sorted(counts.items(), key=lambda pair: ORDER.get(pair[0], 9))), 'needs_attention': attention}


def render(title: str, entries: list[dict[str, Any]], secrets: list[str] | None = None, generated: datetime.datetime | None = None) -> str:
    clean = _cleaner(list(secrets or []))
    e = lambda value: html.escape(clean(value))
    counts = Counter(status_of(entry['item']) for entry in entries)
    stats = ''.join(f'<button class="stat" data-f="{e(status)}"><b>{count}</b><span>{e(status)}</span></button>' for status, count in sorted(counts.items(), key=lambda pair: ORDER.get(pair[0], 9)))
    suites: dict[str, list[dict[str, Any]]] = {}
    for entry in entries:
        suites.setdefault(str(entry['item'].get('suite') or 'No suite'), []).append(entry)
    sections = []
    for name, rows in sorted(suites.items(), reverse=True):
        rows = sorted(rows, key=lambda entry: (ORDER.get(status_of(entry['item']), 9), str(entry['item'].get('title'))))
        tally = Counter(status_of(entry['item']) for entry in rows)
        heading = f'{len(rows)} cases · ' + ', '.join(f'{count} {e(status)}' for status, count in tally.most_common())
        sections.append(f'<section><h2>{e(name)} <small>{heading}</small></h2>{"".join(_card(entry, clean) for entry in rows)}</section>')
    stamp = (generated or datetime.datetime.now()).strftime('%Y-%m-%d %H:%M')
    return f'''<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>{e(title)}</title><style>{_CSS}</style></head><body><main><h1>{e(title)}</h1><p class="sub">{len(entries)} cases · generated {stamp}</p><div class="stats">{stats}</div><div class="notice"><strong>Reading this report.</strong> Status is each case's latest saved Scout run. Review notes don't change Scout's verdict. A Blocked case hasn't been tested yet, and a Failed case is a possible bug until someone reviews it. App logs are left out.</div><input id="q" type="search" placeholder="Search cases" aria-label="Search cases">{"".join(sections)}<p id="none" class="m" hidden>No cases match.</p></main><script>{_JS}</script></body></html>'''
