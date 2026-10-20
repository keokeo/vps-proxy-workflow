# 真实验收、域名测速和故障定位

先区分测的到底是什么。服务器服务 active、配置合法、手机显示已连接、测速绿灯是不同证据，不能相互替代。用户只问已有节点是否有问题时，从只读检查开始，不重新部署。

## 1. 服务器最小检查

通过核验过的主机和指定密钥连接，禁止密码回退。读系统版本、uptime、load、可用内存、磁盘、服务状态、NRestarts、监听、UFW和有效SSH配置。检查配置时只输出脱敏参数和权限，日志按错误类型聚合；服务器配置检查器的错误可能带出UUID或私钥，先捕获再脱敏。

- REALITY：二进制真实版本、`check -c`、实际 service、监听地址/端口、SNI/握手目标、用户flow、配置600、私网拒绝规则。
- WireGuard：interface、peer数量、握手时间/流量；不打印私钥或完整客户端配置。
- SS：实际实例、端口、cipher、TCP/UDP模式；不打印password。
- SSH：`sshd -T -C` 的root上下文与实际运行参数，日志中的失败/成功认证方式。扫描次数多说明入口被探测，不直接证明入侵；没有发现成功密码登录也不能证明整机绝对安全。
- 更新：可读现有缓存的可升级列表和 reboot-required，但未执行索引刷新就说明缓存时效未知。升级不是只读检查，不能擅自更新全部软件。

先确认没有资源瓶颈或进程异常，再分析网络。服务端直接访问握手目标和普通HTTPS站点可确认服务器自身出口，不证明客户端到它的链路。

## 2. 独立客户端测试

对生成的 `mihomo-reality-test.yaml` 使用当前客户端内核的配置校验；按当前版本帮助确认参数。常见方式：

```bash
# 所有路径都替换成本次真实路径；先确认测试端口空闲。
"$MIHOMO_BIN" -t -d "$PRIVATE_TEST_DIR" -f "$PRIVATE_TEST_PROFILE"
"$MIHOMO_BIN" -d "$PRIVATE_TEST_DIR" -f "$PRIVATE_TEST_PROFILE"
```

后台运行时保存 PID，进程日志写600文件；验证结束只终止自己启动的测试进程，不使用 `killall mihomo`。不要让测试实例修改全局系统代理、TUN或实际应用配置。端口冲突应换独立端口重新生成，不能杀掉现有客户端。

已有其他VPN/TUN时，临时实例的出站连接也可能被它捕获，形成串联代理。先核对去往新VPS的实际路由和旧代理的连接记录；显式请求新测试端口并看到新VPS出口，只证明这条链可用，不能单独证明本机直连新VPS。需要排除旧TUN影响时，在用户授权范围内选择可恢复的独立路径，不能默默关闭用户现用网络。

显式通过测试代理请求，排除当前shell `NO_PROXY` 的影响：

```bash
curl --proxy "socks5h://127.0.0.1:$TEST_PORT" --noproxy '' \
  --max-time 15 --fail --silent --show-error https://api.ipify.org
curl --proxy "socks5h://127.0.0.1:$TEST_PORT" --noproxy '' \
  --max-time 15 --silent --show-error --output /dev/null \
  --write-out '%{http_code} %{time_total}\n' https://www.microsoft.com
```

出口应与**服务商分配或从服务器实际确认的公网出口**一致；NAT型VPS可能与SSH入口地址不同，应先确认映射，不机械判错。HTTPS要看预期响应和是否超时，不以所有网站必须返回200为规则。

`socks5h` 域名请求可验证这次远端解析路径，但不是设备级DNS泄漏测试。需要XUDP/UDP时，用支持 SOCKS5 UDP ASSOCIATE 的客户端做一次真实DNS/UDP请求并确认响应；`curl` 的普通HTTPS请求不能证明UDP可用。

## 3. 核对真实应用是否生效

Clash Verge导入本地文件后通常保留一份副本。检查“当前profile、实时mode、PROXY组当前选项、实时连接链”，不能只读取项目原始YAML。若本机可读Mihomo控制API或Unix socket，先读取当前控制器地址/认证方式，不猜端口、不打印secret；只提取需要的字段。读取不到实际应用状态时，把结论限定为“独立测试可用”。

不同流量入口：

| 入口 | 需要确认 |
| --- | --- |
| 系统代理 | macOS `scutil --proxy` 或实际系统设置；只有遵循系统代理的程序受影响 |
| 应用/命令行专用代理 | 应用设置或环境中的 HTTP_PROXY/HTTPS_PROXY/ALL_PROXY、监听端口、NO_PROXY；不要打印其他环境凭据 |
| TUN | 实时enable、路由、排除项、DNS劫持和最终分流；开关开了不等于全部走VPS |
| 手机 | 真实导入字段、所选节点、实际出口；Mac成功不代表手机已成功 |

系统代理与TUN都关闭，也可能有应用单独使用代理。本次没有观察到某程序的连接时，不能因为其配置文件有代理字段，就断言当前流量已通过。

生成器默认 `MATCH,PROXY`，只保证进入该代理的请求交给选中节点，不实现“国内直连、海外代理”。用户要分流时按其规则需求调整，不默默插入 `DIRECT` 兜底或自动故障直连。

## 4. IPv6、DNS与WebRTC范围

`dns.ipv6: false` 控制解析行为，配置全局 `ipv6: false` 也不单独证明系统原生IPv6被阻断。必须在用户实际使用入口下分别测IPv4/IPv6、DNS和必要的浏览器WebRTC；没有测试就列为未验证。

TUN的自动路由与最终规则是两层；DIRECT、排除地址/接口、本地DNS均可能影响覆盖。不要承诺“打开TUN绝无直连”；macOS的严格路由支持和行为以当前内核文档为准，不照搬Windows/Linux断网保护结论。

不为了代理验收去修改系统地区、时区或伪造平台身份，不把一个IP声誉网站的分数当作平台安全保证。

## 5. 域名测速口径

在**VPS**运行 `../scripts/benchmark_targets.py`，将当前目标作为baseline，新增候选域名交错测三轮或用户指定轮数。脚本用单调时钟和独立 GNU timeout，保留成功、超时、握手失败的区别，输出每轮值和中位数。TLS1.3、H2和证书主机名检查是独立探测；排名不自动代表全部兼容。

需要与用户给出的 `date +%s%3N; timeout openssl ...` 命令逐字对照时，可在Ubuntu上的bash中执行相同命令；macOS的date/timeout不一定兼容。保持相同测量地点、轮数、超时和计时方式，不能混用 curl 的 `time_appconnect` 与整条命令时间直接排名。

Python测时注意：把短进程的标准输出直接丢弃，再用 `subprocess.wait(timeout=...)`，可能把几十毫秒的握手量化成轮询等待时间。本脚本通过管道捕获小输出、不使用Python的timed wait、依靠GNU timeout限时。日志不要保存整份证书内容。

输出表至少说明：域名、成功次数、中位数、明显抖动或超时、TLS1.3/H2是否通过。只有几毫秒差距时称“本次持平/接近”，不因此迁移正在工作的目标。REALITY目标主要参与建连；吞吐和AI响应速度还受用户→VPS→实际服务的线路影响。

更换目标会涉及服务端握手目标/SNI和客户端SNI/导入副本；只测速没有更换授权时，不修改它们。需要切换时备份现有配置，协调全部客户端更新，复测真实REALITY连接，失败恢复原目标。

## 6. 常见分支

| 现象 | 优先核对 |
| --- | --- |
| SSH连不上 | 实际端口/安全组/主机指纹/所用密钥/有效Match；不要盲目删known_hosts |
| 独立测试成功，应用不通 | 当前导入副本、profile、节点选择、实时mode、代理入口与监听端口 |
| 手机不通，Mac通 | 导入URI/二维码解码、SNI、公钥、shortID、UUID、flow、软件版本和手机网络 |
| 偶发超时 | 服务资源与重启、用户到VPS的RTT/丢包、晚高峰和请求冷启动；分别测握手目标和真正访问站点 |
| 域名很快但REALITY失败 | TLS/H2、证书/目标兼容、服务端参数与客户端一致性；普通openssl成功并非REALITY验收 |
| WG已active但无流量 | 客户端发包、UDP可达、peerAllowedIPs、转发/NAT规则与出口接口 |

每次修复围绕证据，保留可用配置和独立复测结果。同一原因连续失败而没有新证据时，停止重复改动并回退，汇总需要用户提供的真实信息。

官方参考：[Mihomo TUN](https://wiki.metacubex.one/en/config/inbound/tun/)、[规则](https://wiki.metacubex.one/en/config/rules/)、[DNS](https://wiki.metacubex.one/en/config/dns/)、[运行模式](https://wiki.metacubex.one/en/config/general/)。
