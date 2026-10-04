"""Payload factories — one per entity, input fields only."""

MODEL_CODE_DEFAULT = "ADU-TEST-1"

# Bureau-only scoring variable: score = round_half_up(600 * (bureau - 300) / 550),
# so the default applicant (bureau 575) scores exactly 300. The PRD 3.4
# floor-reject branch fires only when the clamped score satisfies
# score_floor <= score < 300, and clamping never lets a stored score fall
# below score_floor, so a score of exactly 300 with score_floor 0 reaches
# VERIFICATION_PENDING while still exercising the same weighted-sum formula.
BUREAU_ONLY_VARIABLES = [{"name": "bureau_score", "weight": 6, "min": 300, "max": 850}]

STANDARD_EFFECTIVE_FROM = "2026-01-01T00:00:00Z"
STANDARD_EFFECTIVE_TO = "2027-12-31T00:00:00Z"


def create_model_version_payload(**overrides) -> dict:
    # The default model scores the default applicant (bureau 575) at exactly
    # 300 under the weight-6 bureau-only variable. score_floor 0 /
    # score_ceiling 1000 clamp nothing, and 300 sits outside the PRD 3.4
    # floor-reject band (score_floor <= clamped score < 300), so the default
    # fixture path reaches VERIFICATION_PENDING.
    defaults = {
        "model_code": MODEL_CODE_DEFAULT,
        "variables": [dict(v) for v in BUREAU_ONLY_VARIABLES],
        "calibration_note": "baseline",
        "score_floor": 0,
        "score_ceiling": 1000,
    }
    defaults.update(overrides)
    return defaults


def create_partner_payload(**overrides) -> dict:
    defaults = {
        "legal_name": "Test Bank",
        "partner_type": "BANK",
        "home_state": "TX",
    }
    defaults.update(overrides)
    return defaults


def create_credit_box_payload(**overrides) -> dict:
    defaults = {
        "min_score": 0,
        "max_score": 1000,
        "allowed_states": ["TX"],
        "min_loan_cents": 100000,
        "max_loan_cents": 10000000,
        "monthly_volume_cap_count": 10,
        "annual_percentage_rate": 12.0,
        "effective_from": STANDARD_EFFECTIVE_FROM,
        "effective_to": STANDARD_EFFECTIVE_TO,
    }
    defaults.update(overrides)
    return defaults


def create_applicant_payload(**overrides) -> dict:
    """A clean applicant: passes both instant checks, scores 300 under the
    default bureau-only model (round_half_up(600 * (575 - 300) / 550) == 300),
    DTI 20.0, standard approved amount 5000000. A stored score of 300 sits
    outside the PRD 3.4 floor-reject band, so this applicant reaches
    VERIFICATION_PENDING."""
    defaults = {
        "full_name": "Test Applicant",
        "state_code": "TX",
        "annual_income_cents": 12000000,
        "monthly_debt_payments_cents": 200000,
        "education_level": "BACHELOR",
        "employment_status": "EMPLOYED",
        "months_employed": 12,
        "bank_account_avg_balance_cents": 500000,
        "bank_account_nsf_count_90d": 0,
        "monthly_net_cashflow_cents": 100000,
        "bureau_score": 575,
    }
    defaults.update(overrides)
    return defaults


def create_application_payload(applicant_id, **overrides) -> dict:
    defaults = {
        "applicant_id": applicant_id,
        "channel": "DIRECT",
        "requested_amount_cents": 5000000,
    }
    defaults.update(overrides)
    return defaults


def create_fairness_review_payload(model_version_id, **overrides) -> dict:
    defaults = {
        "model_version_id": model_version_id,
        "review_type": "DISPARATE_IMPACT",
        "details": "baseline",
    }
    defaults.update(overrides)
    return defaults


def create_attestation_payload(partner_id, **overrides) -> dict:
    defaults = {
        "partner_id": partner_id,
        "period_label": "2026-09",
    }
    defaults.update(overrides)
    return defaults


def create_securitization_pool_payload(trust_partner_id, **overrides) -> dict:
    defaults = {
        "trust_partner_id": trust_partner_id,
        "pool_label": "TR-POOL",
        "target_principal_cents": 100000000,
        "max_single_loan_cents": 10000000,
    }
    defaults.update(overrides)
    return defaults
