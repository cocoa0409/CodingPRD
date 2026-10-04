"""Breadth tests: cross-cutting layers — OCC, derived reconciliation, sweeps, pagination, sagas."""
from test_helpers import (
    ATTRACTION_HOST,
    PERMIT_CLERK,
    PLATFORM_ADMIN,
    REMIT_ADMIN,
    SERVICE_TECHNICIAN,
    SERVICE_WRITER,
    STORE_MANAGER,
    ApiErrorId,
    create_boat_unit,
    create_member,
    create_open_attraction,
    create_permit_sale,
    create_remit_batch,
    create_service_order,
    create_store,
    get_success_data,
    request_session,
    set_clock,
    validate_error,
    validate_paginated,
)


# --- cross_cutting_layers/occ_success_path_advances_the_parent_version -----

def test_an_accepted_permit_sale_advances_the_batch_version_and_invalidates_the_next_writer(api):
    """PRD §3.7: "A successful create increments the containing batch's version
    by one and re-derives the batch's live totals, so the next writer's
    expectation is immediately out of date unless they re-read."
    PRD §2.10: "A successful sale creation advances the containing batch's
    `version` by one."

    Design: Corner/cross_cutting_layers/occ_success_path_advances_the_parent_version
    """
    set_clock(api, "2026-09-01T00:00:00Z")
    store = create_store(api)
    member = create_member(api, store["id"], email="m_oc@x.com",
                           full_name="Oz Carr")
    batch = create_remit_batch(api, store["id"])
    observed_version = batch["version"]

    first = create_permit_sale(api, store["id"], member["id"], batch["id"],
                               observed_version)
    assert first["fee_cents"] == 3200, (
        f"a FISHING/RESIDENT seven-day sale prices at 3200; got {first['fee_cents']}"
    )
    assert first["status"] == "ISSUED", (
        f"a sale is created in ISSUED with its lifetime fee already computed; got "
        f"{first['status']}"
    )

    advanced = get_success_data(api.get_remit_batch(batch["id"], REMIT_ADMIN), 200)
    assert advanced["version"] > observed_version, (
        "an accepted sale advances the parent batch's version by one; got "
        f"{observed_version} then {advanced['version']}"
    )

    stale = api.create_permit_sale(
        store["id"],
        {
            "member_id": member["id"],
            "permit_type": "HUNTING",
            "residency_class": "RESIDENT",
            "term_days": 30,
            "land_access_units": 0,
            "agent_user_id": "clerk_4471",
            "permit_remit_batch_id": batch["id"],
            "expected_remit_batch_version": observed_version,
        },
        PERMIT_CLERK,
    )
    validate_error(stale, ApiErrorId.ERR_STALE_VERSION, 412)

    _, meta = validate_paginated(
        api.list_permit_sales(REMIT_ADMIN, params={"permit_remit_batch_id": batch["id"]})
    )
    assert meta["total_count"] == 1, (
        f"the rejected call created no row; got {meta['total_count']}"
    )


# --- cross_cutting_layers/derived_venue_occupancy_reconciles_after_each_release ---

def test_a_sweep_that_releases_both_parties_reconciles_the_venue_and_the_store_together(api):
    """PRD §2.4: "A derived field that is recomputed in place is a mutation like
    any other — rewriting `Store.dwell_committed_minutes`, `Store.attraction_posture`,
    `Member.points_balance` or a batch's live totals moves that row's `updated_at`
    and advances its `version`."
    PRD §3.2: "the party's capacity is released, and the member's
    `no_show_strikes` at that venue increments."

    Design: Corner/cross_cutting_layers/derived_venue_occupancy_reconciles_after_each_release
    """
    set_clock(api, "2026-09-01T00:00:00Z")
    store = create_store(api)
    attraction = create_open_attraction(api, store["id"], attraction_type="AQUARIUM",
                                        capacity_units=20, dwell_cost_minutes=30)
    first_member = create_member(api, store["id"], email="m_df1@x.com",
                                 full_name="Dell Frost")
    second_member = create_member(api, store["id"], email="m_df2@x.com",
                                  full_name="Dane Frost")
    get_success_data(
        request_session(api, store["id"], attraction["id"], first_member["id"],
                        party_size=3, slot_start_utc="2026-08-20T09:00:00Z",
                        slot_end_utc="2026-08-20T10:00:00Z"),
        201,
    )
    get_success_data(
        request_session(api, store["id"], attraction["id"], second_member["id"],
                        party_size=2, slot_start_utc="2026-08-20T11:00:00Z",
                        slot_end_utc="2026-08-20T12:00:00Z"),
        201,
    )

    before = get_success_data(api.get_attraction(attraction["id"], ATTRACTION_HOST), 200)
    assert before["in_use_units"] == 5, (
        f"the two confirmed parties hold five units; got {before['in_use_units']}"
    )
    summary_before = get_success_data(
        api.get_dwell_summary(store["id"], STORE_MANAGER), 200
    )
    assert summary_before["dwell_committed_minutes"] > 0

    get_success_data(api.ops_run(store["id"], PLATFORM_ADMIN), 200)

    after = get_success_data(api.get_attraction(attraction["id"], ATTRACTION_HOST), 200)
    assert after["in_use_units"] == 0, (
        "both slots ended before the clock, so both parties were swept and the "
        f"derived occupancy reconciled; got {after['in_use_units']}"
    )
    summary_after = get_success_data(api.get_dwell_summary(store["id"], STORE_MANAGER), 200)
    assert summary_after["dwell_committed_minutes"] == 0, (
        "the store-level derived field reconciled in the same operation; got "
        f"{summary_after['dwell_committed_minutes']}"
    )


# --- cross_cutting_layers/future_slot_session_survives_a_checkpoint --------

def test_a_session_booked_beyond_the_clock_is_deferred_rather_than_swept(api):
    """PRD §2.5: "The checkpoint is a single sweep that advances the store's"
    PRD §3.2: "A `CONFIRMED` session that reaches a checkpoint with its
    `slot_end_utc` already behind the store clock and no check-in on record is
    marked `NO_SHOW`."

    Design: Corner/cross_cutting_layers/future_slot_session_survives_a_checkpoint
    """
    set_clock(api, "2026-09-01T00:00:00Z")
    store = create_store(api)
    attraction = create_open_attraction(api, store["id"], attraction_type="AQUARIUM",
                                        capacity_units=20, dwell_cost_minutes=30)
    member = create_member(api, store["id"], email="m_fu@x.com",
                           full_name="Fern Ude")
    session = get_success_data(
        request_session(api, store["id"], attraction["id"], member["id"],
                        party_size=2, slot_start_utc="2027-06-01T10:00:00Z",
                        slot_end_utc="2027-06-01T11:00:00Z"),
        201,
    )

    get_success_data(api.ops_run(store["id"], PLATFORM_ADMIN), 200)
    still_confirmed = get_success_data(api.get_session(session["id"], ATTRACTION_HOST), 200)
    assert still_confirmed["status"] == "CONFIRMED", (
        "the slot is still a year ahead of the clock, so the sweep leaves it; got "
        f"{still_confirmed['status']}"
    )
    venue = get_success_data(api.get_attraction(attraction["id"], ATTRACTION_HOST), 200)
    assert venue["in_use_units"] == 2, "nothing was swept"

    set_clock(api, "2027-07-01T00:00:00Z")
    get_success_data(api.ops_run(store["id"], PLATFORM_ADMIN), 200)

    after = get_success_data(api.get_session(session["id"], ATTRACTION_HOST), 200)
    assert after["status"] == "NO_SHOW", (
        "once the clock moves past the slot the checkpoint sweeps it; got "
        f"{after['status']}"
    )
    released = get_success_data(api.get_attraction(attraction["id"], ATTRACTION_HOST), 200)
    assert released["in_use_units"] == 0, (
        "the deferral is explicit rather than silent, so the release happens only "
        f"after the second checkpoint; got {released['in_use_units']}"
    )


# --- cross_cutting_layers/session_list_pagination_with_status_filter -------

def test_the_status_filter_is_applied_before_the_page_boundary(api):
    """PRD §2.3: "`total_count` is the number of records matching the filter
    before paging was applied, and `has_more` reports whether further records
    remain past the returned window."
    PRD §3.1: "Session listings may be filtered by `attraction_id`, `member_id`,
    `waiver_id`, `store_id` or `status`."

    Design: Corner/cross_cutting_layers/session_list_pagination_with_status_filter
    """
    set_clock(api, "2026-09-01T00:00:00Z")
    store = create_store(api)
    attraction = create_open_attraction(api, store["id"], attraction_type="AQUARIUM",
                                        capacity_units=40, dwell_cost_minutes=30)
    member = create_member(api, store["id"], email="m_pg@x.com",
                           full_name="Page Dune")
    sessions = [
        get_success_data(
            request_session(api, store["id"], attraction["id"], member["id"],
                            party_size=1,
                            slot_start_utc=f"2026-11-01T{9 + index:02d}:00:00Z",
                            slot_end_utc=f"2026-11-01T{10 + index:02d}:00:00Z"),
            201,
        )
        for index in range(3)
    ]
    get_success_data(api.cancel_session(sessions[2]["id"], ATTRACTION_HOST), 200)

    confirmed_rows, confirmed_meta = validate_paginated(
        api.list_sessions(ATTRACTION_HOST,
                          params={"attraction_id": attraction["id"],
                                  "status": "CONFIRMED", "limit": 1, "offset": 0})
    )
    assert confirmed_meta["total_count"] == 2, (
        "the filtered total counts only the confirmed sessions rather than all "
        f"three; got {confirmed_meta['total_count']}"
    )
    assert len(confirmed_rows) == 1, (
        f"the page boundary returns exactly one row; got {len(confirmed_rows)}"
    )
    assert confirmed_meta["has_more"] is True, (
        "a further confirmed session remains past the returned window"
    )

    cancelled_rows, cancelled_meta = validate_paginated(
        api.list_sessions(ATTRACTION_HOST,
                          params={"attraction_id": attraction["id"],
                                  "status": "CANCELLED"})
    )
    assert cancelled_meta["total_count"] == 1, (
        f"one cancelled session matches; got {cancelled_meta['total_count']}"
    )
    assert [row["id"] for row in cancelled_rows] == [sessions[2]["id"]], (
        "the status filter is applied before the page boundary, so no cancelled "
        "session appears in the confirmed page"
    )


# --- cross_cutting_layers/service_intake_forward_only_saga_leaves_prior_steps_intact ---

def test_a_failed_materials_step_does_not_compensate_the_verification_it_followed(api):
    """PRD §3.6: "Advancing to `MATERIALS_ORDERED` requires the intake's
    `deposit_cents` to be at least five thousand cents inclusive; a deposit below
    that floor is refused with `ERR_OUTSTANDING_DEPOSIT_REQUIRED` (HTTP 422)."
    PRD §3.6: "its `project_charge_cents` is recomputed at every gate through the
    intake charge calculation."
    PRD §3.6: "Releasing it to the member requires the linked order to be
    `COMPLETED`."

    Design: Corner/cross_cutting_layers/service_intake_forward_only_saga_leaves_prior_steps_intact
    """
    set_clock(api, "2026-09-01T00:00:00Z")
    store = create_store(api)
    member = create_member(api, store["id"], email="m_sg@x.com",
                           full_name="Sage Rill")
    batch = create_remit_batch(api, store["id"])
    sale = create_permit_sale(api, store["id"], member["id"], batch["id"],
                              batch["version"], permit_type="HUNTING", term_days=30)
    unit = create_boat_unit(api, store["id"], stock_no="BU-SG", model_name="Bay 170",
                            unit_price_cents=4_000_000, unit_condition="USED",
                            hull_id_no="HINSG0000001", motor_price_cents=0,
                            trailer_price_cents=0)
    order = create_service_order(api, store["id"], unit["id"],
                                 order_kind="TAXIDERMY", promised_lead_days=60)
    intake = get_success_data(
        api.create_service_intake(
            store["id"],
            {"member_id": member["id"], "service_order_id": order["id"],
             "intake_kind": "TAXIDERMY", "specimen_quantity": 2,
             "quoted_lead_days": 60, "deposit_cents": 4999, "species_code": "WTDEER",
             "permit_sale_id": sale["id"]},
            SERVICE_WRITER,
        ),
        201,
    )
    verified = get_success_data(
        api.verify_intake_permit(intake["id"], SERVICE_WRITER), 200
    )
    assert verified["status"] == "PERMIT_VERIFIED"

    failed = api.order_intake_materials(intake["id"], SERVICE_WRITER)
    validate_error(failed, ApiErrorId.ERR_OUTSTANDING_DEPOSIT_REQUIRED, 422)

    retried = api.order_intake_materials(intake["id"], SERVICE_WRITER)
    validate_error(retried, ApiErrorId.ERR_OUTSTANDING_DEPOSIT_REQUIRED, 422)

    unchanged = get_success_data(api.get_service_intake(intake["id"], SERVICE_WRITER), 200)
    assert unchanged["status"] == "PERMIT_VERIFIED", (
        "the step is not rolled back to INTAKE_QUOTED and the retry is refused "
        f"the same way; got {unchanged['status']}"
    )
    assert unchanged["project_charge_cents"] == 45_000, (
        "the charge the verification step wrote is not recomputed downward; got "
        f"{unchanged['project_charge_cents']}"
    )

    order_row = get_success_data(
        api.get_service_order(order["id"], SERVICE_TECHNICIAN), 200
    )
    assert order_row["promised_lead_days"] == 60, (
        "the linked order keeps the promise that stood before the verification "
        f"step; got {order_row['promised_lead_days']}"
    )
    # One cent below the floor is the boundary case: the step is refused at
    # 4999 and would be admitted at 5000 (PRD §3.6).