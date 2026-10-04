"""Entity assertions and domain invariant checkers (PRD §2.4, §3).

Every resource shares the common properties of §2.4: `id` (UUID),
`created_at`/`updated_at` (ISO 8601 UTC), and `version` (integer starting as
a small integer at creation). Per-entity checkers assert PRD-exact field
names and the PRD status vocabularies.
"""
from datetime import datetime, timedelta, timezone

import pytest

from prd_bench_local_runner.testing import (
    assert_cost_precision,
    is_iso8601_timestamp,
    is_valid_uuid,
)

from .constants import (
    MONITORING_INTERVAL_DAYS,
    MONITORING_REPORT_COUNT,
    SPECIAL_CONDITIONS_GENERAL,
    SPECIAL_CONDITIONS_INDIVIDUAL,
)
from .types import (
    ALL_RESOURCE_TYPES,
    ATF_PATHWAYS,
    GENERAL_PATHWAYS,
    AaStatus,
    Agency,
    AppealStatus,
    ApplicationStatus,
    BankStatus,
    CaseSource,
    CaseStatus,
    CommentStatus,
    CommentType,
    CreditTxnStatus,
    Determination,
    JdStatus,
    JdType,
    LedpaConclusion,
    Mechanism,
    NoticeStatus,
    OrganizationType,
    Pathway,
    PermitStatus,
    PirOutcome,
    PlanStatus,
    ReportOutcome,
    ReportStatus,
    ResolutionTrack,
)


# ---------------------------------------------------------------------------
# Timestamp helpers
# ---------------------------------------------------------------------------
def parse_iso8601(value) -> datetime:
    """Parse an ISO 8601 UTC timestamp, accepting both `Z` and `+00:00`
    renderings and optional fractional seconds."""
    assert isinstance(value, str), f"expected ISO 8601 string, got {value!r}"
    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    dt = datetime.fromisoformat(text)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def iso_add_days(value: str, days: int) -> str:
    """Return the ISO 8601 instant `days` after `value`, rendered as
    YYYY-MM-DDTHH:MM:SSZ (fixtures use whole-day arithmetic throughout)."""
    dt = parse_iso8601(value) + timedelta(days=days)
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def assert_iso_instants_equal(actual, expected, label="timestamp"):
    """Compare two ISO 8601 instants by value, tolerant of fractional-second
    formatting differences between renderings of the same instant."""
    assert parse_iso8601(actual) == parse_iso8601(expected), (
        f"{label}: expected instant {expected}, got {actual}"
    )


def _assert_common(data, entity_name):
    assert isinstance(data, dict), f"{entity_name} response must be an object"
    assert is_valid_uuid(data.get("id", "")), f"{entity_name}.id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        f"{entity_name}.created_at must be ISO 8601"
    )
    assert is_iso8601_timestamp(data.get("updated_at", "")), (
        f"{entity_name}.updated_at must be ISO 8601"
    )
    assert isinstance(data.get("version"), int) and data["version"] >= 1, (
        f"{entity_name}.version must be a positive integer"
    )


def _enum_values(enum_cls):
    return [e.value for e in enum_cls]


# ---------------------------------------------------------------------------
# Per-entity assertions
# ---------------------------------------------------------------------------
def assert_applicant(data: dict):
    _assert_common(data, "Applicant")
    assert isinstance(data["legal_name"], str) and data["legal_name"]
    assert data["organization_type"] in _enum_values(OrganizationType)
    assert isinstance(data["contact_email"], str) and data["contact_email"]
    assert isinstance(data["prior_violation_count"], int)
    assert data["prior_violation_count"] >= 0


def assert_site(data: dict):
    _assert_common(data, "WatersSite")
    assert is_valid_uuid(data.get("applicant_id", ""))
    assert isinstance(data["site_name"], str) and data["site_name"]
    assert isinstance(data["state_code"], str) and len(data["state_code"]) == 2
    assert isinstance(data["watershed_code"], str) and data["watershed_code"]
    assert data["total_acres"] > 0
    types_present = data["resource_types_present"]
    assert isinstance(types_present, list) and len(types_present) > 0
    for t in types_present:
        assert t in ALL_RESOURCE_TYPES, f"unknown resource type {t}"


def assert_jd(data: dict):
    _assert_common(data, "JurisdictionalDetermination")
    assert is_valid_uuid(data.get("site_id", ""))
    assert data["jd_type"] in _enum_values(JdType)
    assert data["determination"] in _enum_values(Determination)
    assert isinstance(data["rationale"], str)
    assert data["status"] in _enum_values(JdStatus)
    if data["status"] == JdStatus.DRAFT.value:
        # PRD §3.1: while DRAFT both issued_date and expiration_date are null.
        assert data.get("issued_date") is None
        assert data.get("expiration_date") is None


def assert_appeal(data: dict):
    _assert_common(data, "Appeal")
    assert is_valid_uuid(data.get("jd_id", ""))
    assert isinstance(data["grounds_text"], str)
    assert data["status"] in _enum_values(AppealStatus)
    assert is_iso8601_timestamp(data.get("filed_date", ""))
    if data["status"] == AppealStatus.FILED.value:
        assert data.get("decided_date") is None
        assert data.get("decision_rationale") is None
    else:
        assert is_iso8601_timestamp(data.get("decided_date", ""))


def assert_application(data: dict):
    _assert_common(data, "PermitApplication")
    assert is_valid_uuid(data.get("applicant_id", ""))
    assert is_valid_uuid(data.get("site_id", ""))
    assert is_valid_uuid(data.get("jd_id", ""))
    assert data["pathway"] in _enum_values(Pathway)
    impacts = data["impacts"]
    assert isinstance(impacts, list) and len(impacts) > 0
    for line in impacts:
        assert line["resource_type"] in ALL_RESOURCE_TYPES
        assert line["impact_acres"] > 0
    expected_total = sum(line["impact_acres"] for line in impacts)
    assert data["total_impact_acres"] == pytest.approx(expected_total, abs=1e-6), (
        "total_impact_acres must equal the sum of impacts[].impact_acres (PRD §3.3)"
    )
    assert data["is_after_the_fact"] == (data["pathway"] in ATF_PATHWAYS)
    # PRD §3.3: compensatory mitigation required exactly when total > 0.10.
    assert data["compensatory_mitigation_required"] == (data["total_impact_acres"] > 0.10)
    assert data["status"] in _enum_values(ApplicationStatus)
    assert data["notice_status"] in _enum_values(NoticeStatus)
    if data["pathway"] in GENERAL_PATHWAYS:
        # PRD §3.3: the streamlined path never carries pir fields.
        assert data.get("pir_score") is None
        assert data.get("pir_outcome") is None
    elif data.get("pir_outcome") is not None:
        assert data["pir_outcome"] in _enum_values(PirOutcome)


def assert_alternatives_analysis(data: dict):
    _assert_common(data, "AlternativesAnalysis")
    assert is_valid_uuid(data.get("application_id", ""))
    assert isinstance(data["avoidance_demonstrated"], bool)
    assert isinstance(data["avoidance_narrative"], str)
    assert isinstance(data["minimization_steps"], list)
    assert data["ledpa_conclusion"] in _enum_values(LedpaConclusion)
    assert isinstance(data["offsite_alternatives_considered"], int)
    assert data["offsite_alternatives_considered"] >= 0
    assert isinstance(data["revision_count"], int) and data["revision_count"] >= 0
    assert data["status"] in _enum_values(AaStatus)


def assert_agency_comment(data: dict):
    _assert_common(data, "AgencyComment")
    assert is_valid_uuid(data.get("application_id", ""))
    assert data["agency"] in _enum_values(Agency)
    assert data["comment_type"] in _enum_values(CommentType)
    assert isinstance(data["comment_text"], str)
    assert is_iso8601_timestamp(data.get("filed_date", ""))
    assert data["status"] in _enum_values(CommentStatus)
    if data["status"] == CommentStatus.FILED.value:
        assert data.get("resolution_text") is None


def assert_mitigation_plan(data: dict):
    _assert_common(data, "MitigationPlan")
    assert is_valid_uuid(data.get("application_id", ""))
    assert data["mechanism"] in _enum_values(Mechanism)
    assert data["financial_assurance_dollars"] >= 0
    assert isinstance(data["long_term_stewardship_secured"], bool)
    required = data["required_credits_by_type"]
    assert isinstance(required, dict) and len(required) > 0
    for t, credits in required.items():
        assert t in ALL_RESOURCE_TYPES
        assert credits > 0
        assert_cost_precision(credits)
    assert data["status"] in _enum_values(PlanStatus)
    # PRD §3.6: ilf_fee_due_dollars exists only for IN_LIEU_FEE / COMBINATION.
    if data["mechanism"] in (Mechanism.IN_LIEU_FEE.value, Mechanism.COMBINATION.value):
        assert data["ilf_fee_due_dollars"] is not None
        assert data["ilf_fee_due_dollars"] > 0
        assert_cost_precision(data["ilf_fee_due_dollars"])
    else:
        assert data.get("ilf_fee_due_dollars") is None
    if data["status"] in (
        PlanStatus.CREDITS_SECURED.value,
        PlanStatus.ACTIVE.value,
        PlanStatus.COMPLETED.value,
    ):
        # PRD §3.6: either securing route stamps secured_date with the clock.
        assert is_iso8601_timestamp(data.get("secured_date", ""))


def assert_mitigation_bank(data: dict):
    _assert_common(data, "MitigationBank")
    assert isinstance(data["bank_name"], str) and data["bank_name"]
    assert isinstance(data["sponsor_name"], str) and data["sponsor_name"]
    assert isinstance(data["state_code"], str) and len(data["state_code"]) == 2
    watersheds = data["service_area_watersheds"]
    assert isinstance(watersheds, list) and len(watersheds) > 0
    for t, cap in data["credit_capacity"].items():
        assert t in ALL_RESOURCE_TYPES
        assert cap >= 0
    for t, price in data["base_price_per_credit"].items():
        assert t in ALL_RESOURCE_TYPES
        assert price > 0
    assert data["status"] in _enum_values(BankStatus)
    assert_cost_precision(data["revenue_dollars"])
    assert_bank_inventory_conserved(data)


def assert_credit_transaction(data: dict):
    _assert_common(data, "CreditTransaction")
    assert is_valid_uuid(data.get("bank_id", ""))
    assert is_valid_uuid(data.get("plan_id", ""))
    assert data["resource_type"] in ALL_RESOURCE_TYPES
    assert data["credits"] > 0
    assert data["status"] in _enum_values(CreditTxnStatus)
    if data["status"] == CreditTxnStatus.RESERVED.value:
        # PRD §3.6: prices are stamped only at purchase.
        assert data.get("price_per_credit_dollars") is None
        assert data.get("total_price_dollars") is None
    elif data["status"] == CreditTxnStatus.PURCHASED.value:
        assert data["price_per_credit_dollars"] > 0
        assert data["total_price_dollars"] > 0
        assert_cost_precision(data["price_per_credit_dollars"])
        assert_cost_precision(data["total_price_dollars"])
        assert data["total_price_dollars"] == pytest.approx(
            data["credits"] * data["price_per_credit_dollars"], abs=0.01
        ), "total_price_dollars = credits * price_per_credit_dollars (PRD §3.6)"


def assert_permit(data: dict):
    _assert_common(data, "Permit")
    assert is_valid_uuid(data.get("application_id", ""))
    number = data["permit_number"]
    assert isinstance(number, str) and number.startswith("WP-"), (
        "permit_number is `WP-` plus a four-digit zero-padded sequential count (PRD §3.7)"
    )
    suffix = number[3:]
    assert len(suffix) == 4 and suffix.isdigit()
    assert is_iso8601_timestamp(data.get("issue_date", ""))
    assert is_iso8601_timestamp(data.get("expiration_date", ""))
    assert_iso_instants_equal(
        data["expiration_date"],
        iso_add_days(data["issue_date"], 1825),
        label="permit expiration_date = issue_date + 1825 days (PRD §3.7)",
    )
    assert data["status"] in _enum_values(PermitStatus)
    assert isinstance(data["special_conditions"], list)


def assert_monitoring_report(data: dict):
    _assert_common(data, "MonitoringReport")
    assert is_valid_uuid(data.get("permit_id", ""))
    assert is_valid_uuid(data.get("plan_id", ""))
    assert isinstance(data["period_index"], int)
    assert 1 <= data["period_index"] <= MONITORING_REPORT_COUNT
    assert is_iso8601_timestamp(data.get("due_date", ""))
    assert data["status"] in _enum_values(ReportStatus)
    if data.get("outcome") is not None:
        assert data["outcome"] in _enum_values(ReportOutcome)
    if data.get("outcome") != ReportOutcome.DEFICIENT.value:
        # PRD §3.8: deficiency_notes stays null unless a deficiency is recorded.
        assert data.get("deficiency_notes") is None


def assert_enforcement_case(data: dict):
    _assert_common(data, "EnforcementCase")
    assert is_valid_uuid(data.get("site_id", ""))
    assert is_valid_uuid(data.get("responsible_applicant_id", ""))
    assert data["unauthorized_fill_acres"] >= 0
    assert isinstance(data["description"], str)
    assert data["case_source"] in _enum_values(CaseSource)
    assert is_iso8601_timestamp(data.get("opened_date", ""))
    assert data["case_status"] in _enum_values(CaseStatus)
    assert data["resolution_track"] in _enum_values(ResolutionTrack)
    assert isinstance(data["extension_used"], bool)
    assert data["penalty_accrued_dollars"] >= 0
    if data["case_status"] == CaseStatus.OPENED.value:
        # PRD §3.9: while a case is unconfirmed its accrual reads 0.
        assert data.get("confirmed_date") is None
        assert data["penalty_accrued_dollars"] == 0
    if data["case_status"] != CaseStatus.CLOSED.value:
        assert data.get("penalty_final_dollars") is None


# ---------------------------------------------------------------------------
# Domain invariant checkers
# ---------------------------------------------------------------------------
def assert_bank_inventory_conserved(bank: dict):
    """Conservation invariant (PRD §3.6): for every bank and resource type,
    credit_capacity == available + reserved + purchased at all times."""
    capacity = bank["credit_capacity"]
    available = bank["available_credits_by_type"]
    reserved = bank["credits_reserved_by_type"]
    purchased = bank["credits_purchased_by_type"]
    for t, cap in capacity.items():
        a = available.get(t, 0.0)
        r = reserved.get(t, 0.0)
        p = purchased.get(t, 0.0)
        assert cap == pytest.approx(a + r + p, abs=1e-6), (
            f"inventory drift for {t}: capacity {cap} != available {a} + "
            f"reserved {r} + purchased {p}"
        )


def assert_credit_requirement(plan: dict, expected_by_type: dict, field="required_credits_by_type"):
    """Per-type credit requirement matches the expected map (2dp values)."""
    actual = plan[field]
    assert isinstance(actual, dict), f"{field} must be an object"
    assert set(actual.keys()) == set(expected_by_type.keys()), (
        f"{field} keys {sorted(actual.keys())} != expected {sorted(expected_by_type.keys())}"
    )
    for t, expected in expected_by_type.items():
        assert actual[t] == pytest.approx(expected, abs=0.005), (
            f"{field}[{t}]: expected {expected}, got {actual[t]}"
        )


def assert_permit_conditions_for_pathway(permit: dict, pathway: str):
    """Special conditions are pinned per pathway and never vary (PRD §3.7)."""
    if pathway in GENERAL_PATHWAYS:
        assert permit["special_conditions"] == SPECIAL_CONDITIONS_GENERAL
    else:
        assert permit["special_conditions"] == SPECIAL_CONDITIONS_INDIVIDUAL


def assert_monitoring_schedule_shape(reports: list, issue_date: str):
    """Exactly five reports, period_index 1..5 ascending, each due at
    issue_date + 365 * period_index days, all opening DUE (PRD §3.7)."""
    assert len(reports) == MONITORING_REPORT_COUNT, (
        f"expected {MONITORING_REPORT_COUNT} reports, got {len(reports)}"
    )
    for i, report in enumerate(reports, start=1):
        assert report["period_index"] == i, (
            f"reports must be sorted by period_index ascending: position {i} "
            f"has period_index {report['period_index']}"
        )
        assert_iso_instants_equal(
            report["due_date"],
            iso_add_days(issue_date, MONITORING_INTERVAL_DAYS * i),
            label=f"report {i} due_date = issue_date + {MONITORING_INTERVAL_DAYS * i} days",
        )
        assert report["status"] == ReportStatus.DUE.value


def expected_coverage_interval(issue_date: str, period_index: int) -> tuple:
    """Zero-gap coverage interval for report `period_index` (PRD §3.8): the
    first report starts at the permit's issue_date and each later report
    starts where the previous one ended. With annual submissions the interval
    for period i is [issue + 365*(i-1) days, issue + 365*i days]."""
    start = iso_add_days(issue_date, MONITORING_INTERVAL_DAYS * (period_index - 1))
    end = iso_add_days(issue_date, MONITORING_INTERVAL_DAYS * period_index)
    return start, end
