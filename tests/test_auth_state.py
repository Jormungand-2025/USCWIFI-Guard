"""Offline regressions: authentication sessions, delayed probes and UI state."""
import queue
import sys
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
import campus_guard as guard


class AuthenticationStateTests(unittest.TestCase):
    def app(self):
        app = guard.App.__new__(guard.App)
        app.lock = threading.RLock()
        app.stop = threading.Event()
        app.events = queue.Queue()
        app.settings = {'paused': False, 'blocked': ''}
        app.status = 'initial'
        app.next_login = 0
        app.next_status = 0
        app.last_internet = 0
        app.probe_running = False
        app.probe_ok = None
        app.network_epoch = 0
        app.auth_state = None
        app.unconfirmed_logins = 0
        app.portal_client = None
        app.last_action = 'campus'
        app.failures = 0
        app.safe_to_submit = lambda *_: True
        return app

    def test_confirmed_login_removes_previous_cooldown(self):
        app = self.app()
        app.next_login = time.monotonic() + 8
        app.record_auth(True)
        self.assertEqual(app.next_login, 0)

    def test_wired_start_already_online_confirms_internet_without_login(self):
        app = self.app()
        app.last_action = 'wired'
        app.network_key = (7, '192.0.2.2', '192.0.2.1')
        app.campus_confirmed = False
        portal = app.portal_client = MagicMock()
        portal.detect_wired_campus.return_value = False
        portal.logged_in.return_value = True
        with patch.object(guard, 'portal_routes_through', return_value=True), \
             patch.object(guard, 'wired_connections', return_value=(app.network_key,)), \
             patch.object(guard.threading, 'Thread'):
            app.maintain_connected(None, {})
        self.assertTrue(app.auth_state)
        with patch.object(guard, 'internet_available', return_value=True) as probe:
            app.probe_internet(app.network_epoch)
        probe.assert_called_once_with('192.0.2.2')
        self.assertEqual(app.status, '校园网已登录，Internet 可用')
        portal.login.assert_not_called()

    def test_repeated_logout_can_login_without_previous_cooldown(self):
        app = self.app()
        portal = MagicMock()
        portal.logged_in.side_effect = [False, True, False, True]
        portal.login.return_value = True
        # Hold only the background probe; no internet or credential requests.
        with patch.object(guard, 'Portal', return_value=portal), patch.object(guard.threading, 'Thread'):
            app.maintain(None, {})
            app.maintain(None, {})
            app.maintain(None, {})
            app.maintain(None, {})
        self.assertEqual(portal.login.call_count, 2)
        self.assertTrue(app.auth_state)
        self.assertEqual(app.next_login, 0)
        self.assertIn('已登录', app.status)

    def test_unconfirmed_login_keeps_submission_cooldown(self):
        app = self.app()
        portal = MagicMock()
        portal.logged_in.return_value = False
        portal.login.return_value = True
        with patch.object(guard, 'Portal', return_value=portal):
            app.maintain(None, {})
            app.maintain(None, {})
        self.assertEqual(portal.login.call_count, 1)

    def test_status_confirmation_uses_the_login_session(self):
        app = self.app()
        portal = MagicMock()
        portal.logged_in.side_effect = [False, True]
        portal.login.return_value = True
        with patch.object(guard, 'Portal', return_value=portal) as factory, patch.object(guard.threading, 'Thread'):
            app.maintain(None, {})
            app.maintain(None, {})
        factory.assert_called_once()
        portal.close.assert_not_called()
        self.assertTrue(app.auth_state)

    def test_success_without_confirmation_stops_after_three_submissions(self):
        app = self.app()
        portal = MagicMock()
        portal.logged_in.return_value = False
        portal.login.return_value = True
        with patch.object(guard, 'Portal', return_value=portal):
            for _ in range(3):
                app.next_login = 0
                app.maintain(None, {})
            app.next_login = 0
            with self.assertRaises(guard.ManualRequired):
                app.maintain(None, {})
        self.assertEqual(portal.login.call_count, 3)

    def test_late_probe_cannot_overwrite_logged_out_session(self):
        app = self.app()
        app.record_auth(True)
        old_epoch = app.network_epoch
        started, finish = threading.Event(), threading.Event()

        def delayed_probe():
            started.set()
            finish.wait(2)
            return True

        with patch.object(guard, 'internet_available', side_effect=delayed_probe):
            worker = threading.Thread(target=app.probe_internet, args=(old_epoch,))
            worker.start()
            self.assertTrue(started.wait(1))
            app.record_auth(False)
            app.update('认证接口暂未确认在线，稍后再次查询')
            finish.set()
            worker.join(2)
        self.assertFalse(worker.is_alive())
        self.assertIsNone(app.probe_ok)
        self.assertIn('暂未确认', app.status)

    def test_pause_during_status_request_discards_response(self):
        app = self.app()
        portal = MagicMock()

        def status():
            app.settings['paused'] = True
            app.network_epoch += 1
            app.update('维护已暂停')
            return True

        portal.logged_in.side_effect = status
        with patch.object(guard, 'Portal', return_value=portal):
            app.maintain(None, {})
        self.assertEqual(app.status, '维护已暂停')
        portal.login.assert_not_called()

    def test_ui_renders_latest_status_instead_of_queued_old_status(self):
        app = self.app()
        app.root, app.tray, app.status_text = MagicMock(), MagicMock(), MagicMock()
        app.update('认证接口暂未确认在线，稍后再次查询')
        app.update('USCWIFI 已登录，Internet 可用')
        app.pump()
        self.assertTrue(all(call.args[0] == app.status for call in app.status_text.set.call_args_list))


if __name__ == '__main__':
    unittest.main()
