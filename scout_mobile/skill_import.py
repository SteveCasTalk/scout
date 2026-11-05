"""Convert the generate-test-cases skill's cases.csv into Scout saved-case definitions.

Pure and dependency-light: no device, dashboard or network access. The skill's CSV is
the input contract; anything Scout cannot honestly run is reported, never saved.
"""
from __future__ import annotations

import csv
import hashlib
import io
import re
import uuid
from typing import Any, Callable

COLUMNS = ('ID', 'Title', 'Story', 'Priority', 'Mode', 'Negative', 'Preconditions', 'Steps', 'Expected result', 'Trace', 'Status')
PRIORITIES = {'P0', 'P1', 'P2'}
HELD_MODES = {
    'MOCK': 'Needs forced server responses: attach a sandbox fixture from a real contract, then author it as a scenario matrix variant.',
    'STORE': 'Needs a tester to confirm the store or system dialog; Scout stops at purchase entry and never confirms checkout.',
    'BE': 'Needs BE/ops to trigger the change first; only the app-side check can be automated.',
    'MANUAL': 'Judged by eye; checkpoints cannot prove visual, media or timing quality.',
    'DEV': 'Logic only a unit test can prove; belongs to the developer.',
}
MODES = {'LIVE', *HELD_MODES}
SOURCE_LABEL = '[generate-test-cases]'
# Bump when conversion output changes, so re-imports update cases whose CSV rows did not change.
CONVERTER_VERSION = '3'
NAMESPACE = uuid.UUID('6f0c3a52-5a0e-4c61-9d3b-2f1e7f6a9b10')

_ID = re.compile(r'^TC-\d+-\d+[a-z]?$')
_TBD = re.compile(r'\bTBD\b|pending contract', re.I)
_QUOTED = re.compile(r'"([^"]+)"|“([^”]+)”|「([^」]+)」')
# A quoted phrase in these clauses is not simply on screen, so it must stay a classification.
_NOT_LITERAL = re.compile(r"\b(no|not|never|without|absent|hidden|removed|disappears?|doesn't|or|if|unless|when|instead|before|until|previously)\b", re.I)
# Stating an absence or an end state only means something once the flow has finished.
_FINAL_ONLY = re.compile(r"\b(no|not|never|without|absent|hidden|removed|disappears?|doesn't|at the end|ends? on|remains? on|stays? on|finally)\b", re.I)
# A clause starting with a pronoun can't be judged without the clause before it.
_NEEDS_PREVIOUS = re.compile(r"^(it|its|they|their|this|that|these|those)\b", re.I)
SPEC_STEPS = 'Steps: from spec, confirm with exploration'
_STEPS_NOTE = re.compile(re.escape(SPEC_STEPS) + r'|Steps: explored in run [A-Za-z0-9_-]+')
UNEXPLORED_NOTE = ' Review first: this imported case\'s steps come from the spec and were not confirmed by exploration, and its setup may not have been checked, so this result does not establish an app bug.'
_SOURCE = re.compile(re.escape(SOURCE_LABEL) + r'.*\bSource: ([0-9a-f]{16})\s*$', re.S)
_LIMITATIONS = (
    (re.compile(r'\b(never|always|throughout|at no point|endless)\b', re.I), 'Claims an invariant over time; final checkpoints cannot prove it, so consider temporal_assertions.'),
    (re.compile(r'\b(analytics|event fires?|tracking)\b', re.I), 'Mentions analytics or backend behaviour, which screen evidence cannot prove.'),
    (re.compile(r'\brotat(e|ion)\b', re.I), 'Needs rotation, which Scout has no execution operation for.'),
)


INSTRUCTIONS = (
    'Output from the generate-test-cases skill (a cases.csv with TC-<ticket>-<NN> IDs) is the standard input for saved '
    'Scout cases. Always convert it with import_generated_test_cases, dry run first; never map it by hand. Report held '
    'and rejected rows to the user. Read get_test_case_template before authoring any other case.'
)
STANDARD = {
    'version': 1,
    'tool': 'import_generated_test_cases',
    'rule': 'Never map this CSV by hand. create_test_case, update_test_case, validate_test_cases and import_test_cases refuse TC-<ticket>-<NN> titles that lack the importer footer.',
    'columns': list(COLUMNS),
    'mapping': {
        'title': '<ID> <Title>, cut to 160 characters', 'goal': 'Title and Expected result, which give the checkpoint classifier context', 'suite': '<Story> <Mode>', 'ticket_key': 'Story, uppercase',
        'comparison_key': 'ID', 'steps': 'Steps, one per line', 'expected': 'Expected result',
        'preconditions': 'Preconditions plus a footer holding ID, Priority, Mode, Negative, Trace and the source hash',
        'checkpoints': 'One required classification per semicolon-separated clause, joined to the clause before it when it starts with a pronoun; final for the last clause and for stated absences or end states, during_run otherwise; plus optional during_run text_present for quoted copy that is stated plainly',
        'starting_conditions': 'Left at defaults, because the opening screen often cannot prove them; confirm prerequisites before running',
    },
    'saved_modes': ['LIVE'],
    'held_modes': HELD_MODES,
    'also_held': 'Rows marked TBD or pending contract.',
    'after_import': 'Explore each case with a bounded prompt run, then call mark_generated_case_explored with that run ID, corrected steps, real starting_conditions and checkpoints. Prefer exact text seen in that run over clauses the classifier must judge, because a final check sees only the last screen. Non-passing runs carry a review note until then.',
}


class Rejected(ValueError):
    """The row cannot be converted as written."""


class Held(ValueError):
    """The row is valid, but Scout should not run it yet."""


def parse_csv(text: str) -> list[dict[str, Any]]:
    reader = csv.DictReader(io.StringIO(text.lstrip('﻿'), newline=''))
    missing = [name for name in COLUMNS if name not in (reader.fieldnames or [])]
    if missing:
        raise ValueError(f'Not a generate-test-cases CSV; missing columns: {", ".join(missing)}.')
    return list(reader)


def split_steps(text: str) -> str:
    """Put `1. … 2. …` on separate lines, only following consecutive numbering."""
    text = text.strip()
    starts, position, number = [], 0, 1
    while match := re.compile(rf'(?:^|(?<=\s)){number}[.)]\s+').search(text, position):
        starts.append(match.start())
        position, number = match.end(), number + 1
    if len(starts) < 2 or starts[0] != 0:
        return text
    return '\n'.join(text[start:end].strip() for start, end in zip(starts, [*starts[1:], len(text)]))


def split_clauses(text: str) -> list[str]:
    """Split an expected result on semicolons that are outside quoted copy."""
    quoted = [match.span() for match in _QUOTED.finditer(text)]
    clauses, start = [], 0
    for index, char in enumerate(text):
        if char in ';；' and not any(left < index < right for left, right in quoted):
            clauses.append(text[start:index])
            start = index + 1
    clauses.append(text[start:])
    return [clause.strip() for clause in clauses if clause.strip()]


def merge_clauses(clauses: list[str]) -> list[str]:
    """Keep together clauses the classifier could not judge alone."""
    merged: list[str] = []
    for clause in clauses:
        if merged and _NEEDS_PREVIOUS.match(clause):
            merged[-1] = f'{merged[-1]}; {clause}'
        else:
            merged.append(clause)
    return merged


def build_checkpoints(expected: str) -> list[dict[str, Any]]:
    checkpoints, literals = [], []
    clauses = merge_clauses(split_clauses(expected))
    for index, clause in enumerate(clauses, 1):
        # Earlier clauses may describe earlier screens; the last one is where the flow must end.
        scope = 'final' if index == len(clauses) or _FINAL_ONLY.search(clause) else 'during_run'
        checkpoints.append({'id': f'expected_{index}', 'expected': clause, 'scope': scope, 'required': True, 'method': 'classification'})
        if not _NOT_LITERAL.search(clause):
            for match in _QUOTED.finditer(clause):
                copy = next(group for group in match.groups() if group).strip()
                # Short single words match unrelated text, because the check is a substring.
                if (len(copy) >= 4 or ' ' in copy) and copy not in literals:
                    literals.append(copy)
    # Copy can be a toast between samples or in another language, so not seeing it cannot fail the run alone.
    checkpoints += [{'id': f'copy_{index}', 'expected': copy, 'scope': 'during_run', 'required': False, 'method': 'text_present'} for index, copy in enumerate(literals, 1)]
    if len(checkpoints) > 12:
        checkpoints = [{'id': 'expected_1', 'expected': expected, 'scope': 'final', 'required': True, 'method': 'classification'}]
    if any(len(item['expected']) > 1000 for item in checkpoints):
        raise Rejected('Expected result is too long for a checkpoint (1000 characters each); split the case.')
    return checkpoints


def source_hash(row: dict[str, Any], package: str) -> str:
    values = [str(row.get(name) or '').strip() for name in COLUMNS if name != 'Status']
    return hashlib.sha256('\0'.join([*values, package, CONVERTER_VERSION]).encode()).hexdigest()[:16]


def convert_row(row: dict[str, Any], platform: str, package: str, project: str) -> dict[str, Any]:
    if row.get(None):
        raise Rejected('Row has more cells than the header; quote any cell containing a comma.')
    values = {name: str(row.get(name) or '').strip() for name in COLUMNS}
    identity, title, story = values['ID'], values['Title'], values['Story'].upper()
    if not _ID.match(identity):
        raise Rejected('ID must look like TC-6819-01 or TC-6819-07a.')
    empty = [name for name in ('Title', 'Story', 'Priority', 'Mode', 'Steps', 'Expected result') if not values[name]]
    if empty:
        raise Rejected(f'Empty: {", ".join(empty)}.')
    if identity.startswith('TC-0000-'):
        raise Rejected('This is the template\'s example row.')
    mode, priority = values['Mode'].upper(), values['Priority'].upper()
    if mode not in MODES or priority not in PRIORITIES:
        raise Rejected(f'Unknown Mode {values["Mode"]!r} or Priority {values["Priority"]!r}.')
    if mode in HELD_MODES:
        raise Held(HELD_MODES[mode])
    if any(_TBD.search(value) for value in values.values()):
        raise Held('Marked TBD or pending contract; there is no settled result to check yet.')
    digest = source_hash(row, package)
    footer = (f'{SOURCE_LABEL} ID: {identity}; Priority: {priority}; Mode: {mode}; Negative: {values["Negative"] or "no"}; '
              f'Trace: {values["Trace"] or "none"}; {SPEC_STEPS}; Source: {digest}')
    preconditions = f'{values["Preconditions"]}\n\n{footer}'.strip()
    steps = split_steps(values['Steps'])
    limits = {'Story': (story, 40), 'Preconditions': (preconditions, 4000), 'Steps': (steps, 8000), 'Expected result': (values['Expected result'], 4000), 'Title': (title, 4000)}
    too_long = [name for name, (value, limit) in limits.items() if len(value) > limit]
    suite = f'{story} {mode}'
    if too_long or len(suite) > 80:
        raise Rejected(f'Too long for Scout: {", ".join(too_long) or "Story"}.')
    full_title = f'{identity} {title}'
    return {
        'tc_id': identity,
        'source_hash': digest,
        'warnings': [message for pattern, message in _LIMITATIONS if pattern.search(values['Expected result'] + ' ' + values['Steps'])],
        'definition': {
            'title': full_title if len(full_title) <= 160 else full_title[:159] + '…',
            'platform': platform, 'project': project, 'suite': suite, 'ticket_key': story, 'app_id': package,
            'comparison_key': identity, 'goal': f'{title}. Expected result: {values["Expected result"]}'[:4000], 'preconditions': preconditions, 'steps': steps,
            'expected': values['Expected result'], 'checkpoints': build_checkpoints(values['Expected result']),
        },
    }


def plan_import(rows: list[dict[str, Any]], platform: str, package: str, project: str) -> dict[str, list[dict[str, Any]]]:
    """Sort rows into ready, held and rejected. Duplicated IDs are rejected on every occurrence."""
    seen: dict[str, int] = {}
    for row in rows:
        identity = str(row.get('ID') or '').strip()
        seen[identity] = seen.get(identity, 0) + 1
    plan: dict[str, list[dict[str, Any]]] = {'ready': [], 'held': [], 'rejected': []}
    for row in rows:
        identity = str(row.get('ID') or '').strip()
        try:
            if seen[identity] > 1:
                raise Rejected('Duplicate ID in this CSV.')
            plan['ready'].append(convert_row(row, platform, package, project))
        except Held as reason:
            plan['held'].append({'tc_id': identity, 'story': str(row.get('Story') or '').strip().upper(), 'mode': str(row.get('Mode') or '').strip().upper(), 'reason': str(reason)})
        except Rejected as reason:
            plan['rejected'].append({'tc_id': identity, 'reason': str(reason)})
    return plan


def tc_id_of(title: Any) -> str | None:
    first = str(title or '').split(' ', 1)[0]
    return first if _ID.match(first) else None


def saved_source(preconditions: Any) -> str | None:
    match = _SOURCE.search(str(preconditions or ''))
    return match.group(1) if match else None


def require_standard(case: dict[str, Any]) -> None:
    """Keep skill cases consistent: a TC-titled case must have come through the importer."""
    identity = tc_id_of(case.get('title'))
    if identity and not saved_source(case.get('preconditions')):
        raise ValueError(f'{identity} looks like generate-test-cases output. Import the CSV with import_generated_test_cases instead of mapping it by hand; updates must keep the {SOURCE_LABEL} footer in preconditions.')


def run_note(status: str, preconditions: Any) -> str:
    """Note for a non-passing run of an imported case nobody has explored yet."""
    return UNEXPLORED_NOTE if status in {'Failed', 'Inconclusive'} and SOURCE_LABEL in str(preconditions or '') and SPEC_STEPS in str(preconditions) else ''


def check_against_run(checkpoints: list[dict[str, Any]], trace: list[dict[str, Any]]) -> None:
    """Refuse exact-text checks the run's screens contradict, so they can't be invented."""
    screens = [str((entry.get('screen') or {}).get('text') or '') for entry in trace if entry.get('screen')]
    if not screens:
        raise ValueError('The exploration run has no observed screens.')
    for item in checkpoints:
        if item['method'] == 'classification':
            continue
        text, final = item['expected'].casefold(), item['scope'] == 'final'
        pool = screens[-1:] if final else screens
        found = any(text in screen.casefold() for screen in pool)
        where = 'its final screen' if final else 'any of its screens'
        if item['method'] == 'text_present' and not found:
            raise ValueError(f'{item["id"]}: "{item["expected"]}" is not on {where} in the exploration run.')
        if item['method'] == 'text_absent' and found and final:
            raise ValueError(f'{item["id"]}: "{item["expected"]}" is on {where} in the exploration run.')


def mark_explored(saved: dict[str, Any], run_id: str, steps: str | None = None, starting_conditions: dict[str, Any] | None = None, checkpoints: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    """Return a saved imported case recorded as explored, with any corrections from that run."""
    preconditions = str(saved.get('preconditions') or '')
    if not saved_source(preconditions) or not _STEPS_NOTE.search(preconditions):
        raise ValueError('This case is not an imported case.')
    fields = ('workspace_id', 'project', 'ticket_key', 'comparison_key', 'app_id', 'title', 'platform', 'suite', 'goal', 'expected', 'assertion_text', 'checkpoints', 'sandbox', 'execution', 'starting_conditions', 'steps')
    definition = {field: saved[field] for field in fields if field in saved}
    definition['preconditions'] = _STEPS_NOTE.sub(f'Steps: explored in run {run_id}', preconditions)
    if checkpoints is not None:
        definition['checkpoints'] = checkpoints
    if steps and steps.strip():
        definition['steps'] = steps.strip()
    if starting_conditions is not None:
        definition['starting_conditions'] = starting_conditions
    return definition


def build_items(workspace_id: str, ready: list[dict[str, Any]], existing: dict[str, dict[str, Any]],
                read_case: Callable[[str], dict[str, Any]]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Return authoring items plus unchanged cases.

    A row the skill has not changed writes nothing, so edits made after exploration
    survive a re-run. A changed row replaces spec-owned fields but keeps the saved
    starting conditions, sandbox and execution, which a CSV cannot express.
    """
    items, unchanged = [], []
    for entry in ready:
        definition = {**entry['definition'], 'workspace_id': workspace_id}
        summary = existing.get(entry['tc_id'])
        item: dict[str, Any] = {'case': definition}
        if summary:
            saved = read_case(summary['id'])
            if saved_source(saved.get('preconditions')) == entry['source_hash']:
                unchanged.append({'tc_id': entry['tc_id'], 'id': summary['id'], 'revision': saved.get('revision')})
                continue
            for field in ('starting_conditions', 'sandbox', 'execution'):
                if saved.get(field) is not None:
                    definition[field] = saved[field]
            item.update(id=summary['id'], expected_revision=saved['revision'])
        key = '|'.join([workspace_id, definition['platform'], definition['project'], entry['tc_id'], entry['source_hash'], str(item.get('id', '')), str(item.get('expected_revision', ''))])
        items.append({**item, 'request_id': str(uuid.uuid5(NAMESPACE, key))})
    return items, unchanged


def batches(items: list[dict[str, Any]], max_items: int = 100, max_chars: int = 900_000) -> list[list[dict[str, Any]]]:
    """Stay inside the authoring limits of 100 items and 1 MB per request."""
    groups: list[list[dict[str, Any]]] = []
    size = 0
    for item in items:
        length = len(str(item).encode())
        if not groups or len(groups[-1]) >= max_items or size + length > max_chars:
            groups.append([])
            size = 0
        groups[-1].append(item)
        size += length
    return groups
