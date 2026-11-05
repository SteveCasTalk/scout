"""generate-test-cases CSV conversion. Synthetic inputs only; no device or dashboard is used."""
import unittest

from scout_mobile import skill_import as si
from scout_mobile.mcp_server import _normalize_case_item, get_test_case_template, mcp

HEADER = ','.join(si.COLUMNS)


def row(**overrides):
    values = {'ID': 'TC-6819-01', 'Title': 'Member opens My plans', 'Story': 'ava-6819', 'Priority': 'P0', 'Mode': 'LIVE', 'Negative': 'no',
              'Preconditions': 'Member with one active plan', 'Steps': '1. Open the Buddies tab 2. Tap the My plans chip',
              'Expected result': 'My plans lists the plan; no error message at the end', 'Trace': 'AVA-6819 AC1', 'Status': 'Not run'}
    return {**values, **overrides}


def convert(**overrides):
    return si.convert_row(row(**overrides), 'Android', 'com.example.uat', 'Twomi')


class ParseTest(unittest.TestCase):
    def test_shipped_template_header_is_accepted(self):
        rows = si.parse_csv('﻿' + HEADER + '\nTC-1-01,T,S,P0,LIVE,no,"a, b",1. x,y,z,Not run\n')
        self.assertEqual(rows[0]['Preconditions'], 'a, b')

    def test_other_csv_is_refused(self):
        with self.assertRaisesRegex(ValueError, 'missing columns'):
            si.parse_csv('id,title\n1,x\n')

    def test_unquoted_comma_is_rejected_not_shifted(self):
        rows = si.parse_csv(HEADER + '\nTC-1-01,T,S,P0,LIVE,no,a,b,1. x,y,z,Not run\n')
        plan = si.plan_import(rows, 'Android', 'com.example.uat', 'Twomi')
        self.assertEqual(plan['ready'], [])
        self.assertIn('more cells', plan['rejected'][0]['reason'])


class ConvertTest(unittest.TestCase):
    def test_maps_to_fields_scout_requires(self):
        case = convert()['definition']
        self.assertEqual(case['title'], 'TC-6819-01 Member opens My plans')
        self.assertEqual((case['ticket_key'], case['suite'], case['app_id'], case['comparison_key']), ('AVA-6819', 'AVA-6819 LIVE', 'com.example.uat', 'TC-6819-01'))
        self.assertEqual(case['steps'], '1. Open the Buddies tab\n2. Tap the My plans chip')
        for fact in ('Priority: P0', 'Mode: LIVE', 'Trace: AVA-6819 AC1', 'Member with one active plan'):
            self.assertIn(fact, case['preconditions'])

    def test_steps_split_only_on_consecutive_numbers(self):
        self.assertEqual(si.split_steps('1. Open version 3. Tap'), '1. Open version 3. Tap')
        self.assertEqual(si.split_steps('Open it'), 'Open it')

    def test_long_title_keeps_id(self):
        title = convert(Title='x' * 400)['definition']['title']
        self.assertEqual(len(title), 160)
        self.assertEqual(si.tc_id_of(title), 'TC-6819-01')

    def test_every_clause_is_required_and_earlier_ones_may_pass_during_run(self):
        checkpoints = convert()['definition']['checkpoints']
        self.assertEqual([(item['expected'], item['scope']) for item in checkpoints], [('My plans lists the plan', 'during_run'), ('no error message at the end', 'final')])
        self.assertTrue(all(item['required'] and item['method'] == 'classification' for item in checkpoints))

    def test_absence_and_end_states_stay_final(self):
        scopes = [item['scope'] for item in si.build_checkpoints('Toast appears; no spinner remains; ends on My plans; list is shown')]
        self.assertEqual(scopes, ['during_run', 'final', 'final', 'final'])

    def test_single_clause_is_final(self):
        self.assertEqual(si.build_checkpoints('My plans lists the plan')[0]['scope'], 'final')

    def test_login_state_needs_an_explicit_statement(self):
        for text, state in (('Member with one plan', 'any'), ('Signed-in member', 'signed_in'), ('Logged in', 'signed_in'), ('Guest user', 'signed_out'), ('Not signed in', 'signed_out'), ('Guest, then signed in', 'any')):
            self.assertEqual(si.login_state(text), state, text)
        self.assertEqual(convert(Preconditions='Signed in member')['definition']['starting_conditions'], {'login_state': 'signed_in'})

    def test_unexplored_note_only_on_unexplored_non_passing_runs(self):
        footer = convert()['definition']['preconditions']
        self.assertTrue(si.run_note('Failed', footer))
        self.assertTrue(si.run_note('Inconclusive', footer))
        self.assertEqual(si.run_note('Passed', footer), '')
        self.assertEqual(si.run_note('Blocked', footer), '')
        self.assertEqual(si.run_note('Failed', 'Ordinary case'), '')

    def test_mark_explored_clears_note_and_applies_corrections(self):
        saved = {**convert()['definition'], 'id': 'case-1', 'revision': 2, 'updated': 'x', 'workspace_id': 'w'}
        marked = si.mark_explored(saved, 'run-1', 'Tap Plans', {'login_state': 'signed_in'})
        self.assertEqual(si.run_note('Failed', marked['preconditions']), '')
        self.assertIn('explored in run run-1', marked['preconditions'])
        self.assertEqual(si.saved_source(marked['preconditions']), si.saved_source(saved['preconditions']))
        self.assertEqual((marked['steps'], marked['starting_conditions']), ('Tap Plans', {'login_state': 'signed_in'}))
        self.assertNotIn('revision', marked)
        with self.assertRaises(ValueError):
            si.mark_explored(marked, 'run-2')

    def test_quoted_copy_becomes_literal_check(self):
        literal = [item for item in si.build_checkpoints('Plan screen shows "Cancel plan"') if item['method'] == 'text_present']
        self.assertEqual([item['expected'] for item in literal], ['Cancel plan'])
        self.assertEqual((literal[0]['scope'], literal[0]['required']), ('during_run', False))

    def test_quoted_copy_is_not_required_when_negated_or_alternative(self):
        for expected in ('No "Cancel plan" button', 'Shows "Cancel plan" or "End plan"', 'Shows "Cancel plan" if active'):
            self.assertEqual([item['method'] for item in si.build_checkpoints(expected)], ['classification'])

    def test_short_generic_copy_is_not_a_substring_check(self):
        self.assertEqual([item['method'] for item in si.build_checkpoints('Dialog shows "OK"')], ['classification'])

    def test_semicolon_inside_quotes_does_not_split(self):
        self.assertEqual(si.split_clauses('Shows "a; b"; no error'), ['Shows "a; b"', 'no error'])

    def test_too_many_checkpoints_collapse_to_one(self):
        checkpoints = si.build_checkpoints(';'.join(f'clause {index}' for index in range(13)))
        self.assertEqual(len(checkpoints), 1)

    def test_oversized_clause_is_rejected(self):
        with self.assertRaises(si.Rejected):
            si.build_checkpoints('x' * 1001)

    def test_limitations_are_warned(self):
        self.assertTrue(convert(**{'Expected result': 'The error never appears'})['warnings'])
        self.assertEqual(convert()['warnings'], [])


class RoutingTest(unittest.TestCase):
    def plan(self, *rows):
        return si.plan_import(list(rows), 'Android', 'com.example.uat', 'Twomi')

    def test_only_live_is_ready(self):
        for mode in si.HELD_MODES:
            plan = self.plan(row(Mode=mode))
            self.assertEqual((len(plan['ready']), plan['held'][0]['mode']), (0, mode))
        self.assertEqual(len(self.plan(row())['ready']), 1)

    def test_tbd_and_pending_contract_are_held(self):
        for overrides in ({'Expected result': 'Expected: TBD — needs PO/dev confirmation'}, {'Trace': 'AC1 pending contract'}):
            self.assertEqual(len(self.plan(row(**overrides))['held']), 1)

    def test_bad_rows_are_rejected(self):
        for overrides in ({'ID': 'CASE-1'}, {'ID': 'TC-0000-01'}, {'Mode': 'AUTO'}, {'Priority': 'High'}, {'Steps': ''}, {'Expected result': ' '}):
            self.assertEqual(len(self.plan(row(**overrides))['rejected']), 1, overrides)

    def test_duplicate_ids_are_rejected_both_times(self):
        self.assertEqual(len(self.plan(row(), row())['rejected']), 2)


class StandardTest(unittest.TestCase):
    def test_discovery_publishes_the_standard(self):
        template = get_test_case_template()['generated_cases']
        self.assertEqual(template['tool'], 'import_generated_test_cases')
        self.assertEqual(template['columns'], list(si.COLUMNS))
        self.assertIn('import_generated_test_cases', mcp.instructions)
        self.assertIn('import_generated_test_cases', {tool.name for tool in mcp._tool_manager.list_tools()})

    def test_hand_mapped_skill_case_is_refused(self):
        with self.assertRaisesRegex(ValueError, 'import_generated_test_cases'):
            _normalize_case_item({'request_id': 'r', 'case': {'title': 'TC-6819-01 Member opens My plans', 'preconditions': 'Member'}})

    def test_imported_case_and_its_later_edits_pass(self):
        case = convert()['definition']
        _normalize_case_item({'request_id': 'r', 'case': case})
        _normalize_case_item({'request_id': 'r', 'case': {**case, 'steps': 'edited after exploration'}})

    def test_other_titles_are_unaffected(self):
        for title in ('Login reaches account settings', 'TC review of plans', 'TC-login smoke'):
            _normalize_case_item({'request_id': 'r', 'case': {'title': title, 'preconditions': ''}})


class ItemsTest(unittest.TestCase):
    workspace = '0a5fd19c-032d-42bd-952a-dad99d7107dd'

    def test_new_case_has_stable_request_id(self):
        first, _ = si.build_items(self.workspace, [convert()], {}, None)
        second, _ = si.build_items(self.workspace, [convert()], {}, None)
        self.assertEqual(first[0]['request_id'], second[0]['request_id'])
        self.assertNotIn('id', first[0])
        self.assertEqual(first[0]['case']['workspace_id'], self.workspace)

    def test_changed_row_gets_new_request_id(self):
        first, _ = si.build_items(self.workspace, [convert()], {}, None)
        second, _ = si.build_items(self.workspace, [convert(Title='Changed')], {}, None)
        self.assertNotEqual(first[0]['request_id'], second[0]['request_id'])

    def test_unchanged_row_writes_nothing_and_keeps_edits(self):
        entry = convert()
        saved = {'revision': 4, 'steps': 'edited after exploration', 'preconditions': entry['definition']['preconditions']}
        items, unchanged = si.build_items(self.workspace, [entry], {'TC-6819-01': {'id': 'case-1'}}, lambda _: saved)
        self.assertEqual(items, [])
        self.assertEqual(unchanged[0]['id'], 'case-1')

    def test_changed_row_updates_and_keeps_what_csv_cannot_express(self):
        saved = {'revision': 4, 'preconditions': convert()['definition']['preconditions'], 'starting_conditions': {'login_state': 'signed_in'}, 'sandbox': None, 'execution': {'schema_version': 2}}
        items, _ = si.build_items(self.workspace, [convert(Title='Changed')], {'TC-6819-01': {'id': 'case-1'}}, lambda _: saved)
        self.assertEqual((items[0]['id'], items[0]['expected_revision']), ('case-1', 4))
        self.assertEqual(items[0]['case']['starting_conditions'], {'login_state': 'signed_in'})
        self.assertEqual(items[0]['case']['execution'], {'schema_version': 2})
        self.assertNotIn('sandbox', items[0]['case'])

    def test_batches_respect_item_and_size_limits(self):
        self.assertEqual([len(group) for group in si.batches([{'a': 1}] * 101)], [100, 1])
        self.assertEqual(len(si.batches([{'a': 'x' * 600}] * 2, max_chars=1000)), 2)
        self.assertEqual(si.batches([]), [])


if __name__ == '__main__':
    unittest.main()
