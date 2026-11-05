"""Synthetic checks for the HTML project summary. No device or dashboard is involved."""
import unittest

from scout_mobile.project_report import reason_of, render, summary


def entry(status='Passed', title='TC-1 Case', **run):
    return {'item': {'title': title, 'suite': 'CA-1 LIVE', 'latest_run_status': status}, 'case': {'expected': 'It works', 'steps': 'Tap', 'checkpoints': [{'id': 'a', 'expected': 'Save', 'scope': 'final', 'required': True}]}, 'run': {'run': run, 'notes': run.pop('review_notes', [])} if run or status != 'Not run' else None}


class ReportTests(unittest.TestCase):
    def test_counts_and_attention_list_are_ordered_by_what_to_read_first(self):
        result = summary([entry('Passed'), entry('Inconclusive', 'B'), entry('Failed', 'C'), entry('Blocked', 'A', notes='x Reason code: prerequisite_missing.'), entry('Not run', 'D')])
        self.assertEqual(result['counts'], {'Failed': 1, 'Blocked': 1, 'Inconclusive': 1, 'Not run': 1, 'Passed': 1})
        self.assertEqual([row['status'] for row in result['needs_attention']], ['Failed', 'Blocked', 'Inconclusive'])
        self.assertEqual(result['needs_attention'][1]['reason'], 'test data missing')

    def test_unknown_reason_codes_are_shown_as_they_are(self):
        self.assertEqual(reason_of('Reason code: new_code.'), 'new_code')
        self.assertEqual(reason_of('nothing'), '')

    def test_page_shows_status_reason_and_cases_without_a_run(self):
        page = render('Project report', [entry('Blocked', 'A', notes='Reason code: account_mismatch.'), entry('Not run', 'B')])
        self.assertIn('Blocked · wrong account signed in', page)
        self.assertIn('not run', page)
        self.assertIn('Project report', page)

    def test_app_text_is_escaped(self):
        page = render('Report', [entry('Failed', '<script>alert(1)</script>', notes='<img src=x onerror=alert(1)>')])
        self.assertNotIn('<script>alert(1)', page)
        self.assertNotIn('<img src=x', page)

    def test_credentials_and_tokens_are_removed(self):
        token = 'eyJabcdefghijkl.mnopqrstuvwx.yz123'
        page = render('Report', [entry('Failed', 'Case', notes=f'password=hunter2 {token} tester@example.com')], ['tester@example.com'])
        for secret in ('hunter2', token, 'tester@example.com'):
            self.assertNotIn(secret, page)

    def test_review_notes_are_labelled_and_verdicts_stay(self):
        page = render('Report', [entry('Failed', 'Case', review_notes=[{'body': 'Expected on this account.'}])])
        self.assertIn('Review note, not a Scout verdict.', page)
        self.assertIn('data-status="Failed"', page)

    def test_app_logs_are_never_included(self):
        self.assertNotIn('SECRET-LOG', render('Report', [entry('Passed', 'Case', app_logs='SECRET-LOG')]))


if __name__ == '__main__':
    unittest.main()
