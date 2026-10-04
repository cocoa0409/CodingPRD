"""Breadth tests: endpoint contracts — computed reads, cross-reference reads, actions."""
from test_helpers import (
    ATTRACTION_HOST,
    EVENTS_COORDINATOR,
    PLATFORM_ADMIN,
    STORE_MANAGER,
    ApiErrorId,
    create_member,
    create_open_attraction,
    create_store,
    create_waiver,
    get_success_data,
    request_session,
    set_clock,
    validate_error,
    validate_paginated,
)


# --- endpoints/computed_read_dwell_summary_matches_the_derivation ----------

def test_the_dwell_summary_is_a_pure_read_that_agrees_with_the_store_row(api):
    """PRD §2.7: "The store exposes a computed dwell read that reports
    `dwell_capacity_minutes`, `dwell_committed_minutes`, `dwell_free_minutes`,
    `attraction_posture`, the over-capacity venue count and the expired-waiver
    venue count without mutating any row."

    Design: Corner/endpoints/computed_read_dwell_summary_matches_the_derivation
    """
    set_clock(api, "2026-09-01T00:00:00Z")
    store = create_store(api)
    attraction = create_open_attraction(api, store["id"], attraction_type="AQUARIUM",
                                        capacity_units=40, dwell_cost_minutes=30)
    member = create_member(api, store["id"], email="m_cr@x.com",
                           full_name="Cato Reed")
    session = get_success_data(
        request_session(api, store["id"], attraction["id"], member["id"],
                        party_size=4, slot_start_utc="2026-11-01T10:00:00Z",
                        slot_end_utc="2026-11-01T11:00:00Z"),
        201,
    )

    first = get_success_data(api.get_dwell_summary(store["id"], STORE_MANAGER), 200)
    second = get_success_data(api.get_dwell_summary(store["id"], STORE_MANAGER), 200)
    assert first["dwell_committed_minutes"] == session["dwell_charge_minutes"], (
        "the committed total is the live session's charge; got "
        f"{first['dwell_committed_minutes']}"
    )
    assert first["dwell_free_minutes"] == 60_000 - first["dwell_committed_minutes"]
    assert first["attraction_posture"] == second["attraction_posture"] == "OPEN"
    assert first["dwell_committed_minutes"] == second["dwell_committed_minutes"]

    store_row = get_success_data(api.get_store(store["id"], STORE_MANAGER), 200)
    assert store_row["dwell_committed_minutes"] == first["dwell_committed_minutes"], (
        "the derived field on the store agrees with the summary; got "
        f"{store_row['dwell_committed_minutes']}"
    )
    assert store_row["attraction_posture"] == first["attraction_posture"]


# --- endpoints/expired_waiver_venues_are_counted_in_the_summary -----------

def test_the_expired_waiver_venue_count_alone_drives_the_restricted_branch(api):
    """PRD §2.7: "The second is the number of the store's venues that require a
    waiver and that hold at least one `CONFIRMED` session whose referenced waiver
    has an `expires_on` instant earlier than the store clock's current instant."
    PRD §2.7: "it is `RESTRICTED` in that case even when the budget is healthy."

    Design: Corner/endpoints/expired_waiver_venues_are_counted_in_the_summary
    """
    set_clock(api, "2026-08-31T00:00:00Z")
    store = create_store(api)
    attraction = create_open_attraction(api, store["id"], attraction_type="ARCHERY_RANGE",
                                        capacity_units=12, dwell_cost_minutes=45)
    member = create_member(api, store["id"], email="m_ew@x.com",
                           full_name="Elle Ward")
    waiver = create_waiver(api, store["id"], member["id"],
                           activity_scope="ARCHERY_RANGE",
                           signed_at_utc="2026-08-30T00:00:00Z", waiver_term_days=5)
    session = get_success_data(
        request_session(api, store["id"], attraction["id"], member["id"],
                        session_kind="ARCHERY_LANE", party_size=2, lane_no=5,
                        waiver_id=waiver["id"]),
        201,
    )
    set_clock(api, "2026-09-05T00:00:00Z")

    before = get_success_data(api.get_dwell_summary(store["id"], STORE_MANAGER), 200)
    assert before["attraction_posture"] == "RESTRICTED", (
        "an expired-waiver venue forces the restricted branch even on a healthy "
        f"budget; got {before['attraction_posture']}"
    )
    assert before["dwell_committed_minutes"] > 0, "the budget is far from exhausted"

    get_success_data(api.ops_run(store["id"], PLATFORM_ADMIN), 200)

    after = get_success_data(api.get_dwell_summary(store["id"], STORE_MANAGER), 200)
    assert after["dwell_committed_minutes"] == before["dwell_committed_minutes"], (
        "the sweep released no budget, so the branch reading is driven by the "
        f"expired-waiver venue alone; got {after['dwell_committed_minutes']}"
    )
    expired = get_success_data(api.get_waiver(waiver["id"], ATTRACTION_HOST), 200)
    assert expired["status"] == "EXPIRED", (
        f"the checkpoint moved the lapsed waiver to EXPIRED; got {expired['status']}"
    )
    # The expired-waiver counter tracks SIGNED rows only, so once the sweep wrote
    # the lapse the venue stops forcing the branch — provable by releasing the
    # one confirmed session that holds it, which leaves the budget unchanged.
    get_success_data(api.cancel_session(session["id"], ATTRACTION_HOST), 200)
    released = get_success_data(api.get_dwell_summary(store["id"], STORE_MANAGER), 200)
    assert released["attraction_posture"] == "OPEN", (
        "with the expired waiver no longer forcing it and the budget healthy, the "
        f"store returns to OPEN; got {released['attraction_posture']}"
    )


# --- endpoints/cross_reference_filtered_reads_resolve_both_directions -----

def test_the_nested_venue_read_and_the_flat_filtered_read_return_the_same_rows(api):
    """PRD §2.6: "the sessions and the fulfilments presented under a given
    waiver can each be listed in their own right" — see §3.1: "Session listings
    may be filtered by `attraction_id`, `member_id`, `waiver_id`, `store_id` or
    `status`."

    Design: Corner/endpoints/cross_reference_filtered_reads_resolve_both_directions
    """
    set_clock(api, "2026-09-01T00:00:00Z")
    store = create_store(api)
    aquarium = create_open_attraction(api, store["id"], attraction_type="AQUARIUM",
                                      capacity_units=40, dwell_cost_minutes=30)
    museum = create_open_attraction(api, store["id"], attraction_type="MUSEUM",
                                    capacity_units=30, dwell_cost_minutes=20)
    member = create_member(api, store["id"], email="m_cx@x.com",
                           full_name="Cass Reed")
    first = get_success_data(
        request_session(api, store["id"], aquarium["id"], member["id"], party_size=2,
                        slot_start_utc="2026-11-01T10:00:00Z",
                        slot_end_utc="2026-11-01T11:00:00Z"),
        201,
    )
    second = get_success_data(
        request_session(api, store["id"], museum["id"], member["id"], party_size=2,
                        slot_start_utc="2026-11-02T10:00:00Z",
                        slot_end_utc="2026-11-02T11:00:00Z"),
        201,
    )

    nested_rows, nested_meta = validate_paginated(
        api.list_attraction_sessions(aquarium["id"], ATTRACTION_HOST)
    )
    assert nested_meta["total_count"] == 1, (
        f"the nested venue read holds exactly one session; got {nested_meta['total_count']}"
    )
    assert [row["id"] for row in nested_rows] == [first["id"]]

    flat_rows, flat_meta = validate_paginated(
        api.list_sessions(ATTRACTION_HOST, params={"attraction_id": museum["id"]})
    )
    assert flat_meta["total_count"] == 1, (
        f"the flat filtered read holds the other session; got {flat_meta['total_count']}"
    )
    assert [row["id"] for row in flat_rows] == [second["id"]]

    combined = {row["id"] for row in nested_rows} | {row["id"] for row in flat_rows}
    assert combined == {first["id"], second["id"]}, (
        "the union of the two responses contains both sessions and no duplicates"
    )


# --- endpoints/action_endpoint_confirm_enforces_its_preconditions ---------

def test_confirming_a_registration_reads_the_offerings_state_not_only_its_own(api):
    """PRD §3.3: "An `EventsCoordinator` then confirms the seats, which is
    permitted only while the offering is `PUBLISHED`."
    PRD §2.11: "a target entity not in any source state the requested transition declares yields"

    Design: Corner/endpoints/action_endpoint_confirm_enforces_its_preconditions
    """
    set_clock(api, "2026-09-01T00:00:00Z")
    store = create_store(api)
    member = create_member(api, store["id"], email="m_ae@x.com",
                           full_name="Ansel Reed")
    offering = get_success_data(
        api.create_event_offering(
            store["id"],
            {"offering_kind": "SEMINAR", "title": "Trailer Care",
             "starts_at_utc": "2026-10-01T10:00:00Z",
             "ends_at_utc": "2026-10-01T11:00:00Z", "registration_cap": 20},
            EVENTS_COORDINATOR,
        ),
        201,
    )
    registration = get_success_data(
        api.create_event_registration(store["id"], offering["id"],
                                      {"member_id": member["id"], "seats": 2},
                                      EVENTS_COORDINATOR),
        201,
    )

    response = api.confirm_event_registration(offering["id"], registration["id"],
                                              EVENTS_COORDINATOR)
    validate_error(response, ApiErrorId.ERR_INVALID_STATE, 409)
    unchanged = get_success_data(
        api.get_event_registration(registration["id"], EVENTS_COORDINATOR), 200
    )
    assert unchanged["status"] == "REGISTERED", (
        f"the refused confirm left the registration alone; got {unchanged['status']}"
    )

    get_success_data(api.publish_event_offering(offering["id"], EVENTS_COORDINATOR), 200)
    confirmed = get_success_data(
        api.confirm_event_registration(offering["id"], registration["id"],
                                       EVENTS_COORDINATOR),
        200,
    )
    assert confirmed["status"] == "CONFIRMED", (
        f"the identical confirm succeeds after publish; got {confirmed['status']}"
    )
    refreshed = get_success_data(
        api.get_event_offering(offering["id"], EVENTS_COORDINATOR), 200
    )
    assert refreshed["confirmed_count"] == 2


# --- endpoints/cancel_offering_bulk_cancels_registrations_and_credits_points ---

def test_cancelling_an_offering_cancels_every_live_registration_and_credits_by_party_size(api):
    """PRD §3.3: "every registration still in `REGISTERED`, `CONFIRMED` or
    `WAITLISTED` moves to `CANCELLED`, each of those registrations grants its
    member the same two hundred fifty points where it covered two or more seats."
    PRD §3.3: "the offering's confirmed count is rewound to zero, and the
    offering's dwell charge is released back to the store budget."

    Design: Corner/endpoints/cancel_offering_bulk_cancels_registrations_and_credits_points
    """
    set_clock(api, "2026-09-01T00:00:00Z")
    store = create_store(api)
    pair_member = create_member(api, store["id"], email="m_bk1@x.com",
                                full_name="Bly Reed")
    single_member = create_member(api, store["id"], email="m_bk2@x.com",
                                  full_name="Ben Reed")
    offering = get_success_data(
        api.publish_event_offering(
            get_success_data(
                api.create_event_offering(
                    store["id"],
                    {"offering_kind": "KIDS_WORKSHOP", "title": "Fly Tying",
                     "starts_at_utc": "2026-10-01T10:00:00Z",
                     "ends_at_utc": "2026-10-01T11:30:00Z", "registration_cap": 90},
                    EVENTS_COORDINATOR,
                ),
                201,
            )["id"],
            EVENTS_COORDINATOR,
        ),
        200,
    )
    pair_registration = get_success_data(
        api.create_event_registration(store["id"], offering["id"],
                                      {"member_id": pair_member["id"], "seats": 2},
                                      EVENTS_COORDINATOR),
        201,
    )
    get_success_data(
        api.confirm_event_registration(offering["id"], pair_registration["id"],
                                       EVENTS_COORDINATOR),
        200,
    )
    single_registration = get_success_data(
        api.create_event_registration(store["id"], offering["id"],
                                      {"member_id": single_member["id"], "seats": 1},
                                      EVENTS_COORDINATOR),
        201,
    )
    get_success_data(
        api.confirm_event_registration(offering["id"], single_registration["id"],
                                       EVENTS_COORDINATOR),
        200,
    )

    before = get_success_data(
        api.get_event_offering(offering["id"], EVENTS_COORDINATOR), 200
    )
    assert before["confirmed_count"] == 3, (
        f"three seats are confirmed before the cancel; got {before['confirmed_count']}"
    )

    get_success_data(api.cancel_event_offering(offering["id"], EVENTS_COORDINATOR), 200)

    after = get_success_data(
        api.get_event_offering(offering["id"], EVENTS_COORDINATOR), 200
    )
    assert after["status"] == "CANCELLED"
    assert after["confirmed_count"] == 0, (
        f"the confirmed count is rewound to zero; got {after['confirmed_count']}"
    )
    pair_row = get_success_data(
        api.get_event_registration(pair_registration["id"], EVENTS_COORDINATOR), 200
    )
    single_row = get_success_data(
        api.get_event_registration(single_registration["id"], EVENTS_COORDINATOR), 200
    )
    assert pair_row["status"] == "CANCELLED"
    assert single_row["status"] == "CANCELLED"

    pair_member_row = get_success_data(
        api.get_member(pair_member["id"], STORE_MANAGER), 200
    )
    single_member_row = get_success_data(
        api.get_member(single_member["id"], STORE_MANAGER), 200
    )
    assert pair_member_row["points_balance"] == 250, (
        "a two-seat cancellation grants 250 consolation points; got "
        f"{pair_member_row['points_balance']}"
    )
    assert single_member_row["points_balance"] == 0, (
        "the credit is conditional on party size, so a single seat grants "
        f"nothing; got {single_member_row['points_balance']}"
    )

    summary = get_success_data(api.get_dwell_summary(store["id"], STORE_MANAGER), 200)
    assert summary["dwell_committed_minutes"] == 0, (
        "the offering's dwell charge was released back to the store budget; got "
        f"{summary['dwell_committed_minutes']}"
    )