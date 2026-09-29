"""Requests that break two rules at once, and the one error that must be reported.

Each test below arranges a single request that violates two separate guards, then
asserts the platform reports the higher-priority guard and nothing else: lodging
safety over room capacity, version pinning over training currency, and club
posture over screening currency.
"""

from __future__ import annotations

from typing import Any, Dict

from prd_bench_local_runner.testing import (
    get_success_data,
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers.api_client import ApiClient
from test_helpers.api_errors import ApiErrorId
from test_helpers.assertions import assert_counters, assert_state
from test_helpers.constants import CLOCK_EPOCH
from test_helpers.test_users import (
    COMPLIANCE_AUDITOR_HEADERS,
    NGB_ADMIN_HEADERS,
    OFFICER_ADJUDICATOR_HEADERS,
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
MINOR_STAY = {
    "occupant_kind": "MINOR_ATHLETE",
    "trip_label": "NATIONALS_2026",
    "room_number": "204",
    "check_in": "2026-09-01T15:00:00Z",
    "check_out": "2026-09-03T11:00:00Z",
}
ADULT_STAY = {
    "occupant_kind": "ADULT_MEMBER",
    "trip_label": "NATIONALS_2026",
    "room_number": "204",
    "check_in": "2026-09-02T09:00:00Z",
    "check_out": "2026-09-04T09:00:00Z",
}


def _clear_and_train(api: ApiClient, club_id: str, member_id: str, club_version: int) -> None:
    admin = make_club_admin_headers(club_id)
    order = get_success_data(
        api.order_screening(
            member_id, {"expedited": False, "expected_club_version": club_version}, admin
        ),
        201,
    )
    get_success_data(
        api.post_screening_result(
            order["id"], {"vendor_disposition": "NO_RECORD"}, SCREENING_VENDOR_HEADERS
        )
    )
    get_success_data(
        api.adjudicate_screening_order(
            order["id"],
            {"disposition": "CLEAR", "rationale": "registry return carried no records"},
            OFFICER_ADJUDICATOR_HEADERS,
        )
    )
    assignment = get_success_data(
        api.assign_training(
            {"member_id": member_id, "course_code": "SS101", "due_at": "2026-09-01T00:00:00Z"},
            admin,
        ),
        201,
    )
    get_success_data(api.start_training(assignment["id"], admin))
    get_success_data(api.complete_training(assignment["id"], {"score": 92}, admin))


def _slot_with_two_minor_athletes(api: ApiClient) -> Dict[str, Any]:
    """A room slot already holding two booked minor-athlete stays."""
    get_success_data(api.set_clock(CLOCK_EPOCH, NGB_ADMIN_HEADERS))
    club = get_success_data(api.charter_club(ALPHA_AQUATICS, NGB_ADMIN_HEADERS), 201)
    admin = make_club_admin_headers(club["id"])
    get_success_data(api.publish_course(SS101, NGB_ADMIN_HEADERS), 201)
    member = get_success_data(
        api.register_member(
            {
                "club_id": club["id"],
                "full_name": "Vera Quinn",
                "email": "vera.quinn@alpha.test",
                "role_type": "CHAPERONE",
                "has_minor_athlete_contact": False,
                "date_of_birth": "1983-03-23",
                "jurisdiction_codes": ["CA"],
            },
            admin,
        ),
        201,
    )
    _clear_and_train(api, club["id"], member["id"], club["version"])

    stays = []
    for age in (14, 15):
        payload = dict(MINOR_STAY, minor_athlete_age=age)
        stays.append(get_success_data(api.book_room_stay(club["id"], payload, admin), 201))
    return {"club": club, "member": member, "stays": stays}


def test_lodging_safety_refusal_wins_over_the_room_capacity_refusal(api: ApiClient) -> None:
    """An adult booking into a full minor-occupied slot breaks both overlap rules.

    PRD 3.7 says:
    "If any neighbour has a different `occupant_kind` from the requested booking, the request is refused with `ERR_MINOR_ADULT_LODGING_PROHIBITED`: an adult member and a minor athlete may never share a room slot across overlapping time, in either direction."
    "If the number of neighbours plus the requested booking would exceed two occupants, the request is refused with `ERR_ROOM_OCCUPANCY_CONFLICT`."
    "Because safety strictly precedes capacity, a request that trips both rules always reports the lodging-safety refusal."

    Design: Difficulty/priority_pair_validation_conflict/lodging_safety_check_outranks_room_capacity_check
    """
    setup = _slot_with_two_minor_athletes(api)
    admin = make_club_admin_headers(setup["club"]["id"])

    response = api.book_room_stay(
        setup["club"]["id"], dict(ADULT_STAY, member_id=setup["member"]["id"]), admin
    )

    error = validate_error(response, ApiErrorId.MINOR_ADULT_LODGING_PROHIBITED.value, 409)
    assert error["error_id"] != ApiErrorId.ROOM_OCCUPANCY_CONFLICT.value


def test_the_rejected_adult_booking_leaves_the_two_minor_stays_untouched(api: ApiClient) -> None:
    """The refused request writes nothing into the slot it was aimed at.

    PRD 2.8 says:
    "Because many operations are guarded by several rules at once, the platform evaluates its checks in one fixed order and reports **the first failure only**."
    Its fifteenth rule is the one that fires here:
    "No overlapping booked stay in the same room slot has a different `occupant_kind` — otherwise `ERR_MINOR_ADULT_LODGING_PROHIBITED`."

    Design: Difficulty/priority_pair_validation_conflict/lodging_safety_check_outranks_room_capacity_check
    """
    setup = _slot_with_two_minor_athletes(api)
    admin = make_club_admin_headers(setup["club"]["id"])

    validate_error(
        api.book_room_stay(
            setup["club"]["id"], dict(ADULT_STAY, member_id=setup["member"]["id"]), admin
        ),
        ApiErrorId.MINOR_ADULT_LODGING_PROHIBITED.value,
        409,
    )

    for stay in setup["stays"]:
        assert_state(validate_success(api.get_room_stay(stay["id"], NGB_ADMIN_HEADERS)), "status", "BOOKED")

    rows, _meta = validate_paginated(
        api.list_club_room_stays(setup["club"]["id"], NGB_ADMIN_HEADERS)
    )
    in_slot = [
        row
        for row in rows
        if row["trip_label"] == "NATIONALS_2026" and row["room_number"] == "204"
    ]
    assert len(in_slot) == 2
    assert [row["occupant_kind"] for row in in_slot] == ["MINOR_ATHLETE", "MINOR_ATHLETE"]


PLACEMENT = {
    "team_name": "Novice Group",
    "season_start": "2026-09-01T00:00:00Z",
    "season_end": "2027-06-01T00:00:00Z",
}


def _cleared_but_untrained_with_pending_placement(api: ApiClient) -> Dict[str, Any]:
    """A screened member who has no training assignment at all, plus a PENDING placement."""
    get_success_data(api.set_clock(CLOCK_EPOCH, NGB_ADMIN_HEADERS))
    club = get_success_data(api.charter_club(ALPHA_AQUATICS, NGB_ADMIN_HEADERS), 201)
    admin = make_club_admin_headers(club["id"])
    get_success_data(api.publish_course(SS101, NGB_ADMIN_HEADERS), 201)
    member = get_success_data(
        api.register_member(
            {
                "club_id": club["id"],
                "full_name": "Devon Kerr",
                "email": "devon.kerr@alpha.test",
                "role_type": "VOLUNTEER",
                "has_minor_athlete_contact": False,
                "date_of_birth": "1995-05-25",
                "jurisdiction_codes": ["CA"],
            },
            admin,
        ),
        201,
    )
    order = get_success_data(
        api.order_screening(
            member["id"],
            {"expedited": False, "expected_club_version": club["version"]},
            admin,
        ),
        201,
    )
    get_success_data(
        api.post_screening_result(
            order["id"], {"vendor_disposition": "NO_RECORD"}, SCREENING_VENDOR_HEADERS
        )
    )
    get_success_data(
        api.adjudicate_screening_order(
            order["id"],
            {"disposition": "CLEAR", "rationale": "registry return carried no records"},
            OFFICER_ADJUDICATOR_HEADERS,
        )
    )
    placement = get_success_data(
        api.create_coach_assignment(
            dict(PLACEMENT, member_id=member["id"], club_id=club["id"]), admin
        ),
        201,
    )
    current = get_success_data(api.get_member(member["id"], NGB_ADMIN_HEADERS))
    return {"club": club, "member": current, "placement": placement}


def test_stale_pinned_member_version_is_reported_before_the_training_gate(
    api: ApiClient,
) -> None:
    """One activation breaks version pinning and training currency eight steps apart.

    PRD 3.6 says:
    "The club administrator activates the placement supplying only `expected_member_version`, and six conditions must hold: the placement must be in status `PENDING`, else `ERR_COACH_ASSIGNMENT_INVALID_STATE`; the pinned member version must match, else `ERR_STALE_MEMBER_VERSION`; the placement's club must be at posture `OPEN`, so both `RESTRICTED` and `FROZEN` block activation; the member must not be `DISQUALIFIED`; the member must be under no permanent and no active restriction, else `ERR_CONTACT_NOT_PERMITTED`; and the member's `screening_status` must be `CLEARED` and `training_status` must be `CURRENT`, reported as `ERR_SCREENING_NOT_CURRENT` and `ERR_TRAINING_NOT_CURRENT` respectively."
    PRD 2.8 orders those two refusals, at its tenth rule:
    "The pinned parent version matches — `expected_club_version` against the club's `version`, `expected_member_version` against the member's `version` — otherwise `ERR_STALE_CLUB_VERSION` or `ERR_STALE_MEMBER_VERSION`."
    and only at its eighteenth:
    "The subject member's `training_status` is `CURRENT` — otherwise `ERR_TRAINING_NOT_CURRENT`."

    Design: Difficulty/priority_pair_validation_conflict/stale_member_version_outranks_the_training_currency_gate
    """
    setup = _cleared_but_untrained_with_pending_placement(api)
    assert_state(setup["member"], "training_status", "NEVER")
    assert_state(setup["member"], "contact_eligibility", "RESTRICTED")
    admin = make_club_admin_headers(setup["club"]["id"])

    response = api.activate_coach_assignment(
        setup["placement"]["id"],
        {"expected_member_version": setup["member"]["version"] - 1},
        admin,
    )

    error = validate_error(response, ApiErrorId.STALE_MEMBER_VERSION.value, 412)
    assert error["error_id"] != ApiErrorId.TRAINING_NOT_CURRENT.value


def test_the_placement_stays_pending_after_the_stale_version_refusal(api: ApiClient) -> None:
    """A refused activation performs none of the writes a successful one would.

    PRD 3.6 says of the successful path:
    "Activation moves the placement `PENDING → ACTIVE`, stamps `activated_at` from the clock, and pins `eligibility_snapshot_version` to the member's `version` at that instant — a durable record of exactly which eligibility view the club approved."

    Design: Difficulty/priority_pair_validation_conflict/stale_member_version_outranks_the_training_currency_gate
    """
    setup = _cleared_but_untrained_with_pending_placement(api)
    admin = make_club_admin_headers(setup["club"]["id"])

    validate_error(
        api.activate_coach_assignment(
            setup["placement"]["id"],
            {"expected_member_version": setup["member"]["version"] - 1},
            admin,
        ),
        ApiErrorId.STALE_MEMBER_VERSION.value,
        412,
    )

    placement = validate_success(
        api.get_coach_assignment(setup["placement"]["id"], NGB_ADMIN_HEADERS)
    )
    assert_state(placement, "status", "PENDING")
    assert placement["activated_at"] is None
    assert placement["eligibility_snapshot_version"] is None

    club = validate_success(api.get_club(setup["club"]["id"], NGB_ADMIN_HEADERS))
    assert_counters(club, active_assignment_count=0)


def _frozen_club_with_pending_placement(api: ApiClient) -> Dict[str, Any]:
    """A club frozen by one CRITICAL open finding, still holding a PENDING placement."""
    get_success_data(api.set_clock(CLOCK_EPOCH, NGB_ADMIN_HEADERS))
    club = get_success_data(api.charter_club(ALPHA_AQUATICS, NGB_ADMIN_HEADERS), 201)
    admin = make_club_admin_headers(club["id"])
    member = get_success_data(
        api.register_member(
            {
                "club_id": club["id"],
                "full_name": "Sam Okada",
                "email": "sam.okada@alpha.test",
                "role_type": "VOLUNTEER",
                "has_minor_athlete_contact": False,
                "date_of_birth": "1996-06-16",
                "jurisdiction_codes": ["CA"],
            },
            admin,
        ),
        201,
    )
    placement = get_success_data(
        api.create_coach_assignment(
            dict(PLACEMENT, member_id=member["id"], club_id=club["id"], team_name="Development Group"),
            admin,
        ),
        201,
    )
    audit = get_success_data(
        api.open_club_audit(
            {
                "club_id": club["id"],
                "audit_period_start": "2026-01-01T00:00:00Z",
                "audit_period_end": "2026-08-01T00:00:00Z",
                "score_variant": "SELF_ATTESTED",
                "sampled_member_ids": [],
            },
            COMPLIANCE_AUDITOR_HEADERS,
        ),
        201,
    )
    get_success_data(
        api.write_finding(
            audit["id"],
            {"finding_code": "UNSCREENED_CONTACT", "severity": "CRITICAL", "is_repeat": False},
            COMPLIANCE_AUDITOR_HEADERS,
        ),
        201,
    )
    current = get_success_data(api.get_member(member["id"], NGB_ADMIN_HEADERS))
    return {"club": club, "member": current, "placement": placement}


def test_frozen_club_posture_is_reported_before_the_screening_currency_gate(
    api: ApiClient,
) -> None:
    """Activating an unscreened member at a frozen club reports the posture, not the screening.

    PRD 2.9 says:
    "The posture is `FROZEN` when the club's `sanction_status` is either `SUSPENDED` or `TERMINATED`, or when its `critical_open_finding_count` reaches or exceeds one. A single open finding of `CRITICAL` severity anywhere in the club's audit history is therefore enough to freeze it."
    "A `FROZEN` posture blocks six operations at the club: registering a new member, ordering a screen, creating a coach placement, activating a coach placement, booking a travel room stay, and renewing a membership."
    PRD 2.8 puts that gate at its twelfth rule:
    "The governing club's `compliance_posture` permits the operation — otherwise `ERR_CLUB_POSTURE_FROZEN`."
    and the screening gate only at its seventeenth:
    "The subject member's `screening_status` is `CLEARED` — otherwise `ERR_SCREENING_NOT_CURRENT`."

    Design: Difficulty/priority_pair_validation_conflict/frozen_club_posture_outranks_screening_currency_gate
    """
    setup = _frozen_club_with_pending_placement(api)
    club = validate_success(api.get_club(setup["club"]["id"], NGB_ADMIN_HEADERS))
    assert_counters(club, critical_open_finding_count=1)
    assert_state(club, "compliance_posture", "FROZEN")
    assert_state(setup["member"], "screening_status", "UNSCREENED")

    response = api.activate_coach_assignment(
        setup["placement"]["id"],
        {"expected_member_version": setup["member"]["version"]},
        make_club_admin_headers(setup["club"]["id"]),
    )

    error = validate_error(response, ApiErrorId.CLUB_POSTURE_FROZEN.value, 409)
    assert error["error_id"] != ApiErrorId.SCREENING_NOT_CURRENT.value
    assert error["error_id"] != ApiErrorId.STALE_MEMBER_VERSION.value


def test_the_placement_stays_pending_after_the_frozen_posture_refusal(api: ApiClient) -> None:
    """The pending placement created before the freeze is left exactly as it was.

    PRD 2.9 says:
    "Placements still in status `PENDING` are deliberately excluded from that count, because nobody in a pending placement is standing in front of athletes yet; the consequence is that a member still working through screening or training does not by itself restrict their club, and the attempt to activate that member surfaces the screening-currency or training-currency refusal rather than the club-posture refusal."
    "In every blocked case the refusal is `ERR_CLUB_POSTURE_FROZEN` (HTTP 409)."

    Design: Difficulty/priority_pair_validation_conflict/frozen_club_posture_outranks_screening_currency_gate
    """
    setup = _frozen_club_with_pending_placement(api)

    validate_error(
        api.activate_coach_assignment(
            setup["placement"]["id"],
            {"expected_member_version": setup["member"]["version"]},
            make_club_admin_headers(setup["club"]["id"]),
        ),
        ApiErrorId.CLUB_POSTURE_FROZEN.value,
        409,
    )

    placement = validate_success(
        api.get_coach_assignment(setup["placement"]["id"], NGB_ADMIN_HEADERS)
    )
    assert_state(placement, "status", "PENDING")
    assert placement["activated_at"] is None

    club = validate_success(api.get_club(setup["club"]["id"], NGB_ADMIN_HEADERS))
    assert_counters(club, active_assignment_count=0, restricted_member_count=0)
