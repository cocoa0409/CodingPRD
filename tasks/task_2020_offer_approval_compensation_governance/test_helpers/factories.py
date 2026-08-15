"""Payload factories — one per entity, input fields only."""
import uuid


def _uniq_email(prefix="cand"):
    return f"{prefix}.{uuid.uuid4().hex[:10]}@x.com"


DEFAULTS = {
    "REQ_TITLE": "Sr Eng",
    "REQ_DEPARTMENT": "ENG",
    "ROLE_LEVEL": "L5",
    "GEO_TIER": "T1",
    "ANNUAL_BUDGET_CENTS": 50000000,
    "SALARY_MIN_CENTS": 15000000,
    "SALARY_MID_CENTS": 18000000,
    "SALARY_MAX_CENTS": 21000000,
    "HEADCOUNT_AUTHORIZED": 1,
    "OFFER_BASE_CENTS": 18000000,
    "SNAPSHOT_BASE_CENTS": 19000000,
}


def create_requisition_payload(**overrides) -> dict:
    defaults = {
        "title": DEFAULTS["REQ_TITLE"],
        "department": DEFAULTS["REQ_DEPARTMENT"],
        "role_level": DEFAULTS["ROLE_LEVEL"],
        "geo_tier": DEFAULTS["GEO_TIER"],
        "annual_budget_cents": DEFAULTS["ANNUAL_BUDGET_CENTS"],
        "salary_min_cents": DEFAULTS["SALARY_MIN_CENTS"],
        "salary_mid_cents": DEFAULTS["SALARY_MID_CENTS"],
        "salary_max_cents": DEFAULTS["SALARY_MAX_CENTS"],
        "headcount_authorized": DEFAULTS["HEADCOUNT_AUTHORIZED"],
    }
    defaults.update(overrides)
    return defaults


def create_candidate_payload(**overrides) -> dict:
    defaults = {
        "full_name": "Candidate One",
        "email": _uniq_email(),
    }
    defaults.update(overrides)
    return defaults


def create_equity_snapshot_payload(**overrides) -> dict:
    defaults = {
        "role_level": DEFAULTS["ROLE_LEVEL"],
        "geo_tier": DEFAULTS["GEO_TIER"],
        "base_cents": DEFAULTS["SNAPSHOT_BASE_CENTS"],
    }
    defaults.update(overrides)
    return defaults


def create_approval_policy_payload(**overrides) -> dict:
    defaults = {
        "min_band_severity": "ABOVE_BAND",
        "required_role": "CompAnalyst",
        "chain_position": 1,
    }
    defaults.update(overrides)
    return defaults


def create_offer_payload(**overrides) -> dict:
    defaults = {
        "base_cents": DEFAULTS["OFFER_BASE_CENTS"],
        "bonus_target_pct": 0,
        "equity_shares": 0,
        "equity_fmv_cents": 0,
    }
    defaults.update(overrides)
    return defaults


def create_perk_payload(**overrides) -> dict:
    defaults = {
        "kind": "SIGN_ON",
        "amount_cents": 1000000,
        "clawback_months": 12,
        "clawback_variant": "FULL_CLIFF",
    }
    defaults.update(overrides)
    return defaults


def create_clearance_check_payload(**overrides) -> dict:
    defaults = {"kind": "BACKGROUND"}
    defaults.update(overrides)
    return defaults


def create_delegation_grant_payload(**overrides) -> dict:
    defaults = {
        "grantor_user_id": "vp-1",
        "delegate_user_id": "delegate-1",
        "scope_role": "VPPeople",
        "valid_from": "2026-08-01T00:00:00Z",
        "valid_until": "2026-09-01T00:00:00Z",
    }
    defaults.update(overrides)
    return defaults
