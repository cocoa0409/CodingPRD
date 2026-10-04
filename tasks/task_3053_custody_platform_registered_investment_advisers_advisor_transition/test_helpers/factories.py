"""Payload factories — one per entity, input fields only."""

DEFAULTS = {
    "LEGAL_NAME": "Bay Meridian Wealth Advisors",
    "CRD_NUMBER": "CRD-118044",
    "HOME_STATE_CODE": "CA",
    "HOUSEHOLD_NAME": "Alvarez Family",
    "DELIVERING_FIRM_NAME": "Prior Custodian LLC",
    "FEED_HOST": "feeds.baymeridian.example",
    "PAYEE_NAME": "Alvarez Charitable Trust",
    "SECOND_FIRM_LEGAL_NAME": "Legacy Coast Advisors",
    "SECOND_FIRM_CRD_NUMBER": "CRD-204410",
    "SECOND_FIRM_HOME_STATE_CODE": "OR",
    "SECOND_HOUSEHOLD_NAME": "Brennan Family",
}


def create_firm_payload(**overrides) -> dict:
    defaults = {
        "legal_name": DEFAULTS["LEGAL_NAME"],
        "crd_number": DEFAULTS["CRD_NUMBER"],
        "home_state_code": DEFAULTS["HOME_STATE_CODE"],
    }
    defaults.update(overrides)
    return defaults


def create_second_firm_payload(**overrides) -> dict:
    defaults = {
        "legal_name": DEFAULTS["SECOND_FIRM_LEGAL_NAME"],
        "crd_number": DEFAULTS["SECOND_FIRM_CRD_NUMBER"],
        "home_state_code": DEFAULTS["SECOND_FIRM_HOME_STATE_CODE"],
    }
    defaults.update(overrides)
    return defaults


def create_custody_agreement_payload(**overrides) -> dict:
    defaults = {"adviser_crd_number": DEFAULTS["CRD_NUMBER"]}
    defaults.update(overrides)
    return defaults


def create_household_payload(firm_id: str, **overrides) -> dict:
    defaults = {"firm_id": firm_id, "household_name": DEFAULTS["HOUSEHOLD_NAME"]}
    defaults.update(overrides)
    return defaults


def create_account_payload(household_id: str, firm_id: str, **overrides) -> dict:
    defaults = {
        "household_id": household_id,
        "firm_id": firm_id,
        "account_number": "RIA-100001",
        "account_type": "INDIVIDUAL",
        "householding_consent": "OP_IN",
    }
    defaults.update(overrides)
    return defaults


def create_entitlement_payload(firm_id: str, agreement_id: str, **overrides) -> dict:
    defaults = {
        "firm_id": firm_id,
        "entitlement_code": "TRADING_AUTHORIZATION",
        "requested_custody_agreement_id": agreement_id,
    }
    defaults.update(overrides)
    return defaults


def create_asset_transfer_payload(receiving_account_id: str, firm_id: str, **overrides) -> dict:
    defaults = {
        "receiving_account_id": receiving_account_id,
        "firm_id": firm_id,
        "delivering_firm_name": DEFAULTS["DELIVERING_FIRM_NAME"],
        "method": "ACAT",
    }
    defaults.update(overrides)
    return defaults


def create_transfer_lot_payload(**overrides) -> dict:
    defaults = {
        "symbol": "VTI",
        "quantity_micros": 4_000_000_000,
        "sent_cost_basis_cents": 90_000_000,
        "lot_inventory_date": "2019-01-02T00:00:00Z",
        "valuation_price_micros": 250_000_000,
    }
    defaults.update(overrides)
    return defaults


def create_model_payload(firm_id: str, **overrides) -> dict:
    defaults = {"firm_id": firm_id, "model_name": "Core Balanced"}
    defaults.update(overrides)
    return defaults


def create_model_target_payload(**overrides) -> dict:
    defaults = {"symbol": "VTI", "target_weight_bps": 10_000}
    defaults.update(overrides)
    return defaults


def create_block_order_payload(firm_id: str, model_id: str, **overrides) -> dict:
    defaults = {
        "firm_id": firm_id,
        "model_id": model_id,
        "symbol": "VTI",
        "side": "BUY",
        "executed_share_micros": 1_000_000_000,
        "execution_price_micros": 52_375_001,
    }
    defaults.update(overrides)
    return defaults


def create_block_allocation_payload(account_id: str, **overrides) -> dict:
    defaults = {
        "account_id": account_id,
        "requested_share_micros": 1_000_000_000,
        "allocation_rank": 1,
    }
    defaults.update(overrides)
    return defaults


def create_billing_run_payload(firm_id: str, household_id: str, **overrides) -> dict:
    defaults = {
        "firm_id": firm_id,
        "household_id": household_id,
        "period_start_date": "2026-09-01T00:00:00Z",
        "period_end_date": "2026-12-01T00:00:00Z",
        "fee_variant_used": "HOUSEHOLD_AGGREGATED",
        "stated_invoice_cents": 0,
    }
    defaults.update(overrides)
    return defaults


def create_fee_credit_payload(**overrides) -> dict:
    defaults = {"credit_cents": 300_000}
    defaults.update(overrides)
    return defaults


def create_alternative_payload(account_id: str, **overrides) -> dict:
    defaults = {
        "account_id": account_id,
        "asset_name": "Meridian Real Assets Fund II",
        "unit_count": 20,
        "stated_value_cents": 50_000_000,
        "valuation_floor_cents": 30_000_000,
        "valuation_as_of_date": "2026-08-01T00:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def create_standing_instruction_payload(**overrides) -> dict:
    defaults = {
        "instruction_type": "THIRD_PARTY_DISBURSEMENT",
        "payee_name": DEFAULTS["PAYEE_NAME"],
        "periodic_limit_cents": 500_000,
    }
    defaults.update(overrides)
    return defaults


def create_money_movement_payload(account_id: str, instruction_id: str, **overrides) -> dict:
    defaults = {
        "account_id": account_id,
        "standing_instruction_id": instruction_id,
        "amount_cents": 100_000,
        "movement_type": "ACH_DISBURSEMENT",
        "authorization_note": "Client confirmed on 2026-09-01 by signed form",
    }
    defaults.update(overrides)
    return defaults


def create_custody_evidence_payload(**overrides) -> dict:
    defaults = {"requirement_code": "SURPRISE_EXAMINATION", "critical": True}
    defaults.update(overrides)
    return defaults


def create_data_feed_payload(firm_id: str, **overrides) -> dict:
    defaults = {
        "firm_id": firm_id,
        "feed_type": "POSITIONS",
        "delivery_endpoint_host": DEFAULTS["FEED_HOST"],
    }
    defaults.update(overrides)
    return defaults


def create_onboarding_batch_payload(firm_id: str, **overrides) -> dict:
    defaults = {"firm_id": firm_id, "batch_kind": "ACCOUNTS", "items": []}
    defaults.update(overrides)
    return defaults


def create_examination_bundle_payload(**overrides) -> dict:
    defaults = {"period_start_date": "2026-09-01T00:00:00Z", "period_end_date": "2026-12-01T00:00:00Z"}
    defaults.update(overrides)
    return defaults


def create_system_config_payload(**overrides) -> dict:
    defaults = {"database_invariant_enforcement": "WARN"}
    defaults.update(overrides)
    return defaults


def create_admin_action_payload(firm_id: str, **overrides) -> dict:
    defaults = {
        "firm_id": firm_id,
        "admin_action_kind": "REGULATORY_FREEZE",
        "admin_action_detail": "Emergency suspension pending examination",
    }
    defaults.update(overrides)
    return defaults