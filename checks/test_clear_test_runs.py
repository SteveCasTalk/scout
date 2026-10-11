import io
import json
import unittest
from unittest import mock
from urllib.error import HTTPError

from scout_mobile import mcp_server
from scout_mobile.dashboard_client import DashboardClient

WORKSPACE = '11111111-1111-4111-8111-111111111111'
CASE = '22222222-2222-4222-8222-222222222222'
CLEARED = {'deleted_runs': 3, 'deleted_evidence': 2, 'deleted_batches': 1}


class _Response(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class ClearRunsClientTest(unittest.TestCase):
    def setUp(self):
        self.client = DashboardClient('http://localhost:5173')
        self.sent = []

    def _respond(self, body, status=200):
        def open_(request, timeout=None):
            self.sent.append(request)
            if status != 200:
                raise HTTPError(request.full_url, status, 'error', {}, io.BytesIO(json.dumps(body).encode()))
            return _Response(json.dumps(body).encode())
        self.client.opener = mock.Mock(open=mock.Mock(side_effect=open_))

    def test_workspace_clear_omits_case_id(self):
        self._respond(CLEARED)
        self.assertEqual(self.client.clear_runs(WORKSPACE), CLEARED)
        request = self.sent[0]
        self.assertEqual(request.get_method(), 'DELETE')
        self.assertEqual(request.full_url, 'http://localhost:5173/api/runs')
        self.assertEqual(request.get_header('Origin'), 'http://localhost:5173')
        self.assertEqual(json.loads(request.data), {'workspace_id': WORKSPACE})

    def test_case_clear_sends_case_id(self):
        self._respond(CLEARED)
        self.client.clear_runs(WORKSPACE, CASE)
        self.assertEqual(json.loads(self.sent[0].data), {'workspace_id': WORKSPACE, 'case_id': CASE})

    def test_not_found_is_reported(self):
        self._respond({'error': 'Test case not found.'}, 404)
        with self.assertRaisesRegex(ValueError, 'not found'):
            self.client.clear_runs(WORKSPACE, CASE)

    def test_invalid_arguments_never_reach_the_dashboard(self):
        self._respond(CLEARED)
        for args in [('not-a-uuid',), (WORKSPACE, 'nope'), (WORKSPACE, '')]:
            with self.subTest(args=args), self.assertRaises(ValueError):
                self.client.clear_runs(*args)
        self.assertEqual(self.sent, [])


class ClearTestRunsToolTest(unittest.TestCase):
    def test_tool_delegates_to_dashboard_client(self):
        client = mock.Mock()
        client.clear_runs.return_value = CLEARED
        with mock.patch.object(mcp_server, '_library_dashboard', return_value=client):
            self.assertEqual(mcp_server.clear_test_runs(WORKSPACE), CLEARED)
            self.assertEqual(mcp_server.clear_test_runs(WORKSPACE, CASE), CLEARED)
        self.assertEqual(client.clear_runs.call_args_list, [mock.call(WORKSPACE, None), mock.call(WORKSPACE, CASE)])

    def test_docstring_marks_clear_as_permanent_and_user_requested(self):
        doc = mcp_server.clear_test_runs.__doc__ or ''
        self.assertIn('PERMANENTLY', doc)
        self.assertIn('explicitly asked', doc)
        self.assertIn('Keeps the test cases', doc)


if __name__ == '__main__':
    unittest.main()
