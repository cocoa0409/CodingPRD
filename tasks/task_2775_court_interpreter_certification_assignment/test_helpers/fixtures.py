"""Composite setup helpers.

Every test starts against an empty database (the harness relaunches the server
before each test), so every fixture builds its preconditions from scratch using
only PRD-declared endpoints.

All helpers use get_success_data() so that a broken precondition reports as a
setup failure rather than as a confusing assertion failure. Ownership-gated
Interpreter calls always go through make_interpreter_headers(interpreter["id"]).
"""

from typing import Any, Dict, List, Optional

from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import DEFAULT_CLOCK_UTC, TEST_DEFAULTS
from .factories import (
    adjudicate_complaint_payload,
    appeal_complaint_payload,
    appeal_decision_payload,
    cancel_assignment_payload,
    complete_assignment_payload,
    continue_hearing_payload,
    create_assignment_payload,
    create_complaint_payload,
    create_courthouse_payload,
    create_credential_payload,
    create_hearing_payload,
    create_interpreter_payload,
    create_language_payload,
    create_north_courthouse_payload,
    create_rare_language_payload,
    create_rate_schedule_payload,
    create_unmet_need_report_payload,
    decline_assignment_payload,
    ethics_training_payload,
    exam_attempt_payload,
    pay_pay_claim_payload,
    renew_credential_payload,
    review_complaint_payload,
    revoke_credential_payload,
    set_clock_payload,
)
from .test_users import (
    TEST_USERS,
    make_interpreter_headers,
    make_program_admin_headers,
    make_quality_reviewer_headers,
)

ADMIN = TEST_USERS["program_admin_headers"]
CREDENTIALING = TEST_USERS["credentialing_officer_headers"]
COORDINATOR = TEST_USERS["scheduling_coordinator_headers"]
FISCAL = TEST_USERS["fiscal_officer_headers"]
REVIEWER = TEST_USERS["quality_reviewer_headers"]
REVIEWER_ALT = TEST_USERS["quality_reviewer_alt_headers"]


# ---------------------------------------------------------------------------
# Clock (PRD §2.5)
# ---------------------------------------------------------------------------
def set_clock(to_iso8601: str = DEFAULT_CLOCK_UTC) -> Dict[str, Any]:
    """Move the logical clock forward. Returns the clock read {current_utc: ...}."""
    return get_success_data(
        api_client.set_clock(set_clock_payload(to_iso8601), ADMIN)
    )


# ---------------------------------------------------------------------------
# Tier 1 — single-entity creation wrappers
# ---------------------------------------------------------------------------
def bootstrap_language(**overrides) -> Dict[str, Any]:
    """POST /languages with the canonical DESIGNATED Spanish row."""
    return get_success_data(
        api_client.create_language(create_language_payload(**overrides), ADMIN)
    )


def bootstrap_rare_language(**overrides) -> Dict[str, Any]:
    """POST /languages with a RARE language that has no oral instrument."""
    return get_success_data(
        api_client.create_language(create_rare_language_payload(**overrides), ADMIN)
    )


def bootstrap_courthouse(**overrides) -> Dict[str, Any]:
    """POST /courthouses with the canonical CERTIFIED_VRI main courthouse."""
    return get_success_data(
        api_client.create_courthouse(create_courthouse_payload(**overrides), ADMIN)
    )


def bootstrap_north_courthouse(**overrides) -> Dict[str, Any]:
    """POST /courthouses with a second courthouse in another county, no VRI kit."""
    return get_success_data(
        api_client.create_courthouse(create_north_courthouse_payload(**overrides), ADMIN)
    )


def bootstrap_rate_schedule(**overrides) -> Dict[str, Any]:
    """POST /rate-schedules with the canonical open-ended schedule."""
    return get_success_data(
        api_client.create_rate_schedule(create_rate_schedule_payload(**overrides), ADMIN)
    )


def enrol_interpreter(**overrides) -> Dict[str, Any]:
    """POST /interpreters — the applicant enrolment call."""
    return get_success_data(
        api_client.create_interpreter(create_interpreter_payload(**overrides), CREDENTIALING)
    )


def complete_ethics_training(interpreter_id: str,
                             completed_on: str = "2026-08-01",
                             provider: str = TEST_DEFAULTS["ETHICS_PROVIDER"]
                             ) -> Dict[str, Any]:
    """POST /interpreters/{id}/ethics-training — returns the updated interpreter."""
    return get_success_data(
        api_client.record_ethics_training(
            interpreter_id,
            ethics_training_payload(completed_on=completed_on, provider=provider),
            CREDENTIALING,
        )
    )


def read_interpreter(interpreter_id: str, headers: Optional[Dict[str, str]] = None
                     ) -> Dict[str, Any]:
    return get_success_data(
        api_client.get_interpreter(interpreter_id, headers or CREDENTIALING)
    )


def read_courthouse(courthouse_id: str, headers: Optional[Dict[str, str]] = None
                    ) -> Dict[str, Any]:
    """GET /courthouses/{id} — the live encumbrance ledger."""
    return get_success_data(api_client.get_courthouse(courthouse_id, headers or FISCAL))


def read_hearing(hearing_id: str, headers: Optional[Dict[str, str]] = None
                 ) -> Dict[str, Any]:
    return get_success_data(api_client.get_hearing(hearing_id, headers or COORDINATOR))


def read_assignment(assignment_id: str, headers: Optional[Dict[str, str]] = None
                    ) -> Dict[str, Any]:
    return get_success_data(
        api_client.get_assignment(assignment_id, headers or COORDINATOR)
    )


def read_credential(credential_id: str, headers: Optional[Dict[str, str]] = None
                    ) -> Dict[str, Any]:
    return get_success_data(
        api_client.get_credential(credential_id, headers or CREDENTIALING)
    )


def read_pay_claim(pay_claim_id: str, headers: Optional[Dict[str, str]] = None
                   ) -> Dict[str, Any]:
    return get_success_data(api_client.get_pay_claim(pay_claim_id, headers or FISCAL))


def read_complaint(complaint_id: str, headers: Optional[Dict[str, str]] = None
                   ) -> Dict[str, Any]:
    return get_success_data(api_client.get_complaint(complaint_id, headers or REVIEWER))


def read_language(language_id: str, headers: Optional[Dict[str, str]] = None
                  ) -> Dict[str, Any]:
    return get_success_data(api_client.get_language(language_id, headers or ADMIN))


def read_quality_score(interpreter_id: str, headers: Optional[Dict[str, str]] = None
                       ) -> Dict[str, Any]:
    """GET /interpreters/{id}/quality-score — both variants side by side."""
    return get_success_data(
        api_client.get_quality_score(interpreter_id, headers or ADMIN)
    )


# ---------------------------------------------------------------------------
# Tier 2 — program configuration bundle
# ---------------------------------------------------------------------------
def setup_program_config(language_overrides: Optional[Dict[str, Any]] = None,
                         courthouse_overrides: Optional[Dict[str, Any]] = None,
                         rate_overrides: Optional[Dict[str, Any]] = None,
                         with_rate_schedule: bool = True,
                         with_north_courthouse: bool = False,
                         with_rare_language: bool = False,
                         clock: Optional[str] = DEFAULT_CLOCK_UTC,
                         ) -> Dict[str, Any]:
    """Clock + language + courthouse (+ rate schedule) — the shared preamble.

    Returns {"language", "courthouse", "rate_schedule", "north_courthouse",
    "rare_language"}; absent members are None.
    """
    if clock:
        set_clock(clock)
    config: Dict[str, Any] = {
        "language": bootstrap_language(**(language_overrides or {})),
        "courthouse": bootstrap_courthouse(**(courthouse_overrides or {})),
        "rate_schedule": None,
        "north_courthouse": None,
        "rare_language": None,
    }
    if with_rare_language:
        config["rare_language"] = bootstrap_rare_language()
    if with_north_courthouse:
        config["north_courthouse"] = bootstrap_north_courthouse()
    if with_rate_schedule:
        config["rate_schedule"] = bootstrap_rate_schedule(**(rate_overrides or {}))
    return config


# ---------------------------------------------------------------------------
# Tier 3 — credential lifecycle shortcuts (PRD §3.3)
# ---------------------------------------------------------------------------
def open_credential(interpreter_id: str, language_id: str,
                    target_tier: str = "CERTIFIED",
                    expected_interpreter_version: Optional[int] = None,
                    ) -> Dict[str, Any]:
    """POST /credentials. When the expected version is omitted it is read live."""
    if expected_interpreter_version is None:
        expected_interpreter_version = read_interpreter(interpreter_id)["version"]
    return get_success_data(
        api_client.create_credential(
            create_credential_payload(
                interpreter_id, language_id, expected_interpreter_version, target_tier
            ),
            CREDENTIALING,
        )
    )


def record_exam_attempt(credential_id: str, exam_type: str = "WRITTEN",
                        score: float = 86, taken_on: str = "2026-08-01",
                        ) -> Dict[str, Any]:
    """POST /credentials/{id}/exam-attempts."""
    return get_success_data(
        api_client.create_exam_attempt(
            credential_id,
            exam_attempt_payload(exam_type=exam_type, score=score, taken_on=taken_on),
            CREDENTIALING,
        )
    )


def advance_credential(credential_id: str) -> Dict[str, Any]:
    """POST /credentials/{id}/advance."""
    return get_success_data(
        api_client.advance_credential(credential_id, CREDENTIALING)
    )


def drive_credential_to_active(credential_id: str,
                               written_score: float = TEST_DEFAULTS["WRITTEN_PASS_SCORE"],
                               oral_score: float = TEST_DEFAULTS["ORAL_PASS_SCORE"],
                               taken_on: str = "2026-08-01",
                               ) -> Dict[str, Any]:
    """Walk a credential from its current stage to ACTIVE.

    Records a passing attempt for whichever examination the current status is
    waiting on, then advances; PENDING_ETHICS advances straight to ACTIVE. Works
    for every target tier because it reads the live status each hop.
    """
    credential = read_credential(credential_id)
    for _ in range(8):
        status = credential["status"]
        if status == "ACTIVE":
            return credential
        if status == "PENDING_WRITTEN":
            record_exam_attempt(credential_id, "WRITTEN", written_score, taken_on)
        elif status == "PENDING_ORAL":
            record_exam_attempt(credential_id, "ORAL", oral_score, taken_on)
        elif status != "PENDING_ETHICS":
            raise AssertionError(
                f"Setup step failed: credential {credential_id} is in status {status}, "
                "which cannot be advanced to ACTIVE"
            )
        credential = advance_credential(credential_id)
    raise AssertionError(
        f"Setup step failed: credential {credential_id} never reached ACTIVE"
    )


def setup_active_interpreter(language_id: str,
                             target_tier: str = "CERTIFIED",
                             interpreter_overrides: Optional[Dict[str, Any]] = None,
                             written_score: float = TEST_DEFAULTS["WRITTEN_PASS_SCORE"],
                             oral_score: float = TEST_DEFAULTS["ORAL_PASS_SCORE"],
                             taken_on: str = "2026-08-01",
                             ethics_completed_on: str = "2026-08-01",
                             with_ethics: bool = True,
                             ) -> Dict[str, Any]:
    """Enrol an interpreter and drive one credential all the way to ACTIVE.

    Returns {"interpreter", "credential"} with the interpreter re-read after the
    credential activated, so roster_status / credential_tier are current.
    """
    interpreter = enrol_interpreter(**(interpreter_overrides or {}))
    if with_ethics:
        interpreter = complete_ethics_training(
            interpreter["id"], completed_on=ethics_completed_on
        )
    credential = open_credential(
        interpreter["id"], language_id, target_tier, interpreter["version"]
    )
    credential = drive_credential_to_active(
        credential["id"], written_score=written_score, oral_score=oral_score,
        taken_on=taken_on,
    )
    return {
        "interpreter": read_interpreter(interpreter["id"]),
        "credential": credential,
    }


def setup_pending_ethics_credential(language_id: str,
                                    target_tier: str = "CERTIFIED",
                                    interpreter_overrides: Optional[Dict[str, Any]] = None,
                                    written_score: float = TEST_DEFAULTS["WRITTEN_PASS_SCORE"],
                                    oral_score: float = TEST_DEFAULTS["ORAL_PASS_SCORE"],
                                    taken_on: str = "2026-08-01",
                                    with_ethics: bool = False,
                                    ) -> Dict[str, Any]:
    """Drive a credential to PENDING_ETHICS and stop there.

    With with_ethics=False the holder's ethics_training_status is still
    NOT_STARTED, so the next advance is the one the PRD refuses.
    """
    interpreter = enrol_interpreter(**(interpreter_overrides or {}))
    if with_ethics:
        interpreter = complete_ethics_training(interpreter["id"], completed_on=taken_on)
    credential = open_credential(
        interpreter["id"], language_id, target_tier, interpreter["version"]
    )
    for _ in range(6):
        status = credential["status"]
        if status == "PENDING_ETHICS":
            break
        if status == "PENDING_WRITTEN":
            record_exam_attempt(credential["id"], "WRITTEN", written_score, taken_on)
        elif status == "PENDING_ORAL":
            record_exam_attempt(credential["id"], "ORAL", oral_score, taken_on)
        else:
            raise AssertionError(
                f"Setup step failed: unexpected credential status {status}"
            )
        credential = advance_credential(credential["id"])
    return {
        "interpreter": read_interpreter(interpreter["id"]),
        "credential": credential,
    }


# ---------------------------------------------------------------------------
# Tier 3 — calendar and assignment shortcuts (PRD §3.5-§3.7)
# ---------------------------------------------------------------------------
def schedule_hearing(courthouse_id: str, language_id: str, **overrides
                     ) -> Dict[str, Any]:
    """POST /hearings — priority is scored and frozen by this call."""
    return get_success_data(
        api_client.create_hearing(
            create_hearing_payload(courthouse_id, language_id, **overrides), COORDINATOR
        )
    )


def propose_assignment(hearing_id: str, interpreter_id: Optional[str] = None,
                       expected_hearing_version: Optional[int] = None,
                       **overrides) -> Dict[str, Any]:
    """POST /assignments. The hearing version is read live unless pinned."""
    if expected_hearing_version is None:
        expected_hearing_version = read_hearing(hearing_id)["version"]
    return get_success_data(
        api_client.create_assignment(
            create_assignment_payload(
                hearing_id, expected_hearing_version, interpreter_id, **overrides
            ),
            COORDINATOR,
        )
    )


def confirm_assignment(assignment_id: str, interpreter_id: str) -> Dict[str, Any]:
    """POST /assignments/{id}/confirm as the owning interpreter."""
    return get_success_data(
        api_client.confirm_assignment(
            assignment_id, make_interpreter_headers(interpreter_id)
        )
    )


def decline_assignment(assignment_id: str, interpreter_id: str,
                       reason_code: str = "INTERPRETER_DECLINED") -> Dict[str, Any]:
    """POST /assignments/{id}/decline as the owning interpreter."""
    return get_success_data(
        api_client.decline_assignment(
            assignment_id,
            decline_assignment_payload(reason_code=reason_code),
            make_interpreter_headers(interpreter_id),
        )
    )


def check_in_assignment(assignment_id: str, interpreter_id: str) -> Dict[str, Any]:
    """POST /assignments/{id}/check-in as the owning interpreter."""
    return get_success_data(
        api_client.check_in_assignment(
            assignment_id, make_interpreter_headers(interpreter_id)
        )
    )


def complete_assignment(assignment_id: str, interpreter_id: str,
                        actual_end_utc: str,
                        one_way_miles: Optional[float] = None) -> Dict[str, Any]:
    """POST /assignments/{id}/complete as the owning interpreter."""
    return get_success_data(
        api_client.complete_assignment(
            assignment_id,
            complete_assignment_payload(actual_end_utc, one_way_miles),
            make_interpreter_headers(interpreter_id),
        )
    )


def cancel_assignment(assignment_id: str,
                      reason_code: str = "COORDINATOR_CANCELLED") -> Dict[str, Any]:
    """POST /assignments/{id}/cancel as the scheduling coordinator."""
    return get_success_data(
        api_client.cancel_assignment(
            assignment_id, cancel_assignment_payload(reason_code=reason_code), COORDINATOR
        )
    )


def record_no_show(assignment_id: str,
                   headers: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    """POST /assignments/{id}/no-show as the scheduling coordinator."""
    return get_success_data(
        api_client.no_show_assignment(assignment_id, headers or COORDINATOR)
    )


def continue_hearing(hearing_id: str,
                     reason_code: str = "COURT_CONGESTION") -> Dict[str, Any]:
    """POST /hearings/{id}/continue as the scheduling coordinator."""
    return get_success_data(
        api_client.continue_hearing(
            hearing_id, continue_hearing_payload(reason_code=reason_code), COORDINATOR
        )
    )


def pay_claim_for_assignment(assignment_id: str) -> Dict[str, Any]:
    """GET /pay-claims?assignment_id=... and return the single claim row."""
    data = get_success_data(
        api_client.list_pay_claims(FISCAL, params={"assignment_id": assignment_id})
    )
    assert data, f"Setup step failed: no pay claim exists for assignment {assignment_id}"
    return data[0]


def pay_claims_for_assignment(assignment_id: str) -> List[Dict[str, Any]]:
    """GET /pay-claims?assignment_id=... and return every claim row."""
    return get_success_data(
        api_client.list_pay_claims(FISCAL, params={"assignment_id": assignment_id})
    )


def submit_pay_claim(pay_claim_id: str, interpreter_id: str) -> Dict[str, Any]:
    """POST /pay-claims/{id}/submit as the owning interpreter."""
    return get_success_data(
        api_client.submit_pay_claim(
            pay_claim_id, make_interpreter_headers(interpreter_id)
        )
    )


def approve_pay_claim(pay_claim_id: str) -> Dict[str, Any]:
    """POST /pay-claims/{id}/approve as the fiscal officer."""
    return get_success_data(api_client.approve_pay_claim(pay_claim_id, FISCAL))


def issue_payment(pay_claim_id: str,
                  payment_reference: str = "WARRANT-2026-0001") -> Dict[str, Any]:
    """POST /pay-claims/{id}/pay as the fiscal officer."""
    return get_success_data(
        api_client.pay_pay_claim(
            pay_claim_id, pay_pay_claim_payload(payment_reference), FISCAL
        )
    )


# ---------------------------------------------------------------------------
# Tier 4 — full service scenarios
# ---------------------------------------------------------------------------
def setup_confirmed_assignment(hearing_overrides: Optional[Dict[str, Any]] = None,
                               assignment_overrides: Optional[Dict[str, Any]] = None,
                               config: Optional[Dict[str, Any]] = None,
                               interpreter_bundle: Optional[Dict[str, Any]] = None,
                               target_tier: str = "CERTIFIED",
                               config_kwargs: Optional[Dict[str, Any]] = None,
                               ) -> Dict[str, Any]:
    """Config + ACTIVE interpreter + hearing + CONFIRMED assignment + claim.

    Returns {"language", "courthouse", "rate_schedule", "north_courthouse",
    "rare_language", "interpreter", "credential", "hearing", "assignment",
    "pay_claim"}. The claim is the ENCUMBERED PROVISIONAL claim the confirm made.
    """
    config = config or setup_program_config(**(config_kwargs or {}))
    bundle = interpreter_bundle or setup_active_interpreter(
        config["language"]["id"], target_tier=target_tier
    )
    hearing_overrides = dict(hearing_overrides or {})
    hearing_courthouse_id = hearing_overrides.pop(
        "courthouse_id", config["courthouse"]["id"]
    )
    hearing_language_id = hearing_overrides.pop("language_id", config["language"]["id"])
    hearing = schedule_hearing(
        hearing_courthouse_id, hearing_language_id, **hearing_overrides
    )
    assignment = propose_assignment(
        hearing["id"], bundle["interpreter"]["id"], **(assignment_overrides or {})
    )
    assignment = confirm_assignment(assignment["id"], bundle["interpreter"]["id"])
    result = dict(config)
    result.update(
        {
            "interpreter": bundle["interpreter"],
            "credential": bundle["credential"],
            "hearing": read_hearing(hearing["id"]),
            "assignment": assignment,
            "pay_claim": pay_claim_for_assignment(assignment["id"]),
        }
    )
    return result


def setup_served_assignment(check_in_clock: str,
                            actual_end_utc: str,
                            one_way_miles: Optional[float] = None,
                            hearing_overrides: Optional[Dict[str, Any]] = None,
                            assignment_overrides: Optional[Dict[str, Any]] = None,
                            config: Optional[Dict[str, Any]] = None,
                            interpreter_bundle: Optional[Dict[str, Any]] = None,
                            target_tier: str = "CERTIFIED",
                            config_kwargs: Optional[Dict[str, Any]] = None,
                            ) -> Dict[str, Any]:
    """Confirmed assignment, then clock -> check_in_clock, check-in and complete.

    Returns the setup_confirmed_assignment bundle with `assignment`, `hearing`
    and `pay_claim` re-read after completion.
    """
    bundle = setup_confirmed_assignment(
        hearing_overrides=hearing_overrides,
        assignment_overrides=assignment_overrides,
        config=config,
        interpreter_bundle=interpreter_bundle,
        target_tier=target_tier,
        config_kwargs=config_kwargs,
    )
    set_clock(check_in_clock)
    check_in_assignment(bundle["assignment"]["id"], bundle["interpreter"]["id"])
    assignment = complete_assignment(
        bundle["assignment"]["id"], bundle["interpreter"]["id"],
        actual_end_utc, one_way_miles,
    )
    bundle["assignment"] = assignment
    bundle["hearing"] = read_hearing(bundle["hearing"]["id"])
    bundle["pay_claim"] = read_pay_claim(bundle["pay_claim"]["id"])
    return bundle


def setup_submitted_pay_claim(check_in_clock: str,
                              actual_end_utc: str,
                              one_way_miles: Optional[float] = None,
                              **kwargs) -> Dict[str, Any]:
    """Served assignment whose FINALIZED claim has been submitted by its holder."""
    bundle = setup_served_assignment(
        check_in_clock, actual_end_utc, one_way_miles, **kwargs
    )
    bundle["pay_claim"] = submit_pay_claim(
        bundle["pay_claim"]["id"], bundle["interpreter"]["id"]
    )
    return bundle


# ---------------------------------------------------------------------------
# Tier 4 — discipline workflow (PRD §3.9)
# ---------------------------------------------------------------------------
def file_complaint(interpreter_id: str, assignment_id: Optional[str] = None,
                   filer_user_id: str = "qr-001", **overrides) -> Dict[str, Any]:
    """POST /complaints as a QualityReviewer whose id becomes filed_by_user_id."""
    payload = create_complaint_payload(interpreter_id, **overrides)
    if assignment_id is not None:
        payload["assignment_id"] = assignment_id
    return get_success_data(
        api_client.create_complaint(
            payload, make_quality_reviewer_headers(filer_user_id)
        )
    )


def review_complaint(complaint_id: str, recommendation: str = "SUBSTANTIATE",
                     findings: str = "Recording confirms the reported defect.",
                     reviewer_user_id: str = "qr-002") -> Dict[str, Any]:
    """POST /complaints/{id}/review as a reviewer who is not the filer."""
    return get_success_data(
        api_client.review_complaint(
            complaint_id,
            review_complaint_payload(recommendation=recommendation, findings=findings),
            make_quality_reviewer_headers(reviewer_user_id),
        )
    )


def adjudicate_complaint(complaint_id: str, disposition: str = "SUBSTANTIATED",
                         sanction_type: Optional[str] = None,
                         suspension_days: Optional[int] = None,
                         adjudicator_user_id: str = "pa-001") -> Dict[str, Any]:
    """POST /complaints/{id}/adjudicate as a ProgramAdmin."""
    return get_success_data(
        api_client.adjudicate_complaint(
            complaint_id,
            adjudicate_complaint_payload(disposition, sanction_type, suspension_days),
            make_program_admin_headers(adjudicator_user_id),
        )
    )


def appeal_complaint(complaint_id: str, interpreter_id: str,
                     grounds: str = "The record does not support the finding."
                     ) -> Dict[str, Any]:
    """POST /complaints/{id}/appeal as the sanctioned interpreter."""
    return get_success_data(
        api_client.appeal_complaint(
            complaint_id,
            appeal_complaint_payload(grounds=grounds),
            make_interpreter_headers(interpreter_id),
        )
    )


def decide_appeal(complaint_id: str, outcome: str = "UPHELD",
                  decider_user_id: str = "pa-002") -> Dict[str, Any]:
    """POST /complaints/{id}/appeal-decision as a ProgramAdmin who did not adjudicate."""
    return get_success_data(
        api_client.decide_appeal(
            complaint_id,
            appeal_decision_payload(outcome=outcome),
            make_program_admin_headers(decider_user_id),
        )
    )


def disciplinary_actions_for(interpreter_id: str) -> List[Dict[str, Any]]:
    """GET /disciplinary-actions?interpreter_id=..."""
    return get_success_data(
        api_client.list_disciplinary_actions(
            ADMIN, params={"interpreter_id": interpreter_id}
        )
    )


def disciplinary_actions_for_complaint(complaint_id: str) -> List[Dict[str, Any]]:
    """GET /disciplinary-actions?complaint_id=..."""
    return get_success_data(
        api_client.list_disciplinary_actions(
            ADMIN, params={"complaint_id": complaint_id}
        )
    )


def setup_reviewed_complaint(interpreter_id: str,
                             assignment_id: Optional[str] = None,
                             category: str = "ACCURACY",
                             severity: str = "MAJOR",
                             narrative: str = "Counsel reports whole answers omitted "
                                              "during direct examination.",
                             recommendation: str = "SUBSTANTIATE",
                             findings: str = "Recording confirms two omitted answers.",
                             filer_user_id: str = "qr-001",
                             reviewer_user_id: str = "qr-002",
                             ) -> Dict[str, Any]:
    """File a complaint and review it — REVIEWED and ready for adjudication."""
    complaint = file_complaint(
        interpreter_id, assignment_id, filer_user_id=filer_user_id,
        category=category, severity=severity, narrative=narrative,
    )
    return review_complaint(
        complaint["id"], recommendation=recommendation, findings=findings,
        reviewer_user_id=reviewer_user_id,
    )


def setup_sanction(interpreter_id: str,
                   sanction_type: str,
                   assignment_id: Optional[str] = None,
                   severity: str = "MAJOR",
                   category: str = "PROFESSIONALISM",
                   suspension_days: Optional[int] = None,
                   narrative: str = "Interpreter abandoned the courtroom mid-proceeding.",
                   filer_user_id: str = "qr-001",
                   reviewer_user_id: str = "qr-002",
                   adjudicator_user_id: str = "pa-001",
                   ) -> Dict[str, Any]:
    """File, review and substantiate one complaint, imposing `sanction_type`.

    Returns {"complaint", "action"} where action is the DisciplinaryAction row the
    adjudication created.
    """
    complaint = setup_reviewed_complaint(
        interpreter_id, assignment_id, category=category, severity=severity,
        narrative=narrative, recommendation="SUBSTANTIATE",
        filer_user_id=filer_user_id, reviewer_user_id=reviewer_user_id,
    )
    complaint = adjudicate_complaint(
        complaint["id"], "SUBSTANTIATED", sanction_type, suspension_days,
        adjudicator_user_id=adjudicator_user_id,
    )
    actions = disciplinary_actions_for_complaint(complaint["id"])
    return {"complaint": complaint, "action": actions[0] if actions else None}


# ---------------------------------------------------------------------------
# Tier 5 — clock-driven operations and reporting (PRD §3.4, §3.10)
# ---------------------------------------------------------------------------
def run_daily_sweep() -> Dict[str, Any]:
    """POST /ops/daily-sweep as a ProgramAdmin."""
    return get_success_data(api_client.run_daily_sweep(ADMIN))


def renew_credential(credential_id: str, cycle_credit_hours: float = 16.0
                     ) -> Dict[str, Any]:
    """POST /credentials/{id}/renew."""
    return get_success_data(
        api_client.renew_credential(
            credential_id, renew_credential_payload(cycle_credit_hours), CREDENTIALING
        )
    )


def revoke_credential(credential_id: str,
                      reason: str = "Sustained ethics violation.") -> Dict[str, Any]:
    """POST /credentials/{id}/revoke as a ProgramAdmin."""
    return get_success_data(
        api_client.revoke_credential(
            credential_id, revoke_credential_payload(reason), ADMIN
        )
    )


def create_unmet_need_report(courthouse_id: str, period_start: str, period_end: str
                             ) -> Dict[str, Any]:
    """POST /unmet-need-reports as a QualityReviewer."""
    return get_success_data(
        api_client.create_unmet_need_report(
            create_unmet_need_report_payload(courthouse_id, period_start, period_end),
            REVIEWER,
        )
    )


def setup_lapsed_credential(language_id: str,
                            lapse_clock: str,
                            target_tier: str = "CERTIFIED",
                            interpreter_overrides: Optional[Dict[str, Any]] = None,
                            ) -> Dict[str, Any]:
    """ACTIVE credential, then clock past expires_on and one sweep to LAPSED.

    Returns {"interpreter", "credential", "sweep"}.
    """
    bundle = setup_active_interpreter(
        language_id, target_tier=target_tier,
        interpreter_overrides=interpreter_overrides,
    )
    set_clock(lapse_clock)
    sweep = run_daily_sweep()
    return {
        "interpreter": read_interpreter(bundle["interpreter"]["id"]),
        "credential": read_credential(bundle["credential"]["id"]),
        "sweep": sweep,
    }


def list_assignments_for_hearing(hearing_id: str) -> List[Dict[str, Any]]:
    """GET /assignments?hearing_id=..."""
    return get_success_data(
        api_client.list_assignments(COORDINATOR, params={"hearing_id": hearing_id})
    )


def list_assignments_for_interpreter(interpreter_id: str) -> List[Dict[str, Any]]:
    """GET /assignments?interpreter_id=..."""
    return get_success_data(
        api_client.list_assignments(COORDINATOR, params={"interpreter_id": interpreter_id})
    )


def list_complaints_for_interpreter(interpreter_id: str) -> List[Dict[str, Any]]:
    """GET /complaints?interpreter_id=..."""
    return get_success_data(
        api_client.list_complaints(REVIEWER, params={"interpreter_id": interpreter_id})
    )


def eligible_interpreters(hearing_id: str,
                          params: Optional[Dict[str, Any]] = None
                          ) -> List[Dict[str, Any]]:
    """GET /hearings/{id}/eligible-interpreters — the ranked pool."""
    return get_success_data(
        api_client.list_eligible_interpreters(hearing_id, COORDINATOR, params=params)
    )
