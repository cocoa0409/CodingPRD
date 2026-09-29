"""Each catalogued error is reached by its own route and told apart from its neighbours.

The point of these tests is discrimination rather than mere failure: an absent
identity must not be confused with a forbidden one, a missing row must name the
entity that was missing, and an invalid-state refusal must name the machine that
refused.  Where two gates hold at once the numbered order of PRD 2.8 decides.
"""

from __future__ import annotations

from typing import Any, Dict, Sequence

from prd_bench_local_runner.testing import (
    get_success_data,
    validate_error,
    validate_success,
)

from test_helpers.api_client import ApiClient
from test_helpers.api_errors import ApiErrorId
from test_helpers.assertions import assert_counters, assert_state
from test_helpers.constants import CLOCK_EPOCH, UNKNOWN_UUID
from test_helpers.test_users import (
    COMPLIANCE_AUDITOR_HEADERS,
    NGB_ADMIN_HEADERS,
    NO_IDENTITY_HEADERS,
    OFFICER_ADJUDICATOR_HEADERS,
    OFFICER_CLOSER_HEADERS,
    OFFICER_IMPOSE_HEADERS,
    OFFICER_INTAKE_HEADERS,
    SCREENING_VENDOR_HEADERS,
    make_club_admin_headers,
    make_headers_with_role,
)

ALPHA_AQUATICS = {
    "name": "Alpha Aquatics",
    "state_code": "CA",
    "roster_size_attested": 3,
    "minor_athlete_program": True,
    "initial_escrow_cents": 500000,
}
SS101 = {
    "code": "SS101",
    "title": "Abuse Prevention Core",
    "validity_days": 365,
    "delivery_mode": "ONLINE",
    "required_for_tiers": ["TIER_1", "TIER_2", "TIER_3"],
    "pass_score": 80,
}


def _epoch(api: ApiClient) -> None:
    get_success_data(api.set_clock(CLOCK_EPOCH, NGB_ADMIN_HEADERS))


def _club(api: ApiClient, payload: Dict[str, Any] = ALPHA_AQUATICS) -> Dict[str, Any]:
    return get_success_data(api.charter_club(payload, NGB_ADMIN_HEADERS), 201)


def _member(
    api: ApiClient,
    club_id: str,
    name: str,
    email: str,
    dob: str,
    role_type: str = "VOLUNTEER",
    contact: bool = False,
    codes: Sequence[str] = ("CA",),
) -> Dict[str, Any]:
    return get_success_data(
        api.register_member(
            {
                "club_id": club_id,
                "full_name": name,
                "email": email,
                "role_type": role_type,
                "has_minor_athlete_contact": contact,
                "date_of_birth": dob,
                "jurisdiction_codes": list(codes),
            },
            make_club_admin_headers(club_id),
        ),
        201,
    )


def _live_club_version(api: ApiClient, club_id: str) -> int:
    return validate_success(api.get_club(club_id, NGB_ADMIN_HEADERS))["version"]


def test_an_absent_identity_and_an_undeclared_role_are_both_unauthenticated(
    api: ApiClient,
) -> None:
    """Priority 1 runs before the endpoint's own role list, so neither request reaches authorization.

    PRD 2.8 says:
    "Both `X-User-ID` and `X-User-Role` are present and non-empty and the role is one of the six declared roles — otherwise `ERR_UNAUTHENTICATED`."
    "The acting role is authorized for the called endpoint — otherwise `ERR_UNAUTHORIZED`."
    "Because many operations are guarded by several rules at once, the platform evaluates its checks in one fixed order and reports **the first failure only**."

    Design: Corner/errors/missing_and_unknown_role_headers_are_unauthenticated
    """
    _epoch(api)
    club = _club(api)

    # Neither header present at all.
    validate_error(
        api.get_club(club["id"], NO_IDENTITY_HEADERS),
        ApiErrorId.UNAUTHENTICATED,
        401,
    )
    # A well-formed header naming a role the platform never declared.
    validate_error(
        api.get_club(club["id"], make_headers_with_role("outside-auditor", "Auditor")),
        ApiErrorId.UNAUTHENTICATED,
        401,
    )
    # The identical request with a declared role is answered.
    reread = validate_success(api.get_club(club["id"], NGB_ADMIN_HEADERS))
    assert reread["id"] == club["id"], (
        f"the authenticated read returned {reread['id']}, not {club['id']}"
    )


def test_all_twelve_not_found_codes_are_reachable_and_name_the_entity_that_was_missing(
    api: ApiClient,
) -> None:
    """Eleven come from a path-templated id and the twelfth from a natural key in the body.

    PRD 2.8 says:
    "Every path-templated resource id resolves to an existing row, validated left to right, so an outer segment's 404 is reported before an inner one's — `ERR_CLUB_NOT_FOUND`, `ERR_MEMBER_NOT_FOUND`, `ERR_SCREENING_ORDER_NOT_FOUND`, `ERR_TRAINING_ASSIGNMENT_NOT_FOUND`, `ERR_COACH_ASSIGNMENT_NOT_FOUND`, `ERR_INVESTIGATING_BODY_NOT_FOUND`, `ERR_CASE_NOT_FOUND`, `ERR_INTERIM_MEASURE_NOT_FOUND`, `ERR_CLUB_AUDIT_NOT_FOUND`, `ERR_AUDIT_FINDING_NOT_FOUND`, or `ERR_ROOM_STAY_NOT_FOUND` as appropriate."
    "Every id or natural key named in the body resolves — a `club_id`, a `member_id`, an `investigating_body_id`, each entry of `sampled_member_ids`, and a `course_code` against a published course — otherwise `ERR_CLUB_NOT_FOUND`, `ERR_MEMBER_NOT_FOUND`, `ERR_INVESTIGATING_BODY_NOT_FOUND`, or `ERR_TRAINING_COURSE_NOT_FOUND`."

    PRD 3.4 says:
    "Assigning a course to a member names the `member_id`, the `course_code` — which must equal the `code` of a course that actually exists, else `ERR_TRAINING_COURSE_NOT_FOUND` — and a `due_at` deadline."

    Design: Corner/errors/every_not_found_error_in_the_catalog_is_reachable
    """
    _epoch(api)
    club = _club(api)
    headers = make_club_admin_headers(club["id"])
    member = _member(api, club["id"], "Nils Frey", "nils.frey@alpha.test", "1991-08-30")

    validate_error(
        api.get_club(UNKNOWN_UUID, NGB_ADMIN_HEADERS),
        ApiErrorId.CLUB_NOT_FOUND,
        404,
    )
    validate_error(
        api.get_member(UNKNOWN_UUID, NGB_ADMIN_HEADERS),
        ApiErrorId.MEMBER_NOT_FOUND,
        404,
    )
    validate_error(
        api.post_screening_result(
            UNKNOWN_UUID, {"vendor_disposition": "NO_RECORD"}, SCREENING_VENDOR_HEADERS
        ),
        ApiErrorId.SCREENING_ORDER_NOT_FOUND,
        404,
    )
    validate_error(
        api.start_training(UNKNOWN_UUID, headers),
        ApiErrorId.TRAINING_ASSIGNMENT_NOT_FOUND,
        404,
    )
    validate_error(
        api.get_coach_assignment(UNKNOWN_UUID, NGB_ADMIN_HEADERS),
        ApiErrorId.COACH_ASSIGNMENT_NOT_FOUND,
        404,
    )
    validate_error(
        api.get_investigating_body(UNKNOWN_UUID, NGB_ADMIN_HEADERS),
        ApiErrorId.INVESTIGATING_BODY_NOT_FOUND,
        404,
    )
    validate_error(
        api.get_case(UNKNOWN_UUID, OFFICER_INTAKE_HEADERS),
        ApiErrorId.CASE_NOT_FOUND,
        404,
    )
    validate_error(
        api.get_interim_measure(UNKNOWN_UUID, OFFICER_INTAKE_HEADERS),
        ApiErrorId.INTERIM_MEASURE_NOT_FOUND,
        404,
    )
    validate_error(
        api.write_finding(
            UNKNOWN_UUID,
            {
                "finding_code": "RECORDS_INCOMPLETE",
                "severity": "MINOR",
                "is_repeat": False,
            },
            COMPLIANCE_AUDITOR_HEADERS,
        ),
        ApiErrorId.CLUB_AUDIT_NOT_FOUND,
        404,
    )
    validate_error(
        api.get_audit_finding(UNKNOWN_UUID, COMPLIANCE_AUDITOR_HEADERS),
        ApiErrorId.AUDIT_FINDING_NOT_FOUND,
        404,
    )
    validate_error(
        api.cancel_room_stay(UNKNOWN_UUID, {"reason": "no such stay"}, headers),
        ApiErrorId.ROOM_STAY_NOT_FOUND,
        404,
    )
    # The twelfth is a natural key carried in the body: the member resolves and
    # only the course code does not.
    validate_error(
        api.assign_training(
            {
                "member_id": member["id"],
                "course_code": "SS999",
                "due_at": "2026-09-01T00:00:00Z",
            },
            headers,
        ),
        ApiErrorId.TRAINING_COURSE_NOT_FOUND,
        404,
    )


def test_four_machines_refuse_in_one_fixture_and_each_names_its_own_invalid_state(
    api: ApiClient,
) -> None:
    """One club, one member, one case and one audit produce four distinct invalid-state codes.

    PRD 2.8 says:
    "The addressed resource is in a state from which the requested transition exists — otherwise `ERR_SCREENING_ORDER_INVALID_STATE`, `ERR_TRAINING_ASSIGNMENT_INVALID_STATE`, `ERR_COACH_ASSIGNMENT_INVALID_STATE`, `ERR_CASE_INVALID_STATE`, `ERR_INTERIM_MEASURE_INVALID_STATE`, `ERR_AUDIT_INVALID_STATE`, `ERR_FINDING_INVALID_STATE`, `ERR_ROOM_STAY_INVALID_STATE`, or `ERR_MEMBER_INVALID_STATE`."

    PRD 3.4 says:
    "Completion requires status `IN_PROGRESS` and a `score` between 0 and 100 that reaches or exceeds the referenced course's `pass_score`; a score below the pass mark is not a completion."

    PRD 3.5 says:
    "A renewal attempted from `PENDING`, `SUSPENDED`, or `REVOKED` has no transition and is refused with `ERR_MEMBER_INVALID_STATE`."

    PRD 3.8 says:
    "Routing a case that is not in `INTAKE_REVIEW` is refused with `ERR_CASE_INVALID_STATE`."
    "Administrative closure touches nothing else: no investigating body's `open_case_count` moves, because the case was never routed, and any interim measure imposed during intake survives the closure untouched."

    PRD 3.9 says:
    "Finalize is available only from `SAMPLED` and moves the audit `SAMPLED → FINDINGS_ISSUED` with `finalized_at` stamped from the clock."

    Design: Corner/errors/cheap_invalid_state_errors_are_distinguishable_per_entity
    """
    _epoch(api)
    club = _club(api)
    headers = make_club_admin_headers(club["id"])
    get_success_data(api.publish_course(SS101, NGB_ADMIN_HEADERS), 201)
    member = _member(api, club["id"], "Stu Tang", "stu.tang@alpha.test", "1990-09-01")
    assert_state(member, "membership_status", "PENDING")
    assignment = get_success_data(
        api.assign_training(
            {
                "member_id": member["id"],
                "course_code": "SS101",
                "due_at": "2026-09-01T00:00:00Z",
            },
            headers,
        ),
        201,
    )
    case = get_success_data(
        api.file_case(
            {
                "club_id": club["id"],
                "reported_member_id": member["id"],
                "allegation_category": "POLICY_VIOLATION",
                "reporter_kind": "PARENT",
                "narrative": "matter withdrawn by the reporter",
                "occurred_at": "2026-07-31T23:00:00Z",
            },
            OFFICER_INTAKE_HEADERS,
        ),
        201,
    )
    closed = validate_success(
        api.close_case(
            case["id"], {"closure_reason": "NO_JURISDICTION"}, OFFICER_CLOSER_HEADERS
        )
    )
    assert_state(closed, "status", "CLOSED_ADMINISTRATIVE")
    body = get_success_data(
        api.register_investigating_body(
            {
                "name": "Policy Panel",
                "scope_categories": ["POLICY_VIOLATION"],
                "max_open_cases": 5,
                "intake_status": "ACCEPTING",
            },
            NGB_ADMIN_HEADERS,
        ),
        201,
    )
    audit = get_success_data(
        api.open_club_audit(
            {
                "club_id": club["id"],
                "audit_period_start": "2026-01-01T00:00:00Z",
                "audit_period_end": "2026-06-30T00:00:00Z",
                "score_variant": "SELF_ATTESTED",
                "sampled_member_ids": [member["id"]],
            },
            COMPLIANCE_AUDITOR_HEADERS,
        ),
        201,
    )
    finalized = validate_success(
        api.finalize_club_audit(audit["id"], {}, COMPLIANCE_AUDITOR_HEADERS)
    )
    assert_state(finalized, "status", "FINDINGS_ISSUED")

    # The assignment was never started, so there is no completion transition.
    validate_error(
        api.complete_training(assignment["id"], {"score": 90}, headers),
        ApiErrorId.TRAINING_ASSIGNMENT_INVALID_STATE,
        409,
    )
    validate_error(
        api.renew_membership(member["id"], {"attestation_signed": True}, headers),
        ApiErrorId.MEMBER_INVALID_STATE,
        409,
    )
    validate_error(
        api.route_case(
            case["id"], {"investigating_body_id": body["id"]}, OFFICER_INTAKE_HEADERS
        ),
        ApiErrorId.CASE_INVALID_STATE,
        409,
    )
    validate_error(
        api.finalize_club_audit(audit["id"], {}, COMPLIANCE_AUDITOR_HEADERS),
        ApiErrorId.AUDIT_INVALID_STATE,
        409,
    )

    still_assigned = validate_success(
        api.get_training_assignment(assignment["id"], headers)
    )
    assert_state(still_assigned, "status", "ASSIGNED")
    untouched_body = validate_success(
        api.get_investigating_body(body["id"], NGB_ADMIN_HEADERS)
    )
    assert_counters(untouched_body, open_case_count=0)


def test_a_lifted_measure_and_a_cascade_terminated_placement_each_refuse_the_next_transition(
    api: ApiClient,
) -> None:
    """Both codes are reachable only after a prior cascade has moved the row out of reach.

    PRD 3.8 says:
    "An officer supplies a `reason`, retained as `lift_reason`, against a measure in status `ACTIVE` whose case is still in `INTAKE_REVIEW` or `ROUTED`; a measure that is not `ACTIVE` is refused with `ERR_INTERIM_MEASURE_INVALID_STATE`."
    "The measure moves `ACTIVE → LIFTED` with `lifted_at` stamped from the clock."

    PRD 3.3 says:
    "Every coach placement that member holds in status `PENDING`, `ACTIVE`, or `SUSPENDED` moves to `TERMINATED` with `suspended_reason` recorded as `SCREENING_DISQUALIFICATION`."

    PRD 3.6 says:
    "The club administrator activates the placement supplying only `expected_member_version`, and six conditions must hold: the placement must be in status `PENDING`, else `ERR_COACH_ASSIGNMENT_INVALID_STATE`; the pinned member version must match, else `ERR_STALE_MEMBER_VERSION`; the placement's club must be at posture `OPEN`, so both `RESTRICTED` and `FROZEN` block activation; the member must not be `DISQUALIFIED`; the member must be under no permanent and no active restriction, else `ERR_CONTACT_NOT_PERMITTED`; and the member's `screening_status` must be `CLEARED` and `training_status` must be `CURRENT`, reported as `ERR_SCREENING_NOT_CURRENT` and `ERR_TRAINING_NOT_CURRENT` respectively."

    PRD 2.8 says:
    "The addressed resource is in a state from which the requested transition exists — otherwise `ERR_SCREENING_ORDER_INVALID_STATE`, `ERR_TRAINING_ASSIGNMENT_INVALID_STATE`, `ERR_COACH_ASSIGNMENT_INVALID_STATE`, `ERR_CASE_INVALID_STATE`, `ERR_INTERIM_MEASURE_INVALID_STATE`, `ERR_AUDIT_INVALID_STATE`, `ERR_FINDING_INVALID_STATE`, `ERR_ROOM_STAY_INVALID_STATE`, or `ERR_MEMBER_INVALID_STATE`."
    "The subject member's `screening_status` is not `DISQUALIFIED` — otherwise `ERR_MEMBER_DISQUALIFIED`."

    Design: Corner/errors/measure_and_placement_invalid_state_errors_are_reachable
    """
    _epoch(api)
    club = _club(api, dict(ALPHA_AQUATICS, roster_size_attested=4))
    headers = make_club_admin_headers(club["id"])
    measured = _member(
        api,
        club["id"],
        "Lou Mercer",
        "lou.mercer@alpha.test",
        "1983-10-02",
        role_type="OFFICIAL",
        contact=True,
    )
    body = get_success_data(
        api.register_investigating_body(
            {
                "name": "Conduct Panel",
                "scope_categories": ["POLICY_VIOLATION"],
                "max_open_cases": 5,
                "intake_status": "ACCEPTING",
            },
            NGB_ADMIN_HEADERS,
        ),
        201,
    )
    case = get_success_data(
        api.file_case(
            {
                "club_id": club["id"],
                "reported_member_id": measured["id"],
                "allegation_category": "POLICY_VIOLATION",
                "reporter_kind": "MANDATORY_REPORTER",
                "narrative": "electronic communication policy breach",
                "occurred_at": "2026-07-31T23:00:00Z",
            },
            OFFICER_INTAKE_HEADERS,
        ),
        201,
    )
    validate_success(
        api.route_case(
            case["id"], {"investigating_body_id": body["id"]}, OFFICER_INTAKE_HEADERS
        )
    )
    measure = get_success_data(
        api.impose_interim_measure(
            case["id"],
            {
                "member_id": measured["id"],
                "measure_kind": "NO_CONTACT_DIRECTIVE",
                "effective_from": "2026-08-01T00:00:00Z",
                "effective_to": "2026-09-01T00:00:00Z",
                "expected_member_version": validate_success(
                    api.get_member(measured["id"], NGB_ADMIN_HEADERS)
                )["version"],
            },
            OFFICER_IMPOSE_HEADERS,
        ),
        201,
    )
    lifted = validate_success(
        api.lift_interim_measure(
            measure["id"],
            {"reason": "directive satisfied by the club's written plan"},
            OFFICER_IMPOSE_HEADERS,
        )
    )
    assert_state(lifted, "status", "LIFTED")

    terminated_member = _member(
        api, club["id"], "Tess Moss", "tess.moss@alpha.test", "1988-11-03"
    )
    placement = get_success_data(
        api.create_coach_assignment(
            {
                "member_id": terminated_member["id"],
                "club_id": club["id"],
                "team_name": "Junior Squad",
                "season_start": "2026-09-01T00:00:00Z",
                "season_end": "2027-05-31T00:00:00Z",
            },
            headers,
        ),
        201,
    )
    assert_state(placement, "status", "PENDING")
    order = get_success_data(
        api.order_screening(
            terminated_member["id"],
            {
                "expedited": False,
                "expected_club_version": _live_club_version(api, club["id"]),
            },
            headers,
        ),
        201,
    )
    get_success_data(
        api.post_screening_result(
            order["id"], {"vendor_disposition": "RECORD_FOUND"}, SCREENING_VENDOR_HEADERS
        )
    )
    validate_success(
        api.adjudicate_screening_order(
            order["id"],
            {
                "disposition": "DISQUALIFYING_RECORD",
                "rationale": "conviction appears on the disqualifying criteria list",
            },
            OFFICER_ADJUDICATOR_HEADERS,
        )
    )
    cascaded = validate_success(api.get_coach_assignment(placement["id"], NGB_ADMIN_HEADERS))
    assert_state(cascaded, "status", "TERMINATED")
    assert_state(cascaded, "suspended_reason", "SCREENING_DISQUALIFICATION")
    disqualified = validate_success(
        api.get_member(terminated_member["id"], NGB_ADMIN_HEADERS)
    )
    assert_state(disqualified, "screening_status", "DISQUALIFIED")

    # A measure that is no longer ACTIVE cannot be lifted a second time.
    validate_error(
        api.lift_interim_measure(
            measure["id"], {"reason": "duplicate lift request"}, OFFICER_IMPOSE_HEADERS
        ),
        ApiErrorId.INTERIM_MEASURE_INVALID_STATE,
        409,
    )
    # The placement's own state is checked at priority 11, above the priority 13
    # disqualification that also holds for this member.
    validate_error(
        api.activate_coach_assignment(
            placement["id"],
            {"expected_member_version": disqualified["version"]},
            headers,
        ),
        ApiErrorId.COACH_ASSIGNMENT_INVALID_STATE,
        409,
    )

    reread_measure = validate_success(
        api.get_interim_measure(measure["id"], OFFICER_IMPOSE_HEADERS)
    )
    assert reread_measure["lift_reason"] == "directive satisfied by the club's written plan", (
        f"the first lift's reason was not retained: {reread_measure['lift_reason']!r}"
    )
    reread_placement = validate_success(
        api.get_coach_assignment(placement["id"], NGB_ADMIN_HEADERS)
    )
    assert reread_placement["activated_at"] is None, (
        f"the refused activation stamped a time: {reread_placement['activated_at']!r}"
    )
