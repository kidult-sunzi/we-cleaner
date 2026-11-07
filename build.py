# -*- coding: utf-8 -*-
"""一键打包 we-cleaner.exe（PyInstaller onefile + windowed）。

用法：
    python build.py            # 打包 + 生成 SHA256
    python build.py --assets   # 只重新生成图标和版本信息

产物：dist/we-cleaner.exe、dist/we-cleaner.exe.sha256
"""
import hashlib
import os
import struct
import shutil
import subprocess
import sys
import time

ROOT = os.path.dirname(os.path.abspath(__file__))
os.chdir(ROOT)

VERSION_TXT = r'''VSVersionInfo(
  ffi=FixedFileInfo(
    filevers=(1, 2, 3, 0),
    prodvers=(1, 2, 3, 0),
    mask=0x3f,
    flags=0x0,
    OS=0x40004,
    fileType=0x1,
    subtype=0x0,
    date=(0, 0)
  ),
  kids=[
    StringFileInfo([
      StringTable(
        '040904b0',
        [StringStruct('CompanyName', 'WE Cleaner'),
         StringStruct('FileDescription', 'Wallpaper Engine Workshop Subscription Cleaner'),
         StringStruct('FileVersion', '1.2.3.0'),
         StringStruct('InternalName', 'we-cleaner'),
         StringStruct('LegalCopyright', 'MIT License'),
         StringStruct('OriginalFilename', 'we-cleaner.exe'),
         StringStruct('ProductName', 'WE Cleaner'),
         StringStruct('ProductVersion', '1.2.3.0')])
    ]),
    VarFileInfo([VarStruct('Translation', [1033, 1200])])
  ]
)
'''


def make_icon(path):
    """不依赖 Pillow，直接手写一张 32x32 32bpp ICO：蓝底 + 三条订阅记录 + 红斜杠。"""
    W = H = 32
    px = [[(0, 0, 0, 0) for _ in range(W)] for _ in range(H)]
    blue = (47, 125, 225, 255)
    white = (255, 255, 255, 255)
    red = (231, 76, 60, 255)
    r = 7
    for y in range(H):
        for x in range(W):
            cx, cy = min(x, W - 1 - x), min(y, H - 1 - y)
            if cx < r and cy < r and (r - cx) ** 2 + (r - cy) ** 2 > r * r:
                continue
            px[y][x] = blue
    for y0 in (8, 14, 20):
        for y in range(y0, y0 + 3):
            for x in range(7, 25):
                px[y][x] = white
    for t in range(23):                       # 斜杠表示「剔除别人的记录」
        x, y = 5 + t, 6 + t
        if 0 <= x < W and 0 <= y < H:
            for dx, dy in ((0, 0), (1, 0), (0, 1)):
                if x + dx < W and y + dy < H:
                    px[y + dy][x + dx] = red
    xor = bytearray()
    for y in range(H - 1, -1, -1):           # BMP 自下而上，BGRA
        for x in range(W):
            rr, gg, bb, aa = px[y][x]
            xor += bytes((bb, gg, rr, aa))
    header = struct.pack('<IiiHHIIiiII', 40, W, H * 2, 1, 32, 0, 0, 0, 0, 0, 0)
    image = header + bytes(xor) + bytes((W * H) // 8)   # AND mask 全 0（alpha 生效）
    ico = struct.pack('<HHH', 0, 1, 1)
    ico += struct.pack('<BBBBHHII', W, H, 0, 0, 1, 32, len(image), 22)
    ico += image
    with open(path, 'wb') as f:
        f.write(ico)
    print('  图标: %s (%d 字节)' % (path, len(ico)))


def make_assets():
    make_icon(os.path.join(ROOT, 'app.ico'))
    with open(os.path.join(ROOT, 'version.txt'), 'w', encoding='ascii') as f:
        f.write(VERSION_TXT)
    print('  版本信息: version.txt')


def out_dir():
    """默认 dist；旧 exe 正被运行中的窗口占用时，用 --out release 另出一份。"""
    if '--out' in sys.argv:
        return sys.argv[sys.argv.index('--out') + 1]
    return 'dist'


def free_target(out):
    """旧 exe 正在运行时 Windows 不让删除/覆盖，但允许改名。先让位再打包。"""
    exe = os.path.join(ROOT, out, 'we-cleaner.exe')
    if not os.path.isfile(exe):
        return []
    prev = exe + '.prev-' + time.strftime('%H%M%S')
    try:
        os.rename(exe, prev)
        print('  旧 exe 被占用，已让位为 %s' % os.path.basename(prev))
        return [prev]
    except Exception as e:
        print('  旧 exe 无法改名（%s），尝试直接覆盖' % e)
        return []


def build():
    out = out_dir()
    stale = free_target(out)
    cmd = [
        sys.executable, '-m', 'PyInstaller',
        '--noconfirm', '--clean',
        '--onefile', '--windowed',
        '--name', 'we-cleaner',
        '--distpath', out,
        '--add-data', 'gui.html;.',
        '--icon', 'app.ico',
        '--version-file', 'version.txt',
        '--noupx',                       # 不加壳，降低误报
        # pywebview 在 Windows 上动态加载平台后端，且自带 .NET 程序集 DLL，
        # PyInstaller 没有对应 hook，必须显式收集，否则换台机器就白窗。
        '--collect-all', 'webview',
        '--collect-all', 'clr_loader',
        '--collect-all', 'bottle',
        '--hidden-import', 'webview.platforms.winforms',
        '--hidden-import', 'webview.platforms.edgechromium',
        '--hidden-import', 'webview.platforms.win32',
        '--hidden-import', 'clr',
        'app.py',
    ]
    print('=== PyInstaller ===')
    print(' ', ' '.join(cmd[3:]))
    r = subprocess.run(cmd, cwd=ROOT)
    if r.returncode != 0:
        sys.exit('打包失败，退出码 %d' % r.returncode)
    exe = os.path.join(ROOT, out, 'we-cleaner.exe')
    if not os.path.isfile(exe):
        sys.exit('未找到产物 ' + exe)
    h = hashlib.sha256()
    with open(exe, 'rb') as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b''):
            h.update(chunk)
    digest = h.hexdigest()
    sha = exe + '.sha256'
    with open(sha, 'w', encoding='ascii') as f:
        f.write('%s  we-cleaner.exe\n' % digest)
    for p in stale:
        for _ in range(3):
            try:
                os.remove(p)
            except Exception:
                pass
            if not os.path.exists(p):
                break
            time.sleep(0.3)
        if os.path.exists(p):
            print('  旧版本仍在 %s（可手动删除）' % os.path.basename(p))
    for junk in ('build', '__pycache__'):
        p = os.path.join(ROOT, junk)
        if not os.path.isdir(p):
            continue
        shutil.rmtree(p, ignore_errors=True)
        if not os.path.exists(p):
            print('  已清理中间产物: %s' % junk)
        else:
            print('  中间产物仍在: %s（可手动删除）' % junk)
    print('\n=== 产物 ===')
    print('  %s  %.2f MB' % (exe, os.path.getsize(exe) / 1024 ** 2))
    print('  SHA256: %s' % digest)
    print('  校验文件: %s' % sha)


if __name__ == '__main__':
    print('=== 生成图标与版本信息 ===')
    make_assets()
    if '--assets' not in sys.argv:
        build()
