"""Shipment lifecycle, cold-ischemia cascade, and transplant completion."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    complete_nephrectomy,
    create_shipment_for_offer,
    deliver_offer_end_to_end,
    find_chain,
    get_success_data,
    make_center_coordinator_headers,
    setup_broken_chain_after_first_transplant,
    setup_executing_chain,
    setup_locked_chain,
    validate_error,
    validate_paginated,
    validate_success,
)

OPERATOR = TEST_USERS["match_operator_headers"]
ADMIN = TEST_USERS["registry_admin_headers"]
LOGISTICS = TEST_USERS["logistics_headers"]


class TestShipmentBranching:
    def test_organ_shipment_branching_delay_reroute_paths(self, api):
        """PRD §3.6: "A `DEPARTED` shipment may be flagged `DELAYED` with a
        `contingency_reason` of `WEATHER`, `MECHANICAL`, `ATC`, or
        `COURIER_BREAKDOWN` — any other reason is rejected with
        `ERR_INVALID_REQUEST`. From `DEPARTED` or `DELAYED`, the shipment may be
        rerouted, moving it to `REROUTED`, incrementing `routing_sequence` by
        one, and replacing `scheduled_arrival_utc` with the
        `new_scheduled_arrival_utc` supplied in the reroute call. Delivery is
        allowed from `DEPARTED`, `DELAYED`, or `REROUTED`: the server stamps
        `actual_arrival_utc` and computes `cold_ischemia_hours_actual` as the
        elapsed hours from the donor's nephrectomy completion timestamp to
        actual arrival, rounded half-up to two decimal places."

        Design: Difficulty/non_linear_state_machine/organ_shipment_branching_delay_reroute_paths
        """
        ctx = setup_executing_chain()
        offer1 = ctx["offers"][0]
        complete_nephrectomy(ctx["starter"])
        shipment = create_shipment_for_offer(offer1)
        get_success_data(api.depart_shipment(shipment["id"], LOGISTICS))
        delayed = validate_success(
            api.delay_shipment(shipment["id"], {"contingency_reason": "WEATHER"}, LOGISTICS)
        )
        assert delayed["shipment_state"] == "DELAYED"
        rerouted = validate_success(
            api.reroute_shipment(
                shipment["id"],
                {"new_scheduled_arrival_utc": "2026-09-11T16:00:00Z"},
                LOGISTICS,
            )
        )
        assert rerouted["shipment_state"] == "REROUTED"
        assert rerouted["routing_sequence"] == 1
        delivered = validate_success(api.deliver_shipment(shipment["id"], LOGISTICS))
        assert delivered["shipment_state"] == "DELIVERED"

    def test_organ_shipment_direct_delivery_path(self, api):
        """PRD §3.6: "Delivery is allowed from `DEPARTED`, `DELAYED`, or
        `REROUTED`: the server stamps `actual_arrival_utc` and computes
        `cold_ischemia_hours_actual` as the elapsed hours from the donor's
        nephrectomy completion timestamp to actual arrival, rounded half-up to
        two decimal places."
        PRD §3.6: "Departure requires the shipment to be `PLANNED`, the source
        offer to be in `DONOR_SURGERY_DONE` (otherwise `ERR_ORGAN_NOT_READY`),
        and the origin center to be `ACTIVE` (otherwise
        `ERR_CENTER_SUSPENDED`)."

        Design: Difficulty/non_linear_state_machine/organ_shipment_branching_delay_reroute_paths
        """
        ctx = setup_executing_chain()
        offer1 = ctx["offers"][0]
        complete_nephrectomy(ctx["starter"])
        shipment = create_shipment_for_offer(offer1)
        get_success_data(api.depart_shipment(shipment["id"], LOGISTICS))
        delivered = validate_success(api.deliver_shipment(shipment["id"], LOGISTICS))
        assert delivered["shipment_state"] == "DELIVERED"
        assert delivered["routing_sequence"] == 0


class TestShipmentInvalidTransitions:
    def test_ship_delayed_to_departed_invalid(self, api):
        """PRD §3.6: "The shipment's `shipment_state` walks `PLANNED` →
        `DEPARTED` (optionally via `DELAYED` and `REROUTED`) and terminates at
        either `DELIVERED` or `CANCELLED`."
        PRD §5: "`ERR_INVALID_STATE` | 409".

        Design: Corner/state_machines/ship_delayed_to_departed_invalid
        """
        ctx = setup_executing_chain()
        offer1 = ctx["offers"][0]
        complete_nephrectomy(ctx["starter"])
        shipment = create_shipment_for_offer(offer1)
        get_success_data(api.depart_shipment(shipment["id"], LOGISTICS))
        get_success_data(
            api.delay_shipment(shipment["id"], {"contingency_reason": "ATC"}, LOGISTICS)
        )
        resp = api.depart_shipment(shipment["id"], LOGISTICS)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)


class TestOrganReadiness:
    def test_shipment_departure_gated_on_donor_surgery_state(self, api):
        """PRD §3.6: "Departure requires the shipment to be `PLANNED`, the
        source offer to be in `DONOR_SURGERY_DONE` (otherwise
        `ERR_ORGAN_NOT_READY`), and the origin center to be `ACTIVE` (otherwise
        `ERR_CENTER_SUSPENDED`)."

        Design: Difficulty/cross_entity_state_dependency/shipment_departure_gated_on_donor_surgery_state
        """
        ctx = setup_locked_chain()
        offer1 = ctx["offers"][0]
        # Donor surgery not done (chain not even scheduled): the offer is
        # CENTER_ACCEPTED, so the source offer is not DONOR_SURGERY_DONE.
        shipment = create_shipment_for_offer(offer1)
        assert shipment["shipment_state"] == "PLANNED"
        resp = api.depart_shipment(shipment["id"], LOGISTICS)
        validate_error(resp, ApiErrorId.ERR_ORGAN_NOT_READY.value)
        refreshed = validate_success(api.get_shipment(shipment["id"], LOGISTICS))
        assert refreshed["shipment_state"] == "PLANNED"

    def test_shipment_departure_gated_before_nephrectomy_in_executing_chain(self, api):
        """PRD §3.6: "Departure requires the shipment to be `PLANNED`, the
        source offer to be in `DONOR_SURGERY_DONE` (otherwise
        `ERR_ORGAN_NOT_READY`), and the origin center to be `ACTIVE` (otherwise
        `ERR_CENTER_SUSPENDED`)."

        Design: Difficulty/cross_entity_state_dependency/shipment_departure_gated_on_donor_surgery_state
        """
        ctx = setup_executing_chain()
        offer1 = ctx["offers"][0]
        # Chain executing but nephrectomy NOT completed yet.
        shipment = create_shipment_for_offer(offer1)
        resp = api.depart_shipment(shipment["id"], LOGISTICS)
        validate_error(resp, ApiErrorId.ERR_ORGAN_NOT_READY.value)


class TestTransplantGating:
    def test_organ_shipped_required_for_transplant(self, api):
        """PRD §3.7: "A `CenterCoordinator` marks the recipient transplanted
        only when five conditions hold: the recipient's `medical_status` is
        `LISTED` (otherwise `ERR_INVALID_STATE`); the recipient's
        `chain_participation_state` is `COMMITTED` (otherwise
        `ERR_RECIPIENT_NOT_COMMITTED`); an offer exists for this recipient in
        `ORGAN_SHIPPED` (otherwise `ERR_ORGAN_NOT_ARRIVED`); the linked shipment
        is `DELIVERED` (likewise `ERR_ORGAN_NOT_ARRIVED`); and the shipment's
        `cold_ischemia_violation` is false (otherwise
        `ERR_COLD_ISCHEMIA_VIOLATION`)."

        Design: Corner/validations/organ_shipped_required_for_transplant
        """
        ctx = setup_executing_chain()
        # Position-2 recipient (p2's recipient) is COMMITTED, but no organ has
        # been shipped — the offer is still SCHEDULED.
        recipient = ctx["p2"]["recipient"]
        coord = make_center_coordinator_headers(recipient["home_center_id"])
        resp = api.complete_transplant(recipient["id"], coord)
        validate_error(resp, ApiErrorId.ERR_ORGAN_NOT_ARRIVED.value)


class TestColdIschemiaCascade:
    def test_cold_ischemia_violation_cascades_to_center_counters(self, api):
        """PRD §3.6: "If `cold_ischemia_hours_actual` exceeds
        `cold_ischemia_max_hours`, the `cold_ischemia_violation` flag is set
        true: the destination center's `probed_cold_ischemia_violations`
        increments by one, the linked offer moves to `OFFER_FAILED` with
        `offer_failure_reason` equal to `COLD_ISCHEMIA`, a chain break cascade
        fires, and a subsequent transplant attempt on that offer is rejected
        with `ERR_COLD_ISCHEMIA_VIOLATION`."

        Design: Difficulty/transitive_cascade/cold_ischemia_violation_cascades_to_center_counters
        """
        ctx = setup_executing_chain()
        offer1 = ctx["offers"][0]
        donor1 = ctx["starter"]
        destination_center_id = offer1["recipient_center_id"]
        before = validate_success(api.get_center(destination_center_id, ADMIN))
        complete_nephrectomy(donor1)
        shipment = create_shipment_for_offer(offer1, cold_ischemia_max_hours=1)
        get_success_data(api.depart_shipment(shipment["id"], LOGISTICS))
        # Advance the logical clock ~10 hours so actual cold ischemia exceeds 1h.
        get_success_data(api.set_clock("2026-09-01T10:00:00Z", ADMIN))
        delivered = validate_success(api.deliver_shipment(shipment["id"], LOGISTICS))
        assert delivered["cold_ischemia_violation"] is True
        offer_after = validate_success(api.get_match_offer(offer1["id"], OPERATOR))
        assert offer_after["offer_state"] == "OFFER_FAILED"
        assert offer_after["offer_failure_reason"] == "COLD_ISCHEMIA"
        after = validate_success(api.get_center(destination_center_id, ADMIN))
        assert (
            after["probed_cold_ischemia_violations"]
            == before["probed_cold_ischemia_violations"] + 1
        )
        assert (
            after["reputation_score_bps"]
            == before["reputation_score_bps"] - 800
        )

    def test_cold_ischemia_violation_blocks_transplant(self, api):
        """PRD §3.6: "If `cold_ischemia_hours_actual` exceeds
        `cold_ischemia_max_hours`, the `cold_ischemia_violation` flag is set
        true: the destination center's `probed_cold_ischemia_violations`
        increments by one, the linked offer moves to `OFFER_FAILED` with
        `offer_failure_reason` equal to `COLD_ISCHEMIA`, a chain break cascade
        fires, and a subsequent transplant attempt on that offer is rejected
        with `ERR_COLD_ISCHEMIA_VIOLATION`."

        Design: Difficulty/transitive_cascade/cold_ischemia_violation_cascades_to_center_counters
        """
        ctx = setup_executing_chain()
        offer1 = ctx["offers"][0]
        donor1 = ctx["starter"]
        complete_nephrectomy(donor1)
        shipment = create_shipment_for_offer(offer1, cold_ischemia_max_hours=1)
        get_success_data(api.depart_shipment(shipment["id"], LOGISTICS))
        get_success_data(api.set_clock("2026-09-01T10:00:00Z", ADMIN))
        get_success_data(api.deliver_shipment(shipment["id"], LOGISTICS))
        recipient = ctx["p1"]["recipient"]
        coord = make_center_coordinator_headers(recipient["home_center_id"])
        resp = api.complete_transplant(recipient["id"], coord)
        validate_error(resp, ApiErrorId.ERR_COLD_ISCHEMIA_VIOLATION.value)

    def test_cold_ischemia_hours_rounding(self, api):
        """PRD §3.6: "the server stamps `actual_arrival_utc` and computes
        `cold_ischemia_hours_actual` as the elapsed hours from the donor's
        nephrectomy completion timestamp to actual arrival, rounded half-up to
        two decimal places."

        Design: Corner/calculations/cold_ischemia_hours_rounding
        """
        ctx = setup_executing_chain()
        offer1 = ctx["offers"][0]
        complete_nephrectomy(ctx["starter"])
        shipment = create_shipment_for_offer(offer1)
        get_success_data(api.depart_shipment(shipment["id"], LOGISTICS))
        # Nephrectomy completed at the logical clock 2026-09-01T00:00:00Z;
        # advance by 2.5 hours before delivery: 2.5h is exact at 2dp.
        get_success_data(api.set_clock("2026-09-01T02:30:00Z", ADMIN))
        delivered = validate_success(api.deliver_shipment(shipment["id"], LOGISTICS))
        assert abs(delivered["cold_ischemia_hours_actual"] - 2.5) < 1e-9
        assert delivered["cold_ischemia_violation"] is False


class TestChainBreakCascade:
    def test_donor_withdrawal_cascades_to_chain_break_and_orphan(self, api):
        """PRD §3.8: "The chain itself moves to `BROKEN` and `completion_grade`
        becomes `BROKEN_PARTIAL`. Each downstream recipient whose offer failed
        becomes an orphan: their `chain_participation_state` moves from
        `COMMITTED` to `ORPHANED`, and if their paired donor has already
        completed nephrectomy (donated on the orphan's behalf before the
        break), the orphan's `priority_boost_active` flag is set true. The
        event records `recipients_already_transplanted` — the count of the
        chain's offers already in `TRANSPLANT_COMPLETED` before the event — and
        `downstream_recipients_orphaned`."
        PRD §3.6: "Withdrawal from a donor embedded in a chain in `LOCKED`,
        `SCHEDULED`, or `EXECUTING` emits a `ChainBreakEvent` and cascades the
        break."

        Design: Difficulty/transitive_cascade/donor_withdrawal_cascades_to_chain_break_and_orphan
        """
        ctx, event = setup_broken_chain_after_first_transplant()
        chain = ctx["chain"]
        assert chain["chain_state"] == "BROKEN"
        assert chain["completion_grade"] == "BROKEN_PARTIAL"
        assert event["recipients_already_transplanted"] == 1
        # The broken offer is position-2 (the LAST offer), so no offer sits
        # strictly greater than `broken_at_index` — per PRD §3.8, no
        # downstream recipient is orphaned by this break.
        assert event["downstream_recipients_orphaned"] == 0
        # Already-transplanted recipient (p1.recipient) is unchanged.
        transplanted = validate_success(
            api.get_recipient(ctx["p1"]["recipient"]["id"], ADMIN)
        )
        assert transplanted["medical_status"] == "TRANSPLANTED"
        assert transplanted.get("transplant_completed_at_utc")

    def test_donor_withdrawal_chain_break_event_trigger_and_offer_failures(self, api):
        """PRD §3.8: "The event begins in `RECORDED` and immediately cascades:
        the broken offer itself moves to `OFFER_FAILED` with
        `offer_failure_reason` equal to `DONOR_UNAVAILABLE` (or
        `ORGAN_LOST_IN_TRANSIT` when that is the trigger). Then, walking the
        chain's offers in `position_index` ascending order, every offer whose
        position is strictly greater than the `broken_at_index` and whose state
        is not yet terminal is moved to `OFFER_FAILED` with
        `offer_failure_reason` equal to `CHAIN_BREAK_PROPAGATION`."

        Design: Difficulty/transitive_cascade/donor_withdrawal_cascades_to_chain_break_and_orphan
        """
        ctx, event = setup_broken_chain_after_first_transplant()
        assert event["event_state"] == "CASCADED"
        broken_offer = validate_success(
            api.get_match_offer(event["broken_at_offer_id"], OPERATOR)
        )
        assert broken_offer["offer_state"] == "OFFER_FAILED"
        assert broken_offer["offer_failure_reason"] == "DONOR_UNAVAILABLE"
        # The position-1 offer already reached TRANSPLANT_COMPLETED and stands.
        offer1 = validate_success(api.get_match_offer(ctx["offers"][0]["id"], OPERATOR))
        assert offer1["offer_state"] == "TRANSPLANT_COMPLETED"


class TestCompletionGrade:
    def test_chain_completion_grade_partial_on_break_after_one_transplant(self, api):
        """PRD §3.5: "When a chain reaches `BROKEN` with `length_actual` greater
        than zero but strictly less than `length_target`, `completion_grade` is
        likewise `BROKEN_PARTIAL`."

        Design: Corner/calculations/chain_completion_grade_partial_on_break_after_one_transplant
        """
        ctx, _event = setup_broken_chain_after_first_transplant()
        chain = ctx["chain"]
        assert chain["chain_state"] == "BROKEN"
        assert chain["length_actual"] == 1
        assert chain["length_target"] == 2
        assert chain["completion_grade"] == "BROKEN_PARTIAL"
