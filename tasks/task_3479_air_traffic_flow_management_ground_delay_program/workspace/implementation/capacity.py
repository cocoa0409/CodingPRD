"""Capacity forecasting, rate gates, and the constraint-event cascades.

- calculations.capacity_forecast_rate (PLANNING / OPERATIONAL variants)
- calculations.max_feasible_rate (ground-stop zeroing, gate forecast, AFP load)
- implied capacity used by the auto-downgrade cascade (PRD 3.2)
- the confirm/extend cascades: forecast STALE + TMI ACTIVE -> REVISING

All multiplier arithmetic uses exact Fractions so flooring is deterministic.
"""

from fractions import Fraction

from constants import (
    EVENT_TYPE_STEPS,
    GDP_VALID_RATES,
    MIN_CAPACITY_FLOOR_PCT,
    REPORTED_EVENT_WEIGHT,
)
from errors import ApiError
from storage import DB, create_record, touch
from validation import windows_overlap

# Exact rational forms of the PRD step/weight constants.
_STEP_FRACTIONS = {
    event_type: Fraction(str(step)) for event_type, step in EVENT_TYPE_STEPS.items()
}
_REPORTED_WEIGHT = Fraction(str(REPORTED_EVENT_WEIGHT))
_FLOOR_MULTIPLIER = Fraction(MIN_CAPACITY_FLOOR_PCT, 100)


def _overlapping_events(facility_id, window_start, window_end):
    return [
        e
        for e in DB["constraint_events"].values()
        if e["facility_id"] == facility_id
        and e["status"] != "CLEARED"
        and windows_overlap(
            e["window_start"], e["window_end"], window_start, window_end
        )
    ]


def _event_factor(event, weight):
    return 1 - _STEP_FRACTIONS[event["event_type"]] * event["severity"] * weight


def compute_forecast(facility, variant, window_start, window_end):
    """Run calculations.capacity_forecast_rate once at forecast creation.

    Returns (predicted_acceptance_rate, included_event_ids). PLANNING includes
    CONFIRMED events only; OPERATIONAL additionally includes REPORTED events at
    REPORTED_EVENT_WEIGHT. CLEARED events are always excluded.
    """
    raw = Fraction(1)
    included = []
    events = _overlapping_events(facility["id"], window_start, window_end)
    events.sort(key=lambda e: (e["created_at"], e["_seq"]))
    for event in events:
        if event["status"] == "CONFIRMED":
            weight = Fraction(1)
        elif event["status"] == "REPORTED" and variant == "OPERATIONAL":
            weight = _REPORTED_WEIGHT
        else:
            continue
        raw *= _event_factor(event, weight)
        included.append(event["id"])
    effective = max(raw, _FLOOR_MULTIPLIER)
    predicted = facility["base_acceptance_rate"] * effective
    rate = max(1, predicted.numerator // predicted.denominator)
    return rate, included


def select_gate_forecast(facility_id, window_start, window_end):
    """The gate forecast: among PUBLISHED, non-STALE, PLANNING-variant
    forecasts covering [window_start, window_end], the latest published_at
    wins, ties broken by created_at ASC. None when no candidate exists."""
    candidates = [
        f
        for f in DB["forecasts"].values()
        if f["facility_id"] == facility_id
        and f["status"] == "PUBLISHED"
        and f["variant"] == "PLANNING"
        and f["window_start"] <= window_start
        and f["window_end"] >= window_end
    ]
    if not candidates:
        return None
    candidates.sort(
        key=lambda f: (f["created_at"], f["_seq"])
    )  # deterministic base order
    candidates.sort(key=lambda f: f["published_at"], reverse=True)
    return candidates[0]


def max_feasible_rate(facility, window_start, window_end, exclude_tmi_id=None):
    """calculations.max_feasible_rate. Returns (feasible_or_None, gate_forecast).

    feasible is None iff no gate forecast exists (the caller then raises
    ERR_NO_CURRENT_FORECAST). A live overlapping GROUND_STOP (other than the
    candidate) zeroes the answer; otherwise the gate forecast rate is capped by
    the facility base rate and the aggregate load of overlapping non-terminal
    AIRSPACE_FLOW_PROGRAMs (excluding the candidate) is subtracted, floored at
    0.
    """
    forecast = select_gate_forecast(facility["id"], window_start, window_end)
    if forecast is None:
        return None, None
    for other in DB["tmis"].values():
        if (
            other["facility_id"] == facility["id"]
            and other["id"] != exclude_tmi_id
            and other["tmi_type"] == "GROUND_STOP"
            and other["status"] in ("PUBLISHED", "ACTIVE", "REVISING")
            and windows_overlap(
                other["program_start"], other["program_end"], window_start, window_end
            )
        ):
            return 0, forecast
    afp_load = 0
    for other in DB["tmis"].values():
        if (
            other["facility_id"] == facility["id"]
            and other["id"] != exclude_tmi_id
            and other["tmi_type"] == "AIRSPACE_FLOW_PROGRAM"
            and other["status"] in ("PUBLISHED", "ACTIVE", "REVISING")
            and windows_overlap(
                other["program_start"], other["program_end"], window_start, window_end
            )
        ):
            afp_load += other["controlled_rate"]
    feasible = max(
        0,
        min(forecast["predicted_acceptance_rate"], facility["base_acceptance_rate"])
        - afp_load,
    )
    return feasible, forecast


def enforce_capacity_gate(facility, tmi, window_start, window_end, rate):
    """Priority 20: controlled_rate <= max_feasible_rate, recomputed now.
    The forecast gate (ERR_NO_CURRENT_FORECAST) precedes the rate comparison
    because the feasible rate derives from the gate forecast."""
    feasible, forecast = max_feasible_rate(
        facility, window_start, window_end, exclude_tmi_id=tmi["id"]
    )
    if forecast is None:
        raise ApiError(
            "ERR_NO_CURRENT_FORECAST",
            "no PUBLISHED, non-STALE, PLANNING-variant forecast covers the window",
        )
    if rate > feasible:
        raise ApiError(
            "ERR_RATE_EXCEEDS_CAPACITY",
            "controlled_rate %d exceeds max feasible rate %d" % (rate, feasible),
        )


def implied_rate(facility, window_start, window_end):
    """Implied capacity over CONFIRMED events overlapping the window (PRD 3.2):
    base * product(1 - step*severity), multiplier floored at 10% of base, rate
    floored to an integer with a minimum of 1."""
    raw = Fraction(1)
    for event in _overlapping_events(facility["id"], window_start, window_end):
        if event["status"] == "CONFIRMED":
            raw *= _event_factor(event, Fraction(1))
    effective = max(raw, _FLOOR_MULTIPLIER)
    predicted = facility["base_acceptance_rate"] * effective
    return max(1, predicted.numerator // predicted.denominator)


def _largest_gdp_rate_not_exceeding(implied):
    for rate in sorted(GDP_VALID_RATES, reverse=True):
        if rate <= implied:
            return rate
    return GDP_VALID_RATES[0]  # 6 when the implied rate falls below 6


def cascade_event_confirmed(event):
    """PRD 3.2 confirmation/extension cascades:
    link 1 — every overlapping PUBLISHED forecast on the facility -> STALE;
    link 2 — each overlapping ACTIVE GDP whose implied capacity collapsed below
    its controlled_rate auto-transitions to REVISING with a
    SYSTEM_AUTO_DOWNGRADE TMIRevision.
    """
    facility = DB["facilities"].get(event["facility_id"])
    forecasts = [
        f
        for f in DB["forecasts"].values()
        if f["facility_id"] == event["facility_id"]
        and f["status"] == "PUBLISHED"
        and windows_overlap(
            f["window_start"], f["window_end"], event["window_start"], event["window_end"]
        )
    ]
    forecasts.sort(key=lambda f: (f["created_at"], f["_seq"]))
    for forecast in forecasts:
        forecast["status"] = "STALE"
        touch(forecast)

    tmis = [
        t
        for t in DB["tmis"].values()
        if t["facility_id"] == event["facility_id"]
        and t["tmi_type"] == "GROUND_DELAY_PROGRAM"
        and t["status"] == "ACTIVE"
        and windows_overlap(
            t["program_start"], t["program_end"], event["window_start"], event["window_end"]
        )
    ]
    tmis.sort(key=lambda t: (t["created_at"], t["_seq"]))
    for tmi in tmis:
        implied = implied_rate(facility, tmi["program_start"], tmi["program_end"])
        if implied < tmi["controlled_rate"]:
            new_rate = _largest_gdp_rate_not_exceeding(implied)
            create_record(
                "revisions",
                {
                    "tmi_id": tmi["id"],
                    "revision_index": tmi["revision_count"] + 1,
                    "previous_controlled_rate": tmi["controlled_rate"],
                    "new_controlled_rate": new_rate,
                    "previous_program_end": None,
                    "new_program_end": None,
                    "origin": "SYSTEM_AUTO_DOWNGRADE",
                    "reason": "AUTO_CAPACITY_DOWNGRADE",
                    "applied": False,
                    "applied_at": None,
                },
            )
            tmi["revision_count"] += 1
            tmi["status"] = "REVISING"
            touch(tmi)
