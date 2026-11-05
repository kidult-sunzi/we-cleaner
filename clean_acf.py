#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Wallpaper Engine 多账号订阅清理 · 按 subscribedby 精准剔除

解决什么：一台电脑登过多个 Steam 账号，Steam 把别人订阅的壁纸也拉了下来。
做什么  ：只删 appworkshop_431960.acf 里「非主账号」的 WorkshopItemDetails 条目。
不做什么：不删壁纸文件、不改云端订阅列表、不联网、不改 Steam 程序文件。

推荐用法：双击 we-cleaner.exe（图形界面）；本文件也可独立命令行运行。
命令行  ：
    python clean_acf.py --list                     # 只看账号分组，不写文件
    python clean_acf.py --mine <账号ID> --apply    # 一步到位
    python clean_acf.py --restore                 # 从最近一次自动备份还原
    python clean_acf.py --help                     # 全部参数

前提：Steam 必须完全退出（含后台 steamwebhelper.exe），否则它退出时会把
      内存里的状态写回去，改动会被覆盖。
"""
import argparse
import collections
import ctypes
import datetime
import os
import re
import shutil
import subprocess
import sys

if hasattr(sys.stdout, 'reconfigure'):
    try:
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    except Exception:
        pass

STEAM_ID64_BASE = 76561197960265728
ACF_NAME = 'appworkshop_431960.acf'

# 匹配一个带 subscribedby 的条目块，连同缩进和行尾换行一起删除，不留空行
BLOCK = re.compile(
    r'[ \t]*"[0-9]+"\s*\{[^{}]*"subscribedby"\s*"([0-9]+)"[^{}]*\}[ \t]*\r?\n'
)
SUBSCRIBEDBY = re.compile(r'"subscribedby"\s*"([^"]+)"')


def mask(x):
    return x[:4] + '*' * (len(x) - 8) + x[-4:] if len(x) > 8 else '***'


# ---------- 找文件 ----------

def reg_steam_path():
    if os.name != 'nt':
        return None
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r'Software\Valve\Steam') as k:
            v, _ = winreg.QueryValueEx(k, 'SteamPath')
            return os.path.normpath(v.replace('/', '\\'))
    except Exception:
        return None


def find_acf():
    """从注册表、默认安装位置、各盘符、libraryfolders.vdf 里找出所有 acf。"""
    roots = []
    sp = reg_steam_path()
    if sp:
        roots.append(sp)
    for var in ('ProgramFiles', 'ProgramFiles(x86)'):
        p = os.environ.get(var)
        if p:
            roots.append(os.path.join(p, 'Steam'))
    for drive in 'CDEFGH':
        roots += [drive + ':\\Steam', drive + ':\\SteamLibrary']

    extra = []
    for r in list(roots):
        lf = os.path.join(r, 'steamapps', 'libraryfolders.vdf')
        if os.path.isfile(lf):
            try:
                t = open(lf, encoding='utf-8', errors='replace').read()
                for m in re.finditer(r'"path"\s*"([^"]+)"', t):
                    extra.append(os.path.normpath(m.group(1).replace('\\\\', '\\')))
            except OSError:
                pass
    roots += extra

    found = []
    for r in roots:
        p = os.path.normpath(os.path.join(r, 'steamapps', 'workshop', ACF_NAME))
        if os.path.isfile(p) and p.lower() not in [x.lower() for x in found]:
            found.append(p)
    return found


def account_meta():
    """从 Steam/userdata/<accountID>/config/localconfig.vdf 读昵称，帮你认出哪个是自己的账号。"""
    meta = {}
    sp = reg_steam_path()
    if not sp:
        return meta
    ud = os.path.join(sp, 'userdata')
    if not os.path.isdir(ud):
        return meta
    for d in os.listdir(ud):
        if not d.isdigit():
            continue
        f = os.path.join(ud, d, 'config', 'localconfig.vdf')
        if not os.path.isfile(f):
            continue
        try:
            t = open(f, encoding='utf-8', errors='replace').read()
            n = re.search(r'"PersonaName"\s*"([^"]*)"', t)
            meta[d] = (n.group(1) if n else '',
                       datetime.datetime.fromtimestamp(os.path.getmtime(f)).strftime('%Y-%m-%d'))
        except OSError:
            pass
    return meta


def choose_file():
    cands = find_acf()
    if not cands:
        print('没有自动找到 ' + ACF_NAME + '。请用 --file 手动指定完整路径。')
        return None
    if len(cands) == 1:
        return cands[0]
    print('找到多个 acf，请选择 Wallpaper Engine 实际所在的那个库：')
    for i, p in enumerate(cands, 1):
        print('  %d) %s' % (i, p))
    ans = input('输入序号（默认 1）: ').strip() or '1'
    try:
        return cands[int(ans) - 1]
    except (ValueError, IndexError):
        print('输入无效。')
        return None


# ---------- 读写与分析 ----------

def read_text(path):
    raw = open(path, 'rb').read()
    bom = raw.startswith(b'\xef\xbb\xbf')
    text = raw.decode('utf-8-sig' if bom else 'utf-8', errors='replace')
    newline = '\r\n' if b'\r\n' in raw[:4096] else '\n'
    return text, newline, bom


def _win_processes():
    """返回 {pid: 进程名小写}。

    直接走 Win32 进程快照，不启 tasklist：中文 Windows 下 tasklist 的输出会
    UnicodeDecodeError，而 --windowed 打包的 exe 没有控制台，子进程输出更不可靠。
    """
    from ctypes import wintypes
    k32 = ctypes.windll.kernel32

    class PROCESSENTRY32W(ctypes.Structure):
        _fields_ = [
            ('dwSize', wintypes.DWORD),
            ('cntUsage', wintypes.DWORD),
            ('th32ProcessID', wintypes.DWORD),
            ('th32DefaultHeapID', ctypes.c_size_t),
            ('th32ModuleID', wintypes.DWORD),
            ('cntThreads', wintypes.DWORD),
            ('th32ParentProcessID', wintypes.DWORD),
            ('pcPriClassBase', ctypes.c_long),
            ('dwFlags', wintypes.DWORD),
            ('szExeFile', ctypes.c_wchar * 260),
        ]

    k32.CreateToolhelp32Snapshot.argtypes = [wintypes.DWORD, wintypes.DWORD]
    k32.CreateToolhelp32Snapshot.restype = wintypes.HANDLE
    k32.Process32FirstW.argtypes = [wintypes.HANDLE, ctypes.POINTER(PROCESSENTRY32W)]
    k32.Process32FirstW.restype = wintypes.BOOL
    k32.Process32NextW.argtypes = [wintypes.HANDLE, ctypes.POINTER(PROCESSENTRY32W)]
    k32.Process32NextW.restype = wintypes.BOOL
    k32.CloseHandle.argtypes = [wintypes.HANDLE]

    snap = k32.CreateToolhelp32Snapshot(0x00000002, 0)   # TH32CS_SNAPPROCESS
    if not snap or snap == wintypes.HANDLE(-1).value:
        raise OSError('CreateToolhelp32Snapshot 失败')
    result = {}
    try:
        e = PROCESSENTRY32W()
        e.dwSize = ctypes.sizeof(e)
        ok = k32.Process32FirstW(snap, ctypes.byref(e))
        while ok:
            result[int(e.th32ProcessID)] = e.szExeFile.lower()
            ok = k32.Process32NextW(snap, ctypes.byref(e))
    finally:
        k32.CloseHandle(snap)
    return result


def steam_pids():
    """属于 Steam 主程序 / 辅助进程的 PID 集合。"""
    names = _win_processes().items()
    return {pid for pid, n in names if n in ('steam.exe', 'steamwebhelper.exe')}


def steam_running():
    try:
        if os.name == 'nt':
            return bool(steam_pids())
        r = subprocess.run(['pgrep', '-f', 'steam'], capture_output=True, timeout=10)
        return r.returncode == 0
    except Exception:
        # 查询失败不能当成「没在运行」：否则 Steam 其实开着时会误放行写入，
        # 客户端退出时把内存状态写回，改动被悄悄覆盖。
        try:
            print('  [警告] 无法查询进程状态，为安全起见按「Steam 仍在运行」处理。')
        except Exception:
            pass
        return True


def close_steam_windows():
    """给 Steam 的顶层可见窗口发 WM_CLOSE，等价于用户点右上角 X。

    这是「正常退出」而不是 TerminateProcess：Steam 会保存状态、正常收尾。
    steam://exit 协议在部分机器上不生效时，这是最可靠的第二条路。
    """
    from ctypes import wintypes
    u = ctypes.windll.user32
    pids = steam_pids()
    visible, hidden = [], []
    PROC = ctypes.WINFUNCTYPE(ctypes.c_bool, wintypes.HWND, wintypes.LPARAM)

    def cb(hwnd, _):
        pid = wintypes.DWORD()
        u.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        if pid.value in pids:
            # Steam 最小化到托盘时主窗口不可见，所以要同时收集隐藏窗口
            (visible if u.IsWindowVisible(hwnd) else hidden).append(hwnd)
        return True

    try:
        u.EnumWindows(PROC(cb), 0)
    except Exception:
        return 0
    targets = visible or hidden
    for h in targets:
        try:
            u.PostMessageW(h, 0x0010, 0, 0)   # WM_CLOSE
        except Exception:
            pass
    return len(targets)


def analyse(text):
    matches = list(BLOCK.finditer(text))
    all_subs = SUBSCRIBEDBY.findall(text)
    groups = collections.defaultdict(list)
    for m in matches:
        item = re.search(r'"([0-9]+)"', m.group(0)).group(1)
        touched = re.search(r'"timetouched"\s*"([0-9]+)"', m.group(0))
        groups[m.group(1)].append((item, int(touched.group(1)) if touched else 0))
    return matches, all_subs, groups


def normalise_mine(value, groups):
    """支持序号、9 位 account ID、17 位 SteamID64。"""
    v = value.strip()
    if v.isdigit() and 1 <= int(v) <= len(groups):
        return sorted(groups, key=lambda a: -len(groups[a]))[int(v) - 1]
    if len(v) == 17 and v.isdigit():
        v = str(int(v) - STEAM_ID64_BASE)
    return v


def print_accounts(text, meta):
    matches, all_subs, groups = analyse(text)
    print('  带 subscribedby 的条目: %d   可安全匹配的整块: %d' % (len(all_subs), len(matches)))
    if len(matches) != len(all_subs):
        print('  [!] 两者不等，文件结构可能与预期不同，已停止以免误删。')
        return None
    print('\n  序号  subscribedby      条目  SteamID64          本机昵称        最近活跃')
    order = sorted(groups, key=lambda a: -len(groups[a]))
    for i, acc in enumerate(order, 1):
        name, when = meta.get(acc, ('', ''))
        try:
            sid = str(STEAM_ID64_BASE + int(acc))
        except ValueError:
            sid = '-'
        print('   %d   %-17s %3d  %-18s %-14s %s' %
              (i, acc, len(groups[acc]), sid, name[:12] or '-', when or '-'))
    print('\n  昵称来自本机 Steam\\userdata，供你认账号；脚本不会据此自动选主账号。')
    return matches, groups, order


def preview(groups, order, mine):
    others = {a: r for a, r in groups.items() if a != mine}
    total = sum(len(r) for r in others.values())
    print('\n  主账号: %s  →  保留 %d 条' % (mine, len(groups[mine])))
    for a, r in others.items():
        ids = ', '.join(x[0] for x in r)
        print('  将删除 %s 的 %d 条: %s' % (a, len(r), ids[:300] + (' ...' if len(ids) > 300 else '')))
    print('  合计删除 %d 条。' % total)
    return total


def apply_changes(path, text, newline, bom, mine, to_delete, ask):
    if steam_running():
        print('\n  [拒绝写入] 无法确认 Steam 已完全退出（检测到进程，或进程查询失败）。')
        print('  请完全退出 Steam（任务管理器确认后台也没有），再重试。')
        return False
    if ask:
        ans = input('\n  确认写入？输入 yes 继续: ').strip().lower()
        if ans != 'yes':
            print('  已取消，文件未改动。')
            return False

    removed = []

    def repl(m):
        if m.group(1) == mine:
            return m.group(0)
        removed.append(m.group(1))
        return ''

    new = BLOCK.sub(repl, text)
    # Steam 生成的 acf 顶层常多一个 '}'，只要求删除前后差值守恒
    if len(removed) != to_delete:
        print('  删除数不符（预期 %d / 实际 %d），已中止，文件未改动。' % (to_delete, len(removed)))
        return False
    if (new.count('{') - new.count('}')) != (text.count('{') - text.count('}')):
        print('  花括号结构变化，已中止，文件未改动。')
        return False
    left = SUBSCRIBEDBY.findall(new)
    if any(x != mine for x in left):
        print('  仍残留非主账号条目，已中止，文件未改动。')
        return False

    stamp = datetime.datetime.now().strftime('%Y%m%d-%H%M%S')
    backup = path + '.bak-' + stamp
    shutil.copy2(path, backup)
    with open(path, 'w', encoding='utf-8-sig' if bom else 'utf-8', newline='') as f:
        f.write(new.replace('\r\n', '\n').replace('\n', newline) if newline == '\r\n' else new)
    print('\n  已备份: %s' % backup)
    print('  已写入: %s' % path)
    print('  结果: 删除 %d 条，保留 %d 条；剩余 subscribedby 全部为 %s；结构校验通过。' %
          (len(removed), len(left), mine))
    print('\n  接下来：启动 Steam，看 Steam\\logs\\workshop_log.txt 有没有把条目加回来；')
    print('  想还原: python clean_acf.py --restore --file "%s"' % path)
    return True


def do_restore(path):
    d = os.path.dirname(path) or '.'
    base = os.path.basename(path)
    baks = sorted(f for f in os.listdir(d) if f.startswith(base + '.bak-'))
    if not baks:
        print('没有找到备份文件。')
        return False
    if steam_running():
        print('[拒绝还原] Steam 仍在运行，请先完全退出。')
        return False
    src = os.path.join(d, baks[-1])
    shutil.copy2(src, path)
    print('已从 %s 还原到 %s' % (src, path))
    return True


def main():
    ap = argparse.ArgumentParser(description='按 subscribedby 精准删除非主账号的 WE 订阅条目')
    ap.add_argument('--file', help='acf 完整路径（不填则自动探测）')
    ap.add_argument('--mine', help='主账号：序号 / 9 位 account ID / 17 位 SteamID64')
    ap.add_argument('--list', action='store_true', help='只列账号分组，不写文件')
    ap.add_argument('--apply', action='store_true', help='写入（默认只预览）')
    ap.add_argument('--yes', action='store_true', help='写入时跳过确认')
    ap.add_argument('--restore', action='store_true', help='从最近一次自动备份还原')
    args = ap.parse_args()

    print('=' * 66)
    print(' Wallpaper Engine 多账号订阅清理 · 按 subscribedby 精准剔除')
    print(' 不删壁纸文件 / 不改云端订阅 / 不联网；只改本地 acf')
    print('=' * 66)

    path = args.file
    if not path:
        path = choose_file()
    if not path or not os.path.isfile(path):
        if args.restore:
            print('请先用 --file 指定 acf 路径。')
        else:
            print('文件不存在: %s' % path)
        sys.exit(1)
    path = os.path.normpath(path)

    if args.restore:
        do_restore(path)
        return

    text, newline, bom = read_text(path)
    print('\n文件: %s  (%d 字节)' % (path, os.path.getsize(path)))
    result = print_accounts(text, account_meta())
    if result is None:
        sys.exit(1)
    matches, groups, order = result
    if not groups:
        print('没有带 subscribedby 的条目，无需处理。')
        return
    if args.list:
        print('\n[只读] 未改动任何文件。')
        return

    mine = normalise_mine(args.mine, groups) if args.mine else None
    if not mine:
        if not sys.stdin.isatty():
            print('\n[只读] 需要指定主账号：python clean_acf.py --mine <ID> [--apply]')
            return
        raw = input('\n哪个是你的主账号？输入上表序号 / 9 位 ID / 17 位 SteamID64: ').strip()
        if not raw:
            print('已取消。')
            return
        mine = normalise_mine(raw, groups)
    if mine not in groups:
        print('acf 里没有这个账号: %s' % mine)
        print('可选: %s' % ', '.join(order))
        sys.exit(1)

    to_delete = preview(groups, order, mine)
    if args.apply:
        apply_changes(path, text, newline, bom, mine, to_delete, ask=not args.yes)
    elif sys.stdin.isatty():
        ans = input('\n现在应用？（输入 yes 写入并自动备份，其它键仅结束）: ').strip().lower()
        if ans == 'yes':
            apply_changes(path, text, newline, bom, mine, to_delete, ask=False)
        else:
            print('[预览模式] 未改动任何文件。')
    else:
        print('\n[预览模式] 未改动任何文件。确认无误后加 --apply。')


if __name__ == '__main__':
    main()
