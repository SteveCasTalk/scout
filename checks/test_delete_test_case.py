import io
import json
import unittest
from unittest import mock
from urllib.error import HTTPError

from scout_mobile import mcp_server
from scout_mobile.dashboard_client import DashboardClient

WORKSPACE = '11111111-1111-4111-8111-111111111111'
CASE = '22222222-2222-4222-8222-222222222222'


class _Response(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class DeleteTestCaseClientTest(unittest.TestCase):
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

    def test_sends_owner_scoped_delete_with_expected_revision(self):
        self._respond({'deleted': True, 'id': CASE})
        self.assertEqual(self.client.delete_test_case(WORKSPACE, CASE, 3), {'deleted': True, 'id': CASE})
        request = self.sent[0]
        self.assertEqual(request.get_method(), 'DELETE')
        self.assertEqual(request.full_url, 'http://localhost:5173/api/cases')
        self.assertEqual(request.get_header('Origin'), 'http://localhost:5173')
        self.assertEqual(json.loads(request.data), {'id': CASE, 'workspace_id': WORKSPACE, 'revision': 3})

    def test_revision_conflict_is_reported(self):
        self._respond({'error': 'This test changed elsewhere. Reload the library before deleting it.'}, 409)
        with self.assertRaisesRegex(ValueError, 'changed elsewhere'):
            self.client.delete_test_case(WORKSPACE, CASE, 1)

    def test_invalid_arguments_never_reach_the_dashboard(self):
        self._respond({'deleted': True, 'id': CASE})
        for args in [('not-a-uuid', CASE, 1), (WORKSPACE, 'nope', 1), (WORKSPACE, CASE, 0),
                     (WORKSPACE, CASE, True), (WORKSPACE, CASE, '2')]:
            with self.subTest(args=args), self.assertRaises(ValueError):
                self.client.delete_test_case(*args)
        self.assertEqual(self.sent, [])


class DeleteTestCaseToolTest(unittest.TestCase):
    def test_tool_delegates_to_dashboard_client(self):
        client = mock.Mock()
        client.delete_test_case.return_value = {'deleted': True, 'id': CASE}
        with mock.patch.object(mcp_server, '_library_dashboard', return_value=client):
            self.assertEqual(mcp_server.delete_test_case(WORKSPACE, CASE, 4), {'deleted': True, 'id': CASE})
        client.delete_test_case.assert_called_once_with(WORKSPACE, CASE, 4)

    def test_docstring_marks_deletion_as_permanent_and_user_requested(self):
        doc = mcp_server.delete_test_case.__doc__ or ''
        self.assertIn('PERMANENTLY', doc)
        self.assertIn('explicitly asked', doc)


if __name__ == '__main__':
    unittest.main()
