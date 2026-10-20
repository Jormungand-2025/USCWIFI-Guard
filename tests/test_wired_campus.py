"""API recognition for both Ethernet and Wi-Fi; no live credentials or requests."""
import contextlib
import json
import unittest
from unittest.mock import MagicMock, patch
import test_auth_state
import campus_guard as g


class ConnectedCampusTests(unittest.TestCase):
    def app(self, kind):
        app = test_auth_state.AuthenticationStateTests().app()
        app.last_action = kind
        app.network_key = (7, '192.0.2.2', '192.0.2.1')
        app.network_wifi = ((1, 'any-network-name'),)
        app.campus_confirmed = False
        app.credentials = {'username': 'test', 'password': 'test'}
        app.safe_to_submit = g.App.safe_to_submit.__get__(app)
        app.portal_client = g.Portal(app.network_key[1])
        app.portal_client.login = MagicMock(side_effect=lambda credentials, guard: guard())
        wlan = MagicMock()
        wlan.snapshot.return_value = list(app.network_wifi)
        return app, wlan

    def context(self, app):
        stack = contextlib.ExitStack()
        stack.enter_context(patch.object(g, 'wired_connections', return_value=(app.network_key,) if app.last_action == 'wired' else ()))
        stack.enter_context(patch.object(g, 'wireless_connections', return_value=(app.network_key,)))
        stack.enter_context(patch.object(g, 'portal_routes_through', return_value=True))
        stack.enter_context(patch.object(g.threading, 'Thread'))
        stack.callback(app.portal_client.close)
        return stack

    def response(self, payload, code=200):
        response = g.requests.Response()
        response.status_code = code
        response._content = json.dumps(payload).encode()
        return response

    def test_online_and_offline_are_campus_for_both_connection_types(self):
        for kind in ('wired', 'wireless'):
            for code in (0, 1):
                with self.subTest(kind=kind, code=code):
                    app, wlan = self.app(kind)
                    app.portal_client.s.request = MagicMock(return_value=self.response({'code': code, 'msg': 'online' if code == 0 else 'offline'}))
                    with self.context(app):
                        app.maintain_connected(wlan, app.credentials)
                    self.assertTrue(app.campus_confirmed)
                    self.assertEqual(app.auth_state, code == 0)
                    self.assertEqual(app.portal_client.login.call_count, int(code == 1))
                    request = app.portal_client.s.request
                    self.assertEqual(request.call_args.args, ('GET', g.BASE + '/api/account/status'))
                    self.assertFalse(request.call_args.kwargs['allow_redirects'])
                    self.assertIsNone(request.call_args.kwargs['data'])

    def test_unreachable_invalid_or_redirected_api_never_logs_in(self):
        cases = [g.requests.Timeout(), self.response({}, 503), self.response({}, 302),
                 self.response([]), self.response({'code': 2}), self.response({'code': True}),
                 self.response({'code': '1'}), self.response({'message': 'hello'})]
        html = self.response({}); html._content = b'<html>login</html>'; cases.append(html)
        for kind in ('wired', 'wireless'):
            for result in cases:
                with self.subTest(kind=kind, result=type(result).__name__):
                    app, wlan = self.app(kind)
                    app.portal_client.s.request = MagicMock()
                    if isinstance(result, Exception):
                        app.portal_client.s.request.side_effect = result
                    else:
                        app.portal_client.s.request.return_value = result
                    with self.context(app):
                        app.maintain_connected(wlan, app.credentials)
                    self.assertFalse(app.campus_confirmed)
                    app.portal_client.login.assert_not_called()
                    self.assertIn('无法确认校园网', app.status)

    def test_route_change_during_status_discards_result(self):
        for kind in ('wired', 'wireless'):
            app, wlan = self.app(kind)
            app.portal_client.s.request = MagicMock(return_value=self.response({'code': 1}))
            with self.context(app), patch.object(g, 'portal_routes_through', side_effect=[True, False]):
                app.maintain_connected(wlan, app.credentials)
            self.assertFalse(app.campus_confirmed)
            app.portal_client.login.assert_not_called()

    def test_wifi_switch_before_submission_blocks_password(self):
        app, wlan = self.app('wireless')
        app.campus_confirmed = True
        with self.context(app):
            self.assertTrue(app.safe_to_submit(wlan, app.credentials))
            wlan.snapshot.return_value = [(1, 'changed-network')]
            self.assertFalse(app.safe_to_submit(wlan, app.credentials))

    def test_failed_api_invalidates_previous_online_probe(self):
        app, wlan = self.app('wired')
        app.record_auth(True)
        old_epoch = app.network_epoch
        app.campus_confirmed = True
        app.portal_client.s.request = MagicMock(side_effect=g.requests.Timeout())
        with self.context(app), patch.object(g, 'internet_available', return_value=True):
            app.maintain_connected(wlan, app.credentials)
            app.probe_internet(old_epoch)
        self.assertFalse(app.campus_confirmed)
        self.assertIsNone(app.probe_ok)
        self.assertIn('无法确认校园网', app.status)

    def test_multiple_or_changed_connections_cannot_submit(self):
        for kind in ('wired', 'wireless'):
            app, wlan = self.app(kind)
            app.campus_confirmed = True
            with self.context(app):
                app.network_key = None
                app.maintain_connected(wlan, app.credentials)
                self.assertFalse(app.safe_to_submit(wlan, app.credentials))
            app.portal_client.login.assert_not_called()

    def test_requests_are_bound_to_selected_adapter(self):
        portal = g.Portal('192.0.2.2')
        try:
            for scheme in ('http://', 'https://'):
                self.assertEqual(portal.s.get_adapter(scheme).poolmanager.connection_pool_kw['source_address'], ('192.0.2.2', 0))
        finally:
            portal.close()


if __name__ == '__main__':
    unittest.main()
