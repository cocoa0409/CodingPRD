"""Composite setup helpers.

Every helper drives the public API only, so each test rebuilds its own world
from an empty database. Setup calls go through ``get_success_data`` so a broken
precondition surfaces as a setup failure rather than as a confusing assertion.

Identity threading: the Student, FacultyMentor and Evaluator roles act under the
id of their own row, so every ownership-gated call below uses
``make_student_headers`` / ``make_mentor_headers`` / ``make_evaluator_headers``
with the real row's id.
"""
from typing import Any, Dict, List, Optional

from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import BASE_CLOCK_UTC, TEST_DEFAULTS
from .factories import (
    close_term_payload,
    create_aid_disbursement_payload,
    create_attempt_payload,
    create_blueprint_payload,
    create_competency_payload,
    create_evaluator_payload,
    create_integrity_case_payload,
    create_mentor_assignment_payload,
    create_mentor_payload,
    create_program_payload,
    create_sap_review_payload,
    create_student_payload,
    create_subscription_term_payload,
    create_transcript_record_payload,
    record_score_payload,
    resolve_case_payload,
    submit_attempt_payload,
    withdraw_student_payload,
)
from .test_users import (
    TEST_USERS,
    make_evaluator_headers,
    make_integrity_officer_headers,
    make_mentor_headers,
    make_student_headers,
)

REGISTRAR = TEST_USERS["registrar_headers"]
ADMIN = TEST_USERS["platform_admin_headers"]
AID_OFFICER = TEST_USERS["financial_aid_officer_headers"]
INTEGRITY_OFFICER = TEST_USERS["integrity_officer_headers"]


# ─── Logical clock ────────────────────────────────────────────────────────────

def set_clock(instant: str, headers: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    """Move the logical clock to a supplied instant."""
    return get_success_data(api_client.set_clock(instant, headers or ADMIN))


def read_clock(headers: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    return get_success_data(api_client.get_clock(headers or ADMIN))


# ─── Single-step builders ─────────────────────────────────────────────────────

def create_program(**overrides: Any) -> Dict[str, Any]:
    return get_success_data(
        api_client.create_program(create_program_payload(**overrides), REGISTRAR)
    )


def publish_program(program_id: str) -> Dict[str, Any]:
    return get_success_data(api_client.publish_program(program_id, REGISTRAR))


def create_competency(program_id: str, **overrides: Any) -> Dict[str, Any]:
    return get_success_data(
        api_client.create_competency(
            create_competency_payload(program_id, **overrides), REGISTRAR
        )
    )


def set_prerequisite(competency_id: str, prerequisite_competency_id: Optional[str]
                     ) -> Dict[str, Any]:
    return get_success_data(
        api_client.set_competency_prerequisite(
            competency_id,
            {"prerequisite_competency_id": prerequisite_competency_id},
            REGISTRAR,
        )
    )


def retire_competency(competency_id: str) -> Dict[str, Any]:
    return get_success_data(api_client.retire_competency(competency_id, REGISTRAR))


def create_blueprint(
    competency: Dict[str, Any],
    dimensions: Optional[List[Dict[str, Any]]] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    """Publish a rubric blueprint, supplying the competency's current version."""
    payload = create_blueprint_payload(
        competency["id"], competency["version"], dimensions=dimensions, **overrides
    )
    return get_success_data(api_client.create_blueprint(payload, REGISTRAR))


def create_student(program_id: str, **overrides: Any) -> Dict[str, Any]:
    return get_success_data(
        api_client.create_student(
            create_student_payload(program_id, **overrides), REGISTRAR
        )
    )


def activate_student(student_id: str) -> Dict[str, Any]:
    return get_success_data(api_client.activate_student(student_id, REGISTRAR))


def suspend_student(student_id: str, reason: str = "administrative hold"
                    ) -> Dict[str, Any]:
    return get_success_data(
        api_client.suspend_student(student_id, REGISTRAR, {"reason": reason})
    )


def reinstate_student(student_id: str) -> Dict[str, Any]:
    return get_success_data(api_client.reinstate_student(student_id, REGISTRAR))


def withdraw_student(student_id: str, effective_utc: str,
                     reason: str = "personal") -> Dict[str, Any]:
    return get_success_data(
        api_client.withdraw_student(
            student_id, withdraw_student_payload(effective_utc, reason), REGISTRAR
        )
    )


def create_term(student_id: str, **overrides: Any) -> Dict[str, Any]:
    return get_success_data(
        api_client.create_subscription_term(
            create_subscription_term_payload(student_id, **overrides), REGISTRAR
        )
    )


def activate_term(term_id: str) -> Dict[str, Any]:
    return get_success_data(api_client.activate_subscription_term(term_id, REGISTRAR))


def close_term(term_id: str, outcome: str, effective_utc: str) -> Dict[str, Any]:
    return get_success_data(
        api_client.close_subscription_term(
            term_id, close_term_payload(outcome, effective_utc), REGISTRAR
        )
    )


def create_mentor(**overrides: Any) -> Dict[str, Any]:
    return get_success_data(
        api_client.create_mentor(create_mentor_payload(**overrides), REGISTRAR)
    )


def set_mentor_status(mentor_id: str, status: str) -> Dict[str, Any]:
    return get_success_data(
        api_client.set_mentor_status(mentor_id, {"status": status}, REGISTRAR)
    )


def assign_mentor(student: Dict[str, Any], mentor_id: Optional[str] = None,
                  **overrides: Any) -> Dict[str, Any]:
    """Assign a mentor, supplying the student's current version."""
    payload = create_mentor_assignment_payload(
        student["id"], student["version"], mentor_id=mentor_id, **overrides
    )
    return get_success_data(api_client.create_mentor_assignment(payload, REGISTRAR))


def record_contact(assignment_id: str, mentor_id: str,
                   note: str = "Weekly progress call") -> Dict[str, Any]:
    return get_success_data(
        api_client.record_contact(
            assignment_id, make_mentor_headers(mentor_id), {"note": note}
        )
    )


def record_endorsement(assignment_id: str, mentor_id: str, competency_id: str
                       ) -> Dict[str, Any]:
    return get_success_data(
        api_client.record_endorsement(
            assignment_id, {"competency_id": competency_id},
            make_mentor_headers(mentor_id),
        )
    )


def end_assignment(assignment_id: str) -> Dict[str, Any]:
    return get_success_data(api_client.end_mentor_assignment(assignment_id, REGISTRAR))


def create_evaluator(**overrides: Any) -> Dict[str, Any]:
    return get_success_data(
        api_client.create_evaluator(create_evaluator_payload(**overrides), REGISTRAR)
    )


def set_evaluator_status(evaluator_id: str, status: str) -> Dict[str, Any]:
    return get_success_data(
        api_client.set_evaluator_status(evaluator_id, {"status": status}, ADMIN)
    )


def open_attempt(student_id: str, competency_id: str,
                 headers: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    return get_success_data(
        api_client.create_attempt(
            create_attempt_payload(student_id, competency_id),
            headers or make_student_headers(student_id),
        )
    )


def submit_attempt(attempt_id: str, student_id: str, **overrides: Any
                   ) -> Dict[str, Any]:
    return get_success_data(
        api_client.submit_attempt(
            attempt_id, submit_attempt_payload(**overrides),
            make_student_headers(student_id),
        )
    )


def record_score(attempt_id: str, evaluator_id: str,
                 dimension_scores: Optional[List[Dict[str, Any]]] = None,
                 **overrides: Any) -> Dict[str, Any]:
    return get_success_data(
        api_client.record_score(
            attempt_id,
            record_score_payload(evaluator_id, dimension_scores, **overrides),
            make_evaluator_headers(evaluator_id),
        )
    )


def request_revision(attempt_id: str, evaluator_id: str,
                     reason: str = "Artifact missing a section") -> Dict[str, Any]:
    return get_success_data(
        api_client.request_revision(
            attempt_id, {"reason": reason}, make_evaluator_headers(evaluator_id)
        )
    )


def reopen_attempt(attempt_id: str, student_id: str) -> Dict[str, Any]:
    return get_success_data(
        api_client.reopen_attempt(attempt_id, make_student_headers(student_id))
    )


def open_case(attempt_id: str, opener_user_id: str = "officer-open",
              **overrides: Any) -> Dict[str, Any]:
    return get_success_data(
        api_client.create_integrity_case(
            create_integrity_case_payload(attempt_id, **overrides),
            make_integrity_officer_headers(opener_user_id),
        )
    )


def investigate_case(case_id: str, officer_user_id: str = "officer-open"
                     ) -> Dict[str, Any]:
    return get_success_data(
        api_client.investigate_case(
            case_id, make_integrity_officer_headers(officer_user_id)
        )
    )


def resolve_case(case_id: str, outcome: str, sanction: str = "NONE",
                 resolver_user_id: str = "officer-resolve") -> Dict[str, Any]:
    return get_success_data(
        api_client.resolve_case(
            case_id, resolve_case_payload(outcome, sanction),
            make_integrity_officer_headers(resolver_user_id),
        )
    )


def create_sap_review(student_id: str, term_id: str) -> Dict[str, Any]:
    return get_success_data(
        api_client.create_sap_review(
            create_sap_review_payload(student_id, term_id), REGISTRAR
        )
    )


def schedule_aid(student_id: str, term: Dict[str, Any], **overrides: Any
                 ) -> Dict[str, Any]:
    """Schedule an award, supplying the term's current version."""
    payload = create_aid_disbursement_payload(
        student_id, term["id"], term["version"], **overrides
    )
    return get_success_data(api_client.create_aid_disbursement(payload, AID_OFFICER))


def disburse_aid(award_id: str) -> Dict[str, Any]:
    return get_success_data(api_client.disburse_aid(award_id, AID_OFFICER))


def return_aid(award_id: str) -> Dict[str, Any]:
    return get_success_data(api_client.return_aid(award_id, AID_OFFICER))


def cancel_aid(award_id: str) -> Dict[str, Any]:
    return get_success_data(api_client.cancel_aid(award_id, AID_OFFICER))


def create_transcript(student_id: str, purpose: str = "TRANSFER") -> Dict[str, Any]:
    return get_success_data(
        api_client.create_transcript_record(
            create_transcript_record_payload(student_id, purpose), REGISTRAR
        )
    )


def issue_transcript(record_id: str) -> Dict[str, Any]:
    return get_success_data(api_client.issue_transcript_record(record_id, REGISTRAR))


# ─── Read-back helpers ────────────────────────────────────────────────────────

def refresh_program(program_id: str) -> Dict[str, Any]:
    return get_success_data(api_client.get_program(program_id, REGISTRAR))


def refresh_competency(competency_id: str) -> Dict[str, Any]:
    return get_success_data(api_client.get_competency(competency_id, REGISTRAR))


def refresh_blueprint(blueprint_id: str) -> Dict[str, Any]:
    return get_success_data(api_client.get_blueprint(blueprint_id, REGISTRAR))


def refresh_student(student_id: str) -> Dict[str, Any]:
    return get_success_data(api_client.get_student(student_id, REGISTRAR))


def refresh_term(term_id: str) -> Dict[str, Any]:
    return get_success_data(api_client.get_subscription_term(term_id, REGISTRAR))


def refresh_mentor(mentor_id: str) -> Dict[str, Any]:
    return get_success_data(api_client.get_mentor(mentor_id, REGISTRAR))


def refresh_assignment(assignment_id: str) -> Dict[str, Any]:
    return get_success_data(api_client.get_mentor_assignment(assignment_id, REGISTRAR))


def refresh_evaluator(evaluator_id: str) -> Dict[str, Any]:
    return get_success_data(api_client.get_evaluator(evaluator_id, REGISTRAR))


def refresh_attempt(attempt_id: str) -> Dict[str, Any]:
    return get_success_data(api_client.get_attempt(attempt_id, REGISTRAR))


def refresh_score(score_id: str) -> Dict[str, Any]:
    return get_success_data(api_client.get_evaluator_score(score_id, REGISTRAR))


def refresh_case(case_id: str) -> Dict[str, Any]:
    return get_success_data(api_client.get_integrity_case(case_id, REGISTRAR))


def refresh_award(award_id: str) -> Dict[str, Any]:
    return get_success_data(api_client.get_aid_disbursement(award_id, REGISTRAR))


def refresh_transcript(record_id: str) -> Dict[str, Any]:
    return get_success_data(api_client.get_transcript_record(record_id, REGISTRAR))


def progress_summary(student_id: str, headers: Optional[Dict[str, str]] = None
                     ) -> Dict[str, Any]:
    return get_success_data(
        api_client.get_progress_summary(student_id, headers or REGISTRAR)
    )


# ─── Composite scenarios ──────────────────────────────────────────────────────
# The recurring preamble every scenario shares: pin the clock, register a
# program with one competency, publish it, enrol a student, activate them and
# open an active subscription term.

def base_chain(
    clock: str = BASE_CLOCK_UTC,
    program_overrides: Optional[Dict[str, Any]] = None,
    competency_overrides: Optional[Dict[str, Any]] = None,
    student_overrides: Optional[Dict[str, Any]] = None,
    term_overrides: Optional[Dict[str, Any]] = None,
    with_blueprint: bool = False,
    blueprint_dimensions: Optional[List[Dict[str, Any]]] = None,
    blueprint_overrides: Optional[Dict[str, Any]] = None,
    activate_the_student: bool = True,
    activate_the_term: bool = True,
    create_the_term: bool = True,
) -> Dict[str, Any]:
    """Published program + one competency + student + subscription term.

    Returns a context dict keyed ``program``, ``competency``, ``student``,
    ``term`` and — when ``with_blueprint`` is set — ``blueprint``.
    """
    set_clock(clock)
    program = create_program(**(program_overrides or {}))
    competency = create_competency(program["id"], **(competency_overrides or {}))
    program = publish_program(program["id"])
    ctx: Dict[str, Any] = {"program": program}
    if with_blueprint:
        blueprint = create_blueprint(
            competency, dimensions=blueprint_dimensions, **(blueprint_overrides or {})
        )
        ctx["blueprint"] = blueprint
        competency = refresh_competency(competency["id"])
    ctx["competency"] = competency
    student = create_student(program["id"], **(student_overrides or {}))
    if activate_the_student:
        student = activate_student(student["id"])
    ctx["student"] = student
    if create_the_term:
        term = create_term(student["id"], **(term_overrides or {}))
        if activate_the_term:
            term = activate_term(term["id"])
        ctx["term"] = term
    return ctx


def assessment_ready(
    evaluator_overrides: Optional[Dict[str, Any]] = None,
    open_the_attempt: bool = True,
    **base_kwargs: Any,
) -> Dict[str, Any]:
    """Base chain + a published blueprint + one CERTIFIED evaluator + a DRAFT
    attempt on the competency."""
    base_kwargs.setdefault("with_blueprint", True)
    ctx = base_chain(**base_kwargs)
    ctx["evaluator"] = create_evaluator(**(evaluator_overrides or {}))
    if open_the_attempt:
        ctx["attempt"] = open_attempt(
            ctx["student"]["id"], ctx["competency"]["id"]
        )
    return ctx


def attempt_under_review(submit_overrides: Optional[Dict[str, Any]] = None,
                         **kwargs: Any) -> Dict[str, Any]:
    """Assessment-ready scenario whose attempt has been submitted and is waiting
    for a reader."""
    ctx = assessment_ready(**kwargs)
    ctx["attempt"] = submit_attempt(
        ctx["attempt"]["id"], ctx["student"]["id"], **(submit_overrides or {})
    )
    return ctx


def scored_attempt(score: float = 90, **kwargs: Any) -> Dict[str, Any]:
    """Attempt resolved by a single reader on a one-reader blueprint. Adds
    ``score`` and refreshes ``attempt``, ``student`` and ``term``."""
    ctx = attempt_under_review(**kwargs)
    ctx["score"] = record_score(
        ctx["attempt"]["id"], ctx["evaluator"]["id"], [{"code": "D1", "score": score}]
    )
    ctx["attempt"] = refresh_attempt(ctx["attempt"]["id"])
    ctx["student"] = refresh_student(ctx["student"]["id"])
    if "term" in ctx:
        ctx["term"] = refresh_term(ctx["term"]["id"])
    return ctx


def two_reader_scenario(**kwargs: Any) -> Dict[str, Any]:
    """Assessment-ready scenario on a two-reader blueprint with two independent
    evaluators, the attempt already submitted."""
    kwargs.setdefault("blueprint_overrides", {"required_evaluator_count": 2})
    ctx = attempt_under_review(
        evaluator_overrides={"full_name": "Reader One", "email": "r1@example.edu"},
        **kwargs,
    )
    ctx["evaluator_one"] = ctx["evaluator"]
    ctx["evaluator_two"] = create_evaluator(
        full_name="Reader Two", email="r2@example.edu", certification_level="SENIOR"
    )
    return ctx


def mentored_scenario(mentor_overrides: Optional[Dict[str, Any]] = None,
                      **base_kwargs: Any) -> Dict[str, Any]:
    """Base chain plus a registered mentor holding an ACTIVE assignment on the
    student. Adds ``mentor`` and ``assignment`` and refreshes ``student``."""
    ctx = base_chain(**base_kwargs)
    ctx["mentor"] = create_mentor(**(mentor_overrides or {}))
    ctx["assignment"] = assign_mentor(ctx["student"], ctx["mentor"]["id"])
    ctx["student"] = refresh_student(ctx["student"]["id"])
    ctx["mentor"] = refresh_mentor(ctx["mentor"]["id"])
    return ctx


def scheduled_aid_scenario(**base_kwargs: Any) -> Dict[str, Any]:
    """Base chain plus one SCHEDULED aid award on the active term."""
    ctx = base_chain(**base_kwargs)
    ctx["award"] = schedule_aid(ctx["student"]["id"], ctx["term"])
    ctx["term"] = refresh_term(ctx["term"]["id"])
    ctx["student"] = refresh_student(ctx["student"]["id"])
    return ctx


def mastery_then_aid_scenario(score: float = 90, **kwargs: Any) -> Dict[str, Any]:
    """A mastered attempt followed by a SCHEDULED award on the same term, so the
    term already carries a non-zero credit-hour equivalency."""
    ctx = scored_attempt(score=score, **kwargs)
    ctx["award"] = schedule_aid(ctx["student"]["id"], ctx["term"])
    ctx["term"] = refresh_term(ctx["term"]["id"])
    ctx["student"] = refresh_student(ctx["student"]["id"])
    return ctx


def held_attempt_scenario(opener_user_id: str = "officer-open", **kwargs: Any
                          ) -> Dict[str, Any]:
    """An attempt under review with one OPEN integrity case against it, so the
    attempt sits in INTEGRITY_HOLD."""
    ctx = attempt_under_review(**kwargs)
    ctx["case"] = open_case(ctx["attempt"]["id"], opener_user_id=opener_user_id)
    ctx["attempt"] = refresh_attempt(ctx["attempt"]["id"])
    return ctx


def student_headers(ctx: Dict[str, Any]) -> Dict[str, str]:
    """Identity headers for the scenario's own student."""
    return make_student_headers(ctx["student"]["id"])


def mentor_headers(ctx: Dict[str, Any]) -> Dict[str, str]:
    return make_mentor_headers(ctx["mentor"]["id"])


def evaluator_headers(ctx: Dict[str, Any]) -> Dict[str, str]:
    return make_evaluator_headers(ctx["evaluator"]["id"])
