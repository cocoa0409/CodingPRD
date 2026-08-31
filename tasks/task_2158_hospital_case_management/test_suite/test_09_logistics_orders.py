"""Equipment and transport logistics: the polymorphic order shape, the pinned cost,
the buffered vehicle window, and the conserved commitment ledger."""
from test_helpers import (
    CASE_MANAGER,
    DISCHARGE_COORDINATOR,
    ApiErrorId,
    assert_logistics_order,
    confirm_order,
    create_screening_draft,
    create_transport_order,
    document_choice_payload,
    open_episode,
    place_offer,
    read_episode,
    read_episode_version,
    read_logistics_order,
    read_referral,
    seed_dme_supplier,
    seed_patient,
    seed_payer,
    seed_vehicle,
    setup_broadcast_referral,
    setup_screened_episode,
    submit_screening_row,
    validate_error,
    validate_paginated,
    validate_success,
)

LAKESIDE = {
    "name": "Lakeside Choice", "coinsurance_pct": 0.200,
    "snf_auth_required": False, "hh_auth_required": False, "auth_expiry_days": 30,
}


def _screened_episode(payer_row, mrn, name="Sam Iverson", dob="1959-11-11"):
    """One admitted, screened episode on an existing payer."""
    patient = seed_patient(
        payer_row["id"], mrn=mrn, full_name=name, date_of_birth=dob,
        prior_admissions_180d=2, lives_alone=False, has_pcp=True,
    )
    episode = open_episode(patient["id"])
    screening = create_screening_draft(episode["id"])
    submit_screening_row(screening["id"])
    return read_episode(episode["id"])


def _shared_vehicle_scenario(vehicle_type="BLS_AMBULANCE"):
    payer = seed_payer(**LAKESIDE)
    vehicle = seed_vehicle(
        operator_name="Valley Medi-Ride", vehicle_type=vehicle_type,
        base_rate_cents=25000, per_mile_cents=900,
    )
    first = _screened_episode(payer, "MRN-VEH-001", "Sam Iverson", "1959-11-11")
    second = _screened_episode(payer, "MRN-VEH-002", "Tam Ruiz", "1961-02-02")
    return {"payer": payer, "vehicle": vehicle, "first": first, "second": second}


def test_buffered_transport_windows_sixty_minutes_apart_still_collide(api):
    """PRD §3.7: "Vehicle exclusivity is enforced with a symmetric turnaround buffer of
    forty-five minutes on each side: the order's window is expanded to run from three
    quarters of an hour before `window_start` to three quarters of an hour after
    `window_end`, and that expanded window must not intersect the identically expanded
    window of any other `CONFIRMED` `PATIENT_TRANSPORT` order on the same vehicle. Because
    both ends of these windows are inclusive, sharing even a single instant is a conflict,
    and the refusal is `ERR_VEHICLE_WINDOW_CONFLICT` (HTTP 409)."
    PRD §3.7: "A successful confirmation moves the order `REQUESTED → CONFIRMED`, adds its
    `cost_cents` to the episode's `logistics_committed_cents`, advances the episode's
    `version` by one, and — on the transport branch only — marks the buffered vehicle
    interval occupied."

    Design: Difficulty/resource_temporal_overlap/transport_window_closed_buffered_conflict_on_vehicle
    """
    env = _shared_vehicle_scenario()
    first_order = create_transport_order(
        env["first"]["id"], env["vehicle"]["id"], mileage_miles=12,
        window_start="2026-08-02T14:00:00Z", window_end="2026-08-02T15:00:00Z",
    )
    confirm_order(first_order["id"])
    second_order = create_transport_order(
        env["second"]["id"], env["vehicle"]["id"], mileage_miles=9,
        window_start="2026-08-02T16:00:00Z", window_end="2026-08-02T17:00:00Z",
    )

    response = api.confirm_logistics_order(second_order["id"], DISCHARGE_COORDINATOR)

    validate_error(response, ApiErrorId.ERR_VEHICLE_WINDOW_CONFLICT, 409)
    assert read_logistics_order(second_order["id"])["status"] == "REQUESTED"
    assert read_episode(env["second"]["id"])["logistics_committed_cents"] == 0
    assert read_logistics_order(first_order["id"])["status"] == "CONFIRMED"
    assert read_episode(env["first"]["id"])["logistics_committed_cents"] == 35800


def test_a_transport_window_clear_of_both_buffers_confirms(api):
    """PRD §3.7: "Vehicle exclusivity is enforced with a symmetric turnaround buffer of
    forty-five minutes on each side: the order's window is expanded to run from three
    quarters of an hour before `window_start` to three quarters of an hour after
    `window_end`, and that expanded window must not intersect the identically expanded
    window of any other `CONFIRMED` `PATIENT_TRANSPORT` order on the same vehicle."
    PRD §2.10: "`Episode.logistics_committed_cents` is the sum of `cost_cents` across that
    episode's logistics orders in `CONFIRMED` or `COMPLETED` status; confirming an order
    credits it, cancelling a confirmed order debits it by the same amount, and completing a
    confirmed order leaves it untouched because completion stays inside the committed set."

    Design: Difficulty/resource_temporal_overlap/transport_window_closed_buffered_conflict_on_vehicle
    """
    env = _shared_vehicle_scenario()
    first_order = create_transport_order(
        env["first"]["id"], env["vehicle"]["id"], mileage_miles=12,
        window_start="2026-08-02T14:00:00Z", window_end="2026-08-02T15:00:00Z",
    )
    confirm_order(first_order["id"])
    second_order = create_transport_order(
        env["second"]["id"], env["vehicle"]["id"], mileage_miles=9,
        window_start="2026-08-02T16:31:00Z", window_end="2026-08-02T17:31:00Z",
    )

    confirmed = validate_success(
        api.confirm_logistics_order(second_order["id"], DISCHARGE_COORDINATOR)
    )

    assert confirmed["status"] == "CONFIRMED", (
        "the buffered windows [13:15, 15:45] and [15:46, 18:16] share no instant"
    )
    assert confirmed["cost_cents"] == 33100
    assert read_episode(env["second"]["id"])["logistics_committed_cents"] == 33100
    assert read_episode(env["first"]["id"])["logistics_committed_cents"] == 35800


def test_confirming_then_cancelling_returns_the_commitment_ledger_to_zero(api):
    """PRD §2.10: "`Episode.logistics_committed_cents` is the sum of `cost_cents` across
    that episode's logistics orders in `CONFIRMED` or `COMPLETED` status; confirming an
    order credits it, cancelling a confirmed order debits it by the same amount, and
    completing a confirmed order leaves it untouched because completion stays inside the
    committed set."
    PRD §3.7: "Cancelling a `CONFIRMED` order is a compensating action: it subtracts that
    order's `cost_cents` from `logistics_committed_cents`, restoring the conserved total
    exactly, and on the transport branch releases the buffered vehicle interval so that it
    is immediately reusable by another order."
    PRD §3.7: "For a `PATIENT_TRANSPORT` order the cost is the vehicle's `base_rate_cents`
    plus its `per_mile_cents` multiplied by the order's `mileage_miles`, in exact integer
    cents with no rounding."

    Design: Difficulty/compensating_invariant/logistics_committed_cents_conserved_across_confirm_and_cancel
    """
    env = _shared_vehicle_scenario("WHEELCHAIR_VAN")
    order = create_transport_order(
        env["first"]["id"], env["vehicle"]["id"], mileage_miles=12,
        window_start="2026-08-02T14:00:00Z", window_end="2026-08-02T15:00:00Z",
    )
    assert order["cost_cents"] == 35800, "25000 base plus 900 per mile over 12 miles"
    assert read_episode(env["first"]["id"])["logistics_committed_cents"] == 0

    confirm_order(order["id"])
    assert read_episode(env["first"]["id"])["logistics_committed_cents"] == 35800

    cancelled = validate_success(
        api.cancel_logistics_order(
            order["id"], {"reason_code": "CLINICAL_CHANGE"}, DISCHARGE_COORDINATOR
        )
    )

    assert cancelled["status"] == "CANCELLED"
    assert cancelled["cancel_reason"] == "CLINICAL_CHANGE"
    assert cancelled["cost_cents"] == 35800, "the pinned cost is never rewritten"
    assert read_episode(env["first"]["id"])["logistics_committed_cents"] == 0, (
        "the compensating action restores the conserved total exactly"
    )


def test_cancelling_a_confirmed_order_frees_the_buffered_vehicle_window(api):
    """PRD §3.7: "Cancelling a `CONFIRMED` order is a compensating action: it subtracts
    that order's `cost_cents` from `logistics_committed_cents`, restoring the conserved
    total exactly, and on the transport branch releases the buffered vehicle interval so
    that it is immediately reusable by another order."
    PRD §3.7: "A successful confirmation moves the order `REQUESTED → CONFIRMED`, adds its
    `cost_cents` to the episode's `logistics_committed_cents`, advances the episode's
    `version` by one, and — on the transport branch only — marks the buffered vehicle
    interval occupied."

    Design: Difficulty/compensating_invariant/logistics_committed_cents_conserved_across_confirm_and_cancel
    """
    env = _shared_vehicle_scenario("WHEELCHAIR_VAN")
    first_order = create_transport_order(
        env["first"]["id"], env["vehicle"]["id"], mileage_miles=12,
        window_start="2026-08-02T14:00:00Z", window_end="2026-08-02T15:00:00Z",
    )
    second_order = create_transport_order(
        env["second"]["id"], env["vehicle"]["id"], mileage_miles=9,
        window_start="2026-08-02T16:00:00Z", window_end="2026-08-02T17:00:00Z",
    )
    assert second_order["cost_cents"] == 33100

    confirm_order(first_order["id"])
    blocked = api.confirm_logistics_order(second_order["id"], DISCHARGE_COORDINATOR)
    validate_error(blocked, ApiErrorId.ERR_VEHICLE_WINDOW_CONFLICT, 409)

    validate_success(
        api.cancel_logistics_order(
            first_order["id"], {"reason_code": "CLINICAL_CHANGE"}, DISCHARGE_COORDINATOR
        )
    )
    freed = validate_success(
        api.confirm_logistics_order(second_order["id"], DISCHARGE_COORDINATOR)
    )

    assert freed["status"] == "CONFIRMED", (
        "the cancelled order's buffered interval is immediately reusable"
    )
    assert read_episode(env["first"]["id"])["logistics_committed_cents"] == 0
    assert read_episode(env["second"]["id"])["logistics_committed_cents"] == 33100


def test_confirming_a_cancelled_order_reports_the_state_error_not_the_window_clash(api):
    """PRD §2.8: "The ladder is: authentication of the two headers first; then the
    endpoint's role list; then, for the entity-backed roles, the ownership comparison that
    yields `ERR_NOT_OWNER` (this applies to bed-offer creation, offer withdrawal, and
    authorization decisions); then left-to-right existence of every path resource; then
    request-body well-formedness, meaning required fields present, enum values that are
    declared members, integers inside their declared ranges — the three screening scores
    between 0 and 10 inclusive, `quality_star_rating` between 1 and 5 inclusive,
    `coinsurance_pct` between 0.000 and 0.500 inclusive, rates and day counts strictly
    positive — and `limit` inside 1 through 100, all failing as `ERR_VALIDATION`; then
    existence of every resource id referenced in the request **body** rather than the path,
    covering `patient_id`, `primary_payer_id`, `provider_id`, `vehicle_id`,
    `supplier_provider_id`, `destination_provider_id`, `chosen_bed_offer_id`, and every
    member of `provider_ids`, each failing with that resource type's own 404 code; then the
    two uniqueness constraints described below; then the optimistic-concurrency guard of
    §2.5; then state-machine admissibility; then the safety, referential, temporal and
    fiscal rules described throughout §3."
    PRD §3.7: "The order must be `REQUESTED`, or the refusal is
    `ERR_INVALID_LOGISTICS_STATE`, and the episode's `case_status` must be `PLANNING` or
    `READY_FOR_DISCHARGE`."

    Design: Difficulty/priority_pair_validation_conflict/state_beats_temporal_on_logistics_confirm_of_cancelled_order
    """
    env = _shared_vehicle_scenario()
    first_order = create_transport_order(
        env["first"]["id"], env["vehicle"]["id"], mileage_miles=12,
        window_start="2026-08-02T14:00:00Z", window_end="2026-08-02T15:00:00Z",
    )
    validate_success(
        api.cancel_logistics_order(
            first_order["id"], {"reason_code": "USER_REQUEST"}, CASE_MANAGER
        )
    )
    second_order = create_transport_order(
        env["second"]["id"], env["vehicle"]["id"], mileage_miles=9,
        window_start="2026-08-02T14:30:00Z", window_end="2026-08-02T15:30:00Z",
    )
    confirm_order(second_order["id"])

    response = api.confirm_logistics_order(first_order["id"], DISCHARGE_COORDINATOR)

    validate_error(response, ApiErrorId.ERR_INVALID_LOGISTICS_STATE, 409)
    assert response.json()["data"]["error_id"] != "ERR_VEHICLE_WINDOW_CONFLICT"
    assert read_logistics_order(first_order["id"])["status"] == "CANCELLED"
    assert read_episode(env["first"]["id"])["logistics_committed_cents"] == 0
    assert read_logistics_order(second_order["id"])["status"] == "CONFIRMED"
    assert read_episode(env["second"]["id"])["logistics_committed_cents"] == 33100


def test_the_window_clash_the_state_error_pre_empted_is_genuinely_present(api):
    """PRD §3.7: "Vehicle exclusivity is enforced with a symmetric turnaround buffer of
    forty-five minutes on each side: the order's window is expanded to run from three
    quarters of an hour before `window_start` to three quarters of an hour after
    `window_end`, and that expanded window must not intersect the identically expanded
    window of any other `CONFIRMED` `PATIENT_TRANSPORT` order on the same vehicle. Because
    both ends of these windows are inclusive, sharing even a single instant is a conflict,
    and the refusal is `ERR_VEHICLE_WINDOW_CONFLICT` (HTTP 409)."
    PRD §3.7: "The order must be `REQUESTED`, or the refusal is
    `ERR_INVALID_LOGISTICS_STATE`, and the episode's `case_status` must be `PLANNING` or
    `READY_FOR_DISCHARGE`."

    Design: Difficulty/priority_pair_validation_conflict/state_beats_temporal_on_logistics_confirm_of_cancelled_order
    """
    env = _shared_vehicle_scenario()
    first_order = create_transport_order(
        env["first"]["id"], env["vehicle"]["id"], mileage_miles=12,
        window_start="2026-08-02T14:00:00Z", window_end="2026-08-02T15:00:00Z",
    )
    validate_success(
        api.cancel_logistics_order(
            first_order["id"], {"reason_code": "USER_REQUEST"}, CASE_MANAGER
        )
    )
    second_order = create_transport_order(
        env["second"]["id"], env["vehicle"]["id"], mileage_miles=9,
        window_start="2026-08-02T14:30:00Z", window_end="2026-08-02T15:30:00Z",
    )
    confirm_order(second_order["id"])

    state_refusal = api.confirm_logistics_order(first_order["id"], DISCHARGE_COORDINATOR)
    validate_error(state_refusal, ApiErrorId.ERR_INVALID_LOGISTICS_STATE, 409)

    replacement = create_transport_order(
        env["first"]["id"], env["vehicle"]["id"], mileage_miles=12,
        window_start="2026-08-02T14:00:00Z", window_end="2026-08-02T15:00:00Z",
    )
    window_refusal = api.confirm_logistics_order(replacement["id"], DISCHARGE_COORDINATOR)

    validate_error(window_refusal, ApiErrorId.ERR_VEHICLE_WINDOW_CONFLICT, 409)
    assert read_logistics_order(replacement["id"])["status"] == "REQUESTED"
    assert read_episode(env["first"]["id"])["logistics_committed_cents"] == 0


def test_a_dme_order_costs_its_published_item_rate(api):
    """PRD §3.7: "For a `DME_DELIVERY` order the cost is a flat published rate keyed on
    `item_code`: a hospital bed costs 45000 cents, an oxygen concentrator 32000 cents, a
    wheelchair 21000 cents, a walker 8000 cents, and a CPAP unit 27000 cents."
    PRD §3.7: "An order is created in `REQUESTED` status with `cancel_reason` null, and
    creating one is a planning artifact, so an episode at `SCREENED` advances to `PLANNING`;
    the episode's `version` advances by one."

    Design: Corner/calculations/dme_order_cost_uses_item_rate_constant_not_vehicle_rates
    """
    env = setup_screened_episode(
        payer=dict(LAKESIDE),
        patient={
            "mrn": "MRN-C306", "full_name": "Quin Rossi", "date_of_birth": "1955-06-16",
            "prior_admissions_180d": 2, "lives_alone": False, "has_pcp": True,
        },
    )
    supplier = seed_dme_supplier()

    order = validate_success(
        api.create_logistics_order(
            env["episode"]["id"],
            {
                "expected_episode_version": read_episode_version(env["episode"]["id"]),
                "order_type": "DME_DELIVERY", "supplier_provider_id": supplier["id"],
                "item_code": "OXYGEN_CONCENTRATOR",
                "window_start": "2026-08-02T09:00:00Z",
                "window_end": "2026-08-02T12:00:00Z",
            },
            CASE_MANAGER,
        ),
        201,
    )

    assert_logistics_order(order)
    assert order["cost_cents"] == 32000, (
        f"the oxygen-concentrator rate is flat and vehicle-independent, got {order['cost_cents']}"
    )
    assert order["status"] == "REQUESTED"
    episode = read_episode(env["episode"]["id"])
    assert episode["logistics_committed_cents"] == 0, "a REQUESTED order is not committed"
    assert episode["case_status"] == "PLANNING"


def test_a_dme_order_carrying_a_vehicle_id_is_a_shape_mismatch(api):
    """PRD §3.7: "A `DME_DELIVERY` order additionally requires `supplier_provider_id` and
    `item_code` and must not carry `vehicle_id` or `mileage_miles`. Supplying a field the
    order type forbids, or omitting one it requires, is `ERR_ORDER_SHAPE_MISMATCH`
    (HTTP 422)."

    Design: Corner/validations/dme_order_carrying_vehicle_id_returns_order_shape_mismatch
    """
    env = setup_screened_episode(
        payer=dict(LAKESIDE),
        patient={
            "mrn": "MRN-D004", "full_name": "Sky Tanaka", "date_of_birth": "1951-08-08",
            "prior_admissions_180d": 2, "lives_alone": False, "has_pcp": True,
        },
    )
    supplier = seed_dme_supplier()
    vehicle = seed_vehicle()

    response = api.create_logistics_order(
        env["episode"]["id"],
        {
            "expected_episode_version": read_episode_version(env["episode"]["id"]),
            "order_type": "DME_DELIVERY", "supplier_provider_id": supplier["id"],
            "item_code": "WALKER", "vehicle_id": vehicle["id"],
            "window_start": "2026-08-02T09:00:00Z",
            "window_end": "2026-08-02T12:00:00Z",
        },
        CASE_MANAGER,
    )

    validate_error(response, ApiErrorId.ERR_ORDER_SHAPE_MISMATCH, 422)
    _, meta = validate_paginated(
        api.list_logistics_orders(CASE_MANAGER, params={"episode_id": env["episode"]["id"]})
    )
    assert meta["total_count"] == 0
    assert read_episode(env["episode"]["id"])["case_status"] == "SCREENED", (
        "the refused create is not a planning artifact"
    )


def test_a_new_transport_order_supersedes_the_confirmed_one_it_replaces(api):
    """PRD §3.7: "Creating a `PATIENT_TRANSPORT` order is also destructive by design: it
    supersedes any prior `PATIENT_TRANSPORT` order on the same episode whose `status` is
    `REQUESTED` or `CONFIRMED`, moving that prior order to `CANCELLED` with `cancel_reason`
    of `SUPERSEDED`, releasing its vehicle interval, and — when that prior order had been
    `CONFIRMED` — debiting `logistics_committed_cents` by its `cost_cents`."
    PRD §3.7: "For a `PATIENT_TRANSPORT` order the cost is the vehicle's `base_rate_cents`
    plus its `per_mile_cents` multiplied by the order's `mileage_miles`, in exact integer
    cents with no rounding."

    Design: Corner/cross_cutting_complexity_layers/transport_create_supersedes_prior_confirmed_transport_order
    """
    env = setup_screened_episode(
        payer=dict(LAKESIDE),
        patient={
            "mrn": "MRN-G003", "full_name": "Nam Lozano", "date_of_birth": "1942-09-09",
            "prior_admissions_180d": 2, "lives_alone": False, "has_pcp": True,
        },
    )
    vehicle = seed_vehicle(
        operator_name="Valley Medi-Ride", vehicle_type="WHEELCHAIR_VAN",
        base_rate_cents=25000, per_mile_cents=900,
    )
    first_order = create_transport_order(
        env["episode"]["id"], vehicle["id"], mileage_miles=12,
        window_start="2026-08-02T14:00:00Z", window_end="2026-08-02T15:00:00Z",
    )
    confirm_order(first_order["id"])
    assert read_episode(env["episode"]["id"])["logistics_committed_cents"] == 35800

    replacement = create_transport_order(
        env["episode"]["id"], vehicle["id"], mileage_miles=20,
        window_start="2026-08-02T14:30:00Z", window_end="2026-08-02T15:30:00Z",
    )

    superseded = read_logistics_order(first_order["id"])
    assert superseded["status"] == "CANCELLED"
    assert superseded["cancel_reason"] == "SUPERSEDED"
    assert read_episode(env["episode"]["id"])["logistics_committed_cents"] == 0
    assert replacement["cost_cents"] == 43000, "25000 base plus 900 per mile over 20 miles"

    confirmed = validate_success(
        api.confirm_logistics_order(replacement["id"], DISCHARGE_COORDINATOR)
    )
    assert confirmed["status"] == "CONFIRMED", (
        "the superseded order's buffered window was released, so the overlap clears"
    )
    assert read_episode(env["episode"]["id"])["logistics_committed_cents"] == 43000
    _, meta = validate_paginated(
        api.list_logistics_orders(CASE_MANAGER, params={"vehicle_id": vehicle["id"]})
    )
    assert meta["total_count"] == 2


def test_placement_pins_the_transport_destination_and_the_delivery_deadline(api):
    """PRD §3.7: "When the episode already has a referral in `PLACED` status and a supplied
    `destination_provider_id` differs from the provider of that referral's chosen offer, the
    request is refused with `ERR_TRANSPORT_DESTINATION_MISMATCH` (HTTP 422) — the hospital
    may not book transport to a facility the patient did not choose."
    PRD §3.7: "On the delivery branch, the supplier's `status` must be `ACTIVE` and its
    `provider_type` must be `DME_SUPPLIER`, and when the episode has a referral in `PLACED`
    status the delivery's `window_end` must be at or before that referral's `needed_by`; a
    delivery landing after the bed is needed is `ERR_DELIVERY_AFTER_NEEDED_BY` (HTTP 422)."
    PRD §3.7: "For a `DME_DELIVERY` order the cost is a flat published rate keyed on
    `item_code`: a hospital bed costs 45000 cents, an oxygen concentrator 32000 cents, a
    wheelchair 21000 cents, a walker 8000 cents, and a CPAP unit 27000 cents."

    Design: Corner/errors/transport_destination_and_dme_window_referential_rejections
    """
    env = setup_broadcast_referral(
        payer=dict(LAKESIDE),
        patient={
            "mrn": "MRN-E105", "full_name": "Fay Njoku", "date_of_birth": "1944-06-06",
            "prior_admissions_180d": 2, "lives_alone": False, "has_pcp": True,
        },
        referral={"requested_level_of_care": "SNF", "projected_stay_days": 14,
                  "needed_by": "2026-08-10T00:00:00Z"},
    )
    supplier = seed_dme_supplier()
    vehicle = seed_vehicle(
        operator_name="Valley Medi-Ride", vehicle_type="WHEELCHAIR_VAN",
        base_rate_cents=25000, per_mile_cents=900,
    )
    offer = place_offer(
        env["referral"]["id"], env["provider_a"]["id"], env["referral_version"],
        bed_available_from="2026-08-05T00:00:00Z", hold_expires_at="2026-08-09T00:00:00Z",
        daily_rate_cents=30000,
    )
    placed = validate_success(
        api.document_choice(
            env["referral"]["id"],
            document_choice_payload(offer["id"], choice_basis="CLINICAL_MATCH"),
            CASE_MANAGER,
        )
    )
    assert placed["status"] == "PLACED"
    assert placed["chosen_bed_offer_id"] == offer["id"]
    episode_id = env["episode"]["id"]

    wrong_destination = api.create_logistics_order(
        episode_id,
        {
            "expected_episode_version": read_episode_version(episode_id),
            "order_type": "PATIENT_TRANSPORT", "vehicle_id": vehicle["id"],
            "mileage_miles": 12, "destination_provider_id": env["provider_b"]["id"],
            "window_start": "2026-08-09T14:00:00Z", "window_end": "2026-08-09T15:00:00Z",
        },
        CASE_MANAGER,
    )
    validate_error(wrong_destination, ApiErrorId.ERR_TRANSPORT_DESTINATION_MISMATCH, 422)
    _, meta = validate_paginated(
        api.list_logistics_orders(CASE_MANAGER, params={"episode_id": episode_id})
    )
    assert meta["total_count"] == 0, "the refused create left no order row behind"

    late_delivery = validate_success(
        api.create_logistics_order(
            episode_id,
            {
                "expected_episode_version": read_episode_version(episode_id),
                "order_type": "DME_DELIVERY", "supplier_provider_id": supplier["id"],
                "item_code": "HOSPITAL_BED",
                "window_start": "2026-08-14T09:00:00Z",
                "window_end": "2026-08-14T12:00:00Z",
            },
            CASE_MANAGER,
        ),
        201,
    )
    assert late_delivery["cost_cents"] == 45000
    assert late_delivery["status"] == "REQUESTED"

    refused_confirm = api.confirm_logistics_order(late_delivery["id"], DISCHARGE_COORDINATOR)
    validate_error(refused_confirm, ApiErrorId.ERR_DELIVERY_AFTER_NEEDED_BY, 422)
    assert read_logistics_order(late_delivery["id"])["status"] == "REQUESTED"
    assert read_episode(episode_id)["logistics_committed_cents"] == 0

    accepted = validate_success(
        api.create_logistics_order(
            episode_id,
            {
                "expected_episode_version": read_episode_version(episode_id),
                "order_type": "PATIENT_TRANSPORT", "vehicle_id": vehicle["id"],
                "mileage_miles": 12, "destination_provider_id": env["provider_a"]["id"],
                "window_start": "2026-08-09T14:00:00Z", "window_end": "2026-08-09T15:00:00Z",
            },
            CASE_MANAGER,
        ),
        201,
    )
    assert accepted["status"] == "REQUESTED", (
        "the very same body naming the chosen provider is accepted"
    )
    assert read_referral(env["referral"]["id"])["status"] == "PLACED"
