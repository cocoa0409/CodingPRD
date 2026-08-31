"""Deliverable scheduling, production-slot capacity and the approval cascade."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    assert_deliverable,
    assert_production_slot,
    build_deal,
    create_deliverable_payload,
    make_athlete_headers,
    make_brand_rep_headers,
    open_production_slot,
    place_booking,
    read_engagement,
    register_athlete,
    review_deliverable_payload,
    schedule_deliverable,
    setup_four_line_engagement,
    submit_deliverable,
    submit_deliverable_payload,
    validate_error,
    validate_paginated,
    validate_success,
)

AGENT = TEST_USERS["talent_agent_headers"]


def test_deliverable_weight_is_derived_from_its_type(api):
    """PRD 3.7: "Every new deliverable opens in `PENDING` with `asset_url` null,
    `line_value_cents` null and `revision_count` 0, and its `weight` is derived from
    its `type` and never supplied by the client: a `SOCIAL_POST` weighs 1, an
    `APPEARANCE` weighs 4, and a `SHOOT` weighs 2."
    PRD 3.7: "A successful shoot creation increments that slot's `reserved_count` by
    1."

    Design: Corner/entities/deliverable_weight_computed_from_type
    """
    deal = build_deal(stage="active", signed_by_reference="CS-C-0001")
    slot = open_production_slot(name="Studio B", capacity=2)

    post = validate_success(
        api.create_deliverable(
            create_deliverable_payload(
                deal["engagement_id"], "SOCIAL_POST",
                due_date="2026-09-20", disclosure_required=False,
            ),
            AGENT,
        ),
        201,
    )
    shoot = validate_success(
        api.create_deliverable(
            create_deliverable_payload(
                deal["engagement_id"], "SHOOT", due_date="2026-09-16",
                disclosure_required=False, production_slot_id=slot["id"],
                shoot_start_at="2026-09-15T09:00:00Z",
                shoot_end_at="2026-09-15T13:00:00Z",
            ),
            AGENT,
        ),
        201,
    )
    assert_deliverable(post)
    assert_deliverable(shoot)

    assert post["weight"] == 1
    assert shoot["weight"] == 2
    assert post["status"] == "PENDING"
    assert post["line_value_cents"] is None

    stored_slot = validate_success(api.get_production_slot(slot["id"], AGENT))
    assert_production_slot(stored_slot)
    assert stored_slot["reserved_count"] == 1

    engagement = read_engagement(deal["engagement_id"])
    assert engagement["binding_fee_cents"] == 2_621_400


def test_shoot_outside_the_slot_window_is_refused(api):
    """PRD 3.7: "Shoot scheduling then meets the slot twice. First the reservation
    must lie inside the slot's own window: `shoot_start_at` at or after
    `window_start_at` and `shoot_end_at` at or before `window_end_at`, or the request
    is refused with `ERR_SLOT_WINDOW_VIOLATION`."

    Design: Corner/validations/shoot_outside_slot_window_returns_slot_window_violation
    """
    deal = build_deal(stage="active", signed_by_reference="CS-C-0002")
    slot = open_production_slot(
        name="Studio C", capacity=2,
        window_start_at="2026-09-01T00:00:00Z", window_end_at="2026-09-30T23:00:00Z",
    )

    response = api.create_deliverable(
        create_deliverable_payload(
            deal["engagement_id"], "SHOOT", due_date="2026-10-06",
            disclosure_required=False, production_slot_id=slot["id"],
            shoot_start_at="2026-10-05T13:00:00Z", shoot_end_at="2026-10-05T17:00:00Z",
        ),
        AGENT,
    )
    validate_error(response, ApiErrorId.ERR_SLOT_WINDOW_VIOLATION.value, 422)

    stored_slot = validate_success(api.get_production_slot(slot["id"], AGENT))
    assert stored_slot["reserved_count"] == 0

    rows, _meta = validate_paginated(
        api.list_deliverables(AGENT, params={"production_slot_id": slot["id"]})
    )
    assert rows == []


def test_back_to_back_shoot_reservations_do_not_contend(api):
    """PRD 2.7: "A shoot reservation covers the instants from `shoot_start_at`
    inclusive up to `shoot_end_at` exclusive. Two reservations whose boundaries merely
    meet — one ending exactly where the next begins — do not overlap."
    PRD 3.7: "Because the intervals are half-open, back-to-back reservations — one
    ending exactly where the next begins — never overlap and never contend for the
    same unit of capacity."

    Design: Difficulty/resource_temporal_overlap/production_slot_half_open_adjacency_allowed_capacity_exceeded
    """
    deal = build_deal(stage="active", signed_by_reference="CS-2026-0005")
    slot = open_production_slot(capacity=1)
    schedule_deliverable(
        deal["engagement_id"], "SHOOT", due_date="2026-09-16",
        disclosure_required=False, production_slot_id=slot["id"],
        shoot_start_at="2026-09-15T09:00:00Z", shoot_end_at="2026-09-15T13:00:00Z",
    )

    response = api.create_deliverable(
        create_deliverable_payload(
            deal["engagement_id"], "SHOOT", due_date="2026-09-17",
            disclosure_required=False, production_slot_id=slot["id"],
            shoot_start_at="2026-09-15T13:00:00Z", shoot_end_at="2026-09-15T17:00:00Z",
        ),
        AGENT,
    )
    adjacent = validate_success(response, 201)
    assert adjacent["status"] == "PENDING"

    stored_slot = validate_success(api.get_production_slot(slot["id"], AGENT))
    assert stored_slot["reserved_count"] == 2


def test_third_overlapping_reservation_exceeds_the_slot_capacity(api):
    """PRD 3.7: "Second the aggregate capacity is tested. The reservation covers the
    instants from `shoot_start_at` inclusive up to `shoot_end_at` exclusive, and
    across all deliverable rows on that same slot whose `status` is anything other
    than `VOIDED`, no single instant may be covered by more reservations than the
    slot's `capacity` allows."
    PRD 3.7: "Breaching the ceiling is refused with `ERR_SLOT_CAPACITY_EXCEEDED`. A
    successful shoot creation increments that slot's `reserved_count` by 1."

    Design: Difficulty/resource_temporal_overlap/production_slot_half_open_adjacency_allowed_capacity_exceeded
    """
    deal = build_deal(stage="active", signed_by_reference="CS-2026-0005")
    slot = open_production_slot(capacity=1)
    schedule_deliverable(
        deal["engagement_id"], "SHOOT", due_date="2026-09-16",
        disclosure_required=False, production_slot_id=slot["id"],
        shoot_start_at="2026-09-15T09:00:00Z", shoot_end_at="2026-09-15T13:00:00Z",
    )
    schedule_deliverable(
        deal["engagement_id"], "SHOOT", due_date="2026-09-17",
        disclosure_required=False, production_slot_id=slot["id"],
        shoot_start_at="2026-09-15T13:00:00Z", shoot_end_at="2026-09-15T17:00:00Z",
    )

    response = api.create_deliverable(
        create_deliverable_payload(
            deal["engagement_id"], "SHOOT", due_date="2026-09-18",
            disclosure_required=False, production_slot_id=slot["id"],
            shoot_start_at="2026-09-15T12:00:00Z", shoot_end_at="2026-09-15T16:00:00Z",
        ),
        AGENT,
    )
    validate_error(response, ApiErrorId.ERR_SLOT_CAPACITY_EXCEEDED.value, 409)

    stored_slot = validate_success(api.get_production_slot(slot["id"], AGENT))
    assert stored_slot["reserved_count"] == 2

    rows, meta = validate_paginated(
        api.list_deliverables(AGENT, params={"production_slot_id": slot["id"]})
    )
    assert len(rows) == 2
    assert meta["total_count"] == 2


def test_appearance_deliverable_naming_a_foreign_booking_is_refused(api):
    """PRD 3.7: "An `APPEARANCE` deliverable must carry a `booking_id`, and the
    booking it names must belong to the *same* engagement as the deliverable itself;
    it must not carry a `production_slot_id`, a `shoot_start_at` or a `shoot_end_at`."
    PRD 3.7: "Any departure from that shape — an appearance without a booking, an
    appearance whose booking belongs to another engagement, a shoot missing its slot
    or window, a social post carrying either — is refused with
    `ERR_BOOKING_ENGAGEMENT_MISMATCH`."

    Design: Corner/validations/appearance_deliverable_with_foreign_booking_returns_mismatch
    """
    deal_a = build_deal(stage="active", signed_by_reference="CS-C-0002")
    deal_b = build_deal(
        stage="pending", clock=None, athlete=deal_a["athlete"],
        brand_overrides={
            "name": "Kite Footwear", "category": "FOOTWEAR",
            "legal_entity_name": "Kite Footwear Ltd",
        },
        opportunity_overrides={
            "exclusivity_category": "FOOTWEAR", "exclusivity_months": 6,
        },
        term_sheet_overrides={
            "fee_cents": 1_000_000, "morals_clause_tier": "TIER_C", "exclusivity_months": 6,
        },
        screening_officer="co-screen-2",
    )
    foreign_booking = place_booking(
        deal_b["engagement_id"], city="Denver",
        start_at="2026-09-10T14:00:00Z", end_at="2026-09-10T22:00:00Z",
        travel_buffer_hours=0,
    )

    response = api.create_deliverable(
        create_deliverable_payload(
            deal_a["engagement_id"], "APPEARANCE", due_date="2026-09-11",
            disclosure_required=False, booking_id=foreign_booking["id"],
        ),
        AGENT,
    )
    validate_error(response, ApiErrorId.ERR_BOOKING_ENGAGEMENT_MISMATCH.value, 422)

    rows, _meta = validate_paginated(
        api.list_deliverables(AGENT, params={"engagement_id": deal_a["engagement_id"]})
    )
    assert rows == []
    rows, _meta = validate_paginated(
        api.list_deliverables(AGENT, params={"booking_id": foreign_booking["id"]})
    )
    assert rows == []


def test_deliverables_filtered_by_booking_id_return_only_that_booking(api):
    """PRD 3.7: "Deliverables can be listed and filtered by `engagement_id`,
    `booking_id`, `production_slot_id`, `status` and `type`."
    PRD 3.7: "Every new deliverable opens in `PENDING` with `asset_url` null,
    `line_value_cents` null and `revision_count` 0, and its `weight` is derived from
    its `type` and never supplied by the client: a `SOCIAL_POST` weighs 1, an
    `APPEARANCE` weighs 4, and a `SHOOT` weighs 2."

    Design: Corner/endpoints/deliverables_filtered_by_booking_id_returns_only_that_booking
    """
    deal = build_deal(stage="pending")
    booking = place_booking(
        deal["engagement_id"], city="Chicago",
        start_at="2026-09-10T14:00:00Z", end_at="2026-09-10T22:00:00Z",
        travel_buffer_hours=12,
    )
    from test_helpers import countersign_engagement

    countersign_engagement(deal["engagement_id"], "CS-C-0002")
    appearance = schedule_deliverable(
        deal["engagement_id"], "APPEARANCE", due_date="2026-09-11",
        disclosure_required=False, booking_id=booking["id"],
    )
    schedule_deliverable(
        deal["engagement_id"], "SOCIAL_POST", due_date="2026-09-20",
        disclosure_required=False,
    )

    rows, _meta = validate_paginated(
        api.list_deliverables(AGENT, params={"booking_id": booking["id"]})
    )
    assert len(rows) == 1
    assert rows[0]["id"] == appearance["id"]
    assert rows[0]["type"] == "APPEARANCE"
    assert rows[0]["weight"] == 4

    rows, meta = validate_paginated(
        api.list_deliverables(AGENT, params={"engagement_id": deal["engagement_id"]})
    )
    assert len(rows) == 2
    assert meta["total_count"] == 2


def test_revision_cycle_returns_the_deliverable_to_submitted(api):
    """PRD 3.7: "A `decision` of `REQUEST_REVISION` moves the deliverable
    `SUBMITTED → REVISION_REQUESTED` and increments its `revision_count` by 1. Nothing
    else moves: `approved_deliverable_count` is unchanged and no completion cascade
    fires. The athlete may then resubmit, closing the cycle
    `SUBMITTED → REVISION_REQUESTED → SUBMITTED` as many times as the parties need."
    PRD 3.7: "Submitting supplies an `asset_url`, requires the engagement to be
    `ACTIVE`, requires the submitting `Athlete`'s `X-User-ID` to equal the
    engagement's `athlete_id`, and moves the deliverable `PENDING → SUBMITTED` on a
    first submission or `REVISION_REQUESTED → SUBMITTED` on a resubmission,
    overwriting the stored `asset_url` in the latter case."

    Design: Corner/state_machines/deliverable_revision_cycle_returns_to_submitted
    """
    deal = build_deal(stage="active", signed_by_reference="CS-C-0002")
    deliverable = schedule_deliverable(
        deal["engagement_id"], "SOCIAL_POST", due_date="2026-09-20",
        disclosure_required=False,
    )
    submit_deliverable(deliverable["id"], deal["athlete_id"], "https://cdn.example/v1.jpg")

    bounced = validate_success(
        api.review_deliverable(
            deliverable["id"],
            review_deliverable_payload("REQUEST_REVISION", "Logo is cropped"),
            make_brand_rep_headers(deal["brand_id"]),
        ),
        200,
    )
    assert bounced["status"] == "REVISION_REQUESTED"
    assert bounced["revision_count"] == 1

    engagement = read_engagement(deal["engagement_id"])
    assert engagement["approved_deliverable_count"] == 0
    assert engagement["contract_status"] == "ACTIVE"

    resubmitted = validate_success(
        api.submit_deliverable(
            deliverable["id"],
            submit_deliverable_payload("https://cdn.example/v2.jpg"),
            make_athlete_headers(deal["athlete_id"]),
        ),
        200,
    )
    assert resubmitted["status"] == "SUBMITTED"
    assert resubmitted["asset_url"] == "https://cdn.example/v2.jpg"
    assert resubmitted["revision_count"] == 1


def test_submitting_an_approved_deliverable_is_refused(api):
    """PRD 3.7: "Submitting from any other status — `APPROVED`, `VOIDED` or
    `SUBMITTED` — is refused with `ERR_DELIVERABLE_INVALID_STATE`, and submitting
    against an engagement that is not `ACTIVE` is refused with
    `ERR_ENGAGEMENT_NOT_ACTIVE`."

    Design: Corner/validations/deliverable_submit_from_approved_returns_invalid_state
    """
    # Two planned posts, so approving one line leaves the engagement ACTIVE and
    # the refusal under test is the deliverable's own from-state, not the
    # engagement contract-status rung that precedes it in the PRD ladder.
    deal = build_deal(
        stage="active", signed_by_reference="CS-C-0002",
        opportunity_overrides={"planned_posts": 2, "proposed_fee_cents": 200_000},
    )
    deliverable = schedule_deliverable(
        deal["engagement_id"], "SOCIAL_POST", due_date="2026-09-20",
        disclosure_required=False,
    )
    submit_deliverable(deliverable["id"], deal["athlete_id"], "https://cdn.example/s1.jpg")
    validate_success(
        api.review_deliverable(
            deliverable["id"], review_deliverable_payload("APPROVE"),
            make_brand_rep_headers(deal["brand_id"]),
        ),
        200,
    )

    response = api.submit_deliverable(
        deliverable["id"], submit_deliverable_payload("https://cdn.example/s2.jpg"),
        make_athlete_headers(deal["athlete_id"]),
    )
    validate_error(response, ApiErrorId.ERR_DELIVERABLE_INVALID_STATE.value, 409)

    stored = validate_success(api.get_deliverable(deliverable["id"], AGENT))
    assert stored["status"] == "APPROVED"
    assert stored["asset_url"] == "https://cdn.example/s1.jpg"
    assert read_engagement(deal["engagement_id"])["approved_deliverable_count"] == 1


def test_another_athlete_may_not_submit_the_asset(api):
    """PRD 2.1: "When `X-User-Role` is `Athlete`, `X-User-ID` is the `id` of the
    acting `Athlete`; ownership checks on any resource that references an `Athlete`
    compare the resource's athlete foreign-key field — `athlete_id` on the engagement
    behind the resource — to `X-User-ID`. A mismatch in either case is rejected with
    `ERR_NOT_RESOURCE_OWNER` (HTTP 403)."
    PRD 3.7: "Submitting supplies an `asset_url`, requires the engagement to be
    `ACTIVE`, requires the submitting `Athlete`'s `X-User-ID` to equal the
    engagement's `athlete_id`, and moves the deliverable `PENDING → SUBMITTED` on a
    first submission or `REVISION_REQUESTED → SUBMITTED` on a resubmission,
    overwriting the stored `asset_url` in the latter case."

    Design: Corner/rbac/athlete_cannot_submit_another_athletes_deliverable
    """
    deal = build_deal(stage="active", signed_by_reference="CS-C-0002")
    deliverable = schedule_deliverable(
        deal["engagement_id"], "SOCIAL_POST", due_date="2026-09-20",
        disclosure_required=False,
    )
    other_athlete = register_athlete(
        full_name="Ivo Marchetti", sport="TENNIS", market_tier="REGIONAL",
        base_appearance_rate_cents=120_000, commission_pct=0.1,
    )

    response = api.submit_deliverable(
        deliverable["id"], submit_deliverable_payload("https://cdn.example/wrong.jpg"),
        make_athlete_headers(other_athlete["id"]),
    )
    validate_error(response, ApiErrorId.ERR_NOT_RESOURCE_OWNER.value, 403)

    stored = validate_success(api.get_deliverable(deliverable["id"], AGENT))
    assert stored["status"] == "PENDING"
    assert stored["asset_url"] is None


def test_approving_the_third_line_moves_only_the_counter(api):
    """PRD 3.7: "When the gate passes, the deliverable moves `SUBMITTED → APPROVED`
    and a four-hop cascade runs: because the deliverable became `APPROVED`, the
    engagement's `approved_deliverable_count` increments by 1; if that counter has now
    reached `required_deliverable_count`, the engagement's `contract_status` moves
    `ACTIVE → COMPLETED`; and because `contract_status` became `COMPLETED`, the
    engagement's `settlement_status` moves `UNBILLED → BILLABLE`, opening settlement.
    If the counter has not yet reached the required total, the engagement stays
    `ACTIVE` and the settlement dimension does not move."

    Design: Difficulty/transitive_cascade/approve_final_deliverable_completes_contract_flips_settlement_billable
    """
    deal = setup_four_line_engagement(approve_upto=3)

    engagement = read_engagement(deal["engagement_id"])
    assert engagement["required_deliverable_count"] == 4
    assert engagement["approved_deliverable_count"] == 3
    assert engagement["contract_status"] == "ACTIVE"
    assert engagement["settlement_status"] == "UNBILLED"
    assert engagement["accrued_fee_cents"] == 180_500


def test_approving_the_final_line_completes_the_contract_and_opens_settlement(api):
    """PRD 3.7: "When the gate passes, the deliverable moves `SUBMITTED → APPROVED`
    and a four-hop cascade runs: because the deliverable became `APPROVED`, the
    engagement's `approved_deliverable_count` increments by 1; if that counter has now
    reached `required_deliverable_count`, the engagement's `contract_status` moves
    `ACTIVE → COMPLETED`; and because `contract_status` became `COMPLETED`, the
    engagement's `settlement_status` moves `UNBILLED → BILLABLE`, opening settlement."
    PRD 3.10: "It sits at `UNBILLED` from acceptance and moves to `BILLABLE` the
    moment the contract dimension enters either `COMPLETED` or `TERMINATED` — those
    are the only two doors into billability, and neither is triggered directly by a
    caller."

    Design: Difficulty/transitive_cascade/approve_final_deliverable_completes_contract_flips_settlement_billable
    """
    deal = setup_four_line_engagement(approve_upto=3)
    final_line = deal["deliverables"][3]

    approved = validate_success(
        api.review_deliverable(
            final_line["id"], review_deliverable_payload("APPROVE"),
            make_brand_rep_headers(deal["brand_id"]),
        ),
        200,
    )
    assert approved["status"] == "APPROVED"

    engagement = read_engagement(deal["engagement_id"])
    assert engagement["approved_deliverable_count"] == 4
    assert engagement["contract_status"] == "COMPLETED"
    assert engagement["settlement_status"] == "BILLABLE"
    assert engagement["accrued_fee_cents"] == 180_500, "approval writes no ledger entry"
