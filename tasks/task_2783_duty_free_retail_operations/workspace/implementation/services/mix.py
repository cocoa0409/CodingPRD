"""Rolling 30-day traveller nationality mix (PRD section 3.2)."""
from datetime import timedelta

import clock
import db

WINDOW_DAYS = 30


def compute(terminal_id):
    now = clock.now()
    cutoff = now - timedelta(days=WINDOW_DAYS)
    pool = []
    for itinerary in db.ordered(db.itineraries):
        if itinerary["departure_terminal_id"] != terminal_id:
            continue
        if itinerary["scan_status"] not in ("SCANNED", "AMENDED"):
            continue
        if not itinerary["scanned_at"]:
            continue
        scanned_at = clock.parse(itinerary["scanned_at"])
        if cutoff <= scanned_at <= now:
            pool.append(itinerary)
    size = len(pool)
    mix = {}
    if size:
        counts = {}
        for itinerary in pool:
            nationality = itinerary["nationality_code"]
            counts[nationality] = counts.get(nationality, 0) + 1
        for nationality, count in counts.items():
            mix[nationality] = (count * 10000) // size
    return size, mix


def refresh(terminal):
    """Recompute and store the mix; the caller owns the version increment."""
    size, mix = compute(terminal["id"])
    terminal["scanned_itinerary_count_30d"] = size
    terminal["traveler_nationality_mix"] = mix
