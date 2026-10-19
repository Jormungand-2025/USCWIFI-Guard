# USCWIFI Guard · 校园网维护助手

Windows 托盘程序，用于自动连接 `USCWIFI`、完成校园网账号认证，并在断线后尝试恢复。

面向 Windows 10/11 x64，当前在 Windows 10 上开发和验证。此项目针对 `USCWIFI` 和 `210.43.112.9` 的认证流程，其他学校需要适配。

## 下载与使用

从 [Releases](https://github.com/Jormungand-2025/USCWIFI-Guard/releases/latest) 下载 `USCWIFI_Guard.exe`。无需安装 Python。

1. 先在 Windows 中手动连接一次 `USCWIFI`，确保系统已保存同名无线配置，并保持 Wi-Fi 开启。
2. 将程序放到固定位置，双击运行，在本机窗口输入账号和密码。
3. 按需勾选“登录 Windows 后自动启动”，点击“保存并开始”。
4. 关闭窗口或点击“隐藏到托盘”后仍会继续维护；双击托盘图标可打开设置。

移动 EXE 后，请重新点击“保存并开始”，更新自动启动路径。程序不需要管理员权限。

## 功能

- 自动连接已经保存的 `USCWIFI` 无线配置。
- 查询认证状态，未登录时按校园网页现有流程提交认证。
- 约每 0.5 秒检查无线状态，约每 3 秒查询认证状态；外网探测在后台执行。
- 使用当前无线 IPv4，直接打开学校账号认证页。
- 保留其他 Wi-Fi 或物理有线连接，不主动抢回校园网。
- 支持暂停、恢复、修改凭据、退出及当前用户登录后自动启动。
- 登录拒绝、验证码、强制修改密码时停止自动认证并提醒。
- 网络故障采用退避重试，避免连续提交密码。

## 凭据与日志

凭据通过 Windows DPAPI 加密，保存在当前 Windows 用户的 `%LOCALAPPDATA%\USCWIFI维护助手\settings.json`，不包含在仓库和发布文件中。

状态日志位于同目录的 `status.log`，不记录账号、密码、认证原始响应或 cookie。程序遵循学校现有的 HTTP 认证接口；本机加密不改变网络传输协议，也不能防范当前 Windows 账户已被完全控制的情况。

## 从源码运行

需要 Windows 和 Python 3.13（当前构建环境）。

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
python src/campus_guard.py
```

## 构建 EXE

```powershell
python -m pip install -r requirements-dev.txt
powershell -ExecutionPolicy Bypass -File scripts/build.ps1
```

生成文件：`dist/USCWIFI_Guard.exe`。本地构建不需要校园网账号密码。

## 项目结构

```text
src/campus_guard.py       主程序
docs/usage.md             使用与故障处理
scripts/build.ps1         Windows 打包脚本
requirements.txt         运行依赖
requirements-dev.txt     构建依赖
CHANGELOG.md             版本记录
LICENSE                  MIT 许可证
```

## 验证范围

已验证本机网络识别、认证状态查询、当前 IP 获取、凭据加密、窗口初始化，以及登录拒绝、验证码、强制改密时停止的逻辑。已验证快速检测路径及认证页直达地址。

完整的开机、断线、重新认证表现依赖本机无线配置和学校服务器，需要在实际环境验证。学校认证接口、nasId 或运营商配置变化时，程序可能需要更新。

详情见 [使用说明](docs/usage.md)。反馈问题时请提供系统版本和脱敏后的状态日志，不要上传密码、完整配置、学号或个人截图。

## 许可证

[MIT](LICENSE)。这是非官方工具，与学校和网络运营商无隶属关系。
