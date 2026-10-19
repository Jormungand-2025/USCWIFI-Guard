"""Match the school's actual JavaScript request fields and session ordering."""
import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
import campus_guard as guard


class PortalContextTests(unittest.TestCase):
    def discover(self, url):
        portal = guard.Portal()
        response = MagicMock()
        response.url = url
        portal.s.get = MagicMock(return_value=response)
        return portal, portal.discover()

    def test_ip_query_does_not_become_explicit_authentication_target(self):
        portal, fields = self.discover(guard.PORTAL + '?nasId=1&ip=10.0.0.5')
        try:
            self.assertEqual(fields, {'nasId': '1', 'isp': 'local'})
            self.assertEqual(portal.s.headers['Referer'], portal.page_url)
        finally:
            portal.close()

    def test_explicit_gateway_parameters_match_web_form(self):
        portal, fields = self.discover(guard.PORTAL + '?nasId=2&wlanuserip=10.0.0.5&switchip=10.0.0.1&mac=aa:bb:cc:dd:ee:ff')
        try:
            self.assertEqual(fields['userIpv4'], '10.0.0.5')
            self.assertEqual(fields['nasId'], '2')
            self.assertEqual(fields['userMac'], 'aa:bb:cc:dd:ee:ff')
        finally:
            portal.close()

    def test_page_is_initialized_before_csrf_and_credential_submission(self):
        portal = guard.Portal()
        order = []
        portal.discover = lambda: order.append('page') or {'nasId': '1', 'isp': 'local'}

        def call(path, data=None):
            order.append(path)
            return {'csrf_token': 'test'} if path == 'csrf-token' else {'code': 0}

        portal.call = call
        try:
            self.assertTrue(portal.login({'username': 'test', 'password': 'test'}, lambda: True))
            self.assertEqual(order, ['page', 'csrf-token', 'account/check', 'account/login'])
        finally:
            portal.close()

    def test_diagnostics_do_not_echo_identity_or_messages(self):
        result = {'code': 0, 'msg': '用户 test-user 的密码不正确', 'online': {'Username': 'test-user'},
                  'token': 'private-token', 'authCode': 'err:password', 'dialCode': 'ok:dialup'}
        summary = str(guard.response_summary(result))
        self.assertNotIn('test-user', summary)
        self.assertNotIn('private-token', summary)
        self.assertIn('password', summary)


if __name__ == '__main__':
    unittest.main()
