"""Verify presenter controls without contacting AWS or starting HTTP load."""

from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import Mock, patch

import demo


class DemoControlsTest(unittest.TestCase):
    def setUp(self):
        self.directory = TemporaryDirectory(prefix='library-demo-test-')
        self.addCleanup(self.directory.cleanup)
        self.output = Path(self.directory.name) / 'reports'
        self.args = ['--sections', 'api,grpc', '--base-url', 'http://127.0.0.1:9', '--output-dir', str(self.output)]
        self.console = StringIO()
        self.addCleanup(patch.stopall)
        self.api_suite = patch.object(demo, 'run_api_suite').start()
        self.grpc_suite = patch.object(demo, 'run_grpc_suite').start()
        patch.object(demo, 'show_results').start()
        self.http = patch.object(demo, 'api', side_effect=AssertionError('Unexpected network call')).start()

    def run_demo(self, answers=(), extra=()):
        with patch('builtins.input', side_effect=answers), redirect_stdout(self.console):
            return demo.main(self.args + list(extra))

    def test_each_function_waits_for_its_enter(self):
        def enter(prompt):
            self.assertIn('Press Enter', prompt)
            if self.api_suite.call_count == 0:
                self.grpc_suite.assert_not_called()
            else:
                self.api_suite.assert_called_once_with()
                self.grpc_suite.assert_not_called()
            return ''

        with patch('builtins.input', side_effect=enter) as keyboard, redirect_stdout(self.console):
            self.assertEqual(demo.main(self.args), 0)
        self.assertEqual(keyboard.call_count, 2)
        self.api_suite.assert_called_once_with()
        self.grpc_suite.assert_called_once_with()
        report = json.loads((self.output / 'demo-report.json').read_text())
        self.assertEqual(report['status'], 'PASS')
        self.assertEqual(list(report['sections']), ['api', 'grpc'])

    def test_quitting_cleans_up_and_never_starts_next_function(self):
        def leave_fixtures():
            demo.ACTIVE_LOANS.append('loan-id')
            demo.RESERVATIONS.append('hold-id')
        self.api_suite.side_effect = leave_fixtures
        self.http.side_effect = lambda service, path, method='GET': {'status': 'READY'}
        self.assertEqual(self.run_demo(['', 'q']), 0)
        self.grpc_suite.assert_not_called()
        self.http.assert_any_call('lending', '/loans/loan-id/return', 'POST')
        self.http.assert_any_call('reservation', '/reservations/hold-id', 'DELETE')
        self.assertEqual(demo.REPORT['status'], 'STOPPED')
        self.assertNotIn('grpc', demo.REPORT['sections'])

    def test_eof_stops_before_any_function(self):
        self.assertEqual(self.run_demo([EOFError()]), 0)
        self.api_suite.assert_not_called()
        self.assertEqual(demo.REPORT['status'], 'STOPPED')

    def test_ctrl_c_reports_interruption(self):
        self.assertEqual(self.run_demo([KeyboardInterrupt()]), 130)
        self.api_suite.assert_not_called()
        self.assertEqual(demo.REPORT['status'], 'INTERRUPTED')

    def test_failure_is_recorded_and_next_demo_still_requires_enter(self):
        self.api_suite.side_effect = RuntimeError('Expected test failure')
        self.assertEqual(self.run_demo(['', '']), 1)
        self.grpc_suite.assert_called_once_with()
        self.assertEqual(demo.REPORT['sections']['api']['status'], 'FAIL')
        self.assertEqual(demo.REPORT['sections']['grpc']['status'], 'PASS')
        self.assertEqual(demo.REPORT['status'], 'FAIL')
        self.assertTrue((demo.ARTIFACTS / 'api-failure.txt').is_file())

    def test_ctrl_c_during_a_function_marks_that_step_interrupted(self):
        self.api_suite.side_effect = KeyboardInterrupt()
        self.assertEqual(self.run_demo(['']), 130)
        self.grpc_suite.assert_not_called()
        self.assertEqual(demo.REPORT['sections']['api']['status'], 'INTERRUPTED')
        self.assertEqual(demo.REPORT['status'], 'INTERRUPTED')

    def test_auto_mode_never_reads_keyboard(self):
        with patch('builtins.input', side_effect=AssertionError('Unexpected prompt')) as keyboard, redirect_stdout(self.console):
            self.assertEqual(demo.main(self.args + ['--auto']), 0)
        keyboard.assert_not_called()
        self.api_suite.assert_called_once_with()
        self.grpc_suite.assert_called_once_with()

    def test_list_does_not_run_or_create_reports(self):
        self.assertEqual(self.run_demo([], extra=['--list']), 0)
        self.api_suite.assert_not_called()
        self.assertFalse(self.output.exists())

    def test_dependencies_are_validated_before_creating_reports(self):
        with redirect_stderr(StringIO()), self.assertRaises(SystemExit) as raised:
            demo.main(self.args + ['--sections', 'notifications,api'])
        self.assertEqual(raised.exception.code, 2)
        self.assertFalse(self.output.exists())

    def test_cleanup_failure_cannot_be_reported_as_successful_quit(self):
        self.api_suite.side_effect = lambda: demo.ACTIVE_LOANS.append('loan-id')
        self.http.side_effect = RuntimeError('Cleanup unavailable')
        self.assertEqual(self.run_demo(['', 'q']), 1)
        self.assertEqual(demo.REPORT['status'], 'FAIL')
        self.assertTrue(demo.REPORT['cleanup_warnings'])


if __name__ == '__main__':
    unittest.main()
