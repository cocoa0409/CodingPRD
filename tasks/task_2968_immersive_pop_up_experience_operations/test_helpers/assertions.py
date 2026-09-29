"""Entity assertions, envelope helpers and the domain's conserved quantities."""

from decimal import ROUND_HALF_UP, Decimal
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

import pytest
from prd_bench_local_runner.testing import (
    is_iso8601_timestamp,
    is_valid_uuid,
    validate_paginated,
    validate_success,
)

from .api_client import canonical_instant, same_instant

# The four list-only envelope fields.  A single-resource read carries none of
# them; a collection read carries all four.
PAGINATION_META_FIELDS = ("limit", "offset", "total_count", "has_more")


def round_half_up(value: float, places: int = 2) -> float:
    """Round half away from zero to `places` decimals, as the PRD prescribes."""
    quantum = Decimal(1).scaleb(-places)
    return float(Decimal(str(value)).quantize(quantum, rounding=ROUND_HALF_UP))


# ─── Envelope helpers ───────────────────────────────────────────────────────

def validate_object(response, expected_status: int = 200) -> dict:
    """Validate a single-resource response and assert it is not paginated.

    A single read reports no limit, offset, total_count or has_more.
    """
    data = validate_success(response, expected_status)
    body = response.json()
    assert body["response_type"] == "object", (
        f"Expected response_type 'object', got {body['response_type']!r}"
    )
    for field in PAGINATION_META_FIELDS:
        assert field not in body["meta"], (
            f"A single-resource read must not report meta.{field}"
        )
    return data


def validate_unpaginated(response, expected_status: int = 200) -> list:
    """Validate an array response that carries no pagination envelope fields.

    Used where the PRD returns a list that is not a paginated collection, so
    the four pagination fields must be absent rather than merely ignored.
    """
    data = validate_success(response, expected_status)
    body = response.json()
    assert body["response_type"] == "array", (
        f"Expected response_type 'array', got {body['response_type']!r}"
    )
    assert isinstance(data, list), f"Expected a list payload, got {type(data)}"
    for field in PAGINATION_META_FIELDS:
        assert field not in body["meta"], (
            f"An unpaginated list must not report meta.{field}"
        )
    return data


def validate_collection(response) -> Tuple[List[dict], Dict[str, Any]]:
    """Validate a paginated collection read and return (rows, meta)."""
    rows, meta = validate_paginated(response)
    body = response.json()
    assert body["response_type"] == "array", (
        f"Expected response_type 'array', got {body['response_type']!r}"
    )
    return rows, meta


def assert_total_count(response, expected: int) -> List[dict]:
    rows, meta = validate_collection(response)
    assert meta["total_count"] == expected, (
        f"Expected total_count {expected}, got {meta['total_count']}"
    )
    return rows


def assert_ids(rows: Sequence[dict], expected_ids: Iterable[str]) -> None:
    actual = [row["id"] for row in rows]
    assert actual == list(expected_ids), (
        f"Expected rows {list(expected_ids)}, got {actual}"
    )


def assert_created_at_ascending(rows: Sequence[dict]) -> None:
    stamps = [row["created_at"] for row in rows]
    assert stamps == sorted(stamps), (
        f"Collection must be ordered by created_at ascending, got {stamps}"
    )


def assert_instant_equals(actual: Optional[str], expected: Optional[str],
                          label: str = "instant") -> None:
    """Compare two UTC instants without assuming sub-second width."""
    assert same_instant(actual, expected), (
        f"Expected {label} {expected!r}, got {actual!r} "
        f"(canonical {canonical_instant(actual)!r})"
    )


def assert_common_fields(data: dict, expected_version: Optional[int] = None) -> None:
    """Assert the audit fields every versioned resource carries."""
    assert is_valid_uuid(data.get("id", "")), f"id must be a UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        f"created_at must be an ISO 8601 UTC instant, got {data.get('created_at')!r}"
    )
    assert is_iso8601_timestamp(data.get("updated_at", "")), (
        f"updated_at must be an ISO 8601 UTC instant, got {data.get('updated_at')!r}"
    )
    assert isinstance(data.get("version"), int) and data["version"] >= 1, (
        f"version must start at 1 and count up, got {data.get('version')!r}"
    )
    if expected_version is not None:
        assert data["version"] == expected_version, (
            f"Expected version {expected_version}, got {data['version']}"
        )


def assert_millisecond_precision(timestamp: str) -> None:
    """Assert a returned timestamp carries exactly three fractional digits."""
    assert isinstance(timestamp, str), f"Expected a timestamp string, got {timestamp!r}"
    assert len(timestamp) == 24 and timestamp.endswith("Z") and timestamp[19] == ".", (
        f"Timestamp must carry exactly three fractional digits and end in Z: "
        f"{timestamp!r}"
    )


# ─── Per-resource assertions ────────────────────────────────────────────────

def assert_venue(data: dict) -> None:
    assert_common_fields(data)
    assert isinstance(data["city_code"], str) and len(data["city_code"]) == 3
    assert 1 <= len(data["site_name"]) <= 120
    assert len(data["lease_start_date"]) == 10 and len(data["lease_end_date"]) == 10
    assert data["lease_end_date"] > data["lease_start_date"]
    assert data["status"] in (
        "DRAFT", "PERMIT_UNDER_REVIEW", "PERMIT_CONDITIONS", "PERMIT_ISSUED",
        "PERMIT_DENIED", "LEASE_ACTIVE", "LEASE_ENDED",
    )
    for field in (
        "lease_extension_option_days", "lease_extension_days_consumed",
        "base_monthly_rent_cents", "buildout_allowance_cents",
        "kit_reuse_credit_cents", "buildout_cap_cents", "allowance_drawn_cents",
        "kit_credit_drawn_cents", "operator_capex_cents", "buildout_spend_cents",
        "requested_occupancy_load", "permitted_occupancy_load", "egress_capacity",
        "permit_submission_round",
    ):
        assert isinstance(data[field], int), f"{field} must be a whole number"
        assert data[field] >= 0, f"{field} must not be negative"
    assert isinstance(data["sprinklered"], bool)
    assert 0 <= data["permit_submission_round"] <= 3
    assert_buildout_conserved(data)


def assert_agreement(data: dict) -> None:
    assert_common_fields(data)
    assert data["status"] in ("DRAFT", "ACTIVE", "EXPIRED")
    assert 0 <= data["royalty_rate_bps"] <= 10000
    assert 0 <= data["merch_royalty_rate_bps"] <= 10000
    assert isinstance(data["minimum_guarantee_cents"], int)
    assert isinstance(data["approval_scopes"], list) and data["approval_scopes"]
    assert set(data["approval_scopes"]) <= {
        "CREATIVE_EXECUTION", "MERCHANDISE", "MARKETING"
    }
    assert isinstance(data["territory_city_codes"], list)
    assert data["term_end_date"] > data["term_start_date"]
    assert data["open_submission_count"] >= 0
    assert data["approved_submission_count"] >= 0


def assert_submission(data: dict) -> None:
    assert_common_fields(data)
    assert data["status"] in (
        "SUBMITTED", "IN_REVIEW", "CHANGES_REQUESTED", "APPROVED", "REJECTED",
        "SUPERSEDED",
    )
    assert data["scope"] in ("CREATIVE_EXECUTION", "MERCHANDISE", "MARKETING")
    assert 1 <= len(data["asset_code"]) <= 40
    assert 0 <= data["revision_round"] <= 3
    assert is_valid_uuid(data["license_agreement_id"])
    assert is_valid_uuid(data["run_id"])
    assert isinstance(data["submitted_by_user_id"], str) and data["submitted_by_user_id"]


def assert_run(data: dict) -> None:
    assert_common_fields(data)
    assert data["run_status"] in ("PLANNED", "OPEN", "EXTENDED", "CLOSING", "CLOSED")
    assert data["clearance_status"] in ("UNCLEARED", "CLEARED", "SUSPENDED")
    assert is_valid_uuid(data["venue_id"])
    assert is_valid_uuid(data["license_agreement_id"])
    assert is_valid_uuid(data["build_kit_id"])
    assert 1 <= data["base_ticket_price_cents"] <= 100000
    assert 15 <= data["timed_slot_minutes"] <= 120
    assert 1 <= data["max_group_size"] <= 60
    assert data["effective_capacity"] >= 0
    assert data["effective_capacity_cap"] >= 0
    assert data["royalty_statement_count"] >= 0
    assert data["extension_days_granted"] >= 0
    assert -50.00 <= data["demand_index"] <= 100.00
    assert data["scheduled_close_date"] > data["scheduled_open_date"]


def assert_room(data: dict) -> None:
    """A themed room is immutable: it reports no version and no status."""
    assert is_valid_uuid(data.get("id", "")), "id must be a UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        "created_at must be an ISO 8601 UTC instant"
    )
    assert "version" not in data, "A themed room carries no version"
    assert "updated_at" not in data, "A themed room is never updated"
    assert "status" not in data, "A themed room carries no status"
    assert 1 <= data["room_sequence"] <= 12
    assert 1 <= data["room_occupancy_cap"] <= 400
    assert 1 <= data["target_dwell_minutes"] <= 120
    assert 1 <= data["min_dwell_minutes"] <= data["target_dwell_minutes"]
    assert 1 <= data["sensory_intensity_level"] <= 5
    assert isinstance(data["has_quiet_bypass"], bool)
    assert isinstance(data["wheelchair_accessible"], bool)
    assert data["throughput_per_slot"] >= 0


def assert_slot(data: dict) -> None:
    assert_common_fields(data)
    assert data["status"] in (
        "DRAFT", "OPEN", "SOLD_OUT", "HELD_FOR_BUYOUT", "SUSPENDED", "CANCELLED",
        "CLOSED_OUT",
    )
    assert data["pricing_tier"] in ("OFFPEAK", "STANDARD", "PEAK", "PREMIUM")
    assert data["slot_end_utc"] > data["slot_start_utc"]
    assert data["base_capacity"] >= 1
    assert data["released_capacity"] in (0, data["base_capacity"])
    assert 0 <= data["wheelchair_sold"] <= data["wheelchair_positions"]
    assert_slot_ledger_conserved(data)


def assert_guest(data: dict) -> None:
    assert_common_fields(data)
    assert data["status"] in ("ACTIVE", "RESTRICTED")
    assert data["loyalty_tier"] in ("VISITOR", "MEMBER", "PATRON")
    assert data["email"].count("@") == 1 and 5 <= len(data["email"]) <= 160
    assert 1 <= len(data["display_name"]) <= 80
    assert isinstance(data["accommodation_profile"], list)
    assert set(data["accommodation_profile"]) <= {
        "QUIET_ROUTE", "WHEELCHAIR", "ASL_INTERPRETER", "LOW_STIM_HOURS"
    }
    for field in ("experience_credit_cents", "no_show_strikes", "visit_count"):
        assert isinstance(data[field], int) and data[field] >= 0


def assert_order(data: dict) -> None:
    assert_common_fields(data)
    assert data["status"] in (
        "PENDING", "CONFIRMED", "CHECKED_IN", "NO_SHOW", "REFUND_DUE", "REFUNDED",
        "CANCELLED",
    )
    assert data["order_type"] in ("SINGLE", "GROUP", "PRIVATE_BUYOUT")
    assert data["party_size"] >= 1
    assert 0 <= data["wheelchair_party_count"] <= data["party_size"]
    assert 0 <= data["merch_amount_cents"] <= 500000
    assert 1000 <= data["unit_price_cents"] <= 100000
    for field in (
        "per_guest_after_loyalty_cents", "gross_amount_cents", "group_discount_cents",
        "companion_waiver_cents", "discount_cents", "net_amount_cents",
        "net_collected_cents", "refunded_cents", "credit_issued_cents",
    ):
        assert isinstance(data[field], int), f"{field} must be whole cents"
        assert data[field] >= 0, f"{field} must not be negative"
    assert data["refund_pct"] in (0.00, 0.50, 1.00)
    assert data["discount_cents"] == (
        data["group_discount_cents"] + data["companion_waiver_cents"]
    ), "discount_cents is the sum of the group discount and the companion waiver"
    assert data["net_amount_cents"] == max(
        0, data["gross_amount_cents"] - data["discount_cents"]
    ), "net_amount_cents is gross less discount, floored at 0"


def assert_staff_member(data: dict) -> None:
    assert_common_fields(data)
    assert data["status"] in (
        "CANDIDATE", "TRAINING", "CLEARED", "SUSPENDED", "RELEASED"
    )
    assert data["staff_role"] in ("PERFORMER", "AMBASSADOR", "TECHNICIAN")
    assert isinstance(data["certifications"], list)
    assert 0 <= data["incident_count"] <= 20
    assert 0 <= data["training_score"] <= 100
    for field in ("cert_coverage_pct", "readiness_score_preflight",
                  "readiness_score_audit"):
        assert 0.00 <= data[field] <= 100.00, f"{field} is clamped to 0.00..100.00"


def assert_shift(data: dict) -> None:
    assert_common_fields(data)
    assert data["status"] in ("SCHEDULED", "CANCELLED", "COMPLETED")
    assert data["station"] in ("FLOOR", "BOOTH", "RIGGING", "ENTRY")
    assert data["shift_end_utc"] > data["shift_start_utc"]
    assert is_valid_uuid(data["staff_member_id"])
    assert is_valid_uuid(data["run_id"])


def assert_inspection(data: dict) -> None:
    assert_common_fields(data)
    assert data["status"] in ("SCHEDULED", "FINALIZED", "VOIDED")
    assert data["inspection_type"] in ("EGRESS", "CAPACITY", "ACCESSIBILITY", "SENSORY")
    assert data["severity"] in ("NONE", "MINOR", "MAJOR", "CRITICAL")
    assert data["outcome"] in (None, "PASS", "CONDITIONAL", "FAIL")
    assert 0 <= data["findings_count"] <= 200
    assert data["measured_egress_width_cm"] >= 0
    assert data["allowed_occupancy_cap"] >= 0


def assert_kit(data: dict) -> None:
    assert_common_fields(data)
    assert data["status"] in (
        "READY", "DEPLOYED", "IN_TRANSIT", "REFURB_REQUIRED", "RETIRED"
    )
    assert data["localization_status"] in ("PENDING", "LOCALIZED")
    assert 1 <= data["module_count"] <= 60
    assert 0.00 <= data["condition_score"] <= 100.00
    assert data["reuse_cycle_count"] >= 0
    assert 0 <= data["refurb_count"] <= 2
    assert isinstance(data["localization_cost_cents"], int)
    assert data["localization_cost_cents"] >= 0


def assert_statement(data: dict) -> None:
    assert_common_fields(data)
    assert data["status"] in (
        "DRAFT", "UNDER_TRUEUP", "ISSUED", "SETTLED", "SUPERSEDED"
    )
    assert data["period_end_date"] > data["period_start_date"]
    for field in (
        "ticket_base_cents", "merch_base_cents", "provisional_royalty_cents",
        "provisional_royalty_cents_prev", "truedown_cents", "final_royalty_cents",
        "mg_prorated_cents", "minimum_guarantee_shortfall_cents", "amount_due_cents",
    ):
        assert isinstance(data[field], int), f"{field} must be whole cents"
        assert data[field] >= 0, f"{field} must not be negative"


# ─── Conserved quantities ───────────────────────────────────────────────────

def assert_buildout_conserved(venue: dict) -> None:
    """A venue's spend is exactly the sum of its three funding legs."""
    legs = (
        venue["allowance_drawn_cents"]
        + venue["kit_credit_drawn_cents"]
        + venue["operator_capex_cents"]
    )
    assert venue["buildout_spend_cents"] == legs, (
        "buildout_spend_cents must equal allowance_drawn_cents + "
        f"kit_credit_drawn_cents + operator_capex_cents: "
        f"{venue['buildout_spend_cents']} != {legs}"
    )
    assert venue["allowance_drawn_cents"] <= venue["buildout_allowance_cents"], (
        "allowance draws never exceed the allowance"
    )
    assert venue["kit_credit_drawn_cents"] <= venue["kit_reuse_credit_cents"], (
        "kit credit draws never exceed the kit reuse credit"
    )
    assert venue["buildout_spend_cents"] <= venue["buildout_cap_cents"], (
        "spend never exceeds the buildout cap"
    )


def assert_slot_ledger_conserved(slot: dict) -> None:
    """A slot's released seats are exactly held plus sold plus available."""
    parts = slot["held_capacity"] + slot["sold_capacity"] + slot["available_capacity"]
    assert slot["released_capacity"] == parts, (
        "released_capacity must equal held_capacity + sold_capacity + "
        f"available_capacity: {slot['released_capacity']} != "
        f"{slot['held_capacity']} + {slot['sold_capacity']} + "
        f"{slot['available_capacity']}"
    )


def assert_slot_ledger(slot: dict, released: int, held: int, sold: int,
                       available: int) -> None:
    """Assert the four seat counters and their conservation in one step."""
    actual = (
        slot["released_capacity"], slot["held_capacity"],
        slot["sold_capacity"], slot["available_capacity"],
    )
    assert actual == (released, held, sold, available), (
        f"Expected released/held/sold/available "
        f"{(released, held, sold, available)}, got {actual}"
    )
    assert_slot_ledger_conserved(slot)


def assert_refund_split_conserved(order: dict) -> None:
    """A settled refund splits the net amount into cash and credit only."""
    total = order["refunded_cents"] + order["credit_issued_cents"]
    assert total <= order["net_amount_cents"], (
        "refunded_cents + credit_issued_cents may never exceed net_amount_cents: "
        f"{total} > {order['net_amount_cents']}"
    )
    if order["status"] in ("REFUND_DUE", "REFUNDED"):
        assert total == order["net_amount_cents"], (
            "refunded_cents plus credit_issued_cents equals net_amount_cents once "
            f"an order has entered the refund path: {total} != "
            f"{order['net_amount_cents']}"
        )
        cash = int(round_half_up(order["net_amount_cents"] * order["refund_pct"], 0))
        assert order["refunded_cents"] == cash, (
            "refunded_cents is the collected amount times refund_pct rounded half "
            f"up: {order['refunded_cents']} != {cash}"
        )
        assert order["net_collected_cents"] == 0, (
            "net_collected_cents is zero once the refund split is fixed"
        )


def assert_guest_credit_conserved(guest: dict, orders: Sequence[dict]) -> None:
    """A guest's credit balance is the sum of credit issued on its refunds."""
    expected = sum(
        order["credit_issued_cents"] for order in orders
        if order["status"] == "REFUNDED"
    )
    assert guest["experience_credit_cents"] == expected, (
        "experience_credit_cents must equal the sum of credit_issued_cents over "
        f"the guest's refunded orders: {guest['experience_credit_cents']} != "
        f"{expected}"
    )


def assert_extension_days_conserved(venue: dict, runs: Sequence[dict]) -> None:
    """A venue's consumed extension days are the sum granted across its runs."""
    granted = sum(run["extension_days_granted"] for run in runs)
    assert venue["lease_extension_days_consumed"] == granted, (
        "lease_extension_days_consumed must equal the sum of "
        f"extension_days_granted across the venue's runs: "
        f"{venue['lease_extension_days_consumed']} != {granted}"
    )
    assert (
        venue["lease_extension_days_consumed"]
        <= venue["lease_extension_option_days"]
    ), "consumed extension days never exceed the option"


def assert_unchanged(before: dict, after: dict, *fields: str) -> None:
    """Assert a rejected write left the named fields (and the version) inert."""
    checked = fields or tuple(before.keys())
    for field in checked:
        assert after.get(field) == before.get(field), (
            f"{field} changed from {before.get(field)!r} to {after.get(field)!r} "
            "on a call that should have left the row untouched"
        )
    if "version" in before and "version" in after:
        assert after["version"] == before["version"], (
            f"version moved from {before['version']} to {after['version']} on a "
            "rejected write"
        )


def assert_row_inert(before: dict, after: dict) -> None:
    """Assert a whole row is byte-for-byte what it was before a rejected call."""
    assert after == before, (
        "A rejected call must leave the row entirely unchanged; differences: "
        + repr({
            key: (before.get(key), after.get(key))
            for key in set(before) | set(after)
            if before.get(key) != after.get(key)
        })
    )


ENTITY_ASSERTIONS = {
    "venue": assert_venue,
    "agreement": assert_agreement,
    "submission": assert_submission,
    "run": assert_run,
    "room": assert_room,
    "slot": assert_slot,
    "guest": assert_guest,
    "order": assert_order,
    "staff_member": assert_staff_member,
    "shift": assert_shift,
    "inspection": assert_inspection,
    "kit": assert_kit,
    "statement": assert_statement,
}
