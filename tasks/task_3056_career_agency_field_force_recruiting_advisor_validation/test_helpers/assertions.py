"""Entity assertions and domain invariant checkers.

Response-shape assertions are deliberately permissive about *optional*
fields (a faithful implementation may legitimately omit a derived field from a
serializer) but strict about the fields the requirements pin to a value.
"""
import pytest
from decimal import Decimal, ROUND_HALF_UP
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp

from .constants import (
    COMPETENCY_KEYS, WEIGHT_TABLES, CHARGEBACK_BLOCK_CENTS,
    TIER_1_MIN, TIER_2_MIN, TIER_3_MIN,
)


# ---------------------------------------------------------------------------
# Common field checks
# ---------------------------------------------------------------------------
def _assert_common(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, \
        "version must be a positive integer starting at 1"


# ---------------------------------------------------------------------------
# DistrictOffice
# ---------------------------------------------------------------------------
def assert_district_office(data: dict):
    _assert_common(data)
    assert isinstance(data["office_code"], str) and data["office_code"]
    assert isinstance(data["name"], str) and data["name"]
    assert isinstance(data["region_code"], str) and data["region_code"]
    assert isinstance(data["state_code"], str) and data["state_code"]
    assert isinstance(data["override_rate_pct"], (int, float))
    assert isinstance(data["override_cap_cents"], int)
    assert isinstance(data["override_paid_cents"], int)
    assert data["override_paid_cents"] >= 0
    assert data["status"] in ("ACTIVE", "SUSPENDED", "CLOSED")


# ---------------------------------------------------------------------------
# Advisor
# ---------------------------------------------------------------------------
def assert_advisor(data: dict):
    _assert_common(data)
    assert isinstance(data["full_name"], str) and data["full_name"]
    assert isinstance(data["email"], str) and data["email"]
    assert isinstance(data["district_office_id"], str)
    assert data["sponsoring_advisor_id"] is None or isinstance(data["sponsoring_advisor_id"], str)
    assert data["rank"] in ("REP", "DISTRICT_DIRECTOR", "MANAGING_DIRECTOR")
    assert data["contract_status"] in (
        "NOT_CONTRACTED", "ACTIVE_TRAINING", "VALIDATING", "AT_RISK", "VALIDATED", "TERMINATED")
    assert data["validation_posture"] in (
        "VALIDATING", "VALIDATED", "AT_RISK", "FAILED_POSTURE")
    assert data["insurance_license_status"] in ("NONE", "PENDING", "ACTIVE", "LAPSED")
    assert data["securities_registration_status"] in ("NONE", "PENDING", "ACTIVE", "SUSPENDED")
    assert data["appointment_status"] in ("NONE", "REQUESTED", "APPROVED", "TERMINATED")
    for field in ("team_production_cents", "override_income_cents",
                  "chargeback_balance_cents", "renewal_commission_cents"):
        assert isinstance(data[field], int), f"{field} must be an integer"
    assert isinstance(data["orphan_pool_access"], bool)
    assert data["terminated_at"] is None or is_iso8601_timestamp(data["terminated_at"])


def assert_advisor_invariants(data: dict):
    """Invariants that hold on every advisor read."""
    assert data["team_production_cents"] >= 0
    assert data["renewal_commission_cents"] >= 0
    if data["contract_status"] == "VALIDATED":
        assert data["validation_posture"] == "VALIDATED"
    if data["contract_status"] == "TERMINATED":
        assert data["validation_posture"] == "FAILED_POSTURE"
    # orphan-pool access is granted only to validators
    assert data["orphan_pool_access"] in (True, False)
    if data["orphan_pool_access"]:
        assert data["validation_posture"] == "VALIDATED"


# ---------------------------------------------------------------------------
# RecruitingCandidate
# ---------------------------------------------------------------------------
def assert_candidate(data: dict):
    _assert_common(data)
    assert isinstance(data["full_name"], str) and data["full_name"]
    assert data["source_channel"] in ("CAMPUS", "CAREER_CHANGER", "REFERRAL", "INTERNAL")
    assert isinstance(data["district_office_id"], str)
    assert data["stage"] in (
        "SOURCED", "SCREENED", "ASSESSMENT_PENDING", "ASSESSED", "INTERVIEW_READY",
        "OFFER_EXTENDED", "OFFER_ACCEPTED", "OFFER_DECLINED", "REENGAGED",
        "REJECTED", "CONTRACTED")
    assert isinstance(data["reengagement_count"], int)
    assert data["reengagement_count"] >= 0
    assert is_iso8601_timestamp(data["entered_stage_at"])


# ---------------------------------------------------------------------------
# SelectionAssessment
# ---------------------------------------------------------------------------
def assert_selection_assessment(data: dict):
    _assert_common(data)
    assert isinstance(data["candidate_id"], str)
    assert data["assessment_version"] in ("V1", "V2")
    assert data["status"] in ("SCHEDULED", "SCORED", "SUPERSEDED", "INVALIDATED")
    if data["status"] == "SCORED":
        assert isinstance(data["weighted_score"], (int, float))
        assert data["outcome"] in ("PASS", "CONDITIONAL", "FAIL")
        assert isinstance(data["locked_weights"], dict)
        assert set(data["locked_weights"].keys()) == set(COMPETENCY_KEYS)


def _round_half_up_2(value) -> float:
    """Round half up to two decimal places (PRD §2.7/§3.2).

    Python's built-in `round()` is half-to-even on binary floats and reads the
    pinned example of §3.2 (9, 9, 8, 9 under V1) as 8.87; the PRD states
    verbatim that the pinned order yields 8.88, so the half-up rule must be
    applied explicitly.
    """
    return float(Decimal(str(value)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


def assert_scored_against_weight_table(data: dict):
    """The pinned round-then-sum evaluation order, checked from the response."""
    weights = WEIGHT_TABLES[data["assessment_version"]]
    comp = data["competency_scores"]
    expected_locked = {k: weights[k] for k in COMPETENCY_KEYS}
    assert data["locked_weights"] == pytest.approx(expected_locked), \
        "locked_weights must be the weight table actually applied"
    avg = sum(Decimal(str(comp[k])) * Decimal(str(weights[k])) for k in COMPETENCY_KEYS)
    weighted_component = _round_half_up_2(avg * Decimal("0.70"))
    raw_component = _round_half_up_2(Decimal(str(comp["ETHICS"])) * Decimal("0.305"))
    expected = _round_half_up_2(Decimal(str(weighted_component)) + Decimal(str(raw_component)))
    assert data["weighted_score"] == pytest.approx(expected, abs=0.005), (
        f"weighted_score must be {expected} under the {data['assessment_version']} table")


# ---------------------------------------------------------------------------
# EmploymentContract
# ---------------------------------------------------------------------------
def assert_employment_contract(data: dict):
    _assert_common(data)
    assert isinstance(data["advisor_id"], str)
    assert isinstance(data["candidate_id"], str)
    assert data["contract_type"] in ("FULL_TIME", "PART_TIME", "INTERN")
    assert data["training_allowance_mode"] in ("FLAT_MONTHLY", "PRODUCTION_DRAW")
    assert data["contract_status"] in (
        "DRAFT", "ACTIVE_TRAINING", "VALIDATING", "AT_RISK", "VALIDATED", "TERMINATED")
    assert isinstance(data["training_allowance_total_cents"], int)
    assert isinstance(data["training_allowance_paid_cents"], int)
    assert data["training_allowance_paid_cents"] <= data["training_allowance_total_cents"], \
        "allowance paid must never exceed the allowance total"
    assert isinstance(data["validation_requirement_cents"], int)


# ---------------------------------------------------------------------------
# ValidationPeriod
# ---------------------------------------------------------------------------
def assert_validation_period(data: dict):
    _assert_common(data)
    assert isinstance(data["contract_id"], str)
    assert isinstance(data["period_number"], int)
    assert data["period_number"] >= 1
    assert is_iso8601_timestamp(data["start_date"])
    assert is_iso8601_timestamp(data["end_date"])
    assert data["start_date"] < data["end_date"], "start_date must be strictly before end_date"
    assert isinstance(data["required_production_cents"], int)
    assert isinstance(data["achieved_production_cents"], int)
    assert data["achieved_production_cents"] >= 0
    assert isinstance(data["extension_count"], int)
    assert 0 <= data["extension_count"] <= 2
    assert data["status"] in ("OPEN", "PASSED", "FAILED", "EXTENDED")


# ---------------------------------------------------------------------------
# ProductLicense
# ---------------------------------------------------------------------------
def assert_product_license(data: dict):
    _assert_common(data)
    assert isinstance(data["advisor_id"], str)
    assert data["product_line"] in ("LIFE", "ANNUITY", "DISABILITY", "LONG_TERM_CARE")
    assert isinstance(data["license_number"], str) and data["license_number"]
    assert is_iso8601_timestamp(data["effective_date"])
    assert is_iso8601_timestamp(data["expires_at"])
    assert isinstance(data["appointment_required"], bool)
    assert data["status"] in ("PENDING", "ACTIVE", "LAPSED", "REVOKED")


# ---------------------------------------------------------------------------
# SecuritiesRegistration
# ---------------------------------------------------------------------------
def assert_securities_registration(data: dict):
    _assert_common(data)
    assert isinstance(data["advisor_id"], str)
    assert data["registration_type"] in ("SERIES_6", "SERIES_7", "SERIES_63", "SERIES_65", "SERIES_66")
    assert isinstance(data["crd_number"], str) and data["crd_number"]
    assert is_iso8601_timestamp(data["effective_date"])
    assert is_iso8601_timestamp(data["expires_at"])
    assert data["prerequisite_registration_id"] is None or \
        isinstance(data["prerequisite_registration_id"], str)
    assert data["status"] in ("PENDING", "ACTIVE", "SUSPENDED", "TERMINATED")


# ---------------------------------------------------------------------------
# CarrierAppointment
# ---------------------------------------------------------------------------
def assert_carrier_appointment(data: dict):
    _assert_common(data)
    assert isinstance(data["advisor_id"], str)
    assert isinstance(data["requires_license_id"], str)
    assert isinstance(data["carrier_name"], str)
    assert isinstance(data["state_code"], str)
    assert data["appointment_status"] in ("REQUESTED", "APPROVED", "REJECTED", "TERMINATED")
    assert data["appointment_date"] is None or is_iso8601_timestamp(data["appointment_date"])


# ---------------------------------------------------------------------------
# Policy
# ---------------------------------------------------------------------------
def assert_policy(data: dict):
    _assert_common(data)
    assert isinstance(data["policy_number"], str) and data["policy_number"]
    assert isinstance(data["writing_advisor_id"], str)
    assert isinstance(data["carrier_name"], str)
    assert data["product_line"] in ("LIFE", "ANNUITY", "DISABILITY", "LONG_TERM_CARE")
    assert isinstance(data["annual_premium_cents"], int)
    assert isinstance(data["is_advanced_commission"], bool)
    assert isinstance(data["months_inforce"], int)
    assert data["months_inforce"] >= 0
    assert isinstance(data["orphaned"], bool)
    assert data["status"] in ("ISSUED", "ACTIVE", "LAPSED", "SURRENDERED", "TERMINATED")
    assert data["lapse_date"] is None or is_iso8601_timestamp(data["lapse_date"])
    assert data["reinstatement_date"] is None or is_iso8601_timestamp(data["reinstatement_date"])


# ---------------------------------------------------------------------------
# JointWorkCase
# ---------------------------------------------------------------------------
def assert_joint_work_case(data: dict):
    _assert_common(data)
    assert isinstance(data["policy_id"], str)
    assert isinstance(data["lead_advisor_id"], str)
    assert isinstance(data["support_advisor_id"], str)
    assert data["lead_advisor_id"] != data["support_advisor_id"], \
        "lead and support advisors must be different advisors"
    assert isinstance(data["split_pct_lead"], (int, float))
    assert 0 < data["split_pct_lead"] <= 1
    assert data["status"] in ("OPEN", "SUBMITTED", "CLOSED", "VOIDED")
    assert data["submitted_at"] is None or is_iso8601_timestamp(data["submitted_at"])


# ---------------------------------------------------------------------------
# CommissionCredit
# ---------------------------------------------------------------------------
def assert_commission_credit(data: dict):
    _assert_common(data)
    assert isinstance(data["policy_id"], str)
    assert isinstance(data["advisor_id"], str)
    assert data["credit_type"] in (
        "PRIMARY", "SPLIT_LEAD", "SPLIT_SUPPORT", "OVERRIDE_DO", "OVERRIDE_MD",
        "TRAINING_ALLOWANCE", "RENEWAL")
    assert isinstance(data["credit_pct"], (int, float))
    for field in ("gross_commission_cents", "net_commission_cents",
                  "advanced_paid_cents", "case_gross_commission_cents",
                  "chargeback_assessed_cents", "recovered_cents"):
        assert isinstance(data[field], int), f"{field} must be an integer"
    assert data["chargeback_assessed_cents"] >= 0
    assert data["recovered_cents"] >= 0
    assert data["status"] in ("ACCRUED", "PAID", "CHARGED_BACK", "RECOVERED", "VOIDED")
    assert data["chargeback_reason"] in (
        None, "LAPSE_WITHIN_12MO", "SURRENDER", "REPLACEMENT", "TERMINATION")


def assert_policy_credit_conservation(credits: list):
    """The per-policy commission conservation invariant as acceptance criterion.

    The sum of gross_commission_cents over the policy's non-VOIDED PRIMARY /
    SPLIT_LEAD / SPLIT_SUPPORT credits equals case_gross_commission_cents exactly.
    """
    live = [c for c in credits
            if c["status"] != "VOIDED"
            and c["credit_type"] in ("PRIMARY", "SPLIT_LEAD", "SPLIT_SUPPORT")]
    assert live, "a policy must always carry at least one live primary/split credit"
    case_gross = live[0]["case_gross_commission_cents"]
    for c in credits:
        assert c["case_gross_commission_cents"] == case_gross, \
            "case_gross_commission_cents must be identical on every credit row of the policy"
    total = sum(c["gross_commission_cents"] for c in live)
    assert total == case_gross, (
        f"live gross credits sum to {total}, expected case_gross_commission_cents {case_gross}")


def assert_chargeback_balance_invariant(advisor: dict, credits: list):
    """The advisor's chargeback balance equals the CHARGED_BACK remainder."""
    expected = sum(c["chargeback_assessed_cents"] - c["recovered_cents"]
                   for c in credits if c["status"] == "CHARGED_BACK")
    assert advisor["chargeback_balance_cents"] == expected, (
        f"chargeback_balance_cents {advisor['chargeback_balance_cents']} "
        f"!= sum of assessed-minus-recovered {expected}")


def assert_chargeback_block_exceeded(advisor: dict):
    assert advisor["chargeback_balance_cents"] > CHARGEBACK_BLOCK_CENTS


# ---------------------------------------------------------------------------
# PersistencyRecord
# ---------------------------------------------------------------------------
def assert_persistency_record(data: dict):
    _assert_common(data)
    assert isinstance(data["advisor_id"], str)
    assert isinstance(data["measurement_period"], str)
    assert is_iso8601_timestamp(data["measurement_start"])
    assert is_iso8601_timestamp(data["measurement_end"])
    assert isinstance(data["policies_issued"], int)
    assert isinstance(data["policies_persisted"], int)
    assert data["status"] in ("PROVISIONAL", "FINALIZED", "DISPUTED")
    if data["status"] == "FINALIZED":
        assert data["persistency_tier"] in ("TIER_1", "TIER_2", "TIER_3", "INELIGIBLE")
        assert data["persistency_pct"] is not None
        assert data["renewal_rate_pct"] is not None
        assert isinstance(data["renewal_commission_cents"], int)


def tier_for_pct(pct: float) -> str:
    if pct >= TIER_1_MIN:
        return "TIER_1"
    if pct >= TIER_2_MIN:
        return "TIER_2"
    if pct >= TIER_3_MIN:
        return "TIER_3"
    return "INELIGIBLE"


# ---------------------------------------------------------------------------
# OrphanPolicyAssignment
# ---------------------------------------------------------------------------
def assert_orphan_assignment(data: dict):
    _assert_common(data)
    assert isinstance(data["policy_id"], str)
    assert isinstance(data["from_advisor_id"], str)
    assert data["to_advisor_id"] is None or isinstance(data["to_advisor_id"], str)
    assert data["assignment_method"] in ("ROUND_ROBIN", "SENIORITY", "MANUAL")
    assert data["status"] in ("PENDING", "ASSIGNED", "REJECTED")
    if data["status"] == "ASSIGNED":
        assert isinstance(data["to_advisor_id"], str)
        assert is_iso8601_timestamp(data["assigned_at"])
    if data["status"] == "PENDING":
        assert data["to_advisor_id"] is None
        assert data["assigned_at"] is None