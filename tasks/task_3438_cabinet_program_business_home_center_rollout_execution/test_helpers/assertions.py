"""Entity assertions and domain invariant checkers.

Each ``assert_<entity>(data)`` validates the shape of one resource body:
system-managed fields (PRD §2.5), enum membership, field presence, and the
nullability the PRD assigns ("null until <event>"). These check structure,
not business outcomes; expected values belong in the tests themselves.
"""

import re
from typing import Any, Dict, Optional

from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid

_WEEK_RE = re.compile(r"^\d{4}-W\d{2}$")


# ── Primitives ──────────────────────────────────────────────────────────────

def assert_iso_week(value: Any, field: str = "week") -> None:
    assert isinstance(value, str) and _WEEK_RE.match(value), (
        f"{field} must be an ISO week string 'YYYY-Www', got {value!r}"
    )


def assert_common_fields(data: Dict[str, Any]) -> None:
    """The four system-managed fields every resource carries (PRD §2.5)."""
    assert is_valid_uuid(data.get("id", "")), f"id must be a UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, (
        f"version must be an integer >= 1, got {data.get('version')!r}"
    )


def _assert_opt_iso(data: Dict[str, Any], field: str) -> None:
    assert field in data, f"{field} must be present (null allowed)"
    if data[field] is not None:
        assert is_iso8601_timestamp(data[field]), f"{field} must be ISO 8601 or null"


def _assert_opt_week(data: Dict[str, Any], field: str) -> None:
    assert field in data, f"{field} must be present (null allowed)"
    if data[field] is not None:
        assert_iso_week(data[field], field)


def _assert_enum(data: Dict[str, Any], field: str, allowed) -> None:
    assert data.get(field) in allowed, f"{field} must be one of {allowed}, got {data.get(field)!r}"


def _assert_int(data: Dict[str, Any], field: str, minimum: Optional[int] = None) -> None:
    assert isinstance(data.get(field), int) and not isinstance(data.get(field), bool), (
        f"{field} must be an integer, got {data.get(field)!r}"
    )
    if minimum is not None:
        assert data[field] >= minimum, f"{field} must be >= {minimum}, got {data[field]}"


def _assert_opt_int(data: Dict[str, Any], field: str) -> None:
    assert field in data, f"{field} must be present (null allowed)"
    if data[field] is not None:
        assert isinstance(data[field], int) and not isinstance(data[field], bool), (
            f"{field} must be an integer or null, got {data[field]!r}"
        )


# ── Entities ────────────────────────────────────────────────────────────────

def assert_account(data: Dict[str, Any]) -> None:
    assert_common_fields(data)
    assert isinstance(data.get("name"), str) and data["name"]
    _assert_enum(data, "channel", {"RETAIL", "DEALER", "BUILDER"})
    _assert_enum(data, "pricing_class", {"STANDARD", "VOLUME", "NATIONAL"})
    _assert_enum(data, "lead_time_class", {"STANDARD", "EXTENDED"})
    _assert_int(data, "credit_limit_cents", minimum=0)
    assert isinstance(data.get("store_codes"), list)
    assert all(isinstance(code, str) for code in data["store_codes"])
    _assert_enum(data, "status", {"ACTIVE", "SUSPENDED", "CLOSED"})
    _assert_int(data, "open_exposure_cents", minimum=0)


def assert_program(data: Dict[str, Any]) -> None:
    assert_common_fields(data)
    assert is_valid_uuid(data.get("account_id", "")), "account_id must be a UUID"
    assert isinstance(data.get("name"), str) and data["name"]
    pct = data.get("program_discount_pct")
    assert isinstance(pct, (int, float)) and not isinstance(pct, bool), (
        f"program_discount_pct must be numeric, got {pct!r}"
    )
    assert 0 <= pct <= 0.5, f"program_discount_pct must be within 0..0.5, got {pct}"
    _assert_enum(data, "status", {"DRAFT", "ACTIVE", "TRANSITIONING"})
    _assert_opt_iso(data, "transition_started_at")
    _assert_opt_iso(data, "display_reset_deadline")
    _assert_opt_iso(data, "disposition_deadline")
    _assert_int(data, "open_order_count", minimum=0)


def assert_family_spec(spec: Dict[str, Any]) -> None:
    assert isinstance(spec.get("family_code"), str) and spec["family_code"]
    _assert_int(spec, "standard_price_cents", minimum=0)
    _assert_int(spec, "base_lead_weeks", minimum=0)
    _assert_int(spec, "complexity_units_per_cabinet", minimum=0)


def assert_program_line(data: Dict[str, Any]) -> None:
    assert_common_fields(data)
    assert is_valid_uuid(data.get("program_id", "")), "program_id must be a UUID"
    assert isinstance(data.get("line_code"), str) and data["line_code"]
    _assert_enum(data, "status", {"ACTIVE", "SUNSETTING", "RETIRED"})
    assert_iso_week(data.get("effective_start_week"), "effective_start_week")
    assert isinstance(data.get("families"), list) and data["families"]
    for spec in data["families"]:
        assert_family_spec(spec)
    assert "supersedes_line_id" in data, "supersedes_line_id must be present (null allowed)"
    if data["supersedes_line_id"] is not None:
        assert is_valid_uuid(data["supersedes_line_id"]), "supersedes_line_id must be a UUID"
    _assert_int(data, "original_disposition_qty", minimum=0)
    _assert_opt_int(data, "remaining_disposition_qty")
    assert isinstance(data.get("disposition_actions"), list)
    for action in data["disposition_actions"]:
        assert action.get("action_type") in {"RTV", "LIQUIDATE", "TRANSFER", "DESTROY"}
        _assert_int(action, "qty", minimum=1)
        assert is_iso8601_timestamp(action.get("created_at", ""))


def assert_finish_batch(data: Dict[str, Any]) -> None:
    assert_common_fields(data)
    assert isinstance(data.get("finish_code"), str) and data["finish_code"]
    assert isinstance(data.get("batch_code"), str) and data["batch_code"]
    for coord in ("lab_l", "lab_a", "lab_b"):
        assert isinstance(data.get(coord), (int, float)) and not isinstance(data.get(coord), bool), (
            f"{coord} must be numeric, got {data.get(coord)!r}"
        )
    assert is_iso8601_timestamp(data.get("effective_from", "")), "effective_from must be ISO 8601"
    _assert_enum(data, "status", {"CURRENT", "RETIRED"})


def assert_design_job(data: Dict[str, Any]) -> None:
    assert_common_fields(data)
    assert is_valid_uuid(data.get("account_id", "")), "account_id must be a UUID"
    assert is_valid_uuid(data.get("program_id", "")), "program_id must be a UUID"
    assert isinstance(data.get("store_code"), str) and data["store_code"]
    assert isinstance(data.get("designer_user_id"), str) and data["designer_user_id"]
    assert is_iso8601_timestamp(data.get("measure_window_start", ""))
    assert is_iso8601_timestamp(data.get("measure_window_end", ""))
    assert "layout_lines" in data, "layout_lines must be present (null allowed)"
    if data["layout_lines"] is not None:
        assert isinstance(data["layout_lines"], list)
        for line in data["layout_lines"]:
            assert isinstance(line.get("family_code"), str)
            assert isinstance(line.get("finish_code"), str)
            _assert_int(line, "quantity", minimum=1)
    _assert_enum(
        data, "status",
        {"REQUESTED", "MEASURED", "LAYOUT_READY", "QUOTED", "CONVERTED", "CANCELLED"},
    )
    _assert_int(data, "revision_count", minimum=0)
    _assert_opt_int(data, "quoted_total_cents")
    assert "quoted_line_id" in data, "quoted_line_id must be present (null allowed)"
    if data["quoted_line_id"] is not None:
        assert is_valid_uuid(data["quoted_line_id"]), "quoted_line_id must be a UUID"


def assert_order_line(line: Dict[str, Any]) -> None:
    assert isinstance(line.get("family_code"), str) and line["family_code"]
    assert isinstance(line.get("finish_code"), str) and line["finish_code"]
    _assert_int(line, "quantity", minimum=1)
    # Server-added pricing/production fields (PRD §3.3, §3.4)
    if "unit_quoted_cents" in line:
        assert line["unit_quoted_cents"] is None or isinstance(line["unit_quoted_cents"], int)
    if "unit_invoiced_cents" in line:
        assert line["unit_invoiced_cents"] is None or isinstance(line["unit_invoiced_cents"], int)
    if "finish_batch_id" in line:
        assert line["finish_batch_id"] is None or is_valid_uuid(line["finish_batch_id"])
    if "units" in line:
        assert line["units"] is None or (isinstance(line["units"], int) and line["units"] >= 0)


def assert_order(data: Dict[str, Any]) -> None:
    assert_common_fields(data)
    assert is_valid_uuid(data.get("account_id", "")), "account_id must be a UUID"
    assert is_valid_uuid(data.get("program_id", "")), "program_id must be a UUID"
    assert "design_job_id" in data, "design_job_id must be present (null allowed)"
    if data["design_job_id"] is not None:
        assert is_valid_uuid(data["design_job_id"]), "design_job_id must be a UUID"
    _assert_enum(data, "destination_type", {"JOB_SITE", "STORE"})
    assert "store_code" in data and "jobsite_address" in data
    if data["destination_type"] == "STORE":
        assert isinstance(data["store_code"], str) and data["store_code"]
    else:
        assert isinstance(data["jobsite_address"], str) and data["jobsite_address"]
    assert_iso_week(data.get("requested_delivery_week"), "requested_delivery_week")
    assert isinstance(data.get("lines"), list) and data["lines"]
    for line in data["lines"]:
        assert_order_line(line)
    _assert_enum(
        data, "status",
        {"SUBMITTED", "ACKNOWLEDGED", "SCHEDULED", "IN_PRODUCTION", "MFG_COMPLETE",
         "SHIPPED", "DELIVERED", "CANCELLED"},
    )
    _assert_enum(data, "payment_status", {"UNINVOICED", "CREDIT_HOLD", "INVOICED", "PAID"})
    _assert_opt_week(data, "promised_delivery_week")
    _assert_opt_week(data, "scheduled_week")
    _assert_opt_week(data, "scheduled_delivery_week")
    _assert_opt_int(data, "quoted_total_cents")
    _assert_opt_int(data, "invoiced_total_cents")
    assert isinstance(data.get("price_lock"), bool)
    assert isinstance(data.get("repricing_required"), bool)


def assert_production_slot(data: Dict[str, Any]) -> None:
    assert_common_fields(data)
    _assert_enum(data, "plant_code", {"PLANT_EAST", "PLANT_WEST", "PLANT_SOUTH"})
    assert isinstance(data.get("family_code"), str) and data["family_code"]
    assert_iso_week(data.get("week"), "week")
    _assert_int(data, "capacity_units", minimum=1)
    _assert_int(data, "committed_units", minimum=0)
    _assert_enum(data, "status", {"OPEN", "LOCKED"})


def assert_shipment(data: Dict[str, Any]) -> None:
    assert_common_fields(data)
    assert is_valid_uuid(data.get("order_id", "")), "order_id must be a UUID"
    _assert_enum(data, "destination_type", {"JOB_SITE", "STORE"})
    assert "store_code" in data and "jobsite_address" in data
    _assert_enum(data, "status", {"PLANNED", "LOADED", "IN_TRANSIT", "DELIVERED", "FAILED", "RETURNED"})
    _assert_int(data, "attempt_count", minimum=0)
    _assert_opt_iso(data, "delivered_at")


def assert_damage_claim(data: Dict[str, Any]) -> None:
    assert_common_fields(data)
    assert is_valid_uuid(data.get("shipment_id", "")), "shipment_id must be a UUID"
    assert is_valid_uuid(data.get("order_id", "")), "order_id must be a UUID"
    _assert_int(data, "line_index", minimum=0)
    _assert_int(data, "claimed_qty", minimum=1)
    assert isinstance(data.get("filed_by_user_id"), str) and data["filed_by_user_id"]
    assert is_iso8601_timestamp(data.get("filed_at", "")), "filed_at must be ISO 8601"
    _assert_enum(data, "status", {"FILED", "UNDER_REVIEW", "APPROVED", "DENIED"})
    assert "resolution" in data, "resolution must be present (null allowed)"
    if data["resolution"] is not None:
        assert data["resolution"] in {"REPLACEMENT", "CREDIT"}
    _assert_opt_int(data, "settlement_cents")
    assert "decided_by_user_id" in data, "decided_by_user_id must be present (null allowed)"
    if data["decided_by_user_id"] is not None:
        assert isinstance(data["decided_by_user_id"], str) and data["decided_by_user_id"]


def assert_replacement_order(data: Dict[str, Any]) -> None:
    assert_common_fields(data)
    assert is_valid_uuid(data.get("damage_claim_id", "")), "damage_claim_id must be a UUID"
    assert is_valid_uuid(data.get("order_id", "")), "order_id must be a UUID"
    _assert_int(data, "line_index", minimum=0)
    _assert_int(data, "quantity", minimum=1)
    assert is_valid_uuid(data.get("finish_batch_id", "")), "finish_batch_id must be a UUID"
    assert is_valid_uuid(data.get("original_finish_batch_id", "")), (
        "original_finish_batch_id must be a UUID"
    )
    _assert_enum(
        data, "status",
        {"CREATED", "SCHEDULED", "IN_PRODUCTION", "SHIPPED", "RECEIVED", "REMAKE", "CANCELLED"},
    )
    _assert_opt_week(data, "scheduled_week")


def assert_display_reset(data: Dict[str, Any]) -> None:
    assert_common_fields(data)
    assert is_valid_uuid(data.get("program_id", "")), "program_id must be a UUID"
    assert is_valid_uuid(data.get("line_id", "")), "line_id must be a UUID"
    assert isinstance(data.get("store_code"), str) and data["store_code"]
    _assert_enum(data, "status", {"PLANNED", "SCHEDULED", "COMPLETE", "WAIVED"})
    _assert_opt_iso(data, "scheduled_date")
    _assert_opt_iso(data, "completed_at")
    assert isinstance(data.get("completed_late"), bool)


# ── Domain invariants ───────────────────────────────────────────────────────

def assert_slot_lock_consistency(slot: Dict[str, Any]) -> None:
    """A slot is LOCKED exactly when commitments have reached capacity
    (re-opened when a release drops them back below). Expedite overbooking may
    legitimately push committed_units above capacity, so the invariant is on
    the status/committed relationship, not a hard cap."""
    assert slot["committed_units"] >= 0
    if slot["committed_units"] >= slot["capacity_units"]:
        assert slot["status"] == "LOCKED", (
            f"slot at {slot['committed_units']}/{slot['capacity_units']} must be LOCKED"
        )
    else:
        assert slot["status"] == "OPEN", (
            f"slot at {slot['committed_units']}/{slot['capacity_units']} must be OPEN"
        )


def assert_disposition_invariant(line: Dict[str, Any]) -> None:
    """Logged disposition quantities plus the remainder always equal the
    original disposition quantity."""
    logged = sum(action["qty"] for action in line.get("disposition_actions", []))
    remaining = line.get("remaining_disposition_qty")
    if remaining is None:
        remaining = 0
    assert logged + remaining == line["original_disposition_qty"], (
        f"disposition invariant broken: {logged} logged + {remaining} remaining "
        f"!= {line['original_disposition_qty']} original"
    )


def assert_account_exposure_invariants(account: Dict[str, Any]) -> None:
    assert account["open_exposure_cents"] >= 0
    assert account["credit_limit_cents"] >= 0
