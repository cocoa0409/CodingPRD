"""Payload factories and calendar helpers.

One factory per creatable resource, covering input fields only (system and
computed fields are never sent). Every factory accepts ``**overrides`` so a
test controls exactly the fields it cares about.

The calendar helpers exist because the contract's deadlines, windows and week
arithmetic all read the logical clock (PRD §2.4): tests derive weeks and
instants from ``CLOCK_DEFAULT`` (or from wherever they moved the clock)
instead of hand-writing date strings.
"""

from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from .constants import CLOCK_DEFAULT, CURRENT_WEEK_DEFAULT


# ── Calendar helpers ────────────────────────────────────────────────────────

def parse_instant(value: str) -> datetime:
    """Parse an ISO 8601 UTC instant (``...Z`` or offset form)."""
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def format_instant(dt: datetime) -> str:
    """Render a datetime as ``YYYY-MM-DDTHH:MM:SSZ``."""
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def iso_week_of(instant_iso: str) -> str:
    """ISO week string ``YYYY-Www`` of the week containing the instant."""
    year, week, _ = parse_instant(instant_iso).isocalendar()
    return f"{year}-W{week:02d}"


def add_days(instant_iso: str, days: int) -> str:
    return format_instant(parse_instant(instant_iso) + timedelta(days=days))


def add_minutes(instant_iso: str, minutes: int) -> str:
    return format_instant(parse_instant(instant_iso) + timedelta(minutes=minutes))


def add_hours(instant_iso: str, hours: int) -> str:
    return format_instant(parse_instant(instant_iso) + timedelta(hours=hours))


def add_weeks_to_week(week_str: str, weeks: int) -> str:
    """Advance an ISO week string by ``weeks`` weeks (may be negative)."""
    monday = datetime.strptime(f"{week_str}-1", "%G-W%V-%u")
    monday += timedelta(weeks=weeks)
    year, week, _ = monday.isocalendar()
    return f"{year}-W{week:02d}"


def week_of_clock_default() -> str:
    return iso_week_of(CLOCK_DEFAULT)


# Derived week landmarks relative to the fresh-deployment clock reading.
WEEK_CURRENT = week_of_clock_default()          # ISO week of the default clock
WEEK_NEXT = add_weeks_to_week(WEEK_CURRENT, 1)
WEEK_PLUS_2 = add_weeks_to_week(WEEK_CURRENT, 2)
WEEK_PLUS_3 = add_weeks_to_week(WEEK_CURRENT, 3)
WEEK_PLUS_4 = add_weeks_to_week(WEEK_CURRENT, 4)
WEEK_PLUS_5 = add_weeks_to_week(WEEK_CURRENT, 5)
WEEK_PLUS_6 = add_weeks_to_week(WEEK_CURRENT, 6)
WEEK_MINUS_1 = add_weeks_to_week(WEEK_CURRENT, -1)

# A measurement window comfortably after the default clock (PRD §3.2 requires
# measure_window_start >= the logical clock).
MEASURE_WINDOW_START_DEFAULT = "2026-09-02T09:00:00Z"
MEASURE_WINDOW_END_DEFAULT = "2026-09-02T10:00:00Z"


# ── Shared building blocks ──────────────────────────────────────────────────

def family_spec(
    family_code: str = "F1",
    standard_price_cents: int = 10000,
    base_lead_weeks: int = 3,
    complexity_units_per_cabinet: int = 1,
    **overrides: Any,
) -> Dict[str, Any]:
    spec = {
        "family_code": family_code,
        "standard_price_cents": standard_price_cents,
        "base_lead_weeks": base_lead_weeks,
        "complexity_units_per_cabinet": complexity_units_per_cabinet,
    }
    spec.update(overrides)
    return spec


def order_line(
    family_code: str = "F1",
    finish_code: str = "OAK",
    quantity: int = 1,
    **overrides: Any,
) -> Dict[str, Any]:
    line = {"family_code": family_code, "finish_code": finish_code, "quantity": quantity}
    line.update(overrides)
    return line


def clock_payload(to_iso8601: str = CLOCK_DEFAULT, **overrides: Any) -> Dict[str, Any]:
    payload = {"to_iso8601": to_iso8601}
    payload.update(overrides)
    return payload


# ── Accounts / programs / lines ─────────────────────────────────────────────

def account_payload(**overrides: Any) -> Dict[str, Any]:
    payload = {
        "name": "Dealer Test",
        "channel": "DEALER",
        "pricing_class": "VOLUME",
        "lead_time_class": "STANDARD",
        "credit_limit_cents": 100_000_000,
        "store_codes": [],
    }
    payload.update(overrides)
    return payload


def retail_account_payload(store_codes: Optional[List[str]] = None, **overrides: Any) -> Dict[str, Any]:
    payload = account_payload(
        name="Retail Test",
        channel="RETAIL",
        pricing_class="STANDARD",
        store_codes=list(store_codes) if store_codes is not None else ["ST-1"],
    )
    payload.update(overrides)
    return payload


def account_status_payload(to_status: str, **overrides: Any) -> Dict[str, Any]:
    payload = {"to_status": to_status}
    payload.update(overrides)
    return payload


def program_payload(account_id: str, **overrides: Any) -> Dict[str, Any]:
    payload = {
        "account_id": account_id,
        "name": "Program",
        "program_discount_pct": 0.0,
    }
    payload.update(overrides)
    return payload


def program_line_payload(
    expected_program_version: int,
    line_code: str = "L1",
    families: Optional[List[Dict[str, Any]]] = None,
    effective_start_week: str = WEEK_CURRENT,
    include_disposition_qty: bool = False,
    **overrides: Any,
) -> Dict[str, Any]:
    """Payload for POST /cabinet/programs/{id}/lines.

    ``old_line_disposition_qty`` is omitted unless ``include_disposition_qty``
    (or an explicit override) asks for it, matching the PRD's optional input.
    """
    payload: Dict[str, Any] = {
        "line_code": line_code,
        "effective_start_week": effective_start_week,
        "families": families if families is not None else [family_spec()],
        "expected_program_version": expected_program_version,
    }
    if include_disposition_qty:
        payload["old_line_disposition_qty"] = 0
    payload.update(overrides)
    return payload


def disposition_action_payload(action_type: str, qty: int, **overrides: Any) -> Dict[str, Any]:
    payload = {"action_type": action_type, "qty": qty}
    payload.update(overrides)
    return payload


# ── Finish batches / capacity ───────────────────────────────────────────────

def finish_batch_payload(**overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "finish_code": "OAK",
        "batch_code": "B1",
        "lab_l": 50,
        "lab_a": 20,
        "lab_b": 30,
        "effective_from": "2026-08-01T00:00:00Z",
    }
    payload.update(overrides)
    return payload


def production_slot_payload(**overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "plant_code": "PLANT_EAST",
        "family_code": "F1",
        "week": WEEK_NEXT,
        "capacity_units": 100,
    }
    payload.update(overrides)
    return payload


# ── Design jobs ─────────────────────────────────────────────────────────────

def design_job_payload(account_id: str, program_id: str, **overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "account_id": account_id,
        "program_id": program_id,
        "store_code": "ST-1",
        "measure_window_start": MEASURE_WINDOW_START_DEFAULT,
        "measure_window_end": MEASURE_WINDOW_END_DEFAULT,
    }
    payload.update(overrides)
    return payload


def design_job_transition_payload(to_status: str, **overrides: Any) -> Dict[str, Any]:
    payload = {"to_status": to_status}
    payload.update(overrides)
    return payload


def design_job_convert_payload(**overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "destination_type": "STORE",
        "store_code": "ST-1",
        "requested_delivery_week": WEEK_PLUS_4,
    }
    payload.update(overrides)
    return payload


# ── Orders ──────────────────────────────────────────────────────────────────

def order_payload(account_id: str, program_id: str, **overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "account_id": account_id,
        "program_id": program_id,
        "destination_type": "JOB_SITE",
        "jobsite_address": "1 Job Ln",
        "requested_delivery_week": WEEK_PLUS_4,
        "lines": [order_line()],
    }
    payload.update(overrides)
    return payload


def store_order_payload(account_id: str, program_id: str, store_code: str, **overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "account_id": account_id,
        "program_id": program_id,
        "destination_type": "STORE",
        "store_code": store_code,
        "requested_delivery_week": WEEK_PLUS_4,
        "lines": [order_line()],
    }
    payload.update(overrides)
    return payload


def order_transition_payload(to_status: str, **overrides: Any) -> Dict[str, Any]:
    payload = {"to_status": to_status}
    payload.update(overrides)
    return payload


def order_financial_payload(to_status: str, **overrides: Any) -> Dict[str, Any]:
    payload = {"to_status": to_status}
    payload.update(overrides)
    return payload


# ── Claims / replacements / shipments / resets ──────────────────────────────

def claim_payload(shipment_id: str, order_id: str, **overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "shipment_id": shipment_id,
        "order_id": order_id,
        "line_index": 0,
        "claimed_qty": 1,
    }
    payload.update(overrides)
    return payload


def claim_transition_payload(to_status: str, **overrides: Any) -> Dict[str, Any]:
    payload = {"to_status": to_status}
    payload.update(overrides)
    return payload


def shipment_transition_payload(to_status: str, **overrides: Any) -> Dict[str, Any]:
    payload = {"to_status": to_status}
    payload.update(overrides)
    return payload


def replacement_transition_payload(to_status: str, **overrides: Any) -> Dict[str, Any]:
    payload = {"to_status": to_status}
    payload.update(overrides)
    return payload


def display_reset_transition_payload(to_status: str, **overrides: Any) -> Dict[str, Any]:
    payload = {"to_status": to_status}
    payload.update(overrides)
    return payload
