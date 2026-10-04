"""Payload factories — one per entity, client-supplied fields only."""

from .constants import TEST_DEFAULTS


def methodology_payload(**overrides) -> dict:
    payload = {
        "name": "Corporate Finance Senior Unsecured",
        "version_code": "2026.1",
        "methodology_code": "CF-SENIOR-2026.1",
        "sector": "CORPORATE_FINANCE",
    }
    payload.update(overrides)
    return payload


def rated_entity_payload(methodology_id: str, **overrides) -> dict:
    payload = {
        "legal_name": "Acme Industrials PLC",
        "sector": "CORPORATE_FINANCE",
        "domicile_country": "GB",
        "revenue_band": "LARGE",
        "methodology_id": methodology_id,
    }
    payload.update(overrides)
    return payload


def engagement_letter_payload(rated_entity_id: str, **overrides) -> dict:
    payload = {
        "rated_entity_id": rated_entity_id,
        "fee_amount_cents": TEST_DEFAULTS["FEE_AMOUNT_CENTS"],
        "fee_structure": "FLAT_ANNUAL",
        "fee_payer_is_issuer": True,
        "signed_at": "2026-09-01T00:00:00Z",
    }
    payload.update(overrides)
    return payload


def rating_request_payload(engagement_letter_id: str, rated_entity_id: str, **overrides) -> dict:
    payload = {
        "engagement_letter_id": engagement_letter_id,
        "rated_entity_id": rated_entity_id,
        "instrument_type": "SENIOR_UNSECURED",
        "instrument_notional_cents": TEST_DEFAULTS["INSTRUMENT_NOTIONAL_CENTS"],
        "requested_rating_scale": "GLOBAL_LONG_TERM",
    }
    payload.update(overrides)
    return payload


def analyst_payload(**overrides) -> dict:
    payload = {
        "full_name": "Priya Raman",
        "primary_sector": "CORPORATE_FINANCE",
        "analyst_tier": "LEAD",
        "independence_declared_at": "2026-09-01T00:00:00Z",
    }
    payload.update(overrides)
    return payload


def team_assignment_payload(rating_request_id: str, lead_analyst_id: str,
                            support_analyst_id: str, **overrides) -> dict:
    payload = {
        "rating_request_id": rating_request_id,
        "lead_analyst_id": lead_analyst_id,
        "support_analyst_id": support_analyst_id,
        "window_start": TEST_DEFAULTS["WINDOW_START"],
        "window_end": TEST_DEFAULTS["WINDOW_END"],
    }
    payload.update(overrides)
    return payload


def conflict_screening_payload(team_assignment_id: str, analyst_id: str, **overrides) -> dict:
    payload = {
        "team_assignment_id": team_assignment_id,
        "analyst_id": analyst_id,
        "conflict_type": "NONE",
        "screening_result": "CLEAR",
    }
    payload.update(overrides)
    return payload


def committee_payload(rating_request_id: str, **overrides) -> dict:
    payload = {
        "rating_request_id": rating_request_id,
        "committee_date": "2026-12-15T00:00:00Z",
        "required_voting_members": 2,
    }
    payload.update(overrides)
    return payload


def vote_payload(analyst_id: str, **overrides) -> dict:
    payload = {
        "analyst_id": analyst_id,
        "vote_value": "AFFIRM",
        "assigned_grade": "BAA",
    }
    payload.update(overrides)
    return payload


RATIONALE_200 = (
    "The issuer is assigned this grade on the strength of a diversified operating "
    "base, resilient cash generation and leverage comfortably inside the sector "
    "band; the outlook reflects the committee's forward view and no watch "
    "designation is applied at this session."
)


def decide_payload(**overrides) -> dict:
    payload = {
        "assigned_grade": "BAA",
        "outlook": "STABLE",
        "watch_status": "NO_WATCH",
        "rationale": RATIONALE_200,
    }
    payload.update(overrides)
    return payload


def appeal_payload(**overrides) -> dict:
    payload = {
        "filer_user_id": "issuer-cfo-1",
        "new_information_summary": (
            "The issuer files a signed binding divestiture agreement raising "
            "material proceeds that were absent from the pack, which it asserts "
            "changes the leverage trajectory over the medium term."
        ),
    }
    payload.update(overrides)
    return payload


def surveillance_review_payload(rated_entity_id: str, **overrides) -> dict:
    payload = {
        "rated_entity_id": rated_entity_id,
        "review_type": "PERIODIC",
        "review_due_at": "2027-01-05T00:00:00Z",
    }
    payload.update(overrides)
    return payload


def review_slot_payload(analyst_id: str, surveillance_review_id: str, **overrides) -> dict:
    payload = {
        "analyst_id": analyst_id,
        "surveillance_review_id": surveillance_review_id,
        "slot_start": "2026-12-01T09:00:00Z",
        "slot_end": "2026-12-01T11:00:00Z",
    }
    payload.update(overrides)
    return payload


def compensation_payload(analyst_id: str, **overrides) -> dict:
    payload = {
        "analyst_id": analyst_id,
        "base_salary_cents": TEST_DEFAULTS["BASE_SALARY_CENTS"],
        "rating_accuracy_score": TEST_DEFAULTS["RATING_ACCURACY_SCORE"],
        "comp_period": TEST_DEFAULTS["COMP_PERIOD"],
    }
    payload.update(overrides)
    return payload


def appearance_reconciliation_payload(analyst_id: str, rating_decision_id: str, **overrides) -> dict:
    payload = {
        "analyst_id": analyst_id,
        "rating_decision_id": rating_decision_id,
        "stated_role": "LEAD_ANALYST",
        "evidence_reference": TEST_DEFAULTS["EVIDENCE_REFERENCE"],
    }
    payload.update(overrides)
    return payload