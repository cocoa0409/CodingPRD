"""Transitive cascades: partner exit and district churn (PRD §3.1, §3.2, §3.4, §3.6)."""
from test_helpers import (
    COORDINATOR,
    DIRECTOR,
    PARTNER_MGR,
    ApiErrorId,
    TUESDAYS_5,
    add_partner_with_volunteer,
    add_session,
    api_client,
    assert_kit_ledger_invariant,
    base_world,
    get_agreement,
    get_delivery,
    get_inventory,
    get_session,
    get_volunteer,
    make_delivery,
    plan_delivery,
    planned_delivery,
    schedule_delivery,
    transition_district,
    validate_error,
    validate_paginated,
    validate_success,
)


def _exit_cascade_setup():
    """Partner1's credentialed vol1 leads a PLANNED delivery with two SCHEDULED
    sessions; partner2's vol2 is credentialed and untouched by the cascade."""
    world = base_world(assemble=20)
    second = add_partner_with_volunteer()
    delivery = make_delivery(world["agreement"]["id"], world["volunteer"]["id"], enrolled_count=10)
    plan_delivery(delivery["id"])
    s1 = add_session(delivery["id"], world["volunteer"]["id"], "2026-09-08", confirm=True)
    s2 = add_session(delivery["id"], world["volunteer"]["id"], "2026-09-15", confirm=True)
    return world, second, delivery, s1, s2


def test_partner_exit_cascades_to_sessions_and_delivery(api):
    """PRD §3.2: "Exit is the consequential path, a three-link cascade. First,
    every volunteer recruited by the partner whose `engagement_status` is still
    ACTIVE becomes DEPARTED. Second, each departed volunteer's sessions in
    SCHEDULED move to NEEDS_SUBSTITUTE. Third, every delivery touched by those
    sessions recomputes its `sessions_blocked_count`, mutating the delivery and
    bumping its `version`."

    Design: Difficulty/transitive_cascade/partner_exit_cascades_volunteer_departure_session_block_delivery_recompute
    """
    world, second, delivery, s1, s2 = _exit_cascade_setup()
    resp = api_client.transition_corporate_partner(world["partner"]["id"], {"action": "EXIT"}, PARTNER_MGR)
    validate_success(resp, 200)

    vol1 = get_volunteer(world["volunteer"]["id"])
    assert vol1["engagement_status"] == "DEPARTED", "link 1: partner exit departs its volunteers"
    assert get_session(s1["id"])["status"] == "NEEDS_SUBSTITUTE", "link 2: sessions flip"
    assert get_session(s2["id"])["status"] == "NEEDS_SUBSTITUTE"
    delivery_after = get_delivery(delivery["id"])
    assert delivery_after["sessions_blocked_count"] == 2, "link 3: delivery recomputes"
    vol2 = get_volunteer(second["volunteer"]["id"])
    assert vol2["engagement_status"] == "ACTIVE", "cascade is scoped to the exited partner"


def test_partner_exit_cascade_recovers_via_substitute(api):
    """PRD §3.5: "Recovery is substitution, which moves a SCHEDULED or
    NEEDS_SUBSTITUTE session back to SCHEDULED. ... Success writes
    `volunteer_id`, recomputes `sessions_blocked_count`, and increments the
    delivery's `version` by 1."

    Design: Difficulty/transitive_cascade/partner_exit_cascades_volunteer_departure_session_block_delivery_recompute
    """
    world, second, delivery, s1, s2 = _exit_cascade_setup()
    api_client.transition_corporate_partner(world["partner"]["id"], {"action": "EXIT"}, PARTNER_MGR)
    current_version = get_delivery(delivery["id"])["version"]

    resp = api_client.substitute_session(
        s1["id"],
        {"new_volunteer_id": second["volunteer"]["id"], "expected_delivery_version": current_version},
        COORDINATOR,
    )
    data = validate_success(resp, 200)
    assert data["status"] == "SCHEDULED"
    assert data["volunteer_id"] == second["volunteer"]["id"]
    assert get_delivery(delivery["id"])["sessions_blocked_count"] == 1
    assert get_session(s2["id"])["status"] == "NEEDS_SUBSTITUTE", "the unsubstituted session stays blocked"


def _churn_cascade_setup():
    """SCHEDULED 5-session delivery (enrolled 20, 23 kits reserved of 50)."""
    world = base_world(session_count=5, program_code="JA-ECO3", min_students=10, assemble=50)
    delivery = make_delivery(world["agreement"]["id"], world["volunteer"]["id"], enrolled_count=20)
    assert delivery["required_kits"] == 23
    plan_delivery(delivery["id"])
    sessions = [
        add_session(delivery["id"], world["volunteer"]["id"], d, start_minutes=540, end_minutes=630, confirm=True)
        for d in TUESDAYS_5
    ]
    delivery = schedule_delivery(delivery["id"])
    assert delivery["status"] == "SCHEDULED"
    inv = get_inventory(world["inventory"]["id"])
    assert inv["reserved_count"] == 23 and inv["available_count"] == 27
    return world, delivery, sessions


def test_district_churn_terminates_agreement_and_cancels_delivery(api):
    """PRD §3.1: "Churn is the consequential path: every partnership agreement
    at a school of the churned district whose `status` is PROPOSED, ACTIVE, or
    AMENDMENT_PENDING transitions to TERMINATED, and each so-terminated
    agreement runs its own termination cascade — deliveries cancelled, their
    sessions cancelled, their kits released — described in §3.3 and §3.4."
    PRD §3.4: "the delivery's sessions in TENTATIVE, SCHEDULED,
    NEEDS_SUBSTITUTE, or NO_SHOW become CANCELLED"

    Design: Difficulty/transitive_cascade/district_churn_terminates_agreement_cancels_delivery_releases_kits
    """
    world, delivery, sessions = _churn_cascade_setup()
    resp = api_client.transition_district(world["district"]["id"], {"action": "CHURN"}, DIRECTOR)
    validate_success(resp, 200)

    assert get_agreement(world["agreement"]["id"])["status"] == "TERMINATED", "link 1"
    delivery_after = get_delivery(delivery["id"])
    assert delivery_after["status"] == "CANCELLED", "link 2"
    assert delivery_after["kit_status"] == "RELEASED"
    rows, meta = validate_paginated(
        api_client.list_sessions(COORDINATOR, params={"delivery_id": delivery["id"]})
    )
    assert len(rows) == 5
    assert all(r["status"] == "CANCELLED" for r in rows), "every session cancelled by the cascade"


def test_district_churn_releases_kit_reservation(api):
    """PRD §3.6: "When a delivery is cancelled, a `kit_status` of RESERVED
    becomes RELEASED and `required_kits` move from `reserved_count` back to
    `available_count`"
    PRD §2.9: "one invariant holds at all times: the lifetime `assembled_count`
    always equals the sum of the other five counters."

    Design: Difficulty/transitive_cascade/district_churn_terminates_agreement_cancels_delivery_releases_kits
    """
    world, delivery, sessions = _churn_cascade_setup()
    resp = api_client.transition_district(world["district"]["id"], {"action": "CHURN"}, DIRECTOR)
    validate_success(resp, 200)

    inv = get_inventory(world["inventory"]["id"])
    assert inv["reserved_count"] == 0, "23 reserved kits released"
    assert inv["available_count"] == 50, "full stock restored"
    assert_kit_ledger_invariant(inv)
