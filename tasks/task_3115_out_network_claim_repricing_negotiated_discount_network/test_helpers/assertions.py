"""Entity assertions and domain invariant checkers."""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def _assert_common(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, (
        "version must be a positive integer"
    )


def assert_payer_client(data: dict):
    _assert_common(data)
    assert isinstance(data["payer_name"], str) and data["payer_name"]
    assert data["status"] in ("ACTIVE", "SUSPENDED")
    assert isinstance(data["fee_percent"], (int, float))
    assert isinstance(data["fee_cap_cents_per_claim"], int)
    assert isinstance(data["minimum_invoice_cents"], int)
    assert isinstance(data["transparency_reporting_enabled"], bool)


def assert_repricing_policy(data: dict):
    _assert_common(data)
    assert data["claim_type"] in ("PROFESSIONAL", "FACILITY", "ANCILLARY", "EMERGENCY")
    assert data["network_status"] in ("IN_NETWORK", "OUT_OF_NETWORK", "EMERGENCY_OON")
    assert data["methodology"] in (
        "CONTRACTED_NETWORK", "REFERENCE_BASED", "PERCENT_OF_MEDICARE", "UCR",
        "NEGOTIATION_REQUIRED",
    )
    assert isinstance(data["priority"], int)
    assert data["status"] in ("ACTIVE", "RETIRED")


def assert_provider(data: dict):
    _assert_common(data)
    assert isinstance(data["npi"], str) and data["npi"]
    assert isinstance(data["legal_name"], str) and data["legal_name"]
    assert isinstance(data["tin"], str) and data["tin"]


def assert_network_agreement(data: dict):
    _assert_common(data)
    assert isinstance(data["network_name"], str)
    assert is_valid_uuid(data.get("provider_id", ""))
    assert isinstance(data["discount_percent"], (int, float))
    assert data["status"] in ("ACTIVE", "SUSPENDED", "TERMINATED")
    assert data.get("balance_billing_prohibited") is True


def assert_medicare_entry(data: dict):
    """Rate-table row: carries id + created_at only — no updated_at, no version."""
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert "updated_at" not in data, "rate rows must not carry updated_at"
    assert "version" not in data, "rate rows must not carry version"
    assert isinstance(data["procedure_code"], str)
    assert isinstance(data["region_code"], str)
    assert isinstance(data["base_rate_cents"], int)
    assert isinstance(data["geographic_adjustment_factor"], (int, float))
    assert isinstance(data["effective_year"], int)


def assert_ucr_rate(data: dict):
    """UCR row: carries id + created_at only — no updated_at, no version."""
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert "updated_at" not in data, "rate rows must not carry updated_at"
    assert "version" not in data, "rate rows must not carry version"
    assert isinstance(data["procedure_code"], str)
    assert isinstance(data["region_code"], str)
    assert isinstance(data["percentile_50_cents"], int)
    assert isinstance(data["percentile_80_cents"], int)


def assert_claim(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("payer_client_id", ""))
    assert is_valid_uuid(data.get("provider_id", ""))
    assert isinstance(data["external_claim_ref"], str)
    assert data["claim_type"] in ("PROFESSIONAL", "FACILITY", "ANCILLARY", "EMERGENCY")
    assert data["network_status"] in ("IN_NETWORK", "OUT_OF_NETWORK", "EMERGENCY_OON")
    assert isinstance(data["billed_amount_cents"], int)
    assert isinstance(data["patient_responsibility_cents"], int)
    assert isinstance(data["nsa_flag"], bool)
    assert data["status"] in (
        "RECEIVED", "PENDING_LINES", "PRICED", "SETTLED", "FINALIZED",
    )


def assert_claim_line(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("claim_id", ""))
    assert isinstance(data["procedure_code"], str)
    assert isinstance(data["quantity_units"], int) and data["quantity_units"] >= 1
    assert isinstance(data["unit_charge_cents"], int) and data["unit_charge_cents"] > 0
    assert isinstance(data["region_code"], str)
    assert data["status"] in ("PENDING", "PRICED", "VOID")


def assert_determination(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("claim_id", ""))
    assert data["methodology"] in (
        "CONTRACTED_NETWORK", "REFERENCE_BASED", "PERCENT_OF_MEDICARE", "UCR",
        "NEGOTIATED",
    )
    assert data["status"] in ("ACTIVE", "SUPERSEDED")


def assert_negotiation_case(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("claim_id", ""))
    assert data["opened_by_role"] in ("PayerRep", "ProviderRep")
    assert isinstance(data["round_count"], int) and data["round_count"] >= 0
    assert data["status"] in (
        "OPEN", "OFFER_PENDING", "COUNTERED", "ACCEPTED", "SETTLED", "WITHDRAWN",
        "EXPIRED",
    )


def assert_settlement_agreement(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("negotiation_case_id", ""))
    assert is_valid_uuid(data.get("claim_id", ""))
    assert isinstance(data["settled_amount_cents"], int)
    assert data["status"] in ("PENDING_SIGNATURES", "EXECUTED", "VOIDED")


def assert_open_negotiation(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("claim_id", ""))
    assert data["initiated_by"] in ("PAYER", "PROVIDER")
    assert is_iso8601_timestamp(data.get("initiated_at", ""))
    assert is_iso8601_timestamp(data.get("expires_at", ""))
    assert data["status"] in ("ACTIVE", "AGREED", "EXPIRED", "SUPERSEDED_BY_IDR")


def assert_idr_submission(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("claim_id", ""))
    assert is_valid_uuid(data.get("open_negotiation_id", ""))
    assert isinstance(data["payer_offer_cents"], int)
    assert isinstance(data["provider_offer_cents"], int)
    assert isinstance(data["qpa_cents"], int)
    assert data["status"] in (
        "SUBMITTED", "DECIDED_PAYER", "DECIDED_PROVIDER", "DISMISSED",
    )


def assert_appeal(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("claim_id", ""))
    assert is_valid_uuid(data.get("determination_id", ""))
    assert isinstance(data["appeal_reason"], str)
    assert data["status"] in (
        "SUBMITTED", "UNDER_REVIEW", "RE_REVIEWED_UPHELD", "RE_REVIEWED_ADJUSTED",
        "DENIED",
    )


def assert_feed_batch(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("payer_client_id", ""))
    assert data["feed_type"] in ("CLAIM_INTAKE", "REMITTANCE", "ELIGIBILITY")
    assert isinstance(data["record_count"], int)
    assert is_iso8601_timestamp(data.get("received_at", ""))
    assert is_iso8601_timestamp(data.get("sla_due_at", ""))
    assert data["status"] in ("RECEIVED", "PROCESSED", "FAILED")


def assert_fee_invoice(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("payer_client_id", ""))
    assert isinstance(data["claim_ids"], list)
    assert data["status"] in ("DRAFT", "ISSUED", "VOIDED")


def assert_transparency_report(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("fee_invoice_id", ""))
    assert isinstance(data["total_billed_cents"], int)
    assert isinstance(data["total_allowed_cents"], int)
    assert isinstance(data["total_savings_cents"], int)
    assert isinstance(data["total_fee_cents"], int)
    assert data["status"] == "PUBLISHED"


def assert_priced_claim_invariants(claim: dict):
    """Derived-amount identity that must hold once a claim is priced."""
    assert claim["allowed_amount_cents"] is not None
    assert claim["payer_liability_cents"] == (
        claim["allowed_amount_cents"] - claim["patient_responsibility_cents"]
    ), "payer_liability = allowed - patient_responsibility"
    assert claim["savings_cents"] == (
        claim["billed_amount_cents"]
        - claim["allowed_amount_cents"]
        + claim["patient_responsibility_cents"]
    ), "savings = billed - allowed + patient_responsibility"
