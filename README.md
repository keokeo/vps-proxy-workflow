# VPS Proxy Workflow

把一台刚拿到 root 密码的 VPS，配置成可用、可验证、能安全维护的私有代理节点。

这是一个供 Codex、Claude Code，以及其他具有文件和终端权限的 AI Agent 使用的工作流，默认基于 Ubuntu 24.04、sing-box 和 VLESS + REALITY + Vision。入口是普通的 `SKILL.md` 和配套文档，不依赖某一种 Agent。它会根据服务器和客户端的真实状态逐步执行，并在完成连接测试后收紧 root 的 SSH 登录方式。

## 覆盖流程

1. 拿到公网地址、实际 SSH 端口和初始 root 密码，核对主机指纹。
2. 创建或复用专用 SSH 密钥，安装公钥并用全新连接验证。
3. 检查系统、端口、路由和防火墙，部署隔离运行的 REALITY 主节点。
4. 生成 Clash Verge / Shadowrocket 导入文件，核对实际应用是否选中正确节点。
5. 按需向当前 Clash / Mihomo 配置合并国内直连、国外代理的分流规则，保留已有节点与客户端设置。
6. 验证公网出口、HTTPS、分流结果和按需测试的 DNS、UDP、IPv6 范围。
7. 通过备份、临时回退和独立连接测试，关闭 root 的 SSH 密码及交互认证。
8. 记录管理命令、配置位置、验证结果和恢复路径。

也支持已有节点巡检、伪装域名测速，以及按需配置 Shadowsocks / WireGuard 备用。Trojan 按实际需求选择。

## 安装与使用

将仓库克隆到 Codex 技能目录：

```bash
git clone https://github.com/keokeo/vps-proxy-workflow.git \
  "${CODEX_HOME:-$HOME/.codex}/skills/vps-proxy-workflow"
```

已有同名目录时，先检查差异并备份，避免覆盖当前技能。Claude Code 和其他支持 Skill 的 Agent 可按各自的技能安装方式导入本仓库；安装目录和调用语法以所用 Agent 为准。

Codex 中可以这样调用：

```text
使用 $vps-proxy-workflow，从拿到 VPS 的 root 密码开始，
帮我完成私有节点搭建、客户端配置和 SSH 公钥登录加固。
```

没有 Skill 安装机制的 Agent，也可以将仓库克隆到任意工作目录，然后让它读取该目录下的 `SKILL.md`，按任务继续阅读引用文档。例如：

```text
请读取 /path/to/vps-proxy-workflow/SKILL.md，按其中的工作流执行。
我刚拿到 VPS 的 root 密码，请从核对主机指纹和建立专用 SSH 密钥开始，
完成 REALITY 节点搭建、客户端配置、可选分流和连接验证，再收紧 root 登录方式。
```

已有节点、只想加入分流时，可以使用：

```text
请读取 /path/to/vps-proxy-workflow/SKILL.md，
按照 references/clash-split-routing.md，给我当前使用的 Clash Verge 配置合并分流规则。
先确认实际生效的配置来源并备份，保留节点、凭据、代理组、端口、DNS、TUN 和 IPv6 设置，
保留已有自定义规则的用途，检查规则优先级和内核校验结果。
这次只修改客户端分流，不修改 SSH 或 VPS。
```

将示例路径替换为本机仓库的实际位置。

新建部署时，准备好 VPS 地址、SSH 端口、服务商控制台可核验的主机指纹，以及要使用的客户端。初始密码在可信的交互终端输入，不贴到公开 Issue，也不写进命令参数或日志。仅修改客户端分流时无需提供 VPS 密码。

技能入口：[SKILL.md](SKILL.md)。分步骤说明位于 [references/](references/)。

## Clash 国内直连、国外代理分流

提供可合并的 [分流配置片段](assets/clash-split-routing.yaml) 和 [合并与验证说明](references/clash-split-routing.md)。配置使用 MetaCubeX 的五个 MRS 规则集，按规则让局域网和国内目标直连、国外目标走 `PROXY`，未匹配的流量最终也走 `PROXY`。规则集每 86400 秒更新一次，通过 `PROXY` 下载。

规则从上往下匹配：局域网域名和 IP、国内域名、非中国域名、国内 IP、`GEOIP,CN`，最后为 `MATCH,PROXY`。已有自定义规则的位置会影响结果，合并时应核对优先级；`MATCH` 必须留在最后。实际代理组名称不是 `PROXY` 时，需要同步调整规则和规则集下载策略。

这是需要合并到当前配置的片段，不能直接替换完整配置。Agent 应先确认 Clash Verge 当前使用的配置及规则扩展来源，备份后合并 `rule-anchor`、`rule-providers` 和 `rules`，保留已有节点和其他设置，并验证真实直连与代理请求。配置文件中的同名字段应合并，不能重复添加第二个 `rules:`。

该片段适用于 Clash Verge 所用的 Mihomo 内核；MRS 不是 Shadowrocket 的通用规则格式。TUN 是否开启是独立设置，加入分流不会自动开启 TUN。

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

生成器默认仍使用 `MATCH,PROXY`，不会自动生成上述分流配置。需要分流时，由 Agent 按 [合并与验证说明](references/clash-split-routing.md) 另行合并。

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
