"""Payload factories — one per entity, input fields only (PRD §3)."""
from typing import Any, Dict, Iterable, List, Optional

from .constants import BASE_FEE_CENTS

_seq = {"n": 0}


def _next() -> int:
    _seq["n"] += 1
    return _seq["n"]


def create_party_payload(**overrides) -> dict:
    n = _next()
    defaults: Dict[str, Any] = {
        "name": f"Party {n} LLC",
        "party_type": "PETITIONER",
    }
    defaults.update(overrides)
    return defaults


def create_patent_payload(**overrides) -> dict:
    n = _next()
    defaults: Dict[str, Any] = {
        "patent_number": f"US9{n:07d}",
        "title": f"Test Patent {n}",
        "issue_date": "2020-01-01T00:00:00Z",
        "owner_id": None,  # must be overridden
        "total_claims": 2,
    }
    defaults.update(overrides)
    return defaults


def create_litigation_matter_payload(**overrides) -> dict:
    n = _next()
    defaults: Dict[str, Any] = {
        "defendant_party_id": None,  # must be overridden
        "court_name": "W.D. Tex.",
        "docket_number": f"6:26-cv-{n:05d}",
        "complaint_served_date": "2026-01-01T00:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def default_grounds(challenged_claims: Iterable[int],
                    basis: str = "ANTICIPATION_102") -> List[dict]:
    return [{"claim_number": c, "basis": basis} for c in challenged_claims]


def default_prior_art(reference_type: str = "PATENT",
                      citation: str = "US5555555") -> List[dict]:
    return [{"reference_type": reference_type, "citation": citation}]


def create_petition_payload(**overrides) -> dict:
    challenged = overrides.get("challenged_claims", [1])
    defaults: Dict[str, Any] = {
        "patent_id": None,       # must be overridden
        "petitioner_id": None,   # must be overridden
        "review_type": "IPR",
        "challenged_claims": list(challenged),
        "grounds": default_grounds(challenged),
        "prior_art": default_prior_art(),
        "real_party_in_interest": "Real Party LLC",
        "fee_paid_cents": BASE_FEE_CENTS,
        "expected_patent_version": None,  # must be overridden
    }
    defaults.update(overrides)
    return defaults


def per_ground_scores(*claim_scores, basis: str = "ANTICIPATION_102") -> List[dict]:
    """Build the decide-institution score payload.

    Each entry is (claim_number, score) or (claim_number, score, basis).
    """
    entries: List[dict] = []
    for item in claim_scores:
        if len(item) == 3:
            c, s, b = item
        else:
            c, s = item
            b = basis
        entries.append({"claim_number": c, "basis": b, "score": s})
    return entries


def create_decision_payload(per_ground_scores, lead_judge_user_id, **overrides) -> dict:
    defaults: Dict[str, Any] = {
        "per_ground_scores": per_ground_scores,
        "lead_judge_user_id": lead_judge_user_id,
    }
    defaults.update(overrides)
    return defaults


def create_brief_payload(brief_type, page_count, **overrides) -> dict:
    defaults: Dict[str, Any] = {"brief_type": brief_type, "page_count": page_count}
    defaults.update(overrides)
    return defaults


def create_declaration_payload(**overrides) -> dict:
    defaults: Dict[str, Any] = {
        "declarant_name": "Dr. Expert",
        "page_count": 10,
        "contains_new_evidence": False,
    }
    defaults.update(overrides)
    return defaults


def create_discovery_payload(**overrides) -> dict:
    defaults: Dict[str, Any] = {"discovery_type": "ROUTINE"}
    defaults.update(overrides)
    return defaults


def create_amendment_motion_payload(substitute_claims, **overrides) -> dict:
    defaults: Dict[str, Any] = {"substitute_claims": substitute_claims}
    defaults.update(overrides)
    return defaults


def substitute_claim(original_claim_number: int, text: Optional[str] = None) -> dict:
    return {
        "original_claim_number": original_claim_number,
        "substitute_text": text or f"{original_claim_number}. (substitute) Amended text ...",
    }


def create_extension_payload(**overrides) -> dict:
    defaults: Dict[str, Any] = {
        "justification": "Good cause shown: coordinated parallel proceedings.",
    }
    defaults.update(overrides)
    return defaults


def create_hearing_room_payload(**overrides) -> dict:
    n = _next()
    defaults: Dict[str, Any] = {"name": f"Room {n}", "capacity": 20}
    defaults.update(overrides)
    return defaults


def schedule_payload(hearing_room_id, start_at, end_at) -> dict:
    return {
        "hearing_room_id": hearing_room_id,
        "start_at": start_at,
        "end_at": end_at,
    }


def outcomes_payload(*claim_outcomes) -> List[dict]:
    """Each entry is (claim_number, outcome)."""
    return [{"claim_number": c, "outcome": o} for c, o in claim_outcomes]


def all_not_unpatentable(claim_numbers: Iterable[int]) -> List[dict]:
    return [{"claim_number": c, "outcome": "NOT_UNPATENTABLE"} for c in claim_numbers]
