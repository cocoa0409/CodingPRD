"""Entity assertions and domain invariant checkers."""

import re

from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid

BARE_UUID_RE = re.compile(
    r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$"
)
ISO_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
ISO_MILLIS_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}Z$")


# --------------------------------------------------------------------------
# Shared record shape
# --------------------------------------------------------------------------
def assert_common_fields(data: dict, entity_name: str = "record"):
    """id is a bare UUID, created_at/updated_at are ISO 8601 UTC, version >= 1."""
    assert is_valid_uuid(data.get("id", "")), f"{entity_name}.id must be a UUID"
    assert BARE_UUID_RE.match(data["id"]), (
        f"{entity_name}.id must be a bare UUID with no type prefix, got {data['id']!r}"
    )
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        f"{entity_name}.created_at must be an ISO 8601 UTC timestamp"
    )
    assert is_iso8601_timestamp(data.get("updated_at", "")), (
        f"{entity_name}.updated_at must be an ISO 8601 UTC timestamp"
    )
    assert isinstance(data.get("version"), int) and data["version"] >= 1, (
        f"{entity_name}.version must be an integer starting at 1"
    )


def assert_iso_date(value, field_name: str):
    assert isinstance(value, str) and ISO_DATE_RE.match(value), (
        f"{field_name} must be a calendar date, got {value!r}"
    )


def assert_iso_millis_timestamp(value, field_name: str):
    """ISO 8601 UTC with exactly three fractional digits."""
    assert isinstance(value, str) and ISO_MILLIS_RE.match(value), (
        f"{field_name} must be ISO 8601 UTC with three fractional digits, got {value!r}"
    )


# --------------------------------------------------------------------------
# Per-entity assertions
# --------------------------------------------------------------------------
def assert_creditor(data: dict):
    assert_common_fields(data, "Creditor")
    assert isinstance(data["name"], str) and data["name"]
    assert isinstance(data["contact_email"], str) and data["contact_email"]
    assert isinstance(data["active_judgment_count"], int)
    assert data["active_judgment_count"] >= 0


def assert_debtor(data: dict):
    assert_common_fields(data, "Debtor")
    assert isinstance(data["full_name"], str) and data["full_name"]
    assert re.match(r"^[A-Z]{2}$", data["state_code"]), (
        "state_code must be exactly two uppercase letters"
    )
    assert isinstance(data["head_of_household"], bool)
    assert isinstance(data["weekly_disposable_earnings_cents"], int)
    assert data["weekly_disposable_earnings_cents"] >= 0
    assert data["locate_status"] in ("UNLOCATED", "LOCATED", "STALE")
    assert isinstance(data["skip_trace_count"], int) and data["skip_trace_count"] >= 0
    assert isinstance(data["no_show_count"], int) and data["no_show_count"] >= 0
    assert_recoverability_score_range(data["recoverability_score"])
    if data.get("certified_recoverability_score") is not None:
        assert_recoverability_score_range(data["certified_recoverability_score"])


def assert_judgment(data: dict):
    assert_common_fields(data, "Judgment")
    assert is_valid_uuid(data["creditor_id"])
    assert is_valid_uuid(data["debtor_id"])
    assert isinstance(data["court_case_number"], str) and data["court_case_number"]
    assert re.match(r"^[A-Z]{2}$", data["state_code"])
    assert data["status"] in ("ACTIVE", "SATISFIED", "EXPIRED")
    assert data["enforcement_posture"] in (
        "NONE", "LIEN_PERFECTED", "ENFORCING", "STAYED",
    )
    assert data["application_order"] in ("STATUTORY_ORDER", "PRINCIPAL_FIRST")
    assert_iso_date(data["entered_on"], "Judgment.entered_on")
    assert_iso_date(data["expires_on"], "Judgment.expires_on")
    for money_field in (
        "original_principal_cents",
        "principal_balance_cents",
        "accrued_interest_cents",
        "costs_balance_cents",
        "total_payoff_cents",
        "collected_to_date_cents",
        "gross_exposure_cents",
    ):
        assert isinstance(data[money_field], int), (
            f"Judgment.{money_field} must be a whole number of cents"
        )
        assert data[money_field] >= 0, f"Judgment.{money_field} must not go negative"
    assert 0 <= data["interest_rate_bps"] <= 3000
    assert isinstance(data["renewal_count"], int)
    assert isinstance(data["renewal_dates"], list)
    assert_judgment_ledger_invariants(data)


def assert_county_filing(data: dict):
    assert_common_fields(data, "CountyFiling")
    assert is_valid_uuid(data["judgment_id"])
    assert isinstance(data["county_code"], str) and data["county_code"]
    assert re.match(r"^[A-Z]{2}$", data["state_code"])
    assert data["filing_type"] in ("ABSTRACT_OF_JUDGMENT", "JUDGMENT_LIEN")
    assert data["status"] in (
        "DRAFT", "SUBMITTED", "RECORDED", "REJECTED", "RELEASED", "LAPSED",
    )
    assert isinstance(data["fee_cents"], int) and data["fee_cents"] >= 0
    assert isinstance(data["rejection_count"], int) and data["rejection_count"] >= 0


def assert_asset_finding(data: dict):
    assert_common_fields(data, "AssetFinding")
    assert is_valid_uuid(data["judgment_id"])
    assert data["asset_type"] in (
        "REAL_PROPERTY", "BANK_ACCOUNT", "EMPLOYMENT", "VEHICLE",
    )
    assert data["source"] in (
        "SKIP_TRACE", "PUBLIC_RECORD", "CREDIT_HEADER", "DEBTOR_EXAM",
    )
    assert data["status"] in ("OPEN", "VERIFIED", "STALE", "EXHAUSTED")
    assert isinstance(data["estimated_value_cents"], int)
    assert data["estimated_value_cents"] >= 0
    assert_custody_conservation(data)


def assert_enforcement_action(data: dict):
    assert_common_fields(data, "EnforcementAction")
    assert is_valid_uuid(data["judgment_id"])
    assert is_valid_uuid(data["asset_finding_id"])
    assert data["action_type"] in ("WAGE_GARNISHMENT", "BANK_LEVY")
    assert data["status"] in (
        "DRAFT", "WRIT_REQUESTED", "SERVED", "SUSPENDED",
        "COLLECTED", "RELEASED", "QUASHED",
    )
    for money_field in ("levy_hold_cents", "collected_cents", "sheriff_fee_cents",
                        "weekly_withholding_cents"):
        assert isinstance(data[money_field], int), (
            f"EnforcementAction.{money_field} must be a whole number of cents"
        )
        assert data[money_field] >= 0


def assert_exemption_claim(data: dict):
    assert_common_fields(data, "ExemptionClaim")
    assert is_valid_uuid(data["enforcement_action_id"])
    assert data["claim_type"] in (
        "HEAD_OF_HOUSEHOLD", "SOCIAL_SECURITY", "WAGE_CAP", "HOMESTEAD",
    )
    assert data["status"] in (
        "FILED", "OPPOSED", "SUSTAINED", "OVERRULED", "DEFAULTED",
    )
    assert isinstance(data["claimed_amount_cents"], int)
    assert data["claimed_amount_cents"] > 0
    assert_iso_date(data["filed_on"], "ExemptionClaim.filed_on")
    assert_iso_date(data["filing_deadline_on"], "ExemptionClaim.filing_deadline_on")
    assert_iso_date(data["opposition_deadline_on"],
                    "ExemptionClaim.opposition_deadline_on")


def assert_debtor_examination(data: dict):
    assert_common_fields(data, "DebtorExamination")
    assert is_valid_uuid(data["judgment_id"])
    assert data["status"] in ("SCHEDULED", "SERVED", "HELD", "NO_SHOW")
    assert data["subpoena_status"] in ("NOT_ISSUED", "ISSUED", "SERVED", "EXPIRED")
    assert isinstance(data["continuance_count"], int)
    assert 0 <= data["continuance_count"] <= 2
    assert_iso_date(data["subpoena_service_deadline_on"],
                    "DebtorExamination.subpoena_service_deadline_on")


def assert_settlement_offer(data: dict):
    assert_common_fields(data, "SettlementOffer")
    assert is_valid_uuid(data["judgment_id"])
    assert data["offered_by"] in ("CREDITOR", "DEBTOR")
    assert data["kind"] in ("LUMP_SUM", "INSTALLMENT")
    assert data["status"] in (
        "OPEN", "ACCEPTED", "REJECTED", "EXPIRED", "COUNTERED",
    )
    assert data["application_order_concession"] in (
        "STATUTORY_ORDER", "PRINCIPAL_FIRST",
    )
    assert isinstance(data["amount_cents"], int) and data["amount_cents"] > 0
    assert 1 <= data["installment_count"] <= 60
    assert isinstance(data["monthly_cents"], int)
    assert isinstance(data["min_acceptable_cents"], int)
    assert 1 <= data["round_number"] <= 4


def assert_installment_agreement(data: dict):
    assert_common_fields(data, "InstallmentAgreement")
    assert is_valid_uuid(data["judgment_id"])
    assert is_valid_uuid(data["settlement_offer_id"])
    assert data["status"] in ("ACTIVE", "DEFAULTED", "COMPLETED", "TERMINATED")
    assert isinstance(data["total_cents"], int) and data["total_cents"] > 0
    assert 1 <= data["installment_count"] <= 60
    assert isinstance(data["monthly_cents"], int)
    assert isinstance(data["final_installment_cents"], int)
    assert isinstance(data["missed_count"], int) and data["missed_count"] >= 0
    assert isinstance(data["reinstatement_count"], int)
    assert_iso_date(data["first_due_on"], "InstallmentAgreement.first_due_on")
    assert_installment_schedule_sums(data)


def assert_payment(data: dict):
    assert_common_fields(data, "Payment")
    assert is_valid_uuid(data["judgment_id"])
    assert data["status"] in ("APPLIED", "REVERSED")
    assert data["source"] in ("DEBTOR_DIRECT", "GARNISHMENT", "LEVY", "SETTLEMENT")
    assert isinstance(data["amount_cents"], int) and data["amount_cents"] > 0
    assert_iso_date(data["received_on"], "Payment.received_on")
    for bucket in ("applied_to_costs_cents", "applied_to_interest_cents",
                   "applied_to_principal_cents"):
        assert isinstance(data[bucket], int), f"Payment.{bucket} must be whole cents"
        assert data[bucket] >= 0
    assert isinstance(data["contingency_fee_cents"], int)


# --------------------------------------------------------------------------
# Domain invariants
# --------------------------------------------------------------------------
def assert_custody_conservation(finding: dict):
    """available_cents + frozen_cents + swept_cents == estimated_value_cents."""
    total = (
        finding["available_cents"] + finding["frozen_cents"] + finding["swept_cents"]
    )
    assert total == finding["estimated_value_cents"], (
        "asset custody must conserve: available "
        f"{finding['available_cents']} + frozen {finding['frozen_cents']} + swept "
        f"{finding['swept_cents']} = {total}, expected "
        f"{finding['estimated_value_cents']}"
    )
    for bucket in ("available_cents", "frozen_cents", "swept_cents"):
        assert finding[bucket] >= 0, f"AssetFinding.{bucket} must not go negative"


def assert_judgment_ledger_invariants(judgment: dict):
    """total_payoff_cents and gross_exposure_cents are the declared sums."""
    expected_payoff = (
        judgment["principal_balance_cents"]
        + judgment["accrued_interest_cents"]
        + judgment["costs_balance_cents"]
    )
    assert judgment["total_payoff_cents"] == expected_payoff, (
        "total_payoff_cents must equal principal + interest + costs, got "
        f"{judgment['total_payoff_cents']} vs {expected_payoff}"
    )
    expected_gross = expected_payoff + judgment["collected_to_date_cents"]
    assert judgment["gross_exposure_cents"] == expected_gross, (
        "gross_exposure_cents must equal the payoff plus collected_to_date_cents, got "
        f"{judgment['gross_exposure_cents']} vs {expected_gross}"
    )


def assert_installment_schedule_sums(agreement: dict):
    """(n - 1) monthly instalments plus the final one must total total_cents."""
    n = agreement["installment_count"]
    reconstructed = (
        agreement["monthly_cents"] * (n - 1) + agreement["final_installment_cents"]
    )
    assert reconstructed == agreement["total_cents"], (
        f"{n - 1} x {agreement['monthly_cents']} + "
        f"{agreement['final_installment_cents']} = {reconstructed}, expected "
        f"{agreement['total_cents']}"
    )


def assert_recoverability_score_range(score):
    assert isinstance(score, int), "recoverability scores are integers"
    assert 0 <= score <= 100, f"recoverability score must be 0..100, got {score}"


def assert_payoff_quote_shape(quote: dict):
    """The non-persisting quote answers with its declared field set."""
    for field in (
        "as_of",
        "application_order",
        "principal_balance_cents",
        "accrued_interest_cents",
        "costs_balance_cents",
        "total_payoff_cents",
        "collected_to_date_cents",
        "gross_exposure_cents",
        "segment_count",
    ):
        assert field in quote, f"payoff quote must carry {field}"
    assert quote["total_payoff_cents"] == (
        quote["principal_balance_cents"]
        + quote["accrued_interest_cents"]
        + quote["costs_balance_cents"]
    )
    assert quote["gross_exposure_cents"] == (
        quote["total_payoff_cents"] + quote["collected_to_date_cents"]
    )


def assert_sweep_summary_shape(summary: dict):
    """The clock advance answers with a summary, not a stored object."""
    for field in (
        "current_utc",
        "expired_judgment_count",
        "defaulted_claim_count",
        "expired_offer_count",
        "expired_subpoena_count",
        "terminated_agreement_count",
    ):
        assert field in summary, f"clock advance summary must carry {field}"


def assert_logical_instant_equals(value, expected_iso: str, field_name: str = "current_utc"):
    """The value denotes exactly the expected ISO 8601 UTC instant.

    PRD 2.5 says the clock summary's `current_utc` "echoes the new logical
    instant" and renders a logical instant as `2026-08-01T00:00:00Z`.  It never
    pins a fractional-digit width for this field: the three-fractional-digit rule
    in 2.2 binds `api_request_timestamp`, and the one in 2.4 binds `created_at` /
    `updated_at` on stored objects, while 2.5 states the clock response "is not a
    stored object".  So the instant is asserted, not its rendering width.
    """
    from datetime import datetime, timezone

    def _parse(text):
        assert isinstance(text, str), f"{field_name} must be a string, got {text!r}"
        assert "T" in text, f"{field_name} must be an ISO 8601 instant, got {text!r}"
        normalised = text[:-1] + "+00:00" if text.endswith(("Z", "z")) else text
        try:
            parsed = datetime.fromisoformat(normalised)
        except ValueError:
            raise AssertionError(
                f"{field_name} must be an ISO 8601 UTC instant, got {text!r}"
            )
        assert parsed.tzinfo is not None, (
            f"{field_name} must carry a UTC designator, got {text!r}"
        )
        return parsed.astimezone(timezone.utc)

    assert _parse(value) == _parse(expected_iso), (
        f"{field_name} must echo the new logical instant {expected_iso!r}, got {value!r}"
    )
