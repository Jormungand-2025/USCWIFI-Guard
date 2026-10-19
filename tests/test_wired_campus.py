import sys
import threading
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
import campus_guard as g


class WiredCampusTests(unittest.TestCase):
    def app(self):
        a = g.App.__new__(g.App)
        a.lock = threading.RLock()
        a.wired_key = (7, '192.0.2.2', '192.0.2.1')
        a.wired_confirmed = False
        a.last_action = 'wired'
        a.credentials = {'username': 'test', 'password': 'test'}
        a.portal_client = MagicMock()
        a.permitted = lambda: True
        a.update = MagicMock()
        a.maintain = MagicMock()
        return a

    def test_redirect_recognition_never_submits_credentials(self):
        p = g.Portal()
        try:
            for target, expected in [(g.PORTAL+'?nasId=2', True),
                                     ('http://210.43.112.9.evil.test/tpl/default/login_account.html', False),
                                     ('http://example.org/', False), (g.BASE+'/', False)]:
                p.s.get = MagicMock(return_value=MagicMock(is_redirect=True,
                    url='http://www.msftconnecttest.com/connecttest.txt', headers={'Location':target}))
                self.assertEqual(p.detect_wired_campus(), expected)
                self.assertFalse(p.s.get.call_args.kwargs['allow_redirects'])
            p.s.get = MagicMock(return_value=MagicMock(is_redirect=False))
            self.assertFalse(p.detect_wired_campus())
        finally:
            p.close()

    def test_ordinary_wired_network_never_authenticates(self):
        a = self.app()
        a.portal_client.detect_wired_campus.return_value = False
        with patch.object(g, 'portal_routes_through', return_value=True):
            a.maintain_wired(a.credentials)
        a.maintain.assert_not_called()
        self.assertFalse(a.wired_confirmed)

    def test_recognized_wired_campus_authenticates_without_wlan(self):
        a = self.app()
        with patch.object(g, 'portal_routes_through', return_value=True), \
             patch.object(g, 'wired_connections', return_value=(a.wired_key,)):
            a.maintain_wired(a.credentials)
            self.assertTrue(a.safe_to_submit(None, a.credentials))
        a.maintain.assert_called_once_with(None, a.credentials)

    def test_network_switch_after_discovery_prevents_login(self):
        a = self.app()
        with patch.object(g, 'portal_routes_through', return_value=True), \
             patch.object(g, 'wired_connections', return_value=()):
            a.maintain_wired(a.credentials)
        a.maintain.assert_not_called()

    def test_route_through_wifi_or_vpn_prevents_authentication(self):
        a = self.app()
        with patch.object(g, 'portal_routes_through', return_value=False):
            a.maintain_wired(a.credentials)
        a.portal_client.detect_wired_campus.assert_not_called()
        a.maintain.assert_not_called()

    def test_submission_rechecks_connection_route_and_pause(self):
        a = self.app()
        a.wired_confirmed = True
        with patch.object(g, 'wired_connections', return_value=(a.wired_key,)), \
             patch.object(g, 'portal_routes_through', return_value=False):
            self.assertFalse(a.safe_to_submit(None, a.credentials))
        with patch.object(g, 'wired_connections', return_value=()):
            self.assertFalse(a.safe_to_submit(None, a.credentials))
        a.permitted = lambda: False
        self.assertFalse(a.safe_to_submit(None, a.credentials))

    def test_requests_are_bound_to_ethernet_address(self):
        p = g.Portal('192.0.2.2')
        try:
            for scheme in ('http://', 'https://'):
                self.assertEqual(p.s.get_adapter(scheme).poolmanager.connection_pool_kw['source_address'],
                                 ('192.0.2.2', 0))
        finally:
            p.close()

    def test_multiple_wired_networks_wait_without_submitting(self):
        a = self.app()
        a.wired_key = None
        a.maintain_wired(a.credentials)
        a.maintain.assert_not_called()


if __name__ == '__main__':
    unittest.main()
