"""Domain assertions: per-resource shape checkers and comparison helpers.

Instants compare on a canonical three-fractional-digit UTC rendering, so a
timestamp the contract pins as ``2026-09-22T00:00:00Z`` still matches an
implementation that renders the same moment as ``2026-09-22T00:00:00.000Z``
(PRD section 2.8 fixes the rendering of the common timestamp fields, but the
comparison helper keeps computed-instant assertions spelling-tolerant).

The ``assert_*`` functions check only what the PRD guarantees about a
resource's shape: field presence and value domain. They never demand a field
the PRD leaves to implementation discretion.
"""

from typing import Any, Dict, Iterable, Optional

from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid


# --- Instants -------------------------------------------------------------------

def canonical_instant(value: Optional[str]) -> Optional[str]:
    """Normalise an ISO 8601 UTC instant to ``YYYY-MM-DDTHH:MM:SS.mmmZ`` so two
    spellings of one instant compare equal."""
    if value is None or not isinstance(value, str):
        return value
    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1]
    if "+" in text[10:]:
        text = text[: 10 + text[10:].index("+")]
    if "." in text:
        head, frac = text.split(".", 1)
        frac = (frac + "000")[:3]
    else:
        head, frac = text, "000"
    return f"{head}.{frac}Z"


def assert_instant(actual: Optional[str], expected: Optional[str], label: str = "instant") -> None:
    """Assert two instants denote the same moment (or both are null)."""
    if expected is None:
        assert actual is None, f"{label}: expected null, got {actual!r}"
        return
    assert actual is not None, f"{label}: expected {expected!r}, got null"
    assert canonical_instant(actual) == canonical_instant(expected), (
        f"{label}: expected {expected!r}, got {actual!r}"
    )


def assert_instant_format(value: Any, label: str = "instant") -> None:
    assert isinstance(value, str) and is_iso8601_timestamp(value), (
        f"{label}: not an ISO 8601 UTC instant: {value!r}"
    )


# --- Common field blocks (PRD section 2.8) ---------------------------------------

def assert_mutable_common_fields(data: Dict[str, Any], label: str = "resource") -> None:
    """Primary resources carry id, created_at, updated_at, version."""
    assert is_valid_uuid(data.get("id", "")), f"{label}.id must be a UUID, got {data.get('id')!r}"
    assert_instant_format(data.get("created_at"), f"{label}.created_at")
    assert_instant_format(data.get("updated_at"), f"{label}.updated_at")
    assert isinstance(data.get("version"), int) and not isinstance(data.get("version"), bool), (
        f"{label}.version must be an integer, got {data.get('version')!r}"
    )
    assert data["version"] >= 1, f"{label}.version starts at 1, got {data['version']}"


def assert_append_only_common_fields(data: Dict[str, Any], label: str = "record") -> None:
    """Append-only records carry id and created_at, and never version/updated_at."""
    assert is_valid_uuid(data.get("id", "")), f"{label}.id must be a UUID, got {data.get('id')!r}"
    assert_instant_format(data.get("created_at"), f"{label}.created_at")
    assert "version" not in data, f"{label} must not carry version (append-only)"
    assert "updated_at" not in data, f"{label} must not carry updated_at (append-only)"


def assert_cents(actual: Any, expected: int, label: str = "amount") -> None:
    """Money in the licensing domain is an integer number of cents."""
    assert isinstance(actual, int) and not isinstance(actual, bool), (
        f"{label}: money must be an integer number of cents, got {actual!r}"
    )
    assert actual == expected, f"{label}: expected {expected} cents, got {actual}"


# --- Per-resource shape assertions -------------------------------------------------

def assert_organization(data: Dict[str, Any]) -> None:
    assert_mutable_common_fields(data, "Organization")
    assert isinstance(data.get("org_code"), str) and data["org_code"], "org_code required"
    assert isinstance(data.get("name"), str) and data["name"], "name required"
    assert data.get("org_type") in {"ISSUER", "OBLIGATED_PERSON", "BROKER_DEALER", "MUNICIPAL_ADVISOR"}, (
        f"org_type out of domain: {data.get('org_type')!r}"
    )
    assert data.get("status") in {"ACTIVE", "SUSPENDED"}, f"status out of domain: {data.get('status')!r}"
    assert data.get("compliance_posture") in {"CLEAR", "WATCH"}, (
        f"compliance_posture out of domain: {data.get('compliance_posture')!r}"
    )
    for counter in ("late_report_count", "published_par_total", "active_professional_count"):
        assert isinstance(data.get(counter), int) and data[counter] >= 0, (
            f"{counter} must be a non-negative integer, got {data.get(counter)!r}"
        )


def assert_rule_proposal(data: Dict[str, Any]) -> None:
    assert_mutable_common_fields(data, "RuleProposal")
    assert isinstance(data.get("rule_code"), str) and data["rule_code"], "rule_code required"
    assert isinstance(data.get("title"), str) and data["title"], "title required"
    assert isinstance(data.get("body"), str), "body required"
    assert data.get("category") in {
        "DEALER_CONDUCT", "ADVISOR_CONDUCT", "DISCLOSURE",
        "TRADE_REPORTING", "MARKET_DATA", "QUALIFICATION",
    }, f"category out of domain: {data.get('category')!r}"
    assert data.get("status") in {
        "DRAFT", "OPEN_FOR_COMMENT", "PENDING_APPROVAL", "APPROVED",
        "DISAPPROVED", "EFFECTIVE", "SUPERSEDED",
    }, f"status out of domain: {data.get('status')!r}"
    assert isinstance(data.get("expedited"), bool), "expedited must be boolean"
    assert isinstance(data.get("comment_round"), int) and data["comment_round"] >= 0, (
        f"comment_round must be a non-negative integer, got {data.get('comment_round')!r}"
    )


def assert_comment_letter(data: Dict[str, Any]) -> None:
    assert_mutable_common_fields(data, "CommentLetter")
    assert isinstance(data.get("author_name"), str) and data["author_name"], "author_name required"
    assert isinstance(data.get("body"), str) and data["body"], "body required"
    assert data.get("sentiment") in {"SUPPORT", "OPPOSE", "NEUTRAL"}, (
        f"sentiment out of domain: {data.get('sentiment')!r}"
    )
    assert data.get("status") in {"RECEIVED", "PUBLISHED", "DISMISSED"}, (
        f"status out of domain: {data.get('status')!r}"
    )


def assert_disclosure_submission(data: Dict[str, Any]) -> None:
    assert_mutable_common_fields(data, "DisclosureSubmission")
    assert isinstance(data.get("issuer_org_id"), str) and data["issuer_org_id"], "issuer_org_id required"
    assert data.get("submission_type") in {
        "OFFICIAL_STATEMENT", "ANNUAL_FINANCIAL", "EVENT_NOTICE", "VOLUNTARY",
    }, f"submission_type out of domain: {data.get('submission_type')!r}"
    assert isinstance(data.get("document_uri"), str) and data["document_uri"], "document_uri required"
    cusip = data.get("cusip")
    assert isinstance(cusip, str) and len(cusip) == 9, f"cusip must be 9 characters, got {cusip!r}"
    assert data.get("status") in {"RECEIVED", "PUBLISHED", "DEFICIENT"}, (
        f"status out of domain: {data.get('status')!r}"
    )
    assert data.get("timeliness") in {"TIMELY", "LATE", "NOT_APPLICABLE"}, (
        f"timeliness out of domain: {data.get('timeliness')!r}"
    )


def assert_professional(data: Dict[str, Any]) -> None:
    assert_mutable_common_fields(data, "MunicipalProfessional")
    assert isinstance(data.get("full_name"), str) and data["full_name"], "full_name required"
    assert isinstance(data.get("employer_org_id"), str) and data["employer_org_id"], "employer_org_id required"
    assert data.get("professional_class") in {
        "MUNICIPAL_DEALER_REP", "MUNICIPAL_ADVISOR_REP", "MUNICIPAL_PRINCIPAL",
    }, f"professional_class out of domain: {data.get('professional_class')!r}"
    assert data.get("qualification_status") in {"UNQUALIFIED", "QUALIFIED", "CE_DUE", "LAPSED"}, (
        f"qualification_status out of domain: {data.get('qualification_status')!r}"
    )
    assert data.get("standing") in {"ACTIVE", "SUSPENDED"}, (
        f"standing out of domain: {data.get('standing')!r}"
    )
    assert isinstance(data.get("may_transact"), bool), "may_transact must be boolean"


def assert_exam_attempt(data: Dict[str, Any]) -> None:
    assert_append_only_common_fields(data, "ExamAttempt")
    assert isinstance(data.get("professional_id"), str) and data["professional_id"], "professional_id required"
    assert data.get("series_code") in {"MSRB_50", "MSRB_52", "MSRB_53", "MSRB_54"}, (
        f"series_code out of domain: {data.get('series_code')!r}"
    )
    score = data.get("score")
    assert isinstance(score, int) and not isinstance(score, bool) and 0 <= score <= 100, (
        f"score must be an integer in [0, 100], got {score!r}"
    )
    assert data.get("result") in {"PASS", "FAIL"}, f"result out of domain: {data.get('result')!r}"


def assert_trade_report(data: Dict[str, Any]) -> None:
    assert_mutable_common_fields(data, "TradeReport")
    assert isinstance(data.get("dealer_org_id"), str) and data["dealer_org_id"], "dealer_org_id required"
    cusip = data.get("cusip")
    assert isinstance(cusip, str) and len(cusip) == 9, f"cusip must be 9 characters, got {cusip!r}"
    assert data.get("trade_type") in {"INTER_DEALER", "CUSTOMER_BUY", "CUSTOMER_SELL"}, (
        f"trade_type out of domain: {data.get('trade_type')!r}"
    )
    par = data.get("par_amount")
    assert isinstance(par, int) and not isinstance(par, bool) and par > 0, (
        f"par_amount must be a positive integer, got {par!r}"
    )
    price = data.get("price")
    assert isinstance(price, (int, float)) and not isinstance(price, bool) and price > 0, (
        f"price must be a positive number, got {price!r}"
    )
    assert_instant_format(data.get("executed_at"), "executed_at")
    assert_instant_format(data.get("reported_at"), "reported_at")
    assert isinstance(data.get("late_flag"), bool), "late_flag must be boolean"
    seconds_late = data.get("seconds_late")
    assert isinstance(seconds_late, int) and not isinstance(seconds_late, bool) and seconds_late >= 0, (
        f"seconds_late must be a non-negative integer, got {seconds_late!r}"
    )
    published_par = data.get("published_par")
    assert isinstance(published_par, int) and not isinstance(published_par, bool) and published_par > 0, (
        f"published_par must be a positive integer, got {published_par!r}"
    )
    assert isinstance(data.get("capped_flag"), bool), "capped_flag must be boolean"
    assert data.get("status") in {"DISSEMINATED", "CANCELLED"}, (
        f"status out of domain: {data.get('status')!r}"
    )


def assert_data_subscription(data: Dict[str, Any]) -> None:
    assert_mutable_common_fields(data, "DataSubscription")
    assert data.get("product_code") in {"TRADE_REALTIME", "TRADE_HISTORICAL", "DISCLOSURE_ARCHIVE"}, (
        f"product_code out of domain: {data.get('product_code')!r}"
    )
    assert isinstance(data.get("licensee_org_id"), str) and data["licensee_org_id"], "licensee_org_id required"
    assert isinstance(data.get("subscriber_principal"), str) and data["subscriber_principal"], (
        "subscriber_principal required"
    )
    assert data.get("license_scope") in {"INTERNAL", "DISPLAY", "REDISTRIBUTION"}, (
        f"license_scope out of domain: {data.get('license_scope')!r}"
    )
    seats = data.get("seats")
    assert isinstance(seats, int) and not isinstance(seats, bool) and seats >= 1, (
        f"seats must be an integer >= 1, got {seats!r}"
    )
    assert data.get("status") in {"PENDING", "ACTIVE", "TERMINATED", "REJECTED"}, (
        f"status out of domain: {data.get('status')!r}"
    )
    assert isinstance(data.get("monthly_fee_cents"), int) and data["monthly_fee_cents"] >= 0, (
        f"monthly_fee_cents must be a non-negative integer, got {data.get('monthly_fee_cents')!r}"
    )
    assert isinstance(data.get("annual_invoice_cents"), int) and data["annual_invoice_cents"] >= 0, (
        f"annual_invoice_cents must be a non-negative integer, got {data.get('annual_invoice_cents')!r}"
    )


def assert_enforcement_referral(data: Dict[str, Any]) -> None:
    assert_mutable_common_fields(data, "EnforcementReferral")
    assert isinstance(data.get("rule_code"), str) and data["rule_code"], "rule_code required"
    assert isinstance(data.get("violation_summary"), str), "violation_summary required"
    assert data.get("examining_authority") in {"DEALER_EXAM_AUTHORITY", "ADVISOR_EXAM_AUTHORITY"}, (
        f"examining_authority out of domain: {data.get('examining_authority')!r}"
    )
    assert data.get("status") in {"OPEN", "REFERRED", "CLOSED_ACTION_TAKEN", "CLOSED_NO_ACTION"}, (
        f"status out of domain: {data.get('status')!r}"
    )
    assert isinstance(data.get("needs_rule_review"), bool), "needs_rule_review must be boolean"
    # Exactly one subject is set.
    subjects = [data.get("subject_org_id"), data.get("subject_professional_id")]
    assert sum(1 for s in subjects if s) == 1, f"exactly one subject must be set, got {subjects!r}"


def assert_solicitation_record(data: Dict[str, Any]) -> None:
    assert_append_only_common_fields(data, "SolicitationRecord")
    assert isinstance(data.get("advisor_org_id"), str) and data["advisor_org_id"], "advisor_org_id required"
    assert isinstance(data.get("municipal_entity_name"), str) and data["municipal_entity_name"], (
        "municipal_entity_name required"
    )
    assert data.get("compensation_type") in {"FIXED", "HOURLY", "CONTINGENT"}, (
        f"compensation_type out of domain: {data.get('compensation_type')!r}"
    )
    cents = data.get("compensation_cents")
    assert isinstance(cents, int) and not isinstance(cents, bool) and cents >= 0, (
        f"compensation_cents must be a non-negative integer, got {cents!r}"
    )
    assert isinstance(data.get("disclosure_provided"), bool), "disclosure_provided must be boolean"


# --- Domain invariants --------------------------------------------------------------

def assert_may_transact_invariant(data: Dict[str, Any]) -> None:
    """may_transact is true precisely when QUALIFIED and standing ACTIVE
    (PRD section 3.6)."""
    expected = data.get("qualification_status") == "QUALIFIED" and data.get("standing") == "ACTIVE"
    assert data.get("may_transact") == expected, (
        f"may_transact {data.get('may_transact')} contradicts "
        f"qualification_status={data.get('qualification_status')} standing={data.get('standing')}"
    )


def assert_envelope_meta(body: Dict[str, Any]) -> None:
    """The meta block carries the prefixed request id and a UTC instant."""
    meta = body["meta"]
    assert isinstance(meta.get("api_request_id"), str)
    assert meta["api_request_id"].startswith("req_"), (
        f"meta.api_request_id must start with 'req_', got {meta['api_request_id']!r}"
    )
    assert_instant_format(meta.get("api_request_timestamp"), "meta.api_request_timestamp")


def assert_ids_in_order(items: Iterable[Dict[str, Any]], label: str = "list") -> None:
    """List responses are sorted by creation timestamp ascending (PRD section 2.3);
    on identical timestamps the order only needs to be stable, so this checks the
    non-decreasing created_at ordering."""
    stamps = [canonical_instant(i.get("created_at")) for i in items]
    assert stamps == sorted(stamps), f"{label}: created_at ordering is not ascending: {stamps!r}"
