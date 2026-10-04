"""Breadth tests: validation rules and the errors they surface."""
from test_helpers import (
    ATTRACTION_HOST,
    DEAL_DESK_CLERK,
    EVENTS_COORDINATOR,
    NON_EXISTENT_UUID,
    PLATFORM_ADMIN,
    RECEIVING_MANAGER,
    SERVICE_WRITER,
    STORE_MANAGER,
    ApiErrorId,
    create_boat_unit,
    create_event_offering,
    create_member,
    create_open_attraction,
    REMIT_ADMIN,
    make_member_headers,
    create_permit_sale,
    create_remit_batch,
    create_service_intake,
    create_service_order,
    create_store,
    create_waiver,
    get_success_data,
    request_session,
    set_clock,
    validate_error,
    validate_paginated,
)


# --- validations/missing_auth_header_returns_unauthenticated ---------------

def test_a_store_write_without_the_role_header_is_rejected_before_the_body_is_parsed(api):
    """PRD §2.1: "If either header is absent on an endpoint whose authorized
    roles do not include `Anonymous`, the request is rejected with
    `ERR_UNAUTHENTICATED` (HTTP 401)."
    PRD §2.11: "missing headers yield `ERR_UNAUTHENTICATED` (HTTP 401) before any
    other rule."

    Design: Corner/validations/missing_auth_header_returns_unauthenticated
    """
    anonymous = {}
    response = api.create_store(
        {
            "name": "Ozark Flagship",
            "state_code": "MO",
            "dealer_license_no": "MO-DLR-4417",
            "dwell_capacity_minutes": 60000,
            "load_bays_total": 4,
        },
        anonymous,
    )
    validate_error(response, ApiErrorId.ERR_UNAUTHENTICATED, 401)

    rows, meta = validate_paginated(api.list_stores(PLATFORM_ADMIN))
    assert meta["total_count"] == 0, (
        f"no store row was created; got total_count {meta['total_count']}"
    )
    assert rows == []


# --- validations/role_not_permitted_returns_forbidden_role -----------------

def test_a_member_attempting_to_open_a_venue_is_refused_by_role(api):
    """PRD §2.1: "If both headers are present but the declared `X-User-Role` is
    not among the roles the endpoint authorizes, the request is rejected with
    `ERR_FORBIDDEN_ROLE` (HTTP 403)."

    Design: Corner/validations/role_not_permitted_returns_forbidden_role
    """
    set_clock(api, "2026-09-01T00:00:00Z")
    store = create_store(api)
    member = create_member(api, store["id"], email="m_rf@x.com",
                           full_name="Rae Fenn")
    attraction = create_open_attraction(api, store["id"])
    planned = get_success_data(
        api.create_attraction(store["id"],
                              {"attraction_type": "MUSEUM", "capacity_units": 20,
                               "dwell_cost_minutes": 30},
                              STORE_MANAGER),
        201,
    )

    response = api.open_attraction(planned["id"], make_member_headers(member["id"]))
    validate_error(response, ApiErrorId.ERR_FORBIDDEN_ROLE, 403)

    unchanged = get_success_data(api.get_attraction(planned["id"], STORE_MANAGER), 200)
    assert unchanged["status"] == "PLANNED", (
        f"the refused open left the venue unopened; got {unchanged['status']}"
    )
    assert attraction["status"] == "OPEN"


# --- validations/expired_waiver_blocks_a_lane_session ---------------------

def test_a_waiver_lapsing_on_the_current_instant_does_not_admit_a_lane_session(api):
    """PRD §3.2: "a waiver that is not `SIGNED`, or whose `expires_on` is earlier
    than the store clock's current instant, is rejected with
    `ERR_WAIVER_EXPIRED` (HTTP 422)."
    PRD §3.2: "The expiry check is evaluated against the logical clock, so an
    operation performed while the clock sits at the store's startup instant of
    the first of September 2026 will accept a waiver that a later checkpoint
    would expire."

    Design: Corner/validations/expired_waiver_blocks_a_lane_session
    """
    set_clock(api, "2026-09-01T00:00:00Z")
    store = create_store(api)
    attraction = create_open_attraction(api, store["id"], attraction_type="ARCHERY_RANGE",
                                        capacity_units=12, dwell_cost_minutes=45)
    member = create_member(api, store["id"], email="m_wx@x.com",
                           full_name="Wren Axe")
    waiver = create_waiver(api, store["id"], member["id"],
                           activity_scope="ARCHERY_RANGE",
                           signed_at_utc="2026-08-31T00:00:00Z", waiver_term_days=1)

    read_back = get_success_data(api.get_waiver(waiver["id"], ATTRACTION_HOST), 200)
    assert read_back["expires_on"].startswith("2026-09-01"), (
        "a one-day waiver signed on 2026-08-31 lapses at the current instant; got "
        f"{read_back['expires_on']}"
    )
    assert read_back["status"] == "SIGNED"

    response = request_session(api, store["id"], attraction["id"], member["id"],
                               session_kind="ARCHERY_LANE", party_size=2, lane_no=4,
                               waiver_id=waiver["id"])
    validate_error(response, ApiErrorId.ERR_WAIVER_EXPIRED, 422)

    _, meta = validate_paginated(
        api.list_sessions(ATTRACTION_HOST, params={"member_id": member["id"]})
    )
    assert meta["total_count"] == 0, (
        f"no session row was created for the member; got {meta['total_count']}"
    )


# --- validations/taxidermy_intake_without_hunting_permit_is_rejected ------

def test_a_hunting_permit_verifies_the_intake_where_a_fishing_permit_does_not(api):
    """PRD §3.6: "Advancing a taxidermy intake past `INTAKE_QUOTED` requires a
    `permit_sale_id` referencing a permit sale whose `permit_type` is `HUNTING`
    or `ARCHERY_RANGE` and whose `status` is `ISSUED` or `REMITTED` — a
    lawful-take permit."
    PRD §3.6: "The refusal is `ERR_PERMIT_VERIFICATION_REQUIRED` (HTTP 422), and
    it is enforced both when the intake is created and when the permit
    verification step is taken."
    PRD §3.6: "A stage uplift is added — nothing at `INTAKE_QUOTED` or
    `PERMIT_VERIFIED`."

    Design: Corner/validations/taxidermy_intake_without_hunting_permit_is_rejected
    """
    set_clock(api, "2026-09-01T00:00:00Z")
    store = create_store(api)
    member = create_member(api, store["id"], email="m_tx@x.com",
                           full_name="Tuck Rill")
    batch = create_remit_batch(api, store["id"])
    fishing = create_permit_sale(api, store["id"], member["id"], batch["id"],
                                 batch["version"], permit_type="FISHING",
                                 term_days=30)
    refreshed = get_success_data(api.get_remit_batch(batch["id"], REMIT_ADMIN), 200)
    hunting = create_permit_sale(api, store["id"], member["id"], batch["id"],
                                 refreshed["version"], permit_type="HUNTING",
                                 term_days=30)
    unit = create_boat_unit(api, store["id"], stock_no="BU-TX", model_name="Bay 170",
                            unit_price_cents=4_000_000, unit_condition="USED",
                            hull_id_no="HINTX0000001", motor_price_cents=0,
                            trailer_price_cents=0)
    fishing_order = create_service_order(api, store["id"], unit["id"],
                                         order_kind="TAXIDERMY", promised_lead_days=60)
    hunting_order = create_service_order(api, store["id"], unit["id"],
                                         order_kind="TAXIDERMY", promised_lead_days=60)

    # The gate fires at creation too, so the wrong-type permit is presented at
    # the create call rather than reaching the verification step.
    rejected = api.create_service_intake(
        store["id"],
        {
            "member_id": member["id"],
            "service_order_id": fishing_order["id"],
            "intake_kind": "TAXIDERMY",
            "specimen_quantity": 2,
            "quoted_lead_days": 60,
            "deposit_cents": 5000,
            "species_code": "WTDEER",
            "permit_sale_id": fishing["id"],
        },
        SERVICE_WRITER,
    )
    validate_error(rejected, ApiErrorId.ERR_PERMIT_VERIFICATION_REQUIRED, 422)

    hunting_intake = create_service_intake(
        api, store["id"], member["id"], hunting_order["id"], intake_kind="TAXIDERMY",
        specimen_quantity=2, quoted_lead_days=60, deposit_cents=5000,
        species_code="WTDEER", permit_sale_id=hunting["id"])
    advanced = get_success_data(
        api.verify_intake_permit(hunting_intake["id"], SERVICE_WRITER), 200
    )
    assert advanced["status"] == "PERMIT_VERIFIED", (
        f"a hunting permit satisfies the gate; got {advanced['status']}"
    )
    assert advanced["project_charge_cents"] == 45_000, (
        "the taxidermy base carries no specimen uplift before curing; got "
        f"{advanced['project_charge_cents']}"
    )


# --- validations/deposit_below_floor_blocks_materials_order ----------------

def test_one_cent_below_the_deposit_floor_separates_the_two_outcomes(api):
    """PRD §3.6: "Advancing to `MATERIALS_ORDERED` requires the intake's
    `deposit_cents` to be at least five thousand cents inclusive; a deposit below
    that floor is refused with `ERR_OUTSTANDING_DEPOSIT_REQUIRED` (HTTP 422)."

    Design: Corner/validations/deposit_below_floor_blocks_materials_order
    """
    set_clock(api, "2026-09-01T00:00:00Z")
    store = create_store(api)
    member = create_member(api, store["id"], email="m_dp@x.com",
                           full_name="Dell Pike")
    unit = create_boat_unit(api, store["id"], stock_no="BU-DP", model_name="Bay 170",
                            unit_price_cents=4_000_000, unit_condition="USED",
                            hull_id_no="HINDP0000001", motor_price_cents=0,
                            trailer_price_cents=0)
    below_order = create_service_order(api, store["id"], unit["id"],
                                       order_kind="OUTFITTING", promised_lead_days=20)
    at_order = create_service_order(api, store["id"], unit["id"],
                                    order_kind="OUTFITTING", promised_lead_days=20)
    below = get_success_data(
        api.verify_intake_permit(
            create_service_intake(api, store["id"], member["id"], below_order["id"],
                                  intake_kind="OUTFITTING", specimen_quantity=1,
                                  quoted_lead_days=20,
                                  deposit_cents=4999)["id"],
            SERVICE_WRITER),
        200,
    )
    at_floor = get_success_data(
        api.verify_intake_permit(
            create_service_intake(api, store["id"], member["id"], at_order["id"],
                                  intake_kind="OUTFITTING", specimen_quantity=1,
                                  quoted_lead_days=20,
                                  deposit_cents=5000)["id"],
            SERVICE_WRITER),
        200,
    )

    response = api.order_intake_materials(below["id"], SERVICE_WRITER)
    validate_error(response, ApiErrorId.ERR_OUTSTANDING_DEPOSIT_REQUIRED, 422)
    unchanged = get_success_data(api.get_service_intake(below["id"], SERVICE_WRITER), 200)
    assert unchanged["status"] == "PERMIT_VERIFIED", (
        f"the refused intake holds its stage; got {unchanged['status']}"
    )

    advanced = get_success_data(
        api.order_intake_materials(at_floor["id"], SERVICE_WRITER), 200
    )
    assert advanced["status"] == "MATERIALS_ORDERED", (
        f"the deposit floor is inclusive; got {advanced['status']}"
    )
    assert advanced["project_charge_cents"] == 27_000, (
        "the 12000-cent outfitting base plus the 15000-cent materials uplift, with "
        f"no specimen uplift yet; got {advanced['project_charge_cents']}"
    )


# --- validations/appraised_at_is_immutable_once_written -------------------

def test_the_server_stamped_appraisal_instant_cannot_be_rewritten(api):
    """PRD §3.5: "its `appraised_at_utc` is immutable from the moment it is
    written: any write that attempts to rewrite that server-stamped instant is
    rejected with `ERR_TYPE_IMMUTABLE` (HTTP 422) and nothing else on the row
    changes, even if the same request also carried a legitimate revision to the
    offer."

    Design: Corner/validations/appraised_at_is_immutable_once_written
    """
    set_clock(api, "2026-09-01T00:00:00Z")
    store = create_store(api)
    member = create_member(api, store["id"], email="m_im2@x.com",
                           full_name="Ira Mott")
    unit = create_boat_unit(api, store["id"], stock_no="BU-IM", model_name="Bay 170",
                            unit_price_cents=4_000_000, unit_condition="USED",
                            hull_id_no="HINIM0000001", motor_price_cents=0,
                            trailer_price_cents=0)
    appraisal = get_success_data(
        api.create_appraisal(store["id"], {"member_id": member["id"],
                                           "boat_unit_id": unit["id"],
                                           "offer_amount_cents": 40000},
                             DEAL_DESK_CLERK),
        201,
    )
    assert appraisal["appraised_at_utc"].startswith("2026-09-01"), (
        f"the server stamps the appraisal at the clock instant; got "
        f"{appraisal['appraised_at_utc']}"
    )

    response = api.revise_appraisal(appraisal["id"],
                                    {"appraised_at_utc": "2020-01-01T00:00:00Z"},
                                    DEAL_DESK_CLERK)
    validate_error(response, ApiErrorId.ERR_TYPE_IMMUTABLE, 422)

    unchanged = get_success_data(api.get_appraisal(appraisal["id"], DEAL_DESK_CLERK), 200)
    assert unchanged["appraised_at_utc"] == appraisal["appraised_at_utc"], (
        "the timestamp is untouched after the refusal"
    )
    assert unchanged["offer_amount_cents"] == 40000
    assert unchanged["status"] == "PENDING"


# --- validations/business_validation_precedes_missing_parent_check --------

def test_a_deal_naming_an_unknown_hull_fails_the_existence_check_not_the_shape_check(api):
    """PRD §2.6: "A reference to a missing attraction, member, waiver, boat unit,
    appraisal, title filing, boat deal, permit sale, remit batch, club card
    application, point event, service order, service intake, event offering,
    event registration, bay booking or order fulfilment fails with
    `ERR_RESOURCE_NOT_FOUND` (HTTP 404)."
    PRD §2.11: "the general request-shape rule at `p24` ... rejects absent
    required fields, invalid enum members and negative numeric fields with
    `ERR_INVALID_REQUEST` (HTTP 400)."

    Design: Corner/validations/business_validation_precedes_missing_parent_check
    """
    set_clock(api, "2026-09-01T00:00:00Z")
    store = create_store(api)
    member = create_member(api, store["id"], email="m_vo@x.com",
                           full_name="Vale Ostrom")

    response = api.create_deal(store["id"],
                               {"member_id": member["id"],
                                "boat_unit_id": NON_EXISTENT_UUID},
                               DEAL_DESK_CLERK)
    validate_error(response, ApiErrorId.ERR_RESOURCE_NOT_FOUND, 404)

    _, meta = validate_paginated(
        api.list_deals(DEAL_DESK_CLERK, params={"store_id": store["id"]})
    )
    assert meta["total_count"] == 0, "no deal row was created"


# --- validations/activity_scope_mismatch_is_a_safety_failure --------------

def test_a_waiver_of_the_wrong_activity_scope_does_not_satisfy_the_gate(api):
    """PRD §3.2: "A venue that requires a waiver will not confirm a session
    presented without one: a request that names no `waiver_id`, or names one
    whose scope does not match the venue, is rejected with `ERR_WAIVER_REQUIRED`
    (HTTP 422)."

    Design: Corner/validations/activity_scope_mismatch_is_a_safety_failure
    """
    set_clock(api, "2026-09-01T00:00:00Z")
    store = create_store(api)
    attraction = create_open_attraction(api, store["id"], attraction_type="SIMULATOR",
                                        capacity_units=6, dwell_cost_minutes=25)
    member = create_member(api, store["id"], email="m_am@x.com",
                           full_name="Alma Rill")
    pond_waiver = create_waiver(api, store["id"], member["id"],
                                activity_scope="CATCH_AND_RELEASE_POND",
                                signed_at_utc="2026-08-01T00:00:00Z",
                                waiver_term_days=365)

    response = request_session(api, store["id"], attraction["id"], member["id"],
                               session_kind="SIMULATOR", party_size=2, lane_no=2,
                               waiver_id=pond_waiver["id"])
    validate_error(response, ApiErrorId.ERR_WAIVER_REQUIRED, 422)

    checked = get_success_data(api.get_waiver(pond_waiver["id"], ATTRACTION_HOST), 200)
    assert checked["activity_scope"] == "CATCH_AND_RELEASE_POND"
    assert checked["status"] == "SIGNED", (
        "the waiver is live at the clock, so only the scope mismatch caused the "
        f"failure; got {checked['status']}"
    )
    _, meta = validate_paginated(
        api.list_sessions(ATTRACTION_HOST, params={"member_id": member["id"]})
    )
    assert meta["total_count"] == 0


# --- validations/future_conflict_temporal_validation_on_bay_booking -------

def test_a_booking_conflicting_with_a_future_reservation_is_refused_now(api):
    """PRD §3.6: "another booking on the same store and same bay number whose interval overlaps the requested interval widened by a fifteen-minute turnover buffer at each end is refused with"

    Design: Corner/validations/future_conflict_temporal_validation_on_bay_booking
    """
    set_clock(api, "2026-09-01T00:00:00Z")
    store = create_store(api)
    member = create_member(api, store["id"], email="m_fv@x.com",
                           full_name="Faye Voss")
    unit = create_boat_unit(api, store["id"], stock_no="BU-FV", model_name="Bay 170",
                            unit_price_cents=4_000_000, unit_condition="NEW",
                            hull_id_no="HINFV0000001", motor_price_cents=0,
                            trailer_price_cents=0)
    order = create_service_order(api, store["id"], unit["id"],
                                 order_kind="OVERSIZE_LOADING", promised_lead_days=3)
    existing = get_success_data(
        api.create_bay_booking(
            store["id"],
            {"bay_no": 3, "member_id": member["id"], "service_order_id": order["id"],
             "booked_start_utc": "2026-12-01T09:00:00Z",
             "booked_end_utc": "2026-12-01T10:00:00Z"},
            RECEIVING_MANAGER,
        ),
        201,
    )

    response = api.create_bay_booking(
        store["id"],
        {"bay_no": 3, "member_id": member["id"], "service_order_id": order["id"],
         "booked_start_utc": "2026-12-01T09:30:00Z",
         "booked_end_utc": "2026-12-01T10:30:00Z"},
        RECEIVING_MANAGER,
    )
    validate_error(response, ApiErrorId.ERR_BAY_BOOKING_CONFLICT, 409)

    accepted = get_success_data(
        api.create_bay_booking(
            store["id"],
            {"bay_no": 3, "member_id": member["id"], "service_order_id": order["id"],
             "booked_start_utc": "2026-12-02T09:00:00Z",
             "booked_end_utc": "2026-12-02T10:00:00Z"},
            RECEIVING_MANAGER,
        ),
        201,
    )
    assert accepted["status"] == "RESERVED", (
        f"the following day is free; got {accepted['status']}"
    )
    unchanged = get_success_data(api.get_bay_booking(existing["id"], RECEIVING_MANAGER), 200)
    assert unchanged["status"] == "RESERVED", (
        "the untouched reservation still holds its slot"
    )


# --- validations/aggregate_validation_passes_individually_but_fails_collectively ---

def test_each_offering_is_acceptable_alone_and_the_failure_appears_only_in_aggregate(api):
    """PRD §2.11: "the dwell-budget gate at `p18`."
    PRD §3.3: "If that recomputation would leave the free minutes below zero, the
    publication is refused outright with `ERR_DWELL_BUDGET_EXCEEDED` (HTTP 409)
    and no field on the offering changes at all — the event stays `DRAFT` and the
    budget is untouched."

    Design: Corner/validations/aggregate_validation_passes_individually_but_fails_collectively
    """
    set_clock(api, "2026-09-01T00:00:00Z")
    store = create_store(api, dwell_capacity_minutes=40)
    first = create_event_offering(api, store["id"], offering_kind="SEMINAR",
                                  title="Rigging Basics",
                                  starts_at_utc="2026-10-01T10:00:00Z",
                                  ends_at_utc="2026-10-01T11:00:00Z",
                                  registration_cap=30)
    second = create_event_offering(api, store["id"], offering_kind="SEMINAR",
                                   title="Sonar Basics",
                                   starts_at_utc="2026-10-02T10:00:00Z",
                                   ends_at_utc="2026-10-02T11:00:00Z",
                                   registration_cap=30)

    published = get_success_data(
        api.publish_event_offering(first["id"], EVENTS_COORDINATOR), 200
    )
    summary = get_success_data(api.get_dwell_summary(store["id"], STORE_MANAGER), 200)
    assert summary["dwell_committed_minutes"] == published["dwell_charge_minutes"], (
        "the first publish commits exactly its own charge; got "
        f"{summary['dwell_committed_minutes']}"
    )
    assert summary["dwell_committed_minutes"] <= 40, (
        "the first offering is individually acceptable; got "
        f"{summary['dwell_committed_minutes']}"
    )

    response = api.publish_event_offering(second["id"], EVENTS_COORDINATOR)
    validate_error(response, ApiErrorId.ERR_DWELL_BUDGET_EXCEEDED, 409)

    unchanged = get_success_data(
        api.get_event_offering(second["id"], EVENTS_COORDINATOR), 200
    )
    assert unchanged["status"] == "DRAFT", (
        "the budget check runs before the state write; got " f"{unchanged['status']}"
    )
    still_published = get_success_data(
        api.get_event_offering(first["id"], EVENTS_COORDINATOR), 200
    )
    assert still_published["status"] == "PUBLISHED", (
        "the aggregate failure did not roll back the earlier offering"
    )


# --- validations/conditional_validation_applies_only_to_workshops ---------

def test_the_cap_gate_is_skipped_entirely_when_the_offering_is_uncapped(api):
    """PRD §3.3: "The cap must be positive for a seminar or a kids workshop and
    must be exactly zero for a free demo, so the cap field doubles as the signal
    for whether the event is capped at all."
    PRD §3.3: "only while the offering's current `confirmed_count` plus the
    requested `seats` stays at or below the `registration_cap` when that cap is
    positive."

    Design: Corner/validations/conditional_validation_applies_only_to_workshops
    """
    set_clock(api, "2026-09-01T00:00:00Z")
    store = create_store(api)
    member = create_member(api, store["id"], email="m_cv@x.com",
                           full_name="Cora Venn")
    free_demo = get_success_data(
        api.publish_event_offering(
            create_event_offering(api, store["id"], offering_kind="FREE_DEMO",
                                  title="Open Deck",
                                  starts_at_utc="2026-10-01T10:00:00Z",
                                  ends_at_utc="2026-10-01T11:00:00Z",
                                  registration_cap=0)["id"],
            EVENTS_COORDINATOR),
        200,
    )
    capped = create_event_offering(api, store["id"], offering_kind="SEMINAR",
                                   title="Knot School",
                                   starts_at_utc="2026-10-02T10:00:00Z",
                                   ends_at_utc="2026-10-02T11:00:00Z",
                                   registration_cap=2)
    get_success_data(api.publish_event_offering(capped["id"], EVENTS_COORDINATOR), 200)

    # The zero cap signals "uncapped", so the same oversized volume that a
    # capped offering refuses is admitted outright here.
    free_registration = get_success_data(
        api.create_event_registration(store["id"], free_demo["id"],
                                      {"member_id": member["id"], "seats": 50},
                                      EVENTS_COORDINATOR),
        201,
    )
    confirmed = get_success_data(
        api.confirm_event_registration(free_demo["id"], free_registration["id"],
                                       EVENTS_COORDINATOR),
        200,
    )
    assert confirmed["status"] == "CONFIRMED", (
        "an uncapped offering skips the cap gate entirely, so the seats are "
        f"confirmed; got {confirmed['status']}"
    )
    refreshed = get_success_data(
        api.get_event_offering(free_demo["id"], EVENTS_COORDINATOR), 200
    )
    assert refreshed["confirmed_count"] == 50, (
        f"the whole uncapped volume was seated; got {refreshed['confirmed_count']}"
    )

    blocked = api.create_event_registration(
        store["id"], capped["id"], {"member_id": member["id"], "seats": 15},
        EVENTS_COORDINATOR,
    )
    validate_error(blocked, ApiErrorId.ERR_REGISTRATION_CAP_EXCEEDED, 409)
    capped_row = get_success_data(
        api.get_event_offering(capped["id"], EVENTS_COORDINATOR), 200
    )
    assert capped_row["confirmed_count"] == 0, (
        f"the refused seats consumed nothing; got {capped_row['confirmed_count']}"
    )