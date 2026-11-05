# 发布清单（单 exe + 开源 + 降误报）

> **交付形态：一个 `we-cleaner.exe`，不要压缩包、不要解压、不要安装。**
> 「打包」指 `build.py` 用 PyInstaller 把代码做成 exe，不是压成 zip。
> 观众拿到链接 → 下载这一个文件 → 双击就用。

## 一、推荐发布组合

| 位置 | 放什么 | 作用 |
|---|---|---|
| **GitHub 仓库** | 源码、`README.md`、`LICENSE`(MIT)、`docs/false-positive.md`、`SHA256SUMS.txt` | 可信背书、申诉材料、版本记录 |
| **GitHub Release** | `we-cleaner.exe` + `we-cleaner.exe.sha256`（再传一份不带版本号的别名） | 正式版、校验值 |
| **Gitee / GitCode** | 仓库镜像 + 发行版 | 国内可访问的源码与下载 |
| **蓝奏云 / 123 云盘** | **同一个 exe**（13 MB，远低于免费版 100 MB 上限） | 视频简介的**主下载**（免登录、不限速） |
| **视频简介** | 一个「下载页」链接，不是裸网盘/裸 exe 链接 | 换网盘不用改视频，观众有地方看说明 |

下载页可以是 GitHub Pages、Gitee Pages，或 B 站专栏。页上必须有：工具截图、三个下载入口、SHA256、误报说明链接。

## 二、GitHub 上的注意事项

- Release 附件**单文件 < 2 GiB**，公开仓库下载不收费；但**别把 exe commit 进仓库**（git push 超过 100 MB 会被拒）。二进制只放 Release 附件。
- **附件名用纯 ASCII**：`we-cleaner.exe`。中文名上传后可能被去掉或乱码。
- 再传一份**固定名副本**，这样 `/releases/latest/download/we-cleaner.exe` 永远指向最新版，下一版不会 404。
- **绝不上传**：任何真实 `appworkshop_431960.acf`、真实 SteamID、用户昵称、截图里没打码的账号数字。演示文件里的 ID 已用 `X/Y` 占位，动画里的壁纸 ID 是超范围纯数字。
- 许可 **MIT**，仓库根目录放 `LICENSE`。README 里写清楚：不联网、不上传、自动备份、会清 431960 下载缓存。

## 三、打包参数（降误报）

```bash
python build.py
```

`build.py` 实际执行 `--onefile --windowed --noupx --icon --version-file --collect-all webview/clr_loader/bottle + hidden-imports`，
并自动生成图标、版本信息和 SHA256。产物：`dist/we-cleaner.exe`（约 13 MB）。

- **知道并接受 onefile 的风险**：运行时自解压到 `%TEMP%`，是启发式误报重灾区；换来的是"双击就用"，对零门槛人群更值。不靠换 onedir 解决，靠下面的缓解措施。
- **不用 UPX**；已加图标和版本信息（产品名、公司名、版本号），空版本信息的 exe 最可疑。
- **行为收敛**：正常退出 Steam（发 `WM_CLOSE`，不强杀）、删文件走 Windows 系统接口送回收站（不借脚本解释器）、不写注册表自启动、不联网、不读账号密码。
- `build.py` 已处理"旧 exe 正在运行无法覆盖"：先改名让位再生成。

## 四、生成校验值（打包完成后）

`python build.py` 会自动写 `dist/we-cleaner.exe.sha256`。生成给下载页用的清单：

```powershell
Get-FileHash -Algorithm SHA256 .\we-cleaner.exe |
  ForEach-Object { "$($_.Hash.ToLower())  we-cleaner.exe" } |
  Out-File -Encoding ascii SHA256SUMS.txt
```

把 `SHA256SUMS.txt` 同时放进仓库和 Release 附件。观众核对方式写在下载页：

```powershell
Get-FileHash -Algorithm SHA256 .\下载到的文件.exe
```

## 五、误报说明页正文（`docs/false-positive.md`）

> **关于杀毒软件提示**
>
> 这是个人开发的开源小工具，没有购买代码签名证书。部分杀毒软件或 Windows 首次运行时可能提示风险，属于对「未签名的新程序」的常规提醒，不是检测到病毒。
>
> 执行「一键清理」或「只清下载缓存」时，360 / 电脑管家等的**主动防御**也可能弹窗，因为它看到陌生程序在删除文件；这是行为拦截，选「允许本次操作」或把 exe 加进信任即可。
>
> 三件事可以自己核对：
> 1. 源码公开在 GitHub，任何人都能看它做了什么；
> 2. 工具不联网、不上传任何数据、不改 Steam 程序文件，删文件走系统回收站（可还原）；
> 3. 下载页提供 SHA-256，可核对文件是否被改动。
>
> 我们已向 Microsoft Defender、火绒、360、腾讯电脑管家提交误报申诉。若仍被拦截，请把下载链接和提示截图发在评论区，或直接只用源码自己运行。不放心就不要下载，没有任何影响。

## 六、置顶评论文案

> 工具链接在简介（下载页，含源码、SHA256 和网盘入口）。
> 就一个 exe，双击就用，不用解压也不用安装。
> 个人开发、没有代码签名，部分杀软会误报，说明和核对方法都在下载页；不放心可以不下。
> 用之前确认 Steam 完全退出，工具会自动备份 acf，出问题点「还原备份acf文件」。

## 七、上线前检查

- [ ] `python build.py` 产出**单个 exe**，未用 UPX，已加版本信息与图标
- [ ] `we-cleaner.exe --smoke` 退出码 0；在未装 Python 的干净机器上双击验证
- [ ] 生成 SHA256，附件名纯 ASCII，带一份固定名别名
- [ ] README / 下载页 / 误报说明 / 置顶文案四处口径一致（都是单 exe，没有压缩包字样）
- [ ] 提前提交误报申诉：Microsoft Defender（`microsoft.com/en-us/wdsi/filesubmission`）、火绒、360、腾讯管家，附样本 + 源码链接
- [ ] 仓库里没有任何真实 acf、SteamID 或用户数据
- [ ] 视频简介放下载页链接，不放裸网盘/裸 exe 链接
