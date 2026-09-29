"""The two race readings (PRD 3.7 provisional, PRD 3.8 official)."""

import db
from services import calc


def _division_of_wave(wave):
    return db.get("divisions", wave["division_id"])


def provisional_penalty_total(entry):
    """Charges every recorded penalty, including SKIPPED_UNMARSHALED."""
    total = 0
    for attempt in calc.attempts_of_entry(entry["id"]):
        total += int(attempt["provisional_penalty_seconds"])
    return total


def official_penalty_total(entry):
    """Suppresses voided attempts and every SKIPPED_UNMARSHALED wave-through."""
    voided = entry.get("voided_attempt_ids") or []
    total = 0
    for attempt in calc.attempts_of_entry(entry["id"]):
        if attempt["id"] in voided:
            continue
        if attempt["outcome"] == "SKIPPED_UNMARSHALED":
            continue
        total += int(attempt["provisional_penalty_seconds"])
    return total


def attempt_provisional_penalty(outcome, obstacle):
    """0 for COMPLETED; the obstacle's penalty_seconds for the other three."""
    if outcome == "COMPLETED":
        return 0
    return int(obstacle["penalty_seconds"])


def apply_provisional_penalty(entry):
    entry["provisional_penalty_seconds"] = provisional_penalty_total(entry)


def gun_base(entry, wave):
    if wave.get("actual_start_utc") is None or entry.get("finish_recorded_utc") is None:
        return None
    return db.seconds_between(wave["actual_start_utc"], entry["finish_recorded_utc"])


def chip_base(entry):
    if entry.get("chip_start_utc") is None or entry.get("finish_recorded_utc") is None:
        return None
    return db.seconds_between(entry["chip_start_utc"], entry["finish_recorded_utc"])


def apply_provisional_reading(entry, wave):
    """Stamped by the finish: gun base for every division, all penalties charged."""
    penalty = provisional_penalty_total(entry)
    entry["provisional_penalty_seconds"] = penalty
    base = gun_base(entry, wave)
    entry["provisional_elapsed_seconds"] = None if base is None else base + penalty


def apply_official_reading(entry, wave):
    """Stamped at wave close / DENIED_OFFICIAL, recomputed by UPHELD_ADJUSTED."""
    division = _division_of_wave(wave)
    penalty = official_penalty_total(entry)
    entry["official_penalty_seconds"] = penalty
    if division is not None and division["scoring_mode"] == "CHIP_TIME":
        base = chip_base(entry)
    else:
        base = gun_base(entry, wave)
    entry["official_elapsed_seconds"] = None if base is None else base + penalty
