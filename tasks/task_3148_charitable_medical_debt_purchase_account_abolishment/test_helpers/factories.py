"""Payload factories — one per entity, input fields only."""

DEFAULTS = {
    "ORG_NAME": "Mercy General Hospital",
    "ORG_TYPE": "HOSPITAL",
    "ORG_STATE": "TX",
    "ORG_EMAIL": "billing@org.example",
    "POLICY_NAME": "TX Standard 400%",
    "POLICY_STATE": "TX",
    "FPL_MULTIPLIER": 4.0,
    "EFFECTIVE_FROM": "2026-01-01",
    "EFFECTIVE_TO": "2027-01-01",
    "PORTFOLIO_LABEL": "Mercy Q3 bundle",
    "FACE_VALUE_CENTS": 2200000,
    "ASKING_PRICE_CENTS": 50000,
    "CAMPAIGN_NAME": "General Relief Fund",
    "GOAL_CENTS": 1000000,
    "DONOR_NAME": "Dee Donor",
    "DONOR_EMAIL": "dee@x.com",
    "FAP_BASELINE": 10,
    "FAP_TARGET": 90,
}


def create_source_organization_payload(**overrides) -> dict:
    defaults = {
        "name": DEFAULTS["ORG_NAME"],
        "org_type": DEFAULTS["ORG_TYPE"],
        "state_code": DEFAULTS["ORG_STATE"],
        "contact_email": DEFAULTS["ORG_EMAIL"],
    }
    defaults.update(overrides)
    return defaults


def create_eligibility_policy_payload(**overrides) -> dict:
    defaults = {
        "name": DEFAULTS["POLICY_NAME"],
        "state_code": DEFAULTS["POLICY_STATE"],
        "fpl_multiplier": DEFAULTS["FPL_MULTIPLIER"],
        "insolvency_qualifies": True,
        "effective_from": DEFAULTS["EFFECTIVE_FROM"],
        "effective_to": DEFAULTS["EFFECTIVE_TO"],
    }
    defaults.update(overrides)
    return defaults


def create_portfolio_payload(source_org_id, **overrides) -> dict:
    defaults = {
        "source_org_id": source_org_id,
        "label": DEFAULTS["PORTFOLIO_LABEL"],
        "face_value_cents": DEFAULTS["FACE_VALUE_CENTS"],
        "asking_price_cents": DEFAULTS["ASKING_PRICE_CENTS"],
    }
    defaults.update(overrides)
    return defaults


def create_account_payload(external_ref, **overrides) -> dict:
    """One item of the bulk-import accounts array."""
    defaults = {
        "external_ref": external_ref,
        "debtor_household_key": f"H-{external_ref}",
        "debtor_zip": "75001",
        "debtor_state": "TX",
        "household_size": 1,
        "annual_income_cents": 1000000,
        "is_insolvent": False,
        "balance_cents": 100000,
        "accrued_adjustment_cents": 0,
        "reported_to_bureau": False,
        "bureau_name": None,
        "mailing_address": "1 Main St",
    }
    defaults.update(overrides)
    return defaults


def create_contract_payload(expected_portfolio_version, **overrides) -> dict:
    defaults = {
        "collection_prohibition": True,
        "no_resale": True,
        "expected_portfolio_version": expected_portfolio_version,
    }
    defaults.update(overrides)
    return defaults


def create_donor_campaign_payload(**overrides) -> dict:
    defaults = {
        "name": DEFAULTS["CAMPAIGN_NAME"],
        "earmark_type": "GENERAL",
        "goal_cents": DEFAULTS["GOAL_CENTS"],
    }
    defaults.update(overrides)
    return defaults


def create_donation_payload(**overrides) -> dict:
    defaults = {
        "donor_name": DEFAULTS["DONOR_NAME"],
        "donor_email": DEFAULTS["DONOR_EMAIL"],
        "gross_cents": 100000,
    }
    defaults.update(overrides)
    return defaults


def create_abolishment_batch_payload(account_ids, expected_portfolio_version) -> dict:
    return {
        "account_ids": list(account_ids),
        "expected_portfolio_version": expected_portfolio_version,
    }


def create_hospital_partnership_payload(source_org_id, **overrides) -> dict:
    defaults = {
        "source_org_id": source_org_id,
        "fap_baseline_score": DEFAULTS["FAP_BASELINE"],
        "fap_target_score": DEFAULTS["FAP_TARGET"],
    }
    defaults.update(overrides)
    return defaults


def create_partnership_milestone_payload(code, **overrides) -> dict:
    defaults = {
        "code": code,
        "description": f"Milestone {code}",
        "weight": 10,
        "due_date": "2026-12-31",
    }
    defaults.update(overrides)
    return defaults


def create_impact_report_payload(**overrides) -> dict:
    defaults = {
        "scope": "GLOBAL",
        "period_start": "2026-09-01",
        "period_end": "2026-09-30",
        "counting_variant": "PER_ACCOUNT",
    }
    defaults.update(overrides)
    return defaults
