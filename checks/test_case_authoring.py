import unittest

from scout_mobile.mcp_server import _normalize_case_item


class CaseAuthoringTest(unittest.TestCase):
    def test_package_maps_to_app_id(self):
        item = _normalize_case_item({'request_id': 'r', 'case': {'title': 't', 'package': 'com.example.app'}})
        self.assertEqual(item['case']['app_id'], 'com.example.app')
        self.assertNotIn('package', item['case'])

    def test_existing_app_id_is_kept(self):
        item = _normalize_case_item({'request_id': 'r', 'case': {'app_id': 'com.example.app'}})
        self.assertEqual(item['case']['app_id'], 'com.example.app')

    def test_conflicting_values_are_rejected(self):
        with self.assertRaises(ValueError):
            _normalize_case_item({'request_id': 'r', 'case': {'app_id': 'a.b.c', 'package': 'x.y.z'}})


if __name__ == '__main__':
    unittest.main()
