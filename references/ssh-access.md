# 从 root 密码建立密钥登录，再关闭 root 的 SSH 密码入口

只在用户已授权初始化这台 VPS、部署密钥或加固 SSH 时执行相应修改。审计请求只读取状态；本文件不授予权限。先从会话和现有 SSH 配置提取 IP/主机名、SSH 端口、root 用户、已有密钥和服务商控制台信息，只询问缺少的必要项。root 密码只用于首次交互认证，不写入 skill、报告、脚本、参数、环境变量或命令历史。

以下本地命令以 macOS/Linux OpenSSH 为例。变量值均来自本次服务器，不能沿用其他机器的数据。

## 1. 验证服务器身份

从服务商可信控制台或另一条已认证的带外通道获取 SSH 主机公钥指纹。控制台内可运行 `ssh-keygen -lf /etc/ssh/ssh_host_ed25519_key.pub -E sha256`。`ssh-keyscan` 只采集候选公钥，不证明对端身份；没有独立指纹时，先取得它，再提交密码。

```bash
# 本地；先填入本次服务器参数。SSH_PORT 不能凭默认值猜测。
VPS_HOST='本次服务器地址'
SSH_PORT='本次SSH端口'
KEY="$HOME/.ssh/vps-本次服务器标签-ed25519"
install -d -m 700 "$HOME/.ssh"
candidate=$(mktemp)
ssh-keyscan -T 5 -p "$SSH_PORT" -t ed25519 "$VPS_HOST" > "$candidate"
ssh-keygen -lf "$candidate" -E sha256
```

将候选指纹与可信指纹逐字比对。仅在匹配后，将该条已验证主机公钥加入 `~/.ssh/known_hosts`，保留其他条目。若服务器不支持 Ed25519，改为控制台已核实的算法；每一条准备信任的公钥都须核实。指纹变更先调查，不直接删除旧记录或使用 `StrictHostKeyChecking=no`。

```bash
# 仅在上一步验证通过后执行；candidate 中只能有已验证的条目。
touch "$HOME/.ssh/known_hosts"
chmod 600 "$HOME/.ssh/known_hosts"
cat "$candidate" >> "$HOME/.ssh/known_hosts"
rm -f "$candidate"
ssh -F /dev/null -p "$SSH_PORT" -o StrictHostKeyChecking=yes \
  -o ControlMaster=no -o ControlPath=none -o PubkeyAuthentication=no \
  -o PreferredAuthentications=password,keyboard-interactive "root@$VPS_HOST"
```

密码应由用户在已授权的交互终端密码提示中输入；如果当前工具会记录密码输入或无法安全交互，交由用户完成这一次登录。不要静默安装 `sshpass`，不要把密码传给 `sshpass -p`、expect 文本或工具参数。保持这个初始会话连接，直到整个加固验收结束。

## 2. 建立专用密钥并保留已有访问

优先使用用户明确指定的现有密钥。需要新建时采用可识别的文件名，先检查同名私钥和 `.pub` 是否已存在；存在则确认复用或换名，绝不覆盖。密钥口令由用户在提示中决定和输入，不默认生成无口令私钥。

```bash
# 本地：确认两个文件都不存在后执行。
ssh-keygen -t ed25519 -a 64 -f "$KEY" -C "vps-root-本次服务器标签"
chmod 600 "$KEY"
chmod 644 "$KEY.pub"
```

服务器中先读取实际 `AuthorizedKeysFile` 配置和 root 家目录。普通布局为 `/root/.ssh/authorized_keys`；若使用其他路径、AuthorizedKeysCommand 或配置管理，应按实际机制添加。已有密钥、限制选项、注释均须保留，不用重定向覆盖整个文件。

本机已有 `ssh-copy-id` 时可交互部署，不依赖它一定存在：

```bash
ssh-copy-id -i "$KEY.pub" -p "$SSH_PORT" \
  -o StrictHostKeyChecking=yes -o ControlMaster=no -o ControlPath=none \
  "root@$VPS_HOST"
```

否则在仍保持的 root 会话中创建目录、备份已有授权文件，再逐行追加**本地 `.pub` 公钥**。不要把私钥复制到服务器。追加前检查公钥主体是否已有，避免重复；文件末行无换行时先补换行。

```bash
# 服务器 root 会话；仅适用于已确认的普通布局。
install -d -m 700 /root/.ssh
umask 077
if test -f /root/.ssh/authorized_keys; then
  keys_backup="/root/.ssh/authorized_keys.before-$(date +%Y%m%d%H%M%S)"
  cp -p /root/.ssh/authorized_keys "$keys_backup"
  chmod 600 "$keys_backup"
fi
# 通过已授权终端粘贴 .pub 的单行内容追加，随后执行：
touch /root/.ssh/authorized_keys
chown root:root /root/.ssh /root/.ssh/authorized_keys
chmod 700 /root/.ssh
chmod 600 /root/.ssh/authorized_keys
```

## 3. 在关闭密码入口之前，证明指定密钥可用

从本地开一个**全新连接**。不用现有复用连接或 agent 中的其他密钥代替待测密钥。

```bash
ssh -F /dev/null -i "$KEY" -p "$SSH_PORT" \
  -o ControlMaster=no -o ControlPath=none -o IdentityAgent=none \
  -o IdentitiesOnly=yes -o BatchMode=yes -o StrictHostKeyChecking=yes \
  -o PreferredAuthentications=publickey -o PasswordAuthentication=no \
  -o KbdInteractiveAuthentication=no "root@$VPS_HOST" 'id -u'
```

退出码 0 且输出 `0` 才算成功。先用 `ssh-keygen -lf "$KEY.pub" -E sha256` 核对专用公钥指纹与服务器已授权的公钥一致；需要时加 `-v` 确认实际接受的是该指纹及 `publickey` 认证，不把别的密钥成功当作待测密钥成功。

**私钥有口令时**，运行相同命令但去掉 `-o BatchMode=yes`，仍保留 `IdentityAgent=none`、`IdentitiesOnly=yes`、禁止复用及禁止两种远端密码认证。由用户在私钥口令提示中解锁；这是本机私钥口令，服务器不会收到它，也不会回退到 root 密码。这样的全新、指定密钥、公钥认证登录成功，同样满足加固前置验证；无需移除私钥口令或生成无口令副本。

如果确实需要无交互复测，也可先由用户执行 `ssh-add "$KEY"` 解锁，并用 `ssh-add -l -E sha256` 核实 agent 含有该公钥指纹。仅在此正向测试分支移除 `IdentityAgent=none`，保留显式 `-i "$KEY"`、`IdentitiesOnly=yes` 和 `BatchMode=yes`，确认实际接受的指纹一致。后续反向测试仍禁用 agent。任一分支完成独立密钥登录验证后即可继续加固；未成功则保留密码入口并诊断。

## 4. 读取真实 SSH 配置与恢复条件

在服务器上确认实际服务名（常见 `ssh` 或 `sshd`）、ExecStart、配置文件 `-f`、守护进程二进制及服务传入的 `-o` 参数。下面变量只是常见布局，应按真实服务调整；检查命令也须带上实际服务的配置覆盖参数。

```bash
# 服务器 root 会话
CFG=/etc/ssh/sshd_config
SSHD=/usr/sbin/sshd
SSH_SERVICE=ssh
"$SSHD" -t -f "$CFG"
```

读取完整主配置、所有 Include 展开内容、已有 Match 块和相关云初始化/配置管理来源。OpenSSH 多处设置常采用先取得的值；多个匹配的 Match 块中，较早取得的同项值可能优先。不能假设“文件名 99-”或末尾追加一定覆盖已有配置。只追加 root 块无法达到目标时，先定位并调整最早实际生效的 root 条件，不通过全局关闭密码来连带改变其他用户。

从 `SSH_CONNECTION` 读取真实客户端 IP、服务器 IP 和服务端口，结合反向主机名、既有 Match 条件构造 `sshd -T -C` 上下文。保存 root 以及所有受相关 Match 条件影响的现有非 root 用户的变更前有效配置；若存在多个地址条件，要分别检查。下面用 `CLIENT_HOST` 表示实际用于 Match Host 的客户端名称，不能凭猜测填入。

```bash
read -r CLIENT_IP CLIENT_PORT SERVER_IP SERVER_PORT <<EOF
$SSH_CONNECTION
EOF
TX=$(mktemp -d /root/ssh-root-hardening.XXXXXX)
chmod 700 "$TX"
cp -p "$CFG" "$TX/sshd_config.before"
chmod 600 "$TX/sshd_config.before"
ROOT_CTX="user=root,addr=$CLIENT_IP,host=$CLIENT_HOST,laddr=$SERVER_IP,lport=$SERVER_PORT"
"$SSHD" -T -f "$CFG" -C "$ROOT_CTX" > "$TX/root.before"
```

实际触及的每个 Include 文件也要单独备份并纳入恢复脚本。确认服务商控制台可用。下面自动回滚例子仅修改主配置；不要直接用于多文件修改。没有 `systemd-run` 时使用已验证的可取消调度器，或先证明控制台能恢复文件和重载服务；未证明恢复路径时停在可用密钥状态。

## 5. 限定 root、校验、设置五分钟自动恢复后重载

在**真实主配置 EOF**追加以下块；先确认没有已生效的同名受管块，重复运行应更新该块而非不断追加。不要放在全局 Include 目录后误以为它处于最后。以下选项仅改变 root 的 SSH 认证，不锁定系统 root 密码，不影响控制台密码，也不改变其他账户的认证方式。

```text
Match User root
    PermitRootLogin prohibit-password
    PubkeyAuthentication yes
    PasswordAuthentication no
    KbdInteractiveAuthentication no
    AuthenticationMethods publickey
```

追加后先运行 `sshd -t`，再比较 `sshd -T -C`：root 必须仅允许公钥，其他用户有效配置须保持不变。若结果不符，恢复并解决配置优先级，不重载。`PermitRootLogin` 的有效输出可能规范化为 `without-password`。

```bash
"$SSHD" -t -f "$CFG"
"$SSHD" -T -f "$CFG" -C "$ROOT_CTX" > "$TX/root.after"
# 人工/确定性检查 after，以及非 root 的 before/after 差异通过后：
sha256sum "$CFG" > "$TX/expected.sha256"
cat > "$TX/rollback.sh" <<'SH'
#!/bin/sh
set -eu
cfg=$1; sshd_bin=$2; ssh_unit=$3; tx=$4
test ! -e "$tx/committed" || exit 0
if ! sha256sum -c "$tx/expected.sha256" >/dev/null; then
  echo 'SSH configuration changed again; refusing to overwrite it' >&2
  exit 1
fi
cp -p "$tx/sshd_config.before" "$cfg"
"$sshd_bin" -t -f "$cfg"
systemctl reload "$ssh_unit"
SH
chmod 700 "$TX/rollback.sh"
RB_UNIT="ssh-root-rollback-$(date +%s)"
systemd-run --unit "$RB_UNIT" --on-active=5m \
  /bin/sh "$TX/rollback.sh" "$CFG" "$SSHD" "$SSH_SERVICE" "$TX"
systemctl is-active "$RB_UNIT.timer"
```

确认 timer 正在等待、参数和恢复文件正确后才执行 `systemctl reload "$SSH_SERVICE"`。优先 reload；不要随意 restart SSH 服务。若不支持 reload，先核实替代方式对已建立会话的影响及恢复机制。任一步出错都保持原连接，恢复备份、校验语法并恢复服务，不继续后续部署。

## 6. 独立验收与撤销自动恢复

1. 再次执行第 3 步的全新专用密钥连接，确认 root 身份和退出码。
2. 执行下面的无公钥负向测试。它不提交真实密码；预期连接失败，调试输出显示服务端仅提供 `publickey`。单独一个失败退出码不能证明密码已禁用。

```bash
# 本地；预期非零退出，不需要输入任何密码。
ssh -F /dev/null -vv -p "$SSH_PORT" \
  -o ControlMaster=no -o ControlPath=none -o IdentityAgent=none \
  -o StrictHostKeyChecking=yes -o BatchMode=yes -o PubkeyAuthentication=no \
  -o PreferredAuthentications=password,keyboard-interactive \
  -o NumberOfPasswordPrompts=0 "root@$VPS_HOST" true
```

3. 再读实际 root `sshd -T -C`，确认 `pubkeyauthentication yes`、`passwordauthentication no`、`kbdinteractiveauthentication no`、`authenticationmethods publickey`，以及禁止 root 密码的 PermitRootLogin 值。复核非 root 用户和其他相关地址条件保持原状。
4. 在五分钟内确认 timer 尚未触发并完成所有验证，随后取消恢复。若已触发或不能确认，重新读取文件及服务状态；不得直接宣称成功。

```bash
# 服务器；先停止 timer 和可能启动的 service，再确认没有恢复旧配置。
systemctl stop "$RB_UNIT.timer" "$RB_UNIT.service"
systemctl is-active "$RB_UNIT.timer" "$RB_UNIT.service"
sha256sum -c "$TX/expected.sha256"
"$SSHD" -t -f "$CFG"
# 仅当两个unit都inactive、摘要/语法通过且有效root配置仍为公钥专用后：
touch "$TX/committed"
chmod 600 "$TX/committed"
```

两个 unit 都应为 inactive（此时命令常返回非零）。复查配置、服务活跃状态，并再开一次全新密钥连接，防止与已启动的回滚竞争。确认完成后才释放原始会话。保留 root 专属权限的备份，记录恢复路径和真实验证结果；输出报告不得包含私钥或 root 密码。

交付可复制的 `ssh -i /本机私钥绝对路径 -p 实际端口 root@实际地址` 与 `exit`。私钥只留在可信客户端；建议用户将私钥及其口令存入自己可恢复的安全存储。密钥遗失后应使用服务商控制台添加新公钥，或按备份恢复 SSH 配置并校验、重载；不能再依靠已关闭的 SSH 密码登录。说明没有修改系统 root 密码。

依据：[OpenSSH sshd_config](https://man.openbsd.org/sshd_config)、[ssh_config](https://man.openbsd.org/ssh_config)、[ssh-keyscan](https://man.openbsd.org/ssh-keyscan)。
