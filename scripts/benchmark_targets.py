#!/usr/bin/env python3
"""Benchmark TLS targets from the machine running this script; emit JSON only.

Requires OpenSSL >= 1.1.1 and GNU timeout (or gtimeout). No configuration is
changed. Measurements include DNS, TCP, TLS, and process startup; they do not
measure proxy throughput. Run on the VPS for VPS-to-target measurements.
"""

import argparse
import json
import math
import re
import shutil
import statistics
import subprocess
import sys
import time
from typing import Any, Callable, Dict, List, Optional


DOMAIN_LABEL = re.compile(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\Z", re.ASCII)
TLS_VERSION = re.compile(r"\bTLSv?1\.[0-3]\b", re.IGNORECASE)
TLS_13 = re.compile(r"\bTLSv?1\.3\b", re.IGNORECASE)
H2 = re.compile(r"\bALPN protocol\s*:\s*h2\b", re.IGNORECASE)
VERIFIED = re.compile(
    r"Verify return code\s*:\s*0\s*\(ok\)|Verification\s*:\s*OK\b",
    re.IGNORECASE,
)


def valid_domain(value: str) -> str:
    """Accept DNS names only, with no shell syntax, ports, paths, or IP literals."""
    domain = value.lower()
    if domain.endswith("."):
        domain = domain[:-1]
    labels = domain.split(".")
    if (
        not domain
        or len(domain) > 253
        or len(labels) < 2
        or not any("a" <= char <= "z" for char in labels[-1])
        or any(not DOMAIN_LABEL.fullmatch(label) for label in labels)
    ):
        raise argparse.ArgumentTypeError(
            "Invalid DNS hostname: use an ASCII domain without a port or URL"
        )
    return domain


def positive_timeout(value: str) -> float:
    try:
        number = float(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("timeout must be a number") from exc
    if not math.isfinite(number) or not 0.05 <= number <= 60:
        raise argparse.ArgumentTypeError("timeout must be between 0.05 and 60 seconds")
    return number


def round_count(value: str) -> int:
    try:
        number = int(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("rounds must be an integer") from exc
    if not 1 <= number <= 20:
        raise argparse.ArgumentTypeError("rounds must be between 1 and 20")
    return number


def error_reason(output: str, exit_code: int) -> str:
    """Return a small reason without copying certificates or arbitrary output."""
    lowered = output.lower()
    if "verify error" in lowered or "verification error" in lowered or "certificate verify failed" in lowered:
        return "certificate or hostname verification failed"
    if "getaddrinfo" in lowered or "connect:errno" in lowered or "connection refused" in lowered or "name or service not known" in lowered:
        return "DNS resolution or TCP connection failed"
    if "unexpected eof" in lowered:
        return "peer closed the connection unexpectedly"
    if "alert" in lowered or "unsupported protocol" in lowered or "no protocols available" in lowered:
        return "TLS protocol negotiation failed"
    return "OpenSSL handshake failed (exit {})".format(exit_code)


def probe(
    domain: str,
    limit: float,
    openssl_bin: str,
    timeout_bin: str,
    compatibility: bool = False,
    runner: Callable[..., Any] = subprocess.run,
    clock: Callable[[], int] = time.monotonic_ns,
) -> Dict[str, Any]:
    command = [
        timeout_bin,
        "--signal=TERM",
        "--kill-after=1s",
        "{:g}s".format(limit),
        openssl_bin,
        "s_client",
        "-connect",
        domain + ":443",
        "-servername",
        domain,
    ]
    if compatibility:
        command.extend(["-tls1_3", "-alpn", "h2", "-verify_hostname", domain, "-verify_return_error"])
    else:
        command.append("-brief")

    started = clock()
    try:
        # GNU timeout bounds the process. Do not pass subprocess.run(timeout=...):
        # its POSIX timed wait can add polling delay to short handshake timings.
        completed = runner(command, input="", capture_output=True, text=True, check=False)
    except OSError:
        result: Dict[str, Any] = {
            "status": "tool_error",
            "elapsed_ms": round((clock() - started) / 1_000_000, 3),
            "exit_code": None,
            "error": "could not execute OpenSSL or GNU timeout",
        }
        if compatibility:
            result.update(tls_1_3=False, http2=False, certificate_and_hostname_verified=False, checks_passed=False)
        return result

    elapsed_ms = round((clock() - started) / 1_000_000, 3)
    output = (completed.stdout or "") + "\n" + (completed.stderr or "")
    code = completed.returncode
    handshake_complete = bool(TLS_VERSION.search(output))
    if code in (124, 137):
        status = "timeout"
        reason = "handshake exceeded the configured timeout"
    elif code in (125, 126, 127):
        status = "tool_error"
        reason = "GNU timeout or OpenSSL could not run"
    elif code != 0:
        status = "error"
        reason = error_reason(output, code)
    elif not handshake_complete:
        status = "error"
        reason = "OpenSSL did not report a completed TLS handshake"
    else:
        status = "ok"
        reason = None

    result = {"status": status, "elapsed_ms": elapsed_ms, "exit_code": code}
    if reason:
        result["error"] = reason
    if compatibility:
        tls13 = status == "ok" and bool(TLS_13.search(output))
        http2 = status == "ok" and bool(H2.search(output))
        verified = status == "ok" and bool(VERIFIED.search(output))
        result.update(
            tls_1_3=tls13,
            http2=http2,
            certificate_and_hostname_verified=verified,
            checks_passed=tls13 and http2 and verified,
        )
    return result


def summarize(samples: List[Dict[str, Any]]) -> Dict[str, Any]:
    successful = [sample["elapsed_ms"] for sample in samples if sample["status"] == "ok"]
    return {
        "success_count": len(successful),
        "failure_count": len(samples) - len(successful),
        "timeout_count": sum(sample["status"] == "timeout" for sample in samples),
        "median_ms": round(statistics.median(successful), 3) if successful else None,
        "min_ms": min(successful) if successful else None,
        "max_ms": max(successful) if successful else None,
    }


def rank_results(results: List[Dict[str, Any]]) -> List[str]:
    # A host with one fast success must not outrank a host succeeding every round.
    ranked = sorted(
        results,
        key=lambda item: (
            -item["summary"]["success_count"],
            item["summary"]["median_ms"] if item["summary"]["median_ms"] is not None else math.inf,
            item["domain"],
        ),
    )
    return [item["domain"] for item in ranked]


def resolve_executable(value: str, parser: argparse.ArgumentParser, label: str) -> str:
    resolved = shutil.which(value)
    if not resolved:
        parser.error("{} executable was not found: {}".format(label, value))
    return resolved


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--domains", nargs="+", required=True, type=valid_domain)
    parser.add_argument("--baseline", type=valid_domain, default="www.microsoft.com")
    parser.add_argument("--rounds", type=round_count, default=3)
    parser.add_argument("--timeout", type=positive_timeout, default=1.0, help="seconds per timing probe (default: 1)")
    parser.add_argument("--compat-timeout", type=positive_timeout, default=3.0, help="seconds per compatibility probe (default: 3)")
    parser.add_argument("--no-compatibility", action="store_true", help="skip the additional TLS 1.3, HTTP/2, and certificate checks")
    parser.add_argument("--openssl-bin", default="openssl")
    parser.add_argument("--timeout-bin", default=shutil.which("timeout") or shutil.which("gtimeout") or "timeout")
    args = parser.parse_args(argv)
    domains = list(dict.fromkeys(args.domains + [args.baseline]))
    if len(domains) > 50:
        parser.error("at most 50 unique domains including the baseline are allowed")
    openssl_bin = resolve_executable(args.openssl_bin, parser, "OpenSSL")
    timeout_bin = resolve_executable(args.timeout_bin, parser, "GNU timeout")

    results: List[Dict[str, Any]] = [
        {"domain": domain, "is_baseline": domain == args.baseline, "samples": []}
        for domain in domains
    ]
    # Interleave hosts each round so one host is not measured only during one burst.
    for round_index in range(1, args.rounds + 1):
        for item in results:
            sample = probe(item["domain"], args.timeout, openssl_bin, timeout_bin)
            item["samples"].append(dict(round=round_index, **sample))
    for item in results:
        item["summary"] = summarize(item["samples"])
        item["compatibility"] = (
            {"status": "skipped"}
            if args.no_compatibility
            else probe(item["domain"], args.compat_timeout, openssl_bin, timeout_bin, compatibility=True)
        )

    output = {
        "schema_version": 1,
        "measurement": "local-machine-to-target TLS handshake, including DNS/TCP/TLS/process startup; not throughput",
        "parameters": {
            "rounds": args.rounds,
            "timeout_seconds": args.timeout,
            "compatibility_timeout_seconds": args.compat_timeout,
            "baseline": args.baseline,
            "compatibility_enabled": not args.no_compatibility,
        },
        "ranking_policy": "success count descending, then successful median milliseconds ascending; compatibility is reported separately",
        "ranking": rank_results(results),
        "results": results,
    }
    json.dump(output, sys.stdout, indent=2, ensure_ascii=False, allow_nan=False)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        sys.exit(130)
