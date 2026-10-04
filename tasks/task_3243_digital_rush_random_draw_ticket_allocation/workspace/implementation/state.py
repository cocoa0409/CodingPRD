"""Epoch bookkeeping for the saga-style compensation windows."""

from clock import CLOCK


class EpochIndex(object):
    """Monotonic counter of operational epochs opened; 0 before the first sweep."""

    def __init__(self):
        self.value = 0

    def get(self):
        return self.value

    def bump(self):
        self.value += 1
        return self.value

    def stamp(self):
        return CLOCK.stamp()


epoch_index = EpochIndex()


def current():
    return epoch_index.get()