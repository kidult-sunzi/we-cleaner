# -*- coding: utf-8 -*-
"""
小红车清理工具 · 图形界面主程序（pywebview）

双击打开 → 点选自己的账号 → 点按钮。工具只改本地 acf；
431960 下载缓存由用户在资源管理器里自己删除，工具只负责打开文件夹。
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



def fit_window(want_w=800, want_h=740):
    """按屏幕工作区收缩窗口。

    固定 740 高在 1366×768 笔记本、或 150% 缩放的 1080p 上会超出屏幕，
    底部那排按钮（清缓存/还原）点不到。
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
        # 必须以下划线开头：pywebview 生成前端接口时会 dir(js_api) 并递归遍历
        # 所有非下划线属性。若把 Window 对象挂在公开属性上，后台线程 getattr
        # 窗口属性会要求切回 UI 线程，与 create_window 互等 → 整个界面死锁未响应。
        self._window = None
        self.acf = None
        self.groups = {}
        self.order = []
        self.meta = {}
        self.cache_targets = []
        self._cache_size = 0
        self._libs = 0
        self.overview = {'ok': False}
        self.orphans = []

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
            # 刻意不碰 state_431960_431960_*.patch：那是 Steam 的下载状态记录，
            # 订阅记录还在时删掉它们可能让 Steam 重新校验、重新下载。
            # 这些文件一共才几 KB，删了也没有任何收益。
        # 遍历缓存目录 + 全盘找库都很慢，只在扫描时算一次，别让每次点按钮都重来
        self._cache_size = sum(size_of(p) for p in self.cache_targets)
        self._libs = len(found) if found else 0

        # 每账号订阅清单（userdata）：纯读、不写、失败就静默降级成空
        try:
            self.overview = core.read_user_subscriptions(self.acf, self.groups)
        except Exception:
            self.overview = {'ok': False}

        # 孤儿目录（磁盘有、acf 没有）：纯读，实测只花 6 毫秒，开机就算
        try:
            self.orphans = core.find_orphans(self.acf)
        except Exception:
            self.orphans = []
        return self

    @staticmethod
    def _tail(a):
        return a[-4:] if len(a) >= 4 else '****'

    def _current_account_id(self):
        """当前登录账号（accountid）。认不出返回 None，绝不猜。

        只信 read_user_subscriptions() 交叉核对过的结果：它要求
        loginusers.vdf 的 MostRecent 号确实存在于 userdata 账号目录，
        否则 known=False。界面与后端共用这一个判断，别另起一套。
        """
        ov = self.overview or {}
        if not ov.get('ok') or not ov.get('known'):
            return None
        for a in ov.get('accounts', []):
            if a.get('mine'):
                return str(a['id'])
        return None

    def _state(self):
        accounts = []
        cur = self._current_account_id()
        for a in self.order:
            name, when = self.meta.get(a, ('', ''))
            accounts.append({
                'name': name or ('账号 ' + self._tail(a)),
                'count': len(self.groups[a]),
                'last': when or '未知',
                'tail': self._tail(a),
                'mine': bool(cur and a == cur),
            })
        cur_name = ''
        if cur:
            cur_name = self.meta.get(cur, ('', ''))[0] or ('账号尾号 ' + self._tail(cur))
        cache = self._cache_size
        return {
            'acf': self.acf or '',
            'acf_ok': bool(self.acf),
            'steam': 'running' if core.steam_running() else 'stopped',
            'cache': human(cache) if cache else '0 GB（已清理）',
            'accounts': accounts,
            'known': bool(cur),
            'current_in_list': bool(cur and cur in self.groups),
            'current_name': cur_name,
            'webview2': webview2_ok(),
            'libs': self._libs,
            'overview': self.overview,
            'orphans': {
                'count': len(self.orphans),
                'size': human(sum(o['size'] for o in self.orphans)) if self.orphans else '',
                'items': [{'id': o['id'], 'size': human(o['size'])} for o in self.orphans],
            },
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
            lines.append(['配置文件里有 %d 个账号的订阅记录，共 %d 条' %
                          (len(state['accounts']), sum(a['count'] for a in state['accounts'])), ''])
        else:
            lines.append(['没找到 appworkshop_431960.acf，请确认已安装 Wallpaper Engine', 'tip'])
        if not state['webview2']:
            lines.append(['警告：本机缺少 WebView2 运行库，界面可能无法显示', 'tip'])
        if state['libs'] > 1:
            lines.append(['检测到多个游戏库，当前只处理第一个', 'tip'])
        ov = state.get('overview') or {}
        if ov.get('ok') and ov.get('known') and ov.get('others'):
            lines.append(['这台电脑登过 %d 个 Steam 账号，其中 %d 个不是你的，'
                          '累计订过 %d 张壁纸' % (ov['logged'], ov['others'], ov['other_sum']), 'tip'])
        if ov.get('ok') and ov.get('other_in_acf'):
            lines.append(['⚠ 还有 %d 条别人的订阅记录留在配置里（配置被还原成旧版本、'
                          '或那个账号再登录一次，这些壁纸会被整批下回来）'
                          % ov['other_in_acf'], 'warn'])
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

        # 认得出「最近登录的账号」也绝不替用户决定保留谁（约定 3.7）。
        # 那条信息只用于界面展示和确认框提醒，后端不拦截、不改写用户的选择。

        # 先读文件确认「工具能认全」，再动 Steam。
        # 以前这道检查在写盘前最后一步，失败时用户的 Steam 已经被关掉了，
        # 却只收到一句看不懂的「残留别的账号的条目」。见约定文档 3.6。
        try:
            text, nl, bom = core.read_text(self.acf)
        except OSError:
            return self._result(False, [['配置文件读取失败', 'warn']], self._state(),
                                error='配置文件读不出来，已停止。\n\n没有任何文件被改动。')
        bad = core.unmatched_details(text, mine=mine)
        if bad:
            # 运行日志要能当"诊断报告"截图发人：写清楚几条、长什么样、可能是什么原因。
            # 片段已由 core 打码，不含原样账号 ID。
            lines.append(['配置里有 %d 条记录工具读不懂，已停止' % len(bad), 'warn'])
            lines.append(['下面是它们的写法（数字已打码），把这一屏截图发给开发者就能定位：', 'dim'])
            for i, (_, frag) in enumerate(bad[:6], 1):
                lines.append(['  第 %d 条：%s' % (i, frag), 'dim'])
            if len(bad) > 6:
                lines.append(['  ……还有 %d 条，写法类似' % (len(bad) - 6), 'dim'])
            lines.append(['常见原因：记录里多了一层小括号 / 文件末尾少了换行 / 一格写了多个账号。', 'dim'])
            lines.append(['没有改动任何文件，Steam 也没有被关闭。', 'dim'])
            return self._result(False, lines, self._state(),
                                error=core.unknown_shape_message(len(bad), self.acf))
        if not self._exit_steam(lines):
            lines += LOG.drain()
            return self._result(False, lines, self._state(),
                                error=('没能自动退出 Steam。\n请在 Steam 窗口右上角点 X，'
                                       '或托盘图标右键 → 退出，然后重试。\n\n没有改动任何文件。'))
        _, _, g = core.analyse(text)
        n = sum(len(r) for a, r in g.items() if a != mine)
        keep = len(g.get(mine, []))
        if n == 0:
            lines.append(['没有别的账号记录，已经是干净的', 'ok'])
            return self._result(True, lines, self._state(), done='没有别的账号记录，不用清理。')
        lines.append(['将删除其他账号 %d 条，保留你的 %d 条' % (n, keep), 'tip'])
        try:
            ok = core.apply_changes(self.acf, text, nl, bom, mine, n, ask=False)
        except core.WriteRefused as e:
            # 拒写必须原样告诉用户，不能糊成"校验没通过"，更不能当成功。
            # 以前日志只留第一行，用户截图帮不上忙；现在整段原因都进运行日志。
            lines += LOG.drain()
            for ln in e.msg.split('\n'):
                if ln.strip():
                    lines.append([ln, 'warn'])
            return self._result(False, lines, self._state(), error=e.msg)
        lines += LOG.drain()
        if ok:
            self._scan()
            res = self._result(
                True, lines, self._state(),
                done='清理完成：删除 %d 条，保留 %d 条。\n备份已保存在配置文件旁边。' % (n, keep))
            # 前端见到 rules 就弹「清理后要注意什么」，而不是普通完成框
            res['rules'] = True
            return res
        return self._result(False, lines, self._state(),
                            error='已取消，文件没有改动。')

    # ---------- 打开缓存文件夹（由用户自己删） ----------
    @safe
    def open_cache_folder(self):
        """打开下载缓存所在目录并选中 431960 文件夹，删除交给用户手动完成。

        360 的反勒索／文档保护规则盯的是「陌生进程删图片类文件」——缓存里
        159 个文件有 106 个是 jpg/mp4/gif。换任何删除接口都绕不开：实测
        SHFileOperationW 与系统外壳的 delete verb 都会被弹窗询问。
        所以工具不再删除任何缓存文件，只把文件夹打开；删除由资源管理器
        发起，用户看得见、也不会被安全软件拦。
        """
        LOG.clear()
        lines = []
        steamapps = os.path.dirname(os.path.dirname(self.acf)) if self.acf else None
        dl = os.path.join(steamapps, 'workshop', 'downloads') if steamapps else None
        folder = os.path.join(dl, '431960') if dl else None
        if not dl or not os.path.isdir(dl):
            return self._result(False, [['没找到下载缓存所在的文件夹', 'tip']],
                                self._state(),
                                error='没找到下载缓存目录，请检查 Steam 库路径。')
        target = folder if os.path.isdir(folder) else dl
        opened = False
        try:
            # /select, 会打开父目录并选中该文件夹，用户直接按 Delete 即可
            subprocess.Popen(['explorer.exe', '/select,' + os.path.normpath(target)])
            opened = True
        except Exception:
            try:
                os.startfile(dl)
                opened = True
            except Exception as e:
                diag('OPEN_FOLDER failed: %r' % e)
        if not opened:
            return self._result(False, [['打开文件夹失败', 'tip']], self._state(),
                                error=('没能打开文件夹。请自己到 Steam 库的 '
                                       'workshop\\downloads 里删除 431960。'))
        if os.path.isdir(folder):
            lines.append(['已打开文件夹并选中 431960，按 Delete 删掉它即可', 'ok'])
            lines.append(['只删 431960 这个文件夹；旁边的配置文件和 state_*.patch 不要动', 'tip'])
        else:
            lines.append(['已打开 downloads 文件夹，目前没有 431960 下载缓存', 'ok'])
        lines += LOG.drain()
        # 不返回 done：打开文件夹就是终点，不再弹「完成」窗口
        return self._result(True, lines, self._state())

    def cache_status(self):
        """前端轮询用：只重算 431960 缓存大小，不碰 acf、不写日志、不弹窗。

        删除是在资源管理器里由用户手动完成的，工具感知不到那一刻，
        所以点「点击前往」之后由前端每隔两秒问一次，删完即更新界面。
        """
        steamapps = os.path.dirname(os.path.dirname(self.acf)) if self.acf else None
        dl = os.path.join(steamapps, 'workshop', 'downloads') if steamapps else None
        folder = os.path.join(dl, '431960') if dl else None
        self.cache_targets = [folder] if folder and os.path.isdir(folder) else []
        self._cache_size = sum(size_of(p) for p in self.cache_targets)
        return {'cache': human(self._cache_size) if self._cache_size
                else '0 GB（已清理）'}

    # ---------- 孤儿目录（只打开，绝不代删） ----------
    @safe
    def open_orphan(self, idx):
        """打开某个孤儿目录并在资源管理器里选中它，删除交给用户按 Delete。

        和下载缓存同理：孤儿里装的也是 jpg/mp4，360 反勒索按"哪个进程在删
        图片"判定，程序代删必被弹窗。所以这里只打开，不删。
        实验 001（2026-11-07）已实证：这类目录 Steam 不认识，删了不会重下。
        """
        LOG.clear()
        lines = []
        try:
            i = int(idx)
        except (TypeError, ValueError):
            i = 0
        if not self.orphans:
            return self._result(False, [['没有发现无主残留', 'ok']], self._state(),
                                error='现在没有可清理的无主残留。')
        if i < 1 or i > len(self.orphans):
            return self._result(False, [['编号超出范围', 'tip']], self._state(),
                                error='请重新点一次「前往删除」。')
        o = self.orphans[i - 1]
        path = o['path']
        if not os.path.isdir(path):
            self._scan()
            return self._result(False, [['这个目录已经不在磁盘上了', 'ok']], self._state(),
                                error='这个目录已经不在了，界面已按最新状态刷新。')
        opened = False
        try:
            subprocess.Popen(['explorer.exe', '/select,' + os.path.normpath(path)])
            opened = True
        except Exception:
            try:
                os.startfile(path)
                opened = True
            except Exception as e:
                diag('OPEN_ORPHAN failed: %r' % e)
        if not opened:
            return self._result(
                False, [['打开文件夹失败', 'tip']], self._state(),
                error=('没能打开文件夹。请自己到 Steam 库的 '
                       'workshop\\content\\431960 里删掉 %s。' % o['id']))
        lines.append(['已打开并选中 %s，按 Delete 删掉它即可' % o['id'], 'ok'])
        lines.append(['这个目录 Steam 完全不认识，删了不会重新下载', 'tip'])
        lines += LOG.drain()
        return self._result(True, lines, self._state())

    def orphans_status(self):
        """前端轮询用：只重算孤儿列表，不写日志、不弹窗。

        删除是用户在资源管理器里手动完成的，工具感知不到那一刻，
        所以点完之后由前端定时问一次，删完即更新界面。
        """
        try:
            self.orphans = core.find_orphans(self.acf)
        except Exception:
            pass
        total = sum(o['size'] for o in self.orphans)
        return {'count': len(self.orphans),
                'size': human(total) if total else '',
                'items': [{'id': o['id'], 'size': human(o['size'])} for o in self.orphans]}

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
                                error='还原没有成功，具体原因写在下面的运行日志里。\n\n没有改动任何文件。')
        self._scan()
        return self._result(True, lines, self._state(), done='已还原上一次的配置文件备份。')

    # ---------- 启动握手 ----------
    @safe
    def ready(self):
        """前端真正握上手才调到这里；成功后界面才放行按钮。"""
        BOOT_READY.set()
        diag('HANDSHAKE ok, buttons enabled')
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

def selftest():
    api = Api()
    st = api.refresh()['state']
    out = _REAL_STDOUT
    out.write('selftest: acf=%s\n' % (st['acf'] or 'NOT FOUND'))
    out.write('selftest: acf_ok=%s steam=%s cache=%s webview2=%s libs=%d\n' %
              (st['acf_ok'], st['steam'], st['cache'], st['webview2'], st['libs']))
    out.write('selftest: accounts=%s\n' %
              [(a['name'][:2] + '***', a['count'], a['tail']) for a in st['accounts']])
    ov = st.get('overview') or {}
    out.write('selftest: overview ok=%s 登过=%s 别人的号=%s 累计=%s 配置里还剩=%s\n' %
              (ov.get('ok'), ov.get('logged'), ov.get('others'),
               ov.get('other_sum'), ov.get('other_in_acf')))
    orp = st.get('orphans') or {}
    out.write('selftest: orphans count=%s size=%s ids=%s\n' %
              (orp.get('count'), orp.get('size'),
               [i['id'] for i in (orp.get('items') or [])]))
    methods = ['refresh', 'exit_steam', 'start_steam', 'clean', 'open_cache_folder',
               'cache_status', 'open_orphan', 'orphans_status',
               'restore', 'notice_seen', 'ready']
    for m in methods:
        assert callable(getattr(api, m)), m
    out.write('selftest: api 方法齐全（%d 个）\n' % len(methods))
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


def _rmtree_force(path):
    """删目录，遇到只读/被占用时去掉只读再试一次。不同 Python 版本回调名不同。"""
    import stat as _stat

    def _onexc(func, p, exc):
        try:
            os.chmod(p, _stat.S_IWRITE)
            func(p)
        except Exception:
            pass

    try:
        shutil.rmtree(path, onexc=_onexc)
    except TypeError:
        shutil.rmtree(path, onerror=lambda f, p, e: _onexc(f, p, e))


def cleanup_stale_mei():
    """onefile 每次启动解压到 %TEMP%\\_MEI*，被强退时不清会越堆越多。

    2026-11-07 改（原先有 bug，实测积了 26 个目录 / 0.42 GB）：
      原实现每次启动把清单**覆盖**成"当前这一个"路径，只记得上一次；
      而且删除失败被 `ignore_errors=True` 全部吞掉。
      于是只要有一次删不掉（比如 WebView2 子进程还占着其中的 DLL），
      那个目录就永远不会再被想起，越积越多。

    现在的做法：
      - 清单**累积**，最多保留 40 条
      - 删不掉的**留在清单里**，下次启动再试
      - 删之前先清只读属性（_rmtree_force）
      - 失败写 diag，便于以后排查
    仍然只动清单里记过的路径，绝不通配扫描，避免误伤别的 PyInstaller 程序。
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

    keep = []
    removed = 0
    for p in old:
        try:
            if os.path.normcase(os.path.abspath(p)) == cur or not os.path.isdir(p):
                continue
            _rmtree_force(p)
        except Exception as e:
            diag('cleanup _MEI failed: %r (%r)' % (p, e))
        if os.path.exists(p):
            keep.append(p)      # 这次没删掉，留着下回再试
        else:
            removed += 1

    keep.append(cur)
    try:
        with open(MEI_LIST, 'w', encoding='utf-8') as f:
            f.write('\n'.join(keep[-40:]) + '\n')
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
    api._window = window
    window.events.closing += _on_closing
    # 页面加载完成由 pywebview 自己触发，比依赖 JS 调 api.ready() 可靠得多。
    # 注意：这里只记「页面加载了」，不负责放行按钮。按钮是否可用由前端
    # 真正握手成功（api.ready() 返回）决定，避免页面事件没触发就卡在灰按钮状态。
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
