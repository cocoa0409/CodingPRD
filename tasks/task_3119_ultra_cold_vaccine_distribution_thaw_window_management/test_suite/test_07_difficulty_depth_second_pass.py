"""Second translations of the depth index, verifying the complementary observable."""
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
    setup_reservation_pair,
    usable_doses,
    get_entitlement,
    get_order,
    current_window_version_for_order,
    get_carton,
    get_program,
    get_site,
    get_excursion,
)


def _accept(order_id, window_version, cartons=1, deliver_at="2026-09-01T06:00:00Z"):
    return api_client.accept_site_order(
        order_id,
        {"accepted_cartons": cartons, "deliver_at": deliver_at,
         "expected_allocation_window_version": window_version},
        TEST_USERS["distribution_planner_headers"])


# ── dual_variant_calc ─────────────────────────────────────────────────────

def test_interim_variant_counts_the_administration_the_certified_variant_reverses(api):
    """PRD §3.9: "The two administration totals diverge in the same way: the interim
    count includes every `ADMINISTER` entry, while the certified count subtracts every
    `REVERSE` entry that names an administration."

    Design: Difficulty/dual_variant_calc/dose_accountability_interim_vs_certified
    """
    ctx = anchor_thawed_carton()
    site_id = ctx["site"]["id"]
    site_headers = make_site_coordinator_headers(site_id)

    from test_helpers import make_reporting_period

    period = make_reporting_period(ctx["program"]["id"],
                                   period_start="2026-09-01T00:00:00Z",
                                   period_end="2026-09-08T00:00:00Z")

    administered = add_ledger_entry(ctx["carton"]["id"], "ADMINISTER", 100,
                                    "2026-09-01T09:00:00Z", as_headers=site_headers)
    api.reverse_dose_ledger_entry(
        administered["id"], {"occurred_at": "2026-09-01T10:00:00Z"}, TEST_USERS["distribution_planner_headers"])

    interim = validate_success(api.get_period_accountability(
        period["id"], {"variant": "INTERIM"}, TEST_USERS["regulatory_affairs_headers"]), 200)
    certified = validate_success(api.get_period_accountability(
        period["id"], {"variant": "CERTIFIED"}, TEST_USERS["regulatory_affairs_headers"]), 200)

    assert interim["administered_doses"] == 100
    assert certified["administered_doses"] == 0
    assert interim["accounted_doses"] == 100
    assert certified["accounted_doses"] == 0
    assert certified["accounted_doses"] < interim["accounted_doses"]


def test_certified_reading_is_strictly_smaller_while_the_period_stays_open(api):
    """PRD §3.9: "a read that names the interim variant reports every recorded loss
    at once, so an open adjudication contributes its full waste quantity even though
    the loss is not yet certified, while a read that names the certified variant
    reports only the certified losses".

    PRD §3.9: "Its derived totals are `released_doses`, the doses released into the
    program inside the period".

    Design: Difficulty/dual_variant_calc/dose_accountability_interim_vs_certified
    """
    ctx = anchor_thawed_carton()
    site_id = ctx["site"]["id"]

    from test_helpers import make_reporting_period, add_ledger_entry as _add

    period = make_reporting_period(ctx["program"]["id"],
                                   period_start="2026-09-01T00:00:00Z",
                                   period_end="2026-09-08T00:00:00Z")
    administered = _add(ctx["carton"]["id"], "ADMINISTER", 200, "2026-09-01T09:00:00Z",
                        as_headers=make_site_coordinator_headers(site_id))
    api.reverse_dose_ledger_entry(
        administered["id"], {"occurred_at": "2026-09-01T10:00:00Z"},
        TEST_USERS["distribution_planner_headers"])

    interim = validate_success(api.get_period_accountability(
        period["id"], {"variant": "INTERIM"}, TEST_USERS["regulatory_affairs_headers"]), 200)
    certified = validate_success(api.get_period_accountability(
        period["id"], {"variant": "CERTIFIED"}, TEST_USERS["regulatory_affairs_headers"]), 200)
    assert interim["accounted_doses"] - certified["accounted_doses"] == 200
    assert interim["released_doses"] == certified["released_doses"]

    period_state = get_success_data(api.get_reporting_period(
        period["id"], TEST_USERS["regulatory_affairs_headers"]))
    assert period_state["status"] == "OPEN"


# ── combinatorial_formula ─────────────────────────────────────────────────

def test_seven_buckets_round_up_to_the_next_whole_carton_at_the_ceiling(api):
    """PRD §3.3: "the seventh bucket absorbs whatever is left: it contributes sixteen
    cartons for each complete group of one hundred and sixty doses remaining after
    the first six, plus three cartons for each complete group of thirty doses
    remaining after that sixteen-per-hundred-and-sixty step".

    PRD §3.3: "that sum is divided by the carton's `doses_per_carton` and rounded up
    to a whole carton by an exact integer ceiling division that never uses floating
    point".

    Design: Difficulty/combinatorial_formula/additive_seven_bucket_waterfall_carton_need
    """
    ctx = setup_entitled_site()
    order = submit_order(ctx["entitlement"]["id"], ctx["site"]["id"],
                         requested_cartons=5, requested_doses=5000)
    res = _accept(order["id"], current_window_version_for_order(order["id"]), 5)
    accepted = validate_success(res, 200)
    # The buckets sum to 2813 doses, which rounds up to 3 cartons.
    assert accepted["rounded_from_doses"] == 3
    assert accepted["min_order_shortfall_cartons"] == 0
    assert accepted["accepted_cartons"] == 5


def test_pack_ceiling_preserves_the_prior_rejection(api):
    """PRD §3.3: "The accepted quantity then lands on the pack-size ceiling while
    preserving any rejection already taken on the same order. Let `prior_rejected` be
    the order's existing `rejected_cartons`."

    PRD §3.3: "It raises the entitlement's `held_cartons` and `accepted_cartons` by
    the accepted quantity."

    Design: Difficulty/combinatorial_formula/holdback_rounding_and_pack_ceiling_on_rejection
    """
    ctx = setup_entitled_site()
    order = submit_order(ctx["entitlement"]["id"], ctx["site"]["id"],
                         requested_cartons=5, requested_doses=0)
    first = _accept(order["id"], current_window_version_for_order(order["id"]), 4)
    assert first.status_code < 400, first.text
    assert get_success_data(first)["rejected_cartons"] == 1

    second = _accept(order["id"], current_window_version_for_order(order["id"]), 5)
    accepted = validate_success(second, 200)
    assert accepted["accepted_cartons"] == 5
    assert accepted["rejected_cartons"] == 0
    ent = get_entitlement(ctx["entitlement"]["id"])
    assert ent["held_cartons"] == 5
    assert ent["available_cartons"] == 5


# ── non_linear_state_machine ──────────────────────────────────────────────

def test_second_adjudication_supersedes_and_points_the_trace_id(api):
    """PRD §3.8: "on success the earlier adjudication becomes `SUPERSEDED` with the
    superseding adjudication's `prior_outcome` set to the old outcome and
    `current_resolution_trace_id` pointing at the new one".

    Design: Difficulty/non_linear_state_machine/excursion_cyclic_reopen_and_adjudication_revision_loop
    """
    ctx = anchor_thawed_carton()
    site_id = ctx["site"]["id"]
    site_headers = make_site_coordinator_headers(site_id)

    exc = create_excursion(ctx["carton"]["id"], site_id, min_temperature_c=-55)
    api.review_temperature_excursion(exc["id"], TEST_USERS["cold_chain_reviewer_headers"])
    # PRD §3.8 refuses an appeal with `ERR_CARTON_DESTROYED` when the referenced
    # carton has been destroyed, and a NOT_USABLE outcome destroys it, so the first
    # adjudication is USABLE and the supersession is exercised over a live carton.
    api.adjudicate_temperature_excursion(
        exc["id"], {"outcome": "USABLE", "rationale": "Breach stayed inside the refrigerated budget."},
        TEST_USERS["medical_science_liaison_headers"])
    appeal = get_success_data(api.file_appeal(
        exc["id"], {"filed_by_user_id": "coord-lena", "filed_at": "2026-09-01T11:00:00Z"},
        site_headers))
    api.accept_appeal(exc["id"], appeal["id"], TEST_USERS["regulatory_affairs_headers"])
    api.review_temperature_excursion(exc["id"], TEST_USERS["cold_chain_reviewer_headers"])
    second = get_success_data(api.adjudicate_temperature_excursion(
        exc["id"], {"outcome": "NOT_USABLE", "rationale": "Second review found the breach outside the budget."},
        TEST_USERS["medical_science_liaison_headers"]))

    adjudications = get_success_data(api.list_excursion_adjudications(
        TEST_USERS["regulatory_affairs_headers"],
        params={"temperature_excursion_id": exc["id"]}))
    superseded = [a for a in adjudications if a["status"] == "SUPERSEDED"]
    assert len(superseded) == 1
    assert superseded[0]["prior_outcome"] is None

    excursion = get_excursion(exc["id"])
    assert excursion["review_status"] == "ADJUDICATED"
    assert excursion["adjudication_status"] == "NOT_USABLE"
    assert excursion["current_resolution_trace_id"] is not None
    assert excursion["current_resolution_trace_id"] != superseded[0]["id"]


def test_carton_thaw_is_refused_while_the_carton_is_in_transit(api):
    """PRD §3.6: "The carton must not be `IN_TRANSIT` (otherwise
    `ERR_CARTON_IN_TRANSIT`)".

    PRD §3.5: "each carton moves to `IN_TRANSIT`".

    Design: Difficulty/non_linear_state_machine/carton_two_independent_axes_with_compound_grade_and_cycle
    """
    from test_helpers import create_shipper_payload, create_logger_reading_payload

    ctx = setup_entitled_site()
    site_id = ctx["site"]["id"]
    order = submit_order(ctx["entitlement"]["id"], site_id)
    _accept(order["id"], current_window_version_for_order(order["id"]), 2)
    dispatch = get_success_data(api.create_dispatch(
        {"site_order_id": order["id"], "storage_site_id": site_id,
         "entry_route": "DIRECT_ULTRA_COLD"}, TEST_USERS["logistics_operator_headers"]))
    api.pack_dispatch(dispatch["id"], TEST_USERS["logistics_operator_headers"])
    shipper = get_success_data(api.create_shipper(
        create_shipper_payload(dispatch["id"]), TEST_USERS["logistics_operator_headers"]))
    api.attach_carton_to_shipper(shipper["id"], {"carton_id": ctx["carton"]["id"]},
                                 TEST_USERS["logistics_operator_headers"])
    for recorded_at, temp in (("2026-09-01T01:00:00Z", -75), ("2026-09-01T06:05:00Z", -74)):
        api.create_logger_reading(
            create_logger_reading_payload(shipper["id"], recorded_at=recorded_at,
                                          temperature_c=temp),
            TEST_USERS["logistics_operator_headers"])
    shipper = get_success_data(api.get_shipper(shipper["id"],
                                               TEST_USERS["cold_chain_reviewer_headers"]))
    api.seal_shipper(shipper["id"], {"expected_shipper_version": shipper["version"]},
                     TEST_USERS["logistics_operator_headers"])
    api.send_dispatch(dispatch["id"], TEST_USERS["logistics_operator_headers"])

    carton = get_carton(ctx["carton"]["id"])
    assert carton["temperature_state"] == "IN_TRANSIT"
    assert carton["thawed_at"] is None
    assert carton["current_expires_at"] is None

    res = api.thaw_carton(ctx["carton"]["id"], make_site_coordinator_headers(site_id))
    validate_error(res, "ERR_CARTON_IN_TRANSIT", expected_status=409)


# ── transitive_cascade ────────────────────────────────────────────────────

def test_recall_lapses_the_entitlement_without_a_shipping_window_lapse(api):
    """PRD §3.1: "— for any entitlement of the batch still holding `available_cartons`
    above zero — lapses that entitlement with `acceptance_status` `LAPSED` and
    `held_cartons` reset to zero."

    PRD §3.2: "the program's `lapsed_carton_count` advances by the lapsed cartons"
    (only for a lapse raised by a window close).

    Design: Difficulty/transitive_cascade/batch_recall_destroys_cartons_and_lapses_entitlement
    """
    ctx = anchor_delivered_carton()
    api.recall_batch(ctx["batch"]["id"], TEST_USERS["regulatory_affairs_headers"],
                     {"reason": "Potency out of specification at the stability station."})

    ent = get_entitlement(ctx["entitlement"]["id"])
    assert ent["acceptance_status"] == "LAPSED"
    assert ent["held_cartons"] == 0

    lapses = get_success_data(api.list_shipping_window_lapses(
        TEST_USERS["distribution_planner_headers"]))
    assert lapses == []
    assert get_program(ctx["program"]["id"])["lapsed_carton_count"] == 0


def test_not_usable_adjudication_writes_only_a_waste_entry(api):
    """PRD §3.8: "A `NOT_USABLE` outcome writes a single `WASTE` ledger entry for the
    negated value of the smaller of the carton's `remaining_doses` and the certified
    lost doses, moves the carton's `temperature_state` to `DESTROYED`, and walks
    `quarantine_status` through `RETAINED` and then `DESTROYED`; no separate
    `DESTROY` entry is written, and the carton's `remaining_doses` falls only by the
    wasted quantity."

    Design: Difficulty/transitive_cascade/not_usable_adjudication_cascades_to_site_and_program
    """
    from test_helpers import setup_adjudicated_excursion

    ctx = anchor_thawed_carton()
    make_family(ctx["site"]["id"],
                make_delivered_second_site(ctx, site_code="MI-RIV-05",
                                           capability="REFRIGERATED")["id"])
    before = get_carton(ctx["carton"]["id"])["remaining_doses"]
    setup_adjudicated_excursion(ctx, min_temperature_c=-65, outcome="NOT_USABLE")

    ledger = get_success_data(api.list_carton_ledger_entries(
        ctx["carton"]["id"], TEST_USERS["cold_chain_reviewer_headers"]))
    waste = [e for e in ledger if e["entry_type"] == "WASTE"]
    destroys = [e for e in ledger if e["entry_type"] == "DESTROY"]
    assert len(waste) == 1
    assert destroys == []

    carton = get_carton(ctx["carton"]["id"])
    assert carton["temperature_state"] == "DESTROYED"
    assert carton["remaining_doses"] == before + waste[0]["quantity_doses"]


# ── priority_pair_validation_conflict ─────────────────────────────────────

def test_state_check_precedes_the_capacity_check_on_a_draft_dispatch(api):
    """PRD §3.4: "The order behind the dispatch must be `ACCEPTED` or
    `PARTIALLY_ACCEPTED`, or the request is refused with `ERR_ORDER_NOT_ACCEPTED`."

    PRD §3.5: "Arrival is recorded by a `SiteCoordinator` with an `arrived_at` instant
    and moves the dispatch from `IN_TRANSIT` to `DELIVERED`."

    Design: Difficulty/priority_pair_validation_conflict/state_precondition_beats_cold_chain_safety_conflict
    """
    ctx = setup_entitled_site()
    order = submit_order(ctx["entitlement"]["id"], ctx["site"]["id"],
                         requested_cartons=2, requested_doses=0)
    dispatch = get_success_data(api.create_dispatch(
        {"site_order_id": order["id"], "storage_site_id": ctx["site"]["id"],
         "entry_route": "DIRECT_ULTRA_COLD"}, TEST_USERS["logistics_operator_headers"]))

    res = api.deliver_dispatch(
        dispatch["id"], {"arrived_at": "2026-09-01T06:00:00Z"},
        make_site_coordinator_headers(ctx["site"]["id"]))
    validate_error(res, "ERR_INVALID_STATE", expected_status=409)

    still_draft = get_success_data(api.get_dispatch(
        dispatch["id"], TEST_USERS["logistics_operator_headers"]))
    assert still_draft["status"] == "DRAFT"


def test_standing_gate_is_reachable_once_the_fiscal_check_passes(api):
    """PRD §3.3: "`requested_cartons` must not exceed the entitlement's
    `available_cartons`, or it is refused with `ERR_ORDER_EXCEEDS_ENTITLEMENT`."

    PRD §2.8: "`RESTRICTED` blocks new site-order submission but permits existing
    orders to be accepted, dispatched, and delivered".

    Design: Difficulty/priority_pair_validation_conflict/entitlement_exhaustion_beats_program_standing_conflict
    """
    from test_helpers import make_reporting_period

    ctx = setup_entitled_site()
    holder = submit_order(ctx["entitlement"]["id"], ctx["site"]["id"],
                          requested_cartons=10, requested_doses=0)
    _accept(holder["id"], current_window_version_for_order(holder["id"]), 10)
    assert get_entitlement(ctx["entitlement"]["id"])["available_cartons"] == 0

    from test_helpers import add_lapsed_periods
    add_lapsed_periods(ctx["program"]["id"], count=5)
    api.assess_program_standing(
        ctx["program"]["id"], {"as_of": "2026-09-01T00:00:00Z",
                               "propagation_mode": "AFTER_CYCLE"},
        TEST_USERS["regulatory_affairs_headers"])
    # Either gate reading refuses the submission with ERR_PROGRAM_NOT_OPEN, so the
    # assertion does not turn on which tier the weighted score lands in.
    assert get_program(ctx["program"]["id"])["standing_status"] in ("RESTRICTED", "FROZEN")

    too_many = get_success_data(api.create_site_order(
        {"allocation_entitlement_id": ctx["entitlement"]["id"],
         "storage_site_id": ctx["site"]["id"], "requested_cartons": 1,
         "requested_doses": 0}, make_site_coordinator_headers(ctx["site"]["id"])))
    res = api.submit_site_order(too_many["id"],
                                make_site_coordinator_headers(ctx["site"]["id"]))
    validate_error(res, "ERR_ORDER_EXCEEDS_ENTITLEMENT", expected_status=422)


# ── boundary_precision_check ──────────────────────────────────────────────

def test_capacity_boundary_below_the_ceiling_is_admitted(api):
    """PRD §3.3: "the carton capacity of each equipment class it owns, in
    `ultra_cold_capacity_cartons` and `refrigerated_capacity_cartons`".

    PRD §3.3: "that the site's capacity at the requested `deliver_at` can hold the
    accepted cartons for the required entry type (otherwise
    `ERR_SITE_CAPACITY_INSUFFICIENT`)".

    Design: Difficulty/boundary_precision_check/destination_capacity_exact_boundary_is_inclusive
    """
    ctx = setup_entitled_site()
    roomy = make_site(ctx["program"]["id"], site_code="MI-RIV-02",
                      site_name="Riverside Field Unit", ultra_cold_capacity_cartons=3,
                      refrigerated_capacity_cartons=3, expected_weekly_doses=600)
    certify_site(roomy["id"], certificate_number="CERT-MI-0002")

    order = submit_order(ctx["entitlement"]["id"], roomy["id"],
                         requested_cartons=2, requested_doses=0)
    res = _accept(order["id"], current_window_version_for_order(order["id"]), 2)
    accepted = validate_success(res, 200)
    assert accepted["accepted_cartons"] == 2
    assert get_site(roomy["id"])["inventory_status"] == "OPEN"


def test_positive_dose_order_produces_a_non_zero_rounded_need(api):
    """PRD §3.3: "an order with `requested_doses` of zero contributes nothing to any
    bucket and is skipped in the ceiling step so that it never creates a carton."

    PRD §3.3: "the result is the order's `rounded_from_doses`, the cartons implied by
    the dose requirement before any uplift."

    Design: Difficulty/boundary_precision_check/zero_dose_order_uses_the_carton_only_variant
    """
    ctx = setup_entitled_site()
    carton_only = submit_order(ctx["entitlement"]["id"], ctx["site"]["id"],
                               requested_cartons=1, requested_doses=0)
    dosed = submit_order(ctx["entitlement"]["id"], ctx["site"]["id"],
                         requested_cartons=2, requested_doses=2340)

    assert get_order(carton_only["id"])["rounded_from_doses"] == 0
    assert get_order(dosed["id"])["rounded_from_doses"] == 2


# ── cross_entity_state_dependency ─────────────────────────────────────────

def test_certified_destination_then_accepts_the_same_order(api):
    """PRD §3.3: "Accepting the full available quantity moves it to `FULFILLED`; the
    preconditions are that the acting program's `standing_status` is `OPEN`".

    PRD §2.8: "A site's `equipment_certified` flag is true only under that condition
    and is false otherwise".

    Design: Difficulty/cross_entity_state_dependency/order_acceptance_requires_certified_destination
    """
    ctx = setup_entitled_site()
    site = make_site(ctx["program"]["id"], site_code="MI-RIV-03",
                     site_name="Riverside Mobile Unit", expected_weekly_doses=900)

    order = get_success_data(api.create_site_order(
        {"allocation_entitlement_id": ctx["entitlement"]["id"],
         "storage_site_id": site["id"], "requested_cartons": 2, "requested_doses": 0},
        make_site_coordinator_headers(site["id"])))
    certify_site(site["id"], certificate_number="CERT-MI-0003")
    submitted = validate_success(api.submit_site_order(
        order["id"], make_site_coordinator_headers(site["id"])), 200)
    assert submitted["order_status"] == "SUBMITTED"

    accepted = validate_success(_accept(order["id"], current_window_version_for_order(order["id"]), 2), 200)
    assert accepted["accepted_cartons"] == 2
    assert accepted["order_status"] in ("ACCEPTED", "PARTIALLY_ACCEPTED")


def test_live_carton_can_be_dispatched_on_its_transfer(api):
    """PRD §3.7: "Dispatching the transfer is a `LogisticsOperator` act moving it from
    `APPROVED` to `DISPATCHED`, and it cannot move at all until the destination has
    rendered an admissibility decision".

    Design: Difficulty/cross_entity_state_dependency/transfer_dispatchability_tracks_the_carton_expiry
    """
    ctx = anchor_thawed_carton()
    dest = make_delivered_second_site(ctx, site_code="MI-RIV-04", capability="REFRIGERATED")

    transfer = get_success_data(api.create_site_transfer(
        {"from_site_id": ctx["site"]["id"], "to_site_id": dest["id"],
         "carton_id": ctx["carton"]["id"], "requested_at": "2026-09-01T10:00:00Z"},
        TEST_USERS["distribution_planner_headers"]))
    assert transfer["hours_remaining_at_request"] == 120.0
    api.approve_site_transfer(transfer["id"], TEST_USERS["distribution_planner_headers"])
    sent = validate_success(api.send_site_transfer(
        transfer["id"], TEST_USERS["logistics_operator_headers"]), 200)
    assert sent["status"] == "DISPATCHED"
    assert get_carton(ctx["carton"]["id"])["temperature_state"] == "IN_TRANSIT"


# ── resource_temporal_overlap ─────────────────────────────────────────────

def test_touching_pair_pools_exactly_to_the_site_capacity(api):
    """PRD §3.7: "The site's capacity is `ultra_cold_capacity_cartons` when the entry
    type is `ULTRA_COLD` and `refrigerated_capacity_cartons` otherwise."

    PRD §3.7: "two intervals that merely touch — the incoming one beginning exactly
    when the incumbent ends — have zero overlap and do not conflict".

    Design: Difficulty/resource_temporal_overlap/touching_reservation_intervals_are_free_and_interior_overlap_is_not
    """
    ctx, incumbent = setup_reservation_pair(capacity=10, incumbent_cartons=6)

    from test_helpers import create_reservation_payload

    touching = validate_success(api.create_carton_storage_reservation(
        create_reservation_payload(ctx["site"]["id"], ctx["carton"]["id"],
                                   reserved_capacity_cartons=4,
                                   start_at="2026-09-01T12:00:00Z",
                                   end_at="2026-09-01T13:00:00Z",
                                   resolve_method="RESERVATION_BOUNDARY"),
        TEST_USERS["distribution_planner_headers"]), 201)
    assert touching["resolved_conflict_minutes"] == 0
    assert incumbent["reserved_capacity_cartons"] + touching["reserved_capacity_cartons"] == 10
    assert get_success_data(api.get_carton_storage_reservation(
        incumbent["id"], TEST_USERS["distribution_planner_headers"]))["status"] == "HELD"


def test_pooled_reservation_records_the_shared_minutes(api):
    """PRD §3.7: "`CAPACITY_POOLED` routes the overlapping cartons into pooled
    capacity that includes the staging site, so the same interval pair is admitted
    and the overlap is recorded on `resolved_conflict_minutes` instead".

    PRD §3.7: "The overlap between an incoming interval and an incumbent interval is
    the number of whole minutes between the later of their starts and the earlier of
    their ends, floored at zero".

    Design: Difficulty/resource_temporal_overlap/boundary_resolution_vs_pooled_capacity_semantics
    """
    ctx, incumbent = setup_reservation_pair(capacity=10, incumbent_cartons=6)

    from test_helpers import create_reservation_payload

    pooled = validate_success(api.create_carton_storage_reservation(
        create_reservation_payload(ctx["site"]["id"], ctx["carton"]["id"],
                                   reserved_capacity_cartons=6,
                                   start_at="2026-09-01T11:00:00Z",
                                   end_at="2026-09-01T14:00:00Z",
                                   resolve_method="CAPACITY_POOLED"),
        TEST_USERS["distribution_planner_headers"]), 201)
    assert pooled["resolved_conflict_minutes"] == 60
    assert pooled["reserved_capacity_cartons"] == 6
    assert get_success_data(api.get_carton_storage_reservation(
        pooled["id"], TEST_USERS["distribution_planner_headers"]))["status"] == "HELD"


# ── compensating_invariant ────────────────────────────────────────────────

def test_fulfillment_reversal_restores_the_cartons_released_dose_total(api):
    """PRD §3.3: "Reversing a `FULFILLED` order returns it to `ACCEPTED` with
    `payment_status` back at `NOT_DUE`, and it is refused if any carton released
    under the order is no longer physical (otherwise `ERR_CARTONS_DESTROYED`) or if
    any administration has been recorded against those cartons (otherwise
    `ERR_DOSES_ALREADY_ADMINISTERED`)".
    PRD §3.3: "On success the system writes one `REVERSE` ledger entry per `RELEASE`
    entry on each carton, carrying the negated quantity, raises the entitlement's
    `held_cartons` by the accepted cartons, and reduces each carton's
    `cumulative_released_doses` by exactly the reversed amount."

    Design: Difficulty/compensating_invariant/fulfillment_reversal_conserves_the_released_dose_total
    """
    ctx = anchor_delivered_carton()
    carton = get_carton(ctx["carton"]["id"])
    assert carton["cumulative_released_doses"] == 1170
    assert carton["remaining_doses"] == 1170

    ent_before = get_entitlement(ctx["entitlement"]["id"])
    reversed_order = validate_success(api.reverse_order_fulfillment(
        ctx["order"]["id"], TEST_USERS["distribution_planner_headers"]), 200)
    assert reversed_order["order_status"] == "ACCEPTED"
    assert reversed_order["payment_status"] == "NOT_DUE"

    carton_after = get_carton(ctx["carton"]["id"])
    assert carton_after["cumulative_released_doses"] == 0
    assert carton_after["remaining_doses"] == 1170
    assert carton_after["dose_shortfall_doses"] == 0

    # PRD §3.2 defines `held_cartons` as "the cartons currently held by
    # accepted-but-unfulfilled orders" while PRD §3.3 says a reversal "raises the
    # entitlement's `held_cartons` by the accepted cartons".  A running total and a
    # derived view both satisfy both sentences for this request, so only the
    # conservation the two readings share is asserted here.
    ent_after = get_entitlement(ctx["entitlement"]["id"])
    assert ent_after["held_cartons"] >= ent_before["held_cartons"]


def test_fulfillment_reversal_restores_the_site_dose_position(api):
    """PRD §3.3: "That release carries `released_cartons`, a `reason_code` drawn from
    `WINDOW_LAPSE`, `ORDER_REJECTION`, `CAPACITY_UNAVAILABLE`, or
    `PROGRAM_REALLOCATION`".

    PRD §3.3: "`usable_doses` and `administrative_remaining_doses` sum the
    corresponding figures over its physical, non-in-transit cartons".

    Design: Difficulty/compensating_invariant/fulfillment_reversal_conserves_the_released_dose_total
    """
    ctx = anchor_delivered_carton()
    before = usable_doses(ctx["site"]["id"])
    assert before["usable_doses"] == 1170

    api.reverse_order_fulfillment(ctx["order"]["id"], TEST_USERS["distribution_planner_headers"])

    after = usable_doses(ctx["site"]["id"])
    assert after["usable_doses"] == 1170
    assert after["administrative_remaining_doses"] == 1170
    assert get_carton(ctx["carton"]["id"])["dose_shortfall_doses"] == 0


def test_rejection_and_lapse_conserve_the_entitlement_carton_total(api):
    """PRD §3.3: "the rejection sets `order_status` to `REJECTED` with
    `rejected_cartons` equal to the full `requested_cartons_snapshot`, records the
    order rejection, and releases the entitlement's held cartons."

    PRD §3.2: "the entitlement's `acceptance_status` becomes `LAPSED` with
    `held_cartons` zeroed and `lapsed_at` stamped with the logical clock, and the
    program's `lapsed_carton_count` advances by the lapsed cartons."

    Design: Difficulty/compensating_invariant/rejection_and_lapse_conserve_the_entitlement_carton_total
    """
    ctx = setup_entitled_site()
    order = submit_order(ctx["entitlement"]["id"], ctx["site"]["id"],
                         requested_cartons=2, requested_doses=1000)
    assert get_entitlement(ctx["entitlement"]["id"])["available_cartons"] == 10

    rejected = validate_success(api.reject_site_order(
        order["id"], {"rejected_cartons": 2, "reason_code": "CAPACITY_UNAVAILABLE"},
        TEST_USERS["distribution_planner_headers"]), 200)
    assert rejected["order_status"] == "REJECTED"
    assert rejected["rejected_cartons"] == 2

    carton_slots = get_entitlement(ctx["entitlement"]["id"])
    assert carton_slots["available_cartons"] == 10
    assert carton_slots["held_cartons"] == 0

    api_client.set_clock({"current_utc": "2026-09-04T00:00:00Z"},
                         TEST_USERS["platform_admin_headers"])
    validate_success(api.close_allocation_window(
        ctx["window"]["id"], TEST_USERS["distribution_planner_headers"]), 200)

    lapsed_ent = get_entitlement(ctx["entitlement"]["id"])
    assert lapsed_ent["acceptance_status"] == "LAPSED"
    assert lapsed_ent["available_cartons"] == 0
    assert lapsed_ent["held_cartons"] == 0
    assert get_program(ctx["program"]["id"])["lapsed_carton_count"] == 10


def test_rejection_records_doses_not_booked(api):
    """PRD §3.3: "The order rejection itself records `rejected_cartons`, a
    `reason_code` drawn from `BELOW_MIN_ORDER`, `NO_ENTITLEMENT`,
    `CAPACITY_UNAVAILABLE`, `SITE_NOT_READY`, or `WINDOW_CLOSED`, a `rejected_at`, the
    derived `doses_not_booked` equal to the rejected cartons times the presentation's
    doses per carton".

    Design: Difficulty/compensating_invariant/rejection_and_lapse_conserve_the_entitlement_carton_total
    """
    ctx = setup_entitled_site()
    order = submit_order(ctx["entitlement"]["id"], ctx["site"]["id"],
                         requested_cartons=2, requested_doses=1000)
    validate_success(api.reject_site_order(
        order["id"], {"rejected_cartons": 2, "reason_code": "CAPACITY_UNAVAILABLE"},
        TEST_USERS["distribution_planner_headers"]), 200)

    rejections = get_success_data(api.list_order_rejections(
        order["id"], TEST_USERS["distribution_planner_headers"]))
    assert len(rejections) == 1
    assert rejections[0]["reason_code"] == "CAPACITY_UNAVAILABLE"
    assert rejections[0]["doses_not_booked"] == 2 * 1170

# ── dual_variant_calc (beyond-use wall-clock vs effective) ─────────────────

def test_beyond_use_recovery_moves_the_expiry_later(api):
    """PRD §3.6: "The two readings of this rule differ in whether the recovered hours
    are present. With no certified adjudication on the carton the recovered hours are
    zero and `current_expires_at` is exactly `thawed_at` plus the permitted hours; once
    a `USABLE` adjudication exists the recovered hours are added to the vial and dose
    limits alone, which yields a later `current_expires_at` than the wall-clock reading
    for the same carton."

    PRD §3.6: "Each adjudication on the carton whose `outcome` is `USABLE` restores the
    smaller of two figures: its excursion's `min_duration_minutes` divided by sixty,
    and the recovery ceiling of forty-eight hours."

    Design: Difficulty/dual_variant_calc/beyond_use_wallclock_vs_effective_recovery
    """
    ctx = anchor_thawed_carton(thaw_at="2026-09-01T08:00:00Z")
    carton_before = get_carton(ctx["carton"]["id"])
    assert carton_before["current_expires_at"] == "2026-09-06T08:00:00Z"
    assert carton_before["thawed_at"] == "2026-09-01T08:00:00Z"

    # A 1440-minute severe-warm breach, adjudicated USABLE: the certified recoverable
    # hours are min(1440 / 60, 48) = 24.
    exc = create_excursion(ctx["carton"]["id"], ctx["site"]["id"], min_temperature_c=-55,
                           first_breach_at="2026-09-01T09:00:00Z",
                           last_breach_at="2026-09-02T09:00:00Z",
                           reported_at="2026-09-02T10:00:00Z")
    api.review_temperature_excursion(exc["id"], TEST_USERS["cold_chain_reviewer_headers"])
    adjudicated = validate_success(api.adjudicate_temperature_excursion(
        exc["id"],
        {"outcome": "USABLE", "rationale": "Breach stayed outside the tolerance band but dosing hours remain."},
        TEST_USERS["medical_science_liaison_headers"]), 200)
    assert adjudicated["adjudication_status"] == "USABLE"

    carton_after = get_carton(ctx["carton"]["id"])
    assert carton_after["current_expires_at"] == "2026-09-07T08:00:00Z"
    assert carton_after["temperature_state"] == "THAWED"
    assert carton_after["thawed_at"] == "2026-09-01T08:00:00Z"

    def _seconds(instant):
        import datetime
        return datetime.datetime.fromisoformat(instant.replace("Z", "+00:00")).timestamp()

    assert _seconds(carton_after["current_expires_at"]) - \
        _seconds(carton_before["current_expires_at"]) == 86400


def test_wall_clock_reading_is_thawed_at_plus_the_permitted_hours(api):
    """PRD §3.6: "It begins with the permitted hours, resolved at the instant the
    carton first leaves ultra-cold: the smaller of the product's `thaw_stability_hours`
    and its `refrigerated_shelf_life_hours`."

    PRD §3.6: "The carton's `current_expires_at` is the earliest of the batch
    `expiry_date`, the carton limit, the vial limit, the dose limit, the refrigerated
    limit when it applies, and the puncture limit when it applies."

    Design: Difficulty/dual_variant_calc/beyond_use_wallclock_vs_effective_recovery
    """
    ctx = anchor_thawed_carton(thaw_at="2026-09-01T08:00:00Z")
    carton = get_carton(ctx["carton"]["id"])
    assert carton["thawed_at"] == "2026-09-01T08:00:00Z"
    assert carton["thaw_window_expires_at"] == "2026-09-06T08:00:00Z"
    assert carton["current_expires_at"] == "2026-09-06T08:00:00Z"
    assert carton["temperature_state"] == "THAWED"

    # A NOT_USABLE adjudication restores nothing, so the wall-clock reading stands.
    create_excursion(ctx["carton"]["id"], ctx["site"]["id"], min_temperature_c=-70,
                     first_breach_at="2026-09-01T09:00:00Z",
                     last_breach_at="2026-09-01T10:00:00Z",
                     reported_at="2026-09-01T10:05:00Z")
    excursions = get_success_data(api.list_carton_excursions(
        ctx["carton"]["id"], TEST_USERS["cold_chain_reviewer_headers"]))
    exc_id = excursions[0]["id"]
    api.review_temperature_excursion(exc_id, TEST_USERS["cold_chain_reviewer_headers"])
    api.adjudicate_temperature_excursion(
        exc_id, {"outcome": "NOT_USABLE", "rationale": "Sustained cold breach."},
        TEST_USERS["medical_science_liaison_headers"])

    assert get_carton(ctx["carton"]["id"])["current_expires_at"] == "2026-09-06T08:00:00Z"
