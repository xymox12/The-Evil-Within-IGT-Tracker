# controller.py

from model import TimerState, DisplayInfo, update_timer_state
from memory_reader import MemoryReader


class TimerController:
    def __init__(self) -> None:
        self.reader = MemoryReader()
        self.state = TimerState()

    def tick(self) -> DisplayInfo:
        snap = self.reader.read_snapshot()
        self.state, info = update_timer_state(self.state, snap)
        return info
