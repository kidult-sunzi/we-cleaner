# 用到的现成组件（第三方说明）

`we-cleaner.exe` 不是从零写的。打包时把下面这些现成组件一起放了进去，
按它们各自的要求，在这里列出名称、用途和授权原文。

- **下面英文部分是原文，请原样保留，不要翻译、改写或删除**（中文只是解释）。
- 本工具自己的代码采用 MIT 许可，见仓库根目录的 `LICENSE`。
- 版本号来自 `requirements.txt` 和本次实际打包环境。

| 组件 | 版本 | 用来做什么 | 授权 |
|---|---|---|---|
| Python 3.13（含标准库） | 3.13.12 | exe 内嵌的运行环境 | PSF License |
| pywebview | 6.2.1 | 显示工具窗口 | BSD 3-Clause |
| pythonnet | 3.2.1 | 连接 Windows 界面组件 | MIT |
| clr-loader | 0.3.1 | 加载 .NET 运行时 | MIT |
| bottle | 0.13.4 | 界面与后台之间通信 | MIT |
| proxy-tools | 0.1.0 | pywebview 的辅助库 | MIT |
| typing_extensions | 4.16.0 | 类型兼容 | PSF License |
| PyInstaller bootloader | 6.22.3 | 把程序做成单个 exe | GPLv2 + Bootloader Exception |

**没有一起分发的**：Microsoft Edge WebView2 Runtime 和 .NET Framework 由用户电脑的 Windows 提供，
工具只是调用它们，没有打包进 exe，所以不在上表里。

---

## 一、Python / typing_extensions（PSF License）

Python 解释器及其标准库由 Python Software Foundation 发布。完整许可原文：
https://docs.python.org/3/license.html

`typing_extensions` 随包附带的 `LICENSE` 文件即同一份 PSF 许可全文。
工具没有修改 Python 本身。

## 二、PyInstaller（GPLv2 + Bootloader Exception）

PyInstaller 是**打包工具**，本身没有随 exe 分发；只有它生成的启动程序（bootloader）嵌在 exe 里。
其授权文件专门写明以下例外，允许把生成的可执行文件按自己的条件自由分发，无需公开本工具源码。原文如下：

```
Bootloader Exception
--------------------

In addition to the permissions in the GNU General Public License, the
authors give you unlimited permission to link or embed compiled bootloader
and related files into combinations with other programs, and to distribute
those combinations without any restriction coming from the use of those
files. (The General Public License restrictions do apply in other respects;
for example, they cover modification of the files, and distribution when
not linked into a combined executable.)
```

本工具未修改 bootloader。完整授权文件见 PyInstaller 安装包内的 `COPYING.txt`，
或 https://github.com/pyinstaller/pyinstaller/blob/develop/COPYING.txt

## 三、proxy-tools（MIT）

该包的安装信息中声明授权为 MIT，但安装包内没有附带独立的版权声明文件。
来源：https://pypi.org/project/proxy-tools/ 。下面按 MIT 的通用要求保留说明。

## 四、其余组件的授权原文

### pywebview 6.2.1（BSD 3-Clause）

```
BSD 3-Clause License

Copyright (c) 2014-2017, Roman Sirokov
All rights reserved.

Redistribution and use in source and binary forms, with or without
modification, are permitted provided that the following conditions are met:

* Redistributions of source code must retain the above copyright notice, this
  list of conditions and the following disclaimer.

* Redistributions in binary form must reproduce the above copyright notice,
  this list of conditions and the following disclaimer in the documentation
  and/or other materials provided with the distribution.

* Neither the name of the copyright holder nor the names of its
  contributors may be used to endorse or promote products derived from
  this software without specific prior written permission.

THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS "AS IS"
AND ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT LIMITED TO, THE
IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS FOR A PARTICULAR PURPOSE ARE
DISCLAIMED. IN NO EVENT SHALL THE COPYRIGHT HOLDER OR CONTRIBUTORS BE LIABLE
FOR ANY DIRECT, INDIRECT, INCIDENTAL, SPECIAL, EXEMPLARY, OR CONSEQUENTIAL
DAMAGES (INCLUDING, BUT NOT LIMITED TO, PROCUREMENT OF SUBSTITUTE GOODS OR
SERVICES; LOSS OF USE, DATA, OR PROFITS; OR BUSINESS INTERRUPTION) HOWEVER
CAUSED AND ON ANY THEORY OF LIABILITY, WHETHER IN CONTRACT, STRICT LIABILITY,
OR TORT (INCLUDING NEGLIGENCE OR OTHERWISE) ARISING IN ANY WAY OUT OF THE USE
OF THIS SOFTWARE, EVEN IF ADVISED OF THE POSSIBILITY OF SUCH DAMAGE.
```

### pythonnet 3.2.1（MIT）

```
MIT License

Copyright (c) 2006-2021 the contributors of the Python.NET project

Permission is hereby granted, free of charge, to any person obtaining a
copy of this software and associated documentation files (the "Software"),
to deal in the Software without restriction, including without limitation
the rights to use, copy, modify, merge, publish, distribute, sublicense,
and/or sell copies of the Software, and to permit persons to whom the
Software is furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included
in all copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS
OR IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL
THE AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING
FROM, OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER
DEALINGS IN THE SOFTWARE.
```

### clr-loader 0.3.1（MIT）

```
MIT License

Copyright (c) 2019-2026 Benedikt Reinartz

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
```

### bottle 0.13.4（MIT）

```
Copyright (c) 2009-2024, Marcel Hellkamp.

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in
all copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN
THE SOFTWARE.
```
