"""Initial states, invalid transitions, terminal lockdown and compensating moves.

Each test drives one row to a named state and then asks the platform for a
transition that either exists or does not.  The rows that do not move are as
interesting as the rows that do: an administrative closure leaves the
investigating body alone, and a waived finding refuses every later decision.
"""

from __future__ import annotations

from typing import Any, Dict, Iterable

from prd_bench_local_runner.testing import (
    get_success_data,
    validate_error,
    validate_error_is_one_of,
    validate_paginated,
    validate_success,
)

from test_helpers.api_client import ApiClient
from test_helpers.api_errors import ApiErrorId
from test_helpers.assertions import (
    assert_counters,
    assert_instant_equals,
    assert_state,
    assert_version_is,
)
from test_helpers.constants import CLOCK_EPOCH, CLOCK_EPOCH_MS
from test_helpers.test_users import (
    COMPLIANCE_AUDITOR_HEADERS,
    NGB_ADMIN_HEADERS,
    OFFICER_ADJUDICATOR_HEADERS,
    OFFICER_CLOSER_HEADERS,
    OFFICER_IMPOSE_HEADERS,
    OFFICER_INTAKE_HEADERS,
    SCREENING_VENDOR_HEADERS,
    make_club_admin_headers,
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
BODY_PHYSICAL = {
    "name": "Center for SafeSport",
    "scope_categories": ["PHYSICAL_ABUSE"],
    "max_open_cases": 5,
    "intake_status": "ACCEPTING",
}
BODY_EMOTIONAL = {
    "name": "Center for SafeSport",
    "scope_categories": ["EMOTIONAL_MISCONDUCT"],
    "max_open_cases": 5,
    "intake_status": "ACCEPTING",
}
MINOR_STAY = {
    "occupant_kind": "MINOR_ATHLETE",
    "trip_label": "WINTER_CAMP",
    "room_number": "110",
    "check_in": "2026-12-20T15:00:00Z",
    "check_out": "2026-12-22T11:00:00Z",
    "minor_athlete_age": 13,
}


def _epoch(api: ApiClient) -> None:
    get_success_data(api.set_clock(CLOCK_EPOCH, NGB_ADMIN_HEADERS))


def _club(api: ApiClient) -> Dict[str, Any]:
    _epoch(api)
    return get_success_data(api.charter_club(ALPHA_AQUATICS, NGB_ADMIN_HEADERS), 201)


def _member(
    api: ApiClient,
    club_id: str,
    name: str,
    email: str,
    dob: str,
    role_type: str = "VOLUNTEER",
    contact: bool = False,
    codes: Iterable[str] = ("CA",),
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
    club = get_success_data(api.get_club(club_id, make_club_admin_headers(club_id)))
    return club["version"]


def _live_member_version(api: ApiClient, member_id: str, headers: Dict[str, str]) -> int:
    return get_success_data(api.get_member(member_id, headers))["version"]


def _order(api: ApiClient, club_id: str, member_id: str) -> Dict[str, Any]:
    return get_success_data(
        api.order_screening(
            member_id,
            {
                "expedited": False,
                "expected_club_version": _live_club_version(api, club_id),
            },
            make_club_admin_headers(club_id),
        ),
        201,
    )


def _clear_screening(api: ApiClient, club_id: str, member_id: str) -> Dict[str, Any]:
    """Take the member's screening dimension all the way to CLEARED (PRD 3.3)."""
    order = _order(api, club_id, member_id)
    get_success_data(
        api.post_screening_result(
            order["id"], {"vendor_disposition": "NO_RECORD"}, SCREENING_VENDOR_HEADERS
        )
    )
    return get_success_data(
        api.adjudicate_screening_order(
            order["id"],
            {"disposition": "CLEAR", "rationale": "registry return carried no records"},
            OFFICER_ADJUDICATOR_HEADERS,
        )
    )


def _complete_training(api: ApiClient, club_id: str, member_id: str) -> Dict[str, Any]:
    """Publish SS101, assign it and carry it to COMPLETED (PRD 3.4)."""
    headers = make_club_admin_headers(club_id)
    get_success_data(api.publish_course(SS101, NGB_ADMIN_HEADERS), 201)
    assignment = get_success_data(
        api.assign_training(
            {
                "member_id": member_id,
                "course_code": "SS101",
                "due_at": "2026-09-01T00:00:00Z",
            },
            headers,
        ),
        201,
    )
    get_success_data(api.start_training(assignment["id"], headers))
    return get_success_data(
        api.complete_training(assignment["id"], {"score": 92}, headers)
    )


def test_a_new_order_is_ordered_at_version_one_and_moves_only_the_screening_dimension(
    api: ApiClient,
) -> None:
    """The order is born ORDERED with nothing stamped yet, and membership stays PENDING.

    PRD 3.2 says:
    "A successful order is written in status `ORDERED` with all four money fields stamped, the club's `escrow_balance_cents` is debited by `charged_cents`, the club's `version` advances by one, and the member's screening dimension moves `UNSCREENED → SCREENING_ORDERED` (or `CLEARED → SCREENING_ORDERED`, or `EXPIRED → SCREENING_ORDERED`, all three governed by the identical preconditions and side effects)."
    "The member's `contact_eligibility` is re-derived — a member in `SCREENING_ORDERED` is never `ELIGIBLE` — and the member's `version` advances by one."

    PRD 3.3 says:
    "The order moves `ORDERED → RESULT_RETURNED`, `returned_at` is stamped with the logical clock, and the member's `version` advances by one."
    "On the two clearing dispositions the order moves `RESULT_RETURNED → ADJUDICATED`, `adjudicated_at` is stamped with the clock, and the order's `expires_at` is set to `adjudicated_at` plus 730 days — the two-year screening validity period."

    PRD 3.1 says:
    "A newly registered member starts at `screening_status` of `UNSCREENED` on the screening dimension and `membership_status` of `PENDING` on the membership dimension, with `training_status` of `NEVER` and `contact_eligibility` of `RESTRICTED`."

    Design: Corner/state_machines/screening_order_starts_in_ordered_and_moves_the_member_dimension
    """
    club = _club(api)
    headers = make_club_admin_headers(club["id"])
    member = _member(api, club["id"], "Ida Stern", "ida.stern@alpha.test", "1991-01-07")

    order = validate_success(
        api.order_screening(
            member["id"],
            {
                "expedited": False,
                "expected_club_version": _live_club_version(api, club["id"]),
            },
            headers,
        ),
        201,
    )

    assert_state(order, "status", "ORDERED")
    assert order["returned_at"] is None, order["returned_at"]
    assert order["adjudicated_at"] is None, order["adjudicated_at"]
    assert order["expires_at"] is None, order["expires_at"]
    assert_version_is(order, 1)

    after = validate_success(api.get_member(member["id"], headers))
    assert_state(after, "screening_status", "SCREENING_ORDERED")
    assert_state(after, "membership_status", "PENDING")
    assert_state(after, "contact_eligibility", "RESTRICTED")


def test_adjudicating_before_the_vendor_result_is_refused_and_succeeds_after_it(
    api: ApiClient,
) -> None:
    """ADJUDICATED is reachable only from RESULT_RETURNED, so the early attempt fails.

    PRD 3.3 says:
    "The vendor supplies `vendor_disposition`, which is either `NO_RECORD` or `RECORD_FOUND`, against an order that must currently be in status `ORDERED`; a post against an order in any other status is refused with `ERR_SCREENING_ORDER_INVALID_STATE`."
    "The order must be in status `RESULT_RETURNED`."
    "On the two clearing dispositions the order moves `RESULT_RETURNED → ADJUDICATED`, `adjudicated_at` is stamped with the clock, and the order's `expires_at` is set to `adjudicated_at` plus 730 days — the two-year screening validity period."

    PRD 2.8 says:
    "The addressed resource is in a state from which the requested transition exists — otherwise `ERR_SCREENING_ORDER_INVALID_STATE`, `ERR_TRAINING_ASSIGNMENT_INVALID_STATE`, `ERR_COACH_ASSIGNMENT_INVALID_STATE`, `ERR_CASE_INVALID_STATE`, `ERR_INTERIM_MEASURE_INVALID_STATE`, `ERR_AUDIT_INVALID_STATE`, `ERR_FINDING_INVALID_STATE`, `ERR_ROOM_STAY_INVALID_STATE`, or `ERR_MEMBER_INVALID_STATE`."

    Design: Corner/state_machines/adjudicating_before_the_vendor_result_returns_invalid_state
    """
    club = _club(api)
    headers = make_club_admin_headers(club["id"])
    member = _member(api, club["id"], "Ivan Volk", "ivan.volk@alpha.test", "1990-02-08")
    order = _order(api, club["id"], member["id"])

    validate_error(
        api.adjudicate_screening_order(
            order["id"],
            {"disposition": "CLEAR", "rationale": "premature adjudication attempt"},
            OFFICER_ADJUDICATOR_HEADERS,
        ),
        ApiErrorId.SCREENING_ORDER_INVALID_STATE.value,
        409,
    )

    returned = validate_success(
        api.post_screening_result(
            order["id"], {"vendor_disposition": "NO_RECORD"}, SCREENING_VENDOR_HEADERS
        )
    )
    assert_state(returned, "status", "RESULT_RETURNED")
    assert_instant_equals(returned["returned_at"], CLOCK_EPOCH_MS)

    adjudicated = validate_success(
        api.adjudicate_screening_order(
            order["id"],
            {"disposition": "CLEAR", "rationale": "registry return carried no records"},
            OFFICER_ADJUDICATOR_HEADERS,
        )
    )
    assert_state(adjudicated, "status", "ADJUDICATED")
    assert_instant_equals(adjudicated["adjudicated_at"], CLOCK_EPOCH_MS)
    assert_instant_equals(adjudicated["expires_at"], "2028-07-31T00:00:00.000Z")

    assert_state(
        validate_success(api.get_member(member["id"], headers)),
        "screening_status",
        "CLEARED",
    )


def test_cancelling_the_same_room_stay_twice_is_refused_and_keeps_the_first_reason(
    api: ApiClient,
) -> None:
    """Cancellation is not idempotent: the second attempt hits a terminal state.

    PRD 3.7 says:
    "A successful booking is written in status `BOOKED` with `cancel_reason` null."
    "The club administrator supplies a `reason`, which is retained as `cancel_reason`, and the stay moves `BOOKED → CANCELLED`; from that moment its interval no longer participates in either overlap rule, so the freed slot can be rebooked immediately."
    "A stay that is already `CANCELLED` cannot be cancelled again, and the second attempt is refused with `ERR_ROOM_STAY_INVALID_STATE`."

    Design: Corner/state_machines/cancelling_the_same_room_stay_twice_is_rejected
    """
    club = _club(api)
    headers = make_club_admin_headers(club["id"])

    stay = validate_success(api.book_room_stay(club["id"], MINOR_STAY, headers), 201)
    assert_state(stay, "status", "BOOKED")
    assert stay["cancel_reason"] is None, stay["cancel_reason"]

    cancelled = validate_success(
        api.cancel_room_stay(
            stay["id"], {"reason": "family withdrew from the trip"}, headers
        )
    )
    assert_state(cancelled, "status", "CANCELLED")
    assert cancelled["cancel_reason"] == "family withdrew from the trip", cancelled

    validate_error(
        api.cancel_room_stay(stay["id"], {"reason": "duplicate cancellation"}, headers),
        ApiErrorId.ROOM_STAY_INVALID_STATE.value,
        409,
    )

    again = validate_success(api.get_room_stay(stay["id"], headers))
    assert_state(again, "status", "CANCELLED")
    assert again["cancel_reason"] == "family withdrew from the trip", again


def test_a_waived_finding_refuses_a_later_remediation(api: ApiClient) -> None:
    """WAIVED locks the row even against the one decision the club is entitled to make.

    PRD 3.9 says:
    "A `ComplianceAuditor` may instead submit `WAIVED` against a finding in status `OPEN`: the finding moves `OPEN → WAIVED`, the `note` is retained as `decision_note`, `open_finding_count` falls by one while `waived_finding_count` rises by one, the finding is thereafter excluded from any fine, and the club's counters and posture are re-derived."
    "A role submitting a decision reserved to the other party is refused with `ERR_DECISION_ROLE_MISMATCH`, and a decision against a finding in the wrong status — remediation or waiver on a finding that is not `OPEN`, rejection on one that is not `REMEDIATED`, or any decision on a `WAIVED` finding — is refused with `ERR_FINDING_INVALID_STATE`."
    "Finalize is available only from `SAMPLED` and moves the audit `SAMPLED → FINDINGS_ISSUED` with `finalized_at` stamped from the clock."

    Design: Corner/state_machines/waived_finding_is_terminal_and_refuses_further_decisions
    """
    club = _club(api)
    headers = make_club_admin_headers(club["id"])
    member = _member(api, club["id"], "Tom Lund", "tom.lund@alpha.test", "1989-03-09")

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
    finding = get_success_data(
        api.write_finding(
            audit["id"],
            {
                "finding_code": "RECORDS_INCOMPLETE",
                "severity": "MINOR",
                "member_id": member["id"],
                "is_repeat": False,
            },
            COMPLIANCE_AUDITOR_HEADERS,
        ),
        201,
    )
    finalized = get_success_data(
        api.finalize_club_audit(audit["id"], {}, COMPLIANCE_AUDITOR_HEADERS)
    )
    assert_state(finalized, "status", "FINDINGS_ISSUED")

    waived = validate_success(
        api.decide_finding(
            finding["id"],
            {"decision": "WAIVED", "note": "defect cured before the period closed"},
            COMPLIANCE_AUDITOR_HEADERS,
        )
    )
    assert_state(waived, "status", "WAIVED")

    validate_error(
        api.decide_finding(
            finding["id"],
            {
                "decision": "REMEDIATION_SUBMITTED",
                "note": "club attempts to remediate a waived finding",
            },
            headers,
        ),
        ApiErrorId.FINDING_INVALID_STATE.value,
        409,
    )

    assert_state(
        validate_success(api.get_audit_finding(finding["id"], headers)),
        "status",
        "WAIVED",
    )
    after = validate_success(api.get_club_audit(audit["id"], COMPLIANCE_AUDITOR_HEADERS))
    assert_counters(after, waived_finding_count=1, open_finding_count=0)


def test_administrative_closure_leaves_the_investigating_body_untouched(
    api: ApiClient,
) -> None:
    """A case that was never routed closes without moving any body's caseload.

    PRD 3.8 says:
    "The case is created in status `INTAKE_REVIEW` with `intake_received_at` stamped from the logical clock, `investigating_body_id` null, and `reporter_user_id` set from the acting `X-User-ID` so that the reporting obligation leaves an audit trail."
    "The platform then classifies `report_timeliness`: the value is `TIMELY` when the elapsed time from `occurred_at` to `intake_received_at` is at most 24 hours, and `LATE` otherwise — the boundary is inclusive, so a report received exactly 24 hours after the conduct is still `TIMELY`."
    "An officer closes an unrouted case with a `closure_reason` of either `NO_JURISDICTION` or `DUPLICATE_REPORT` and no `outcome` at all; the case moves `INTAKE_REVIEW → CLOSED_ADMINISTRATIVE` with `closed_at` stamped."
    "Administrative closure touches nothing else: no investigating body's `open_case_count` moves, because the case was never routed, and any interim measure imposed during intake survives the closure untouched."
    "Its `open_case_count` starts at zero and is maintained by the platform as the number of cases currently sitting in status `ROUTED` against that body."

    Design: Corner/state_machines/administrative_closure_from_intake_review_leaves_the_body_untouched
    """
    club = _club(api)
    headers = make_club_admin_headers(club["id"])
    member = _member(
        api,
        club["id"],
        "Anya Cole",
        "anya.cole@alpha.test",
        "1984-04-10",
        role_type="OFFICIAL",
        contact=True,
    )
    body = get_success_data(
        api.register_investigating_body(BODY_PHYSICAL, NGB_ADMIN_HEADERS), 201
    )

    case = validate_success(
        api.file_case(
            {
                "club_id": club["id"],
                "reported_member_id": member["id"],
                "allegation_category": "PHYSICAL_ABUSE",
                "reporter_kind": "MANDATORY_REPORTER",
                "narrative": "report that turns out to concern another organisation",
                "occurred_at": "2026-07-31T22:00:00Z",
            },
            OFFICER_INTAKE_HEADERS,
        ),
        201,
    )
    assert_state(case, "status", "INTAKE_REVIEW")
    assert_state(case, "report_timeliness", "TIMELY")

    closed = validate_success(
        api.close_case(
            case["id"], {"closure_reason": "NO_JURISDICTION"}, OFFICER_CLOSER_HEADERS
        )
    )
    assert_state(closed, "status", "CLOSED_ADMINISTRATIVE")
    assert closed["investigating_body_id"] is None, closed["investigating_body_id"]
    assert closed["outcome"] is None, closed["outcome"]
    assert_instant_equals(closed["closed_at"], CLOCK_EPOCH_MS)

    body_after = validate_success(
        api.get_investigating_body(body["id"], NGB_ADMIN_HEADERS)
    )
    assert_counters(body_after, open_case_count=0)

    _rows, meta = validate_paginated(
        api.list_interim_measures(OFFICER_CLOSER_HEADERS, case_id=case["id"])
    )
    assert meta["total_count"] == 0, meta

    assert_state(
        validate_success(api.get_member(member["id"], headers)),
        "membership_status",
        "PENDING",
    )


def test_closing_an_unrouted_case_with_an_outcome_is_rejected_then_succeeds_without_it(
    api: ApiClient,
) -> None:
    """An outcome is forbidden from INTAKE_REVIEW, and the refusal leaves the case open.

    PRD 3.8 says:
    "The officer supplies a `closure_reason` of `INVESTIGATION_COMPLETE` together with an `outcome`; the `outcome` is required when closing from `ROUTED` and forbidden when closing from `INTAKE_REVIEW`."
    "An officer closes an unrouted case with a `closure_reason` of either `NO_JURISDICTION` or `DUPLICATE_REPORT` and no `outcome` at all; the case moves `INTAKE_REVIEW → CLOSED_ADMINISTRATIVE` with `closed_at` stamped."
    "The platform then classifies `report_timeliness`: the value is `TIMELY` when the elapsed time from `occurred_at` to `intake_received_at` is at most 24 hours, and `LATE` otherwise — the boundary is inclusive, so a report received exactly 24 hours after the conduct is still `TIMELY`."

    PRD 2.8 says:
    "The request body conforms to the endpoint's input schema: required fields present, JSON types correct, enum values members of their declared set, string lengths within bounds, `limit` between 1 and 100, `offset` at least 0, `season_end` strictly after `season_start`, `check_out` strictly after `check_in`, `audit_period_end` strictly after `audit_period_start`, `effective_to` at or after `effective_from`, `jurisdiction_codes` non-empty and free of duplicates, and a room stay's `member_id` and `minor_athlete_age` pairing consistent with its `occupant_kind` — otherwise `ERR_VALIDATION`."
    "The addressed resource is in a state from which the requested transition exists — otherwise ... `ERR_CASE_INVALID_STATE` ..."

    PRD establishes that the outcome is "forbidden when closing from `INTAKE_REVIEW`",
    so the refusal itself is normative, but it never names the `error_id` that reports
    it.  Two readings are equally faithful: the rule is a state-conditional body-schema
    check evaluated at position 6 of the order of refusal (`ERR_VALIDATION`), or it is a
    transition that simply does not exist from `INTAKE_REVIEW` and so is reported at
    position 11 (`ERR_CASE_INVALID_STATE`) — note that PRD 2.8's shape enumeration lists
    every other conditional-pairing rule in the system but omits this one.  The assertion
    therefore pins the refusal and the unchanged case, not the choice between the two
    catalogue members.

    Design: Corner/state_machines/closing_from_intake_review_with_an_outcome_is_rejected
    """
    club = _club(api)
    headers = make_club_admin_headers(club["id"])
    member = _member(
        api,
        club["id"],
        "Pia Estes",
        "pia.estes@alpha.test",
        "1983-05-11",
        role_type="OFFICIAL",
        contact=True,
    )

    case = validate_success(
        api.file_case(
            {
                "club_id": club["id"],
                "reported_member_id": member["id"],
                "allegation_category": "POLICY_VIOLATION",
                "reporter_kind": "PARENT",
                "narrative": "duplicate of a report already on file",
                "occurred_at": "2026-07-30T18:00:00Z",
            },
            headers,
        ),
        201,
    )
    assert_state(case, "report_timeliness", "LATE")

    validate_error_is_one_of(
        api.close_case(
            case["id"],
            {"closure_reason": "DUPLICATE_REPORT", "outcome": "UNSUBSTANTIATED"},
            OFFICER_CLOSER_HEADERS,
        ),
        [ApiErrorId.VALIDATION.value, ApiErrorId.CASE_INVALID_STATE.value],
    )
    assert_state(
        validate_success(api.get_case(case["id"], OFFICER_CLOSER_HEADERS)),
        "status",
        "INTAKE_REVIEW",
    )

    closed = validate_success(
        api.close_case(
            case["id"], {"closure_reason": "DUPLICATE_REPORT"}, OFFICER_CLOSER_HEADERS
        )
    )
    assert_state(closed, "status", "CLOSED_ADMINISTRATIVE")
    assert closed["outcome"] is None, closed["outcome"]


def test_lifting_the_measure_restores_the_membership_the_placement_and_both_counters(
    api: ApiClient,
) -> None:
    """The lift is the exact inverse of the imposition, with no drift in either counter.

    PRD 3.8 says:
    "Hop two rewrites the member: `contact_eligibility` becomes `RESTRICTED`, and when the `measure_kind` is `TEMPORARY_SUSPENSION` the membership dimension moves `ACTIVE → SUSPENDED`."
    "The measure moves `ACTIVE → LIFTED` with `lifted_at` stamped from the clock."
    "The member's `contact_eligibility` is re-derived, and when no measure in status `ACTIVE` or `PERMANENT` remains against that member and both `screening_status` is `CLEARED` and `training_status` is `CURRENT`, the membership dimension returns `SUSPENDED → ACTIVE` and `contact_eligibility` becomes `ELIGIBLE`."
    "Every placement of that member in status `SUSPENDED` whose `suspended_reason` is `INTERIM_MEASURE` returns to `ACTIVE`, restoring both `active_assignment_count` counters, and every affected club's `restricted_member_count` and `compliance_posture` are re-derived."

    PRD 2.9 says:
    "Otherwise the posture is `RESTRICTED` when the club's `open_finding_count` reaches or exceeds three, or when its `restricted_member_count` reaches or is above one."

    Design: Corner/state_machines/lifting_a_measure_restores_the_suspended_membership_and_assignment
    """
    club = _club(api)
    headers = make_club_admin_headers(club["id"])
    member = _member(api, club["id"], "Cy Poole", "cy.poole@alpha.test", "1988-06-12")

    _clear_screening(api, club["id"], member["id"])
    _complete_training(api, club["id"], member["id"])

    placement = get_success_data(
        api.create_coach_assignment(
            {
                "member_id": member["id"],
                "club_id": club["id"],
                "team_name": "Distance Group",
                "season_start": "2026-09-01T00:00:00Z",
                "season_end": "2027-05-31T00:00:00Z",
            },
            headers,
        ),
        201,
    )
    activated = get_success_data(
        api.activate_coach_assignment(
            placement["id"],
            {"expected_member_version": _live_member_version(api, member["id"], headers)},
            headers,
        )
    )
    assert_state(activated, "status", "ACTIVE")

    body = get_success_data(
        api.register_investigating_body(BODY_EMOTIONAL, NGB_ADMIN_HEADERS), 201
    )
    case = get_success_data(
        api.file_case(
            {
                "club_id": club["id"],
                "reported_member_id": member["id"],
                "allegation_category": "EMOTIONAL_MISCONDUCT",
                "reporter_kind": "MANDATORY_REPORTER",
                "narrative": "verbal conduct reported at practice",
                "occurred_at": "2026-07-31T20:00:00Z",
            },
            OFFICER_INTAKE_HEADERS,
        ),
        201,
    )
    get_success_data(
        api.route_case(
            case["id"], {"investigating_body_id": body["id"]}, OFFICER_INTAKE_HEADERS
        )
    )

    measure = get_success_data(
        api.impose_interim_measure(
            case["id"],
            {
                "member_id": member["id"],
                "measure_kind": "TEMPORARY_SUSPENSION",
                "effective_from": "2026-08-01T00:00:00Z",
                "effective_to": "2026-09-05T00:00:00Z",
                "expected_member_version": _live_member_version(
                    api, member["id"], OFFICER_IMPOSE_HEADERS
                ),
            },
            OFFICER_IMPOSE_HEADERS,
        ),
        201,
    )
    assert_state(measure, "status", "ACTIVE")

    before = validate_success(api.get_club(club["id"], NGB_ADMIN_HEADERS))
    assert_state(before, "compliance_posture", "RESTRICTED")
    assert_counters(before, restricted_member_count=1, active_assignment_count=0)

    lifted = validate_success(
        api.lift_interim_measure(
            measure["id"],
            {"reason": "investigating body found no basis for continued restriction"},
            OFFICER_IMPOSE_HEADERS,
        )
    )
    assert_state(lifted, "status", "LIFTED")
    assert_instant_equals(lifted["lifted_at"], CLOCK_EPOCH_MS)

    restored_member = validate_success(api.get_member(member["id"], headers))
    assert_state(restored_member, "membership_status", "ACTIVE")
    assert_state(restored_member, "contact_eligibility", "ELIGIBLE")

    restored_placement = validate_success(api.get_coach_assignment(placement["id"], headers))
    assert_state(restored_placement, "status", "ACTIVE")
    assert restored_placement["suspended_reason"] is None, restored_placement

    after = validate_success(api.get_club(club["id"], NGB_ADMIN_HEADERS))
    assert_state(after, "compliance_posture", "OPEN")
    assert_counters(after, restricted_member_count=0, active_assignment_count=1)


def test_an_untouched_assignment_expires_at_its_due_date_and_leaves_training_never(
    api: ApiClient,
) -> None:
    """A course never started expires by clock alone and contributes no expiry at all.

    PRD 3.4 says:
    "The assignment is created in status `ASSIGNED` with `assigned_at` stamped from the logical clock, and `started_at`, `completed_at`, `score`, and `expires_at` all null."
    "Once the logical clock reaches or passes `due_at` while the assignment is still `ASSIGNED`, it moves `ASSIGNED → EXPIRED` on the next read or mutation that touches it, and an `EXPIRED` assignment is excluded from both projection variants entirely."
    "If that expiry is null, meaning at least one required course has no qualifying completion at all, `training_status` is `NEVER`."

    PRD 2.5 says:
    "An `ASSIGNED` training assignment becomes `EXPIRED` once the clock reaches or passes its `due_at`; an assignment already `IN_PROGRESS` is never expired by the clock."

    Design: Corner/state_machines/assigned_training_expires_lazily_once_the_due_date_passes
    """
    club = _club(api)
    headers = make_club_admin_headers(club["id"])
    get_success_data(api.publish_course(SS101, NGB_ADMIN_HEADERS), 201)
    member = _member(api, club["id"], "Elle Xu", "elle.xu@alpha.test", "1995-07-13")

    assignment = validate_success(
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
    assert_state(assignment, "status", "ASSIGNED")
    assert_instant_equals(assignment["assigned_at"], CLOCK_EPOCH_MS)

    get_success_data(api.set_clock("2026-09-01T00:00:00Z", NGB_ADMIN_HEADERS))

    lapsed = validate_success(api.get_training_assignment(assignment["id"], headers))
    assert_state(lapsed, "status", "EXPIRED")
    assert lapsed["started_at"] is None, lapsed["started_at"]
    assert lapsed["completed_at"] is None, lapsed["completed_at"]

    projection = validate_success(
        api.get_eligibility_projection(member["id"], headers, variant="AUDIT_SNAPSHOT")
    )
    assert_state(projection, "training_status", "NEVER")
    assert projection["training_expiry"] is None, projection["training_expiry"]
    assert_state(projection, "contact_eligibility", "RESTRICTED")
