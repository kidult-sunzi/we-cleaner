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


def find_userdata_dirs():
    """找出所有可能的 Steam/userdata 目录（只读，不会新建任何东西）。

    注意：userdata 在 Steam **安装目录**里，不在游戏库目录里。
    WE 装在 D:\\SteamLibrary 时，acf 在 D 盘但 userdata 还在 C 盘，所以不能从 acf 推。
    """
    cands = []
    sp = reg_steam_path()
    if sp:
        cands.append(os.path.join(sp, 'userdata'))
    for var in ('ProgramFiles', 'ProgramFiles(x86)'):
        p = os.environ.get(var)
        if p:
            cands.append(os.path.join(p, 'Steam', 'userdata'))
    for drive in 'CDEFGH':
        cands.append(drive + ':\\Steam\\userdata')

    out = []
    for c in cands:
        c = os.path.normpath(c)
        if os.path.isdir(c) and c.lower() not in [x.lower() for x in out]:
            out.append(c)
    return out


def current_account():
    """当前登录的 accountid。来源 config/loginusers.vdf 的 MostRecent 标记。

    读不到就返回 None —— 绝不能猜，猜错了界面会把别人的号标成"你自己"。
    """
    roots = []
    sp = reg_steam_path()
    if sp:
        roots.append(sp)
    for var in ('ProgramFiles', 'ProgramFiles(x86)'):
        p = os.environ.get(var)
        if p:
            roots.append(os.path.join(p, 'Steam'))

    for r in roots:
        f = os.path.join(r, 'config', 'loginusers.vdf')
        if not os.path.isfile(f):
            continue
        try:
            t = open(f, encoding='utf-8', errors='replace').read()
        except OSError:
            continue
        # 按 "\n\t"<steamid64>"\n\t{" 切开，每两段是一组
        parts = re.split(r'\n\t"(7656\d{13})"\s*\n?\t*\{', t)
        ids = parts[1::2]
        bodies = parts[2::2]
        for sid, body in zip(ids, bodies):
            if re.search(r'"MostRecent"\s*"1"', body):
                try:
                    return str(int(sid) - 76561197960265728)
                except ValueError:
                    return None
        if len(ids) == 1:
            try:
                return str(int(ids[0]) - 76561197960265728)
            except ValueError:
                return None
    return None


def read_user_subscriptions(acf_path, groups=None):
    """读 userdata 下每个账号自己的壁纸订阅清单，并和 acf/硬盘交叉核对。

    数据源：<Steam>/userdata/<accountid>/ugc/431960_subscriptions.vdf
    为什么需要它：acf 会被 Steam 重写，历史账号的条目会被清掉；
    这份文件是按账号分目录存的，能看出"这台电脑到底有几个号订过壁纸"。
    详见 _notes/约定与实现规则.md 2.6。

    全程只读。任何一步失败都只是让结果变少，绝不抛异常、绝不写文件。
    """
    groups = groups or {}
    owner = {}
    for acc, items in groups.items():
        for it in items:
            owner[str(it[0])] = str(acc)

    mine = current_account()

    # 硬盘上真实存在的内容目录
    dirs = set()
    try:
        steamapps = os.path.dirname(os.path.dirname(os.path.abspath(acf_path)))
        cdir = os.path.join(steamapps, 'workshop', 'content', '431960')
        if os.path.isdir(cdir):
            dirs = set(d for d in os.listdir(cdir) if d.isdigit())
    except (OSError, TypeError):
        pass

    meta = account_meta()
    accounts = []
    seen = set()
    for ud in find_userdata_dirs():
        try:
            names = sorted(os.listdir(ud))
        except OSError:
            continue
        for name in names:
            if not name.isdigit() or name in seen:
                continue
            seen.add(name)
            f = os.path.join(ud, name, 'ugc', '431960_subscriptions.vdf')
            ids, last = set(), ''
            if os.path.isfile(f):
                try:
                    t = open(f, encoding='utf-8', errors='replace').read()
                    ids = set(re.findall(r'"publishedfileid"\s*"(\d+)"', t))
                    m = re.search(r'"time_last_updated"\s*"(\d+)"', t)
                    if m:
                        ts = int(m.group(1))
                        if ts > 0:
                            last = datetime.datetime.fromtimestamp(ts).strftime('%Y-%m-%d')
                except (OSError, ValueError):
                    pass
            accounts.append({
                'id': name,
                'name': meta.get(name, ('', ''))[0] or ('账号 ' + name[-4:]),
                'subs': len(ids),
                'last': last,
                'in_acf': len(ids & set(owner)),
                'on_disk': len(ids & dirs),
                '_ids': ids,
            })

    # 没有登录记录时，退一步认为"订阅清单最近更新"的那个是当前账号；
    # 仍然判断不出就整体标为"未知"，界面不会把任何人误标成"你自己"
    if mine not in [a['id'] for a in accounts]:
        mine = None

    others = [a for a in accounts if a['id'] != mine] if mine else []
    other_ids = set()
    for a in others:
        other_ids |= a['_ids']

    for a in accounts:
        a['mine'] = (a['id'] == mine)
        a.pop('_ids', None)

    accounts.sort(key=lambda x: (not x['mine'], -x['subs']))

    return {
        'ok': bool(accounts),
        'known': bool(mine),
        'logged': len(accounts),
        'subbed': len([a for a in accounts if a['subs'] > 0]),
        # others 只数"别的号里真的订过壁纸的"，没订过的号不计入，
        # 否则界面会说出"5 个号订过"这种吓人的错话
        'others': len([a for a in others if a['subs'] > 0]) if mine else 0,
        'other_sum': len(other_ids),
        'other_on_disk': len(other_ids & dirs),
        'other_in_acf': len(other_ids & set(owner)),
        'on_disk_total': len(dirs),
        'accounts': accounts,
    }


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


def unmatched_subscriptions(text):
    """找出「全文里存在、但 BLOCK 正则覆盖不到」的 subscribedby 值。

    背景（2026-11-07 真实用户故障）：分析和删除用的是 BLOCK，它假设条目
      键是纯数字 / 块内无嵌套花括号 / subscribedby 值纯数字 / 块尾有换行。
    但最后一道校验用的是 SUBSCRIBEDBY.findall(new)，全文扫、条件宽松。
    只要文件里有一条不符合上述假设（哪怕完全合法），它就删不掉、却会被
    校验扫到，于是抛 residue「残留别的账号的条目」——用户完全不知道为什么。

    返回漏网的值列表；空列表 = 工具把文件认全了。
    """
    covered = [m.span() for m in BLOCK.finditer(text)]
    return [m.group(1) for m in SUBSCRIBEDBY.finditer(text)
            if not any(a <= m.start() < b for a, b in covered)]


def unmatched_details(text, mine=None):
    """给「工具读不懂的记录」生成可截图的脱敏片段，专供运行日志。

    只取账号字段所在行及前一行，压成一行显示；4 位以上数字串打码，
    但保留引号、花括号、逗号、换行等结构，开发者一眼能看出写法差在哪。
    全程只读，绝不把原样账号 ID 输出到界面。
    """
    covered = [m.span() for m in BLOCK.finditer(text)]
    out = []
    for m in SUBSCRIBEDBY.finditer(text):
        if any(a <= m.start() < b for a, b in covered):
            continue
        val = m.group(1)
        if mine is not None and val == mine:
            continue
        ls = text.rfind('\n', 0, m.start()) + 1
        nl = text.find('\n', m.end())
        le = len(text) if nl < 0 else nl
        prev = text.rfind('\n', 0, max(0, ls - 1))
        frag = text[prev + 1:le] if prev >= 0 else text[ls:le]
        frag = re.sub(r'\s+', ' ', frag).strip()
        frag = re.sub(r'\d{4,}', lambda x: x.group(0)[:2] + '…' + x.group(0)[-2:], frag)
        # 「文件末尾没换行」光看片段看不出来，直接标给人看
        if nl < 0 and not text.endswith('\n'):
            frag += '  ← 文件到这里就结束了，末尾没有换行'
        out.append((val, frag[:200]))
    return out


def unknown_shape_message(n, path=''):
    """给小白看的人话：卡在哪 → 可能原因 → 你要做什么（铁律 4）。"""
    return ('这个文件里有 %d 条订阅记录的写法，和工具见过的都不一样。\n'
            '工具读不懂它们，硬清理可能清不干净，所以停下来了。\n\n'
            '这不是你操作错了，多半是 Steam 版本不同、记录格式变了。\n\n'
            '请这样做：把主界面「运行日志」里这几行截图发给工具开发者，\n'
            '或者直接把下面这个文件发过来，适配之后就能正常清理。\n'
            '%s\n\n'
            'Steam 和所有文件都没有被改动。'
            % (n, path or '（配置文件路径见主界面）'))


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


class WriteRefused(Exception):
    """拒绝写入。带上人话原因，让界面能原样显示，不要笼统说"校验失败"。

    这条是为 P0 修的：以前 apply_changes 只是 return False，上层分不清
    "Steam 还在跑所以没写"和"结构校验没过"，于是界面提示对不上真实原因。
    """

    def __init__(self, code, msg):
        super().__init__(msg)
        self.code = code
        self.msg = msg


def parse_acf(text):
    """严格解析 KeyValues（acf/vdf）。结构不合法就抛 ValueError。

    取代原来的"花括号差值守恒"校验——那种写法只比较差值，原始文件本身
    不平衡（比如你 11/6 那个多一个 `}` 的）反而能通过，等于没校验。
    现在要求：整个文件必须能被完整解析，且解析完不能剩多余 token。
    """
    toks = re.findall(r'"([^"]*)"|([{}])', text)
    if not toks or toks[0][1]:
        raise ValueError('文件开头不是键名')

    pos = 0

    def block():
        nonlocal pos
        d = {}
        while pos < len(toks):
            k, v = toks[pos]
            if v == '}':
                pos += 1
                return d
            if v == '{':
                raise ValueError('出现没有键名的裸花括号块')
            pos += 1
            if pos < len(toks) and toks[pos][1] == '{':
                pos += 1
                d[k] = block()
            elif pos < len(toks):
                d[k] = toks[pos][0]
                pos += 1
            else:
                raise ValueError('键 %r 之后文件意外结束' % k)
        raise ValueError('右花括号数量不足，文件被截断')

    pos = 1
    if pos >= len(toks) or toks[pos][1] != '{':
        raise ValueError('根键后面没有紧跟 {')
    pos += 1
    root = {toks[0][0]: block()}
    if pos != len(toks):
        raise ValueError('解析结束后还剩 %d 个符号，说明有多余的 }' % (len(toks) - pos))
    if len(root) != 1:
        raise ValueError('顶层键不是唯一的')
    return root


def acf_item_ids(root):
    """从解析结果里取出"已装/已订阅"的工坊条目 ID 集合。"""
    aw = root.get('AppWorkshop') or {}
    ids = set()
    for sec in ('WorkshopItemsInstalled', 'WorkshopItemDetails'):
        blk = aw.get(sec)
        if isinstance(blk, dict):
            ids |= set(k for k in blk if str(k).isdigit())
    return ids


def section_ids(root, section):
    """取某个区块下的纯数字条目 ID。区块不存在时返回空集合。"""
    aw = root.get('AppWorkshop') or {}
    blk = aw.get(section)
    if not isinstance(blk, dict):
        return set()
    return set(str(k) for k in blk if str(k).isdigit())


def dir_size(path):
    """递归统计目录大小。跳过符号链接，权限不足的条目直接略过。"""
    total = 0
    try:
        with os.scandir(path) as it:
            for e in it:
                try:
                    if e.is_symlink():
                        continue
                    if e.is_dir(follow_symlinks=False):
                        total += dir_size(e.path)
                    elif e.is_file(follow_symlinks=False):
                        total += e.stat(follow_symlinks=False).st_size
                except OSError:
                    continue
    except OSError:
        pass
    return total


def find_orphans(acf_path):
    """找出"磁盘上有目录、acf 里完全没有记录"的工坊内容（孤儿）。

    判据（约定文档第四节 L2）：
        content\\431960\\<id> 存在，且 id 既不在 WorkshopItemsInstalled
        也不在 WorkshopItemDetails 里 → Steam 不认识它，删了不会重下。

    2026-11-07 实验 001 已实证：这类目录 Steam 不碰、不重下、不留状态。

    两条硬约束：
      1. 只读。本函数绝不删除任何东西——删由用户在资源管理器里自己按 Delete
         （360 反勒索按"哪个进程在删图片"判定，程序删必被拦）
      2. acf 读不出/解析失败/条目为空 → 一律返回空列表。
         「读不懂」绝不能变成「全都是垃圾」（约定 3.5）
    """
    if not acf_path or not os.path.isfile(acf_path):
        return []
    try:
        text, _, _ = read_text(acf_path)
        root = parse_acf(text)
    except (ValueError, OSError):
        return []

    known = acf_item_ids(root)
    if not known:
        return []

    try:
        steamapps = os.path.dirname(os.path.dirname(os.path.abspath(acf_path)))
        cdir = os.path.join(steamapps, 'workshop', 'content', '431960')
        names = os.listdir(cdir)
    except OSError:
        return []

    out = []
    for name in names:
        if not name.isdigit():          # 跳过 _temp 之类的临时目录
            continue
        full = os.path.join(cdir, name)
        if not os.path.isdir(full) or name in known:
            continue
        out.append({'id': name, 'path': full, 'size': dir_size(full)})
    out.sort(key=lambda x: -x['size'])
    return out


def find_backups(acf_path):
    """只读列出 acf 同目录里工具留下的旧备份，按大小降序（约定 3.9）。

    只认 `<acf名>.bak-` 与 `<acf名>.before-restore-` 两种前缀，
    绝不碰 acf 本体、state_*.patch 或任何别的文件。
    这些备份内容里含订阅过的账号 ID，属于隐私痕迹，用户有权看见并清掉；
    但程序绝不代删——只把文件夹打开，由用户在资源管理器里按 Delete。
    """
    if not acf_path:
        return []
    d = os.path.dirname(os.path.abspath(acf_path))
    base = os.path.basename(acf_path)
    prefixes = (base + '.bak-', base + '.before-restore-')
    out = []
    try:
        names = os.listdir(d)
    except OSError:
        return []
    for n in names:
        if not n.startswith(prefixes):
            continue
        p = os.path.join(d, n)
        try:
            if not os.path.isfile(p):
                continue
            size = os.path.getsize(p)
            when = datetime.datetime.fromtimestamp(os.path.getmtime(p)).strftime('%Y-%m-%d')
        except OSError:
            continue
        out.append({'name': n, 'path': p, 'size': size, 'date': when})
    out.sort(key=lambda x: -x['size'])
    return out


def apply_changes(path, text, newline, bom, mine, to_delete, ask):
    if steam_running():
        raise WriteRefused(
            'steam_running',
            'Steam 还在运行，工具不能改这个文件。\n\n'
            '没有任何文件被改动。请先在 Steam 托盘图标上右键 →「退出」，'
            '然后再点一次清理。')

    # 写之前先确认原文件本身是完好的。坏文件不写、不乱猜。
    try:
        root_before = parse_acf(text)
    except ValueError as e:
        raise WriteRefused(
            'corrupt',
            '这个订阅记录文件本身结构已损坏（%s）。\n\n'
            '工具不敢在这种文件上做修改，因为无法确认改完是对的。\n'
            '请先点「还原备份acf文件」，或把它发给开发者排查。\n\n'
            '没有任何文件被改动。' % e)

    # 「能认全」必须和「实际删」用同一套判据（约定 3.6）。
    # 提前拦在这里：命令行不会白问一次确认；界面层会在退出 Steam 之前就拦下。
    unknown = [v for v in unmatched_subscriptions(text) if v != mine]
    if unknown:
        raise WriteRefused(
            'unknown_shape',
            unknown_shape_message(len(unknown), path))

    if ask:
        ans = input('\n  确认写入？输入 yes 继续: ').strip().lower()
        if ans != 'yes':
            print('  已取消，文件未改动。')
            return False

    removed = []        # 账号 ID，用来数条数
    removed_ids = []    # 壁纸 ID，用来核对区块是否真的少了对的条目

    def repl(m):
        if m.group(1) == mine:
            return m.group(0)
        removed.append(m.group(1))
        mm = re.match(r'\s*"(\d+)"', m.group(0))
        if mm:
            removed_ids.append(mm.group(1))
        return ''

    new = BLOCK.sub(repl, text)

    if len(removed) != to_delete:
        raise WriteRefused(
            'count_mismatch',
            '算出来要删 %d 条，实际只匹配到 %d 条，数目对不上，已中止。\n\n'
            '没有任何文件被改动。' % (to_delete, len(removed)))
    if len(removed_ids) != len(removed):
        raise WriteRefused(
            'cannot_read_id',
            '读不出要删除的壁纸编号，已中止。\n\n没有任何文件被改动。')

    # 改完必须还能被完整解析
    try:
        root_after = parse_acf(new)
    except ValueError as e:
        raise WriteRefused(
            'parse_after',
            '改动后的内容结构不合法（%s），已中止。\n\n'
            '没有任何文件被改动。' % e)

    # 逐区块核对：明细里正好少了这几条，已装清单一条都不许变
    det_after = section_ids(root_after, 'WorkshopItemDetails')
    det_before = section_ids(root_before, 'WorkshopItemDetails')
    ins_after = section_ids(root_after, 'WorkshopItemsInstalled')
    ins_before = section_ids(root_before, 'WorkshopItemsInstalled')

    if det_after != det_before - set(removed_ids):
        raise WriteRefused(
            'details_changed',
            '订阅明细的条目变化和预期不符（预期少 %d 条，实际少了 %d 条），已中止。\n\n'
            '没有任何文件被改动。'
            % (len(removed_ids), len(det_before - det_after)))
    if ins_after != ins_before:
        raise WriteRefused(
            'installed_changed',
            '已安装清单被意外改动（少了 %d 条），已中止。\n\n'
            '没有任何文件被改动。' % len(ins_before - ins_after))

    left = SUBSCRIBEDBY.findall(new)
    if any(x != mine for x in left):
        raise WriteRefused(
            'residue',
            '改完之后仍然残留别的账号的条目，已中止。\n\n'
            '这通常说明文件里有工具没认出来的记录写法。请把配置文件发给开发者适配。\n\n'
            '没有任何文件被改动。')

    stamp = datetime.datetime.now().strftime('%Y%m%d-%H%M%S')
    backup = path + '.bak-' + stamp
    shutil.copy2(path, backup)

    # 原子写入（约定 3.4）：中途断电/被杀也不会留下半个文件
    body = (new.replace('\r\n', '\n').replace('\n', newline)
            if newline == '\r\n' else new)
    tmp = path + '.tmp'
    with open(tmp, 'w', encoding='utf-8-sig' if bom else 'utf-8', newline='') as f:
        f.write(body)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, path)

    print('\n  已备份: %s' % backup)
    print('  已写入: %s' % path)
    print('  结果: 删除 %d 条，保留 %d 条；剩余 subscribedby 全部为 %s；结构校验通过。' %
          (len(removed), len(left), mine))
    print('\n  接下来：启动 Steam，看 Steam\\logs\\workshop_log.txt 有没有把条目加回来；')
    print('  想还原: python clean_acf.py --restore --file "%s"' % path)
    return True


def do_restore(path):
    """从「能解析的最近一次自动备份」还原（约定 3.8）。

    2026-11-07 修复的真实故障：原来按文件名排序取最后一个 `.bak-*`，
    会把手工备份 `.bak-fix-20261106-235549`（本身是坏的）选中并覆盖回去，
    于是「还原」越还原越坏，还会把坏文件继续复制成新备份。

    三条硬约束：
      1. 只认工具自动生成的 `.bak-YYYYmmdd-HHMMSS`，手工/实验备份不参与
      2. 从最新往回找第一个能被 parse_acf 完整解析、且条目非空的
      3. 还原前留一份现场，写后再验一次，失败回滚
    """
    d = os.path.dirname(path) or '.'
    base = os.path.basename(path)
    pat = re.compile(r'^' + re.escape(base) + r'\.bak-\d{8}-\d{6}$')
    baks = sorted(f for f in os.listdir(d) if pat.match(f))
    if not baks:
        print('没有找到工具自动生成的备份（.bak-年月日-时分秒）。')
        return False
    if steam_running():
        print('[拒绝还原] Steam 仍在运行，请先完全退出。')
        return False

    good = None
    for f in reversed(baks):
        src = os.path.join(d, f)
        try:
            root = parse_acf(read_text(src)[0])
        except (ValueError, OSError):
            print('  跳过无法解析的备份：%s' % f)
            continue
        if not acf_item_ids(root):
            print('  跳过没有订阅条目的备份：%s' % f)
            continue
        good = src
        break
    if not good:
        print('所有自动备份都无法解析，已停止。没有改动任何文件。')
        return False

    stamp = datetime.datetime.now().strftime('%Y%m%d-%H%M%S')
    keep = os.path.join(d, base + '.before-restore-' + stamp)
    try:
        shutil.copy2(path, keep)          # 留现场；名字不匹配 .bak-*，不会被再选中
        shutil.copy2(good, path)
        parse_acf(read_text(path)[0])     # 写完再验一次
    except (ValueError, OSError) as e:
        try:
            shutil.copy2(keep, path)      # 回滚
        except OSError:
            pass
        print('[还原失败，已回滚] %s' % e)
        return False
    print('已从 %s 还原到 %s' % (os.path.basename(good), path))
    print('还原前的文件已保留为 %s' % os.path.basename(keep))
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
        try:
            apply_changes(path, text, newline, bom, mine, to_delete, ask=not args.yes)
        except WriteRefused as e:
            print('\n  [未写入] %s' % e.msg)
    elif sys.stdin.isatty():
        ans = input('\n现在应用？（输入 yes 写入并自动备份，其它键仅结束）: ').strip().lower()
        if ans == 'yes':
            try:
                apply_changes(path, text, newline, bom, mine, to_delete, ask=False)
            except WriteRefused as e:
                print('\n  [未写入] %s' % e.msg)
        else:
            print('[预览模式] 未改动任何文件。')
    else:
        print('\n[预览模式] 未改动任何文件。确认无误后加 --apply。')


if __name__ == '__main__':
    main()
