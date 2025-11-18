# model.py

from dataclasses import dataclass
from typing import Optional


def format_hhmmss(total_seconds: Optional[int]) -> str:
    if total_seconds is None:
        return "--:--:--"
    if total_seconds < 0:
        total_seconds = 0
    h = total_seconds // 3600
    m = (total_seconds % 3600) // 60
    s = total_seconds % 60
    return f"{h:02d}:{m:02d}:{s:02d}"


@dataclass
class GameSnapshot:
    attached: bool
    igt_seconds: Optional[int]
    chapter_val: Optional[int]
    sub_name: str          # for display (B if non-empty, else A)
    subA_name: str = ""    # NEW: raw subA text
    subB_name: str = ""    # NEW: raw subB text


@dataclass
class TimerState:
    # chapter / subsections
    current_chapter: Optional[int] = None
    current_sub_name: str = ""
    current_sub_index: Optional[int] = None
    had_real_name: bool = False

    # numbering
    seg_counter: int = 0

    # last segment info
    last_sub_index: Optional[int] = None
    last_sub_duration: Optional[int] = None

    # timings
    last_split_igt: Optional[int] = None
    first_sub_igt: Optional[int] = None
    session_start_igt: Optional[int] = None
    last_seen_igt: Optional[int] = None

    # NEW: subB-based logic
    last_subB_name: str = ""                # last non-empty B we saw
    seen_nonblank_subB_this_chapter: bool = False


@dataclass
class DisplayInfo:
    time_text: str
    chapter_text: str
    current_segment_text: str
    last_segment_text: str
    since_first_text: str
    status_text: str


def update_timer_state(state: TimerState, snap: GameSnapshot) -> tuple[TimerState, DisplayInfo]:
    s = state

    # Not attached → no state changes
    if not snap.attached:
        return s, DisplayInfo(
            time_text="--:--:--",
            chapter_text="--",
            current_segment_text="Current Split: --:--:--",
            last_segment_text="Previous Split: --:--:--",
            since_first_text="Total Split Time: --:--:--",
            status_text="Not attached (EvilWithin.exe not running)",
        )

    igt = snap.igt_seconds
    chap = snap.chapter_val
    sub_name = snap.sub_name or ""
    subA_name = getattr(snap, "subA_name", "") or ""
    subB_name = getattr(snap, "subB_name", "") or ""

    # Time label
    time_text = format_hhmmss(igt) if igt is not None else "--:--:--"

    # --- Quickload / restart detection: IGT going backwards ---
    if igt is not None and s.last_seen_igt is not None and igt + 1 < s.last_seen_igt:
        # We just quickloaded.

        # If we haven't actually started a run yet, treat this as the start of segment 1.
        if s.current_sub_index is None and s.first_sub_igt is None:
            s.seg_counter = 1
            s.current_sub_index = 1
            if igt is not None and igt > 0:       # <<< guard here
                if s.session_start_igt is None:
                    s.session_start_igt = igt
                s.first_sub_igt = igt
                s.last_split_igt = igt
        else:
            # Mid-run quickload: classify based on subA vs subB.

            if subB_name and subA_name == subB_name:
                # Case 1: Reloaded the segment we're already on.
                s.had_real_name = False
                # DO NOT touch current_sub_index, seg_counter, last_sub_index, last_sub_duration
                if igt is not None and igt > 0:   # <<< guard here
                    s.last_split_igt = igt        # restart timing from this IGT

            else:
                # Case 2: Reloaded an earlier segment (subA != subB, or B blank).
                s.seg_counter = 1
                s.current_sub_index = 1
                s.current_sub_name = ""
                s.had_real_name = False

                # Fresh run timing from this point
                if igt is not None and igt > 0:   # <<< guard here
                    s.first_sub_igt = igt
                    s.last_split_igt = igt

                # Clear previous segment info...
                s.last_sub_index = None
                s.last_sub_duration = None
                s.last_subB_name = ""
                s.seen_nonblank_subB_this_chapter = False

    if igt is not None:
        s.last_seen_igt = igt

    # session_start_igt: first valid IGT we see
    if s.session_start_igt is None and igt is not None and igt > 0:  # <<< add igt > 0
        s.session_start_igt = igt

    # --- Chapter change handling ---
    if chap is not None and chap != s.current_chapter:
        s.current_chapter = chap

        # Reset only name + B-tracking state for this chapter
        s.current_sub_name = ""
        s.had_real_name = False
        s.last_subB_name = ""
        s.seen_nonblank_subB_this_chapter = False

    # Chapter label text
    chapter_text = f"{s.current_chapter}" if s.current_chapter is not None else "--"

    # --- Auto-start first segment when we have chapter + IGT but no index yet ---
    if s.current_chapter is not None and s.current_sub_index is None and igt is not None and igt > 0:  # <<< add igt > 0
        s.seg_counter = 1
        s.current_sub_index = 1
        s.last_split_igt = igt
        if s.first_sub_igt is None:
            s.first_sub_igt = igt

    # --- Subsection naming + B-driven split detection ---
    if s.current_sub_index is not None:
        # 1) Name the current segment if we don't have a name yet.
        #    For segment 1: B is blank, so this will use A.
        if not s.had_real_name:
            if subB_name:
                s.current_sub_name = subB_name
                s.had_real_name = True
            elif subA_name:
                s.current_sub_name = subA_name
                s.had_real_name = True
            elif sub_name:
                # Fallback: whatever composite name we have
                s.current_sub_name = sub_name
                s.had_real_name = True

        # Helper for splitting
        def do_split(new_name: str):
            nonlocal igt
            # Close previous segment
            if igt is not None and s.last_split_igt is not None:
                seg = igt - s.last_split_igt
                if seg < 0:
                    seg = 0
                s.last_sub_duration = seg
                s.last_sub_index = s.current_sub_index

            # Move to next segment
            s.seg_counter += 1
            s.current_sub_index = s.seg_counter
            s.current_sub_name = new_name
            if igt is not None:
                s.last_split_igt = igt

        # 2) B-based rules:
        #    - While subB == ""  → segment 1.
        #    - First time subB becomes non-empty → segment 1 -> 2.
        #    - Every later change of non-empty B → next segment.
        if subB_name:
            # First non-empty B this chapter
            if not s.seen_nonblank_subB_this_chapter:
                s.seen_nonblank_subB_this_chapter = True

                # If we've actually been timing segment 1 (name + start time),
                # first non-empty B marks the boundary 1 -> 2.
                if (
                    s.had_real_name
                    and s.last_split_igt is not None
                    and igt is not None
                    and igt >= s.last_split_igt
                ):
                    do_split(subB_name)

            # Subsequent B changes (segment 2,3,4,...) → split whenever B changes
            elif s.last_subB_name and subB_name != s.last_subB_name:
                if s.last_split_igt is not None and igt is not None and igt >= s.last_split_igt:
                    do_split(subB_name)

        # Remember B for next tick
        if subB_name:
            s.last_subB_name = subB_name

    # Ensure last_split_igt is set once we have an index & IGT
    if s.current_sub_index is not None and s.last_split_igt is None and igt is not None and igt > 0:  # <<< add igt > 0
        s.last_split_igt = igt
        if s.first_sub_igt is None:
            s.first_sub_igt = igt

    # --- Elapsed in current segment ---
    current_sub_elapsed = None
    if s.current_sub_index is not None and igt is not None and s.last_split_igt is not None:
        current_sub_elapsed = igt - s.last_split_igt
        if current_sub_elapsed < 0:
            current_sub_elapsed = 0

    # --- Run time since first segment ---
    origin = s.first_sub_igt if s.first_sub_igt is not None else s.session_start_igt
    run_since_first = None
    if origin is not None and igt is not None:
        run_since_first = igt - origin
        if run_since_first < 0:
            run_since_first = 0

    # --- Build display strings (no numeric segment labels) ---
    if s.current_sub_index is not None:
        # We only care about the time for "Current"
        current_segment_text = (
            f"{format_hhmmss(current_sub_elapsed)}"
        )
    else:
        current_segment_text = "--:--:--"

    if s.last_sub_duration is not None:
        # "Previous" just shows the last completed segment's time
        last_segment_text = (
            f"{format_hhmmss(s.last_sub_duration)}"
        )
    else:
        last_segment_text = "--:--:--"

    since_first_text = "Total Split Time: " + format_hhmmss(run_since_first)

    status_text = ""

    info = DisplayInfo(
        time_text=time_text,
        chapter_text=chapter_text,
        current_segment_text=current_segment_text,
        last_segment_text=last_segment_text,
        since_first_text=since_first_text,
        status_text=status_text,
    )
    return s, info


