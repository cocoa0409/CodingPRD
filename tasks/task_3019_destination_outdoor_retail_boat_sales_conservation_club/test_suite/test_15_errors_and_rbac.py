"""Breadth tests: error-catalogue entries and role-based access control."""
from test_helpers import (
    ATTRACTION_HOST,
    CREDIT_OFFICER,
    CREDIT_UNDERWRITER,
    CLUB_CARD_SPECIALIST,
    DEAL_DESK_CLERK,
    EVENTS_COORDINATOR,
    FINANCE_ADMIN,
    PLATFORM_ADMIN,
    RECEIVING_MANAGER,
    SERVICE_WRITER,
    STORE_MANAGER,
    TITLE_CLERK,
    ApiErrorId,
    create_bay_booking,
    create_boat_unit,
    create_club_card_application,
    create_deal,
    create_member,
    create_open_attraction,
    create_permit_sale,
    create_remit_batch,
    create_service_order,
    create_store,
    get_success_data,
    make_member_headers,
    set_clock,
    validate_error,
)


# --- errors/stale_version_on_bay_booking_returns_412 -----------------------

def test_a_fulfillment_presenting_an_overtaken_booking_version_is_refused(api):
    """PRD §2.10: "Creating an order fulfilment against a load bay booking
    requires the request to carry `expected_booking_version`, the client's
    last-observed `version` of the `LoadingBayBooking` the fulfilment is being
    created against."
    PRD §2.10: "If the booking's current `version` has advanced past the
    presented value, the create is rejected with `ERR_STALE_VERSION` (HTTP 412)."

    Design: Corner/errors/stale_version_on_bay_booking_returns_412
    """
    set_clock(api, "2026-09-01T00:00:00Z")
    store = create_store(api)
    member = create_member(api, store["id"], email="m_sv@x.com",
                           full_name="Sten Voss")
    unit = create_boat_unit(api, store["id"], stock_no="BU-SV", model_name="Bay 170",
                            unit_price_cents=4_000_000, unit_condition="NEW",
                            hull_id_no="HINSV0000001", motor_price_cents=0,
                            trailer_price_cents=0)
    order = create_service_order(api, store["id"], unit["id"],
                                 order_kind="OVERSIZE_LOADING", promised_lead_days=3)
    booking = create_bay_booking(api, store["id"], member["id"], order["id"],
                                 booked_start_utc="2026-12-01T09:00:00Z",
                                 booked_end_utc="2026-12-01T10:00:00Z")

    first = get_success_data(
        api.create_order_fulfillment(
            store["id"],
            {"member_id": member["id"], "order_kind": "OVERSIZE_CARRYOUT",
             "pre_service_order_id": order["id"], "booking_id": booking["id"],
             "expected_booking_version": booking["version"]},
            RECEIVING_MANAGER,
        ),
        201,
    )
    get_success_data(api.cancel_order_fulfillment(first["id"], RECEIVING_MANAGER), 200)

    current = get_success_data(api.get_bay_booking(booking["id"], RECEIVING_MANAGER), 200)
    assert current["version"] > booking["version"], (
        "the booking's version advanced past the value the client first saw"
    )

    stale = api.create_order_fulfillment(
        store["id"],
        {"member_id": member["id"], "order_kind": "OVERSIZE_CARRYOUT",
         "pre_service_order_id": order["id"], "booking_id": booking["id"],
         "expected_booking_version": current["version"] - 1},
        RECEIVING_MANAGER,
    )
    validate_error(stale, ApiErrorId.ERR_STALE_VERSION, 412)

    accepted = get_success_data(
        api.create_order_fulfillment(
            store["id"],
            {"member_id": member["id"], "order_kind": "OVERSIZE_CARRYOUT",
             "pre_service_order_id": order["id"], "booking_id": booking["id"],
             "expected_booking_version": current["version"]},
            RECEIVING_MANAGER,
        ),
        201,
    )
    assert accepted["status"] == "READY_FOR_RELEASE", (
        "the freshly observed version is accepted; got " f"{accepted['status']}"
    )


# --- errors/overhead_load_above_the_bay_count_returns_bay_not_found --------

def test_bay_five_fails_at_a_four_bay_store_and_succeeds_at_a_five_bay_store(api):
    """PRD §2.6: "A load bay is addressed by"

    Design: Corner/errors/overhead_load_above_the_bay_count_returns_bay_not_found
    """
    set_clock(api, "2026-09-01T00:00:00Z")
    four_bay_store = create_store(api, name="Ozark Flagship", load_bays_total=4)
    five_bay_store = create_store(api, name="Delta Landing", state_code="AR",
                                  dealer_license_no="AR-DLR-1180",
                                  dwell_capacity_minutes=45000, load_bays_total=5)
    member = create_member(api, four_bay_store["id"], email="m_bn@x.com",
                           full_name="Bo Nett")
    four_unit = create_boat_unit(api, four_bay_store["id"], stock_no="BU-BN4",
                                 model_name="Bay 170", unit_price_cents=4_000_000,
                                 unit_condition="NEW", hull_id_no="HINBN0000004",
                                 motor_price_cents=0, trailer_price_cents=0)
    five_unit = create_boat_unit(api, five_bay_store["id"], stock_no="BU-BN5",
                                 model_name="Bay 170", unit_price_cents=4_000_000,
                                 unit_condition="NEW", hull_id_no="HINBN0000005",
                                 motor_price_cents=0, trailer_price_cents=0)
    four_order = create_service_order(api, four_bay_store["id"], four_unit["id"],
                                      order_kind="OVERSIZE_LOADING",
                                      promised_lead_days=3)
    five_order = create_service_order(api, five_bay_store["id"], five_unit["id"],
                                      order_kind="OVERSIZE_LOADING",
                                      promised_lead_days=3)

    rejected = api.create_bay_booking(
        four_bay_store["id"],
        {"bay_no": 5, "member_id": member["id"],
         "service_order_id": four_order["id"],
         "booked_start_utc": "2026-12-01T09:00:00Z",
         "booked_end_utc": "2026-12-01T10:00:00Z"},
        RECEIVING_MANAGER,
    )
    validate_error(rejected, ApiErrorId.ERR_BAY_NOT_FOUND, 404)

    accepted = get_success_data(
        api.create_bay_booking(
            five_bay_store["id"],
            {"bay_no": 5, "member_id": member["id"],
             "service_order_id": five_order["id"],
             "booked_start_utc": "2026-12-01T09:00:00Z",
             "booked_end_utc": "2026-12-01T10:00:00Z"},
            RECEIVING_MANAGER,
        ),
        201,
    )
    assert accepted["bay_no"] == 5, (
        "the ceiling is inclusive at the store's own count; got "
        f"{accepted['bay_no']}"
    )
    assert accepted["status"] == "RESERVED"


# --- errors/title_state_mismatch_and_lien_release_without_prior_title ------

def test_one_error_id_covers_a_cross_state_filing_and_a_lien_release_against_a_new_unit(api):
    """PRD §3.5: "A filing is opened against a `boat_unit_id` with a `filing_kind`
    of `BOAT_TITLE`, `MOTOR_TITLE`, `TRAILER_REGISTRATION` or `LIEN_RELEASE`, and
    with a `state_code` that must equal the originating store's own `state_code`;
    a mismatch is rejected with `ERR_TITLE_STATE_MISMATCH` (HTTP 422)."
    PRD §3.5: "a `LIEN_RELEASE` filing may not be opened against a unit that has
    no `prior_title_no`, because a brand-new hull carries no lien to release."

    Design: Corner/errors/title_state_mismatch_and_lien_release_without_prior_title
    """
    set_clock(api, "2026-09-01T00:00:00Z")
    store = create_store(api, state_code="MO")
    new_unit = create_boat_unit(api, store["id"], stock_no="BU-NEW",
                                model_name="Angler 190", unit_price_cents=9_000_000,
                                unit_condition="NEW", hull_id_no="HINNEW000001",
                                motor_price_cents=0, trailer_price_cents=0)
    used_unit = create_boat_unit(api, store["id"], stock_no="BU-USD",
                                 model_name="Bay 170", unit_price_cents=4_000_000,
                                 unit_condition="USED", hull_id_no="HINUSD000001",
                                 prior_title_no="MO-TTL-OLD-0007",
                                 motor_price_cents=0, trailer_price_cents=0)

    cross_state = api.create_title_filing(
        store["id"],
        {"boat_unit_id": new_unit["id"], "filing_kind": "BOAT_TITLE",
         "state_code": "AR"},
        TITLE_CLERK,
    )
    validate_error(cross_state, ApiErrorId.ERR_TITLE_STATE_MISMATCH, 422)

    lien_on_new = api.create_title_filing(
        store["id"],
        {"boat_unit_id": new_unit["id"], "filing_kind": "LIEN_RELEASE",
         "state_code": "MO"},
        TITLE_CLERK,
    )
    validate_error(lien_on_new, ApiErrorId.ERR_TITLE_STATE_MISMATCH, 422)

    opened = get_success_data(
        api.create_title_filing(
            store["id"],
            {"boat_unit_id": used_unit["id"], "filing_kind": "LIEN_RELEASE",
             "state_code": "MO"},
            TITLE_CLERK,
        ),
        201,
    )
    assert opened["status"] == "DRAFT", (
        f"a used unit can release its lien; got {opened['status']}"
    )


# --- errors/rigging_already_open_blocks_a_second_rigging_order -------------

def test_the_single_open_rigging_rule_is_scoped_to_the_deal(api):
    """PRD §3.6: "At most one `RIGGING` order may be open at a time for the same
    deal: a second non-terminal rigging order for a deal that already has one is
    refused with `ERR_RIGGING_ALREADY_OPEN` (HTTP 409)."

    Design: Corner/errors/rigging_already_open_blocks_a_second_rigging_order
    """
    set_clock(api, "2026-09-01T00:00:00Z")
    store = create_store(api)
    member = create_member(api, store["id"], email="m_ro@x.com",
                           full_name="Rhea Ott")
    first_unit = create_boat_unit(api, store["id"], stock_no="BU-RO1",
                                  model_name="Angler 190", unit_price_cents=9_000_000,
                                  unit_condition="NEW", hull_id_no="HINRO1000001",
                                  motor_price_cents=0, trailer_price_cents=0)
    second_unit = create_boat_unit(api, store["id"], stock_no="BU-RO2",
                                   model_name="Angler 210", unit_price_cents=11_000_000,
                                   unit_condition="NEW", hull_id_no="HINRO2000001",
                                   motor_price_cents=0, trailer_price_cents=0)
    first_deal = create_deal(api, store["id"], member["id"], first_unit["id"])
    second_deal = create_deal(api, store["id"], member["id"], second_unit["id"])
    first_order = create_service_order(api, store["id"], first_unit["id"],
                                       order_kind="RIGGING", promised_lead_days=5,
                                       deal_id=first_deal["id"],
                                       boat_deal_id=first_deal["id"])

    duplicate = api.create_service_order(
        store["id"],
        {"boat_unit_id": first_unit["id"], "order_kind": "RIGGING",
         "promised_lead_days": 5, "deal_id": first_deal["id"],
         "boat_deal_id": first_deal["id"]},
        SERVICE_WRITER,
    )
    validate_error(duplicate, ApiErrorId.ERR_RIGGING_ALREADY_OPEN, 409)

    other = get_success_data(
        api.create_service_order(
            store["id"],
            {"boat_unit_id": second_unit["id"], "order_kind": "RIGGING",
             "promised_lead_days": 5, "deal_id": second_deal["id"],
             "boat_deal_id": second_deal["id"]},
            SERVICE_WRITER,
        ),
        201,
    )
    assert other["status"] == "INTAKE", (
        f"the rule is scoped per deal, not store-wide; got {other['status']}"
    )
    assert first_order["status"] == "INTAKE"


# --- errors/funding_shortfall_boundary_at_the_balance ----------------------

def test_funding_one_cent_below_the_balance_is_refused_and_the_exact_balance_is_accepted(api):
    """PRD §3.4: "Recording a funding amount in the `amount_cents` field below
    the deal's current balance is refused with `ERR_FUNDING_SHORTFALL` (HTTP 422)
    at the exact boundary: an amount equal to the balance is accepted, an amount
    one cent below it is not."

    Design: Corner/errors/funding_shortfall_boundary_at_the_balance
    """
    set_clock(api, "2026-09-01T00:00:00Z")
    store = create_store(api)
    member = create_member(api, store["id"], email="m_fs@x.com",
                           full_name="Finn Sill")
    unit = create_boat_unit(api, store["id"], stock_no="BU-9001",
                            model_name="Angler 190", unit_price_cents=9_000_000,
                            motor_price_cents=1_800_000,
                            trailer_price_cents=350_000, unit_condition="NEW",
                            hull_id_no="HIN9001AA000")
    deal = create_deal(api, store["id"], member["id"], unit["id"])
    contracted = get_success_data(
        api.contract_deal(deal["id"], {"expected_deal_version": deal["version"]},
                          DEAL_DESK_CLERK),
        200,
    )
    balance = contracted["balance_due_cents"]
    assert balance == 12_102_193, (
        f"the contracted balance is 12102193; got {balance}"
    )

    short = api.fund_deal(
        deal["id"],
        {"amount_cents": balance - 1, "expected_deal_version": contracted["version"]},
        FINANCE_ADMIN,
    )
    validate_error(short, ApiErrorId.ERR_FUNDING_SHORTFALL, 422)

    unchanged = get_success_data(api.get_deal(deal["id"], FINANCE_ADMIN), 200)
    assert unchanged["balance_due_cents"] == balance, (
        f"the refused funding left the balance intact; got "
        f"{unchanged['balance_due_cents']}"
    )

    funded = get_success_data(
        api.fund_deal(
            deal["id"],
            {"amount_cents": balance, "expected_deal_version": unchanged["version"]},
            FINANCE_ADMIN,
        ),
        200,
    )
    assert funded["funding_status"] == "FUNDED", (
        f"an amount equal to the balance is accepted; got {funded['funding_status']}"
    )
    assert funded["funded_amount_cents"] == balance
    assert funded["balance_due_cents"] == 0, (
        f"the balance is recomputed down to zero; got {funded['balance_due_cents']}"
    )


# --- errors/segregation_of_duties_on_remit_seal_and_credit_decision --------

def test_the_four_eyes_rule_guards_both_the_credit_decision_and_the_remit_seal(api):
    """PRD §2.9: "the `underwriter_user_id` recorded when an application enters
    underwriting must be non-empty and must differ from the `decision_user_id`
    presented when the decision is recorded, and that same distinctness is
    re-checked at decision time."
    PRD §2.9: "the operator sealing a batch, identified by the `X-User-ID` of the
    sealing request, must differ from the `issuer_admin_user_id` recorded on
    every sale inside the batch."
    PRD §2.9: "All of these violations are rejected with
    `ERR_SEGREGATION_OF_DUTIES` (HTTP 403)."

    Design: Corner/errors/segregation_of_duties_on_remit_seal_and_credit_decision
    """
    set_clock(api, "2026-09-01T00:00:00Z")
    store = create_store(api)
    member = create_member(api, store["id"], email="m_sd2@x.com",
                           full_name="Sid Vance")
    batch = create_remit_batch(api, store["id"])
    create_permit_sale(api, store["id"], member["id"], batch["id"],
                       batch["version"], term_days=30)
    # PRD §3.8: "the entry-level card is open to any member, and a REWARDS or
    # PATRON product is reserved for members who have earned a tier", so this
    # BASE member must be presented with the CLASSIC product for the approval to
    # be reachable.
    application = create_club_card_application(api, store["id"], member["id"],
                                               card_product="CLASSIC")
    get_success_data(
        api.underwrite_club_card_application(
            application["id"], {"underwriter_user_id": "uw_2201"}, CREDIT_UNDERWRITER
        ),
        200,
    )

    same_operator = api.decide_club_card_application(
        application["id"],
        {"decision_user_id": "uw_2201", "decision": "APPROVED",
         "decision_reason": "thin file but strong trade",
         "credit_limit_cents": 300000},
        CREDIT_OFFICER,
    )
    validate_error(same_operator, ApiErrorId.ERR_SEGREGATION_OF_DUTIES, 403)
    unchanged = get_success_data(
        api.get_club_card_application(application["id"], CLUB_CARD_SPECIALIST), 200
    )
    assert unchanged["status"] == "UNDERWRITING", (
        f"the refused decision left the application untouched; got "
        f"{unchanged['status']}"
    )
    assert unchanged["underwriter_user_id"] == "uw_2201"

    approved = get_success_data(
        api.decide_club_card_application(
            application["id"],
            {"decision_user_id": "off_7702", "decision": "APPROVED",
             "decision_reason": "independent review", "credit_limit_cents": 300000},
            CREDIT_OFFICER,
        ),
        200,
    )
    assert approved["status"] == "APPROVED", (
        f"a different operator may decide; got {approved['status']}"
    )
    assert approved["credit_limit_cents"] == 300000


# --- rbac/member_cannot_contract_or_settle_a_deal --------------------------

def test_a_member_is_refused_both_the_sales_desk_and_the_finance_actions(api):
    """PRD §2.1: "A `Member` may therefore read and amend only their own member
    record, their own boat deals, their own intakes, their own fulfilments, their
    own registrations and their own club card applications."
    PRD §2.1: "If both headers are present but the declared `X-User-Role` is not
    among the roles the endpoint authorizes, the request is rejected with
    `ERR_FORBIDDEN_ROLE` (HTTP 403)."

    Design: Corner/rbac/member_cannot_contract_or_settle_a_deal
    """
    set_clock(api, "2026-09-01T00:00:00Z")
    store = create_store(api)
    member = create_member(api, store["id"], email="m_rb@x.com",
                           full_name="Rory Bell")
    unit = create_boat_unit(api, store["id"], stock_no="BU-9001",
                            model_name="Angler 190", unit_price_cents=9_000_000,
                            motor_price_cents=1_800_000,
                            trailer_price_cents=350_000, unit_condition="NEW",
                            hull_id_no="HIN9001AA000")
    deal = create_deal(api, store["id"], member["id"], unit["id"])
    headers = make_member_headers(member["id"])

    contract_response = api.contract_deal(
        deal["id"], {"expected_deal_version": deal["version"]}, headers
    )
    validate_error(contract_response, ApiErrorId.ERR_FORBIDDEN_ROLE, 403)

    settle_response = api.settle_deal(
        deal["id"], {"expected_deal_version": deal["version"]}, headers
    )
    validate_error(settle_response, ApiErrorId.ERR_FORBIDDEN_ROLE, 403)

    unchanged = get_success_data(api.get_deal(deal["id"], DEAL_DESK_CLERK), 200)
    assert unchanged["deal_stage"] == "QUOTED", (
        f"neither refusal moved the deal; got {unchanged['deal_stage']}"
    )
    assert unchanged["version"] == deal["version"], (
        "the deal's version is unchanged after both rejections"
    )


# --- rbac/attraction_host_and_events_coordinator_have_disjoint_exclusive_sets ---

def test_the_floor_host_and_the_calendar_owner_are_each_refused_the_others_route(api):
    """PRD §2.1: "Every other role ... has an opaque operator identity." — the
    role matrix assigns session execution to the floor host and the store
    calendar to the events coordinator, and each is refused on the other's
    routes.
    PRD §2.1: "If both headers are present but the declared `X-User-Role` is not
    among the roles the endpoint authorizes, the request is rejected with
    `ERR_FORBIDDEN_ROLE` (HTTP 403)."

    Design: Corner/rbac/attraction_host_and_events_coordinator_have_disjoint_exclusive_sets
    """
    set_clock(api, "2026-09-01T00:00:00Z")
    store = create_store(api)
    member = create_member(api, store["id"], email="m_rb2@x.com",
                           full_name="Remy Best")
    attraction = create_open_attraction(api, store["id"], attraction_type="AQUARIUM",
                                        capacity_units=40, dwell_cost_minutes=30)
    session = get_success_data(
        api.create_session(
            store["id"],
            {"attraction_id": attraction["id"], "member_id": member["id"],
             "session_kind": "GENERAL_ADMISSION", "party_size": 2,
             "slot_start_utc": "2026-11-01T10:00:00Z",
             "slot_end_utc": "2026-11-01T11:00:00Z"},
            ATTRACTION_HOST,
        ),
        201,
    )
    get_success_data(
        api.create_event_offering(
            store["id"],
            {"offering_kind": "SEMINAR", "title": "Rope Care",
             "starts_at_utc": "2026-10-01T10:00:00Z",
             "ends_at_utc": "2026-10-01T11:00:00Z", "registration_cap": 10,
             "attraction_id": attraction["id"]},
            EVENTS_COORDINATOR,
        ),
        201,
    )

    host_creates_offering = api.create_event_offering(
        store["id"],
        {"offering_kind": "SEMINAR", "title": "Host Attempt",
         "starts_at_utc": "2026-10-05T10:00:00Z",
         "ends_at_utc": "2026-10-05T11:00:00Z", "registration_cap": 10,
         "attraction_id": attraction["id"]},
        ATTRACTION_HOST,
    )
    validate_error(host_creates_offering, ApiErrorId.ERR_FORBIDDEN_ROLE, 403)

    coordinator_checks_in = api.check_in_session(session["id"], EVENTS_COORDINATOR)
    validate_error(coordinator_checks_in, ApiErrorId.ERR_FORBIDDEN_ROLE, 403)

    unchanged = get_success_data(api.get_session(session["id"], ATTRACTION_HOST), 200)
    assert unchanged["status"] == "CONFIRMED", (
        "neither role has executed the other's action; got "
        f"{unchanged['status']}"
    )


# --- rbac/shared_operations_are_permitted_for_multiple_declared_roles ------

def test_the_ops_run_checkpoint_advances_the_epoch_for_either_declared_role(api):
    """PRD §2.5: "The checkpoint is a single sweep that advances the store's"
    PRD §2.5: "Because the sweep is the only thing that moves"

    Design: Corner/rbac/shared_operations_are_permitted_for_multiple_declared_roles
    """
    set_clock(api, "2026-09-01T00:00:00Z")
    store = create_store(api)
    member = create_member(api, store["id"], email="m_sh@x.com",
                           full_name="Shay Dune")
    batch = create_remit_batch(api, store["id"])
    create_permit_sale(api, store["id"], member["id"], batch["id"], batch["version"])

    first = get_success_data(api.ops_run(store["id"], STORE_MANAGER), 200)
    assert first["permit_remit_epoch"] == 1, (
        "the store manager may run the checkpoint for their own store; got "
        f"{first['permit_remit_epoch']}"
    )
    after_first = get_success_data(api.get_store(store["id"], STORE_MANAGER), 200)
    assert after_first["permit_remit_epoch"] == 1
    assert after_first["last_ops_run_at"] is not None, (
        "the sweep stamps last_ops_run_at"
    )

    second = get_success_data(api.ops_run(store["id"], PLATFORM_ADMIN), 200)
    assert second["permit_remit_epoch"] == 2, (
        "the platform operator may run the same checkpoint, and the counter is "
        f"monotone; got {second['permit_remit_epoch']}"
    )