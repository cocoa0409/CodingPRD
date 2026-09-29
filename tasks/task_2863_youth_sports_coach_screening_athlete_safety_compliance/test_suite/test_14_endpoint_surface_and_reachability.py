"""Reads: computed projections, role-split decisions, reverse reachability and paging.

Every relationship the platform declares is reachable from both ends, so these
tests fetch the same row through a parent's nested path and through its own
filtered collection and insist the two agree.  The computed reads are asserted
as pure functions of stored state, and the paging assertions check the window
metadata rather than merely the row count.
"""

from __future__ import annotations

from typing import Any, Dict, Sequence

from prd_bench_local_runner.testing import (
    get_success_data,
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers.api_client import ApiClient
from test_helpers.api_errors import ApiErrorId
from test_helpers.assertions import (
    assert_counters,
    assert_instant_equals,
    assert_pagination_meta,
    assert_state,
    ids_of,
)
from test_helpers.constants import CLOCK_EPOCH
from test_helpers.test_users import (
    COMPLIANCE_AUDITOR_HEADERS,
    NGB_ADMIN_HEADERS,
    OFFICER_ADJUDICATOR_HEADERS,
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


def test_the_projection_read_defaults_to_the_audit_snapshot_and_names_its_open_gates(
    api: ApiClient,
) -> None:
    """For a member with no screening and no training the projection is a pure function of stored state.

    PRD 3.5 says:
    "The read accepts one optional query parameter, `variant`, whose two accepted values are `AUDIT_SNAPSHOT` and `RENEWAL_FORWARD`; when omitted the variant is `AUDIT_SNAPSHOT`."
    "The response reports the `variant` actually applied, the resulting `projected_eligible_through`, the two horizons it was built from as `screening_expiry` and `training_expiry`, the member's current `screening_status`, `training_status`, `membership_status`, `contact_eligibility`, `required_tier`, and `risk_points`, the retention horizon `records_retained_through`, and a `blocking_reasons` array listing the conditions that currently stand between this member and athlete contact."
    "Second, the **screening horizon** is the latest `expires_at` among the member's own screening orders that reached status `ADJUDICATED` with a `disposition` of `CLEAR` or `NON_DISQUALIFYING_RECORD`; when two such orders carry the identical `expires_at`, the one with the earlier `created_at` is the row selected, and when the member has no such order at all the screening horizon is null."
    "If a required course has no candidate assignment at all, its per-course expiry is null."
    "`projected_eligible_through` is then null if either the screening horizon or the training horizon is null, and otherwise the earlier of the two."

    PRD 3.1 says:
    "A newly registered member starts at `screening_status` of `UNSCREENED` on the screening dimension and `membership_status` of `PENDING` on the membership dimension, with `training_status` of `NEVER` and `contact_eligibility` of `RESTRICTED`."
    "The role component contributes 40 points for a `HEAD_COACH`, 30 for an `ASSISTANT_COACH`, 25 for a `CHAPERONE`, 20 for an `OFFICIAL`, and 10 for a `VOLUNTEER`."
    "The score selects a screening tier and writes it to `required_tier`: a score that reaches or exceeds 75 demands `TIER_3`, otherwise a score that reaches or exceeds 45 demands `TIER_2`, otherwise `TIER_1`."

    Design: Corner/endpoints/projection_read_defaults_to_audit_snapshot_and_reports_blocking_reasons
    """
    _epoch(api)
    club = _club(api)
    get_success_data(api.publish_course(SS101, NGB_ADMIN_HEADERS), 201)
    member = _member(api, club["id"], "Cara Reed", "cara.reed@alpha.test", "1997-03-26")

    default_view = validate_success(
        api.get_eligibility_projection(member["id"], COMPLIANCE_AUDITOR_HEADERS)
    )
    assert_state(default_view, "variant", "AUDIT_SNAPSHOT")
    assert default_view["projected_eligible_through"] is None, (
        "a member with neither horizon projects nothing: "
        f"{default_view['projected_eligible_through']!r}"
    )
    assert default_view["screening_expiry"] is None, (
        f"no adjudicated order, so no screening horizon: {default_view['screening_expiry']!r}"
    )
    assert default_view["training_expiry"] is None, (
        f"SS101 has no completion, so no training horizon: {default_view['training_expiry']!r}"
    )
    assert_state(default_view, "screening_status", "UNSCREENED")
    assert_state(default_view, "training_status", "NEVER")
    assert_state(default_view, "membership_status", "PENDING")
    assert_state(default_view, "contact_eligibility", "RESTRICTED")
    assert_state(default_view, "required_tier", "TIER_1")
    assert_counters(default_view, risk_points=10)
    reasons = default_view["blocking_reasons"]
    assert isinstance(reasons, list), f"blocking_reasons must be an array, got {reasons!r}"
    assert reasons, "a RESTRICTED member has conditions standing in the way, so the array is not empty"

    # The forward-looking variant is a different read of the same rows, and with
    # no candidate assignment at all it too has nothing to project.
    forward = validate_success(
        api.get_eligibility_projection(
            member["id"], COMPLIANCE_AUDITOR_HEADERS, variant="RENEWAL_FORWARD"
        )
    )
    assert_state(forward, "variant", "RENEWAL_FORWARD")
    assert forward["projected_eligible_through"] is None, (
        f"the screening horizon is null under either variant: {forward['projected_eligible_through']!r}"
    )


def test_one_finding_refuses_the_club_waiver_and_the_auditor_remediation_then_takes_both_own_moves(
    api: ApiClient,
) -> None:
    """The decision endpoint is shared by two roles whose permitted values are disjoint.

    PRD 3.9 says:
    "A `ClubAdministrator` submits `REMEDIATION_SUBMITTED` against a finding in status `OPEN`: the finding moves `OPEN → REMEDIATED`, the supplied `note` is retained as `evidence_note`, the audit's `open_finding_count` falls by one while `remediated_finding_count` rises by one, and the club's finding counters and posture are re-derived."
    "A `ComplianceAuditor` may instead submit `WAIVED` against a finding in status `OPEN`: the finding moves `OPEN → WAIVED`, the `note` is retained as `decision_note`, `open_finding_count` falls by one while `waived_finding_count` rises by one, the finding is thereafter excluded from any fine, and the club's counters and posture are re-derived."
    "A role submitting a decision reserved to the other party is refused with `ERR_DECISION_ROLE_MISMATCH`, and a decision against a finding in the wrong status — remediation or waiver on a finding that is not `OPEN`, rejection on one that is not `REMEDIATED`, or any decision on a `WAIVED` finding — is refused with `ERR_FINDING_INVALID_STATE`."
    "Finalize is available only from `SAMPLED` and moves the audit `SAMPLED → FINDINGS_ISSUED` with `finalized_at` stamped from the clock."

    PRD 2.8 says:
    "The submitted `decision` value is one the acting role may record — otherwise `ERR_DECISION_ROLE_MISMATCH`."

    Design: Corner/endpoints/finding_decision_is_bounded_by_the_acting_role_in_both_directions
    """
    _epoch(api)
    club = _club(api)
    headers = make_club_admin_headers(club["id"])
    member = _member(api, club["id"], "Dara Ruiz", "dara.ruiz@alpha.test", "1990-04-27")
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
                "finding_code": "TRAINING_LAPSED",
                "severity": "MAJOR",
                "member_id": member["id"],
                "is_repeat": False,
            },
            COMPLIANCE_AUDITOR_HEADERS,
        ),
        201,
    )
    assert_state(finding, "status", "OPEN")
    finalized = validate_success(
        api.finalize_club_audit(audit["id"], {}, COMPLIANCE_AUDITOR_HEADERS)
    )
    assert_state(finalized, "status", "FINDINGS_ISSUED")

    validate_error(
        api.decide_finding(
            finding["id"],
            {"decision": "WAIVED", "note": "club tries to waive its own finding"},
            headers,
        ),
        ApiErrorId.DECISION_ROLE_MISMATCH,
        403,
    )
    validate_error(
        api.decide_finding(
            finding["id"],
            {
                "decision": "REMEDIATION_SUBMITTED",
                "note": "auditor tries to remediate on the club's behalf",
            },
            COMPLIANCE_AUDITOR_HEADERS,
        ),
        ApiErrorId.DECISION_ROLE_MISMATCH,
        403,
    )

    remediated = validate_success(
        api.decide_finding(
            finding["id"],
            {
                "decision": "REMEDIATION_SUBMITTED",
                "note": "training records uploaded for the sampled member",
            },
            headers,
        )
    )
    assert_state(remediated, "status", "REMEDIATED")
    reopened = validate_success(
        api.decide_finding(
            finding["id"],
            {
                "decision": "REMEDIATION_REJECTED",
                "note": "uploaded records do not cover the audit period",
            },
            COMPLIANCE_AUDITOR_HEADERS,
        )
    )
    assert_state(reopened, "status", "OPEN")

    reread = validate_success(api.get_club_audit(audit["id"], COMPLIANCE_AUDITOR_HEADERS))
    assert_counters(
        reread,
        open_finding_count=1,
        remediated_finding_count=0,
        finding_total_count=1,
    )


def test_an_adult_stay_is_listed_under_its_club_and_its_member_while_a_mixed_payload_is_refused(
    api: ApiClient,
) -> None:
    """A stay for an adult member is a link row, so both reverse-reachability paths return it.

    PRD 3.7 says:
    "When `occupant_kind` is `ADULT_MEMBER`, `member_id` must be set and `minor_athlete_age` must be null."
    "An inconsistent pairing is a shape violation refused with `ERR_VALIDATION`."
    "A successful booking is written in status `BOOKED` with `cancel_reason` null."

    PRD 2.8 says:
    "The request body conforms to the endpoint's input schema: required fields present, JSON types correct, enum values members of their declared set, string lengths within bounds, `limit` between 1 and 100, `offset` at least 0, `season_end` strictly after `season_start`, `check_out` strictly after `check_in`, `audit_period_end` strictly after `audit_period_start`, `effective_to` at or after `effective_from`, `jurisdiction_codes` non-empty and free of duplicates, and a room stay's `member_id` and `minor_athlete_age` pairing consistent with its `occupant_kind` — otherwise `ERR_VALIDATION`."

    PRD 2.11 says:
    "Flat collections with foreign-key filters exist alongside those nested paths so that every relationship declared in this system is reverse-reachable: screening orders can be listed by `member_id`, training assignments by `member_id` and `course_code`, coach placements by `member_id` and by `club_id`, cases by `club_id`, `reported_member_id`, and `investigating_body_id`, interim measures by `case_id` and `member_id`, audits by `club_id` and by `score_variant`, findings by `audit_id`, `member_id`, and `severity`, and room stays by `club_id`, `member_id`, `trip_label`, and `room_number`."

    Design: Corner/endpoints/room_stay_is_reachable_from_both_its_club_and_its_member
    """
    _epoch(api)
    club = _club(api)
    headers = make_club_admin_headers(club["id"])
    member = _member(
        api,
        club["id"],
        "Lena Koss",
        "lena.koss@alpha.test",
        "1982-05-28",
        role_type="CHAPERONE",
    )
    stay = get_success_data(
        api.book_room_stay(
            club["id"],
            {
                "occupant_kind": "ADULT_MEMBER",
                "member_id": member["id"],
                "trip_label": "SUMMER_CAMP",
                "room_number": "402",
                "check_in": "2026-08-10T15:00:00Z",
                "check_out": "2026-08-12T11:00:00Z",
            },
            headers,
        ),
        201,
    )
    assert stay["club_id"] == club["id"], (
        f"the club comes from the path: {stay['club_id']} != {club['id']}"
    )
    assert stay["member_id"] == member["id"], (
        f"the occupant is the named member: {stay['member_id']} != {member['id']}"
    )
    assert stay["minor_athlete_age"] is None, (
        f"an adult occupant records no age: {stay['minor_athlete_age']!r}"
    )
    assert_state(stay, "status", "BOOKED")

    validate_error(
        api.book_room_stay(
            club["id"],
            {
                "occupant_kind": "ADULT_MEMBER",
                "member_id": member["id"],
                "trip_label": "SUMMER_CAMP",
                "room_number": "404",
                "check_in": "2026-08-10T15:00:00Z",
                "check_out": "2026-08-12T11:00:00Z",
                "minor_athlete_age": 15,
            },
            headers,
        ),
        ApiErrorId.VALIDATION,
        422,
    )

    member_rows, member_meta = validate_paginated(
        api.list_member_room_stays(member["id"], headers)
    )
    assert ids_of(member_rows) == [stay["id"]], (
        f"the member's stays are {ids_of(member_rows)}, expected only {stay['id']}"
    )
    assert member_rows[0]["room_number"] == "402", (
        f"room 402 is the booked room: {member_rows[0]['room_number']!r}"
    )
    assert_pagination_meta(member_meta, total=1, limit=10, offset=0)

    club_rows, club_meta = validate_paginated(
        api.list_club_room_stays(club["id"], headers)
    )
    assert ids_of(club_rows) == [stay["id"]], (
        f"the club's stays are {ids_of(club_rows)}, expected only {stay['id']}"
    )
    assert club_rows[0]["room_number"] == "402", (
        f"room 402 is the booked room: {club_rows[0]['room_number']!r}"
    )
    assert_pagination_meta(club_meta, total=1, limit=10, offset=0)

    # The refused booking left nothing behind in the slot it named either.
    room_404, room_404_meta = validate_paginated(
        api.list_room_stays(
            NGB_ADMIN_HEADERS,
            club_id=club["id"],
            trip_label="SUMMER_CAMP",
            room_number="404",
        )
    )
    assert room_404 == [], f"the rejected pairing created a stay: {room_404}"
    assert_pagination_meta(room_404_meta, total=0, limit=10, offset=0)


def test_moving_the_clock_onto_the_screening_expiry_lapses_three_dimensions_and_blocks_activation(
    api: ApiClient,
) -> None:
    """Nothing is written at 2028-07-31 except the clock, and the read alone shows the lapses.

    PRD 2.5 says:
    "An `NgbAdmin` may reposition the clock to any instant by supplying `to_iso8601`; the response reports the resulting `current_utc`."
    "A `CLEARED` screening becomes `EXPIRED` once the clock reaches or passes the member's `screening_expires_at` — the boundary is inclusive, so at exactly that instant the screen is already `EXPIRED`."
    "An `ACTIVE` membership becomes `LAPSED` once the clock reaches or passes the member's `eligible_through`, again inclusively."

    PRD 3.3 says:
    "On the two clearing dispositions the order moves `RESULT_RETURNED → ADJUDICATED`, `adjudicated_at` is stamped with the clock, and the order's `expires_at` is set to `adjudicated_at` plus 730 days — the two-year screening validity period."

    PRD 3.4 says:
    "Otherwise, if the logical clock has reached or passed that expiry, `training_status` is `LAPSED` — the boundary is inclusive, so at exactly the expiry instant the training is already lapsed."

    PRD 3.6 says:
    "The restriction gate at position 14 of the order of refusal is measure-based only: a member whose `contact_eligibility` is merely `RESTRICTED` because screening or training currency is missing passes that gate and is refused later, by the screening-currency or training-currency check, which is what makes those two errors observable at all."

    PRD 2.8 says:
    "The subject member's `screening_status` is `CLEARED` — otherwise `ERR_SCREENING_NOT_CURRENT`."

    Design: Corner/endpoints/repositioning_the_clock_expires_the_screen_and_blocks_activation
    """
    _epoch(api)
    club = _club(api)
    headers = make_club_admin_headers(club["id"])
    get_success_data(api.publish_course(SS101, NGB_ADMIN_HEADERS), 201)
    member = _member(
        api, club["id"], "Cleo Xander", "cleo.xander@alpha.test", "1993-06-29"
    )
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
    get_success_data(
        api.post_screening_result(
            order["id"], {"vendor_disposition": "NO_RECORD"}, SCREENING_VENDOR_HEADERS
        )
    )
    adjudicated = validate_success(
        api.adjudicate_screening_order(
            order["id"],
            {"disposition": "CLEAR", "rationale": "registry return carried no records"},
            OFFICER_ADJUDICATOR_HEADERS,
        )
    )
    # 2026-08-01 plus 730 days of exactly 24 hours each is 2028-07-31.
    assert_instant_equals(adjudicated["expires_at"], "2028-07-31T00:00:00.000Z")

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
    validate_success(api.start_training(assignment["id"], headers))
    validate_success(api.complete_training(assignment["id"], {"score": 85}, headers))
    placement = get_success_data(
        api.create_coach_assignment(
            {
                "member_id": member["id"],
                "club_id": club["id"],
                "team_name": "Masters Group",
                "season_start": "2028-09-01T00:00:00Z",
                "season_end": "2029-05-31T00:00:00Z",
            },
            headers,
        ),
        201,
    )
    assert_state(placement, "status", "PENDING")

    moved = validate_success(
        api.set_clock("2028-07-31T00:00:00Z", NGB_ADMIN_HEADERS)
    )
    assert_instant_equals(moved["current_utc"], "2028-07-31T00:00:00.000Z")

    lapsed = validate_success(api.get_member(member["id"], headers))
    assert_state(lapsed, "screening_status", "EXPIRED")
    assert_state(lapsed, "training_status", "LAPSED")
    assert_state(lapsed, "membership_status", "LAPSED")
    assert_state(lapsed, "contact_eligibility", "RESTRICTED")

    validate_error(
        api.activate_coach_assignment(
            placement["id"], {"expected_member_version": lapsed["version"]}, headers
        ),
        ApiErrorId.SCREENING_NOT_CURRENT,
        409,
    )
    unchanged = validate_success(api.get_coach_assignment(placement["id"], headers))
    assert_state(unchanged, "status", "PENDING")
    assert unchanged["activated_at"] is None, (
        f"the refused activation stamped a time: {unchanged['activated_at']!r}"
    )


def test_every_governing_body_wide_collection_honours_its_foreign_key_filter(
    api: ApiClient,
) -> None:
    """Two clubs share the platform, so each cross-club list must partition on the named key.

    PRD 2.11 says:
    "Flat collections with foreign-key filters exist alongside those nested paths so that every relationship declared in this system is reverse-reachable: screening orders can be listed by `member_id`, training assignments by `member_id` and `course_code`, coach placements by `member_id` and by `club_id`, cases by `club_id`, `reported_member_id`, and `investigating_body_id`, interim measures by `case_id` and `member_id`, audits by `club_id` and by `score_variant`, findings by `audit_id`, `member_id`, and `severity`, and room stays by `club_id`, `member_id`, `trip_label`, and `room_number`."
    "Every one of these list endpoints additionally accepts a `status` filter matching that resource's own state field, and the member lists accept `screening_status`, `membership_status`, `contact_eligibility`, and `role_type`."

    PRD 2.3 says:
    "List responses carry `limit`, `offset`, `total_count`, and `has_more` inside `meta`, where `total_count` is the number of rows matching the filters before the page window is applied and `has_more` is true exactly when rows remain beyond the current window."

    PRD 3.2 says:
    "A successful order is written in status `ORDERED` with all four money fields stamped, the club's `escrow_balance_cents` is debited by `charged_cents`, the club's `version` advances by one, and the member's screening dimension moves `UNSCREENED → SCREENING_ORDERED` (or `CLEARED → SCREENING_ORDERED`, or `EXPIRED → SCREENING_ORDERED`, all three governed by the identical preconditions and side effects)."

    PRD 3.4 says:
    "The assignment is created in status `ASSIGNED` with `assigned_at` stamped from the logical clock, and `started_at`, `completed_at`, `score`, and `expires_at` all null."

    Design: Corner/endpoints/governing_body_wide_filtered_lists_resolve_every_foreign_key
    """
    _epoch(api)
    club_a = _club(api)
    club_b = _club(api, BETA_BEARS)
    get_success_data(api.publish_course(SS101, NGB_ADMIN_HEADERS), 201)
    admin_a = make_club_admin_headers(club_a["id"])
    member_a = _member(
        api, club_a["id"], "Gail Adler", "gail.adler@alpha.test", "1990-11-15"
    )
    member_b = _member(
        api,
        club_b["id"],
        "Gus Behr",
        "gus.behr@beta.test",
        "1991-12-16",
        codes=("OR",),
    )
    order = get_success_data(
        api.order_screening(
            member_a["id"],
            {
                "expedited": False,
                "expected_club_version": _live_club_version(api, club_a["id"]),
            },
            admin_a,
        ),
        201,
    )
    assignment = get_success_data(
        api.assign_training(
            {
                "member_id": member_a["id"],
                "course_code": "SS101",
                "due_at": "2026-09-01T00:00:00Z",
            },
            admin_a,
        ),
        201,
    )
    stay = get_success_data(
        api.book_room_stay(
            club_a["id"],
            {
                "occupant_kind": "ADULT_MEMBER",
                "member_id": member_a["id"],
                "trip_label": "FALL_MEET",
                "room_number": "301",
                "check_in": "2026-09-05T15:00:00Z",
                "check_out": "2026-09-07T11:00:00Z",
            },
            admin_a,
        ),
        201,
    )
    audit = get_success_data(
        api.open_club_audit(
            {
                "club_id": club_a["id"],
                "audit_period_start": "2026-01-01T00:00:00Z",
                "audit_period_end": "2026-06-30T00:00:00Z",
                "score_variant": "SELF_ATTESTED",
                "sampled_member_ids": [member_a["id"]],
            },
            COMPLIANCE_AUDITOR_HEADERS,
        ),
        201,
    )

    roster_a, roster_a_meta = validate_paginated(
        api.list_members(NGB_ADMIN_HEADERS, club_id=club_a["id"])
    )
    assert ids_of(roster_a) == [member_a["id"]], (
        f"club A roster is {ids_of(roster_a)}, expected only {member_a['id']}"
    )
    assert roster_a[0]["club_id"] == club_a["id"], (
        f"the listed member belongs to club A: {roster_a[0]['club_id']}"
    )
    assert_pagination_meta(roster_a_meta, total=1, limit=10, offset=0)

    roster_b, roster_b_meta = validate_paginated(
        api.list_members(NGB_ADMIN_HEADERS, club_id=club_b["id"])
    )
    assert ids_of(roster_b) == [member_b["id"]], (
        f"club B roster is {ids_of(roster_b)}, expected only {member_b['id']}"
    )
    assert roster_b[0]["club_id"] == club_b["id"], (
        f"the listed member belongs to club B: {roster_b[0]['club_id']}"
    )
    assert_pagination_meta(roster_b_meta, total=1, limit=10, offset=0)

    orders, _ = validate_paginated(
        api.list_screening_orders(NGB_ADMIN_HEADERS, member_id=member_a["id"])
    )
    assert ids_of(orders) == [order["id"]], (
        f"the member's orders are {ids_of(orders)}, expected only {order['id']}"
    )
    order_read = validate_success(api.get_screening_order(order["id"], NGB_ADMIN_HEADERS))
    assert order_read["id"] == order["id"], (
        f"the read-one form returned {order_read['id']}, not {order['id']}"
    )
    assert order_read["member_id"] == member_a["id"], (
        f"the order names the member: {order_read['member_id']}"
    )
    assert_state(order_read, "status", "ORDERED")

    assignments, _ = validate_paginated(
        api.list_training_assignments(
            NGB_ADMIN_HEADERS, member_id=member_a["id"], status="ASSIGNED"
        )
    )
    assert ids_of(assignments) == [assignment["id"]], (
        f"the member's assignments are {ids_of(assignments)}, expected only {assignment['id']}"
    )
    assignment_read = validate_success(
        api.get_training_assignment(assignment["id"], NGB_ADMIN_HEADERS)
    )
    assert assignment_read["id"] == assignment["id"], (
        f"the read-one form returned {assignment_read['id']}, not {assignment['id']}"
    )
    assert_state(assignment_read, "status", "ASSIGNED")
    assert assignment_read["course_code"] == "SS101", (
        f"the assignment is for SS101: {assignment_read['course_code']!r}"
    )

    stays, _ = validate_paginated(
        api.list_room_stays(
            NGB_ADMIN_HEADERS, club_id=club_a["id"], trip_label="FALL_MEET"
        )
    )
    assert ids_of(stays) == [stay["id"]], (
        f"the trip's stays are {ids_of(stays)}, expected only {stay['id']}"
    )
    stay_read = validate_success(api.get_room_stay(stay["id"], NGB_ADMIN_HEADERS))
    assert stay_read["club_id"] == club_a["id"], (
        f"the stay belongs to club A: {stay_read['club_id']}"
    )
    assert stay_read["member_id"] == member_a["id"], (
        f"the stay's occupant is the member: {stay_read['member_id']}"
    )
    assert_state(stay_read, "occupant_kind", "ADULT_MEMBER")

    audits, _ = validate_paginated(
        api.list_club_audits(NGB_ADMIN_HEADERS, club_id=club_a["id"])
    )
    assert ids_of(audits) == [audit["id"]], (
        f"club A's audits are {ids_of(audits)}, expected only {audit['id']}"
    )

    # A list that ignored its filter would hand club B's reader club A's rows.
    foreign_orders, foreign_meta = validate_paginated(
        api.list_screening_orders(NGB_ADMIN_HEADERS, member_id=member_b["id"])
    )
    assert foreign_orders == [], (
        f"club B's member has ordered nothing, yet the list returned {ids_of(foreign_orders)}"
    )
    assert_pagination_meta(foreign_meta, total=0, limit=10, offset=0)


def test_each_child_agrees_with_itself_through_its_parent_and_its_own_collection_and_pages(
    api: ApiClient,
) -> None:
    """One member's children are fetched both ways, and the findings list is walked a page at a time.

    PRD 2.11 says:
    "Several paths nest one resource under another — a member's screening orders under the member, a case's interim measures under the case, an audit's findings under the audit, a club's room stays and audits under the club."
    "Flat collections with foreign-key filters exist alongside those nested paths so that every relationship declared in this system is reverse-reachable: screening orders can be listed by `member_id`, training assignments by `member_id` and `course_code`, coach placements by `member_id` and by `club_id`, cases by `club_id`, `reported_member_id`, and `investigating_body_id`, interim measures by `case_id` and `member_id`, audits by `club_id` and by `score_variant`, findings by `audit_id`, `member_id`, and `severity`, and room stays by `club_id`, `member_id`, `trip_label`, and `room_number`."

    PRD 2.3 says:
    "`limit` defaults to 10, must be at least 1, and must not exceed 100."
    "Unless a specific list endpoint states otherwise, results are ordered by `created_at` ascending."
    "List responses carry `limit`, `offset`, `total_count`, and `has_more` inside `meta`, where `total_count` is the number of rows matching the filters before the page window is applied and `has_more` is true exactly when rows remain beyond the current window."

    PRD 3.8 says:
    "Routing moves the case `INTAKE_REVIEW → ROUTED`, stamps `investigating_body_id` and `routed_at` from the clock, and increments both the body's `open_case_count` and its `version` by one."
    "Hop one creates the measure in status `ACTIVE` with `permanence` of `TEMPORARY` and `imposed_by_user_id` set from the acting `X-User-ID`, leaving `converted_by_user_id`, `lifted_at`, `lift_reason`, and `rationale` null."

    PRD 3.6 says:
    "A new placement is written in status `PENDING`, with `activated_at`, `eligibility_snapshot_version`, and `suspended_reason` all null and `electronic_comm_authorized` false, and the club's `restricted_member_count` and `compliance_posture` are re-derived."

    Design: Corner/endpoints/sub_resource_and_collection_listings_agree_and_paginate
    """
    _epoch(api)
    club = _club(api, dict(ALPHA_AQUATICS, roster_size_attested=4))
    headers = make_club_admin_headers(club["id"])
    get_success_data(api.publish_course(SS101, NGB_ADMIN_HEADERS), 201)
    member = _member(
        api,
        club["id"],
        "Gwen Cole",
        "gwen.cole@alpha.test",
        "1986-01-17",
        role_type="ASSISTANT_COACH",
        contact=True,
    )
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
    placement = get_success_data(
        api.create_coach_assignment(
            {
                "member_id": member["id"],
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
                "reported_member_id": member["id"],
                "allegation_category": "POLICY_VIOLATION",
                "reporter_kind": "PARENT",
                "narrative": "parent reports an electronic communication concern",
                "occurred_at": "2026-07-31T22:00:00Z",
            },
            OFFICER_INTAKE_HEADERS,
        ),
        201,
    )
    routed = validate_success(
        api.route_case(
            case["id"], {"investigating_body_id": body["id"]}, OFFICER_INTAKE_HEADERS
        )
    )
    assert_state(routed, "status", "ROUTED")
    measure = get_success_data(
        api.impose_interim_measure(
            case["id"],
            {
                "member_id": member["id"],
                "measure_kind": "NO_CONTACT_DIRECTIVE",
                "effective_from": "2026-08-01T00:00:00Z",
                "effective_to": "2026-09-01T00:00:00Z",
                "expected_member_version": validate_success(
                    api.get_member(member["id"], NGB_ADMIN_HEADERS)
                )["version"],
            },
            OFFICER_IMPOSE_HEADERS,
        ),
        201,
    )
    assert_state(measure, "status", "ACTIVE")
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
    finding_one = get_success_data(
        api.write_finding(
            audit["id"],
            {
                "finding_code": "RECORDS_INCOMPLETE",
                "severity": "MINOR",
                "is_repeat": False,
            },
            COMPLIANCE_AUDITOR_HEADERS,
        ),
        201,
    )
    finding_two = get_success_data(
        api.write_finding(
            audit["id"],
            {
                "finding_code": "TRAINING_LAPSED",
                "severity": "MAJOR",
                "member_id": member["id"],
                "is_repeat": False,
            },
            COMPLIANCE_AUDITOR_HEADERS,
        ),
        201,
    )

    cases, _ = validate_paginated(
        api.list_cases(NGB_ADMIN_HEADERS, club_id=club["id"], status="ROUTED")
    )
    assert ids_of(cases) == [case["id"]], (
        f"the club's routed cases are {ids_of(cases)}, expected only {case['id']}"
    )
    assert cases[0]["investigating_body_id"] == body["id"], (
        f"the routed case names the body: {cases[0]['investigating_body_id']}"
    )

    measures, _ = validate_paginated(
        api.list_interim_measures(
            NGB_ADMIN_HEADERS, member_id=member["id"], status="ACTIVE"
        )
    )
    assert ids_of(measures) == [measure["id"]], (
        f"the member's active measures are {ids_of(measures)}, expected only {measure['id']}"
    )
    assert measures[0]["case_id"] == case["id"], (
        f"the measure hangs off the case: {measures[0]['case_id']}"
    )

    placements, _ = validate_paginated(
        api.list_coach_assignments(
            NGB_ADMIN_HEADERS, club_id=club["id"], status="PENDING"
        )
    )
    assert ids_of(placements) == [placement["id"]], (
        f"the club's pending placements are {ids_of(placements)}, expected only {placement['id']}"
    )

    club_audits, _ = validate_paginated(
        api.list_audits_of_club(club["id"], COMPLIANCE_AUDITOR_HEADERS)
    )
    assert ids_of(club_audits) == [audit["id"]], (
        f"the club's audits are {ids_of(club_audits)}, expected only {audit['id']}"
    )

    nested_orders, _ = validate_paginated(
        api.list_member_screening_orders(member["id"], NGB_ADMIN_HEADERS)
    )
    assert ids_of(nested_orders) == [order["id"]], (
        f"the member's orders are {ids_of(nested_orders)}, expected only {order['id']}"
    )

    nested_assignments, _ = validate_paginated(
        api.list_member_training_assignments(member["id"], NGB_ADMIN_HEADERS)
    )
    assert ids_of(nested_assignments) == [assignment["id"]], (
        f"the member's assignments are {ids_of(nested_assignments)}, "
        f"expected only {assignment['id']}"
    )

    findings, findings_meta = validate_paginated(
        api.list_audit_findings(COMPLIANCE_AUDITOR_HEADERS, audit_id=audit["id"])
    )
    assert ids_of(findings) == [finding_one["id"], finding_two["id"]], (
        f"the findings are listed as {ids_of(findings)}, expected the write order "
        f"{[finding_one['id'], finding_two['id']]}"
    )
    assert_pagination_meta(findings_meta, total=2, limit=10, offset=0)

    second_page, second_meta = validate_paginated(
        api.list_audit_findings(
            COMPLIANCE_AUDITOR_HEADERS, audit_id=audit["id"], limit=1, offset=1
        )
    )
    assert ids_of(second_page) == [finding_two["id"]], (
        f"the window at offset 1 holds {ids_of(second_page)}, expected {finding_two['id']}"
    )
    assert_state(second_page[0], "severity", "MAJOR")
    assert_pagination_meta(second_meta, total=2, limit=1, offset=1)
