# VPS Proxy Workflow

把一台刚拿到 root 密码的 VPS，配置成可用、可验证、能安全维护的私有代理节点。

这是一个给 Codex 等支持 Skill 的 Agent 使用的工作流，默认基于 Ubuntu 24.04、sing-box 和 VLESS + REALITY + Vision。它会根据服务器和客户端的真实状态逐步执行，并在完成连接测试后收紧 root 的 SSH 登录方式。

## 覆盖流程

1. 拿到公网地址、实际 SSH 端口和初始 root 密码，核对主机指纹。
2. 创建或复用专用 SSH 密钥，安装公钥并用全新连接验证。
3. 检查系统、端口、路由和防火墙，部署隔离运行的 REALITY 主节点。
4. 生成 Clash Verge / Shadowrocket 导入文件，核对实际应用是否选中正确节点。
5. 验证公网出口、HTTPS 和按需测试的 DNS、UDP、IPv6 范围。
6. 通过备份、临时回退和独立连接测试，关闭 root 的 SSH 密码及交互认证。
7. 记录管理命令、配置位置、验证结果和恢复路径。

也支持已有节点巡检、伪装域名测速，以及按需配置 Shadowsocks / WireGuard 备用。Trojan 按实际需求选择。

## 安装与使用

将仓库克隆到 Codex 技能目录：

```bash
git clone https://github.com/keokeo/vps-proxy-workflow.git \
  "${CODEX_HOME:-$HOME/.codex}/skills/vps-proxy-workflow"
```

已有同名目录时，先检查差异并备份，避免覆盖当前技能。其他支持 `SKILL.md` 的 Agent 可按其技能导入方式使用本仓库。

在会话中调用：

```text
使用 $vps-proxy-workflow，从拿到 VPS 的 root 密码开始，
帮我完成私有节点搭建、客户端配置和 SSH 公钥登录加固。
```

准备好 VPS 地址、SSH 端口、服务商控制台可核验的主机指纹，以及要使用的客户端。初始密码在可信的交互终端输入，不贴到公开 Issue，也不写进命令参数或日志。

技能入口：[SKILL.md](SKILL.md)。分步骤说明位于 [references/](references/)。

## 附带工具

### 伪装域名测速

在 VPS 上运行，需要 Python 3、OpenSSL 和 GNU `timeout`：

```bash
python3 scripts/benchmark_targets.py \
  --domains www.microsoft.com www.icloud.com a0.awsstatic.com \
  --baseline www.microsoft.com --rounds 3 --timeout 1
```

输出逐轮耗时、中位数、超时与错误，以及独立的 TLS 1.3 / HTTP/2 / 证书主机名检查。测量包含 DNS、TCP、TLS 和进程开销；它不能直接代表下载带宽或 AI 响应速度。脚本不修改节点配置。

### 客户端配置生成

在本机运行，默认只需 Python 标准库：

```bash
python3 scripts/build_reality_clients.py \
  --material /path/to/private/material.json \
  --out /path/to/private/client --name VPS-REALITY
```

元数据包含 `server`、`port`、`uuid`、`public_key`、`short_id`、`servername`，以及可选的 `flow`。不能包含 SSH 私钥、root 密码或 REALITY 服务端私钥。

生成 Clash 配置、Shadowrocket 链接和独立测试配置，私有目录权限为700、文件为600，默认拒绝覆盖。`--qr` 可在已安装可选依赖 `qrcode` 及其图片后端时生成二维码。全部参数见各脚本的 `--help`。

## 验证与边界

- 所有服务器地址、端口、密钥和节点访问资料均由具体部署提供，本仓库不含可连接的真实节点。
- 修改前先检查现有服务；只读巡检不会自动重装、轮换凭据或关闭密码登录。
- 公钥登录经过独立验证后，才关闭 root 的 SSH 密码入口；保留原连接及可取消的恢复方案。
- TUN、系统代理、应用专用代理和分流规则分别验收，结论只覆盖实际测过的设备与流量。
- 当前工作流以私有节点部署和维护为目标，不承诺平台账号不被封禁。

**不要提交部署生成的 `material.json`、客户端配置、节点链接、二维码、密码、私钥或服务器日志。** 仓库的 `.gitignore` 已覆盖常见输出路径，公开提交前仍需检查暂存内容。

## 运行离线测试

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s tests -v
```

测试使用文档保留地址和合成凭据，不连接真实 VPS。可选二维码依赖或 macOS 专属环境不存在时，相关测试会明确跳过。生成的配置还应由实际安装的客户端内核校验，真实部署需要另做出口与连接验收。

## 参考项目

[sing-box](https://sing-box.sagernet.org/) · [REALITY](https://github.com/XTLS/REALITY) · [Mihomo](https://wiki.metacubex.one/) · [WireGuard](https://www.wireguard.com/)
