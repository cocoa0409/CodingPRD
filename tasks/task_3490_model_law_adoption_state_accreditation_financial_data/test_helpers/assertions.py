"""Entity assertions and domain invariant checkers.

Two rendering families from the contract drive the timestamp helpers:

- ``created_at`` / ``updated_at`` (and the envelope's api_request_timestamp) are
  rendered with exactly three fractional digits — checked by
  ``assert_system_timestamp``.
- Every clock-sourced or client-echoed domain timestamp (``cast_at``,
  ``published_at``, comment windows, review periods, ``enacted_on``, license
  windows) renders exactly as the logical clock reads, with no forced fraction
  — checked by ``assert_clock_timestamp``.

Numeric comparisons go through ``Decimal`` so half-up rounding checks are exact:
money at two decimals, RBC ratios at four, percentages and accreditation scores
at one, exam priority scores at two.
"""

import re
from decimal import Decimal, ROUND_FLOOR, ROUND_HALF_UP

from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid

from .constants import (
    COMPLAINT_CAP,
    COMPLAINT_RATE_MULTIPLIER,
    COMPLAINT_WEIGHT,
    MIN_SHARE_PCT,
    NEUTRAL_RBC_POINTS,
    RBC_AUTHORIZED_CONTROL_FLOOR,
    RBC_COMPANY_ACTION_FLOOR,
    RBC_NONE_FLOOR,
    RBC_REGULATORY_ACTION_FLOOR,
    SCORE_CAP,
    SHARE_TIER_HIGH,
    SHARE_TIER_HIGH_POINTS,
    SHARE_TIER_LOW,
    SHARE_TIER_LOW_POINTS,
)
from .types import JsonObject

_MONEY_PLACES = Decimal("0.01")
_RATIO_PLACES = Decimal("0.0001")
_SCORE1_PLACES = Decimal("0.1")

_SYSTEM_TS_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}Z$")


# ------------------------------------------------------------------- numerics
def to_decimal(value) -> Decimal:
    """Coerce a JSON number (or numeric string) to an exact ``Decimal``."""
    assert value is not None, "expected a numeric value, got null"
    return Decimal(str(value))


def round_half_up(value, places: Decimal) -> Decimal:
    return to_decimal(value).quantize(places, rounding=ROUND_HALF_UP)


def assert_decimal_equals(actual, expected, places: Decimal = _MONEY_PLACES,
                          label: str = "value") -> None:
    """Assert a rendered number equals the expected amount at the given width."""
    got = round_half_up(actual, places)
    want = round_half_up(expected, places)
    assert got == want, "%s: expected %s, got %s (raw %r)" % (label, want, got, actual)


def assert_money_equals(actual, expected, label: str = "amount") -> None:
    assert_decimal_equals(actual, expected, _MONEY_PLACES, label)


def assert_ratio_equals(actual, expected, label: str = "ratio") -> None:
    assert_decimal_equals(actual, expected, _RATIO_PLACES, label)


def assert_score1_equals(actual, expected, label: str = "score") -> None:
    assert_decimal_equals(actual, expected, _SCORE1_PLACES, label)


# ------------------------------------------------------------------ timestamps
def assert_system_timestamp(value, label: str = "timestamp") -> None:
    """created_at / updated_at: ISO 8601 UTC with exactly three fractional digits."""
    assert isinstance(value, str) and _SYSTEM_TS_RE.match(value), (
        "%s: expected 3-fractional-digit ISO 8601 UTC, got %r" % (label, value)
    )


def assert_clock_timestamp(value, label: str = "timestamp") -> None:
    """A clock-sourced / client-echoed instant; no forced fractional digits."""
    assert isinstance(value, str) and is_iso8601_timestamp(value), (
        "%s: not an ISO 8601 UTC instant: %r" % (label, value)
    )


def assert_is_uuid(value, label: str = "id") -> None:
    """A server-minted UUID with no type prefix."""
    assert is_valid_uuid(value), "%s: expected a bare UUID, got %r" % (label, value)


def assert_common_fields(row: JsonObject, label: str = "row") -> None:
    """Every resource carries id, created_at, updated_at and integer version."""
    assert_is_uuid(row.get("id"), label + ".id")
    assert_system_timestamp(row.get("created_at"), label + ".created_at")
    assert_system_timestamp(row.get("updated_at"), label + ".updated_at")
    assert isinstance(row.get("version"), int) and row["version"] >= 1, (
        "%s.version must be a positive integer, got %r" % (label, row.get("version"))
    )


def _assert_enum(value, allowed, label):
    assert value in allowed, "%s: expected one of %s, got %r" % (label, allowed, value)


def _assert_int_or_none(row, field, label):
    value = row.get(field)
    assert value is None or (isinstance(value, int) and not isinstance(value, bool)), (
        "%s.%s must be an integer or null, got %r" % (label, field, value)
    )


def _assert_number_or_none(row, field, label):
    value = row.get(field)
    assert value is None or isinstance(value, (int, float)) and not isinstance(value, bool), (
        "%s.%s must be a number or null, got %r" % (label, field, value)
    )


# ------------------------------------------------------------------- entities
def assert_model_act(data: JsonObject) -> None:
    assert_common_fields(data, "ModelAct")
    for field in ("model_code", "version_label", "title", "committee_name"):
        assert isinstance(data.get(field), str) and data[field], "ModelAct.%s" % field
    _assert_enum(data.get("act_type"), ("MODEL_LAW", "MODEL_REGULATION"), "act_type")
    _assert_enum(
        data.get("status"),
        ("DRAFTING", "EXPOSURE_OPEN", "BALLOTING", "ADOPTED", "PUBLISHED", "SUPERSEDED"),
        "ModelAct.status",
    )
    assert isinstance(data.get("is_core"), bool), "ModelAct.is_core must be boolean"
    assert isinstance(data.get("votes_cast"), int) and data["votes_cast"] >= 0
    assert isinstance(data.get("favorable_votes"), int) and data["favorable_votes"] >= 0
    published_at = data.get("published_at")
    if published_at is not None:
        assert_clock_timestamp(published_at, "ModelAct.published_at")


def assert_exposure_draft(data: JsonObject) -> None:
    assert_common_fields(data, "ExposureDraft")
    assert_is_uuid(data.get("model_act_id"), "ExposureDraft.model_act_id")
    assert isinstance(data.get("exposure_number"), int) and data["exposure_number"] >= 1
    assert_clock_timestamp(data.get("comment_window_start"), "comment_window_start")
    assert_clock_timestamp(data.get("comment_window_end"), "comment_window_end")
    _assert_enum(data.get("status"), ("OPEN", "CLOSED"), "ExposureDraft.status")


def assert_member_ballot(data: JsonObject) -> None:
    assert_common_fields(data, "MemberBallot")
    assert_is_uuid(data.get("model_act_id"), "MemberBallot.model_act_id")
    assert isinstance(data.get("state_code"), str) and data["state_code"]
    _assert_enum(data.get("vote"), ("YEA", "NAY", "ABSTAIN"), "MemberBallot.vote")
    _assert_enum(data.get("status"), ("CAST", "VOID"), "MemberBallot.status")
    assert_clock_timestamp(data.get("cast_at"), "MemberBallot.cast_at")


def assert_state(data: JsonObject) -> None:
    assert_common_fields(data, "State")
    assert isinstance(data.get("code"), str) and len(data["code"]) == 2
    assert isinstance(data.get("name"), str) and data["name"]
    _assert_enum(
        data.get("accreditation_status"),
        ("ACCREDITED", "PROBATION", "SUSPENDED"),
        "State.accreditation_status",
    )
    assert isinstance(data.get("consecutive_fail_count"), int)
    assert data["consecutive_fail_count"] >= 0
    _assert_number_or_none(data, "core_act_coverage_pct", "State")
    if data.get("core_act_coverage_pct") is not None:
        assert 0 <= float(data["core_act_coverage_pct"]) <= 100.0


def assert_state_adoption(data: JsonObject) -> None:
    assert_common_fields(data, "StateAdoption")
    assert_is_uuid(data.get("model_act_id"), "StateAdoption.model_act_id")
    assert isinstance(data.get("state_code"), str) and data["state_code"]
    assert isinstance(data.get("adopted_citation"), str) and data["adopted_citation"]
    assert_clock_timestamp(data.get("enacted_on"), "StateAdoption.enacted_on")
    _assert_enum(
        data.get("status"),
        ("PENDING_CERTIFICATION", "CERTIFIED_SIMILAR", "CERTIFIED_VARIED",
         "REJECTED_NOT_SIMILAR", "SUPERSEDED"),
        "StateAdoption.status",
    )


def assert_accreditation_review(data: JsonObject) -> None:
    assert_common_fields(data, "AccreditationReview")
    assert_is_uuid(data.get("state_id"), "AccreditationReview.state_id")
    assert_clock_timestamp(data.get("period_start"), "period_start")
    assert_clock_timestamp(data.get("period_end"), "period_end")
    lead = data.get("team_lead_id")
    assert lead is None or isinstance(lead, str), "team_lead_id must be a string or null"
    assert isinstance(data.get("self_assessment_compliant"), int)
    assert isinstance(data.get("self_assessment_total"), int)
    assert data["self_assessment_total"] >= 1
    _assert_int_or_none(data, "findings_compliant", "AccreditationReview")
    _assert_int_or_none(data, "findings_total", "AccreditationReview")
    _assert_number_or_none(data, "desk_score", "AccreditationReview")
    _assert_number_or_none(data, "onsite_score", "AccreditationReview")
    outcome = data.get("proposed_outcome")
    assert outcome is None or outcome in ("PASS", "FAIL")
    _assert_enum(data.get("origin"), ("MANUAL", "AUTO_COVERAGE"), "Review.origin")
    _assert_enum(
        data.get("status"),
        ("SCHEDULED", "FINDINGS_ISSUED", "FINAL_PASS", "FINAL_FAIL"),
        "Review.status",
    )


def assert_insurer(data: JsonObject) -> None:
    assert_common_fields(data, "Insurer")
    assert isinstance(data.get("naic_code"), str) and data["naic_code"]
    assert isinstance(data.get("name"), str) and data["name"]
    assert isinstance(data.get("domicile_state_code"), str)
    _assert_enum(data.get("status"), ("ACTIVE", "UNDER_SUPERVISION"), "Insurer.status")
    _assert_number_or_none(data, "latest_rbc_ratio", "Insurer")
    level = data.get("latest_action_level")
    assert level is None or level in (
        "NONE", "COMPANY_ACTION", "REGULATORY_ACTION",
        "AUTHORIZED_CONTROL", "MANDATORY_CONTROL",
    )


def assert_financial_filing(data: JsonObject) -> None:
    assert_common_fields(data, "FinancialFiling")
    assert_is_uuid(data.get("insurer_id"), "FinancialFiling.insurer_id")
    assert isinstance(data.get("period_year"), int)
    _assert_enum(
        data.get("period_quarter"), ("Q1", "Q2", "Q3", "Q4", "ANNUAL"), "period_quarter"
    )
    assert isinstance(data.get("valuation_standard_code"), str)
    label = data.get("valuation_standard_version_label")
    assert label is None or isinstance(label, str)
    for field in ("reported_surplus_cents", "asset_risk_cents",
                  "underwriting_risk_cents", "other_risk_cents"):
        assert isinstance(data.get(field), int) and data[field] >= 0, field
    _assert_enum(
        data.get("status"),
        ("DRAFT", "SUBMITTED", "VALIDATED", "EDITS_FAILED", "SUPERSEDED"),
        "Filing.status",
    )
    assert isinstance(data.get("edit_failures"), list), "edit_failures must be a list"
    for edit_id in data["edit_failures"]:
        _assert_enum(edit_id, ("E101", "E103", "E106", "E107"), "edit_failures entry")


def assert_rbc_report(data: JsonObject) -> None:
    assert_common_fields(data, "RBCReport")
    assert_is_uuid(data.get("filing_id"), "RBCReport.filing_id")
    assert isinstance(data.get("insurer_naic_code"), str) and data["insurer_naic_code"]
    for field in ("tac_cents", "acl_covariance_cents", "acl_additive_cents",
                  "ratio_covariance", "ratio_additive"):
        assert isinstance(data.get(field), (int, float)), field
    _assert_enum(
        data.get("action_level"),
        ("NONE", "COMPANY_ACTION", "REGULATORY_ACTION",
         "AUTHORIZED_CONTROL", "MANDATORY_CONTROL"),
        "RBCReport.action_level",
    )


def assert_producer(data: JsonObject) -> None:
    assert_common_fields(data, "Producer")
    assert isinstance(data.get("npn"), str) and data["npn"]
    assert isinstance(data.get("full_name"), str) and data["full_name"]
    assert isinstance(data.get("home_state_code"), str)
    assert isinstance(data.get("active_license_count"), int)
    assert data["active_license_count"] >= 0


def assert_producer_license(data: JsonObject) -> None:
    assert_common_fields(data, "ProducerLicense")
    assert_is_uuid(data.get("producer_id"), "ProducerLicense.producer_id")
    assert isinstance(data.get("state_code"), str) and data["state_code"]
    _assert_enum(
        data.get("license_class"),
        ("LIFE", "HEALTH", "PROPERTY_CASUALTY", "PERSONAL_LINES"),
        "license_class",
    )
    assert_clock_timestamp(data.get("effective_from"), "effective_from")
    assert_clock_timestamp(data.get("valid_until"), "valid_until")
    _assert_enum(
        data.get("status"), ("APPLIED", "ISSUED", "REVOKED", "EXPIRED"), "License.status"
    )


def assert_market_conduct_call(data: JsonObject) -> None:
    assert_common_fields(data, "MarketConductCall")
    assert isinstance(data.get("call_code"), str) and data["call_code"]
    assert isinstance(data.get("topic"), str)
    assert isinstance(data.get("lead_state_code"), str) and data["lead_state_code"]
    assert isinstance(data.get("total_cost_cents"), int)
    _assert_enum(data.get("status"), ("OPEN", "CLOSED"), "Call.status")


def assert_market_conduct_response(data: JsonObject) -> None:
    assert_common_fields(data, "MarketConductResponse")
    assert_is_uuid(data.get("call_id"), "MarketConductResponse.call_id")
    assert isinstance(data.get("insurer_naic_code"), str) and data["insurer_naic_code"]
    assert isinstance(data.get("direct_premium_cents"), int)
    assert data["direct_premium_cents"] > 0
    assert isinstance(data.get("complaint_count"), int) and data["complaint_count"] >= 0
    _assert_number_or_none(data, "exam_priority_score", "MarketConductResponse")
    assert isinstance(data.get("escalation_flag"), bool)
    _assert_int_or_none(data, "allocated_cost_cents", "MarketConductResponse")
    excluded = data.get("cost_share_excluded")
    assert excluded is None or isinstance(excluded, bool)


def assert_valuation_standard(data: JsonObject) -> None:
    assert_common_fields(data, "ValuationStandard")
    assert isinstance(data.get("code"), str) and data["code"]
    assert isinstance(data.get("version_label"), str) and data["version_label"]
    assert isinstance(data.get("guidance_text"), str)
    assert isinstance(data.get("author_user_id"), str) and data["author_user_id"]
    _assert_enum(
        data.get("status"), ("DRAFT", "ACTIVE", "RETIRED"), "ValuationStandard.status"
    )


# ------------------------------------------------------- domain math checkers
def expected_action_level(ratio_covariance) -> str:
    """The action-level band a covariance ratio falls in (lower edge inclusive)."""
    ratio = to_decimal(ratio_covariance)
    if ratio >= to_decimal(RBC_NONE_FLOOR):
        return "NONE"
    if ratio >= to_decimal(RBC_COMPANY_ACTION_FLOOR):
        return "COMPANY_ACTION"
    if ratio >= to_decimal(RBC_REGULATORY_ACTION_FLOOR):
        return "REGULATORY_ACTION"
    if ratio >= to_decimal(RBC_AUTHORIZED_CONTROL_FLOOR):
        return "AUTHORIZED_CONTROL"
    return "MANDATORY_CONTROL"


def compute_expected_rbc(reported_surplus_cents, asset_risk_cents,
                         underwriting_risk_cents, other_risk_cents) -> dict:
    """Recompute the pinned RBC aggregation: square and sum the integer-cent
    charges, take the square root, round the ACL half-up to 2 decimals, THEN
    divide into the verbatim surplus and round the ratio half-up to 4."""
    tac = to_decimal(reported_surplus_cents).quantize(_MONEY_PLACES, rounding=ROUND_HALF_UP)
    sum_sq = (to_decimal(asset_risk_cents) ** 2
              + to_decimal(underwriting_risk_cents) ** 2
              + to_decimal(other_risk_cents) ** 2)
    acl_cov = sum_sq.sqrt().quantize(_MONEY_PLACES, rounding=ROUND_HALF_UP)
    acl_add = (to_decimal(asset_risk_cents) + to_decimal(underwriting_risk_cents)
               + to_decimal(other_risk_cents)).quantize(_MONEY_PLACES, rounding=ROUND_HALF_UP)
    ratio_cov = (tac / acl_cov).quantize(_RATIO_PLACES, rounding=ROUND_HALF_UP)
    ratio_add = (tac / acl_add).quantize(_RATIO_PLACES, rounding=ROUND_HALF_UP)
    return {
        "tac_cents": tac,
        "acl_covariance_cents": acl_cov,
        "acl_additive_cents": acl_add,
        "ratio_covariance": ratio_cov,
        "ratio_additive": ratio_add,
        "action_level": expected_action_level(ratio_cov),
    }


def assert_rbc_report_matches_filing(report: JsonObject, filing: JsonObject) -> None:
    """The report must equal the pinned aggregation of its filing's figures."""
    expected = compute_expected_rbc(
        filing["reported_surplus_cents"], filing["asset_risk_cents"],
        filing["underwriting_risk_cents"], filing["other_risk_cents"],
    )
    assert report["filing_id"] == filing["id"], "RBCReport.filing_id must echo the filing"
    assert_money_equals(report["tac_cents"], expected["tac_cents"], "tac_cents")
    assert_money_equals(report["acl_covariance_cents"],
                        expected["acl_covariance_cents"], "acl_covariance_cents")
    assert_money_equals(report["acl_additive_cents"],
                        expected["acl_additive_cents"], "acl_additive_cents")
    assert_ratio_equals(report["ratio_covariance"],
                        expected["ratio_covariance"], "ratio_covariance")
    assert_ratio_equals(report["ratio_additive"],
                        expected["ratio_additive"], "ratio_additive")
    assert report["action_level"] == expected["action_level"], (
        "action_level: expected %s, got %s"
        % (expected["action_level"], report["action_level"])
    )


def compute_expected_exam_priority(complaint_count, direct_premium_cents,
                                   latest_rbc_ratio,
                                   total_premium_including_self) -> Decimal:
    """The pinned priority score: capped complaint term + tiered RBC points +
    two-band share points, summed and capped at the score cap."""
    complaints_per_million = (to_decimal(COMPLAINT_RATE_MULTIPLIER)
                              * to_decimal(complaint_count)
                              / to_decimal(direct_premium_cents))
    complaint_points = to_decimal(COMPLAINT_WEIGHT) * min(
        to_decimal(COMPLAINT_CAP), complaints_per_million
    )
    if latest_rbc_ratio is None:
        rbc_points = Decimal(NEUTRAL_RBC_POINTS)
    else:
        ratio = to_decimal(latest_rbc_ratio)
        if ratio < to_decimal(RBC_AUTHORIZED_CONTROL_FLOOR):
            rbc_points = Decimal(50)
        elif ratio < to_decimal(RBC_REGULATORY_ACTION_FLOOR):
            rbc_points = Decimal(35)
        elif ratio < to_decimal(RBC_COMPANY_ACTION_FLOOR):
            rbc_points = Decimal(20)
        elif ratio < to_decimal(RBC_NONE_FLOOR):
            rbc_points = Decimal(10)
        else:
            rbc_points = Decimal(0)
    share = to_decimal(direct_premium_cents) / to_decimal(total_premium_including_self)
    if share >= to_decimal(SHARE_TIER_HIGH):
        share_points = Decimal(SHARE_TIER_HIGH_POINTS)
    elif share >= to_decimal(SHARE_TIER_LOW):
        share_points = Decimal(SHARE_TIER_LOW_POINTS)
    else:
        share_points = Decimal(0)
    total = min(to_decimal(SCORE_CAP), complaint_points + rbc_points + share_points)
    return total.quantize(_MONEY_PLACES, rounding=ROUND_HALF_UP)


def compute_expected_allocations(total_cost_cents, responses) -> dict:
    """The pinned two-pass cost-share assessment.

    ``responses`` is a list of ``(insurer_naic_code, direct_premium_cents)``.
    Returns ``{naic_code: (allocated_cost_cents, cost_share_excluded)}``.
    Pass 1 shares are computed over all responses; the floor exclusion uses
    pass-1 shares; pass 2 renormalizes once over survivors; the leftover cents
    go one at a time to the largest fractional parts, ties broken by ascending
    insurer code. If the floor would exclude everyone, nobody is excluded.
    """
    total = to_decimal(total_cost_cents)
    premiums = {code: to_decimal(premium) for code, premium in responses}
    grand = sum(premiums.values())
    pass1 = {code: premium / grand for code, premium in premiums.items()}
    survivors = [code for code in premiums if pass1[code] >= to_decimal(MIN_SHARE_PCT)]
    if not survivors:
        survivors = list(premiums.keys())
    excluded = {code: code not in survivors for code in premiums}
    survivor_sum = sum(premiums[code] for code in survivors)
    raw = {code: total * premiums[code] / survivor_sum for code in survivors}
    floored = {code: int(raw[code].to_integral_value(rounding=ROUND_FLOOR))
               for code in survivors}
    allocated = {code: (floored.get(code, 0), excluded[code]) for code in premiums}
    remainder = int(total) - sum(floored.values())
    by_fraction = sorted(
        survivors,
        key=lambda code: (-(raw[code] - floored[code]), code),
    )
    for code in by_fraction[:remainder]:
        allocated[code] = (allocated[code][0] + 1, False)
    return allocated


def assert_allocation_invariant(responses: list, total_cost_cents) -> None:
    """The cents-conservation invariant: allocations sum to the call's pool."""
    allocated_total = sum(
        r["allocated_cost_cents"] or 0 for r in responses
    )
    assert allocated_total == total_cost_cents, (
        "allocated cents must sum to total_cost_cents: %s != %s"
        % (allocated_total, total_cost_cents)
    )
