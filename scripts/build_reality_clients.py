#!/usr/bin/env python3
"""Build local REALITY client artifacts from metadata; never contact a server.

The input JSON contains only server, port, uuid, public_key, short_id,
servername, and optionally flow (xtls-rprx-vision). Output profiles are JSON,
which is valid YAML. The test profile is separate from any active client.
All traffic that enters either profile follows MATCH,PROXY. These files do
not enable system proxy, TUN, or prove device-wide DNS/IPv6 coverage.
Resolving a proxy server hostname uses bootstrap DoH, which may be direct.
"""

from __future__ import annotations

import argparse
import base64
import binascii
import io
import ipaddress
import json
import os
from pathlib import Path
import re
import secrets
import stat
import sys
import uuid
from urllib.parse import quote, urlencode


ALLOWED_KEYS = {"server", "port", "uuid", "public_key", "short_id", "servername", "flow"}
REQUIRED_KEYS = ALLOWED_KEYS - {"flow"}
FILENAMES = (
    "clash-verge-reality.yaml",
    "shadowrocket-reality.txt",
    "mihomo-reality-test.yaml",
)


class BuildError(Exception):
    """An expected failure whose message does not disclose input values."""


def checked_path(raw: str) -> Path:
    """Accept verified macOS system aliases, then reject other symlinks."""
    path = Path(os.path.abspath(os.path.expanduser(raw)))
    if sys.platform == "darwin" and len(path.parts) > 1:
        aliases = {"tmp": "/private/tmp", "var": "/private/var"}
        destination = aliases.get(path.parts[1])
        if destination is not None:
            alias = Path("/") / path.parts[1]
            try:
                alias_status = alias.lstat()
                target_status = Path(destination).lstat()
                link_target = os.path.abspath(os.path.join("/", os.readlink(alias)))
            except OSError:
                pass
            else:
                if (
                    stat.S_ISLNK(alias_status.st_mode)
                    and alias_status.st_uid == 0
                    and link_target == destination
                    and stat.S_ISDIR(target_status.st_mode)
                    and target_status.st_uid == 0
                ):
                    path = Path(destination).joinpath(*path.parts[2:])
    current = Path(path.anchor)
    for component in path.parts[1:]:
        current /= component
        try:
            status = current.lstat()
        except FileNotFoundError:
            continue
        if stat.S_ISLNK(status.st_mode):
            raise BuildError("Symlink paths are not accepted.")
    return path


def load_material(raw: str) -> dict:
    path = checked_path(raw)
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
    fd = os.open(path, flags)
    with os.fdopen(fd, "rb") as handle:
        status = os.fstat(handle.fileno())
        if not stat.S_ISREG(status.st_mode) or status.st_size > 65536:
            raise BuildError("Material must be a regular JSON file smaller than 64 KiB.")
        try:
            material = json.load(handle)
        except (ValueError, UnicodeError):
            raise BuildError("Material is not valid UTF-8 JSON.") from None
    if not isinstance(material, dict):
        raise BuildError("Material must be a JSON object.")
    if set(material) - ALLOWED_KEYS:
        raise BuildError("Material has unexpected fields; provide client metadata only, without credentials or private keys.")
    if REQUIRED_KEYS - set(material):
        raise BuildError("Material is missing required client metadata fields.")
    return validate_material(material)


def host(value: object, *, dns_only: bool = False) -> str:
    if not isinstance(value, str) or not value or value != value.strip():
        raise BuildError("Server and servername must be nonempty hostnames or IP literals.")
    if "%" in value or value.startswith("["):
        raise BuildError("Use a bare IP literal without an IPv6 zone ID, or a valid DNS hostname.")
    try:
        parsed = ipaddress.ip_address(value)
    except ValueError:
        pass
    else:
        if dns_only:
            raise BuildError("Servername must be a DNS hostname.")
        return str(parsed)
    if ":" in value or "%" in value or value.startswith("["):
        raise BuildError("Use a bare IP literal, or a valid DNS hostname.")
    try:
        encoded = value.encode("idna").decode("ascii").lower()
    except UnicodeError:
        raise BuildError("Invalid DNS hostname.") from None
    if len(encoded) > 253 or encoded.endswith("."):
        raise BuildError("Invalid DNS hostname length or trailing dot.")
    labels = encoded.split(".")
    if any(not re.fullmatch(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?", label) for label in labels):
        raise BuildError("Invalid DNS hostname.")
    # Do not treat a malformed dotted IPv4 literal as a DNS hostname.
    if all(label.isdigit() for label in labels):
        raise BuildError("Invalid numeric server address.")
    return encoded


def port(value: object, label: str = "Port") -> int:
    if isinstance(value, bool) or not isinstance(value, int) or not 1 <= value <= 65535:
        raise BuildError(label + " must be an integer from 1 to 65535.")
    return value


def validate_material(material: dict) -> dict:
    result = dict(material)
    result["server"] = host(material["server"])
    result["servername"] = host(material["servername"], dns_only=True)
    result["port"] = port(material["port"], "Server port")
    value = material["uuid"]
    if not isinstance(value, str) or not re.fullmatch(r"[0-9a-fA-F]{8}(?:-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12}", value):
        raise BuildError("UUID must use the standard hyphenated form.")
    try:
        result["uuid"] = str(uuid.UUID(value))
    except ValueError:
        raise BuildError("Invalid UUID.") from None
    value = material["public_key"]
    if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9_-]{43}", value):
        raise BuildError("Public key must be an unpadded base64url encoding of 32 bytes.")
    try:
        decoded = base64.b64decode(value + "=", altchars=b"-_", validate=True)
    except (ValueError, binascii.Error):
        raise BuildError("Invalid public key encoding.") from None
    if len(decoded) != 32 or base64.urlsafe_b64encode(decoded).decode().rstrip("=") != value:
        raise BuildError("Public key must be a canonical base64url encoding of 32 bytes.")
    value = material["short_id"]
    if not isinstance(value, str) or not re.fullmatch(r"(?:[0-9a-fA-F]{2}){1,8}", value):
        raise BuildError("Short ID must contain an even number of hex digits from 2 to 16.")
    result["short_id"] = value.lower()
    if result.get("flow", "xtls-rprx-vision") != "xtls-rprx-vision":
        raise BuildError("This helper supports xtls-rprx-vision flow only.")
    result["flow"] = "xtls-rprx-vision"
    return result


def profile(material: dict, name: str, local_port: int) -> dict:
    node = {
        "name": name,
        "type": "vless",
        "server": material["server"],
        "port": material["port"],
        "uuid": material["uuid"],
        "network": "tcp",
        "tls": True,
        "udp": True,
        "flow": material["flow"],
        "packet-encoding": "xudp",
        "servername": material["servername"],
        "client-fingerprint": "chrome",
        "skip-cert-verify": False,
        "reality-opts": {
            "public-key": material["public_key"],
            "short-id": material["short_id"],
        },
    }
    return {
        "mixed-port": local_port,
        "allow-lan": False,
        "bind-address": "127.0.0.1",
        "ipv6": False,
        "mode": "rule",
        "log-level": "warning",
        "dns": {
            "enable": True,
            "ipv6": False,
            "enhanced-mode": "redir-host",
            "respect-rules": True,
            "nameserver": ["https://1.1.1.1/dns-query"],
            "proxy-server-nameserver": ["https://1.1.1.1/dns-query"],
        },
        "proxies": [node],
        "proxy-groups": [{"name": "PROXY", "type": "select", "proxies": [name]}],
        "rules": ["MATCH,PROXY"],
    }


def share_uri(material: dict, name: str) -> str:
    address = material["server"]
    if ":" in address:
        address = "[" + address + "]"
    query = urlencode({
        "encryption": "none",
        "security": "reality",
        "type": "tcp",
        "flow": material["flow"],
        "sni": material["servername"],
        "fp": "chrome",
        "pbk": material["public_key"],
        "sid": material["short_id"],
    })
    return "vless://" + material["uuid"] + "@" + address + ":" + str(material["port"]) + "?" + query + "#" + quote(name, safe="")


def encoded_profile(value: dict) -> bytes:
    return (json.dumps(value, ensure_ascii=False, indent=2) + "\n").encode("utf-8")


def output_directory(raw: str) -> tuple[Path, int]:
    path = checked_path(raw)
    if path == Path(path.anchor) or path == Path.home():
        raise BuildError("Use a dedicated artifact directory, not a filesystem root or home directory.")
    if not path.parent.is_dir():
        raise BuildError("The output directory's parent must already exist.")
    try:
        path.mkdir(mode=0o700)
    except FileExistsError:
        pass
    flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0)
    fd = os.open(path, flags)
    try:
        status = os.fstat(fd)
        if not stat.S_ISDIR(status.st_mode) or status.st_uid != os.geteuid():
            raise BuildError("Output must be a directory owned by the current user.")
        known = set(FILENAMES) | {"shadowrocket-reality-qr.png"}
        if set(os.listdir(fd)) - known:
            raise BuildError("Output directory contains unrelated files; use a dedicated artifact directory.")
        os.fchmod(fd, 0o700)
    except Exception:
        os.close(fd)
        raise
    return path, fd


def target_status(directory_fd: int, name: str) -> os.stat_result | None:
    try:
        status = os.stat(name, dir_fd=directory_fd, follow_symlinks=False)
    except FileNotFoundError:
        return None
    if stat.S_ISLNK(status.st_mode) or not stat.S_ISREG(status.st_mode):
        raise BuildError("Output targets must be regular files, without symlinks.")
    return status


def atomic_write(directory_fd: int, name: str, content: bytes, overwrite: bool) -> None:
    temp = ".reality-" + secrets.token_hex(16) + ".tmp"
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0)
    fd = os.open(temp, flags, 0o600, dir_fd=directory_fd)
    try:
        with os.fdopen(fd, "wb") as handle:
            os.fchmod(handle.fileno(), 0o600)
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        target_status(directory_fd, name)
        if overwrite:
            os.replace(temp, name, src_dir_fd=directory_fd, dst_dir_fd=directory_fd)
        else:
            # A hard link publishes the complete file with atomic no-clobber semantics.
            os.link(temp, name, src_dir_fd=directory_fd, dst_dir_fd=directory_fd, follow_symlinks=False)
            os.unlink(temp, dir_fd=directory_fd)
    finally:
        try:
            os.unlink(temp, dir_fd=directory_fd)
        except FileNotFoundError:
            pass


def build(args: argparse.Namespace) -> int:
    material = load_material(args.material)
    local_port = port(args.local_port, "Local port")
    test_port = port(args.test_port, "Test port")
    if local_port == test_port:
        raise BuildError("Use different local and isolated test ports.")
    if not args.name or args.name == "PROXY" or any(ord(c) < 32 or ord(c) == 127 for c in args.name):
        raise BuildError("Node name must be nonempty, contain no control characters, and differ from PROXY.")
    uri = share_uri(material, args.name)
    artifacts = {
        FILENAMES[0]: encoded_profile(profile(material, args.name, local_port)),
        FILENAMES[1]: (uri + "\n").encode("utf-8"),
        FILENAMES[2]: encoded_profile(profile(material, args.name, test_port)),
    }
    if args.qr:
        try:
            import qrcode
        except ImportError:
            raise BuildError("Optional QR output needs the already installed qrcode package; no packages were installed.") from None
        buffer = io.BytesIO()
        try:
            qrcode.make(uri).save(buffer, format="PNG")
        except Exception:
            raise BuildError("Optional QR rendering failed; no client artifacts were written.") from None
        artifacts["shadowrocket-reality-qr.png"] = buffer.getvalue()
    out, directory_fd = output_directory(args.out)
    try:
        # Check the whole set before publishing any file.
        for name in artifacts:
            if target_status(directory_fd, name) is not None and not args.overwrite:
                raise BuildError("An output file already exists; use a new directory or explicit --overwrite.")
        for name, content in artifacts.items():
            atomic_write(directory_fd, name, content, args.overwrite)
        os.fsync(directory_fd)
    finally:
        os.close(directory_fd)
    print("Created " + str(len(artifacts)) + " protected client artifacts in " + str(out))
    print("Profiles route traffic entering the proxy to the selected node; import and coverage tests are separate steps.")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--material", required=True, help="Metadata-only JSON file (no credentials/private keys).")
    parser.add_argument("--out", required=True, help="Dedicated output directory; created/protected as mode 0700.")
    parser.add_argument("--name", default="VPS-REALITY", help="Node display name.")
    parser.add_argument("--local-port", type=int, default=7890, help="Main profile mixed proxy port (default 7890).")
    parser.add_argument("--test-port", type=int, default=17893, help="Isolated test mixed proxy port (default 17893).")
    parser.add_argument("--overwrite", action="store_true", help="Explicitly replace this helper's named output files.")
    parser.add_argument("--qr", action="store_true", help="Also render a private PNG using an already installed qrcode package.")
    args = parser.parse_args()
    try:
        return build(args)
    except (BuildError, OSError) as error:
        # OS errors may include file paths; never include raw input values or JSON.
        message = str(error) if isinstance(error, BuildError) else "File operation failed (" + str(error.errno) + ")."
        print("Error: " + message, file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
