"""Capacity pool boundaries, half-open overlap, and itinerary window rules."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    confirm_itinerary,
    confirm_slot,
    create_patient_payload,
    create_referral_payload,
    create_slot_payload,
    create_specialty_service_payload,
    get_case_itinerary,
    get_case_version,
    get_success_data,
    hold_slot_fresh,
    register_and_verify_record,
    set_clock,
    setup_case_with_holds,
    setup_cleared_case,
    setup_referral_in_review,
    validate_error,
    validate_success,
)

ADMIN = TEST_USERS["platform_admin_headers"]
IC = TEST_USERS["intake_coordinator_headers"]
IC_B = TEST_USERS["intake_coordinator_b_headers"]
FC = TEST_USERS["financial_counselor_headers"]
CR = TEST_USERS["case_reviewer_headers"]


def _second_cleared_case(api, card, neur):
    """Drive a second domestic referral+case to FINANCIAL_CLEARED."""
    referral_b = get_success_data(
        api.create_referral(
            create_referral_payload(
                patient=create_patient_payload(
                    full_name="Betty Boundary", residence_state="SD"
                )
            ),
            IC_B,
        )
    )
    register_and_verify_record(referral_b["id"], ic_headers=IC_B)
    get_success_data(api.submit_review(referral_b["id"], IC_B))
    case_b = get_success_data(
        api.create_visit_case(
            {
                "referral_id": referral_b["id"],
                "case_type": "DESTINATION",
                "care_team_specialty_ids": [card["id"], neur["id"]],
            },
            IC_B,
        )
    )
    get_success_data(
        api.create_case_review(
            case_b["id"], {"outcome": "APPROVE", "notes": "ok"}, CR
        )
    )
    get_success_data(
        api.create_billing_transaction(
            case_b["id"], {"txn_type": "DEPOSIT", "amount_cents": 60000}, FC
        )
    )
    return case_b


def _capacity_setup(api):
    """CARD capacity 2; case A holds two same-day CARD slots; third slot open."""
    ctx = setup_cleared_case()
    card, neur = ctx["services"]
    case_id = ctx["case"]["id"]
    slot_c1 = get_success_data(
        api.create_slot(card["id"], create_slot_payload(
            slot_date="2026-09-10", start_min=540, end_min=600), ADMIN)
    )
    slot_c2 = get_success_data(
        api.create_slot(card["id"], create_slot_payload(
            slot_date="2026-09-10", start_min=600, end_min=660), ADMIN)
    )
    slot_c3 = get_success_data(
        api.create_slot(card["id"], create_slot_payload(
            slot_date="2026-09-10", start_min=660, end_min=720), ADMIN)
    )
    hold_slot_fresh(case_id, slot_c1["id"], visit_type="CONSULT", sequencing_priority=1)
    hold_slot_fresh(case_id, slot_c2["id"], visit_type="IMAGING", sequencing_priority=2)
    case_b = _second_cleared_case(api, card, neur)
    return ctx, card, slot_c3, case_b


def test_capacity_boundary_exactly_at_pool_size(api):
    """PRD §3.1: "When the pool has already reached exactly capacity, the next
    hold is rejected with `ERR_CAPACITY_EXHAUSTED`; a hold that would bring
    the count to exactly capacity succeeds."

    Design: Difficulty/boundary_precision_check/capacity_boundary_exactly_at_pool_size
    """
    set_clock()
    _ctx, _card, slot_c3, case_b = _capacity_setup(api)
    # 2 HELD slots == capacity 2 -> the third hold must fail.
    resp = api.create_slot_hold(
        case_b["id"],
        {
            "appointment_slot_id": slot_c3["id"],
            "visit_type": "CONSULT",
            "listed_price_cents": 100000,
            "sequencing_priority": 1,
            "expected_case_version": get_case_version(case_b["id"]),
        },
        IC_B,
    )
    validate_error(resp, ApiErrorId.ERR_CAPACITY_EXHAUSTED)
    slot_after = get_success_data(api.get_slot(slot_c3["id"], IC))
    assert slot_after["status"] == "OPEN"


def test_hold_reaching_exactly_capacity_succeeds(api):
    """PRD §3.1: "When the pool has already reached exactly capacity, the next
    hold is rejected with `ERR_CAPACITY_EXHAUSTED`; a hold that would bring
    the count to exactly capacity succeeds."

    Design: Difficulty/boundary_precision_check/capacity_boundary_exactly_at_pool_size
    """
    set_clock()
    ctx = setup_cleared_case()
    card, _neur = ctx["services"]
    case_id = ctx["case"]["id"]
    slot1 = get_success_data(
        api.create_slot(card["id"], create_slot_payload(
            slot_date="2026-09-10", start_min=540, end_min=600), ADMIN)
    )
    slot2 = get_success_data(
        api.create_slot(card["id"], create_slot_payload(
            slot_date="2026-09-10", start_min=600, end_min=660), ADMIN)
    )
    # First hold: count 1 of 2. Second hold brings the count to exactly 2.
    hold_slot_fresh(case_id, slot1["id"], visit_type="CONSULT", sequencing_priority=1)
    resp = api.create_slot_hold(
        case_id,
        {
            "appointment_slot_id": slot2["id"],
            "visit_type": "IMAGING",
            "listed_price_cents": 100000,
            "sequencing_priority": 2,
            "expected_case_version": get_case_version(case_id),
        },
        IC,
    )
    validate_success(resp, 201)
    assert get_success_data(api.get_slot(slot2["id"], IC))["status"] == "HELD"


def test_adjacent_slot_creation_allowed(api):
    """PRD §3.1: "Two slots on the same service and date collide when each
    one's start falls strictly before the other's end — the half-open
    interval rule — and creation overlapping an existing slot is rejected
    with `ERR_SLOT_OVERLAP`. Adjacency is explicitly legal: one slot ending
    at the exact minute another begins does not overlap."

    Design: Difficulty/resource_temporal_overlap/half_open_slot_overlap_adjacency_allowed
    """
    set_clock()
    svc = get_success_data(
        api.create_specialty_service(
            create_specialty_service_payload(code="CARD", name="Cardiology"), ADMIN
        )
    )
    get_success_data(
        api.create_slot(svc["id"], create_slot_payload(
            slot_date="2026-09-10", start_min=540, end_min=600), ADMIN)
    )
    # [600,660) touches [540,600) at the boundary: legal.
    resp = api.create_slot(
        svc["id"],
        create_slot_payload(slot_date="2026-09-10", start_min=600, end_min=660),
        ADMIN,
    )
    slot = validate_success(resp, 201)
    assert slot["status"] == "OPEN"


def test_overlapping_slot_creation_rejected(api):
    """PRD §3.1: "creation overlapping an existing slot is rejected with
    `ERR_SLOT_OVERLAP`."

    Design: Difficulty/resource_temporal_overlap/half_open_slot_overlap_adjacency_allowed
    """
    set_clock()
    svc = get_success_data(
        api.create_specialty_service(
            create_specialty_service_payload(code="CARD", name="Cardiology"), ADMIN
        )
    )
    get_success_data(
        api.create_slot(svc["id"], create_slot_payload(
            slot_date="2026-09-10", start_min=540, end_min=600), ADMIN)
    )
    resp = api.create_slot(
        svc["id"],
        create_slot_payload(slot_date="2026-09-10", start_min=570, end_min=630),
        ADMIN,
    )
    validate_error(resp, ApiErrorId.ERR_SLOT_OVERLAP)


def test_capacity_counts_held_slots_regardless_of_intervals(api):
    """PRD §3.1: "The count is aggregate per date — two held slots on the same
    date consume two units of the pool regardless of whether their time
    intervals overlap — while the overlap rule independently forbids time
    collisions."

    Design: Difficulty/resource_temporal_overlap/aggregate_capacity_pool_consumption_distinct_from_intervals
    """
    set_clock()
    _ctx, _card, slot_c3, case_b = _capacity_setup(api)
    # slot_c3 [660,720) does not overlap [540,600) or [600,660), yet the pool
    # count (2) already equals capacity (2).
    resp = api.create_slot_hold(
        case_b["id"],
        {
            "appointment_slot_id": slot_c3["id"],
            "visit_type": "CONSULT",
            "listed_price_cents": 100000,
            "sequencing_priority": 1,
            "expected_case_version": get_case_version(case_b["id"]),
        },
        IC_B,
    )
    validate_error(resp, ApiErrorId.ERR_CAPACITY_EXHAUSTED)


def test_slot_release_restores_capacity_pool(api):
    """PRD §3.4: "Releasing a held slot returns it to the pool terminally: the
    slot becomes `RELEASED`, its pending visit becomes `CANCELLED`, the
    itinerary's `revision` increments by one, and both totals are
    recomputed."

    Design: Difficulty/compensating_invariant/visit_cancel_release_restores_capacity_pool
    """
    set_clock()
    ctx = setup_case_with_holds([{"start_min": 540, "end_min": 600}])
    case_id = ctx["case"]["id"]
    card = ctx["services"][0]
    slot = ctx["slots"][0]
    itinerary_before = get_success_data(api.get_itinerary(ctx["itinerary"]["id"], IC))

    resp = api.release_slot(slot["id"], IC)
    validate_success(resp, 200)
    assert get_success_data(api.get_slot(slot["id"], IC))["status"] == "RELEASED"
    itinerary_after = get_success_data(api.get_itinerary(ctx["itinerary"]["id"], IC))
    assert itinerary_after["revision"] == itinerary_before["revision"] + 1

    held = get_success_data(
        api.list_service_slots(
            card["id"], IC, params={"slot_date": "2026-09-10", "status": "HELD"}
        )
    )
    assert held == []


def test_fresh_hold_succeeds_after_release(api):
    """PRD §3.1: "the number of slots simultaneously in `HELD` or `CONFIRMED`
    status for a given service on a given date must stay strictly below
    `destination_daily_capacity` for a new hold to succeed."

    Design: Difficulty/compensating_invariant/visit_cancel_release_restores_capacity_pool
    """
    set_clock()
    _ctx, card, slot_c3, case_b = _capacity_setup(api)
    # Release one of case A's held slots: pool drops back to 1 of 2.
    held = get_success_data(
        api.list_service_slots(
            card["id"], IC, params={"slot_date": "2026-09-10", "status": "HELD"}
        )
    )
    assert len(held) == 2
    resp = api.release_slot(held[0]["id"], IC)
    validate_success(resp, 200)

    resp = api.create_slot_hold(
        case_b["id"],
        {
            "appointment_slot_id": slot_c3["id"],
            "visit_type": "CONSULT",
            "listed_price_cents": 100000,
            "sequencing_priority": 1,
            "expected_case_version": get_case_version(case_b["id"]),
        },
        IC_B,
    )
    validate_success(resp, 201)


def _window_setup(api, num_dates):
    """Cleared case with num_dates slots on distinct dates, all held and
    confirmed. Returns (case_id, itinerary_id, slots)."""
    rheu = get_success_data(
        api.create_specialty_service(
            create_specialty_service_payload(
                code="RHEU", name="Rheumatology", destination_daily_capacity=6,
                supports_imaging=False, supports_remote_products=True,
            ),
            ADMIN,
        )
    )
    card = get_success_data(
        api.create_specialty_service(
            create_specialty_service_payload(code="CARD2", name="Cardiology"), ADMIN
        )
    )
    dates = ["2026-09-14", "2026-09-15", "2026-09-16", "2026-09-17",
             "2026-09-18", "2026-09-21"][:num_dates]
    slots = [
        get_success_data(
            api.create_slot(rheu["id"], create_slot_payload(
                slot_date=d, start_min=540, end_min=600), ADMIN)
        )
        for d in dates
    ]
    referral, _rec = setup_referral_in_review(
        patient_overrides={"full_name": "Wendy Window", "residence_state": "ND"}
    )
    case = get_success_data(
        api.create_visit_case(
            {
                "referral_id": referral["id"],
                "case_type": "DESTINATION",
                "care_team_specialty_ids": [rheu["id"], card["id"]],
            },
            IC,
        )
    )
    get_success_data(
        api.create_case_review(case["id"], {"outcome": "APPROVE", "notes": "ok"}, CR)
    )
    get_success_data(
        api.create_billing_transaction(
            case["id"], {"txn_type": "DEPOSIT", "amount_cents": 60000}, FC
        )
    )
    case_id = case["id"]
    itinerary = get_case_itinerary(case_id)
    for slot in slots:
        hold_slot_fresh(case_id, slot["id"], visit_type="CONSULT",
                        listed_price_cents=100000, sequencing_priority=1)
    for slot in slots:
        confirm_slot(slot["id"])
    return case_id, itinerary["id"], slots


def test_slots_on_different_dates_do_not_share_capacity(api):
    """PRD §3.1: "The count is aggregate per date — two held slots on the same
    date consume two units of the pool regardless of whether their time
    intervals overlap — while the overlap rule independently forbids time
    collisions."

    Design: Difficulty/resource_temporal_overlap/aggregate_capacity_pool_consumption_distinct_from_intervals
    """
    set_clock()
    ctx = setup_cleared_case()
    card, _neur = ctx["services"]
    case_id = ctx["case"]["id"]
    # Fill the 2026-09-10 pool to capacity with two holds by this case.
    slot1 = get_success_data(
        api.create_slot(card["id"], create_slot_payload(
            slot_date="2026-09-10", start_min=540, end_min=600), ADMIN)
    )
    slot2 = get_success_data(
        api.create_slot(card["id"], create_slot_payload(
            slot_date="2026-09-10", start_min=600, end_min=660), ADMIN)
    )
    hold_slot_fresh(case_id, slot1["id"], visit_type="CONSULT", sequencing_priority=1)
    hold_slot_fresh(case_id, slot2["id"], visit_type="IMAGING", sequencing_priority=2)
    # A same-time-interval slot on a DIFFERENT date has its own pool: hold OK.
    slot_other_date = get_success_data(
        api.create_slot(card["id"], create_slot_payload(
            slot_date="2026-09-11", start_min=540, end_min=600), ADMIN)
    )
    resp = api.create_slot_hold(
        case_id,
        {
            "appointment_slot_id": slot_other_date["id"],
            "visit_type": "CONSULT",
            "listed_price_cents": 100000,
            "sequencing_priority": 3,
            "expected_case_version": get_case_version(case_id),
        },
        IC,
    )
    validate_success(resp, 201)
    assert (
        get_success_data(api.get_slot(slot_other_date["id"], IC))["status"] == "HELD"
    )


def test_itinerary_six_distinct_dates_rejected(api):
    """PRD §3.7: "the itinerary must compress into at most 5 distinct
    `slot_date` values among its `PENDING` and `CONFIRMED` visits — exactly 5
    distinct dates is allowed, 6 is rejected with
    `ERR_ITINERARY_WINDOW_EXCEEDED`."

    Design: Difficulty/boundary_precision_check/itinerary_window_exactly_five_days_allowed_six_rejected
    """
    set_clock()
    _case_id, itinerary_id, _slots = _window_setup(api, 6)
    resp = api.confirm_itinerary(itinerary_id, IC)
    validate_error(resp, ApiErrorId.ERR_ITINERARY_WINDOW_EXCEEDED)


def test_itinerary_five_distinct_dates_confirms(api):
    """PRD §3.7: "the itinerary must compress into at most 5 distinct
    `slot_date` values among its `PENDING` and `CONFIRMED` visits — exactly 5
    distinct dates is allowed, 6 is rejected with
    `ERR_ITINERARY_WINDOW_EXCEEDED`."

    Design: Difficulty/boundary_precision_check/itinerary_window_exactly_five_days_allowed_six_rejected
    """
    set_clock()
    _case_id, itinerary_id, _slots = _window_setup(api, 5)
    resp = api.confirm_itinerary(itinerary_id, IC)
    data = validate_success(resp, 200)
    assert data["status"] == "CONFIRMED"


def test_itinerary_confirm_with_pending_visits_rejected(api):
    """PRD §3.7: "no visit under the itinerary may remain `PENDING` — every
    one must be `CONFIRMED` (`ERR_UNCONFIRMED_VISITS_REMAIN`); and the
    itinerary must compress into at most 5 distinct `slot_date` values among
    its `PENDING` and `CONFIRMED` visits — exactly 5 distinct dates is
    allowed, 6 is rejected with `ERR_ITINERARY_WINDOW_EXCEEDED`."

    Design: Corner/endpoints/itinerary_confirm_with_pending_visits_rejected
    """
    set_clock()
    ctx = setup_case_with_holds([{"start_min": 540, "end_min": 600}])
    # Hold leaves the visit PENDING; confirming the itinerary must fail.
    resp = api.confirm_itinerary(ctx["itinerary"]["id"], IC)
    validate_error(resp, ApiErrorId.ERR_UNCONFIRMED_VISITS_REMAIN)
