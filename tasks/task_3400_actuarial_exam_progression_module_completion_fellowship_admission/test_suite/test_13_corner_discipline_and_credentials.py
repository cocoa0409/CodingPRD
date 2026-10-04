"""Corner queue — discipline process and credential admission.

Suspension auto-lift at the boundary, non-cascading resolutions, resolved
lockdown (PRD §3.9); ASA/FSA synchronous evaluation and tier advancement
(PRD §3.9).
"""
from datetime import datetime

import pytest

from test_helpers import (
    ApiErrorId,
    CLOCK_SESSION_HELD,
    CLOCK_SUSPENSION_DAY,
    CLOCK_SUSPENSION_LIFT_EXACT,
    CLOCK_SUSPENSION_LIFT_MINUS_1,
    DEFICIENCIES_ASA_BARE,
    DEFICIENCIES_FSA_NO_ASA,
    DISCIPLINE_BOARD,
    REGISTRAR,
    SEVERITY_LOW,
    SEVERITY_MINOR,
    SUSPENSION_DAYS,
    create_credential_application_payload,
    file_case,
    get_candidate,
    get_success_data,
    make_active_exam,
    make_candidate,
    make_candidate_headers,
    sanction_case,
    sanction_discipline_case_payload,
    set_clock,
    setup_associate,
    setup_fellow,
    setup_registered,
    validate_error,
    validate_success,
)


def _utc(iso):
    return datetime.fromisoformat(iso.replace("Z", "+00:00"))


def test_suspension_auto_lift_at_boundary(api):
    """PRD §3.9: "The suspension lifts itself: when a clock sweep finds the
    current reading has reached a suspended candidate's `suspended_until` —
    the boundary inclusive — the candidate returns `SUSPENDED` → `ACTIVE`,
    `suspended_until` is cleared to null, and the candidate's `version`
    increments. Cancelled registrations are not restored by reinstatement."

    Design: Corner/state_machines/suspension_auto_lift_at_boundary
    """
    candidate = make_candidate(api)
    case = file_case(api, candidate["id"], charge="Disruptive conduct",
                     severity=SEVERITY_LOW)
    set_clock(api, CLOCK_SUSPENSION_DAY)
    sanction_case(api, case["id"], resolution="SUSPENSION",
                  suspension_days=SUSPENSION_DAYS)

    early = set_clock(api, CLOCK_SUSPENSION_LIFT_MINUS_1)
    assert early["suspensions_lifted"] == 0
    assert get_candidate(api, candidate["id"])["status"] == "SUSPENDED"

    boundary = set_clock(api, CLOCK_SUSPENSION_LIFT_EXACT)
    assert boundary["suspensions_lifted"] == 1
    lifted = get_candidate(api, candidate["id"])
    assert lifted["status"] == "ACTIVE"
    assert lifted["suspended_until"] is None


def test_discipline_dismissal_no_cascade_and_resolved_lock(api):
    """PRD §3.9: "`DISMISSED` and `REPRIMAND` mutate no candidate state at
    all."
    PRD §3.9: "Only a `FILED` case can be resolved; sanctioning an
    already-resolved case is rejected with `ERR_DISCIPLINE_ALREADY_RESOLVED`."

    Design: Corner/state_machines/discipline_dismissal_no_cascade_and_resolved_lock
    """
    ctx = setup_registered(api, num_candidates=1)
    candidate = ctx["candidates"][0]
    case = file_case(api, candidate["id"], charge="Unsubstantiated complaint",
                     severity=SEVERITY_MINOR)
    resolved = sanction_case(api, case["id"], resolution="DISMISSED")
    assert resolved["status"] == "RESOLVED"
    assert resolved["resolution"] == "DISMISSED"

    assert get_candidate(api, candidate["id"])["status"] == "ACTIVE"
    rows = get_success_data(api.list_candidate_registrations(candidate["id"], REGISTRAR))
    assert rows[0]["logistics_status"] == "REGISTERED"

    resp = api.sanction_discipline_case(
        case["id"], sanction_discipline_case_payload("REPRIMAND"), DISCIPLINE_BOARD)
    validate_error(resp, ApiErrorId.ERR_DISCIPLINE_ALREADY_RESOLVED)


def test_discipline_reprimand_keeps_candidate_active(api):
    """PRD §3.9: "`DISMISSED` and `REPRIMAND` mutate no candidate state at
    all."

    Design: Corner/state_machines/discipline_reprimand_keeps_candidate_active
    """
    ctx = setup_registered(api, num_candidates=1)
    candidate = ctx["candidates"][0]
    case = file_case(api, candidate["id"], charge="Administrative lapse",
                     severity=SEVERITY_MINOR)
    resolved = sanction_case(api, case["id"], resolution="REPRIMAND")
    assert resolved["status"] == "RESOLVED"
    assert resolved["resolution"] == "REPRIMAND"

    assert get_candidate(api, candidate["id"])["status"] == "ACTIVE"
    rows = get_success_data(api.list_candidate_registrations(candidate["id"], REGISTRAR))
    assert rows[0]["logistics_status"] == "REGISTERED"


def test_credential_asa_deficiency_listing(api):
    """PRD §3.9: "For the `ASA`, the evaluation collects, in canonical order:
    `MISSING_PRELIM_CREDIT` when any exam flagged `is_prelim` of the `ACTIVE`
    syllabus lacks a credit — a direct `PASS` or one mapped through transition
    credit — a deficiency also emitted when no syllabus version is `ACTIVE` at
    all; `MISSING_VEE_TOPIC` when any of the three VEE topics lacks an
    `APPROVED` submission; and `INSUFFICIENT_TOTAL_CREDITS` when the
    candidate's earned exam credit hours plus transfer credit hours capped at
    fifteen fall below a total of ten."
    PRD §3.9: "Every application stamps the candidate's `last_evaluated_at`
    with the current logical clock and increments the candidate's `version` —
    even when the application is denied."

    Design: Corner/state_machines/credential_asa_deficiency_listing
    """
    make_active_exam(api)
    candidate = make_candidate(api)
    application = validate_success(api.create_credential_application(
        create_credential_application_payload("ASA", candidate["version"]),
        make_candidate_headers(candidate["id"])), 201)
    assert application["status"] == "DENIED_DEFICIENCY"
    assert application["deficiency_codes"] == DEFICIENCIES_ASA_BARE

    refreshed = get_candidate(api, candidate["id"])
    # The denied evaluation still stamps the record: exactly one version bump.
    assert refreshed["version"] == candidate["version"] + 1
    assert refreshed["membership_tier"] == "CANDIDATE"
    assert refreshed["last_evaluated_at"] is not None


def test_credential_fsa_requires_asa_first(api):
    """PRD §3.9: "For the `FSA`, it collects: `MISSING_ASA` when the
    candidate's tier is still `CANDIDATE`; `TRACK_INCOMPLETE` when the
    candidate holds no `COMPLETED` track enrollment; `MISSING_PROJECT_PASS`
    when the candidate holds no project assessment whose `result` is `PASS`;
    and `MISSING_PROFESSIONALISM` when the candidate holds no course
    attendance whose status is `ATTENDED`."

    Design: Corner/state_machines/credential_fsa_requires_asa_first
    """
    candidate = make_candidate(api)
    application = validate_success(api.create_credential_application(
        create_credential_application_payload("FSA", candidate["version"]),
        make_candidate_headers(candidate["id"])), 201)
    assert application["status"] == "DENIED_DEFICIENCY"
    assert application["deficiency_codes"] == DEFICIENCIES_FSA_NO_ASA


def test_credential_already_held(api):
    """PRD §3.9: "The candidate must be `ACTIVE`, and the credential must not
    already be held — applying for `ASA` while `ASSOCIATE` or `FELLOW`, or for
    `FSA` while `FELLOW`, is rejected with `ERR_CREDENTIAL_ALREADY_HELD`."

    Design: Corner/state_machines/credential_already_held
    """
    candidate = setup_associate(api)["candidate"]
    assert candidate["membership_tier"] == "ASSOCIATE"
    resp = api.create_credential_application(
        create_credential_application_payload("ASA", candidate["version"]),
        make_candidate_headers(candidate["id"]))
    validate_error(resp, ApiErrorId.ERR_CREDENTIAL_ALREADY_HELD)


def test_fsa_full_progression_happy_path(api):
    """PRD §3.9: "an empty list approves, a non-empty list denies."
    PRD §3.9: "An approved application additionally advances the membership
    ladder: `CANDIDATE` → `ASSOCIATE` stamps `associate_admitted_at`, and
    `ASSOCIATE` → `FELLOW` stamps `fellow_admitted_at`, the fellowship
    admission."

    Design: Corner/endpoints/fsa_full_progression_happy_path
    """
    ctx = setup_fellow(api)
    application = ctx["application"]
    assert application["status"] == "APPROVED"
    assert application["deficiency_codes"] == []

    candidate = ctx["candidate"]
    assert candidate["membership_tier"] == "FELLOW"
    assert _utc(candidate["fellow_admitted_at"]) == _utc(CLOCK_SESSION_HELD)

    enrollment = ctx["enrollment"]
    assert enrollment["status"] == "COMPLETED"
    assert enrollment["completion_pct"] == pytest.approx(100.0, abs=0.005)
    assert ctx["project"]["result"] == "PASS"
    assert ctx["attendance"]["status"] == "ATTENDED"
