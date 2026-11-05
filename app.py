# -*- coding: utf-8 -*-
"""
小红车清理工具 · 图形界面主程序（pywebview）

双击打开 → 点选自己的账号 → 点按钮。所有操作只改本地 acf / 431960 下载缓存。
不删壁纸文件、不改云端订阅、不联网、不改 Steam 程序文件。

打包（build.py 会生成图标/版本信息并调用 PyInstaller，勿手敲命令漏 DLL）：
  python build.py
自检（不弹窗）：
  python app.py --selftest
"""
import os
import sys
import re
import glob
import time
import shutil
import ctypes
import subprocess
import threading
import datetime
import tempfile
import json

# 只记方法名与耗时，不记路径、账号、ID。窗口未响应时用它定位卡在哪一步。
DIAG_PATH = os.path.join(tempfile.gettempdir(), 'we-cleaner.log')
# 首次使用注意事项只在第一次打开时弹；标记放在用户目录，别写进工具目录（可能是只读的）
_NOTICE_BASE = (os.environ.get('LOCALAPPDATA') or os.environ.get('APPDATA')
                or tempfile.gettempdir())
NOTICE_FLAG = os.path.join(_NOTICE_BASE, 'we-cleaner-notice-seen')
MEI_LIST = os.path.join(_NOTICE_BASE, 'we-cleaner-mei.txt')
LAST_EXIT = os.path.join(_NOTICE_BASE, 'we-cleaner-last-exit.txt')
BOOT_READY = threading.Event()


def _note_abnormal_exit(reason):
    """异常自退时留个原因，下次打开用中文告诉用户，不让工具无声消失。"""
    try:
        with open(LAST_EXIT, 'w', encoding='utf-8') as f:
            f.write(reason)
    except Exception:
        pass


def _take_abnormal_hint():
    if not os.path.isfile(LAST_EXIT):
        return ''
    try:
        with open(LAST_EXIT, encoding='utf-8') as f:
            reason = f.read().strip()
        os.remove(LAST_EXIT)
        return reason
    except Exception:
        return ''


def diag(msg):
    try:
        with open(DIAG_PATH, 'a', encoding='utf-8') as f:
            f.write('%s %s\n' % (datetime.datetime.now().strftime('%m-%d %H:%M:%S'), msg))
    except Exception:
        pass

# PyInstaller --windowed 打包后 sys.stdout / sys.stderr 可能是 None，
# clean_acf.py 里大量 print() 会被我们接走，但兜底输出对象必须可写。
_REAL_STDOUT = sys.stdout or open(os.devnull, 'w', encoding='utf-8')
if sys.stderr is None:
    sys.stderr = open(os.devnull, 'w', encoding='utf-8')


class LogWriter:
    """接住 clean_acf 的 print，并自动给真实账号 ID 打码。"""
    def __init__(self):
        self.lines = []
        self.ids = []

    def clear(self):
        self.lines = []

    def write(self, s):
        if s and s.strip():
            self.lines.append(s.rstrip())

    def flush(self):
        pass

    def drain(self):
        out = []
        for line in self.lines:
            for a in self.ids:
                if a in line:
                    line = line.replace(a, a[:4] + '*' * max(1, len(a) - 8) + a[-4:])
                try:
                    sid = str(76561197960265728 + int(a))
                    if sid in line:
                        line = line.replace(sid, sid[:7] + '*' * 6 + sid[-4:])
                except ValueError:
                    pass
            out.append([line, ''])
        self.lines = []
        return out


LOG = LogWriter()
sys.stdout = LOG
sys.stderr = LOG

import webview  # noqa: E402
import clean_acf as core  # noqa: E402

APP_TITLE = '小红车清理工具'


def resource_path(name):
    if getattr(sys, 'frozen', False):
        return os.path.join(sys._MEIPASS, name)
    return os.path.join(os.path.dirname(os.path.abspath(__file__)), name)


def app_dir():
    if getattr(sys, 'frozen', False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.abspath(__file__))


def human(n):
    return '%.2f GB' % (n / 1024 ** 3) if n >= 1024 ** 3 else '%.1f MB' % (n / 1024 ** 2)


def size_of(path):
    if os.path.isfile(path):
        try:
            return os.path.getsize(path)
        except OSError:
            return 0
    total = 0
    for dp, dn, fn in os.walk(path):
        for f in fn:
            try:
                total += os.path.getsize(os.path.join(dp, f))
            except OSError:
                pass
    return total


def webview2_ok():
    """返回 (是否可用, 版本号)。

    WebView2 可能装在 Program Files、Program Files (x86) 或用户目录（按用户安装），
    只认一个固定路径会把「明明装了」误判成「没装」，工具直接不启动。
    优先读注册表里的 pv 版本号，读不到再退回三个常见目录探测。
    """
    try:
        import winreg
        guid = r'Clients\{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}'
        for root, sub in (
            (winreg.HKEY_LOCAL_MACHINE, r'SOFTWARE\WOW6432Node\Microsoft\EdgeUpdate' + '\\' + guid),
            (winreg.HKEY_LOCAL_MACHINE, r'SOFTWARE\Microsoft\EdgeUpdate' + '\\' + guid),
            (winreg.HKEY_CURRENT_USER, r'Software\Microsoft\EdgeUpdate' + '\\' + guid),
        ):
            try:
                with winreg.OpenKey(root, sub) as k:
                    pv = str(winreg.QueryValueEx(k, 'pv')[0] or '').strip()
                if pv and pv != '0.0.0.0':
                    return True, pv
            except Exception:
                continue
    except Exception:
        pass
    for d in (r'C:\Program Files (x86)\Microsoft\EdgeWebView\Application',
              r'C:\Program Files\Microsoft\EdgeWebView\Application',
              os.path.join(os.environ.get('LOCALAPPDATA') or '', 'Microsoft',
                           'EdgeWebView', 'Application')):
        try:
            if d and os.path.isdir(d) and any(re.match(r'^\d+\.', x) for x in os.listdir(d)):
                return True, ''
        except Exception:
            pass
    return False, ''


def drive_type(path):
    """盘符类型：3 = 本地固定磁盘（Windows 回收站只支持这个）。"""
    try:
        root = os.path.splitdrive(os.path.abspath(path))[0] + '\\'
        return int(ctypes.windll.kernel32.GetDriveTypeW(root))
    except Exception:
        return 0


def fit_window(want_w=800, want_h=740):
    """按屏幕工作区收缩窗口。

    固定 740 高在 1366×768 笔记本、或 150% 缩放的 1080p 上会超出屏幕，
    底部那排按钮（还原/卸载）点不到。
    """
    try:
        class RECT(ctypes.Structure):
            _fields_ = [('left', ctypes.c_long), ('top', ctypes.c_long),
                        ('right', ctypes.c_long), ('bottom', ctypes.c_long)]
        r = RECT()
        if ctypes.windll.user32.SystemParametersInfoW(0x0030, 0, ctypes.byref(r), 0):
            aw = int(r.right - r.left)
            ah = int(r.bottom - r.top)
            if aw > 200 and ah > 200:
                return min(want_w, aw - 40), max(480, min(want_h, ah - 60))
    except Exception as e:
        diag('fit_window failed: %r' % e)
    return want_w, want_h


def alert(text):
    try:
        ctypes.windll.user32.MessageBoxW(0, text, APP_TITLE, 0x10)
    except Exception:
        _REAL_STDOUT.write(text + '\n') if _REAL_STDOUT else None


def steam_exe():
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r'Software\Valve\Steam') as k:
            v, _ = winreg.QueryValueEx(k, 'SteamExe')
            if v and os.path.isfile(v):
                return v
    except Exception:
        pass
    root = core.reg_steam_path()
    if root:
        p = os.path.join(root, 'steam.exe')
        if os.path.isfile(p):
            return p
    return None


def recycle(path):
    """送回收站（可还原），不直接抹掉。

    用 Win32 SHFileOperationW 直接调用系统外壳，不启动脚本解释器。
    之前用 PowerShell 执行删除，会被 360 等主动防御判成
    「陌生 exe 借脚本解释器批量删文件」（LOLBin 特征）而拦截。
    """
    if not os.path.exists(path):
        return True, ''
    from ctypes import wintypes

    class SHFILEOPSTRUCTW(ctypes.Structure):
        _fields_ = [
            ('hwnd', wintypes.HWND),
            ('wFunc', wintypes.UINT),
            ('pFrom', ctypes.c_void_p),
            ('pTo', ctypes.c_void_p),
            ('fFlags', ctypes.c_uint16),
            ('fAnyOperationsAborted', wintypes.BOOL),
            ('hNameMappings', ctypes.c_void_p),
            ('lpszProgressTitle', ctypes.c_wchar_p),
        ]

    try:
        shell32 = ctypes.windll.shell32
        shell32.SHFileOperationW.argtypes = [ctypes.POINTER(SHFILEOPSTRUCTW)]
        shell32.SHFileOperationW.restype = ctypes.c_int
        # pFrom 需要「双 \0 结尾」的路径列表
        buf = ctypes.create_unicode_buffer(os.path.abspath(path) + '\0')
        op = SHFILEOPSTRUCTW()
        op.hwnd = None
        op.wFunc = 3                       # FO_DELETE
        op.pFrom = ctypes.cast(buf, ctypes.c_void_p)
        op.pTo = None
        # SILENT | NOCONFIRMATION | ALLOWUNDO | NOERRORUI
        op.fFlags = 0x0004 | 0x0010 | 0x0040 | 0x0400
        rc = shell32.SHFileOperationW(ctypes.byref(op))
        if rc == 0 and not op.fAnyOperationsAborted:
            return True, ''
        return False, '系统返回码 %s（可能被安全软件阻止）' % rc
    except Exception as e:
        return False, str(e)


def safe(fn):
    """任何接口抛异常都要给界面一个明确结果，绝不让 JS 的 await 永远挂起。"""
    def wrap(self, *a, **kw):
        t0 = time.perf_counter()
        diag('BEGIN %s' % fn.__name__)
        try:
            r = fn(self, *a, **kw)
            diag('END   %s  %.2fs' % (fn.__name__, time.perf_counter() - t0))
            return r
        except Exception as e:
            diag('ERROR %s  %.2fs  %r' % (fn.__name__, time.perf_counter() - t0, e))
            LOG.clear()
            try:
                state = self._state()
            except Exception:
                state = None
            return {'ok': False,
                    'lines': [['操作出错：%s' % e, 'tip'],
                              ['没有改动任何文件。', 'dim']],
                    'state': state, 'done': None,
                    'error': '出错了：%s\n\n没有改动任何文件。' % e}
    wrap.__name__ = fn.__name__
    return wrap


class Api:
    def __init__(self):
        self.window = None
        self.acf = None
        self.groups = {}
        self.order = []
        self.meta = {}
        self.cache_targets = []
        self._cache_size = 0
        self._libs = 0

    # ---------- 扫描 ----------
    def _scan(self):
        found = core.find_acf()
        self.acf = found[0] if found else None
        self.groups, self.order = {}, []
        if self.acf:
            try:
                text, _, _ = core.read_text(self.acf)
                _, _, g = core.analyse(text)
                self.groups = g
                self.order = sorted(g, key=lambda a: -len(g[a])) if g else []
                self.meta = core.account_meta()
            except Exception:
                pass
        LOG.ids = list(self.groups.keys())

        steamapps = os.path.dirname(os.path.dirname(self.acf)) if self.acf else None
        self.cache_targets = []
        if steamapps:
            dl = os.path.join(steamapps, 'workshop', 'downloads')
            folder = os.path.join(dl, '431960')
            if os.path.isdir(folder):
                self.cache_targets.append(folder)
            self.cache_targets += [p for p in glob.glob(os.path.join(dl, '431960*.patch'))
                                   if os.path.isfile(p)]
        # 遍历缓存目录 + 全盘找库都很慢，只在扫描时算一次，别让每次点按钮都重来
        self._cache_size = sum(size_of(p) for p in self.cache_targets)
        self._libs = len(found) if found else 0
        return self

    @staticmethod
    def _tail(a):
        return a[-4:] if len(a) >= 4 else '****'

    def _state(self):
        accounts = []
        for a in self.order:
            name, when = self.meta.get(a, ('', ''))
            accounts.append({
                'name': name or ('账号 ' + self._tail(a)),
                'count': len(self.groups[a]),
                'last': when or '未知',
                'tail': self._tail(a),
            })
        cache = self._cache_size
        return {
            'acf': self.acf or '',
            'acf_ok': bool(self.acf),
            'steam': 'running' if core.steam_running() else 'stopped',
            'cache': human(cache) if cache else '0 GB（已清理）',
            'accounts': accounts,
            'webview2': webview2_ok(),
            'libs': self._libs,
        }

    @staticmethod
    def _result(ok, lines, state, done=None, error=None):
        return {'ok': ok, 'lines': lines, 'state': state, 'done': done, 'error': error}

    @safe
    def refresh(self):
        LOG.clear()
        self._scan()
        state = self._state()
        lines = []
        if state['acf_ok']:
            lines.append(['已找到配置文件', 'ok'])
            lines.append(['检测到 %d 个账号，%d 条订阅记录' %
                          (len(state['accounts']), sum(a['count'] for a in state['accounts'])), ''])
        else:
            lines.append(['没找到 appworkshop_431960.acf，请确认已安装 Wallpaper Engine', 'tip'])
        if not state['webview2']:
            lines.append(['警告：本机缺少 WebView2 运行库，界面可能无法显示', 'tip'])
        if state['libs'] > 1:
            lines.append(['检测到多个游戏库，当前只处理第一个', 'tip'])
        return {'ok': True, 'lines': lines, 'state': state}

    # ---------- Steam ----------
    def _exit_steam(self, lines):
        if not core.steam_running():
            lines.append(['Steam 已退出，可以安全操作', 'ok'])
            return True
        lines.append(['正在请求 Steam 正常退出（不会强杀、不会丢下载）…', 'tip'])
        try:
            os.startfile('steam://exit')
        except Exception as e:
            lines.append(['steam://exit 不可用，改用关闭窗口消息', 'dim'])
            diag('steam://exit failed: %r' % e)
        for i in range(14):
            if not core.steam_running():
                lines.append(['Steam 已退出', 'ok'])
                return True
            if i == 3:      # 约 1.6 秒后仍没退，走第二条路
                n = core.close_steam_windows()
                lines.append(['已向 Steam 主窗口发送关闭消息（%d 个窗口，正常退出）' % n, 'dim'])
                diag('WM_CLOSE sent to %d steam windows' % n)
            time.sleep(0.4)
        lines.append(['仍未能自动退出，请在 Steam 窗口点 X 或从托盘右键退出后重试', 'tip'])
        return False

    @safe
    def exit_steam(self):
        LOG.clear()
        lines = []
        ok = self._exit_steam(lines)
        lines += LOG.drain()
        return self._result(ok, lines, self._state(),
                            done='Steam 已退出。' if ok else None,
                            error=('没能自动退出 Steam。\n请在 Steam 窗口右上角点 X，'
                                   '或托盘图标右键 → 退出，然后重试。\n\n没有改动任何文件。')
                            if not ok else None)

    @safe
    def start_steam(self):
        LOG.clear()
        lines = []
        if core.steam_running():
            lines.append(['Steam 已经在运行了', ''])
            return self._result(True, lines, self._state(), done='Steam 已经在运行。')
        exe = steam_exe()
        if not exe:
            return self._result(False, [['没找到 steam.exe', 'tip']], self._state(),
                                error='没找到 Steam 主程序，请手动启动。')
        try:
            subprocess.Popen([exe], close_fds=True)
            lines.append(['正在启动 Steam…', 'ok'])
            return self._result(True, lines, self._state(), done='Steam 已启动。')
        except Exception as e:
            return self._result(False, [['启动失败：%s' % e, 'tip']], self._state(),
                                error='启动失败：%s' % e)

    # ---------- 主流程 ----------
    @safe
    def clean(self, idx):
        LOG.clear()
        lines = []
        if not self.acf or not self.order:
            return self._result(False, [['没找到配置文件或订阅记录', 'tip']], self._state(),
                                error='没找到配置文件或订阅记录。')
        try:
            mine = self.order[int(idx) - 1]
        except (ValueError, IndexError, TypeError):
            return self._result(False, [['请先选择账号', 'tip']], self._state(),
                                error='请先在上面点选「你自己的账号」。')
        if not self._exit_steam(lines):
            lines += LOG.drain()
            return self._result(False, lines, self._state(),
                                error=('没能自动退出 Steam。\n请在 Steam 窗口右上角点 X，'
                                       '或托盘图标右键 → 退出，然后重试。\n\n没有改动任何文件。'))
        text, nl, bom = core.read_text(self.acf)
        _, _, g = core.analyse(text)
        n = sum(len(r) for a, r in g.items() if a != mine)
        keep = len(g.get(mine, []))
        if n == 0:
            lines.append(['没有别的账号记录，已经是干净的', 'ok'])
            return self._result(True, lines, self._state(), done='没有别的账号记录，不用清理。')
        lines.append(['将删除其他账号 %d 条，保留你的 %d 条' % (n, keep), 'tip'])
        ok = core.apply_changes(self.acf, text, nl, bom, mine, n, ask=False)
        lines += LOG.drain()
        if ok:
            self._scan()
            return self._result(True, lines, self._state(),
                                done='清理完成：删除 %d 条，保留 %d 条。\n备份已保存在配置文件旁边。' % (n, keep))
        return self._result(False, lines, self._state(),
                            error='校验没通过，已中止，文件未改动。详情看日志。')

    # ---------- 清缓存 ----------
    @safe
    def clear_cache(self):
        LOG.clear()
        lines = []
        if core.steam_running():
            return self._result(False, [['Steam 正在运行，请先退出', 'tip']], self._state(),
                                error='请先退出 Steam，再清缓存。')
        if not self.cache_targets:
            return self._result(True, [['没有找到 431960 下载缓存', 'ok']], self._state(),
                                done='没有需要清理的下载缓存。')
        # 回收站只支持本地固定磁盘：U 盘 / 移动硬盘 / 网络盘上带 FOF_ALLOWUNDO 删除
        # 会变成永久删除，与「可还原」的承诺不符，直接拦下来。
        odd = [(p, drive_type(p)) for p in self.cache_targets if drive_type(p) != 3]
        if odd:
            kind = {2: '可移动磁盘', 4: '网络驱动器', 5: '光驱', 6: '内存盘'}.get(odd[0][1],
                                                                        '非本地固定磁盘')
            diag('CLEAR_CACHE blocked: drive type %s' % odd[0][1])
            return self._result(False, [
                ['下载缓存不在本地固定磁盘（%s）' % kind, 'tip'],
                ['这种位置删文件不进回收站，会永久删除，已阻止', 'tip'],
            ], self._state(),
                error=('下载缓存所在的磁盘是「%s」。\n\n'
                       '在这种位置删除文件不会进回收站，删了就找不回来，'
                       '所以工具没有删除任何东西。\n\n'
                       '如果确实要清，请自己手动删掉这个文件夹；'
                       '或者把 Steam 库放到本地硬盘再用本工具。' % kind))
        total = sum(size_of(p) for p in self.cache_targets)
        lines.append(['只清理 431960 相关：%d 项，共 %s' % (len(self.cache_targets), human(total)), 'tip'])
        for p in self.cache_targets:
            ok, err = recycle(p)
            lines.append([('已送回收站：' + os.path.basename(p)) if ok else ('失败：' + err),
                          'ok' if ok else 'tip'])
        lines += LOG.drain()
        self._scan()
        good = all(not l[0].startswith('失败') for l in lines)
        return self._result(good, lines, self._state(),
                            done=('缓存已移到回收站。\n\n'
                                  '注意：磁盘空间要清空回收站之后才会真正释放，'
                                  '现在占用还没变少。\n如需找回，打开回收站还原即可。')
                            if good else None,
                            error='部分文件没能清除，详情看日志。' if not good else None)

    # ---------- 还原 ----------
    @safe
    def restore(self):
        LOG.clear()
        lines = []
        if not self.acf:
            return self._result(False, [['没找到配置文件', 'tip']], self._state(),
                                error='没找到配置文件。')
        if core.steam_running():
            return self._result(False, [['Steam 正在运行，请先退出', 'tip']], self._state(),
                                error='请先退出 Steam 再还原配置文件。')
        ok = core.do_restore(self.acf)
        lines += LOG.drain()
        if not ok:
            return self._result(False, lines, self._state(),
                                error='没有找到可用备份，或没能确认 Steam 已退出。\n\n没有改动任何文件。')
        self._scan()
        return self._result(True, lines, self._state(), done='已还原上一次的配置文件备份。')

    # ---------- 启动握手 ----------
    @safe
    def ready(self):
        """前端确认自己活了；30 秒没收到就由 _boot_guard 自动收尾。"""
        BOOT_READY.set()
        return {'ok': True}

    # ---------- 首次使用注意事项 ----------
    @safe
    def notice_seen(self):
        """用户读过注意事项后写标记，之后启动不再弹。"""
        try:
            with open(NOTICE_FLAG, 'w', encoding='utf-8') as f:
                f.write('seen')
        except Exception as e:
            diag('notice flag failed: %r' % e)
        return {'ok': True}

    # ---------- 卸载 ----------
    @safe
    def uninstall(self):
        here = app_dir()
        # 只删工具本体与配套说明；.bak 备份、视频素材（acf-demo*/script.md）一律保留
        names = ['app.py', 'gui.html', 'gui-preview.html', 'clean_acf.py', 'build.py',
                 'run.bat', 'README.md', 'RELEASE.md', 'LICENSE', 'we_cleaner.py',
                 'we-cleaner.exe', 'we-cleaner.exe.sha256', 'app.ico', 'version.txt',
                 'we-cleaner.spec']
        exe_name = (os.path.basename(sys.executable)
                    if getattr(sys, 'frozen', False) else 'we-cleaner.exe')
        present = [n for n in names if os.path.isfile(os.path.join(here, n))]
        # 批处理写在工具目录、用 %~dp0 相对定位：内容全 ASCII，
        # 避免把中文路径写进 ascii 编码的 bat 导致 UnicodeEncodeError。
        bat = os.path.join(here, '_we_uninstall.bat')
        script = ['@echo off', 'cd /d "%~dp0"', 'set /a n=0', ':wait',
                  'set /a n+=1',
                  'del /f /q "%s" >nul 2>&1' % exe_name,
                  'if not exist "%s" goto removed' % exe_name,
                  'if %n% LSS 20 timeout /t 1 >nul',
                  'if %n% LSS 20 goto wait', ':removed']
        for n in present:
            if n != exe_name:
                script.append('del /f /q "%s" >nul 2>&1' % n)
        script.append('del /f /q "_we_uninstall.bat" >nul 2>&1')
        try:
            with open(bat, 'w', encoding='ascii', newline='\r\n') as f:
                f.write('\n'.join(script) + '\n')
            subprocess.Popen(['cmd', '/c', bat], creationflags=0x08000000)
            if self.window:
                def _close():
                    try:
                        self.window.destroy()
                    except Exception:
                        pass
                threading.Timer(1.5, _close).start()
            return {'ok': True,
                    'lines': [['正在卸载，窗口即将关闭。备份文件会保留。', 'tip']],
                    'state': self._state()}
        except Exception as e:
            return self._result(False, [['卸载失败：%s' % e, 'tip']], self._state(),
                                error='卸载失败：%s' % e)


def selftest():
    api = Api()
    st = api.refresh()['state']
    out = _REAL_STDOUT
    out.write('selftest: acf=%s\n' % (st['acf'] or 'NOT FOUND'))
    out.write('selftest: acf_ok=%s steam=%s cache=%s webview2=%s libs=%d\n' %
              (st['acf_ok'], st['steam'], st['cache'], st['webview2'], st['libs']))
    out.write('selftest: accounts=%s\n' %
              [(a['name'][:2] + '***', a['count'], a['tail']) for a in st['accounts']])
    for m in ['refresh', 'exit_steam', 'start_steam', 'clean', 'clear_cache', 'restore',
              'uninstall', 'notice_seen', 'ready']:
        assert callable(getattr(api, m)), m
    out.write('selftest: all 9 api methods present\n')
    out.write('selftest: OK\n')


def _arm_force_exit(delay=3):
    """用户点关闭后，若 WebView2 卡在 COM 清理，3 秒后强制结束进程。"""
    def force():
        time.sleep(delay)
        diag('WATCHDOG force exit (close stuck)')
        os._exit(0)

    threading.Thread(target=force, daemon=True).start()


def _working_set_bytes():
    """读本进程工作集，用于内存失控时自保。"""
    from ctypes import wintypes

    class PMC(ctypes.Structure):
        _fields_ = [('cb', wintypes.DWORD), ('PageFaultCount', wintypes.DWORD),
                    ('PeakWorkingSetSize', ctypes.c_size_t), ('WorkingSetSize', ctypes.c_size_t),
                    ('QuotaPeakPagedPoolUsage', ctypes.c_size_t), ('QuotaPagedPoolUsage', ctypes.c_size_t),
                    ('QuotaPeakNonPagedPoolUsage', ctypes.c_size_t), ('QuotaNonPagedPoolUsage', ctypes.c_size_t),
                    ('PagefileUsage', ctypes.c_size_t), ('PeakPagefileUsage', ctypes.c_size_t)]

    try:
        pmc = PMC()
        pmc.cb = ctypes.sizeof(PMC)
        k32 = ctypes.windll.kernel32
        fn = getattr(k32, 'K32GetProcessMemoryInfo', None) or ctypes.windll.psapi.GetProcessMemoryInfo
        fn.argtypes = [wintypes.HANDLE, ctypes.POINTER(PMC), wintypes.DWORD]
        fn.restype = wintypes.BOOL
        if fn(k32.GetCurrentProcess(), ctypes.byref(pmc), pmc.cb):
            return int(pmc.WorkingSetSize)
    except Exception:
        pass
    return 0


def cleanup_stale_mei():
    """onefile 每次启动解压到 %TEMP%\\_MEI*，被强退时不清会越堆越多。

    只删「自己上次记录过」的目录，绝不通配扫描，避免误伤别的 PyInstaller 程序。
    """
    if not getattr(sys, 'frozen', False):
        return
    cur = os.path.normcase(os.path.abspath(getattr(sys, '_MEIPASS', '')))
    old = []
    try:
        if os.path.isfile(MEI_LIST):
            with open(MEI_LIST, encoding='utf-8') as f:
                old = [x.strip() for x in f if x.strip()]
    except Exception:
        pass
    removed = 0
    for p in old:
        try:
            if os.path.normcase(os.path.abspath(p)) == cur or not os.path.isdir(p):
                continue
            shutil.rmtree(p, ignore_errors=True)
            if not os.path.exists(p):
                removed += 1
        except Exception:
            pass
    try:
        with open(MEI_LIST, 'w', encoding='utf-8') as f:
            f.write(cur + '\n')
    except Exception:
        pass
    if removed:
        diag('cleaned %d own _MEI dirs' % removed)


def _visible_hwnd():
    """找到本工具的可见主窗口；最小化时仍算可见，不会误判。"""
    try:
        u = ctypes.windll.user32
        u.FindWindowW.argtypes = [ctypes.c_wchar_p, ctypes.c_wchar_p]
        u.FindWindowW.restype = ctypes.c_void_p
        u.IsWindowVisible.argtypes = [ctypes.c_void_p]
        h = u.FindWindowW(None, APP_TITLE)
        return h if h and u.IsWindowVisible(h) else None
    except Exception:
        return None


def _on_closing():
    """点 X 立刻隐藏窗口：不等 WebView2 的 COM 清理，避免看起来像「关不掉/未响应」。"""
    _arm_force_exit(3)
    try:
        h = _visible_hwnd()
        if h:
            ctypes.windll.user32.ShowWindow(h, 0)      # SW_HIDE
    except Exception:
        pass
    return True


def acquire_single_instance():
    """小白双击没反应会一直双击，开出一堆进程吃内存。已有实例时只把它拉到前台。"""
    k32 = ctypes.windll.kernel32
    u = ctypes.windll.user32
    try:
        k32.CreateMutexW.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_wchar_p]
        k32.CreateMutexW.restype = ctypes.c_void_p
        handle = k32.CreateMutexW(None, False, 'WE-Cleaner-SingleInstance')
        if k32.GetLastError() == 183:      # ERROR_ALREADY_EXISTS
            h = u.FindWindowW(None, APP_TITLE)
            if h:
                u.ShowWindow(h, 9)         # SW_RESTORE
                u.SetForegroundWindow(h)
                return handle, True
            # 上个实例正在收尾、窗口已没了：若直接挡回，用户会以为「双击没反应」
            diag('existing instance has no window, allow new one')
        return handle, False
    except Exception as e:
        diag('single-instance check failed: %r' % e)
        return None, False


def _memory_guard():
    """独立于窗口、从启动第一秒就生效，不需要用户做任何操作。"""
    over = 0
    while True:
        time.sleep(1)
        ws = _working_set_bytes()
        if ws > 800 * 1024 ** 2:
            over += 1
            if over >= 3:
                diag('MEMORY GUARD force exit: %.0f MB' % (ws / 1024 ** 2))
                _note_abnormal_exit('内存占用异常')
                os._exit(0)
        else:
            over = 0


def _boot_guard():
    """只在「连窗口都没出现」时判定启动失败。

    不能用 JS 握手当唯一判据：js_api 注入慢一点、前端某步抛异常，
    界面明明已经正常可用，也会被误杀（曾把一次正常的清理操作打断）。
    窗口只要出现了，就说明页面加载成功，交给用户正常使用。
    """
    for _ in range(120):                   # 60 秒
        if BOOT_READY.is_set() or _visible_hwnd():
            return
        time.sleep(0.5)
    diag('BOOT TIMEOUT: no window appeared, force exit')
    _note_abnormal_exit('上次没启动成功')
    os._exit(0)


def _exit_watchdog():
    """窗口消失 4 秒后主循环仍在就退出。

    刻意不做「最小化太久自动关闭」：用户最小化工具去干别的很正常，
    十分钟后工具莫名其妙没了只会吓到人。内存失控由 _memory_guard 兜底。
    """
    for _ in range(60):                    # 最多等 30 秒让窗口出现
        if _visible_hwnd():
            break
        time.sleep(0.5)
    else:
        return
    missing = 0
    while True:
        time.sleep(1)
        if _visible_hwnd():
            missing = 0
        else:
            missing += 1
            if missing >= 4:               # 窗口不可见持续 4 秒
                diag('WATCHDOG force exit (window gone, loop stuck)')
                os._exit(0)


def main():
    diag('START app frozen=%s' % getattr(sys, 'frozen', False))
    cleanup_stale_mei()
    smoke = '--smoke' in sys.argv
    if not smoke:
        _mutex, running = acquire_single_instance()
        if running:
            diag('START aborted: activated existing instance')
            return
    if '--selftest' in sys.argv:
        selftest()
        return
    wv_ok, wv_ver = webview2_ok()
    diag('WebView2 ok=%s version=%s' % (wv_ok, wv_ver or '未知'))
    if not wv_ok:
        diag('STOP  no WebView2')
        alert('缺少 WebView2 运行库，界面无法显示。\n\n'
              '请到微软官网搜索「WebView2 Runtime 常青版」安装（约 2 MB），然后重新打开本工具。')
        return
    try:
        if wv_ver and int(wv_ver.split('.')[0]) < 100:
            alert('检测到 WebView2 版本较旧（%s），界面可能白屏或显示异常。\n\n'
                  '建议到微软官网安装最新的「WebView2 Runtime 常青版」后重试。\n\n'
                  '如果现在能正常显示，关掉这个提示继续用即可。' % wv_ver)
    except Exception:
        pass
    api = Api()
    try:
        with open(resource_path('gui.html'), encoding='utf-8') as f:
            html = f.read()
        # 首屏数据直接嵌进 HTML：不依赖 pywebview 的注入握手，窗口一出现就有内容。
        # 握手偶尔不触发，若靠 JS 主动调 refresh，界面会永远停在「正在检测…」＝看起来未响应。
        boot_obj = api.refresh()
        boot_obj['show_notice'] = not os.path.exists(NOTICE_FLAG)
        boot_obj['hint'] = _take_abnormal_hint() if not smoke else ''
        boot = json.dumps(boot_obj, ensure_ascii=False).replace('</', '<\\/')
        diag('BOOT steam=%s accounts=%d' %
             (boot_obj['state']['steam'], len(boot_obj['state']['accounts'])))
        inject = ('<script>window.__WE_NATIVE__=1;window.__WE_BOOT__=%s;</script>' % boot)
        html = html.replace('</head>', inject + '</head>', 1)
    except Exception as e:
        diag('BOOT inject failed: %r' % e)
        alert('界面文件缺失：%s' % e)
        return
    win_w, win_h = fit_window(800, 740)
    diag('WINDOW size %dx%d' % (win_w, win_h))
    window = webview.create_window(APP_TITLE, html=html, js_api=api,
                                   width=win_w, height=win_h, resizable=False)
    api.window = window
    window.events.closing += _on_closing
    # 页面加载完成由 pywebview 自己触发，比依赖 JS 调 api.ready() 可靠得多
    def _on_loaded():
        BOOT_READY.set()
        diag('PAGE loaded')
    window.events.loaded += _on_loaded
    threading.Thread(target=_memory_guard, daemon=True).start()
    threading.Thread(target=_exit_watchdog, daemon=True).start()
    if not smoke:
        threading.Thread(target=_boot_guard, daemon=True).start()
    diag('WINDOW created, entering loop')
    if smoke:
        # 无人值守验证打包产物：开窗 2 秒自动关，绕过 WebView2 偶发的 COM 清理卡死。
        def _smoke_close():
            time.sleep(2)
            diag('SMOKE closing')
            try:
                window.destroy()
            except Exception as e:
                diag('SMOKE destroy err %r' % e)
        webview.start(_smoke_close)
        diag('WINDOW closed (smoke)')
        os._exit(0)
    webview.start()
    diag('WINDOW closed')


if __name__ == '__main__':
    try:
        main()
    except Exception:
        # --windowed 下没有控制台，崩溃时把堆栈落到诊断日志，便于排查打包产物
        try:
            import traceback
            diag('FATAL\n' + traceback.format_exc())
        except Exception:
            pass
        raise
