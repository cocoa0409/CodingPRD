"""Validation ordering, optimistic concurrency, deferred actions and selector policy."""
import pytest

from test_helpers import (
    api_client,
    validate_success,
    validate_error,
    get_success_data,
    TEST_USERS,
    make_site_coordinator_headers,
    make_product,
    make_program,
    make_site,
    make_batch,
    register_carton,
    release_batch,
    certify_site,
    open_window,
    setup_entitled_site,
    submit_order,
    anchor_delivered_carton,
    anchor_thawed_carton,
    make_family,
    make_delivered_second_site,
    get_entitlement,
    get_order,
    current_window_version_for_order,
    get_carton,
    get_shipper,
    get_program,
)


def _accept(order_id, window_version, cartons=1, deliver_at="2026-09-01T06:00:00Z"):
    return api_client.accept_site_order(
        order_id,
        {"accepted_cartons": cartons, "deliver_at": deliver_at,
         "expected_allocation_window_version": window_version},
        TEST_USERS["distribution_planner_headers"])


def test_state_precondition_beats_the_capacity_conflict(api):
    """PRD §2.9: "The parent's operative state is checked next (`ERR_INVALID_STATE`
    when the entity's `order_status`, `acceptance_status`, `temperature_state`, or
    `packing_status` does not admit the operation".

    PRD §3.3: "that the site's capacity at the requested `deliver_at` can hold the
    accepted cartons for the required entry type (otherwise
    `ERR_SITE_CAPACITY_INSUFFICIENT`)".

    Design: Difficulty/priority_pair_validation_conflict/state_precondition_beats_cold_chain_safety_conflict
    """
    ctx = setup_entitled_site()
    small = make_site(ctx["program"]["id"], site_code="MI-RIV-02",
                      site_name="Riverside Field Unit", ultra_cold_capacity_cartons=1,
                      refrigerated_capacity_cartons=1, expected_weekly_doses=600)
    certify_site(small["id"], certificate_number="CERT-MI-0002")

    order = submit_order(ctx["entitlement"]["id"], small["id"],
                         requested_cartons=1, requested_doses=0)
    _accept(order["id"], current_window_version_for_order(order["id"]), 1)
    dispatch = get_success_data(api.create_dispatch(
        {"site_order_id": order["id"], "storage_site_id": small["id"],
         "entry_route": "DIRECT_ULTRA_COLD"}, TEST_USERS["logistics_operator_headers"]))

    order3 = submit_order(ctx["entitlement"]["id"], small["id"],
                          requested_cartons=1, requested_doses=0)

    draft = api.deliver_dispatch(
        dispatch["id"], {"arrived_at": "2026-09-01T06:00:00Z"},
        make_site_coordinator_headers(small["id"]))
    validate_error(draft, "ERR_INVALID_STATE", expected_status=409)

    capacity = _accept(order3["id"], current_window_version_for_order(order3["id"]), 1)
    err = validate_error(capacity, "ERR_SITE_CAPACITY_INSUFFICIENT", expected_status=422)
    assert err["error_id"] != "ERR_BELOW_MIN_ORDER"


def test_entitlement_exhaustion_beats_the_program_standing_conflict(api):
    """PRD §3.3: "`requested_cartons` must not exceed the entitlement's
    `available_cartons`, or it is refused with `ERR_ORDER_EXCEEDS_ENTITLEMENT`."

    PRD §2.8: "A submission by a program that is not `OPEN` is refused with
    `ERR_PROGRAM_NOT_OPEN` (HTTP 422)".

    Design: Difficulty/priority_pair_validation_conflict/entitlement_exhaustion_beats_program_standing_conflict
    """
    from test_helpers import make_reporting_period

    ctx = setup_entitled_site()
    depot = make_site(ctx["program"]["id"], site_code="MI-RIV-06",
                      site_name="Riverside Depot", ultra_cold_capacity_cartons=4,
                      refrigerated_capacity_cartons=4, expected_weekly_doses=800)
    certify_site(depot["id"], certificate_number="CERT-MI-0006")

    # The entitlement has ten cartons (PRD §3.2: 20 weekly cartons less the
    # half-hold-back of 10).  Eight are committed so two remain, which is what lets
    # the two blocks below be told apart: the over-large request breaches the
    # entitlement, while the request that fits passes the entitlement check and
    # reaches the program-standing gate behind it.
    holder = submit_order(ctx["entitlement"]["id"], ctx["site"]["id"],
                          requested_cartons=8, requested_doses=0)
    held = _accept(holder["id"], current_window_version_for_order(holder["id"]), 8)
    assert held.status_code < 400, held.text
    assert get_entitlement(ctx["entitlement"]["id"])["held_cartons"] == 8
    assert get_entitlement(ctx["entitlement"]["id"])["available_cartons"] == 2

    # PRD §3.9: five points per lapsed period, tier one once the score passes
    # twenty.  Five unsubmitted reporting periods past their `period_end` reach that
    # boundary under either propagation mode, so the assertion does not turn on a
    # reading of §2.9 that PRD leaves open.
    from test_helpers import add_lapsed_periods
    add_lapsed_periods(ctx["program"]["id"], count=5)
    api.assess_program_standing(
        ctx["program"]["id"],
        {"as_of": "2026-09-01T00:00:00Z", "propagation_mode": "AFTER_CYCLE"},
        TEST_USERS["regulatory_affairs_headers"])
    # Either gate reading refuses the submission with ERR_PROGRAM_NOT_OPEN, so the
    # assertion does not turn on which tier the weighted score lands in.
    assert get_program(ctx["program"]["id"])["standing_status"] in ("RESTRICTED", "FROZEN")

    over = get_success_data(api.create_site_order(
        {"allocation_entitlement_id": ctx["entitlement"]["id"],
         "storage_site_id": depot["id"], "requested_cartons": 3,
         "requested_doses": 0}, make_site_coordinator_headers(depot["id"])))
    fiscal = api.submit_site_order(over["id"], make_site_coordinator_headers(depot["id"]))
    err = validate_error(fiscal, "ERR_ORDER_EXCEEDS_ENTITLEMENT", expected_status=422)
    assert err["error_id"] != "ERR_PROGRAM_NOT_OPEN"

    fitting = get_success_data(api.create_site_order(
        {"allocation_entitlement_id": ctx["entitlement"]["id"],
         "storage_site_id": depot["id"], "requested_cartons": 1,
         "requested_doses": 0}, make_site_coordinator_headers(depot["id"])))
    standing = api.submit_site_order(fitting["id"], make_site_coordinator_headers(depot["id"]))
    validate_error(standing, "ERR_PROGRAM_NOT_OPEN", expected_status=422)

    assert get_entitlement(ctx["entitlement"]["id"])["held_cartons"] == 8


def test_shipper_seal_rejects_a_stale_shipper_version(api):
    """PRD §2.6: "Sealing a cold chain shipper carries `expected_shipper_version` and
    is refused with the same `ERR_STALE_VERSION` (HTTP 412) when it does not match the
    shipper's current `version`; a shipper's version advances when a carton is
    attached or a temperature reading is recorded".

    Design: Corner/cross_cutting_complexity_layers/shipper_seal_rejects_a_stale_shipper_version
    """
    from test_helpers import create_shipper_payload, create_logger_reading_payload

    ctx = anchor_delivered_carton()
    site_id = ctx["site"]["id"]
    order = submit_order(ctx["entitlement"]["id"], site_id)
    accepted = _accept(order["id"], current_window_version_for_order(order["id"]), 2)
    assert accepted.status_code < 400, accepted.text

    dispatch = get_success_data(api.create_dispatch(
        {"site_order_id": order["id"], "storage_site_id": site_id,
         "entry_route": "DIRECT_ULTRA_COLD"}, TEST_USERS["logistics_operator_headers"]))
    api.pack_dispatch(dispatch["id"], TEST_USERS["logistics_operator_headers"])
    # A serial unique across shippers (PRD §3.4), since the fixture already holds
    # SH-0001 on its own dispatch.
    shipper = get_success_data(api.create_shipper(
        create_shipper_payload(dispatch["id"], shipper_serial="SH-0009"),
        TEST_USERS["logistics_operator_headers"]))

    stale_v = get_success_data(api.get_shipper(
        shipper["id"], TEST_USERS["logistics_operator_headers"]))["version"]
    api.attach_carton_to_shipper(shipper["id"], {"carton_id": ctx["carton"]["id"]},
                                 TEST_USERS["logistics_operator_headers"])
    api.create_logger_reading(
        create_logger_reading_payload(shipper["id"], recorded_at="2026-09-01T01:00:00Z"),
        TEST_USERS["logistics_operator_headers"])
    fresh_v = get_success_data(api.get_shipper(
        shipper["id"], TEST_USERS["logistics_operator_headers"]))["version"]
    assert fresh_v > stale_v

    stale = api.seal_shipper(shipper["id"], {"expected_shipper_version": stale_v},
                             TEST_USERS["logistics_operator_headers"])
    validate_error(stale, "ERR_STALE_VERSION", expected_status=412)

    sealed = validate_success(api.seal_shipper(
        shipper["id"], {"expected_shipper_version": fresh_v},
        TEST_USERS["logistics_operator_headers"]), 200)
    assert sealed["packing_status"] == "SEALED"
    assert sealed["version"] == fresh_v + 1
    assert sealed["packing_completed_at"] == "2026-09-01T00:00:00Z"


def test_order_acceptance_rejects_a_stale_window_version(api):
    """PRD §2.6: "The acceptance of a site order against an entitlement carries
    `expected_allocation_window_version`, and the request is refused with
    `ERR_STALE_VERSION` (HTTP 412) when that value does not match the parent
    `AllocationWindow`'s current `version`."

    Design: Corner/cross_cutting_complexity_layers/order_acceptance_rejects_a_stale_window_version
    """
    ctx = setup_entitled_site()
    site_id = ctx["site"]["id"]
    order_a = submit_order(ctx["entitlement"]["id"], site_id,
                           requested_cartons=2, requested_doses=0)
    order_b = submit_order(ctx["entitlement"]["id"], site_id,
                           requested_cartons=3, requested_doses=0)
    stale_win_v = get_success_data(api.get_allocation_window(
        ctx["window"]["id"], TEST_USERS["distribution_planner_headers"]))["version"]

    first = _accept(order_a["id"], stale_win_v, 2)
    assert first.status_code < 400, first.text
    assert get_success_data(first)["accepted_cartons"] == 2

    second = _accept(order_b["id"], stale_win_v, 3)
    validate_error(second, "ERR_STALE_VERSION", expected_status=412)

    fresh_win_v = get_success_data(api.get_allocation_window(
        ctx["window"]["id"], TEST_USERS["distribution_planner_headers"]))["version"]
    assert fresh_win_v > stale_win_v

    third = _accept(order_b["id"], fresh_win_v, 3)
    assert third.status_code < 400, third.text
    assert get_entitlement(ctx["entitlement"]["id"])["held_cartons"] == 5


def test_ops_cycle_lapses_the_elapsed_reservation_and_the_window(api):
    """PRD §2.11: "That cycle lapses every `HELD` reservation whose `end_at` is at or
    before the logical clock, closes every allocation window whose `closes_at` is at
    or before the logical clock while its `status` is `OPEN`".

    Design: Corner/cross_cutting_complexity_layers/ops_cycle_lapses_the_elapsed_reservation_and_the_window
    """
    from test_helpers import create_reservation_payload

    ctx = setup_entitled_site()
    reservation = validate_success(api.create_carton_storage_reservation(
        create_reservation_payload(ctx["site"]["id"], ctx["carton"]["id"],
                                   reserved_capacity_cartons=2,
                                   start_at="2026-09-03T09:00:00Z",
                                   end_at="2026-09-03T10:00:00Z",
                                   resolve_method="RESERVATION_BOUNDARY"),
        TEST_USERS["distribution_planner_headers"]), 201)

    api_client.set_clock({"current_utc": "2026-09-04T00:00:00Z"},
                         TEST_USERS["platform_admin_headers"])
    before = get_success_data(api.get_carton_storage_reservation(
        reservation["id"], TEST_USERS["distribution_planner_headers"]))
    assert before["status"] == "HELD"

    cycle = validate_success(api.run_cycle(TEST_USERS["platform_admin_headers"]), 200)
    assert cycle["lapsed_reservation_count"] == 1
    assert cycle["lapsed_window_count"] == 1

    after = get_success_data(api.get_carton_storage_reservation(
        reservation["id"], TEST_USERS["distribution_planner_headers"]))
    assert after["status"] == "LAPSED"

    assert get_success_data(api.get_allocation_window(
        ctx["window"]["id"], TEST_USERS["distribution_planner_headers"]))["status"] == "CLOSED"
    assert get_entitlement(ctx["entitlement"]["id"])["acceptance_status"] == "LAPSED"


def test_derived_inventory_and_dose_fields_reconcile_after_a_dispense(api):
    """PRD §3.9: "`administrative_remaining_doses` is the signed sum of
    `quantity_doses` over the carton's entries, clamped at zero."

    PRD §3.3: "`usable_doses` and `administrative_remaining_doses` sum the
    corresponding figures over its physical, non-in-transit cartons".

    Design: Corner/cross_cutting_complexity_layers/derived_inventory_and_dose_fields_reconcile_after_a_dispense
    """
    ctx = anchor_thawed_carton()
    site_id = ctx["site"]["id"]

    from test_helpers import usable_doses, add_ledger_entry

    # The anchored fixture puts ONE carton of 1170 doses at the site, so the site's
    # dose position is that carton's own dose count -- the accepted-doses anchor of
    # 2340 belongs to a two-carton acceptance and is not this fixture.
    before = usable_doses(site_id, make_site_coordinator_headers(site_id))
    assert before["usable_doses"] == 1170
    assert before["administrative_remaining_doses"] == 1170

    add_ledger_entry(ctx["carton"]["id"], "ADMINISTER", 117,
                     "2026-09-01T09:00:00Z",
                     as_headers=make_site_coordinator_headers(site_id))

    after = usable_doses(site_id, make_site_coordinator_headers(site_id))
    assert after["usable_doses"] == 1053
    assert after["administrative_remaining_doses"] == 1053
    assert get_carton(ctx["carton"]["id"])["administrative_remaining_doses"] == 1053
    # PRD §3.9: "`remaining_doses` is the carton's `doses_per_carton` less the doses
    # removed by its entries" -- and an ADMINISTER begins the vial, it does not remove
    # doses from the physical pack, so the count stands.
    assert get_carton(ctx["carton"]["id"])["remaining_doses"] == 1170


def test_hub_selector_is_deterministic_and_refuses_an_empty_candidate_set(api):
    """PRD §3.4: "Selection follows an eligibility filter — sites linked to the
    ordering site through a carton-family membership, with `storage_capability`
    `ULTRA_COLD`, `equipment_certified` true at the logical clock, `inventory_status`
    not `FROZEN`, and not the ordering site itself — and ranks the survivors by
    `expected_weekly_doses` ascending with a tie-break of `created_at` ascending and
    never identity. An empty candidate set is refused with `ERR_NO_ELIGIBLE_SITE`."

    Design: Corner/cross_cutting_complexity_layers/hub_selector_is_deterministic_and_refuses_an_empty_candidate_set
    """
    ctx = setup_entitled_site()
    order = submit_order(ctx["entitlement"]["id"], ctx["site"]["id"])
    accepted = _accept(order["id"], current_window_version_for_order(order["id"]), 2)
    assert accepted.status_code < 400, accepted.text

    hub_high = make_site(ctx["program"]["id"], site_code="MI-RIV-05",
                         site_name="Riverside Annex", ultra_cold_capacity_cartons=4,
                         refrigerated_capacity_cartons=4, expected_weekly_doses=1200)
    certify_site(hub_high["id"], certificate_number="CERT-MI-0005")
    hub_low = make_site(ctx["program"]["id"], site_code="MI-RIV-07",
                        site_name="Riverside Hub", ultra_cold_capacity_cartons=4,
                        refrigerated_capacity_cartons=4, expected_weekly_doses=400)
    certify_site(hub_low["id"], certificate_number="CERT-MI-0007")
    make_family(ctx["site"]["id"], hub_high["id"])
    make_family(ctx["site"]["id"], hub_low["id"])

    dispatch = validate_success(api.create_dispatch(
        {"site_order_id": order["id"], "storage_site_id": ctx["site"]["id"],
         "entry_route": "THAW_AT_HUB"}, TEST_USERS["logistics_operator_headers"]), 201)
    assert dispatch["staging_site_id"] == hub_low["id"]
    assert dispatch["freeze_required"] is True

    unlinked = make_site(ctx["program"]["id"], site_code="MI-RIV-08",
                         site_name="Riverside Unlinked", ultra_cold_capacity_cartons=4,
                         refrigerated_capacity_cartons=4, expected_weekly_doses=100)
    certify_site(unlinked["id"], certificate_number="CERT-MI-0008")
    order8 = submit_order(ctx["entitlement"]["id"], unlinked["id"],
                          requested_cartons=1, requested_doses=0)
    _accept(order8["id"], current_window_version_for_order(order8["id"]), 1)

    no_hub = api.create_dispatch(
        {"site_order_id": order8["id"], "storage_site_id": unlinked["id"],
         "entry_route": "THAW_AT_HUB"}, TEST_USERS["logistics_operator_headers"])
    validate_error(no_hub, "ERR_NO_ELIGIBLE_SITE", expected_status=422)

    families = get_success_data(api.list_carton_families(
        TEST_USERS["cold_chain_reviewer_headers"],
        params={"site_id": ctx["site"]["id"]}))
    assert len(families) == 2


def test_every_side_effect_is_visible_in_the_same_response(api):
    """PRD §3.3: "It raises the entitlement's `held_cartons` and `accepted_cartons`
    by the accepted quantity."

    PRD §2.5: "Derived-field recomputation counts as a modification".

    Design: Corner/consistency_model/every_side_effect_is_visible_in_the_same_response
    """
    ctx = setup_entitled_site()
    order = submit_order(ctx["entitlement"]["id"], ctx["site"]["id"],
                         requested_doses=1000)
    accepted_response = _accept(order["id"], current_window_version_for_order(order["id"]), 2)
    assert accepted_response.status_code < 400, accepted_response.text
    accepted = get_success_data(accepted_response)

    assert accepted["accepted_doses"] == 2340
    # PRD §3.3: "the order's `min_order_shortfall_cartons` is the amount by which
    # `rounded_from_doses` falls short of that governing minimum, or zero if it does
    # not" -- and "the shortfall is taken on the manufacturer-computed carton need
    # before any earlier rejections are netted off". A 1000-dose order rounds to 1
    # carton against a governing minimum of 2, so the shortfall is 1 even though the
    # accepted quantity lands on 2.
    assert accepted["min_order_shortfall_cartons"] == 1

    ent = get_entitlement(ctx["entitlement"]["id"])
    assert ent["held_cartons"] == 2
    assert ent["available_cartons"] == 8

    window_after = get_success_data(api.get_allocation_window(
        ctx["window"]["id"], TEST_USERS["distribution_planner_headers"]))
    assert window_after["accepted_cartons"] == 2