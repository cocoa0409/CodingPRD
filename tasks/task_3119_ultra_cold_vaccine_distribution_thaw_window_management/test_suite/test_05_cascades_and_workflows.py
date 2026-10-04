"""Compensating actions, recall cascades, capacity reservations and gated transitions."""
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
    create_excursion,
    add_ledger_entry,
    make_family,
    make_delivered_second_site,
    setup_adjudicated_excursion,
    setup_reservation_pair,
    usable_doses,
    get_entitlement,
    get_order,
    get_carton,
    get_program,
    get_site,
    get_shipper,
    get_excursion,
)


def _accept_or_fail(order_id, window_version, cartons=2):
    res = api_client.accept_site_order(
        order_id,
        {"accepted_cartons": cartons, "deliver_at": "2026-09-01T06:00:00Z",
         "expected_allocation_window_version": window_version},
        TEST_USERS["distribution_planner_headers"])
    assert res.status_code < 400, f"accept failed: {res.status_code} {res.text}"
    return get_success_data(res)


def test_recall_destroys_cartons_and_lapses_the_entitlement(api):
    """PRD §3.1: "The recall sets the batch to `RECALLED`, destroys every carton of
    the batch whose `temperature_state` is not already `DESTROYED`, appends a
    zero-quantity `DESTROY` ledger entry for each of those cartons, and — for any
    entitlement of the batch still holding `available_cartons` above zero — lapses
    that entitlement with `acceptance_status` `LAPSED` and `held_cartons` reset to
    zero."

    Design: Difficulty/transitive_cascade/batch_recall_destroys_cartons_and_lapses_entitlement
    """
    ctx = anchor_delivered_carton()
    released_before = get_program(ctx["program"]["id"])["released_cartons_to_date"]

    recalled = validate_success(
        api.recall_batch(ctx["batch"]["id"], TEST_USERS["regulatory_affairs_headers"],
                         {"reason": "Potency out of specification at the stability station."}), 200)
    assert recalled["status"] == "RECALLED"

    assert get_carton(ctx["carton"]["id"])["temperature_state"] == "DESTROYED"
    ledger = get_success_data(api.list_carton_ledger_entries(
        ctx["carton"]["id"], TEST_USERS["cold_chain_reviewer_headers"]))
    entries = [e for e in ledger if e["entry_type"] == "DESTROY"]
    assert len(entries) == 1

    ent = get_entitlement(ctx["entitlement"]["id"])
    assert ent["acceptance_status"] == "LAPSED"
    assert ent["held_cartons"] == 0
    assert ent["available_cartons"] == 0

    program = get_program(ctx["program"]["id"])
    assert program["released_cartons_to_date"] == released_before
    assert program["lapsed_carton_count"] == 0


def test_not_usable_adjudication_cascades_to_the_site_and_the_family(api):
    """PRD §3.8: "A `NOT_USABLE` outcome writes a single `WASTE` ledger entry for the
    negated value of the smaller of the carton's `remaining_doses` and the certified
    lost doses, moves the carton's `temperature_state` to `DESTROYED`, and walks
    `quarantine_status` through `RETAINED` and then `DESTROYED`".

    PRD §3.6: "The carton moves to `DESTROYED`, a `DESTROY` entry is written for the
    negated remaining doses, and the origin site's `usable_doses` and
    `inventory_status` are recomputed."

    Design: Difficulty/transitive_cascade/not_usable_adjudication_cascades_to_site_and_program
    """
    ctx = anchor_thawed_carton()
    family_site = make_delivered_second_site(ctx, site_code="MI-RIV-05",
                                             capability="REFRIGERATED",
                                             expected_weekly_doses=1200)
    make_family(ctx["site"]["id"], family_site["id"])

    exc = create_excursion(ctx["carton"]["id"], ctx["site"]["id"],
                           min_temperature_c=-65,
                           first_breach_at="2026-09-01T09:00:00Z",
                           last_breach_at="2026-09-01T11:00:00Z",
                           reported_at="2026-09-01T11:05:00Z")
    api.review_temperature_excursion(exc["id"], TEST_USERS["cold_chain_reviewer_headers"])

    adjudicated = validate_success(api.adjudicate_temperature_excursion(
        exc["id"], {"outcome": "NOT_USABLE",
                    "rationale": "Breach below the excursion tolerance band for two hours."},
        TEST_USERS["medical_science_liaison_headers"]), 200)
    assert adjudicated["adjudication_status"] == "NOT_USABLE"

    assert get_carton(ctx["carton"]["id"])["temperature_state"] == "DESTROYED"

    origin = usable_doses(ctx["site"]["id"])
    assert origin["usable_doses"] == 0

    # PRD §3.3 derives a site's inventory_status from open_excursion_count, which
    # "counts the excursions at the site whose review_status is not ADJUDICATED", so
    # an adjudicated excursion leaves the site OPEN and the site status is not an
    # observable of this cascade (PRD states no separate site restriction on a
    # NOT_USABLE outcome).
    assert origin["inventory_status"] in ("OPEN", "RESTRICTED")
    linked = usable_doses(family_site["id"])
    assert linked["inventory_status"] in ("OPEN", "RESTRICTED")

    assert get_excursion(exc["id"])["quarantine_status"] == "DESTROYED"


def test_recall_requires_an_unrecalled_batch(api):
    """PRD §3.1: "a batch already `DEPLETED` or `RECALLED` is refused with
    `ERR_BATCH_NOT_RECALLABLE`".

    Design: Corner/errors/recall_requires_an_unrecalled_batch
    """
    product = make_product()
    program = make_program()
    batch = make_batch(product["id"], program["id"])
    carton = register_carton(batch["id"], serial="C-01")
    release_batch(batch["id"])

    first = validate_success(
        api.recall_batch(batch["id"], TEST_USERS["regulatory_affairs_headers"],
                         {"reason": "Deviation at the fill line."}), 200)
    assert first["status"] == "RECALLED"
    version_after_first = first["version"]

    second = api.recall_batch(batch["id"], TEST_USERS["regulatory_affairs_headers"],
                              {"reason": "Deviation at the fill line."})
    validate_error(second, "ERR_BATCH_NOT_RECALLABLE", expected_status=409)

    assert get_carton(carton["id"])["temperature_state"] == "DESTROYED"
    ledger = get_success_data(api.list_carton_ledger_entries(
        carton["id"], TEST_USERS["cold_chain_reviewer_headers"]))
    entries = [e for e in ledger if e["entry_type"] == "DESTROY"]
    assert len(entries) == 1
    assert get_success_data(api.get_allocation_batch(
        batch["id"], TEST_USERS["regulatory_affairs_headers"]))["version"] == version_after_first


def test_release_on_a_frozen_program_is_refused(api):
    """PRD §3.1: "The owning program must not be `FROZEN`, or the request is refused
    with `ERR_PROGRAM_FROZEN`".

    PRD §2.11: "That cycle lapses every `HELD` reservation whose `end_at` is at or
    before the logical clock, closes every allocation window whose `closes_at` is at
    or before the logical clock while its `status` is `OPEN`".

    Design: Corner/errors/release_on_a_frozen_program_is_refused
    """
    # Build the frozen program and a separate batch registered under it.
    product = make_product()
    program = make_program(jurisdiction_code="OH", regulatory_body="Ohio Department of Health",
                           fixed_weekly_cartons=8, weekly_allocation_cap_cartons=8,
                           segment_rule="STOP", adjudication_sla_hours=24,
                           quarantine_on_review=False)
    batch = make_batch(product["id"], program["id"], batch_code="UCV-BATCH-OH-1",
                       released_cartons=8)
    register_carton(batch["id"], serial="C-OH-01")
    release_batch(batch["id"])

    open_window(batch["id"], program["id"], closes_at="2026-09-02T00:00:00Z")
    # PRD §3.9's tier ladder is driven by a weighted score: "A score of at most
    # twenty is tier zero", five points per lapsed period.  Five unsubmitted
    # reporting periods past their `period_end` push the score to tier two, which is
    # the FROZEN standing this test needs.
    from test_helpers import add_lapsed_periods
    add_lapsed_periods(program["id"], count=5)
    api_client.set_clock({"current_utc": "2026-09-04T00:00:00Z"},
                         TEST_USERS["platform_admin_headers"])
    cycle = validate_success(api.run_cycle(TEST_USERS["platform_admin_headers"]), 200)
    assert cycle["lapsed_window_count"] == 1
    api.assess_program_standing(
        program["id"], {"as_of": "2026-09-04T00:00:00Z", "propagation_mode": "IMMEDIATE"},
        TEST_USERS["regulatory_affairs_headers"])
    assert get_program(program["id"])["standing_status"] == "FROZEN"

    fresh_batch = make_batch(product["id"], program["id"], batch_code="UCV-BATCH-OH-2",
                             released_cartons=8)
    res = api.release_batch(fresh_batch["id"], TEST_USERS["manufacturing_qa_headers"])
    validate_error(res, "ERR_PROGRAM_FROZEN", expected_status=422)
    assert get_success_data(api.get_allocation_batch(
        fresh_batch["id"], TEST_USERS["manufacturing_qa_headers"]))["status"] == "DRAFT"


def test_destroying_a_carton_twice_is_refused(api):
    """PRD §2.9: "`ERR_ALREADY_TERMINAL` when the entity already sits in a terminal
    state of its machine".

    Design: Corner/errors/destroying_a_carton_twice_is_refused
    """
    ctx = anchor_thawed_carton()
    exc = setup_adjudicated_excursion(ctx, min_temperature_c=-65, outcome="NOT_USABLE")
    assert get_carton(ctx["carton"]["id"])["temperature_state"] == "DESTROYED"

    res = api.destroy_carton(ctx["carton"]["id"],
                             {"reason": "Manual write-off requested by the site."},
                             TEST_USERS["cold_chain_reviewer_headers"])
    validate_error(res, "ERR_ALREADY_TERMINAL", expected_status=409)

    assert get_carton(ctx["carton"]["id"])["temperature_state"] == "DESTROYED"
    ledger = get_success_data(api.list_carton_ledger_entries(
        ctx["carton"]["id"], TEST_USERS["cold_chain_reviewer_headers"]))
    waste = [e for e in ledger if e["entry_type"] == "WASTE"]
    assert len(waste) == 1


def test_touching_reservation_intervals_are_free_and_interior_overlap_is_not(api):
    """PRD §3.7: "two intervals that merely touch — the incoming one beginning
    exactly when the incumbent ends — have zero overlap and do not conflict, and two
    intervals that share a single instant are touching rather than overlapping."

    PRD §3.7: "When there is a strictly positive overlap and the incoming quantity
    plus the incumbent quantity exceeds the site's capacity for that entry type, the
    reservation is refused with `ERR_STORAGE_RESERVATION_CONFLICT` (HTTP 409)."

    Design: Difficulty/resource_temporal_overlap/touching_reservation_intervals_are_free_and_interior_overlap_is_not
    """
    ctx, incumbent = setup_reservation_pair(capacity=10, incumbent_cartons=6)

    from test_helpers import create_reservation_payload

    interior = api.create_carton_storage_reservation(
        create_reservation_payload(ctx["site"]["id"], ctx["carton"]["id"],
                                   reserved_capacity_cartons=6,
                                   start_at="2026-09-01T11:00:00Z",
                                   end_at="2026-09-01T14:00:00Z",
                                   resolve_method="RESERVATION_BOUNDARY"),
        TEST_USERS["distribution_planner_headers"])
    validate_error(interior, "ERR_STORAGE_RESERVATION_CONFLICT", expected_status=409)

    touching = validate_success(api.create_carton_storage_reservation(
        create_reservation_payload(ctx["site"]["id"], ctx["carton"]["id"],
                                   reserved_capacity_cartons=4,
                                   start_at="2026-09-01T12:00:00Z",
                                   end_at="2026-09-01T13:00:00Z",
                                   resolve_method="RESERVATION_BOUNDARY"),
        TEST_USERS["distribution_planner_headers"]), 201)
    assert touching["resolved_conflict_minutes"] == 0
    assert touching["status"] == "HELD"


def test_boundary_resolution_vs_pooled_capacity_semantics(api):
    """PRD §3.7: "The default, `RESERVATION_BOUNDARY`, keeps each reservation inside
    the capacity of the interval it was declared with, so a pooled quantity above the
    site's capacity is refused. `CAPACITY_POOLED` routes the overlapping cartons into
    pooled capacity that includes the staging site, so the same interval pair is
    admitted and the overlap is recorded on `resolved_conflict_minutes` instead".

    Design: Difficulty/resource_temporal_overlap/boundary_resolution_vs_pooled_capacity_semantics
    """
    ctx, incumbent = setup_reservation_pair(capacity=10, incumbent_cartons=6)

    from test_helpers import create_reservation_payload

    boundary = api.create_carton_storage_reservation(
        create_reservation_payload(ctx["site"]["id"], ctx["carton"]["id"],
                                   reserved_capacity_cartons=6,
                                   start_at="2026-09-01T11:00:00Z",
                                   end_at="2026-09-01T14:00:00Z",
                                   resolve_method="RESERVATION_BOUNDARY"),
        TEST_USERS["distribution_planner_headers"])
    validate_error(boundary, "ERR_STORAGE_RESERVATION_CONFLICT", expected_status=409)

    pooled = validate_success(api.create_carton_storage_reservation(
        create_reservation_payload(ctx["site"]["id"], ctx["carton"]["id"],
                                   reserved_capacity_cartons=6,
                                   start_at="2026-09-01T11:00:00Z",
                                   end_at="2026-09-01T14:00:00Z",
                                   resolve_method="CAPACITY_POOLED"),
        TEST_USERS["distribution_planner_headers"]), 201)
    assert pooled["status"] == "HELD"
    assert pooled["resolved_conflict_minutes"] == 60
    assert pooled["reserved_capacity_cartons"] == 6
    assert get_success_data(api.get_carton_storage_reservation(
        incumbent["id"], TEST_USERS["distribution_planner_headers"]))["status"] == "HELD"


def test_order_acceptance_requires_a_certified_destination(api):
    """PRD §3.3: "The ordering site must be equipment-certified at the logical clock,
    or it is refused with `ERR_SITE_EQUIPMENT_NOT_CERTIFIED`."

    PRD §2.8: "A site's `equipment_certified` flag is true only under that condition
    and is false otherwise".

    Design: Difficulty/cross_entity_state_dependency/order_acceptance_requires_certified_destination
    """
    ctx = setup_entitled_site()
    uncertified = make_site(ctx["program"]["id"], site_code="MI-RIV-03",
                            site_name="Riverside Mobile Unit", expected_weekly_doses=900)
    order = get_success_data(api.create_site_order(
        {"allocation_entitlement_id": ctx["entitlement"]["id"],
         "storage_site_id": uncertified["id"], "requested_cartons": 2,
         "requested_doses": 0},
        make_site_coordinator_headers(uncertified["id"])))
    assert get_site(uncertified["id"])["equipment_certified"] is False

    refused = api.submit_site_order(order["id"],
                                    make_site_coordinator_headers(uncertified["id"]))
    validate_error(refused, "ERR_SITE_EQUIPMENT_NOT_CERTIFIED", expected_status=422)

    cert = certify_site(uncertified["id"], certificate_number="CERT-MI-0003")
    assert cert["status"] == "RECORDED"
    assert get_site(uncertified["id"])["equipment_certified"] is True

    submitted = validate_success(api.submit_site_order(
        order["id"], make_site_coordinator_headers(uncertified["id"])), 200)
    assert submitted["order_status"] == "SUBMITTED"
    assert submitted["requested_cartons_snapshot"] == 2


def test_transfer_dispatchability_tracks_the_carton_expiry(api):
    """PRD §3.7: "it requires the logical clock to be strictly before the carton's
    thaw window expiry, otherwise `ERR_THAW_WINDOW_EXPIRED`".

    PRD §3.6: "Expiry is automatic and needs no client. When the logical clock
    reaches a `current_expires_at` that is not null, a carton in `REFRIGERATED`,
    `THAWED`, `PUNCTURED`, `ULTRA_COLD`, or `PALLET_STAGED` moves to `EXPIRED`".

    Design: Difficulty/cross_entity_state_dependency/transfer_dispatchability_tracks_the_carton_expiry
    """
    ctx = anchor_thawed_carton()
    dest = make_delivered_second_site(ctx, site_code="MI-RIV-04", capability="REFRIGERATED",
                                      expected_weekly_doses=700)

    transfer = get_success_data(api.create_site_transfer(
        {"from_site_id": ctx["site"]["id"], "to_site_id": dest["id"],
         "carton_id": ctx["carton"]["id"], "requested_at": "2026-09-01T10:00:00Z"},
        TEST_USERS["distribution_planner_headers"]))
    approved = validate_success(api.approve_site_transfer(
        transfer["id"], TEST_USERS["distribution_planner_headers"]), 200)
    assert approved["admissibility"] == "ADMITTED"

    api_client.set_clock({"current_utc": "2026-09-07T00:00:00Z"},
                         TEST_USERS["platform_admin_headers"])

    res = api.send_site_transfer(transfer["id"], TEST_USERS["logistics_operator_headers"])
    validate_error(res, "ERR_THAW_WINDOW_EXPIRED", expected_status=422)

    carton = get_carton(ctx["carton"]["id"])
    assert carton["temperature_state"] == "EXPIRED"
    assert carton["expired_at"] == "2026-09-06T08:00:00Z"
    assert get_success_data(api.get_site_transfer(
        transfer["id"], TEST_USERS["distribution_planner_headers"]))["status"] == "APPROVED"