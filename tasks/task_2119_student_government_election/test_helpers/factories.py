"""Payload factories — one per creating endpoint, input fields only."""

import itertools

from .constants import (
    PETITION_DEADLINE,
    TERM_END_DATE,
    TERM_START_DATE,
    TEST_DEFAULTS,
    UNDERGRADUATE_CLASS_YEARS,
)

_counter = itertools.count(1)


def unique_student_number(prefix: str = "S") -> str:
    """Student numbers are unique across the whole register (PRD §3.1)."""
    return f"{prefix}-{next(_counter):05d}"


def create_election_payload(**overrides) -> dict:
    payload = {
        "title": TEST_DEFAULTS["ELECTION_TITLE"],
        "academic_year": TEST_DEFAULTS["ACADEMIC_YEAR"],
        "petition_deadline": PETITION_DEADLINE,
        "spending_cap_cents": TEST_DEFAULTS["SPENDING_CAP_CENTS"],
        "poster_cap": TEST_DEFAULTS["POSTER_CAP"],
        "quorum_pct": TEST_DEFAULTS["QUORUM_PCT"],
        "runoff_threshold_pct": TEST_DEFAULTS["RUNOFF_THRESHOLD_PCT"],
    }
    payload.update(overrides)
    return payload


def create_office_payload(election_id: str, **overrides) -> dict:
    payload = {
        "election_id": election_id,
        "name": TEST_DEFAULTS["OFFICE_NAME"],
        "eligible_class_years": list(UNDERGRADUATE_CLASS_YEARS),
        "required_signature_count": 0,
        "term_start_date": TERM_START_DATE,
        "term_end_date": TERM_END_DATE,
    }
    payload.update(overrides)
    return payload


def create_student_payload(**overrides) -> dict:
    payload = {
        "full_name": "Ava Stone",
        "student_number": unique_student_number(),
        "class_year": "SENIOR",
        "gpa": 3.50,
        "credits_completed": 95,
    }
    payload.update(overrides)
    return payload


def update_student_payload(**fields) -> dict:
    """Registrar sync payload — only the amended attributes travel."""
    return dict(fields)


def create_candidacy_payload(election_id: str, office_id: str, student_id: str,
                             **overrides) -> dict:
    payload = {
        "election_id": election_id,
        "office_id": office_id,
        "student_id": student_id,
    }
    payload.update(overrides)
    return payload


def return_petition_payload(reason: str = "Signature sheet is missing the office header") -> dict:
    return {"reason": reason}


def withdraw_candidacy_payload(reason: str = None) -> dict:
    return {} if reason is None else {"reason": reason}


def slate_membership_payload(slate_leader_candidacy_id: str,
                             expected_candidacy_version: int) -> dict:
    return {
        "slate_leader_candidacy_id": slate_leader_candidacy_id,
        "expected_candidacy_version": expected_candidacy_version,
    }


def record_training_payload(modules_completed: int) -> dict:
    return {"modules_completed": modules_completed}


def create_petition_signature_payload(candidacy_id: str, signer_student_id: str,
                                      signed_at: str = "2026-08-05T00:00:00Z",
                                      **overrides) -> dict:
    payload = {
        "candidacy_id": candidacy_id,
        "signer_student_id": signer_student_id,
        "signed_at": signed_at,
    }
    payload.update(overrides)
    return payload


def adjudicate_signature_payload(outcome: str = "VERIFIED",
                                 reject_reason: str = None) -> dict:
    payload = {"outcome": outcome}
    if reject_reason is not None:
        payload["reject_reason"] = reject_reason
    return payload


def void_signature_payload(reason: str = None) -> dict:
    return {} if reason is None else {"reason": reason}


def create_campaign_expense_payload(candidacy_id: str, category: str = "DIGITAL",
                                    amount_cents: int = 1000,
                                    incurred_at: str = "2026-08-05T00:00:00Z",
                                    **overrides) -> dict:
    payload = {
        "candidacy_id": candidacy_id,
        "category": category,
        "amount_cents": amount_cents,
        "incurred_at": incurred_at,
    }
    payload.update(overrides)
    return payload


def reverse_expense_payload(reason: str = None) -> dict:
    return {} if reason is None else {"reason": reason}


def create_compliance_case_payload(election_id: str, candidacy_id: str,
                                   severity: str = "MAJOR",
                                   rule_code: str = "C-4.2",
                                   description: str = "Electioneering inside the polling place",
                                   **overrides) -> dict:
    payload = {
        "election_id": election_id,
        "candidacy_id": candidacy_id,
        "rule_code": rule_code,
        "severity": severity,
        "description": description,
    }
    payload.update(overrides)
    return payload


def dismiss_case_payload(reason: str = None) -> dict:
    return {} if reason is None else {"reason": reason}


def create_referendum_payload(election_id: str, **overrides) -> dict:
    payload = {
        "election_id": election_id,
        "title": "Quorum reform",
        "article_reference": "Art. VII Sec. 3",
        "body_text": "Lower the senate quorum to one third.",
    }
    payload.update(overrides)
    return payload


def review_referendum_payload(outcome: str = "APPROVE", return_reason: str = None) -> dict:
    payload = {"outcome": outcome}
    if return_reason is not None:
        payload["return_reason"] = return_reason
    return payload


def create_ballot_payload(election_id: str, expected_election_version: int,
                          round_number: int = 1, **overrides) -> dict:
    payload = {
        "election_id": election_id,
        "round": round_number,
        "expected_election_version": expected_election_version,
    }
    payload.update(overrides)
    return payload


def candidate_line_payload(office_id: str, candidacy_id: str) -> dict:
    return {
        "line_type": "CANDIDATE",
        "office_id": office_id,
        "candidacy_id": candidacy_id,
    }


def referendum_line_payload(referendum_id: str) -> dict:
    return {"line_type": "REFERENDUM", "referendum_id": referendum_id}


def open_voting_payload(voting_opens_at: str, voting_closes_at: str,
                        round_number: int = 1) -> dict:
    return {
        "round": round_number,
        "voting_opens_at": voting_opens_at,
        "voting_closes_at": voting_closes_at,
    }


def candidate_mark(office_id: str, candidacy_id) -> dict:
    """A candidate mark pairs an office with a candidacy; a null candidacy_id
    records a deliberate abstention on that seat (PRD §3.7)."""
    return {"office_id": office_id, "candidacy_id": candidacy_id}


def referendum_mark(referendum_id: str, choice: str) -> dict:
    return {"referendum_id": referendum_id, "choice": choice}


def create_vote_payload(ballot_id: str, selections: list) -> dict:
    return {"ballot_id": ballot_id, "selections": selections}


def void_vote_payload(void_reason: str = "Machine misread the paper ballot") -> dict:
    return {"void_reason": void_reason}


def create_appeal_payload(election_id: str, candidacy_id: str,
                          remedy_requested: str = "RECOUNT",
                          grounds: str = "Request a manual recount of the paper ballots",
                          compliance_case_id: str = None, **overrides) -> dict:
    payload = {
        "election_id": election_id,
        "candidacy_id": candidacy_id,
        "grounds": grounds,
        "remedy_requested": remedy_requested,
    }
    if compliance_case_id is not None:
        payload["compliance_case_id"] = compliance_case_id
    payload.update(overrides)
    return payload


def resolve_appeal_payload(resolution_note: str = None) -> dict:
    return {} if resolution_note is None else {"resolution_note": resolution_note}


def set_clock_payload(to_iso8601: str) -> dict:
    return {"to_iso8601": to_iso8601}
