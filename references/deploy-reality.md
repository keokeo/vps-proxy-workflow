# 部署 REALITY 主节点

适用范围：已明确授权搭建自己的 VPS。先完成 [ssh-access.md](ssh-access.md) 的主机核验和专用密钥测试；密码认证最终关闭步骤在完整验收后做，若用户明确只要求立即加固则单独执行。

## 1. 先读服务器状态

确认 `/etc/os-release`、CPU 架构、systemd 版本、内存/磁盘、时钟、默认出口接口、已有监听和当前防火墙。以下只读命令可批量执行，私有配置应由程序提取必要字段，不直接完整打印：

```bash
cat /etc/os-release
uname -m
systemctl --version
free -m
df -h /
timedatectl status
ip -4 route get 1.1.1.1
ss -lntup
ufw status verbose
systemctl --failed --no-pager
```

检查服务名、安装路径、端口和目标目录冲突。已有 UFW/nftables/iptables/Docker 规则时逐条增加需要的放行，不 reset 防火墙、不清空其他链。云厂商安全组是另一层，主机开放不等于安全组已经允许。

参数建议：`REALITY_PORT` 用未占用的 TCP 端口（例如 8443）；`REALITY_TARGET` 可先测 `www.microsoft.com`。不要因教程用 443 就迁移工作正常的 8443。用户已有稳定主节点时优先审计而非重装。

## 2. 选域名与安装包

只在有必要时用 `../scripts/benchmark_targets.py` 从 VPS 端测速。要求目标支持 TLS 1.3/H2、证书匹配、可稳定连接；HTTP 重定向情况另测 HTTP 请求，不能从 TLS 测试推断。最快单样本不能证明最适合；使用多轮中位数并查看失败率。

从 [sing-box 官方发布](https://github.com/SagerNet/sing-box/releases) 选择与客户端兼容的稳定版本，记录固定版本号、架构、资产名称和官方 SHA256。不要把本次聊天用过的版本永久硬编码到新部署。`x86_64` 对应 amd64、`aarch64` 对应 arm64，其他架构查官方资产。版本和配置字段以本次官方文档为准。

Ubuntu 可按需安装 `ca-certificates curl openssl python3 ufw`；先确认哪些已安装。下载到私有临时目录，验证摘要后从压缩包中只取预期的常规 `sing-box` 文件，不直接以 root 解压任意路径。下载或摘要失败即停止，不运行不明一键脚本、不执行未经核验的 `curl | bash`。

安装二进制到 `/usr/local/lib/vps-reality/sing-box`，root 所有、755；用绝对路径执行 `version` 并记录。不要替换其他服务共用的二进制。必要时用发行版维护的安装途径，但仍记录实际版本和来源。

## 3. 配置、凭据和运行隔离

以下是本流程使用过的配置形状；生成前核对当前安装版本支持这些字段。用密码学随机源生成 UUID、REALITY 密钥对和 short ID；每台服务器独立。`sing-box generate reality-keypair` 的结果直接捕获解析，不回显到普通工具输出。

在 VPS 上由程序构建对象并写私有临时文件：

```python
config = {
    "log": {"level": "info", "timestamp": True},
    "inbounds": [{
        "type": "vless", "tag": "reality-in", "listen": "0.0.0.0",
        "listen_port": port,
        "users": [{"name": "owner", "uuid": client_uuid,
                   "flow": "xtls-rprx-vision"}],
        "tls": {"enabled": True, "server_name": target,
                "reality": {"enabled": True,
                            "handshake": {"server": target, "server_port": 443},
                            "private_key": private_key,
                            "short_id": [short_id]}}
    }],
    "outbounds": [{"type": "direct", "tag": "direct"}],
    "route": {"rules": [{"ip_is_private": True, "action": "reject"}],
              "final": "direct"}
}
```

这是服务端到实际目标的直接出口，拒绝代理访问私网；不是绕过客户端代理的 DIRECT。对于特殊内部网访问需求，先与用户确认需要的精确网段，再改变拒绝规则。

先运行 `/usr/local/lib/vps-reality/sing-box check -c PRIVATE_TEMP_FILE`，捕获输出；失败只报告脱敏原因。通过后再原子写入 `/etc/vps-reality/config.json`，目录700、文件600、root所有。不要把已有配置原地换成新凭据；修改已有配置先备份并明确客户端同步安排。

只把客户端字段另写到 `/var/lib/vps-reality/client-material.json`，目录700、文件600：

```python
material = {
    "server": public_host, "port": port,
    "uuid": client_uuid, "public_key": public_key,
    "short_id": short_id, "servername": target,
    "flow": "xtls-rprx-vision"
}
```

它仍是私有访问资料，但不应包含服务端私钥。经已核验主机的 SSH 安全取回本机私有工作目录，直接写文件而非工具回显。不要使用会把私有配置完整打印到标准输出的旧安装器。

在支持 `DynamicUser` 和 `LoadCredential` 的 systemd 上，可使用独立服务 `/etc/systemd/system/vps-reality.service`：

```ini
[Unit]
Description=Private VLESS REALITY Vision
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
DynamicUser=yes
LoadCredential=config:/etc/vps-reality/config.json
ExecStart=/usr/local/lib/vps-reality/sing-box run -c %d/config
Restart=on-failure
RestartSec=3
NoNewPrivileges=yes
CapabilityBoundingSet=
ProtectSystem=strict
ProtectHome=yes
PrivateTmp=yes
PrivateDevices=yes
RestrictAddressFamilies=AF_INET AF_INET6 AF_UNIX AF_NETLINK
RestrictSUIDSGID=yes
RestrictRealtime=yes
LockPersonality=yes
SystemCallArchitectures=native
UMask=0077

[Install]
WantedBy=multi-user.target
```

8443 无需绑定低端口能力；若选 443，检查本机是否允许非特权用户绑定，必要时仅给该服务 `CAP_NET_BIND_SERVICE` 的 BoundingSet/AmbientCapabilities，并验证服务启动。不要把普通 8443 的空能力配置照抄到受限的 443 后误以为域名有问题。

若版本/平台不支持这些 systemd 功能，保留最小权限原则并调整；不要为了让服务读取600配置而把它改成644。

## 4. 启动与防火墙

在重载 systemd 前运行 `systemd-analyze verify` 检查 unit；配置检验成功后 `daemon-reload` 并 `enable --now vps-reality.service`。若失败读取脱敏日志，核对端口、二进制架构、权限和隔离能力。服务没正常运行前不宣告完成。

UFW 已开启时只追加 `REALITY_PORT/tcp` 放行。UFW 原来关闭而本次要启用时，先放行**实际 SSH 端口**、所有仍需对外提供的现有服务及本次节点，再启用。保留管理连接并用新连接复核 SSH，防止把非22端口的管理入口封掉。没有 WireGuard 时不启用 IP 转发、不加 NAT。

最低只需 SSH + REALITY TCP；不开放面板，不创建不需要的 TCP/UDP 443 备用规则。每个端口的用途、现有服务的保留与新增规则均记入部署记录。

## 5. 客户端与闭环

在本机运行 `../scripts/build_reality_clients.py`，输入上述客户端元数据；二维码可选，视同访问凭据。若已有 Mihomo，先检查本机计划使用的监听端口空闲，再运行配置校验和独立临时测试实例。只使用 Shadowrocket 等客户端时，不强制安装另一客户端或内核；核对其导入字段后在用户选定的客户端进行真实出口和HTTPS测试。

独立测试验证新配置可用，但不证明 Clash 应用已切换成功。用户让你配置应用时，在其授权范围内选中本地配置和 REALITY 节点，并从运行 API/连接列表或可验证的应用状态确认。仅让用户导入时明确记录“文件已生成，应用导入尚未完成”。

参考 [verify-and-diagnose.md](verify-and-diagnose.md) 验证出口、HTTPS、DNS/UDP 和实际客户端，再完成 root SSH 密码认证关闭。只有用户明确需要的备用协议才继续 [backup-protocols.md](backup-protocols.md)。

## 官方参考

- [sing-box REALITY/TLS 字段](https://sing-box.sagernet.org/configuration/shared/tls/)
- [sing-box VLESS 入站](https://sing-box.sagernet.org/configuration/inbound/vless/)
- [REALITY 目标选择说明](https://github.com/XTLS/REALITY)
- [Mihomo VLESS 节点格式](https://wiki.metacubex.one/en/config/proxies/vless/)
