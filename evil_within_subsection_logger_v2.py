# evil_within_subsections_logger_simple.py
# Requires: pip install pymem psutil

import argparse
import csv
import os
import signal
import sys
import time
from datetime import datetime
from typing import Optional, Tuple
from datetime import datetime, UTC

import psutil
import pymem


PROCESS_NAME = "EVILWithin.exe"

OFFSETS = {
    "chapter_rel":    0x225DCE8,   # chapter int (or ptr->int)
    "struct_ptr_rel": 0x9C58A88,   # ptr to struct
    "map_name_off":   0x0F0,       # struct + 0x0F0 : map name
    "subA_off":       0x218,       # struct + 0x218 : initial subsection (A)
    "subB_abs":       0x9C83638,   # absolute : live subsection (B)
}

MAX_STR_LEN = 512


# --------------------- low-level utils ---------------------
def find_process(name: str):
    for proc in psutil.process_iter(["pid", "name"]):
        try:
            if proc.info["name"] and proc.info["name"].lower() == name.lower():
                return proc.info["pid"]
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue
    return None


def get_module_base(pm: pymem.Pymem, module_name: str) -> int:
    mod = pymem.process.module_from_name(pm.process_handle, module_name)
    return mod.lpBaseOfDll


def read_ptr(pm: pymem.Pymem, addr: int) -> int:
    try:
        return pm.read_longlong(addr)
    except Exception:
        try:
            return pm.read_int(addr)
        except Exception:
            return 0


def read_int_auto(pm: pymem.Pymem, addr_candidate: int) -> int:
    # direct
    try:
        v = pm.read_int(addr_candidate)
        if v not in (0, -1):
            return v
    except Exception:
        pass
    # pointer-to-int
    try:
        p = read_ptr(pm, addr_candidate)
        if p:
            return pm.read_int(p)
    except Exception:
        pass
    return -1


def read_c_string(pm: pymem.Pymem, addr: int, max_len: int = MAX_STR_LEN) -> str:
    if not addr:
        return ""
    try:
        raw = bytearray()
        for i in range(max_len):
            b = pm.read_bytes(addr + i, 1)
            if not b or b == b"\x00":
                break
            raw += b
        if not raw:
            return ""
        try:
            return raw.decode("utf-8")
        except UnicodeDecodeError:
            return raw.decode("latin-1", errors="replace")
    except Exception:
        return ""


def read_w_string(pm: pymem.Pymem, addr: int, max_len: int = MAX_STR_LEN) -> str:
    if not addr:
        return ""
    try:
        raw = bytearray()
        for i in range(max_len):
            two = pm.read_bytes(addr + i * 2, 2)
            if not two or two == b"\x00\x00":
                break
            raw += two
        if not raw:
            return ""
        return raw.decode("utf-16-le", errors="replace")
    except Exception:
        return ""


# --------------------- fast string field (caches layout) ---------------------
class StringField:
    """
    Read a string that may be:
      - pointer to char*/wchar*
      - inline char[]/wchar[]
    Once a working mode is discovered, it’s cached.
    """
    def __init__(self, pm: pymem.Pymem, addr_provider, name: str):
        self.pm = pm
        self.addr_provider = addr_provider
        self.name = name
        self.mode: Optional[Tuple[str, str]] = None  # ("ptr"|"inline", "c"|"w")

    def _try_mode(self, base_addr: int, mode: Tuple[str, str]) -> str:
        kind, enc = mode
        addr = base_addr
        if kind == "ptr":
            addr = read_ptr(self.pm, base_addr)
        if not addr:
            return ""
        return read_c_string(self.pm, addr) if enc == "c" else read_w_string(self.pm, addr)

    def read(self) -> str:
        base = self.addr_provider()
        if not base:
            return ""
        if self.mode:
            s = self._try_mode(base, self.mode)
            if s:
                return s
            self.mode = None  # fall back to discovery

        for mode in (("ptr", "c"), ("ptr", "w"), ("inline", "c"), ("inline", "w")):
            s = self._try_mode(base, mode)
            if s:
                self.mode = mode
                return s
        return ""


# --------------------- CSV ---------------------
def open_csv(path: str):
    new = not os.path.exists(path)
    f = open(path, "a", newline="", encoding="utf-8")
    w = csv.writer(f)
    if new:
        w.writerow(["timestamp_iso", "chapter", "map_name", "subsection", "source"])
    return f, w


# --------------------- main ---------------------
def main():
    ap = argparse.ArgumentParser(description="Log Evil Within subsections (simple A-on-chapter, B-on-change).")
    ap.add_argument("--interval", type=float, default=0.5, help="Polling interval in seconds (default 0.5).")
    ap.add_argument("--csv", type=str, default="evil_within_chapter_log.csv", help="Output CSV path.")
    ap.add_argument("--debug", action="store_true", help="Print debug info each tick.")
    args = ap.parse_args()

    pid = find_process(PROCESS_NAME)
    if pid is None:
        print(f"[!] Could not find process '{PROCESS_NAME}'. Make sure the game is running.")
        sys.exit(1)

    print(f"[+] Found {PROCESS_NAME} (PID {pid})")
    pm = pymem.Pymem()
    pm.open_process_from_id(pid)

    try:
        base = get_module_base(pm, PROCESS_NAME)
    except Exception as e:
        print(f"[!] Failed to get module base for {PROCESS_NAME}: {e}")
        sys.exit(1)

    print(f"[+] Module base: 0x{base:016X}")
    print(f"[+] Logging to: {os.path.abspath(args.csv)}")
    print("[i] Press Ctrl+C to stop.\n")

    # Precompute addresses
    chapter_addr = base + OFFSETS["chapter_rel"]
    struct_ptr_rel = base + OFFSETS["struct_ptr_rel"]
    subB_addr = base + OFFSETS["subB_abs"]

    # struct ptr provider (single-indirect is enough in practice; if needed, you can add double-indirect here)
    def struct_ptr() -> int:
        return read_ptr(pm, struct_ptr_rel)

    # Fields
    map_reader  = StringField(pm, lambda: (struct_ptr() + OFFSETS["map_name_off"]) if struct_ptr() else 0, "map")
    subA_reader = StringField(pm, lambda: (struct_ptr() + OFFSETS["subA_off"])   if struct_ptr() else 0, "subA")
    subB_reader = StringField(pm, lambda: subB_addr, "subB")

    csv_file, writer = open_csv(args.csv)

    # State
    last_chapter = None
    last_map = ""
    last_logged_sub = None
    seen_this_chapter = set()

    def cleanup(*_):
        try: csv_file.close()
        except Exception: pass
        print("\n[+] Stopped. CSV saved.")
        sys.exit(0)

    signal.signal(signal.SIGINT, cleanup)
    if hasattr(signal, "SIGTERM"):
        signal.signal(signal.SIGTERM, cleanup)

    interval = max(0.05, float(args.interval))
    next_tick = time.monotonic()

    while True:
        now = time.monotonic()
        if now < next_tick:
            time.sleep(max(0.0, next_tick - now))
        next_tick += interval

        # Read chapter
        chapter = read_int_auto(pm, chapter_addr)

        # Chapter change → log A once (initial), refresh map
        if chapter not in (-1, 0) and chapter != last_chapter:
            print(f"[•] Chapter changed -> {chapter}")
            last_chapter = chapter
            seen_this_chapter.clear()
            last_logged_sub = None

            # Map refresh (best-effort)
            new_map = map_reader.read()
            if new_map and new_map != last_map:
                last_map = new_map
                print(f"[•] Map: {last_map}")

            # Log A (initial subsection) if available
            subA = subA_reader.read()
            if subA:
                ts = datetime.now(UTC).isoformat(timespec="seconds")
                writer.writerow([ts, chapter, last_map, subA, "A"])
                csv_file.flush()
                seen_this_chapter.add(subA)
                last_logged_sub = subA
                print(f"[+] {ts} | Chapter {chapter} | {subA} (A)")
            elif args.debug:
                print("[dbg] subA empty at chapter start")

        # In-chapter polling of B only (it’s empty on very first load until the first quicksave)
        subB = subB_reader.read()

        if args.debug:
            print(f"[dbg] chap={chapter} subB='{subB}' map='{last_map}'")

        # First B seen or any subsequent change → log (dedupe within chapter)
        if subB:
            if (not seen_this_chapter) or (subB != last_logged_sub and subB not in seen_this_chapter):
                ts = datetime.now(UTC).isoformat(timespec="seconds")
                writer.writerow([ts, chapter, last_map, subB, "B"])
                csv_file.flush()
                seen_this_chapter.add(subB)
                last_logged_sub = subB
                print(f"[+] {ts} | Chapter {chapter} | {subB} (B)")


if __name__ == "__main__":
    main()
