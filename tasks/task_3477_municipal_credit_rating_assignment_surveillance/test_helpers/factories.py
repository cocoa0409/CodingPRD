"""Payload factories — one per creatable resource, input fields only.

Only client-supplied fields are ever put on the wire; computed and system
fields (fees, weighted scores, statuses, timestamps, versions) are for the
server to derive.

Default choices mirror the PRD's own worked examples: the GO weight profile
(0.20/0.20/0.20/0.15/0.10/0.15) sums to exactly 1.000 as PRD section 3.6
requires, and the standard score set (4,4,3,4,4,2) lands exactly on the
3.5000 anchor threshold for an `A` indicative notch under those weights —
the boundary the PRD's anchor table makes inclusive (PRD section 3.2).

Every factory takes ``**overrides`` so a test controls exactly the fields it
cares about and nothing else.
"""

from . import constants as C

# ─── Issuers and underwriters ───────────────────────────────────────────────


def issuer_payload(**overrides):
    payload = {
        "legal_name": "City of Example",
        "state_code": "CA",
        "issuer_type": C.ISSUER_TYPE_GENERAL_GOVERNMENT,
        "fiscal_year_end": "06-30",
        "population": 500000,
    }
    payload.update(overrides)
    return payload


def underwriter_payload(**overrides):
    payload = {
        "firm_name": "Meridian Capital Markets",
        "license_number": "MW-4481",
    }
    payload.update(overrides)
    return payload


# ─── Engagements ────────────────────────────────────────────────────────────


def engagement_payload(issuer_id, **overrides):
    """SOLICITED GO engagement on US-CA by default; pass
    ``solicitation=UNSOLICITED`` (and a LeadAnalyst caller) for the
    agency-initiated path, or ``underwriter_id=...`` for an
    underwriter-originated request."""
    payload = {
        "issuer_id": issuer_id,
        "solicitation": C.SOLICITATION_SOLICITED,
        "credit_type": C.CREDIT_TYPE_GENERAL_OBLIGATION,
        "jurisdiction_code": "US-CA",
    }
    payload.update(overrides)
    return payload


def accept_terms_payload(fee_cents=C.FEE_GO_CENTS, **overrides):
    """Cash covering the full fee with no credit applied, by default."""
    payload = {
        "fee_payment_cents": fee_cents,
        "apply_credit_cents": 0,
    }
    payload.update(overrides)
    return payload


def document_payload(document_code=C.DOC_AUDIT_FY, **overrides):
    payload = {"document_code": document_code}
    payload.update(overrides)
    return payload


# ─── Criteria versions ──────────────────────────────────────────────────────

#: The GO profile whose six weights sum to exactly 1.000 (PRD section 3.6).
DEFAULT_WEIGHTS = {
    "w_economy": 0.20,
    "w_management": 0.20,
    "w_budgetary_performance": 0.20,
    "w_flexibility": 0.15,
    "w_liquidity": 0.10,
    "w_debt_profile": 0.15,
}


def criteria_version_payload(**overrides):
    payload = {
        "jurisdiction_code": "US-CA",
        "credit_type": C.CREDIT_TYPE_GENERAL_OBLIGATION,
        "version_label": "GO-2026.1",
    }
    payload.update(DEFAULT_WEIGHTS)
    payload.update(overrides)
    return payload


# ─── Scorecards ─────────────────────────────────────────────────────────────

#: Scores (4,4,3,4,4,2): weighted exactly 3.5000 under DEFAULT_WEIGHTS, the
#: inclusive `A` anchor boundary (PRD section 3.2).
DEFAULT_SCORES = {
    "score_economy": 4,
    "score_management": 4,
    "score_budgetary_performance": 3,
    "score_flexibility": 4,
    "score_liquidity": 4,
    "score_debt_profile": 2,
}

#: All-fives: weighted 5.0000 -> AAA under any valid weight profile.
PERFECT_SCORES = {
    "score_economy": 5,
    "score_management": 5,
    "score_budgetary_performance": 5,
    "score_flexibility": 5,
    "score_liquidity": 5,
    "score_debt_profile": 5,
}

#: Five 5s with a single 1: the weak-link cap probe for ENTERPRISE credits
#: (PRD section 3.2).
WEAK_LINK_SCORES = {
    "score_economy": 5,
    "score_management": 5,
    "score_budgetary_performance": 5,
    "score_flexibility": 5,
    "score_liquidity": 5,
    "score_debt_profile": 1,
}

#: (3,3,3,3,3,2): weighted 2.8500 -> BB under DEFAULT_WEIGHTS.
BB_SCORES = {
    "score_economy": 3,
    "score_management": 3,
    "score_budgetary_performance": 3,
    "score_flexibility": 3,
    "score_liquidity": 3,
    "score_debt_profile": 2,
}


def scorecard_payload(expected_engagement_version, **overrides):
    """The six factor scores plus the OCC anchor (PRD section 2.6)."""
    payload = dict(DEFAULT_SCORES)
    payload["expected_engagement_version"] = expected_engagement_version
    payload.update(overrides)
    return payload


# ─── Committee sessions and votes ───────────────────────────────────────────

#: The canonical five-member committee pool (PRD section 3.3).
DEFAULT_VOTER_POOL = ["voter-1", "voter-2", "voter-3", "voter-4", "voter-5"]

#: Default session window: the morning after the clock start, comfortably
#: after any engagement setup done at the 2026-09-01 starting instant.
DEFAULT_SESSION_START = "2026-09-02T10:00:00Z"
DEFAULT_SESSION_END = "2026-09-02T12:00:00Z"
#: A point strictly inside the default window, used to open the session.
DEFAULT_SESSION_OPEN_AT = "2026-09-02T10:30:00Z"


def session_payload(**overrides):
    payload = {
        "start_at": DEFAULT_SESSION_START,
        "end_at": DEFAULT_SESSION_END,
        "voter_ids": list(DEFAULT_VOTER_POOL),
    }
    payload.update(overrides)
    return payload


def vote_payload(voter_id, notch_vote=None, recusal_reason=None, **overrides):
    """Exactly one of notch_vote / recusal_reason must be given (PRD 3.3)."""
    payload = {"voter_id": voter_id}
    if notch_vote is not None:
        payload["notch_vote"] = notch_vote
    if recusal_reason is not None:
        payload["recusal_reason"] = recusal_reason
    payload.update(overrides)
    return payload


def alternate_payload(recused_voter_id, alternate_voter_id, **overrides):
    payload = {
        "recused_voter_id": recused_voter_id,
        "alternate_voter_id": alternate_voter_id,
    }
    payload.update(overrides)
    return payload


# ─── Ratings: publish, actions, reinstate ───────────────────────────────────


def publish_payload(**overrides):
    payload = {
        "outlook": C.OUTLOOK_STABLE,
        "rationale": "Stable credit profile",
    }
    payload.update(overrides)
    return payload


def rating_action_payload(action, expected_rating_version, **overrides):
    """AFFIRM / UPGRADE / DOWNGRADE / WITHDRAW with the OCC anchor; supply
    new_notch, new_outlook or withdraw_reason via overrides as the action
    requires (PRD section 3.5)."""
    payload = {
        "action": action,
        "rationale": "surveillance review",
        "expected_rating_version": expected_rating_version,
    }
    payload.update(overrides)
    return payload


# ─── Appeals ────────────────────────────────────────────────────────────────


def appeal_payload(new_information_codes=None, **overrides):
    if new_information_codes is None:
        new_information_codes = [C.DOC_PENSION_VALUATION]
    payload = {"new_information_codes": list(new_information_codes)}
    payload.update(overrides)
    return payload


def appeal_decision_payload(decision=C.DECISION_UPHELD, **overrides):
    payload = {
        "decision": decision,
        "rationale": "committee review of the appeal record",
    }
    payload.update(overrides)
    return payload


# ─── Bond sales ─────────────────────────────────────────────────────────────


def bond_sale_payload(issuer_id, rating_id, **overrides):
    payload = {
        "issuer_id": issuer_id,
        "rating_id": rating_id,
        "par_amount_cents": 100000000,
        "maturity_years": 5,
        "sale_date": "2026-09-15T00:00:00Z",
        "pricing_mode": C.PRICING_MODE_FINAL,
    }
    payload.update(overrides)
    return payload


# ─── Review items ───────────────────────────────────────────────────────────


def review_complete_payload(outcome=C.REVIEW_OUTCOME_NO_ACTION, **overrides):
    payload = {
        "outcome": outcome,
        "rationale": "criteria review completed",
    }
    payload.update(overrides)
    return payload
