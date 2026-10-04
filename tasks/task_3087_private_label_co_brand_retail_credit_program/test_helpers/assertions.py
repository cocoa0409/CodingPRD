"""Entity assertions and domain invariant checkers (PRD §2.6, §2.7)."""
from decimal import Decimal, ROUND_HALF_UP

from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def round_half_up(value, places: int = 0):
    """Round a number to ``places`` decimals using round-half-up (PRD §2.7).

    ``places=0`` yields an int; ``places=2`` yields a float. Both are used by
    the promotional subsidy and reconciliation expectations.
    """
    quant = Decimal(1).scaleb(-places)
    rounded = Decimal(str(value)).quantize(quant, rounding=ROUND_HALF_UP)
    return int(rounded) if places == 0 else float(rounded)


def _assert_common_fields(data: dict) -> None:
    """Every entity in this program carries the full common property set."""
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int), "version must be an integer"


def assert_retail_partner(data: dict) -> None:
    _assert_common_fields(data)
    assert data["partner_status"] in ("ACTIVE", "SUSPENDED", "OFFBOARDING")
    assert isinstance(data["partner_portfolio_exposure_cents"], int)
    assert isinstance(data["loyalty_link_enabled"], bool)


def assert_program_agreement(data: dict) -> None:
    _assert_common_fields(data)
    assert data["agreement_status"] in ("DRAFT", "NEGOTIATION", "ACTIVE", "SUSPENDED", "TERMINATED")
    assert 0.0 <= data["revenue_share_rate"] <= 1.0
    assert 0.0 <= data["promo_subsidy_rate"] <= 1.0
    assert data["revenue_share_rate"] + data["promo_subsidy_rate"] <= 1.0


def assert_credit_program(data: dict) -> None:
    _assert_common_fields(data)
    assert data["program_status"] in ("ACTIVE", "RENEWAL_NEGOTIATION", "WINDING_DOWN", "CLOSED")
    assert 1 <= data["cycle_day"] <= 31
    for field in ("outstanding_receivable_cents", "free_look_exposure_cents",
                  "program_profitability_cents"):
        assert isinstance(data[field], int), f"{field} must be integer cents"


def assert_account(data: dict) -> None:
    _assert_common_fields(data)
    assert data["account_status"] in ("ACTIVE", "DELINQUENT", "CHARGED_OFF", "PAID_OFF", "TRANSFERRED")
    assert isinstance(data["credit_limit_cents"], int)
    assert isinstance(data["outstanding_balance_cents"], int)
    assert isinstance(data["linked_loyalty_balance"], int)


def assert_application(data: dict) -> None:
    _assert_common_fields(data)
    assert data["application_status"] in ("PENDING", "APPROVED", "DECLINED")
    assert data["source_channel"] in ("IN_STORE", "DIGITAL", "PRESCREENED")


def assert_transaction(data: dict) -> None:
    _assert_common_fields(data)
    assert data["transaction_status"] in ("POSTED", "DISPUTED")
    assert data["transaction_channel"] in ("IN_STORE", "DIGITAL")
    assert isinstance(data["amount_cents"], int)


def assert_promo_plan(data: dict) -> None:
    _assert_common_fields(data)
    assert data["plan_status"] in ("ACTIVE", "SETTLED", "EXPIRED")
    assert isinstance(data["subsidy_at_risk_cents"], int)
    assert isinstance(data["subsidy_at_application_cents"], int)
    assert data["promo_term_months"] in (6, 12, 18, 24)


def assert_settlement_batch(data: dict) -> None:
    _assert_common_fields(data)
    assert data["batch_status"] in ("OPEN", "SETTLED")
    assert data["settlement_method"] in ("FORWARD_LOOKING", "AS_CHARGED")
    assert data["reconciliation_method"] in ("PROJECTED", "AS_CHARGED")
    assert isinstance(data["variance_cents"], int)


def assert_dispute_case(data: dict) -> None:
    _assert_common_fields(data)
    assert data["case_status"] in ("OPEN", "UNDER_REVIEW", "RESOLVED_FAVOR_CARDHOLDER",
                                   "RESOLVED_FAVOR_MERCHANT", "CLOSED")
    assert isinstance(data["servicing_brand_name"], str)


def assert_benefit_posting(data: dict) -> None:
    _assert_common_fields(data)
    assert data["posting_reason"] in ("PURCHASE_EARN", "PROMO_BONUS", "DISPUTE_CLAWBACK")
    assert data["posted_status"] in ("POSTED", "REVERSED")
    assert isinstance(data["points_amount"], int)


def assert_scheduled_balance(data: dict) -> None:
    _assert_common_fields(data)
    assert data["balance_bucket"] in ("PRINCIPAL", "PROMO_PRINCIPAL")
    assert isinstance(data["principal_balance_cents"], int)


def assert_wind_down_transfer(data: dict) -> None:
    _assert_common_fields(data)
    assert data["transfer_status"] in ("PROPOSED", "AGREEMENT_REACHED", "COMPLETED", "WITHDRAWN")
    assert data["buyer_role"] in ("RETAILER", "ISSUER")
    assert isinstance(data["purchase_price_cents"], int)