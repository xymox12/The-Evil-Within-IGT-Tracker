# memory_reader.py

from typing import Optional

import psutil
import pymem
import pymem.process

from evil_within_subsection_logger_v2 import OFFSETS, StringField, read_int_auto, read_ptr
from config import PROC_NAME, BASE_OFFSET, POINTER_OFFSETS
from model import GameSnapshot


def get_module_base(pm: pymem.Pymem, module_name: str) -> int:
    mod = pymem.process.module_from_name(pm.process_handle, module_name)
    return mod.lpBaseOfDll


def resolve_pointer_chain(pm: pymem.Pymem, base_addr: int, base_offset: int, ptr_offsets) -> int:
    addr = base_addr + base_offset
    addr = pm.read_longlong(addr)  # first pointer
    for off in ptr_offsets[:-1]:
        addr = pm.read_longlong(addr + off)
    return addr + ptr_offsets[-1]


class MemoryReader:
    def __init__(self) -> None:
        self.pm: Optional[pymem.Pymem] = None
        self.base_addr: Optional[int] = None
        self.chapter_addr: Optional[int] = None
        self.struct_ptr_rel: Optional[int] = None
        self.subA_reader: Optional[StringField] = None
        self.subB_reader: Optional[StringField] = None

    def attach_if_needed(self) -> None:
        """Attach to EvilWithin.exe if we aren't already."""
        if self.pm is not None:
            return

        try:
            # find process
            for proc in psutil.process_iter(["name"]):
                name = proc.info.get("name")
                if name and name.lower() == PROC_NAME.lower():
                    break
            else:
                # not running
                return

            pm_local = pymem.Pymem(PROC_NAME)
            base = get_module_base(pm_local, PROC_NAME)

            chapter_addr_local = base + OFFSETS["chapter_rel"]
            struct_ptr_rel_local = base + OFFSETS["struct_ptr_rel"]
            subB_addr = base + OFFSETS["subB_abs"]

            def struct_ptr() -> int:
                return read_ptr(pm_local, struct_ptr_rel_local)

            # StringField here matches how you used it in timer002.py:
            # StringField(pm, addr_func, name) and .read() takes NO args.
            subA_reader_local = StringField(
                pm_local,
                lambda: (struct_ptr() + OFFSETS["subA_off"]) if struct_ptr() else 0,
                "subA",
            )
            subB_reader_local = StringField(pm_local, lambda: subB_addr, "subB")

            self.pm = pm_local
            self.base_addr = base
            self.chapter_addr = chapter_addr_local
            self.struct_ptr_rel = struct_ptr_rel_local
            self.subA_reader = subA_reader_local
            self.subB_reader = subB_reader_local

            print("[+] Attached to EvilWithin.exe")
            print(f"[+] Module base: 0x{base:016X}")

        except Exception as e:
            print(f"[!] Failed to attach: {e}")
            self.pm = None
            self.base_addr = None
            self.chapter_addr = None
            self.struct_ptr_rel = None
            self.subA_reader = None
            self.subB_reader = None

    def read_snapshot(self) -> GameSnapshot:
        """Return a GameSnapshot with IGT, chapter and subsection name."""
        self.attach_if_needed()
        if not self.pm or not self.base_addr:
            return GameSnapshot(attached=False, igt_seconds=None, chapter_val=None, sub_name="")

        igt_seconds: Optional[int] = None
        chapter_val: Optional[int] = None
        sub_name = ""

        # --- IGT ---
        try:
            addr = resolve_pointer_chain(self.pm, self.base_addr, BASE_OFFSET, POINTER_OFFSETS)
            igt_seconds = self.pm.read_int(addr)
        except Exception as e:
            print(f"[!] Error reading IGT: {e}")

        # --- Chapter ---
        try:
            chapter_val = read_int_auto(self.pm, self.chapter_addr) if self.chapter_addr else None
        except Exception as e:
            print(f"[!] Error reading chapter: {e}")

        # --- Subsections: read raw A and B, then choose a display name ---
        subA_name = ""
        subB_name = ""
        sub_name = ""

        # Read B (absolute)
        if self.subB_reader is not None:
            try:
                subB_name = (self.subB_reader.read() or "").strip()
            except Exception as e:
                print(f"[!] Error reading subB: {e}")
                subB_name = ""

        # Read A (struct-relative)
        if self.subA_reader is not None:
            try:
                subA_name = (self.subA_reader.read() or "").strip()
            except Exception as e:
                print(f"[!] Error reading subA: {e}")
                subA_name = ""

        # For display / backward compat: prefer B, then A
        if subB_name:
            sub_name = subB_name
        elif subA_name:
            sub_name = subA_name

        return GameSnapshot(
            attached=True,
            igt_seconds=igt_seconds,
            chapter_val=chapter_val,
            sub_name=sub_name,
            subA_name=subA_name,
            subB_name=subB_name,
        )
