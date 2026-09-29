"""Who may act, on whose rows, and which two officers may not be the same person.

Authority is checked at three different levels here: the role against the
endpoint, the acting principal against the row it owns, and one officer's
recorded identifier against another's.  Each refusal is paired with the same
call made by the principal who is entitled to it, so a blanket denial cannot
pass these tests.
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
from test_helpers.assertions import (
    assert_counters,
    assert_instant_equals,
    assert_money_equals,
    assert_state,
)
from test_helpers.constants import CLOCK_EPOCH
from test_helpers.test_users import (
    COMPLIANCE_AUDITOR_HEADERS,
    NGB_ADMIN_HEADERS,
    OFFICER_ADJUDICATOR_HEADERS,
    OFFICER_IMPOSE_HEADERS,
    OFFICER_INTAKE_HEADERS,
    OFFICER_INTAKE_USER_ID,
    OFFICER_IMPOSE_USER_ID,
    OFFICER_REVIEW_HEADERS,
    OFFICER_REVIEW_USER_ID,
    SCREENING_VENDOR_HEADERS,
    make_club_admin_headers,
    make_member_headers,
)

ALPHA_AQUATICS = {
    "name": "Alpha Aquatics",
    "state_code": "CA",
    "roster_size_attested": 3,
    "minor_athlete_program": True,
    "initial_escrow_cents": 500000,
}
BETA_BEARS = {
    "name": "Beta Bears",
    "state_code": "OR",
    "roster_size_attested": 2,
    "minor_athlete_program": False,
    "initial_escrow_cents": 200000,
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


def test_four_governing_body_only_writes_are_each_refused_to_a_different_other_role(
    api: ApiClient,
) -> None:
    """Chartering, publishing, registering a body and voiding belong to the governing body alone.

    PRD 2.8 says:
    "The acting role is authorized for the called endpoint — otherwise `ERR_UNAUTHORIZED`."

    PRD 3.3 says:
    "Governing-body staff, and only they, may void an order that has gone wrong — a duplicate submission, a wrong jurisdiction list, a vendor engaged in error."
    "The order moves to `VOIDED`, the club's `escrow_balance_cents` is credited with exactly the order's `charged_cents` and the club's `version` advances by one, and the member's screening dimension reverts to `UNSCREENED` — from `SCREENING_ORDERED` or from `FLAGGED` — with `contact_eligibility` re-derived and the member's `version` advanced by one."
    "The void is the exact compensating counterpart of the order, which is what keeps the escrow conservation identity of §2.12 intact."

    Design: Corner/rbac/ngb_admin_exclusive_writes_are_refused_to_every_other_role
    """
    _epoch(api)
    club = _club(api)
    headers = make_club_admin_headers(club["id"])
    member = _member(api, club["id"], "Eve Xu", "eve.xu@alpha.test", "1992-02-06")
    order = get_success_data(
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

    validate_error(
        api.charter_club(
            {
                "name": "Rogue Club",
                "state_code": "CA",
                "roster_size_attested": 1,
                "minor_athlete_program": False,
                "initial_escrow_cents": 1000,
            },
            headers,
        ),
        ApiErrorId.UNAUTHORIZED,
        403,
    )
    validate_error(
        api.publish_course(
            {
                "code": "SS777",
                "title": "Auditor Special",
                "validity_days": 365,
                "delivery_mode": "ONLINE",
                "required_for_tiers": ["TIER_1"],
                "pass_score": 80,
            },
            COMPLIANCE_AUDITOR_HEADERS,
        ),
        ApiErrorId.UNAUTHORIZED,
        403,
    )
    validate_error(
        api.register_investigating_body(
            {
                "name": "Vendor Panel",
                "scope_categories": ["POLICY_VIOLATION"],
                "max_open_cases": 3,
                "intake_status": "ACCEPTING",
            },
            SCREENING_VENDOR_HEADERS,
        ),
        ApiErrorId.UNAUTHORIZED,
        403,
    )
    validate_error(
        api.void_screening_order(
            order["id"], {"reason": "officer attempts a void"}, OFFICER_INTAKE_HEADERS
        ),
        ApiErrorId.UNAUTHORIZED,
        403,
    )

    voided = validate_success(
        api.void_screening_order(
            order["id"],
            {"reason": "ordered against the wrong member record"},
            NGB_ADMIN_HEADERS,
        )
    )
    assert_state(voided, "status", "VOIDED")
    refunded = validate_success(api.get_club(club["id"], NGB_ADMIN_HEADERS))
    assert_money_equals(refunded, "escrow_balance_cents", 500000)
    assert_money_equals(refunded, "total_funded_cents", 500000)
    reverted = validate_success(api.get_member(member["id"], headers))
    assert_state(reverted, "screening_status", "UNSCREENED")


def test_the_vendor_may_not_adjudicate_and_the_officer_may_not_post_the_return(
    api: ApiClient,
) -> None:
    """Two endpoints act on the same order in the same status, and each belongs to one role only.

    PRD 3.3 says:
    "The screening vendor's only capability is posting back what its search found."
    "The vendor supplies `vendor_disposition`, which is either `NO_RECORD` or `RECORD_FOUND`, against an order that must currently be in status `ORDERED`; a post against an order in any other status is refused with `ERR_SCREENING_ORDER_INVALID_STATE`."
    "Adjudication belongs exclusively to a `SafeSportOfficer`, who supplies a `disposition` and a written `rationale`."
    "On the two clearing dispositions the order moves `RESULT_RETURNED → ADJUDICATED`, `adjudicated_at` is stamped with the clock, and the order's `expires_at` is set to `adjudicated_at` plus 730 days — the two-year screening validity period."
    "The member's screening dimension moves to `CLEARED` (from `SCREENING_ORDERED` on a `CLEAR`, from either `SCREENING_ORDERED` or `FLAGGED` on a `NON_DISQUALIFYING_RECORD`), and `screening_expires_at` on the member is set from the order's `expires_at`."

    PRD 2.8 says:
    "The acting role is authorized for the called endpoint — otherwise `ERR_UNAUTHORIZED`."

    Design: Corner/rbac/screening_result_and_adjudication_are_disjoint_capabilities
    """
    _epoch(api)
    club = _club(api)
    headers = make_club_admin_headers(club["id"])
    member = _member(api, club["id"], "Rae Vidal", "rae.vidal@alpha.test", "1993-03-07")
    order = get_success_data(
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

    validate_error(
        api.adjudicate_screening_order(
            order["id"],
            {"disposition": "CLEAR", "rationale": "vendor tries to clear its own screen"},
            SCREENING_VENDOR_HEADERS,
        ),
        ApiErrorId.UNAUTHORIZED,
        403,
    )
    validate_error(
        api.post_screening_result(
            order["id"],
            {"vendor_disposition": "NO_RECORD"},
            OFFICER_ADJUDICATOR_HEADERS,
        ),
        ApiErrorId.UNAUTHORIZED,
        403,
    )

    returned = validate_success(
        api.post_screening_result(
            order["id"], {"vendor_disposition": "NO_RECORD"}, SCREENING_VENDOR_HEADERS
        )
    )
    assert_state(returned, "status", "RESULT_RETURNED")
    adjudicated = validate_success(
        api.adjudicate_screening_order(
            order["id"],
            {"disposition": "CLEAR", "rationale": "no record returned by the vendor"},
            OFFICER_ADJUDICATOR_HEADERS,
        )
    )
    assert_state(adjudicated, "status", "ADJUDICATED")
    assert_instant_equals(adjudicated["expires_at"], "2028-07-31T00:00:00.000Z")
    cleared = validate_success(api.get_member(member["id"], headers))
    assert_state(cleared, "screening_status", "CLEARED")
    assert_instant_equals(cleared["screening_expires_at"], "2028-07-31T00:00:00.000Z")


def test_the_imposer_cannot_convert_and_the_reporter_cannot_close_while_a_third_officer_can(
    api: ApiClient,
) -> None:
    """Both refusals are keyed on the acting identifier, not on the role, which is identical throughout.

    PRD 2.1 says:
    "Two responsibilities are split across principals rather than roles. A `SafeSportOfficer` may not convert an interim measure that the same `X-User-ID` imposed, and may not close a case that the same `X-User-ID` filed; both refusals are `ERR_SEGREGATION_OF_DUTIES` (HTTP 403)."

    PRD 2.8 says:
    "Segregation of duties holds on measure conversion and case closure — otherwise `ERR_SEGREGATION_OF_DUTIES`."

    PRD 3.8 says:
    "The case is created in status `INTAKE_REVIEW` with `intake_received_at` stamped from the logical clock, `investigating_body_id` null, and `reporter_user_id` set from the acting `X-User-ID` so that the reporting obligation leaves an audit trail."
    "Hop one creates the measure in status `ACTIVE` with `permanence` of `TEMPORARY` and `imposed_by_user_id` set from the acting `X-User-ID`, leaving `converted_by_user_id`, `lifted_at`, `lift_reason`, and `rationale` null."
    "The officer supplies a written `rationale`; the measure must be in status `ACTIVE`, the case must be in status `ROUTED`, and the acting `X-User-ID` must differ from the measure's `imposed_by_user_id` — the officer who imposed a restriction may not be the officer who makes it permanent, and an attempt by the same principal is refused with `ERR_SEGREGATION_OF_DUTIES`."
    "On success the measure moves `ACTIVE → PERMANENT` with `permanence` set to `PERMANENT` and `converted_by_user_id` set from the acting `X-User-ID`."
    "In both branches the acting `X-User-ID` must differ from the case's `reporter_user_id`, else `ERR_SEGREGATION_OF_DUTIES`, and closing a case already in any closed status is refused with `ERR_CASE_INVALID_STATE`."

    Design: Corner/rbac/segregation_of_duties_blocks_the_imposer_and_the_reporter
    """
    _epoch(api)
    club = _club(api)
    member = _member(
        api,
        club["id"],
        "Sam Doss",
        "sam.doss@alpha.test",
        "1980-04-08",
        role_type="HEAD_COACH",
        contact=True,
    )
    body = get_success_data(
        api.register_investigating_body(
            {
                "name": "Conduct Panel",
                "scope_categories": ["SEXUAL_MISCONDUCT"],
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
                "reported_member_id": member["id"],
                "allegation_category": "SEXUAL_MISCONDUCT",
                "reporter_kind": "MANDATORY_REPORTER",
                "narrative": "report taken by the duty officer within the hour",
                "occurred_at": "2026-07-31T23:30:00Z",
            },
            OFFICER_INTAKE_HEADERS,
        ),
        201,
    )
    assert case["reporter_user_id"] == OFFICER_INTAKE_USER_ID, (
        f"the reporter is recorded as {case['reporter_user_id']!r}"
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
                "member_id": member["id"],
                "measure_kind": "TEMPORARY_SUSPENSION",
                "effective_from": "2026-08-01T00:00:00Z",
                "effective_to": "2026-11-01T00:00:00Z",
                "expected_member_version": validate_success(
                    api.get_member(member["id"], NGB_ADMIN_HEADERS)
                )["version"],
            },
            OFFICER_IMPOSE_HEADERS,
        ),
        201,
    )
    assert measure["imposed_by_user_id"] == OFFICER_IMPOSE_USER_ID, (
        f"the imposer is recorded as {measure['imposed_by_user_id']!r}"
    )

    validate_error(
        api.convert_interim_measure_permanent(
            measure["id"],
            {"rationale": "imposer attempts to make its own measure permanent"},
            OFFICER_IMPOSE_HEADERS,
        ),
        ApiErrorId.SEGREGATION_OF_DUTIES,
        403,
    )
    validate_error(
        api.close_case(
            case["id"],
            {"closure_reason": "INVESTIGATION_COMPLETE", "outcome": "UNSUBSTANTIATED"},
            OFFICER_INTAKE_HEADERS,
        ),
        ApiErrorId.SEGREGATION_OF_DUTIES,
        403,
    )

    converted = validate_success(
        api.convert_interim_measure_permanent(
            measure["id"],
            {"rationale": "panel finding supports a permanent restriction"},
            OFFICER_REVIEW_HEADERS,
        )
    )
    assert_state(converted, "status", "PERMANENT")
    assert_state(converted, "permanence", "PERMANENT")
    assert converted["converted_by_user_id"] == OFFICER_REVIEW_USER_ID, (
        f"the converter is recorded as {converted['converted_by_user_id']!r}"
    )
    still_routed = validate_success(api.get_case(case["id"], OFFICER_REVIEW_HEADERS))
    assert_state(still_routed, "status", "ROUTED")
    prohibited = validate_success(api.get_member(member["id"], NGB_ADMIN_HEADERS))
    assert_state(prohibited, "contact_eligibility", "PROHIBITED")


def test_a_member_reads_and_starts_only_their_own_rows_yet_may_report_on_anybody(
    api: ApiClient,
) -> None:
    """One member is denied three ways against a peer's rows, then allowed the same calls on their own.

    PRD 2.1 says:
    "A `Member` caller may start and complete only their own training assignments, and may read only their own member record and its sub-resources; addressing another member's resource is refused with `ERR_UNAUTHORIZED`."
    "Filing an incident report is the one exception to the ownership rule: a `Member` may file a report naming any individual, so the reported member is deliberately not required to be the caller."

    PRD 2.8 says:
    "A `Member` caller acts only on their own resources — otherwise `ERR_UNAUTHORIZED`."

    PRD 3.4 says:
    "The member themself, or their club administrator acting for them, starts the course; when the caller's role is `Member` the acting `X-User-ID` must equal the assignment's own `member_id`, otherwise the request is refused with `ERR_UNAUTHORIZED`."
    "Starting requires status `ASSIGNED` and moves the assignment `ASSIGNED → IN_PROGRESS` with `started_at` stamped."

    PRD 3.8 says:
    "The case is created in status `INTAKE_REVIEW` with `intake_received_at` stamped from the logical clock, `investigating_body_id` null, and `reporter_user_id` set from the acting `X-User-ID` so that the reporting obligation leaves an audit trail."

    Design: Corner/rbac/member_role_reaches_only_their_own_record_and_assignments
    """
    _epoch(api)
    club = _club(api)
    own = _member(api, club["id"], "Ola Wynn", "ola.wynn@alpha.test", "1991-02-17")
    peer = _member(api, club["id"], "Per Kell", "per.kell@alpha.test", "1988-06-05")
    get_success_data(api.publish_course(SS101, NGB_ADMIN_HEADERS), 201)
    assignment = get_success_data(
        api.assign_training(
            {
                "member_id": own["id"],
                "course_code": "SS101",
                "due_at": "2026-10-01T00:00:00Z",
            },
            make_club_admin_headers(club["id"]),
        ),
        201,
    )
    peer_headers = make_member_headers(peer["id"])

    validate_error(
        api.get_member(own["id"], peer_headers), ApiErrorId.UNAUTHORIZED, 403
    )
    validate_error(
        api.get_eligibility_projection(
            own["id"], peer_headers, variant="AUDIT_SNAPSHOT"
        ),
        ApiErrorId.UNAUTHORIZED,
        403,
    )
    validate_error(
        api.start_training(assignment["id"], peer_headers),
        ApiErrorId.UNAUTHORIZED,
        403,
    )

    started = validate_success(
        api.start_training(assignment["id"], make_member_headers(own["id"]))
    )
    assert_state(started, "status", "IN_PROGRESS")
    assert_instant_equals(started["started_at"], "2026-08-01T00:00:00.000Z")
    own_read = validate_success(
        api.get_member(own["id"], make_member_headers(own["id"]))
    )
    assert own_read["id"] == own["id"], (
        f"a member reading themself got {own_read['id']!r}"
    )

    reported = get_success_data(
        api.file_case(
            {
                "club_id": club["id"],
                "reported_member_id": own["id"],
                "allegation_category": "EMOTIONAL_MISCONDUCT",
                "reporter_kind": "ATHLETE",
                "narrative": "peer reports conduct observed at the same practice session",
                "occurred_at": "2026-07-31T23:30:00Z",
            },
            peer_headers,
        ),
        201,
    )
    assert_state(reported, "status", "INTAKE_REVIEW")
    assert reported["reporter_user_id"] == peer["id"], (
        f"the reporter is recorded as {reported['reporter_user_id']!r}"
    )


def test_a_wrong_role_is_reported_before_the_wrong_club_and_before_any_state_check(
    api: ApiClient,
) -> None:
    """The club administrator is off-scope and off-role at once, and only the role refusal is heard.

    PRD 2.8 says:
    "Because many operations are guarded by several rules at once, the platform evaluates its checks in one fixed order and reports **the first failure only**."
    "The acting role is authorized for the called endpoint — otherwise `ERR_UNAUTHORIZED`."
    "A `ClubAdministrator`'s `X-User-ID` matches the owning club of the addressed resource — otherwise `ERR_CLUB_SCOPE_VIOLATION`."

    PRD 3.9 says:
    "Auditing the clubs is the governing body's own accountability loop, and it belongs entirely to the `ComplianceAuditor` role."
    "The audit is created in status `SAMPLED`, with `sampled_member_count` set to the number of entries supplied, `compliant_member_count`, `denominator_count`, `compliance_score`, and `sanction_fine_cents` all null, all four finding counters at zero, and `finalized_at`, `closed_at`, and `resolution` null."

    PRD 3.8 says:
    "Its `open_case_count` starts at zero and is maintained by the platform as the number of cases currently sitting in status `ROUTED` against that body."

    Design: Corner/rbac/unauthorized_role_outranks_the_club_scope_check
    """
    _epoch(api)
    alpha = _club(api)
    beta = _club(api, BETA_BEARS)
    alpha_admin = make_club_admin_headers(alpha["id"])
    member = _member(api, alpha["id"], "Ivy Roe", "ivy.roe@alpha.test", "1990-09-09")
    body = get_success_data(
        api.register_investigating_body(
            {
                "name": "Regional Review Board",
                "scope_categories": ["POLICY_VIOLATION"],
                "max_open_cases": 3,
            },
            NGB_ADMIN_HEADERS,
        ),
        201,
    )
    case = get_success_data(
        api.file_case(
            {
                "club_id": alpha["id"],
                "reported_member_id": member["id"],
                "allegation_category": "POLICY_VIOLATION",
                "reporter_kind": "MANDATORY_REPORTER",
                "narrative": "club administrator files the policy breach it observed",
                "occurred_at": "2026-07-31T23:30:00Z",
            },
            alpha_admin,
        ),
        201,
    )
    order = get_success_data(
        api.order_screening(
            member["id"],
            {"expected_club_version": _live_club_version(api, alpha["id"])},
            alpha_admin,
        ),
        201,
    )
    audit_payload = {
        "club_id": alpha["id"],
        "audit_period_start": "2026-01-01T00:00:00Z",
        "audit_period_end": "2026-08-01T00:00:00Z",
        "score_variant": "SELF_ATTESTED",
        "sampled_member_ids": [member["id"]],
    }

    validate_error(
        api.open_club_audit(audit_payload, make_club_admin_headers(beta["id"])),
        ApiErrorId.UNAUTHORIZED,
        403,
    )
    validate_error(
        api.route_case(
            case["id"], {"investigating_body_id": body["id"]}, alpha_admin
        ),
        ApiErrorId.UNAUTHORIZED,
        403,
    )
    validate_error(
        api.adjudicate_screening_order(
            order["id"],
            {"disposition": "CLEAR", "adjudication_note": "administrator overreach"},
            alpha_admin,
        ),
        ApiErrorId.UNAUTHORIZED,
        403,
    )

    audit = get_success_data(
        api.open_club_audit(audit_payload, COMPLIANCE_AUDITOR_HEADERS), 201
    )
    assert_state(audit, "status", "SAMPLED")
    assert_counters(audit, sampled_member_count=1)
    untouched_case = validate_success(api.get_case(case["id"], NGB_ADMIN_HEADERS))
    assert_state(untouched_case, "status", "INTAKE_REVIEW")
    untouched_body = validate_success(
        api.get_investigating_body(body["id"], NGB_ADMIN_HEADERS)
    )
    assert_counters(untouched_body, open_case_count=0)
    untouched_order = validate_success(
        api.get_screening_order(order["id"], NGB_ADMIN_HEADERS)
    )
    assert_state(untouched_order, "status", "ORDERED")
