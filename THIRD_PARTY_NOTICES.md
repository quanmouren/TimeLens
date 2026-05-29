# 第三方许可证说明

本项目依赖以下第三方 Python 软件包。此处列出的版本为整理本说明时开发环境中实际检测到的版本。

## 直接依赖

| 软件包 | 版本 | 许可证 | 用途 |
| --- | ---: | --- | --- |
| pywin32 | 308 | Python Software Foundation License | Windows foreground window and icon APIs |
| psutil | 6.0.0 | BSD-3-Clause | Process inspection |
| Flask | 3.0.0 | BSD-3-Clause | Local web dashboard and API server |
| pystray | 0.19.5 | LGPL-3.0 | Windows system tray integration |
| Pillow | 10.4.0 | HPND | Image/icon handling |

## 间接运行时依赖

| 软件包 | 版本 | 许可证 | 被谁依赖 |
| --- | ---: | --- | --- |
| blinker | 1.9.0 | MIT | Flask |
| click | 8.1.7 | BSD-3-Clause | Flask |
| itsdangerous | 2.2.0 | BSD-3-Clause | Flask |
| Jinja2 | 3.1.6 | BSD-3-Clause | Flask |
| MarkupSafe | 2.1.5 | BSD-3-Clause | Jinja2 / Flask |
| Werkzeug | 3.1.4 | BSD-3-Clause | Flask |
| six | 1.17.0 | MIT | pystray |

## 发布说明

- 如果以源码形式发布本项目，请将本说明与 `requirements.txt` 一同保留。
- 如果发布打包后的可执行文件，请同时包含已安装 Python 发行包中的许可证文件，尤其是：
  - `pystray-*.dist-info/COPYING`
  - `pystray-*.dist-info/COPYING.LGPL`
  - `psutil-*.dist-info/LICENSE`
  - `flask-*.dist-info/LICENSE.rst`
  - `pillow-*.dist-info/LICENSE`
  - 以及 Flask 运行时依赖对应的许可证文件。
- `pystray` 使用 LGPL-3.0 许可证。打包二进制文件时，请确保用户能够按该许可证要求替换或重新链接 LGPL 覆盖的组件。
- 从本机已安装应用中提取的应用图标仅在运行时显示，不会作为第三方素材打包进本仓库。

本文件仅用于整理第三方许可证说明，不构成法律意见。
