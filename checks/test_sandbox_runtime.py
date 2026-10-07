import socket
import threading
import time
import unittest
from pathlib import Path

from scout_mobile.config import ROOT
from scout_mobile.dashboard_runtime import _foreign_bridge_root
from scout_mobile.sandbox import wait_for_port_release


class BridgeIdentityTest(unittest.TestCase):
    def test_same_checkout_is_not_foreign(self):
        self.assertIsNone(_foreign_bridge_root({'status': 'ready', 'root': str(ROOT)}))

    def test_other_checkout_is_named(self):
        self.assertEqual(_foreign_bridge_root({'status': 'ready', 'root': '/tmp/other-scout'}), '/tmp/other-scout')

    def test_bridge_without_root_is_treated_as_foreign(self):
        self.assertEqual(_foreign_bridge_root({'status': 'ready'}), 'an older Scout checkout')


class PortReleaseTest(unittest.TestCase):
    def _held_port(self):
        holder = socket.socket()
        holder.bind(('127.0.0.1', 0))
        holder.listen()
        return holder, holder.getsockname()[1]

    def test_waits_until_previous_listener_releases(self):
        holder, port = self._held_port()
        threading.Timer(1.0, holder.close).start()
        started = time.monotonic()
        wait_for_port_release('127.0.0.1', port, timeout=5)
        self.assertGreaterEqual(time.monotonic() - started, 0.9)

    def test_time_wait_connections_do_not_block(self):
        listener, port = self._held_port()
        client = socket.create_connection(('127.0.0.1', port))
        accepted, _ = listener.accept()
        accepted.close()  # server side closes first and enters TIME_WAIT
        client.close()
        listener.close()
        wait_for_port_release('127.0.0.1', port, timeout=1)

    def test_reports_a_port_that_stays_busy(self):
        holder, port = self._held_port()
        try:
            with self.assertRaisesRegex(ValueError, f'port {port} is still in use'):
                wait_for_port_release('127.0.0.1', port, timeout=1)
        finally:
            holder.close()


if __name__ == '__main__':
    unittest.main()
