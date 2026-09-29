"""Entity assertions and domain invariant checkers (PRD §2.5, §2.6, §3)."""
from typing import Any, Dict, Optional

from prd_bench_local_runner.testing import (
    is_iso8601_timestamp,
    is_valid_uuid,
)

# --------------------------------------------------------------------------
# Numeric and temporal comparison helpers (PRD §2.4, §2.6)
# --------------------------------------------------------------------------
PCT_TOLERANCE = 1e-6


def as_pct(value: Any) -> float:
    """Coerce a percentage field to float — percentages carry at most 4 decimals."""
    assert value is not None, "percentage field must not be null"
    return float(value)


def as_minor(value: Any) -> int:
    """Coerce a money field to int — money is always whole minor units."""
    assert value is not None, "money field must not be null"
    number = float(value)
    assert abs(number - round(number)) < 1e-9, f"money must be whole minor units, got {value}"
    return int(round(number))


def assert_pct_equals(actual: Any, expected: float, label: str = "percentage") -> None:
    got = as_pct(actual)
    assert abs(got - expected) <= PCT_TOLERANCE, f"{label}: expected {expected}, got {actual}"


def assert_money_equals(actual: Any, expected: int, label: str = "amount") -> None:
    got = as_minor(actual)
    assert got == expected, f"{label}: expected {expected} minor units, got {actual}"


def assert_score_equals(actual: Any, expected: float, label: str = "score") -> None:
    got = float(actual)
    assert abs(got - expected) <= 1e-9, f"{label}: expected {expected}, got {actual}"


def canonical_instant(value: str) -> str:
    """Normalise an instant to ISO-8601 UTC with exactly three fractional digits."""
    assert isinstance(value, str) and value, f"instant must be a non-empty string, got {value!r}"
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


def assert_instant_equals(actual: Any, expected: str, label: str = "instant") -> None:
    assert actual is not None, f"{label} must not be null"
    assert canonical_instant(str(actual)) == canonical_instant(expected), (
        f"{label}: expected {expected}, got {actual}"
    )


def assert_common_fields(data: Dict[str, Any]) -> None:
    """Every resource carries id + created_at; most also carry updated_at + version."""
    assert is_valid_uuid(data.get("id", "")), f"id must be a UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        f"created_at must be ISO 8601, got {data.get('created_at')!r}"
    )
    assert is_iso8601_timestamp(data.get("updated_at", "")), (
        f"updated_at must be ISO 8601, got {data.get('updated_at')!r}"
    )
    assert isinstance(data.get("version"), int) and data["version"] >= 1, (
        f"version must be an integer >= 1, got {data.get('version')!r}"
    )


def assert_append_only_fields(data: Dict[str, Any]) -> None:
    """Append-only evidence records carry only id and created_at (PRD §2.5)."""
    assert is_valid_uuid(data.get("id", "")), f"id must be a UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        f"created_at must be ISO 8601, got {data.get('created_at')!r}"
    )
    assert "version" not in data, "append-only records must not expose version"
    assert "updated_at" not in data, "append-only records must not expose updated_at"


def assert_envelope_meta(body: Dict[str, Any]) -> None:
    """meta.api_request_id starts with req_ and the timestamp is a UTC instant."""
    meta = body["meta"]
    assert str(meta["api_request_id"]).startswith("req_"), (
        f"api_request_id must start with req_, got {meta['api_request_id']!r}"
    )
    assert is_iso8601_timestamp(meta["api_request_timestamp"]), (
        f"api_request_timestamp must be ISO 8601, got {meta['api_request_timestamp']!r}"
    )


# --------------------------------------------------------------------------
# Per-resource assertions
# --------------------------------------------------------------------------
def assert_cedent(data: Dict[str, Any]) -> None:
    assert_common_fields(data)
    assert isinstance(data["name"], str) and 1 <= len(data["name"]) <= 120
    assert data["domicile_code"] == data["domicile_code"].upper()
    assert len(data["domicile_code"]) == 5
    assert data["financial_rating"] in ("A_PLUS", "A", "B_PLUS", "B")
    assert data["status"] in ("ACTIVE", "SUSPENDED")
    assert as_minor(data["settled_receipts_minor"]) >= 0
    assert as_minor(data["outstanding_reinstatement_premium_minor"]) >= 0


def assert_reinsurer(data: Dict[str, Any]) -> None:
    assert_common_fields(data)
    assert data["security_rating"] in ("AAA", "AA", "A", "BBB", "BB")
    assert as_minor(data["capacity_limit_minor"]) > 0
    assert 0 < as_pct(data["max_line_pct"]) <= 100
    assert isinstance(data["lead_authorised"], bool)
    assert data["security_status"] in ("APPROVED", "RESTRICTED", "SUSPENDED")
    assert as_minor(data["committed_capacity_minor"]) >= 0
    assert as_minor(data["available_capacity_minor"]) == as_minor(
        data["capacity_limit_minor"]
    ) - as_minor(data["committed_capacity_minor"])


def assert_program(data: Dict[str, Any]) -> None:
    assert_common_fields(data)
    assert is_valid_uuid(data["cedent_id"])
    assert data["line_of_business"] in ("PROPERTY", "CASUALTY", "MARINE", "MOTOR")
    assert 2020 <= data["underwriting_year"] <= 2035
    assert is_iso8601_timestamp(data["inception_date"])
    assert is_iso8601_timestamp(data["expiry_date"])
    assert is_iso8601_timestamp(data["contract_certainty_deadline"])
    assert data["placement_status"] in (
        "DRAFT",
        "SUBMISSION_READY",
        "IN_MARKET",
        "FIRM_ORDER",
        "BOUND",
        "SETTLED",
        "WITHDRAWN",
    )
    assert data["documentation_status"] in (
        "NOT_STARTED",
        "SLIP_ISSUED",
        "WORDING_DRAFTED",
        "WORDING_AGREED",
        "EXECUTED",
        "CERTAINTY_BREACHED",
    )
    assert data["signdown_method"] in ("PRO_RATA", "LEAD_PROTECTED")
    assert isinstance(data["disclosure_acknowledged"], bool)
    assert 0 <= as_pct(data["brokerage_pct"]) <= 10
    for money_field in (
        "estimated_premium_income_minor",
        "gross_written_premium_minor",
        "brokerage_earned_minor",
        "net_remittance_minor",
        "rounding_residue_minor",
        "fiduciary_holding_minor",
    ):
        as_minor(data[money_field])


def assert_exposure_submission(data: Dict[str, Any]) -> None:
    assert_common_fields(data)
    assert is_valid_uuid(data["program_id"])
    assert data["status"] in (
        "DRAFT",
        "ACTUARY_REVIEW",
        "SIGNED_OFF",
        "REJECTED",
        "SUPERSEDED",
    )
    assert 0.0 <= float(data["completeness_score"]) <= 100.0
    assert data["data_quality_flags_count"] <= data["exposure_records_count"]
    assert 0 <= data["historical_years_supplied"] <= 20


def assert_layer(data: Dict[str, Any]) -> None:
    assert_common_fields(data)
    assert is_valid_uuid(data["program_id"])
    assert data["layer_type"] in ("QUOTA_SHARE", "EXCESS_OF_LOSS", "CATASTROPHE")
    assert data["status"] in (
        "OPEN",
        "IN_MARKET",
        "PARTIALLY_PLACED",
        "FULLY_PLACED",
        "OVERSUBSCRIBED",
        "SIGNED_DOWN",
        "BOUND",
        "LAPSED",
    )
    assert as_minor(data["limit_minor"]) > 0
    assert as_minor(data["attachment_minor"]) >= 0
    assert as_minor(data["sublimit_minor"]) <= as_minor(data["limit_minor"])
    assert as_minor(data["quoted_gross_premium_minor"]) >= 0
    assert as_pct(data["written_line_total_pct"]) >= 0
    assert as_pct(data["signed_line_total_pct"]) >= 0
    assert as_minor(data["limit_eroded_minor"]) >= 0
    assert data["reinstatements_used"] <= data["reinstatements_total"]


def assert_market_submission(data: Dict[str, Any]) -> None:
    assert_common_fields(data)
    assert is_valid_uuid(data["layer_id"])
    assert is_valid_uuid(data["reinsurer_id"])
    assert is_iso8601_timestamp(data["response_deadline"])
    assert is_iso8601_timestamp(data["sent_at"])
    assert data["status"] in ("SENT", "QUOTED", "DECLINED", "CLOSED", "EXPIRED")


def assert_quote(data: Dict[str, Any]) -> None:
    assert_common_fields(data)
    assert is_valid_uuid(data["market_submission_id"])
    assert is_valid_uuid(data["layer_id"])
    assert is_valid_uuid(data["reinsurer_id"])
    assert 0 < as_pct(data["offered_line_pct"]) <= 100
    assert 0 < as_pct(data["quoted_rate_pct"]) <= 100
    assert 0 <= as_pct(data["ceding_commission_pct"]) <= 60
    assert 0 <= data["reinstatements_offered"] <= 5
    assert is_iso8601_timestamp(data["expires_at"])
    assert isinstance(data["negotiation_round"], int) and data["negotiation_round"] >= 0
    assert data["status"] in (
        "QUOTED",
        "COUNTERED",
        "REQUOTED",
        "FIRM_ORDER",
        "DECLINED",
        "LAPSED",
        "BOUND",
    )


def assert_signing_line(data: Dict[str, Any]) -> None:
    assert_common_fields(data)
    assert is_valid_uuid(data["layer_id"])
    assert is_valid_uuid(data["quote_id"])
    assert is_valid_uuid(data["reinsurer_id"])
    assert 0 < as_pct(data["written_line_pct"]) <= 100
    assert data["status"] in ("PROVISIONAL", "SIGNED", "BOUND", "RELEASED")
    if data.get("release_reason") is not None:
        assert data["release_reason"] in (
            "WITHDRAWN_BY_BROKER",
            "SECURITY_FAILURE",
            "SIGNDOWN_ZEROED",
            "PROGRAM_WITHDRAWN",
        )
    as_minor(data["committed_capacity_minor"])


def assert_brokerage_disclosure(data: Dict[str, Any]) -> None:
    assert_common_fields(data)
    assert is_valid_uuid(data["program_id"])
    assert 0 <= as_pct(data["brokerage_pct"]) <= 10
    assert data["status"] in ("DRAFT", "DISCLOSED", "ACKNOWLEDGED", "REJECTED")


def assert_contract_document(data: Dict[str, Any]) -> None:
    assert_append_only_fields(data)
    assert is_valid_uuid(data["program_id"])
    assert data["document_type"] in (
        "SLIP",
        "WORDING_DRAFT",
        "AGREED_WORDING",
        "EXECUTED_CONTRACT",
    )
    assert is_iso8601_timestamp(data["issued_at"])
    assert isinstance(data["days_from_inception"], int)


def assert_fiduciary_transaction(data: Dict[str, Any]) -> None:
    assert_common_fields(data)
    assert is_valid_uuid(data["program_id"])
    assert data["txn_type"] in (
        "CEDENT_RECEIPT",
        "CLAIM_COLLECTION",
        "REMITTANCE_REVERSAL",
        "REINSURER_REMITTANCE",
        "BROKERAGE_DEDUCTION",
        "REINSTATEMENT_PREMIUM",
        "CEDENT_PAYOUT",
    )
    assert as_minor(data["amount_minor"]) > 0
    assert data["status"] in ("PENDING", "APPROVED", "SETTLED", "HELD", "REVERSED")
    assert isinstance(data["created_by_user_id"], str) and data["created_by_user_id"]


def assert_claim_advocacy(data: Dict[str, Any]) -> None:
    assert_common_fields(data)
    assert is_valid_uuid(data["layer_id"])
    assert is_iso8601_timestamp(data["event_date"])
    assert as_minor(data["gross_claim_minor"]) > 0
    assert as_minor(data["ceded_claim_minor"]) >= 0
    assert as_minor(data["collectible_minor"]) >= 0
    assert data["status"] in (
        "NOTIFIED",
        "UNDER_REVIEW",
        "DISPUTED",
        "ADVOCACY_NEGOTIATION",
        "ADVOCACY_ARBITRATION",
        "RESOLVED",
        "COLLECTED",
        "WITHDRAWN",
    )
    if data.get("advocacy_route") is not None:
        assert data["advocacy_route"] in ("NEGOTIATION", "ARBITRATION")


def assert_cession_dispute(data: Dict[str, Any]) -> None:
    assert_common_fields(data)
    assert is_valid_uuid(data["claim_advocacy_id"])
    assert is_valid_uuid(data["signing_line_id"])
    assert as_minor(data["disputed_minor"]) > 0
    assert data["dispute_reason"] in (
        "EXCLUSION_APPLIES",
        "LATE_NOTIFICATION",
        "AGGREGATION_DISAGREEMENT",
        "WORDING_AMBIGUITY",
    )
    assert data["status"] in ("RAISED", "UPHELD", "WITHDRAWN", "SETTLED_PARTIAL")


def assert_renewal_report(data: Dict[str, Any]) -> None:
    assert_append_only_fields(data)
    assert is_valid_uuid(data["program_id"])
    assert is_iso8601_timestamp(data["as_of"])
    assert isinstance(data["generated_by_user_id"], str) and data["generated_by_user_id"]


# --------------------------------------------------------------------------
# Domain invariants
# --------------------------------------------------------------------------
def assert_placement_money_invariants(program: Dict[str, Any]) -> None:
    """Gross premium splits into brokerage, net remittance and residue (PRD §3.6)."""
    gross = as_minor(program["gross_written_premium_minor"])
    brokerage = as_minor(program["brokerage_earned_minor"])
    net = as_minor(program["net_remittance_minor"])
    residue = as_minor(program["rounding_residue_minor"])
    assert gross - (brokerage + net) == residue, (
        "rounding_residue_minor must close the gross/brokerage/net identity: "
        f"{gross} - ({brokerage} + {net}) != {residue}"
    )


def assert_capacity_invariants(reinsurer: Dict[str, Any]) -> None:
    """Committed plus available capacity always equals the market's limit (PRD §3.5)."""
    assert as_minor(reinsurer["committed_capacity_minor"]) + as_minor(
        reinsurer["available_capacity_minor"]
    ) == as_minor(reinsurer["capacity_limit_minor"])


def assert_collectible_invariant(advocacy: Dict[str, Any]) -> None:
    """collectible_minor is the ceded amount less disputes, floored at zero (PRD §3.9)."""
    expected = max(
        as_minor(advocacy["ceded_claim_minor"]) - as_minor(advocacy["disputed_minor"]), 0
    )
    assert_money_equals(advocacy["collectible_minor"], expected, "collectible_minor")


def assert_status(data: Dict[str, Any], field: str, expected: str) -> None:
    assert data[field] == expected, f"expected {field} == {expected}, got {data[field]!r}"


def assert_is_null(data: Dict[str, Any], field: str) -> None:
    assert data.get(field, None) is None, f"expected {field} to be null, got {data.get(field)!r}"


def find_row(rows, row_id: str) -> Optional[Dict[str, Any]]:
    for row in rows:
        if row.get("id") == row_id:
            return row
    return None
