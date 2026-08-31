"""Countersignature pricing, the termination unwind and the conserved counters."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    assert_engagement,
    assert_exclusivity_grant,
    build_deal,
    countersign_engagement,
    countersign_payload,
    make_compliance_officer_headers,
    read_engagement,
    schedule_deliverable,
    setup_engagement_ready_for_unwind,
    setup_engagement_with_confirmed_booking,
    setup_two_engagement_athlete,
    terminate_engagement,
    terminate_payload,
    validate_error,
    validate_paginated,
    validate_success,
)

AGENT = TEST_USERS["talent_agent_headers"]
FINANCE = TEST_USERS["finance_manager_headers"]
ENFORCER = make_compliance_officer_headers("co-enforce-1")


def test_binding_fee_folds_in_the_confirmed_bookings_travel_component(api):
    """PRD 3.5: "The one and only difference is the travel component, which for the
    binding figure is no longer zero. It is the sum of `travel_cost_cents` over the
    engagement's appearance bookings whose `status` is `CONFIRMED` or `COMPLETED`,
    taken in `created_at` ascending order, plus a travel-day allowance obtained by
    multiplying the athlete's `base_appearance_rate_cents` by twenty-five percent and
    by the total travel days of those same bookings, rounded half up to whole cents
    once."
    PRD 3.3: "The two components are added to a travel component, which for the
    provisional figure is always exactly zero — even when confirmed bookings already
    exist elsewhere on the athlete's book."

    Design: Difficulty/dual_variant_calc/provisional_vs_binding_appearance_fee_diverge
    """
    deal = setup_engagement_with_confirmed_booking()
    assert deal["term_sheet"]["provisional_fee_cents"] == 2_621_400
    assert deal["engagement"]["provisional_fee_cents"] == 2_621_400

    response = api.countersign_engagement(
        deal["engagement_id"], countersign_payload("CS-2026-0001"), FINANCE
    )
    engagement = validate_success(response, 200)
    assert_engagement(engagement)

    assert engagement["binding_fee_cents"] == 3_001_900
    assert engagement["provisional_fee_cents"] == 2_621_400
    assert engagement["binding_fee_cents"] - engagement["provisional_fee_cents"] == 380_500


def test_countersignature_activates_the_engagement_over_the_priced_travel_days(api):
    """PRD 3.5: "A `FinanceManager` countersigns an engagement sitting in
    `PENDING_COUNTERSIGN`, supplying a `signed_by_reference` naming the executed paper
    copy, and the engagement moves `PENDING_COUNTERSIGN → ACTIVE`."
    PRD 3.5: "Total travel days is the sum of the `travel_days` of each qualifying
    booking."
    PRD 3.6: "Confirming a hold moves it `HOLD → CONFIRMED` and requires the
    engagement to still be `PENDING_COUNTERSIGN` or `ACTIVE`. The call carries the
    reimbursable `travel_cost_cents` actually committed, and it derives `travel_days`:
    take the span from `start_at` to `end_at` in hours, add twice
    `travel_buffer_hours`, divide by 24 and round *up* to a whole number of days."

    Design: Difficulty/dual_variant_calc/provisional_vs_binding_appearance_fee_diverge
    """
    deal = setup_engagement_with_confirmed_booking()
    assert deal["booking"]["travel_days"] == 2

    engagement = countersign_engagement(deal["engagement_id"], "CS-2026-0001")

    assert engagement["contract_status"] == "ACTIVE"
    booking = validate_success(api.get_appearance_booking(deal["booking"]["id"], AGENT))
    assert booking["travel_days"] == 2
    assert booking["status"] == "CONFIRMED"


def test_termination_releases_the_grant_and_rescores_the_athlete(api):
    """PRD 3.9: "Exclusivity is released first. Every exclusivity grant of this
    engagement whose `status` is `PENDING` or `ACTIVE` is released, so the edge fires
    as `ACTIVE → RELEASED` or as `PENDING → RELEASED` depending on where the grant
    stood, and `released_at` is stamped with the logical clock in both cases. On an
    `ACTIVE → RELEASED` release the athlete's `active_exclusivity_count` decrements by
    1, and because that counter changed, `exposure_risk_snapshot_score` is
    recomputed."
    PRD 3.9: "The call carries a `reason_code`, which is stored as
    `terminated_reason_code`, and moves the engagement `PENDING_COUNTERSIGN →
    TERMINATED` or `ACTIVE → TERMINATED` respectively."

    Design: Difficulty/transitive_cascade/terminate_engagement_releases_grant_decrements_counter_rescores_athlete
    """
    deal = setup_engagement_ready_for_unwind()
    before = validate_success(api.get_athlete(deal["athlete_id"], AGENT))
    assert before["active_exclusivity_count"] == 1
    assert before["exposure_risk_snapshot_score"] == 28

    engagement = validate_success(
        api.terminate_engagement(
            deal["engagement_id"], terminate_payload("MORALS_BREACH"), ENFORCER
        ),
        200,
    )
    assert engagement["contract_status"] == "TERMINATED"
    assert engagement["terminated_reason_code"] == "MORALS_BREACH"

    grants, _meta = validate_paginated(
        api.list_engagement_exclusivity_grants(deal["engagement_id"], AGENT)
    )
    assert len(grants) == 1
    assert_exclusivity_grant(grants[0])
    assert grants[0]["status"] == "RELEASED"
    assert grants[0]["released_at"] is not None

    athlete = validate_success(api.get_athlete(deal["athlete_id"], AGENT))
    assert athlete["active_exclusivity_count"] == 0
    assert athlete["exposure_risk_snapshot_score"] == 0


def test_termination_cancels_bookings_voids_work_and_opens_settlement(api):
    """PRD 3.9: "The calendar is released second. Every appearance booking of this
    engagement whose `status` is `HOLD` or `CONFIRMED` moves to `CANCELLED` with
    `cancel_reason_code` set to the literal string `AUTO_TERMINATION`. For each
    booking that was `CONFIRMED`, a `REVERSAL` ledger entry is appended whose
    `amount_cents` is the negative of that booking's `travel_cost_cents`; because
    those entries were appended, the engagement's `accrued_fee_cents` falls by the
    same total."
    PRD 3.9: "Outstanding work is voided third. Every deliverable of this engagement
    whose `status` is `PENDING`, `SUBMITTED` or `REVISION_REQUESTED` is voided — the
    edge fires as `PENDING → VOIDED`, `SUBMITTED → VOIDED` or
    `REVISION_REQUESTED → VOIDED` as appropriate — and for each voided deliverable of
    type `SHOOT` the referenced production slot's `reserved_count` decrements by 1,
    freeing that half-open window for other reservations."
    PRD 3.9: "Settlement is opened fourth. Because the engagement became
    `TERMINATED`, its `settlement_status` moves `UNBILLED → BILLABLE`, so whatever was
    accrued and approved before the termination can still be paid out."

    Design: Difficulty/transitive_cascade/terminate_engagement_releases_grant_decrements_counter_rescores_athlete
    """
    deal = setup_engagement_ready_for_unwind()

    terminate_engagement(deal["engagement_id"], reason_code="MORALS_BREACH")

    booking = validate_success(api.get_appearance_booking(deal["booking"]["id"], AGENT))
    assert booking["status"] == "CANCELLED"
    assert booking["cancel_reason_code"] == "AUTO_TERMINATION"

    entries, _meta = validate_paginated(
        api.list_ledger_entries(deal["engagement_id"], FINANCE)
    )
    assert [e["entry_type"] for e in entries] == ["TRAVEL_ACCRUAL", "REVERSAL"]
    assert [e["amount_cents"] for e in entries] == [180_500, -180_500]

    shoot = validate_success(api.get_deliverable(deal["shoot"]["id"], AGENT))
    assert shoot["status"] == "VOIDED"
    slot = validate_success(api.get_production_slot(deal["slot"]["id"], AGENT))
    assert slot["reserved_count"] == 0

    engagement = read_engagement(deal["engagement_id"])
    assert engagement["accrued_fee_cents"] == 0
    assert engagement["settlement_status"] == "BILLABLE"


def test_terminating_one_of_two_engagements_returns_the_counter_to_one(api):
    """PRD 2.9: "An athlete's `active_exclusivity_count` is the number of that
    athlete's exclusivity grants whose `status` is `ACTIVE`."
    PRD 3.9: "On an `ACTIVE → RELEASED` release the athlete's
    `active_exclusivity_count` decrements by 1, and because that counter changed,
    `exposure_risk_snapshot_score` is recomputed."

    Design: Difficulty/compensating_invariant/terminate_releases_exclusivity_slot_count_returns_to_baseline
    """
    pair = setup_two_engagement_athlete()
    athlete_id = pair["athlete"]["id"]

    before = validate_success(api.get_athlete(athlete_id, AGENT))
    assert before["active_exclusivity_count"] == 2
    assert before["exposure_risk_snapshot_score"] == 48

    terminate_engagement(
        pair["deal_b"]["engagement_id"], reason_code="BRAND_WITHDRAWAL"
    )

    after = validate_success(api.get_athlete(athlete_id, AGENT))
    assert after["active_exclusivity_count"] == 1
    assert after["exposure_risk_snapshot_score"] == 28

    active_grants, _meta = validate_paginated(
        api.list_athlete_exclusivity_grants(athlete_id, AGENT, params={"status": "ACTIVE"})
    )
    assert len(active_grants) == 1
    assert after["active_exclusivity_count"] == len(active_grants)


def test_the_surviving_engagement_keeps_its_active_grant(api):
    """PRD 2.9: "An athlete's `active_exclusivity_count` is the number of that
    athlete's exclusivity grants whose `status` is `ACTIVE`."
    PRD 3.9: "Exclusivity is released first. Every exclusivity grant of this
    engagement whose `status` is `PENDING` or `ACTIVE` is released, so the edge fires
    as `ACTIVE → RELEASED` or as `PENDING → RELEASED` depending on where the grant
    stood, and `released_at` is stamped with the logical clock in both cases."

    Design: Difficulty/compensating_invariant/terminate_releases_exclusivity_slot_count_returns_to_baseline
    """
    pair = setup_two_engagement_athlete()
    surviving = pair["deal_a"]
    terminated = pair["deal_b"]

    terminate_engagement(terminated["engagement_id"], reason_code="BRAND_WITHDRAWAL")

    released, _meta = validate_paginated(
        api.list_engagement_exclusivity_grants(terminated["engagement_id"], AGENT)
    )
    assert len(released) == 1
    assert released[0]["status"] == "RELEASED"

    kept, _meta = validate_paginated(
        api.list_engagement_exclusivity_grants(surviving["engagement_id"], AGENT)
    )
    assert len(kept) == 1
    assert kept[0]["status"] == "ACTIVE"

    active_grants, _meta = validate_paginated(
        api.list_athlete_exclusivity_grants(
            pair["athlete"]["id"], AGENT, params={"status": "ACTIVE"}
        )
    )
    assert len(active_grants) == 1
    assert active_grants[0]["engagement_id"] == surviving["engagement_id"]

    assert read_engagement(surviving["engagement_id"])["contract_status"] == "ACTIVE"


def test_terminating_a_terminated_engagement_is_refused(api):
    """PRD 3.9: "Compliance can pull an engagement down at any point before it
    completes. Termination is available while the engagement's `contract_status` is
    `PENDING_COUNTERSIGN` or `ACTIVE`; attempting it on an engagement already
    `COMPLETED` or `TERMINATED` is refused with `ERR_ENGAGEMENT_ALREADY_TERMINAL`."

    Design: Corner/state_machines/terminate_terminated_engagement_returns_already_terminal
    """
    deal = build_deal(stage="active", signed_by_reference="CS-C-0002")
    terminate_engagement(deal["engagement_id"], reason_code="MORALS_BREACH")

    response = api.terminate_engagement(
        deal["engagement_id"], terminate_payload("MORALS_BREACH"), ENFORCER
    )
    validate_error(response, ApiErrorId.ERR_ENGAGEMENT_ALREADY_TERMINAL.value, 409)

    athlete = validate_success(api.get_athlete(deal["athlete_id"], AGENT))
    assert athlete["active_exclusivity_count"] == 0, "the counter is not decremented twice"

    grants, _meta = validate_paginated(
        api.list_engagement_exclusivity_grants(deal["engagement_id"], AGENT)
    )
    assert len(grants) == 1
    assert grants[0]["status"] == "RELEASED"


def test_the_terminate_response_already_carries_the_whole_cascade(api):
    """PRD 2.2: "The `data` field contains the resource object or an array of resource
    objects. For 2xx responses with no data, it contains an empty object. Unless
    otherwise noted, operations that create or modify a resource will return the
    created or updated resource object in the data field."
    PRD 3.9: "Settlement is opened fourth. Because the engagement became
    `TERMINATED`, its `settlement_status` moves `UNBILLED → BILLABLE`, so whatever was
    accrued and approved before the termination can still be paid out."

    Design: Corner/consistency_model/terminate_response_body_shows_the_whole_cascade_immediately
    """
    deal = build_deal(stage="active", signed_by_reference="CS-C-0002")
    deliverable = schedule_deliverable(
        deal["engagement_id"], "SOCIAL_POST", due_date="2026-09-20",
        disclosure_required=False,
    )

    engagement = validate_success(
        api.terminate_engagement(
            deal["engagement_id"], terminate_payload("MORALS_BREACH"), ENFORCER
        ),
        200,
    )
    assert engagement["contract_status"] == "TERMINATED"
    assert engagement["settlement_status"] == "BILLABLE"

    athlete = validate_success(api.get_athlete(deal["athlete_id"], AGENT))
    assert athlete["active_exclusivity_count"] == 0
    assert athlete["exposure_risk_snapshot_score"] == 0

    voided = validate_success(api.get_deliverable(deliverable["id"], AGENT))
    assert voided["status"] == "VOIDED"

    grants, _meta = validate_paginated(
        api.list_engagement_exclusivity_grants(deal["engagement_id"], AGENT)
    )
    assert len(grants) == 1
    assert grants[0]["status"] == "RELEASED"
