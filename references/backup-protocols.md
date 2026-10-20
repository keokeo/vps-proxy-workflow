# 按需添加备用协议

只在用户要备用、已有客户端存在兼容需求，或真实测试表明主协议不适用时读取。默认先保留可用 REALITY；安装更多服务本身不提高主节点速度。同一 VPS 上的节点共用机器、IP 和线路；需要抵御这些共同故障时，必须另有独立出口，不能把协议数量当作容灾能力。

已有服务先读取实际服务名、端口和脱敏参数，避免覆盖。各协议凭据独立，每个配置修改都先备份，并准备客户端同步。

## Shadowsocks：兼容现有 Clash/Shadowrocket

适合增加一个轻量密码节点。先确认当前发行版提供的实现与用户客户端共同支持的加密方法。`aes-256-gcm` 是本流程曾成功验证的兼容选项，不把某次手机故障推断成所有设备都必须更换算法。若选其他实现或新加密方法，按双方当前文档验证格式和密钥要求。

1. 从系统仓库安装经确认的实现，检查其默认服务和监听；不要误停其他已在使用的实例。
2. 选择未占用端口，例如8388；密码用独立随机源，不复用 root 密码、UUID 或其他备用节点密码。
3. 以 shadowsocks-libev 为例，私有配置结构如下。由程序安全写入，别将完整对象回显：

```python
config = {
    "server": "0.0.0.0",
    "server_port": ss_port,
    "password": independent_random_password,
    "method": "aes-256-gcm",
    "mode": "tcp_and_udp",
    "timeout": 300
}
```

4. 使用发行版支持的独立 systemd 实例，限制配置为 root600；若服务的非root用户无法读取，可用 `LoadCredential` 把文件交给服务。先检查该版本 `ss-server` 的校验方式，不杜撰不存在的 `-t` 参数；JSON 结构校验后启动隔离实例，通过真实 TCP/UDP 请求确认协议可用。
5. 仅开放该端口需要的 TCP/UDP。生成的 Mihomo 节点使用一致的 `cipher/password`；SS URI 按客户端支持的 SIP002 格式编码。二维码和 URI 都是秘密，独立解码并与实际配置比较。
6. 更换算法或密码会使旧链接失效。重建客户端导入文件，检查 Clash 已导入副本；手机仍失败时先检查二维码、实际字段和协议支持，再决定是否换算法，不反复盲目重启。

## WireGuard：独立 VPN 客户端或 UDP 备用

它需要服务器路由、NAT 和客户端路由共同成立。只在用户需要时配置；不因 REALITY 部署而顺手启用系统转发。

1. 查看默认出口接口和实际已有路由；选择与服务器、客户端 LAN/VPN 都不冲突的私有隧道子网。不要固定假设出口为 `eth0`，也不直接复用教程里的私网。
2. 使用系统仓库的 WireGuard 工具。为服务器和每台设备生成独立密钥，客户端私钥只写入其私有导入文件；如使用 preshared key 同样按秘密处理。发现已有 `wg0` 时换独立接口或有计划地迁移，不覆盖。
3. 配置形状：

```ini
# server: /etc/wireguard/CHOSEN_INTERFACE.conf (600)
[Interface]
Address = SERVER_TUNNEL_ADDRESS
ListenPort = CHOSEN_UDP_PORT
PrivateKey = SERVER_PRIVATE_KEY

[Peer]
PublicKey = THIS_DEVICE_PUBLIC_KEY
PresharedKey = THIS_DEVICE_PRESHARED_KEY
AllowedIPs = THIS_DEVICE_TUNNEL_IPV4/32
```

```ini
# device-specific client file (600)
[Interface]
PrivateKey = THIS_DEVICE_PRIVATE_KEY
Address = THIS_DEVICE_TUNNEL_IPV4/32
DNS = CHOSEN_DNS_ADDRESS

[Peer]
PublicKey = SERVER_PUBLIC_KEY
PresharedKey = THIS_DEVICE_PRESHARED_KEY
Endpoint = VPS_PUBLIC_HOST:CHOSEN_UDP_PORT
AllowedIPs = 0.0.0.0/0
PersistentKeepalive = 25
```

配置里的大写名称是生成时必须替换的参数，不是可直接运行的文件。IPv6 字面地址在 Endpoint 中用方括号包围。

4. IPv4 出口需要启用 `net.ipv4.ip_forward=1`，按实际接口添加只匹配所选隧道网段的 masquerade，并添加最小转发允许。使用现有防火墙支持的机制；独立命名 NAT 表/链，校验后安装，避免 flush 全局规则。让启动/停止规则可重复执行，不重复叠加。UFW 与原生 nftables 混用前核对 forward 默认策略和实际规则顺序。
5. `wg-quick@接口` 启动、UDP端口放行后，用**真实设备**发请求，再观察 `wg show` 的握手时间和字节数、HTTP出口。仅 `active (exited)` 是 wg-quick 的正常状态之一，不等于客户端已经握手。
6. IPv6 单独决定。服务器没有公网IPv6出口时，客户端原生IPv6仍可能绕行；可通过客户端支持的 IPv6 隧道路由或明确的设备阻断策略避免旁路，但必须验证。仅把 `::/0` 写入 AllowedIPs，不能在所有系统上保证路由已安装。若选择双栈隧道，补齐双方IPv6地址和peer AllowedIPs；没有出口时明确说明IPv6目标不可用，不宣称双栈可用。
7. 独立 WireGuard App 和 Clash 的 WireGuard 节点若使用同一 peer，不要同时连接；另一设备另建peer。先核对当前 Mihomo WireGuard 节点格式，再导出所需字段。

## Trojan：不作为必装项

只有确实需要时才添加普通TLS节点。它不依赖 REALITY，也不会让现有 REALITY 自动提速。

- 普通 TLS 需配置客户端可验证的服务端身份：用户控制的域名和可信证书，或客户端明确支持的可信自签证书/公钥固定。
- 不复制“填一个他人网站 SNI + 自签证书 + 跳过验证”的教程作为安全默认值。他人网站的域名不能让你的证书自动可信。
- 使用独立空闲端口。当前 REALITY 若占8443，不在同一地址端口再监听Trojan；改用其他空闲端口或设计明确的共享入口。
- 证书续期、SNI和域名解析也要纳入验证和维护。用户没有域名且现有备用已足够时，说明收益有限即可，不主动购买或部署。

## 关闭不用的备用

用户明确要求停用时：先确认具体服务/端口用途，停止并禁用对应实例，移除只属于该服务的防火墙规则，确认无监听，再从客户端配置移除。保留私有备份，不删除其他服务共享的配置、端口或密钥。复测仍在使用的主节点和管理入口。

参考：[WireGuard 快速入门](https://www.wireguard.com/quickstart/)、[Mihomo 代理格式](https://wiki.metacubex.one/en/config/proxies/)、[sing-box Trojan](https://sing-box.sagernet.org/configuration/inbound/trojan/)。
