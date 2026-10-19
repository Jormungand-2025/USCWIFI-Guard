"""USCWIFI maintenance for Windows 10. No credentials in source or logs."""
import base64
import ctypes as C
from ctypes import wintypes as W
import json
import logging
from logging.handlers import RotatingFileHandler
import os
from pathlib import Path
import queue
import subprocess
import sys
import threading
import time
import tkinter as tk
from tkinter import ttk, messagebox
import urllib.parse
import webbrowser
import winreg

import requests
from PIL import Image, ImageDraw
import pystray

BASE = 'http://210.43.112.9'
PORTAL = BASE + '/tpl/default/login_account.html'
SSID = 'USCWIFI'
DATA = Path(os.environ['LOCALAPPDATA']) / 'USCWIFI维护助手'
CONFIG = DATA / 'settings.json'
RUN_KEY = r'Software\Microsoft\Windows\CurrentVersion\Run'
APP_NAME = 'USCWIFIGuard'
CREATE_NO_WINDOW = 0x08000000


class Blob(C.Structure):
    _fields_ = [('size', W.DWORD), ('data', C.POINTER(C.c_ubyte))]


def protect(value, decrypt=False):
    """Windows DPAPI, bound to this Windows user, UI forbidden."""
    buf = C.create_string_buffer(value)
    src = Blob(len(value), C.cast(buf, C.POINTER(C.c_ubyte)))
    dst = Blob()
    dll = C.windll.crypt32
    if decrypt:
        ok = dll.CryptUnprotectData(C.byref(src), None, None, None, None, 1, C.byref(dst))
    else:
        ok = dll.CryptProtectData(C.byref(src), 'USCWIFI', None, None, None, 1, C.byref(dst))
    if not ok:
        raise C.WinError()
    try:
        return C.string_at(dst.data, dst.size)
    finally:
        C.windll.kernel32.LocalFree(dst.data)


def read_settings():
    if not CONFIG.exists():
        return {'paused': False, 'blocked': '', 'startup': True}, None
    obj = json.loads(CONFIG.read_text(encoding='utf-8'))
    secret = obj.pop('secret', '')
    credentials = json.loads(protect(base64.b64decode(secret), True)) if secret else None
    return obj, credentials


def write_settings(settings, credentials):
    DATA.mkdir(parents=True, exist_ok=True)
    obj = dict(settings)
    if credentials:
        obj['secret'] = base64.b64encode(protect(json.dumps(credentials).encode())).decode()
    tmp = CONFIG.with_suffix('.tmp')
    tmp.write_text(json.dumps(obj, ensure_ascii=False), encoding='utf-8')
    tmp.replace(CONFIG)


def startup_command():
    if getattr(sys, 'frozen', False):
        return subprocess.list2cmdline([sys.executable, '--background'])
    pythonw = str(Path(sys.executable).with_name('pythonw.exe'))
    return subprocess.list2cmdline([pythonw, str(Path(__file__).resolve()), '--background'])


def set_startup(enabled):
    with winreg.CreateKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as key:
        if enabled:
            winreg.SetValueEx(key, APP_NAME, 0, winreg.REG_SZ, startup_command())
        else:
            try:
                winreg.DeleteValue(key, APP_NAME)
            except FileNotFoundError:
                pass


def powershell(script):
    result = subprocess.run(['powershell.exe', '-NoProfile', '-NonInteractive', '-Command', script],
                            capture_output=True, creationflags=CREATE_NO_WINDOW, timeout=20)
    if result.returncode:
        raise RuntimeError('系统网络信息暂时不可用')
    return result.stdout.decode('utf-8-sig').strip()


class Guid(C.Structure):
    _fields_ = [('a', W.DWORD), ('b', W.WORD), ('c', W.WORD), ('d', C.c_ubyte * 8)]


class Interface(C.Structure):
    _fields_ = [('guid', Guid), ('description', W.WCHAR * 256), ('state', W.DWORD)]


class WLAN:
    def __init__(self):
        self.dll = C.windll.wlanapi
        self.handle = W.HANDLE()
        version = W.DWORD()
        rc = self.dll.WlanOpenHandle(2, None, C.byref(version), C.byref(self.handle))
        if rc:
            raise OSError(rc, '无法访问无线网络服务')

    def close(self):
        self.dll.WlanCloseHandle(self.handle, None)

    def snapshot(self):
        ptr = C.c_void_p()
        rc = self.dll.WlanEnumInterfaces(self.handle, None, C.byref(ptr))
        if rc:
            raise OSError(rc, '无法读取无线网络状态')
        found = []
        try:
            count = W.DWORD.from_address(ptr.value).value
            for i in range(count):
                iface = Interface.from_buffer_copy(C.string_at(ptr.value + 8 + i * C.sizeof(Interface), C.sizeof(Interface)))
                ssid = None
                if iface.state == 1:
                    data = C.c_void_p()
                    size, opcode = W.DWORD(), W.DWORD()
                    rc = self.dll.WlanQueryInterface(self.handle, C.byref(iface.guid), 7, None,
                                                     C.byref(size), C.byref(data), C.byref(opcode))
                    if rc:
                        raise OSError(rc, '无法确认当前无线网络')
                    try:
                        raw = C.string_at(data, size.value)
                        length = int.from_bytes(raw[520:524], 'little')
                        if size.value < 556 or length > 32:
                            raise RuntimeError('无线网络状态格式异常')
                        ssid = raw[524:524 + length].decode('utf-8', errors='replace')
                    finally:
                        self.dll.WlanFreeMemory(data)
                found.append((iface.state, ssid))
            return found
        finally:
            self.dll.WlanFreeMemory(ptr)


def action_for(wifi, wired):
    if wired:
        return 'other'
    if any(state == 1 and ssid != SSID for state, ssid in wifi):
        return 'other'
    if any(state == 1 and ssid == SSID for state, ssid in wifi):
        return 'campus'
    if not wifi:
        return 'no_adapter'
    if any(state not in (0, 4) for state, _ in wifi):
        return 'wait'
    return 'connect'


class IpList(C.Structure):
    pass


IpList._fields_ = [('next', C.POINTER(IpList)), ('ip', C.c_char * 16),
                   ('mask', C.c_char * 16), ('context', W.DWORD)]


class Adapter(C.Structure):
    pass


Adapter._fields_ = [('next', C.POINTER(Adapter)), ('combo', W.DWORD),
    ('name', C.c_char * 260), ('description', C.c_char * 132),
    ('address_length', W.UINT), ('address', C.c_ubyte * 8), ('index', W.DWORD),
    ('type', W.UINT), ('dhcp', W.UINT), ('current', C.POINTER(IpList)),
    ('ips', IpList), ('gateways', IpList)]


def adapters():
    size = W.ULONG()
    dll = C.windll.iphlpapi
    rc = dll.GetAdaptersInfo(None, C.byref(size))
    if rc == 232:
        return []
    if rc != 111:
        raise OSError(rc, '无法读取网络地址')
    for _ in range(3):
        buf = C.create_string_buffer(size.value)
        rc = dll.GetAdaptersInfo(buf, C.byref(size))
        if rc == 111:
            continue
        if rc:
            raise OSError(rc, '无法读取网络地址')
        pointer = C.cast(buf, C.POINTER(Adapter))
        result = []
        while pointer:
            a = pointer.contents
            ips = []
            ip = C.pointer(a.ips)
            while ip:
                value = ip.contents.ip.decode('ascii')
                if value != '0.0.0.0' and not value.startswith('169.254.'):
                    ips.append(value)
                ip = ip.contents.next
            gateway = a.gateways.ip.decode('ascii')
            result.append((a.index, a.type, ips, gateway))
            pointer = a.next
        return result
    raise RuntimeError('网络地址正在变化')


_hardware = {}


def refresh_hardware(stop):
    # Slow inventory runs off the critical path. Unknown Ethernet is preserved.
    while not stop.is_set():
        try:
            result = json.loads(powershell("[Console]::OutputEncoding=[System.Text.Encoding]::UTF8; @(Get-NetAdapter -IncludeHidden -ErrorAction Stop | Select-Object ifIndex,HardwareInterface) | ConvertTo-Json -Compress"))
            if isinstance(result, dict):
                result = [result]
            current = {a['ifIndex']: bool(a['HardwareInterface']) for a in result}
            _hardware.update(current)
        except Exception:
            pass
        stop.wait(30)


def wired_active():
    return any(kind == 6 and ips and gateway not in ('', '0.0.0.0')
               and _hardware.get(index, True) for index, kind, ips, gateway in adapters())


def login_page_url():
    params = {'nasId': '1'}
    try:
        ips = {ip for _, kind, addresses, _ in adapters() if kind == 71 for ip in addresses}
        if len(ips) == 1:
            params['ip'] = ips.pop()
    except Exception:
        pass
    return PORTAL + '?' + urllib.parse.urlencode(params)


def internet_available():
    # Verify exact content over HTTPS: portal HTML cannot masquerade as internet.
    for url, expected in [('https://www.msftconnecttest.com/connecttest.txt', 'Microsoft Connect Test'),
                          ('https://connectivitycheck.gstatic.com/generate_204', None)]:
        try:
            with requests.Session() as s:
                s.trust_env = False
                r = s.get(url, timeout=(3, 4), allow_redirects=False)
                if (expected and r.status_code == 200 and r.text.strip() == expected) or (expected is None and r.status_code == 204):
                    return True
        except requests.RequestException:
            pass
    return False


class ManualRequired(Exception):
    pass


class Portal:
    def __init__(self):
        self.s = requests.Session()
        self.s.trust_env = False

    def close(self):
        self.s.close()

    def call(self, path, data=None):
        r = self.s.request('POST' if data is not None else 'GET', BASE + '/api/' + path,
                           data=data, timeout=(2, 3), allow_redirects=False)
        r.raise_for_status()
        if r.is_redirect:
            raise RuntimeError('认证接口发生变化')
        # Some server responses omit UTF-8 in the Content-Type header.
        return json.loads(r.content.decode('utf-8-sig'))

    def logged_in(self):
        status = self.call('account/status')
        if status.get('code') not in (0, 1):
            raise RuntimeError('无法识别认证状态')
        return status.get('code') == 0

    def discover(self, redirect=False):
        # Read the current captive redirect. Never reuse a previous user's IP.
        params = {}
        if redirect:
            try:
                r = self.s.get('http://www.msftconnecttest.com/connecttest.txt', timeout=(1, 2))
                u = urllib.parse.urlsplit(r.url)
                if u.hostname == '210.43.112.9':
                    params = dict(urllib.parse.parse_qsl(u.query))
            except requests.RequestException:
                pass
        ips = [ip for _, kind, addresses, _ in adapters() if kind == 71 for ip in addresses]
        ip = params.get('wlanuserip') or params.get('ip')
        if ip not in ips:
            if len(ips) != 1:
                raise RuntimeError('等待校园网分配明确的 IPv4 地址')
            ip = ips[0]
        fields = {'nasId': params.get('nasId', '1'), 'userIpv4': ip, 'isp': 'local'}
        for key in ('switchip', 'mac'):
            if params.get(key):
                fields['userMac' if key == 'mac' else key] = params[key]
        return fields

    def login(self, credentials, guard):
        token = self.call('csrf-token').get('csrf_token')
        if not token:
            raise RuntimeError('未取得网页登录校验信息')
        self.s.headers['X-CSRF-Token'] = token
        fields = self.discover()
        fields.update(credentials)
        if not guard():
            return False
        checked = self.call('account/check', fields)
        if str(checked.get('isChangePwd')) == '1':
            raise ManualRequired('校园网要求修改密码，请打开登录页处理')
        if checked.get('code') == 1:
            raise ManualRequired('账号校验未通过，请检查账号密码或打开登录页')
        if checked.get('code') != 0:
            raise ManualRequired('账号校验出现未知结果，请打开登录页处理')
        if not guard():
            return False
        result = self.call('account/login', fields)
        if result.get('code') == 2:
            raise ManualRequired('校园网要求验证码，请打开登录页处理')
        if result.get('code') != 0:
            raise ManualRequired('登录被拒绝，请检查账号密码、欠费或设备数量限制')
        return True


class App:
    def __init__(self):
        self.root = tk.Tk()
        self.root.withdraw()
        self.root.title('USCWIFI 维护助手')
        self.root.geometry('510x440')
        self.root.resizable(False, False)
        self.lock = threading.RLock()
        self.stop = threading.Event()
        self.wake = threading.Event()
        self.events = queue.Queue()
        self.status = '正在初始化'
        self.failures = 0
        self.next_login = 0
        self.next_status = 0
        self.last_action = None
        self.next_connect = 0
        self.last_internet = 0
        self.probe_running = False
        self.probe_ok = None
        self.network_epoch = 0
        self.auth_state = None
        try:
            self.settings, self.credentials = read_settings()
        except Exception:
            self.settings, self.credentials = {'paused': True, 'blocked': '', 'startup': False}, None
            self.events.put(('notice', '本机配置无法读取，请重新输入账号密码'))
        self.username = tk.StringVar(value=(self.credentials or {}).get('username', ''))
        self.password = tk.StringVar(value='')
        self.startup = tk.BooleanVar(value=self.settings.get('startup', True))
        self.status_text = tk.StringVar(value=self.status)
        self.pause_text = tk.StringVar(value='恢复维护' if self.settings.get('paused') else '暂停维护')
        self.build_ui()
        self.tray = pystray.Icon(APP_NAME, self.icon_image(), 'USCWIFI 维护助手', pystray.Menu(
            pystray.MenuItem('状态与账号设置', lambda *_: self.events.put(('show', None)), default=True),
            pystray.MenuItem('暂停 / 恢复维护', lambda *_: self.events.put(('pause', None))),
            pystray.MenuItem('打开校园网登录页', lambda *_: self.events.put(('portal', None))),
            pystray.MenuItem('退出', lambda *_: self.events.put(('quit', None)))))
        threading.Thread(target=self.tray.run, daemon=True).start()
        threading.Thread(target=refresh_hardware, args=(self.stop,), daemon=True).start()
        threading.Thread(target=self.worker, daemon=True).start()
        self.root.after(250, self.pump)
        if not self.credentials or '--background' not in sys.argv:
            self.show()

    @staticmethod
    def icon_image():
        image = Image.new('RGB', (64, 64), '#16756b')
        d = ImageDraw.Draw(image)
        for box in [(8, 10, 56, 58), (18, 23, 46, 51)]:
            d.arc(box, 215, 325, fill='white', width=5)
        d.ellipse((28, 43, 36, 51), fill='white')
        return image

    def build_ui(self):
        f = ttk.Frame(self.root, padding=22)
        f.pack(fill='both', expand=True)
        ttk.Label(f, text='USCWIFI 维护助手', font=('Microsoft YaHei UI', 17, 'bold')).pack(anchor='w')
        ttk.Label(f, textvariable=self.status_text, wraplength=455).pack(anchor='w', pady=(12, 16))
        ttk.Label(f, text='校园网账号').pack(anchor='w')
        ttk.Entry(f, textvariable=self.username, width=53).pack(fill='x', pady=(4, 10))
        ttk.Label(f, text='密码（已保存时可留空，保留原密码）').pack(anchor='w')
        ttk.Entry(f, textvariable=self.password, show='●', width=53).pack(fill='x', pady=(4, 10))
        ttk.Checkbutton(f, text='登录 Windows 后自动启动', variable=self.startup).pack(anchor='w')
        ttk.Label(f, text='账号密码通过 Windows 加密保存在当前用户本机。\n只维护 USCWIFI；保留其他 Wi-Fi 和有线网络。', wraplength=455).pack(anchor='w', pady=12)
        row = ttk.Frame(f)
        row.pack(fill='x', pady=4)
        ttk.Button(row, text='保存并开始', command=self.save).pack(side='left')
        ttk.Button(row, textvariable=self.pause_text, command=self.toggle_pause).pack(side='left', padx=8)
        ttk.Button(row, text='打开登录页', command=self.open_portal).pack(side='left')
        ttk.Button(row, text='隐藏到托盘', command=self.root.withdraw).pack(side='left', padx=8)
        ttk.Button(f, text='退出程序', command=self.quit).pack(anchor='e', pady=10)
        self.root.protocol('WM_DELETE_WINDOW', self.root.withdraw)

    def show(self):
        self.root.deiconify()
        self.root.lift()

    def save(self):
        username, password = self.username.get().strip(), self.password.get()
        with self.lock:
            if not password and self.credentials and username == self.credentials.get('username'):
                password = self.credentials['password']
            if not username or not password:
                messagebox.showinfo('需要账号密码', '请输入校园网账号和密码。', parent=self.root)
                return
            credentials = {'username': username, 'password': password}
            settings = {'paused': False, 'blocked': '', 'startup': self.startup.get()}
            try:
                write_settings(settings, credentials)
                set_startup(settings['startup'])
            except Exception:
                messagebox.showerror('保存失败', '配置或自动启动设置保存失败，请重试。', parent=self.root)
                return
            self.credentials, self.settings = credentials, settings
            self.next_login, self.failures = 0, 0
            self.auth_state = None
            self.network_epoch += 1
            self.probe_ok = None
            self.last_internet = 0
        self.password.set('')
        self.pause_text.set('暂停维护')
        self.update('配置已保存，开始维护')
        self.next_status = 0
        self.wake.set()

    def toggle_pause(self):
        with self.lock:
            self.settings['paused'] = False if self.settings.get('blocked') else not self.settings.get('paused', False)
            self.network_epoch += 1
            self.auth_state = None
            self.probe_ok = None
            self.last_internet = 0
            if not self.settings['paused']:
                self.settings['blocked'] = ''
                self.next_login, self.failures = 0, 0
            try:
                write_settings(self.settings, self.credentials)
            except Exception:
                self.events.put(('notice', '暂停状态未能保存到本机'))
            self.pause_text.set('恢复维护' if self.settings['paused'] else '暂停维护')
            self.next_status = 0
            self.wake.set()

    def open_portal(self):
        webbrowser.open(login_page_url())

    def update(self, text):
        with self.lock:
            if text != self.status:
                self.status = text
                logging.info(text)
                self.events.put(('status', text))

    def permitted(self):
        with self.lock:
            return not (self.stop.is_set() or self.settings.get('paused') or self.settings.get('blocked'))

    def safe_to_submit(self, wlan, credentials):
        with self.lock:
            same_credentials = self.credentials == credentials
        return same_credentials and self.permitted() and action_for(wlan.snapshot(), wired_active()) == 'campus'

    def block(self, reason):
        with self.lock:
            self.settings['blocked'] = reason
            try:
                write_settings(self.settings, self.credentials)
            except Exception:
                logging.info('需要人工处理的状态未能持久保存')
        self.update(reason + '；自动登录已停止')
        self.events.put(('notice', reason + '。处理后点击“暂停 / 恢复维护”或“保存并开始”。'))

    def worker(self):
        wlan = None
        try:
            wlan = WLAN()
            while not self.stop.is_set():
                try:
                    with self.lock:
                        settings, credentials = dict(self.settings), dict(self.credentials or {})
                    if settings.get('paused'):
                        self.update('维护已暂停')
                    elif settings.get('blocked'):
                        self.update(settings['blocked'] + '；自动登录已停止')
                    elif not credentials:
                        self.update('请先输入账号密码并保存')
                    else:
                        action = action_for(wlan.snapshot(), wired_active())
                        if action != self.last_action:
                            self.next_status = self.next_login = 0
                            self.last_internet = 0
                            self.probe_ok = None
                            self.network_epoch += 1
                            self.auth_state = None
                            self.last_action = action
                        if action == 'other':
                            self.update('正在使用其他网络，校园网维护待命')
                        elif action == 'no_adapter':
                            self.update('未发现无线网卡，等待可用')
                        elif action == 'wait':
                            self.update('等待无线连接完成或开启 Wi-Fi')
                        elif action == 'connect':
                            self.update('正在连接 USCWIFI，请确保 Wi-Fi 已开启且在覆盖范围内')
                            if time.monotonic() >= self.next_connect and self.permitted() and action_for(wlan.snapshot(), wired_active()) == 'connect':
                                self.next_connect = time.monotonic() + 8
                                subprocess.run(['netsh', 'wlan', 'connect', 'name=USCWIFI', 'ssid=USCWIFI'],
                                               capture_output=True, timeout=12, creationflags=CREATE_NO_WINDOW)
                        else:
                            if time.monotonic() >= self.next_status:
                                self.next_status = time.monotonic() + 3
                                self.maintain(wlan, credentials)
                except ManualRequired as exc:
                    self.block(str(exc))
                except Exception:
                    # No raw exception: response bodies can contain account data.
                    self.failures += 1
                    self.next_login = time.monotonic() + min(60, 2 ** min(self.failures, 6))
                    self.update('网络或认证服务暂不可用，稍后重试')
                self.wake.wait(0.5)
                self.wake.clear()
        except Exception:
            self.update('无线网络服务不可用，请检查 Windows WLAN 服务后重启本程序')
            self.events.put(('notice', self.status))
        finally:
            if wlan:
                wlan.close()

    def maintain(self, wlan, credentials):
        with self.lock:
            request_epoch = self.network_epoch
        portal = Portal()
        try:
            online = portal.logged_in()
            with self.lock:
                if not self.permitted() or request_epoch != self.network_epoch:
                    return
                self.record_auth(online)
                request_epoch = self.network_epoch
                if online:
                    self.failures = 0
                    if self.probe_ok is True:
                        self.update('USCWIFI 已登录，Internet 可用')
                    elif self.probe_ok is False:
                        self.update('校园网已登录，等待 Internet 恢复')
                    else:
                        self.update('校园网已登录，正在后台确认 Internet')
                    interval = 60 if self.probe_ok else 10
                    if not self.probe_running and time.monotonic() - self.last_internet >= interval:
                        self.probe_running = True
                        self.last_internet = time.monotonic()
                        threading.Thread(target=self.probe_internet, args=(self.network_epoch,), daemon=True).start()
                    return
                if time.monotonic() < self.next_login:
                    self.update('认证接口暂未确认在线，稍后再次查询')
                    return
                self.update('正在进行校园网认证')
            if portal.login(credentials, lambda: self.safe_to_submit(wlan, credentials)):
                with self.lock:
                    if self.permitted() and request_epoch == self.network_epoch:
                        self.next_login = time.monotonic() + 8
                        self.next_status = time.monotonic() + 0.5
                        self.last_internet = 0
                        self.update('认证已提交，等待认证接口确认')
        finally:
            portal.close()

    def record_auth(self, online):
        """An authenticated session must never inherit a prior login cooldown."""
        previous = self.auth_state
        if online != previous:
            self.network_epoch += 1
            self.probe_ok = None
            self.last_internet = 0
            self.auth_state = online
        if online or previous is True:
            self.next_login = 0
        if online:
            self.failures = 0

    def probe_internet(self, epoch):
        try:
            available = internet_available()
            with self.lock:
                if epoch == self.network_epoch and self.auth_state is True and self.permitted() and self.last_action == 'campus':
                    self.probe_ok = available
                    self.update('USCWIFI 已登录，Internet 可用' if available else '校园网已登录，等待 Internet 恢复')
        finally:
            self.probe_running = False

    def pump(self):
        try:
            while True:
                event, value = self.events.get_nowait()
                if event == 'status':
                    # Several worker results can arrive before this UI tick.
                    # Render the latest state instead of replaying old results.
                    self.status_text.set(self.status)
                    self.tray.title = ('USCWIFI：' + self.status)[:120]
                    if self.settings.get('blocked'):
                        self.pause_text.set('恢复维护')
                elif event == 'notice':
                    self.show()
                    messagebox.showinfo('USCWIFI 维护助手', value, parent=self.root)
                elif event == 'show':
                    self.show()
                elif event == 'pause':
                    self.toggle_pause()
                elif event == 'portal':
                    self.open_portal()
                elif event == 'quit':
                    self.quit()
                    return
        except queue.Empty:
            pass
        self.root.after(250, self.pump)

    def quit(self):
        self.stop.set()
        self.wake.set()
        self.tray.stop()
        self.root.destroy()

    def run(self):
        self.root.mainloop()


def main():
    # One instance per logged-in Windows session.
    kernel = C.windll.kernel32
    kernel.CreateMutexW.restype = W.HANDLE
    mutex = kernel.CreateMutexW(None, False, 'Local\\USCWIFIGuard.v1')
    if kernel.GetLastError() == 183:
        C.windll.user32.MessageBoxW(None, '程序已在运行，请使用右下角托盘图标打开设置。', 'USCWIFI 维护助手', 64)
        return
    DATA.mkdir(parents=True, exist_ok=True)
    handler = RotatingFileHandler(DATA / 'status.log', maxBytes=256000, backupCount=2, encoding='utf-8')
    logging.basicConfig(level=logging.INFO, handlers=[handler], format='%(asctime)s %(message)s')
    try:
        App().run()
    finally:
        kernel.CloseHandle(W.HANDLE(mutex))


if __name__ == '__main__':
    main()
