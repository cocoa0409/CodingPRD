"""Entity assertions and domain invariant checkers."""

import re
from typing import Any, Dict

from prd_bench_local_runner.testing import (
    is_iso8601_timestamp,
    is_valid_uuid,
)

from . import constants as C

_THREE_FRACTION_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}Z$")
_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_MONTH_RE = re.compile(r"^\d{4}-\d{2}$")


# ─── Shared shape helpers ─────────────────────────────────────────────────────

def assert_identity_fields(data: Dict[str, Any]) -> None:
    """Server-minted identity: a UUID id and a creation instant."""
    assert is_valid_uuid(data.get("id", "")), f"id must be a UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        f"created_at must be ISO 8601 UTC, got {data.get('created_at')!r}"
    )
    assert _THREE_FRACTION_RE.match(data["created_at"]), (
        "created_at must carry exactly three fractional-second digits, "
        f"got {data['created_at']!r}"
    )


def assert_mutable_common_fields(data: Dict[str, Any]) -> None:
    """The full quartet: id, created_at, updated_at, version."""
    assert_identity_fields(data)
    assert is_iso8601_timestamp(data.get("updated_at", "")), (
        f"updated_at must be ISO 8601 UTC, got {data.get('updated_at')!r}"
    )
    assert isinstance(data.get("version"), int) and not isinstance(data.get("version"), bool), (
        f"version must be an integer, got {data.get('version')!r}"
    )
    assert data["version"] >= 1, f"version starts at 1, got {data['version']}"


def assert_append_only_fields(data: Dict[str, Any]) -> None:
    """Append-only rows carry only id and created_at — no updated_at, no version."""
    assert_identity_fields(data)
    assert "updated_at" not in data, "append-only rows must not expose updated_at"
    assert "version" not in data, "append-only rows must not expose version"


def assert_calendar_date(value: Any, field: str) -> None:
    assert isinstance(value, str) and _DATE_RE.match(value), (
        f"{field} must be a calendar date, got {value!r}"
    )


def assert_month(value: Any, field: str) -> None:
    assert isinstance(value, str) and _MONTH_RE.match(value), (
        f"{field} must be a YYYY-MM month, got {value!r}"
    )


def assert_integer_cents(value: Any, field: str) -> None:
    assert isinstance(value, int) and not isinstance(value, bool), (
        f"{field} must be an integer number of cents, got {value!r}"
    )


def assert_two_decimal_pct(value: Any, field: str) -> None:
    assert isinstance(value, (int, float)) and not isinstance(value, bool), (
        f"{field} must be numeric, got {value!r}"
    )
    assert round(float(value), 2) == float(value), (
        f"{field} must carry at most two decimal places, got {value!r}"
    )


def assert_single_resource_meta(meta: Dict[str, Any]) -> None:
    """Single-resource responses omit the four pagination keys."""
    for key in ("limit", "offset", "total_count", "has_more"):
        assert key not in meta, f"single-resource meta must omit {key}"


# ─── Members ──────────────────────────────────────────────────────────────────

def assert_member(data: Dict[str, Any]) -> None:
    assert_mutable_common_fields(data)
    assert isinstance(data["name"], str) and data["name"], "name must be non-empty"
    assert isinstance(data["fte_count"], int) and data["fte_count"] >= 1
    assert data["carnegie_class"] in C.CARNEGIE_CLASSES, (
        f"unexpected carnegie_class {data['carnegie_class']!r}"
    )
    assert_integer_cents(data["budget_ceiling_cents"], "budget_ceiling_cents")
    assert data["budget_ceiling_cents"] >= 0
    assert_integer_cents(data["annual_committed_cents"], "annual_committed_cents")
    assert data["standing"] in ("IN_GOOD_STANDING", "OVER_COMMITTED"), (
        f"unexpected standing {data['standing']!r}"
    )


def assert_member_standing_consistent(member: Dict[str, Any]) -> None:
    """The standing is a pure function of the ledger against the ceiling."""
    expected = ("OVER_COMMITTED"
                if member["annual_committed_cents"] > member["budget_ceiling_cents"]
                else "IN_GOOD_STANDING")
    assert member["standing"] == expected, (
        f"ledger {member['annual_committed_cents']} against ceiling "
        f"{member['budget_ceiling_cents']} implies {expected}, got {member['standing']}"
    )


# ─── Vendors ──────────────────────────────────────────────────────────────────

def assert_vendor(data: Dict[str, Any]) -> None:
    assert_mutable_common_fields(data)
    assert isinstance(data["name"], str) and data["name"]
    assert data["archival_agency_code"] is None or \
        data["archival_agency_code"] in C.ARCHIVAL_AGENCY_CODES
    assert isinstance(data["vpat_on_file"], bool)


# ─── Products ─────────────────────────────────────────────────────────────────

def assert_product(data: Dict[str, Any]) -> None:
    assert_mutable_common_fields(data)
    assert is_valid_uuid(data["vendor_id"])
    assert isinstance(data["name"], str) and data["name"]
    assert_integer_cents(data["base_list_price_cents"], "base_list_price_cents")
    assert data["base_list_price_cents"] >= 1
    assert isinstance(data["title_count"], int) and data["title_count"] >= 1
    assert_two_decimal_pct(data["inflation_cap_pct"], "inflation_cap_pct")
    assert 0 <= float(data["inflation_cap_pct"]) <= 25
    assert isinstance(data["cancellation_notice_days"], int)
    assert data["cancellation_notice_days"] >= 0
    assert data["perpetual_access_mode_offered"] in C.PERPETUAL_ACCESS_MODES
    assert data["ill_mode_offered"] in C.ILL_MODES
    assert isinstance(data["text_mining_offered"], bool)
    assert_tier_bands(data["tier_bands"])


def assert_tier_bands(bands: Any) -> None:
    assert isinstance(bands, list) and bands, "tier_bands must be a non-empty list"
    assert bands[0]["min_participants"] == 1, (
        "the first band's min_participants must be exactly 1, got "
        f"{bands[0]['min_participants']}"
    )
    for earlier, later in zip(bands, bands[1:]):
        assert later["min_participants"] > earlier["min_participants"], (
            "min_participants must strictly increase across the schedule"
        )
    for band in bands:
        assert_two_decimal_pct(band["discount_pct"], "tier_bands[].discount_pct")


# ─── Trials ───────────────────────────────────────────────────────────────────

def assert_trial(data: Dict[str, Any]) -> None:
    assert_mutable_common_fields(data)
    assert is_valid_uuid(data["product_id"])
    assert is_valid_uuid(data["member_id"])
    assert data["status"] in ("DRAFT", "ACTIVE", "CLOSED", "ENDORSED", "DECLINED",
                             "WITHDRAWN"), f"unexpected trial status {data['status']!r}"
    assert_calendar_date(data["start_date"], "start_date")
    assert_calendar_date(data["end_date"], "end_date")
    assert_criteria(data["criteria"])
    for field in ("provisional_score", "final_score"):
        if data[field] is not None:
            assert_two_decimal_pct(data[field], field)
    assert isinstance(data["quorum_penalty_applied"], bool)
    assert isinstance(data["feedback_count"], int) and data["feedback_count"] >= 0
    assert isinstance(data["distinct_stakeholder_group_count"], int)
    assert 0 <= data["distinct_stakeholder_group_count"] <= 4


def assert_criteria(criteria: Any) -> None:
    assert isinstance(criteria, list), "criteria must be a list"
    assert 1 <= len(criteria) <= 6, f"criteria must hold 1..6 entries, got {len(criteria)}"
    codes = [entry["code"] for entry in criteria]
    assert len(set(codes)) == len(codes), "no criterion code may repeat"
    for code in codes:
        assert code in C.CRITERION_CODES, f"unexpected criterion code {code!r}"
    total = sum(float(entry["weight_pct"]) for entry in criteria)
    assert round(total, 2) == 100.00, f"criterion weights must sum to 100, got {total}"


def assert_feedback_entry(data: Dict[str, Any]) -> None:
    assert_append_only_fields(data)
    assert is_valid_uuid(data["trial_id"])
    assert data["stakeholder_group"] in C.STAKEHOLDER_GROUPS
    assert data["criterion_code"] in C.CRITERION_CODES
    assert isinstance(data["score"], int) and 0 <= data["score"] <= 100
    assert data["comment"] is None or isinstance(data["comment"], str)
    assert data["submitted_during_status"] in ("ACTIVE", "CLOSED")
    assert isinstance(data["submitted_by_user_id"], str) and data["submitted_by_user_id"]


# ─── Negotiations ─────────────────────────────────────────────────────────────

def assert_negotiation(data: Dict[str, Any]) -> None:
    assert_mutable_common_fields(data)
    assert is_valid_uuid(data["product_id"])
    assert is_valid_uuid(data["trial_id"])
    assert data["status"] in ("DRAFTING", "VENDOR_REVIEW", "COUNTERED", "AGREED",
                             "SIGNED"), f"unexpected status {data['status']!r}"
    assert_calendar_date(data["target_term_start"], "target_term_start")
    assert_calendar_date(data["target_term_end"], "target_term_end")
    assert data["requested_ill_mode"] in C.ILL_MODES
    assert isinstance(data["requested_text_mining"], bool)
    assert data["requested_accessibility_conformance"] in C.ACCESSIBILITY_CONFORMANCE
    assert data["requested_perpetual_access"] in C.PERPETUAL_ACCESS_MODES
    assert isinstance(data["round_count"], int) and 0 <= data["round_count"] <= 3
    if data["granted_ill_mode"] is not None:
        assert data["granted_ill_mode"] in C.ILL_MODES
    if data["granted_accessibility_conformance"] is not None:
        assert data["granted_accessibility_conformance"] in C.ACCESSIBILITY_CONFORMANCE
    if data["granted_perpetual_access"] is not None:
        assert data["granted_perpetual_access"] in C.PERPETUAL_ACCESS_MODES
    for field in ("vendor_counter_price_cents", "agreed_price_cents"):
        if data[field] is not None:
            assert_integer_cents(data[field], field)
    if data["last_vendor_disposition"] is not None:
        assert data["last_vendor_disposition"] in ("ACCEPT", "COUNTER")


# ─── Commitments ──────────────────────────────────────────────────────────────

def assert_commitment(data: Dict[str, Any]) -> None:
    assert_mutable_common_fields(data)
    assert is_valid_uuid(data["product_id"])
    assert is_valid_uuid(data["member_id"])
    assert data["subscription_id"] is None or is_valid_uuid(data["subscription_id"])
    assert data["status"] in ("PLEDGED", "CONFIRMED", "WITHDRAWN", "RELEASED"), (
        f"unexpected commitment status {data['status']!r}"
    )
    assert_integer_cents(data["projected_price_cents"], "projected_price_cents")
    if data["tier_price_cents"] is not None:
        assert_integer_cents(data["tier_price_cents"], "tier_price_cents")
    assert_two_decimal_pct(data["applied_discount_pct"], "applied_discount_pct")
    assert isinstance(data["participant_count_at_pricing"], int)


# ─── Subscriptions ────────────────────────────────────────────────────────────

def assert_subscription(data: Dict[str, Any]) -> None:
    assert_mutable_common_fields(data)
    assert is_valid_uuid(data["negotiation_id"])
    assert is_valid_uuid(data["product_id"])
    assert data["contract_status"] in ("PENDING_ACTIVATION", "ACTIVE", "NOTICE_GIVEN",
                                      "CANCELLED", "EXPIRED"), (
        f"unexpected contract_status {data['contract_status']!r}"
    )
    assert data["access_status"] in ("UNCONFIGURED", "CONFIGURED", "DEGRADED",
                                    "SUSPENDED", "POST_CANCELLATION"), (
        f"unexpected access_status {data['access_status']!r}"
    )
    assert_integer_cents(data["negotiated_price_cents"], "negotiated_price_cents")
    for field in ("activation_start_date", "term_start", "term_end",
                  "notice_deadline_date"):
        assert_calendar_date(data[field], field)
    assert isinstance(data["entitled_title_count"], int)
    assert data["entitled_title_count"] >= C.MIN_ENTITLED_TITLES
    assert data["perpetual_access_mode"] in C.PERPETUAL_ACCESS_MODES
    assert isinstance(data["access_health_score"], int) and \
        not isinstance(data["access_health_score"], bool), (
        "access_health_score is the one purely integral quantity"
    )
    assert 0 <= data["access_health_score"] <= 100
    assert isinstance(data["degrade_count"], int) and data["degrade_count"] >= 0
    assert_integer_cents(data["sla_credit_cents"], "sla_credit_cents")
    assert isinstance(data["renewal_term_count"], int)
    assert data["renewal_term_count"] >= 0


# ─── Authentication configuration ─────────────────────────────────────────────

def assert_auth_config(data: Dict[str, Any]) -> None:
    assert_mutable_common_fields(data)
    assert is_valid_uuid(data["subscription_id"])
    assert data["auth_method"] in C.AUTH_METHODS
    assert isinstance(data["auth_realm_code"], str) and data["auth_realm_code"]
    assert isinstance(data["ip_ranges"], list) and data["ip_ranges"], (
        "ip_ranges must be a non-empty list"
    )
    assert data["proxy_prefix"] is None or isinstance(data["proxy_prefix"], str)
    assert data["verification_status"] in ("PENDING", "VERIFIED", "FAILED")
    assert data["last_probe_result"] is None or \
        data["last_probe_result"] in C.PROBE_RESULTS


# ─── Access incidents ─────────────────────────────────────────────────────────

def assert_access_incident(data: Dict[str, Any]) -> None:
    assert_mutable_common_fields(data)
    assert is_valid_uuid(data["subscription_id"])
    assert is_valid_uuid(data["member_id"])
    assert data["symptom_code"] in C.SYMPTOM_CODES
    assert isinstance(data["off_campus"], bool)
    assert data["status"] in ("OPEN", "DIAGNOSED", "RESOLVED", "REOPENED")
    assert data["root_cause_code"] is None or \
        data["root_cause_code"] in C.ROOT_CAUSE_CODES
    assert data["remedy_code"] is None or data["remedy_code"] in C.REMEDY_CODES
    assert isinstance(data["reopen_count"], int) and data["reopen_count"] >= 0


def assert_access_health_score(incidents, expected: int) -> None:
    """Recompute the health score from scratch over every incident row."""
    penalty = 0
    for incident in incidents:
        penalty += (C.PENALTY_OFF_CAMPUS if incident["off_campus"]
                    else C.PENALTY_ON_CAMPUS)
        penalty += C.PENALTY_PER_REOPEN * incident["reopen_count"]
        if incident["status"] == "RESOLVED":
            penalty -= C.CREDIT_RESOLVED
    score = max(0, min(100, C.ACCESS_HEALTH_MAX - penalty))
    assert score == expected, (
        f"incident rows imply an access health score of {score}, expected {expected}"
    )


# ─── Usage reports ────────────────────────────────────────────────────────────

def assert_usage_report(data: Dict[str, Any]) -> None:
    assert_append_only_fields(data)
    assert is_valid_uuid(data["subscription_id"])
    assert is_valid_uuid(data["member_id"])
    assert_month(data["period_month"], "period_month")
    for field in ("full_text_requests", "searches", "denials"):
        assert isinstance(data[field], int) and data[field] >= 0, (
            f"{field} must be a non-negative integer, got {data[field]!r}"
        )


# ─── Renewal decisions ────────────────────────────────────────────────────────

def assert_renewal_decision(data: Dict[str, Any]) -> None:
    assert_mutable_common_fields(data)
    assert is_valid_uuid(data["subscription_id"])
    assert data["status"] in ("DRAFT", "VOTING", "DECIDED_RENEW", "DECIDED_CANCEL",
                             "DECIDED_RESTRUCTURE", "EXECUTED", "REVERTED",
                             "SUPERSEDED"), f"unexpected status {data['status']!r}"
    assert data["recommended_action"] in C.RECOMMENDED_ACTIONS
    assert data["resolved_action"] is None or \
        data["resolved_action"] in C.RECOMMENDED_ACTIONS
    assert_two_decimal_pct(data["vendor_requested_increase_pct"],
                           "vendor_requested_increase_pct")
    if data["capped_increase_pct"] is not None:
        assert_two_decimal_pct(data["capped_increase_pct"], "capped_increase_pct")
    if data["cost_per_use_cents"] is not None:
        assert_integer_cents(data["cost_per_use_cents"], "cost_per_use_cents")
    assert data["cost_per_use_band"] is None or data["cost_per_use_band"] in C.CPU_BANDS
    assert_integer_cents(data["loyalty_credit_cents"], "loyalty_credit_cents")
    assert_integer_cents(data["sla_credit_applied_cents"], "sla_credit_applied_cents")
    if data["offer_price_cents"] is not None:
        assert_integer_cents(data["offer_price_cents"], "offer_price_cents")
    assert isinstance(data["titles_out"], list)
    assert isinstance(data["titles_in"], list)
    assert isinstance(data["ballots"], list)
    assert isinstance(data["yes_count"], int) and data["yes_count"] >= 0
    assert isinstance(data["quorum_met"], bool)


def assert_ballot(entry: Dict[str, Any]) -> None:
    assert is_valid_uuid(entry["member_id"])
    assert entry["ballot"] in C.BALLOTS
    assert isinstance(entry["cast_at"], str) and entry["cast_at"]


# ─── Archival deposit checks ──────────────────────────────────────────────────

def assert_archival_check(data: Dict[str, Any]) -> None:
    assert_mutable_common_fields(data)
    assert is_valid_uuid(data["subscription_id"])
    assert data["agency_code"] in C.ARCHIVAL_AGENCY_CODES
    assert data["status"] in ("PENDING", "ATTESTED", "VERIFIED", "FAILED")
    assert isinstance(data["deposited_title_count"], int)
    assert data["deposited_title_count"] >= 0
    assert data["attested_title_count"] is None or \
        isinstance(data["attested_title_count"], int)
    if data["coverage_pct"] is not None:
        assert_two_decimal_pct(data["coverage_pct"], "coverage_pct")


# ─── Analyses ─────────────────────────────────────────────────────────────────

def assert_cost_per_use_shape(data: Dict[str, Any]) -> None:
    assert isinstance(data["usage_count"], int) and data["usage_count"] >= 0
    assert data["cost_per_use_cents"] is None or \
        isinstance(data["cost_per_use_cents"], int)
    assert data["band"] in C.CPU_BANDS, f"unexpected band {data['band']!r}"
    assert_integer_cents(data["settled_invoice_total_cents"],
                         "settled_invoice_total_cents")
    if data["usage_count"] == 0:
        assert data["cost_per_use_cents"] is None, (
            "with no usage the cost per use is null and no error is raised"
        )
        assert data["band"] == "NO_USE"


def assert_invoice_allocation_shape(data: Dict[str, Any]) -> None:
    assert_integer_cents(data["total_cents"], "total_cents")
    assert isinstance(data["lines"], list)
    for line in data["lines"]:
        assert is_valid_uuid(line["commitment_id"])
        assert is_valid_uuid(line["member_id"])
        assert_integer_cents(line["allocated_cents"], "allocated_cents")
        assert isinstance(line["fte_weight"], int)
    assert_integer_cents(data["residual_cents"], "residual_cents")
    assert data["residual_assigned_commitment_id"] is None or \
        is_valid_uuid(data["residual_assigned_commitment_id"])


def assert_allocation_sums_to_total(data: Dict[str, Any]) -> None:
    """Every cent of the negotiated price lands on exactly one line."""
    allocated = sum(line["allocated_cents"] for line in data["lines"])
    assert allocated == data["total_cents"], (
        f"allocated lines sum to {allocated} but the invoice total is "
        f"{data['total_cents']}"
    )
