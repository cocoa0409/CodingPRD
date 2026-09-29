"""Multi-hop cascades, validation precedence between competing gates, and the
arithmetic that lives exactly on a stated boundary."""
from prd_bench_local_runner.testing import (validate_error, validate_paginated,
                                            validate_success)

from test_helpers import assertions, constants, factories, fixtures
from test_helpers.test_users import (DISTRIBUTION_PLANNER, PRODUCTION_OPERATOR,
                                     QA_RELEASER, QA_RELEASER_2_USER_ID,
                                     QC_ANALYST, REGULATORY_AFFAIRS)

# A lot large enough that the customer order can be met in full and still leave
# units unallocated, so every ledger bucket carries a distinguishable figure.
_LOT_PLANNED_UNITS = 300
_ORDER_REQUESTED_UNITS = 200
_LOT_UNALLOCATED_UNITS = _LOT_PLANNED_UNITS - _ORDER_REQUESTED_UNITS
_MATERIAL_QUANTITY_USED = 250.00
# The raw material lot is booked in with this much, so dispensing leaves
# 1000.00 - 250.00 = 750.00 available while it stays qualified.
_MATERIAL_RECEIVED_UNITS = constants.TEST_DEFAULTS["RECEIVED_QUANTITY_UNITS"]
_MATERIAL_AVAILABLE_AFTER_DISPENSE = 750.00


def _released_lot_with_reserved_order(api):
    """A released finished lot built from one critical raw material, with a
    customer order fully allocated against it and the reservation still
    ``RESERVED``."""
    setup = fixtures.manufacturing_setup(api, material_types=("ANTIBODY",),
                                         critical_types=("ANTIBODY",))
    return fixtures.allocated_order(
        api, setup,
        lot_overrides={"planned_units": _LOT_PLANNED_UNITS},
        run_overrides={"planned_fill_units": _LOT_PLANNED_UNITS},
        quantity_used=_MATERIAL_QUANTITY_USED,
        requested_units=_ORDER_REQUESTED_UNITS,
    )


def _shipped_lot_with_shipped_reservation(api):
    """The same shape carried one hop further: the single reservation has been
    shipped, which is the only state a cold-chain event may be recorded from."""
    setup = fixtures.manufacturing_setup(api, material_types=("ANTIBODY",),
                                         critical_types=("ANTIBODY",))
    return fixtures.shipped_allocation(
        api, setup,
        lot_overrides={"planned_units": _LOT_PLANNED_UNITS},
        run_overrides={"planned_fill_units": _LOT_PLANNED_UNITS},
        quantity_used=_MATERIAL_QUANTITY_USED,
        requested_units=_ORDER_REQUESTED_UNITS,
    )


class TestRecallCascadeReachesAllocationsOrdersAndRawMaterial:

    def test_removal_field_action_drives_every_recall_hop(self, api):
        """PRD §3.8: "Whichever of the two admitted starting states applies, the
        effect is identical: `field_action`, `field_action_decided_by_user_id`
        and `field_action_decided_at` are stored, `status` becomes
        `FIELD_ACTION_DECIDED`, `version` increases by 1, and any result already
        produced by the reporting branch is preserved intact."
        PRD §3.8: "Hop 2: the implicated finished lot, which must be in
        `disposition_status` `RELEASED`, moves to the terminal `RECALLED` state
        and its `distribution_status` becomes `BLOCKED`; its `version` increases
        by 1."
        PRD §3.8: "Hop 3: because the lot became `RECALLED`, every reservation
        drawn from that lot whose `status` is `RESERVED` or `SHIPPED` becomes
        `QUARANTINED` with its `quarantine_reason` set to indicate a recall, and
        the lot's `allocated_units`, `shipped_units` and `quarantined_units` are
        recomputed so the finished-goods ledger of §2.8 still balances."
        PRD §3.8: "Hop 3b, which fires **only** under a `REMOVAL`: every raw
        material lot referenced by a `CONSUMED` dispensing row of the recalled
        lot, whose specification has `is_critical` true and whose
        `qualification_status` is currently `QUALIFIED`, moves to `QUARANTINED`;
        a `CORRECTION` leaves raw material alone."
        PRD §3.8: "Two further consequences ride along with the recall: every
        stability study on the recalled lot whose `status` is `APPROVED` or
        `IN_PROGRESS` is aborted as described in §3.6, and under a `REMOVAL`
        where the recalled lot is the **only** `RELEASED` lot of its product,
        that product's `clearance_status` moves from `CLEARED` to `WITHDRAWN`,
        blocking all further release and allocation on it."

        Design: Difficulty/transitive_cascade/complaint_removal_recall_cascades_through_lot_allocation_order_and_material
        """
        bundle = _released_lot_with_reserved_order(api)
        lot_id = bundle["lot"]["id"]
        product_id = bundle["product"]["id"]
        order_id = bundle["order"]["id"]
        allocation_id = bundle["allocations"][0]["id"]
        material_lot_id = bundle["materials"][0]["lot"]["id"]
        study = fixtures.approved_stability_study(api, product_id, lot_id)
        complaint = fixtures.triaged_complaint(api, lot_id, "HIGH", True)

        decided = fixtures.decide_field_action(api, complaint["id"], "REMOVAL")

        assert decided["status"] == "FIELD_ACTION_DECIDED"
        assert decided["field_action"] == "REMOVAL"
        assert decided["field_action_decided_by_user_id"] == QA_RELEASER_2_USER_ID
        assertions.assert_same_instant(decided["field_action_decided_at"],
                                       constants.DEFAULT_CLOCK_UTC,
                                       "field_action_decided_at")
        assert decided["version"] == complaint["version"] + 1

        # Hop 2 on the implicated finished lot.
        lot = validate_success(api.get_reagent_lot(lot_id, QA_RELEASER))
        assert lot["disposition_status"] == "RECALLED"
        assert lot["distribution_status"] == "BLOCKED"
        assert lot["version"] > bundle["lot"]["version"]

        # Hop 3 on the reservation drawn from that lot.
        allocation = validate_success(
            api.get_allocation(allocation_id, DISTRIBUTION_PLANNER))
        assert allocation["status"] == "QUARANTINED"
        assert allocation["quarantine_reason"] is not None
        assert allocation["allocated_units"] == _ORDER_REQUESTED_UNITS

        # Hop 3 recomputes the four finished-goods buckets: the 200 reserved
        # units become quarantined units and the 100 never-allocated units stay
        # available.
        assert lot["filled_units"] == _LOT_PLANNED_UNITS
        assert lot["allocated_units"] == 0
        assert lot["shipped_units"] == 0
        assert lot["quarantined_units"] == _ORDER_REQUESTED_UNITS
        assert lot["available_units"] == _LOT_UNALLOCATED_UNITS
        assertions.assert_reagent_lot_unit_conservation(lot)

        # Hop 4 on the parent customer order.
        order = validate_success(
            api.get_distribution_order(order_id, DISTRIBUTION_PLANNER))
        assert order["status"] == "PARTIALLY_ALLOCATED"
        assert order["allocated_units"] == 0
        assert order["shortfall_units"] == _ORDER_REQUESTED_UNITS
        assertions.assert_order_shortfall_consistent(order)

        # Hop 3b on the critical raw material that the recalled lot consumed.
        material_lot = validate_success(
            api.get_material_lot(material_lot_id, QA_RELEASER))
        assert material_lot["qualification_status"] == "QUARANTINED"
        assert material_lot["quarantine_reason"] is not None
        assert material_lot["available_quantity_units"] == 0
        assert material_lot["consumed_quantity_units"] == _MATERIAL_QUANTITY_USED

        # The dispensing row itself is untouched by the quarantine.
        components, _ = validate_paginated(
            api.list_reagent_lot_components(lot_id, PRODUCTION_OPERATOR))
        assert len(components) == 1
        assert components[0]["status"] == "CONSUMED"
        assert components[0]["quantity_used"] == _MATERIAL_QUANTITY_USED

        # The two consequences that ride along with the recall.
        aborted = validate_success(
            api.get_stability_study(study["id"], REGULATORY_AFFAIRS))
        assert aborted["status"] == "ABORTED"
        assert aborted["version"] > study["version"]
        product = validate_success(
            api.get_product_specification(product_id, REGULATORY_AFFAIRS))
        assert product["clearance_status"] == "WITHDRAWN"

    def test_removal_recall_leaves_both_conservation_ledgers_balanced(self, api):
        """PRD §2.8: "The invariant is that `filled_units` always equals
        `available_units` plus `allocated_units` plus `shipped_units` plus
        `quarantined_units`."
        PRD §2.8: "The invariant is that `received_quantity_units` always equals
        `available_quantity_units` plus `consumed_quantity_units`."
        PRD §3.1: "In both cases the cascade records a free-text
        `quarantine_reason`, forces `available_quantity_units` to 0, and
        increases the lot's `version` by 1."
        PRD §3.8: "Hop 4: because those reservations left `RESERVED` and
        `SHIPPED`, each parent customer order recomputes its own
        `allocated_units` and `shortfall_units`, and where the recomputed
        `allocated_units` has fallen below `requested_units` and the order's
        `status` was `ALLOCATED`, that order drops to `PARTIALLY_ALLOCATED`."

        Design: Difficulty/transitive_cascade/complaint_removal_recall_cascades_through_lot_allocation_order_and_material
        """
        bundle = _released_lot_with_reserved_order(api)
        lot_id = bundle["lot"]["id"]
        material_lot_id = bundle["materials"][0]["lot"]["id"]
        before_material = bundle["materials"][0]["lot"]

        # The ledgers balance before the cascade too.
        assertions.assert_reagent_lot_unit_conservation(bundle["lot"])
        assert before_material["received_quantity_units"] == _MATERIAL_RECEIVED_UNITS
        assert before_material["consumed_quantity_units"] == 0

        complaint = fixtures.triaged_complaint(api, lot_id, "HIGH", True)
        fixtures.decide_field_action(api, complaint["id"], "REMOVAL")

        lot = validate_success(api.get_reagent_lot(lot_id, QA_RELEASER))
        assertions.assert_reagent_lot_unit_conservation(lot)
        assert (lot["available_units"] + lot["allocated_units"]
                + lot["shipped_units"] + lot["quarantined_units"]
                == _LOT_PLANNED_UNITS)

        material_lot = validate_success(
            api.get_material_lot(material_lot_id, QA_RELEASER))
        assertions.assert_material_quantity_conservation(material_lot)
        assert material_lot["version"] > before_material["version"]

        order = validate_success(
            api.get_distribution_order(bundle["order"]["id"],
                                       DISTRIBUTION_PLANNER))
        assertions.assert_order_shortfall_consistent(order)
        assert order["allocated_units"] == 0
        assert order["status"] == "PARTIALLY_ALLOCATED"

    def test_correction_recall_spares_the_critical_raw_material(self, api):
        """PRD §3.8: "Hop 3b, which fires **only** under a `REMOVAL`: every raw
        material lot referenced by a `CONSUMED` dispensing row of the recalled
        lot, whose specification has `is_critical` true and whose
        `qualification_status` is currently `QUALIFIED`, moves to `QUARANTINED`;
        a `CORRECTION` leaves raw material alone."
        PRD §3.8: "Hop 2: the implicated finished lot, which must be in
        `disposition_status` `RELEASED`, moves to the terminal `RECALLED` state
        and its `distribution_status` becomes `BLOCKED`; its `version` increases
        by 1."

        Design: Difficulty/transitive_cascade/complaint_removal_recall_cascades_through_lot_allocation_order_and_material
        """
        bundle = _released_lot_with_reserved_order(api)
        lot_id = bundle["lot"]["id"]
        material_lot_id = bundle["materials"][0]["lot"]["id"]
        assert bundle["materials"][0]["spec"]["is_critical"] is True
        complaint = fixtures.triaged_complaint(api, lot_id, "HIGH", True)

        decided = fixtures.decide_field_action(api, complaint["id"], "CORRECTION")
        assert decided["field_action"] == "CORRECTION"
        assert decided["status"] == "FIELD_ACTION_DECIDED"

        # The finished-goods hops still run in full under a CORRECTION.
        lot = validate_success(api.get_reagent_lot(lot_id, QA_RELEASER))
        assert lot["disposition_status"] == "RECALLED"
        assert lot["distribution_status"] == "BLOCKED"
        assert lot["quarantined_units"] == _ORDER_REQUESTED_UNITS
        assert lot["allocated_units"] == 0
        assertions.assert_reagent_lot_unit_conservation(lot)

        allocation = validate_success(
            api.get_allocation(bundle["allocations"][0]["id"],
                               DISTRIBUTION_PLANNER))
        assert allocation["status"] == "QUARANTINED"

        order = validate_success(
            api.get_distribution_order(bundle["order"]["id"],
                                       DISTRIBUTION_PLANNER))
        assert order["status"] == "PARTIALLY_ALLOCATED"
        assert order["allocated_units"] == 0

        # The raw material hop is the one that does not fire.
        material_lot = validate_success(
            api.get_material_lot(material_lot_id, QA_RELEASER))
        assert material_lot["qualification_status"] == "QUALIFIED"
        assert material_lot["quarantine_reason"] is None
        assert (material_lot["available_quantity_units"]
                == _MATERIAL_AVAILABLE_AFTER_DISPENSE)
        assert material_lot["consumed_quantity_units"] == _MATERIAL_QUANTITY_USED
        assertions.assert_material_quantity_conservation(material_lot)


class TestColdChainExcursionCascadesUpToTheOrderLedger:

    def test_peak_above_the_temperature_limit_quarantines_and_reaches_the_order(
            self, api):
        """PRD §3.9: "It is `EXCURSION_REJECTED` when `max_excursion_temp_c` is
        strictly greater than 15.0 degrees Celsius **or**
        `cumulative_excursion_minutes` is strictly greater than 240 minutes —
        four hours of accumulated excursion is still acceptable, and so is a peak
        of exactly 15.0 degrees."
        PRD §3.9: "When the verdict becomes `EXCURSION_REJECTED`, the reservation
        moves from `SHIPPED` to the terminal `QUARANTINED` state with its
        `quarantine_reason` set to indicate a cold-chain excursion, the lot's
        `shipped_units` decreases and its `quarantined_units` increases by that
        reservation's `allocated_units`, and the parent order recomputes its
        `allocated_units` and `shortfall_units`."
        PRD §2.8: "The invariant is that `filled_units` always equals
        `available_units` plus `allocated_units` plus `shipped_units` plus
        `quarantined_units`."
        PRD §3.9: "Once every reservation of an order carries `status`
        `DELIVERED`, that order advances from `SHIPPED` to the terminal `CLOSED`
        state as a system cascade."

        Design: Difficulty/transitive_cascade/cold_chain_excursion_cascades_from_allocation_up_to_order_ledger
        """
        bundle = _shipped_lot_with_shipped_reservation(api)
        lot_id = bundle["lot"]["id"]
        order_id = bundle["order"]["id"]
        allocation_id = bundle["allocation"]["id"]
        assert bundle["allocation"]["status"] == "SHIPPED"
        assert bundle["lot"]["shipped_units"] == _ORDER_REQUESTED_UNITS
        assert bundle["lot"]["quarantined_units"] == 0

        # 20.0 degrees is strictly greater than the fixed 15.0 limit, so the
        # verdict is rejected on the temperature half alone.
        returned = fixtures.record_cold_chain_event(api, allocation_id, 60, 20.0)

        assert returned["cumulative_excursion_minutes"] == 60
        assert returned["max_excursion_temp_c"] == 20.0
        assert returned["cold_chain_status"] == "EXCURSION_REJECTED"
        assert returned["status"] == "QUARANTINED"
        assert returned["quarantine_reason"] is not None
        assert returned["version"] > bundle["allocation"]["version"]

        allocation = validate_success(
            api.get_allocation(allocation_id, DISTRIBUTION_PLANNER))
        assert allocation["status"] == "QUARANTINED"
        assert allocation["cold_chain_status"] == "EXCURSION_REJECTED"
        # The reservation is not deleted: it keeps the units it drew.
        assert allocation["allocated_units"] == _ORDER_REQUESTED_UNITS

        lot = validate_success(api.get_reagent_lot(lot_id, QA_RELEASER))
        assert lot["shipped_units"] == 0
        assert lot["quarantined_units"] == _ORDER_REQUESTED_UNITS
        assert lot["allocated_units"] == 0
        assert lot["available_units"] == _LOT_UNALLOCATED_UNITS
        assert lot["filled_units"] == _LOT_PLANNED_UNITS
        assertions.assert_reagent_lot_unit_conservation(lot)

        # The order's own figures follow from the reservation leaving SHIPPED.
        order = validate_success(
            api.get_distribution_order(order_id, DISTRIBUTION_PLANNER))
        assert order["allocated_units"] == 0
        assert order["shortfall_units"] == _ORDER_REQUESTED_UNITS
        assertions.assert_order_shortfall_consistent(order)
        # The reservation left SHIPPED for QUARANTINED rather than DELIVERED, so
        # the only declared move out of the order's SHIPPED state is not reached.
        assert order["status"] == "SHIPPED"

    def test_exactly_the_two_limits_stays_acceptable_and_moves_no_units(self, api):
        """PRD §3.9: "It is `EXCURSION_REJECTED` when `max_excursion_temp_c` is
        strictly greater than 15.0 degrees Celsius **or**
        `cumulative_excursion_minutes` is strictly greater than 240 minutes —
        four hours of accumulated excursion is still acceptable, and so is a peak
        of exactly 15.0 degrees."
        PRD §3.9: "Otherwise it is `EXCURSION_ACCEPTABLE` when
        `cumulative_excursion_minutes` is greater than 0, and `INTACT` when it is
        0."

        Design: Difficulty/transitive_cascade/cold_chain_excursion_cascades_from_allocation_up_to_order_ledger
        """
        bundle = _shipped_lot_with_shipped_reservation(api)
        lot_id = bundle["lot"]["id"]
        allocation_id = bundle["allocation"]["id"]

        # Both figures land exactly on their limits, and both comparisons are
        # strictly greater-than, so neither half of the rejection test fires.
        returned = fixtures.record_cold_chain_event(
            api, allocation_id, constants.COLD_CHAIN_MAX_CUMULATIVE_MINUTES,
            constants.COLD_CHAIN_MAX_TEMP_C)

        assert returned["cumulative_excursion_minutes"] == 240
        assert returned["max_excursion_temp_c"] == 15.0
        assert returned["cold_chain_status"] == "EXCURSION_ACCEPTABLE"
        assert returned["status"] == "SHIPPED"
        assert returned["quarantine_reason"] is None

        allocation = validate_success(
            api.get_allocation(allocation_id, DISTRIBUTION_PLANNER))
        assert allocation["status"] == "SHIPPED"
        assert allocation["cold_chain_status"] == "EXCURSION_ACCEPTABLE"

        # No verdict change means no unit moves anywhere up the chain.
        lot = validate_success(api.get_reagent_lot(lot_id, QA_RELEASER))
        assert lot["shipped_units"] == _ORDER_REQUESTED_UNITS
        assert lot["quarantined_units"] == 0
        assert lot["available_units"] == _LOT_UNALLOCATED_UNITS
        assertions.assert_reagent_lot_unit_conservation(lot)

        order = validate_success(
            api.get_distribution_order(bundle["order"]["id"],
                                       DISTRIBUTION_PLANNER))
        assert order["allocated_units"] == _ORDER_REQUESTED_UNITS
        assert order["shortfall_units"] == 0
        assertions.assert_order_shortfall_consistent(order)

    def test_accumulated_minutes_cross_the_limit_only_on_the_second_event(
            self, api):
        """PRD §3.9: "Each event re-derives the cumulative picture:
        `cumulative_excursion_minutes` becomes the sum of `excursion_minutes`
        over every cold-chain event ever recorded against this reservation, and
        `max_excursion_temp_c` becomes the largest `max_temp_c` across those
        events, staying null while no event exists."
        PRD §3.9: "When the verdict becomes `EXCURSION_REJECTED`, the reservation
        moves from `SHIPPED` to the terminal `QUARANTINED` state with its
        `quarantine_reason` set to indicate a cold-chain excursion, the lot's
        `shipped_units` decreases and its `quarantined_units` increases by that
        reservation's `allocated_units`, and the parent order recomputes its
        `allocated_units` and `shortfall_units`."

        Design: Difficulty/transitive_cascade/cold_chain_excursion_cascades_from_allocation_up_to_order_ledger
        """
        bundle = _shipped_lot_with_shipped_reservation(api)
        lot_id = bundle["lot"]["id"]
        allocation_id = bundle["allocation"]["id"]

        # 200 minutes at 10.0 degrees: under both limits.
        first = fixtures.record_cold_chain_event(api, allocation_id, 200, 10.0)
        assert first["cumulative_excursion_minutes"] == 200
        assert first["max_excursion_temp_c"] == 10.0
        assert first["cold_chain_status"] == "EXCURSION_ACCEPTABLE"
        assert first["status"] == "SHIPPED"

        lot_after_first = validate_success(
            api.get_reagent_lot(lot_id, QA_RELEASER))
        assert lot_after_first["shipped_units"] == _ORDER_REQUESTED_UNITS
        assert lot_after_first["quarantined_units"] == 0

        # 41 more minutes takes the accumulated total to 241, one minute past
        # the 240-minute limit, while the peak stays under 15.0.
        second = fixtures.record_cold_chain_event(api, allocation_id, 41, 12.0)
        assert second["cumulative_excursion_minutes"] == 241
        assert second["max_excursion_temp_c"] == 12.0
        assert second["cold_chain_status"] == "EXCURSION_REJECTED"
        assert second["status"] == "QUARANTINED"
        assert second["quarantine_reason"] is not None

        allocation = validate_success(
            api.get_allocation(allocation_id, DISTRIBUTION_PLANNER))
        assert allocation["cumulative_excursion_minutes"] == 241
        assert allocation["status"] == "QUARANTINED"

        lot = validate_success(api.get_reagent_lot(lot_id, QA_RELEASER))
        assert lot["shipped_units"] == 0
        assert lot["quarantined_units"] == _ORDER_REQUESTED_UNITS
        assert lot["available_units"] == _LOT_UNALLOCATED_UNITS
        assertions.assert_reagent_lot_unit_conservation(lot)

        order = validate_success(
            api.get_distribution_order(bundle["order"]["id"],
                                       DISTRIBUTION_PLANNER))
        assert order["allocated_units"] == 0
        assert order["shortfall_units"] == _ORDER_REQUESTED_UNITS
        assertions.assert_order_shortfall_consistent(order)


# Twice the 10 colony-forming-unit action limit of the viable air channel, which
# is what makes a single sample a MAJOR excursion.
_MAJOR_VIABLE_AIR_VALUE = 20.0


def _filled_lot_carrying_a_disqualified_run(api):
    """A finished lot at `FILLED` whose second, still scheduled, run has been
    disqualified by one major viable-air excursion."""
    bundle = fixtures.filled_reagent_lot(
        api,
        product_overrides={"release_test_codes": ["ACTIVITY"]},
        lot_overrides={"planned_units": _LOT_PLANNED_UNITS},
        run_overrides={"planned_fill_units": _LOT_PLANNED_UNITS},
    )
    second = fixtures.schedule_fill_run(
        api, bundle["lot"]["id"],
        scheduled_start=constants.clock_plus(days=3),
        scheduled_end=constants.clock_plus(days=3, hours=4),
        planned_fill_units=100)
    fixtures.record_monitoring_sample(
        api, second["id"], "VIABLE_AIR", _MAJOR_VIABLE_AIR_VALUE,
        sampled_at=constants.clock_plus(days=3, hours=1))
    bundle["second_run"] = validate_success(
        api.get_fill_run(second["id"], PRODUCTION_OPERATOR))
    bundle["lot"] = validate_success(
        api.get_reagent_lot(bundle["lot"]["id"], QA_RELEASER))
    return bundle


class TestStateGateOutranksEnvironmentalConformance:

    def test_wrong_state_is_reported_before_the_disqualified_run(self, api):
        """PRD §2.6: "When a single request violates several rules, exactly one
        error is returned: the one belonging to the lowest-numbered rung of the
        ladder below."
        PRD §2.6: "**Rung 60 — state precondition (every action endpoint).** The
        target resource is in a state from which the requested transition
        exists."
        PRD §2.6: "**Rung 80 — environmental conformance, on `POST
        /reagent-lots/{id}/disposition` when the decision is `RELEASE`.**
        `ERR_ENVIRONMENTAL_NONCONFORMANCE` (409)."
        PRD §3.5: "The first release measurement on a `FILLED` lot advances its
        `disposition_status` from `FILLED` to `UNDER_RELEASE_TEST`; each
        subsequent release measurement is a self-loop on `UNDER_RELEASE_TEST`."

        Design: Difficulty/priority_pair_validation_conflict/state_precondition_priority_60_beats_environmental_nonconformance_priority_80
        """
        bundle = _filled_lot_carrying_a_disqualified_run(api)
        lot_id = bundle["lot"]["id"]
        # Both rungs are violated at once: the lot has not reached
        # UNDER_RELEASE_TEST and one of its runs is DISQUALIFIED.
        assert bundle["lot"]["disposition_status"] == "FILLED"
        assert bundle["second_run"]["environmental_state"] == "DISQUALIFIED"

        validate_error(
            api.disposition_reagent_lot(
                lot_id, factories.reagent_lot_disposition_payload("RELEASE"),
                QA_RELEASER),
            "ERR_REAGENT_LOT_STATE_INVALID")

        # Removing only the state violation lets the lower rung surface, from an
        # otherwise identical request.
        fixtures.record_release_measurement(api, lot_id, "ACTIVITY")
        under_test = validate_success(api.get_reagent_lot(lot_id, QA_RELEASER))
        assert under_test["disposition_status"] == "UNDER_RELEASE_TEST"

        validate_error(
            api.disposition_reagent_lot(
                lot_id, factories.reagent_lot_disposition_payload("RELEASE"),
                QA_RELEASER),
            "ERR_ENVIRONMENTAL_NONCONFORMANCE")

    def test_neither_refusal_moves_the_lot_or_the_disqualified_run(self, api):
        """PRD §2.6: "When a single request violates several rules, exactly one
        error is returned: the one belonging to the lowest-numbered rung of the
        ladder below."
        PRD §3.4: "From those counts comes `environmental_state`: `DISQUALIFIED`
        when `major_excursion_count` is at least 1 or `minor_excursion_count` is
        at least 3, otherwise `EXCURSION` when `minor_excursion_count` is at
        least 1, and otherwise `CONFORMING`."
        PRD §3.5: "Both decisions require the lot's `disposition_status` to be
        `UNDER_RELEASE_TEST` and both are bound by the duty separation of §2.9,
        which is answered before the state check."

        Design: Difficulty/priority_pair_validation_conflict/state_precondition_priority_60_beats_environmental_nonconformance_priority_80
        """
        bundle = _filled_lot_carrying_a_disqualified_run(api)
        lot_id = bundle["lot"]["id"]
        second_run_id = bundle["second_run"]["id"]
        version_at_filled = bundle["lot"]["version"]

        validate_error(
            api.disposition_reagent_lot(
                lot_id, factories.reagent_lot_disposition_payload("RELEASE"),
                QA_RELEASER),
            "ERR_REAGENT_LOT_STATE_INVALID")

        still_filled = validate_success(api.get_reagent_lot(lot_id, QA_RELEASER))
        assert still_filled["disposition_status"] == "FILLED"
        assert still_filled["distribution_status"] == "WITHHELD"
        assert still_filled["released_by_user_id"] is None
        assert still_filled["released_at"] is None
        assert still_filled["version"] == version_at_filled

        fixtures.record_release_measurement(api, lot_id, "ACTIVITY")
        validate_error(
            api.disposition_reagent_lot(
                lot_id, factories.reagent_lot_disposition_payload("RELEASE"),
                QA_RELEASER),
            "ERR_ENVIRONMENTAL_NONCONFORMANCE")

        lot = validate_success(api.get_reagent_lot(lot_id, QA_RELEASER))
        assert lot["disposition_status"] == "UNDER_RELEASE_TEST"
        assert lot["distribution_status"] == "WITHHELD"
        assert lot["released_by_user_id"] is None
        # One major excursion on the lot's second run, counted on the lot too.
        assert lot["em_excursion_count"] == 1

        run = validate_success(api.get_fill_run(second_run_id,
                                                PRODUCTION_OPERATOR))
        assert run["status"] == "SCHEDULED"
        assert run["environmental_state"] == "DISQUALIFIED"
        assert run["major_excursion_count"] == 1
        assert run["minor_excursion_count"] == 0


class TestProductClearanceOutranksAllocationCoverage:

    def test_uncleared_product_is_reported_before_the_shortfall(self, api):
        """PRD §2.6: "When a single request violates several rules, exactly one
        error is returned: the one belonging to the lowest-numbered rung of the
        ladder below."
        PRD §2.6: "**Rung 130 — product clearance, on `POST
        /reagent-lots/{id}/disposition` when the decision is `RELEASE` and on
        `POST /distribution-orders/{id}/allocate`.** `ERR_PRODUCT_NOT_CLEARED`
        (409)."
        PRD §2.6: "**Rung 140 — allocation coverage, on `POST
        /distribution-orders/{id}/allocate`.** `ERR_ALLOCATION_SHORTFALL`
        (409)."
        PRD §3.9: "Two further gates precede the waterfall: the order's `ship_by`
        must not be earlier than the logical clock, failing which the answer is
        `ERR_SHIP_BY_PASSED`, and the product's `clearance_status` must be
        `CLEARED`, failing which the answer is `ERR_PRODUCT_NOT_CLEARED`."
        PRD §3.2: "On success `clearance_status` becomes `CLEARED`,
        `submission_ref` and `cleared_at` are stored, and `version` increases by
        1."

        Design: Difficulty/priority_pair_validation_conflict/product_not_cleared_priority_130_beats_allocation_shortfall_priority_140
        """
        product = fixtures.create_product_specification(api)
        fixtures.design_history_file(api, product["id"])
        product = validate_success(
            api.get_product_specification(product["id"], REGULATORY_AFFAIRS))
        assert product["clearance_status"] == "DESIGN"
        assert product["design_trace_complete"] is True
        # No released lot of this product exists, so the coverage rung is
        # violated as well as the clearance rung.
        order = fixtures.create_distribution_order(api, product["id"],
                                                   requested_units=500)
        assert order["allocation_policy"] == "FEFO_STRICT"

        validate_error(
            api.allocate_distribution_order(order["id"], DISTRIBUTION_PLANNER),
            "ERR_PRODUCT_NOT_CLEARED")

        # Removing only the clearance violation lets the last rung surface.
        cleared = validate_success(api.record_product_clearance(
            product["id"], factories.clearance_payload(), REGULATORY_AFFAIRS))
        assert cleared["clearance_status"] == "CLEARED"
        assert cleared["submission_ref"] is not None
        assert cleared["cleared_at"] is not None
        assert cleared["version"] == product["version"] + 1

        validate_error(
            api.allocate_distribution_order(order["id"], DISTRIBUTION_PLANNER),
            "ERR_ALLOCATION_SHORTFALL")

        unchanged = validate_success(
            api.get_distribution_order(order["id"], DISTRIBUTION_PLANNER))
        assert unchanged["status"] == "DRAFT"
        assert unchanged["allocated_units"] == 0
        assert unchanged["shortfall_units"] == 0
        assert unchanged["version"] == order["version"]
        rows, _ = validate_paginated(api.list_distribution_order_allocations(
            order["id"], DISTRIBUTION_PLANNER))
        assert rows == []

    def test_shortfall_under_strict_policy_persists_nothing(self, api):
        """PRD §3.9: "If need remains and the order's `allocation_policy` is
        `FEFO_STRICT`, the request is rejected with `ERR_ALLOCATION_SHORTFALL`
        and **nothing whatsoever is persisted**: no reservation row is created,
        no lot counter moves, and the order stays in `DRAFT` with
        `allocated_units` 0."
        PRD §2.6: "**Rung 140 — allocation coverage, on `POST
        /distribution-orders/{id}/allocate`.** `ERR_ALLOCATION_SHORTFALL`
        (409)."

        Design: Difficulty/priority_pair_validation_conflict/product_not_cleared_priority_130_beats_allocation_shortfall_priority_140
        """
        bundle = fixtures.released_reagent_lot(
            api,
            lot_overrides={"planned_units": _LOT_PLANNED_UNITS},
            run_overrides={"planned_fill_units": _LOT_PLANNED_UNITS})
        lot_id = bundle["lot"]["id"]
        assert bundle["lot"]["available_units"] == _LOT_PLANNED_UNITS
        # The pool covers 300 of the 500 units asked for, so need remains.
        order = fixtures.create_distribution_order(api, bundle["product"]["id"],
                                                   requested_units=500)

        validate_error(
            api.allocate_distribution_order(order["id"], DISTRIBUTION_PLANNER),
            "ERR_ALLOCATION_SHORTFALL")

        unchanged = validate_success(
            api.get_distribution_order(order["id"], DISTRIBUTION_PLANNER))
        assert unchanged["status"] == "DRAFT"
        assert unchanged["allocated_units"] == 0
        assert unchanged["shortfall_units"] == 0
        assert unchanged["version"] == order["version"]

        rows, meta = validate_paginated(api.list_distribution_order_allocations(
            order["id"], DISTRIBUTION_PLANNER))
        assert rows == []
        assert meta["total_count"] == 0

        lot = validate_success(api.get_reagent_lot(lot_id, QA_RELEASER))
        assert lot["available_units"] == _LOT_PLANNED_UNITS
        assert lot["allocated_units"] == 0
        assert lot["shipped_units"] == 0
        assert lot["quarantined_units"] == 0
        assert lot["version"] == bundle["lot"]["version"]
        assertions.assert_reagent_lot_unit_conservation(lot)


# A specification whose weighted acceptance arithmetic is fully pinned: three of
# the four codes are held at fixed values, so only purity moves the score.
_WEIGHTED_SPEC = {
    "acceptance_mode": "WEIGHTED_SCORE",
    "potency_min_pct": 90.0,
    "potency_max_pct": 110.0,
    "purity_min_pct": 95.0,
    "endotoxin_max_eu_per_ml": 2.0,
    "required_test_codes": ["POTENCY", "PURITY", "ENDOTOXIN", "IDENTITY"],
}
# Potency misses the window low by 1.25, so its sub-score is 1 - 1.25 / 5.0 =
# 0.75 and its outcome is FAIL.
_POTENCY_VALUE = 88.75
# Endotoxin scores 1 - 0.5 / 2.0 = 0.75; identity scores 1 for any value at
# least 1.0.
_ENDOTOXIN_VALUE = 0.5
_IDENTITY_VALUE = 1.0
# 0.45 * 0.75 + 0.15 * 0.75 + 0.10 * 1 = 0.3375 + 0.1125 + 0.1000 = 0.5500, and
# all four codes are present so the denominator is the full 1.00 of weights.
# The score is therefore (0.5500 + 0.30 * purity / 100) * 100.


def _weighted_lot_with_purity(api, purity_value):
    """A raw material lot under a weighted specification, measured on all four
    codes with only purity varying."""
    spec = fixtures.create_material_specification(api, **_WEIGHTED_SPEC)
    lot = fixtures.create_material_lot(api, spec["id"])
    potency = fixtures.record_material_measurement(api, lot["id"], "POTENCY",
                                                   _POTENCY_VALUE)
    purity = fixtures.record_material_measurement(api, lot["id"], "PURITY",
                                                  purity_value)
    fixtures.record_material_measurement(api, lot["id"], "ENDOTOXIN",
                                         _ENDOTOXIN_VALUE)
    fixtures.record_material_measurement(api, lot["id"], "IDENTITY",
                                         _IDENTITY_VALUE)
    lot = validate_success(api.get_material_lot(lot["id"], QC_ANALYST))
    return {"spec": spec, "lot": lot, "potency": potency, "purity": purity}


class TestWeightedAcceptanceScoreBoundary:

    def test_score_of_exactly_85_00_qualifies_the_lot(self, api):
        """PRD §3.1: "Under `WEIGHTED_SCORE`, the verdict is `ACCEPT` when
        `acceptance_score` is at least 85.00 — the boundary is inclusive — **and**
        no present code produced a zero sub-score; an individual `FAIL` outcome
        does not block acceptance by itself, so a measurement slightly outside its
        bound is tolerated when the weighted score still reaches 85.00, and
        identical measurements that `ALL_PASS` would reject are qualified here."
        PRD §3.1: "Purity scores its `measured_value` divided by 100, capped at
        1."
        PRD §3.1: "On success the lot moves `UNDER_TEST` to `QUALIFIED`,
        `dispositioned_by_user_id` and `dispositioned_at` are recorded,
        `available_quantity_units` remains `received_quantity_units` minus
        `consumed_quantity_units`, and the lot's `version` increases by 1."

        Design: Difficulty/boundary_precision_check/acceptance_score_inclusive_at_exactly_85_00_and_unrounded_subscores_at_84_88
        """
        # Purity 100.0 scores 1, contributing the full 0.30: 0.5500 + 0.3000 =
        # 0.8500, which is exactly 85.00 percent.
        built = _weighted_lot_with_purity(api, 100.0)
        lot = built["lot"]
        assert built["potency"]["outcome"] == "FAIL"
        assert built["purity"]["outcome"] == "PASS"
        assert lot["acceptance_score"] == 85.00
        assert assertions.round_half_up(lot["acceptance_score"], 2) == 85.00
        assert lot["qualification_status"] == "UNDER_TEST"

        qualified = validate_success(api.disposition_material_lot(
            lot["id"], factories.material_lot_disposition_payload("QUALIFY"),
            QA_RELEASER))

        assert qualified["qualification_status"] == "QUALIFIED"
        assert qualified["acceptance_score"] == 85.00
        assert qualified["dispositioned_by_user_id"] is not None
        assert qualified["dispositioned_at"] is not None
        assert (qualified["available_quantity_units"]
                == qualified["received_quantity_units"]
                - qualified["consumed_quantity_units"])
        assert qualified["version"] == lot["version"] + 1

        persisted = validate_success(
            api.get_material_lot(lot["id"], QA_RELEASER))
        assert persisted["qualification_status"] == "QUALIFIED"
        assert persisted["acceptance_score"] == 85.00
        assertions.assert_material_quantity_conservation(persisted)

    def test_score_of_84_88_is_refused_one_step_below_the_boundary(self, api):
        """PRD §3.1: "Under `WEIGHTED_SCORE`, the verdict is `ACCEPT` when
        `acceptance_score` is at least 85.00 — the boundary is inclusive — **and**
        no present code produced a zero sub-score; an individual `FAIL` outcome
        does not block acceptance by itself, so a measurement slightly outside its
        bound is tolerated when the weighted score still reaches 85.00, and
        identical measurements that `ALL_PASS` would reject are qualified here."
        PRD §3.1: "When the verdict is not `ACCEPT`, or when a required code still
        has no result, the disposition is refused with
        `ERR_ACCEPTANCE_CRITERIA_NOT_MET`."
        PRD §3.1: "Sub-scores themselves are never rounded — only the final
        percentage is."

        Design: Difficulty/boundary_precision_check/acceptance_score_inclusive_at_exactly_85_00_and_unrounded_subscores_at_84_88
        """
        # Purity 99.6 scores 0.996, contributing 0.2988: 0.5500 + 0.2988 =
        # 0.8488, which is 84.88 percent — just under the inclusive boundary.
        built = _weighted_lot_with_purity(api, 99.6)
        lot = built["lot"]
        assert built["purity"]["outcome"] == "PASS"
        assert lot["acceptance_score"] == 84.88
        assert assertions.round_half_up(lot["acceptance_score"], 2) == 84.88

        validate_error(api.disposition_material_lot(
            lot["id"], factories.material_lot_disposition_payload("QUALIFY"),
            QA_RELEASER), "ERR_ACCEPTANCE_CRITERIA_NOT_MET")

        refused = validate_success(api.get_material_lot(lot["id"], QA_RELEASER))
        assert refused["qualification_status"] == "UNDER_TEST"
        assert refused["acceptance_score"] == 84.88
        assert refused["dispositioned_by_user_id"] is None
        assert refused["dispositioned_at"] is None
        assert refused["version"] == lot["version"]

    def test_unrounded_purity_subscore_keeps_the_score_below_the_boundary(
            self, api):
        """PRD §3.1: "Sub-scores themselves are never rounded — only the final
        percentage is."
        PRD §3.1: "Each present code's sub-score is multiplied by that code's
        weight — 0.45 for potency, 0.30 for purity, 0.15 for endotoxin, 0.10 for
        identity — and those products are summed; that sum is divided by the sum
        of the weights of the present codes only, so the denominator shrinks when
        codes are missing rather than treating an absent code as a zero."
        PRD §3.1: "When the verdict is not `ACCEPT`, or when a required code still
        has no result, the disposition is refused with
        `ERR_ACCEPTANCE_CRITERIA_NOT_MET`."

        Design: Difficulty/boundary_precision_check/acceptance_score_inclusive_at_exactly_85_00_and_unrounded_subscores_at_84_88
        """
        # Purity 99.9 scores 0.999 — a sub-score that must not be rounded to
        # 1.00. Unrounded it contributes 0.2997, giving 0.5500 + 0.2997 = 0.8497
        # and a score of 84.97; rounding the sub-score first would wrongly
        # produce exactly 85.00 and qualify the lot.
        built = _weighted_lot_with_purity(api, 99.9)
        lot = built["lot"]
        assert lot["acceptance_score"] == 84.97
        assert assertions.round_half_up(lot["acceptance_score"], 2) == 84.97

        validate_error(api.disposition_material_lot(
            lot["id"], factories.material_lot_disposition_payload("QUALIFY"),
            QA_RELEASER), "ERR_ACCEPTANCE_CRITERIA_NOT_MET")

        refused = validate_success(api.get_material_lot(lot["id"], QA_RELEASER))
        assert refused["qualification_status"] == "UNDER_TEST"
        assert refused["acceptance_score"] == 84.97


# The viable air channel's action limit, which the server stamps onto every
# sample of that channel as limit_value.
_VIABLE_AIR_LIMIT = constants.EM_ACTION_LIMITS["VIABLE_AIR"]


def _lot_with_scheduled_runs(api, count):
    """A finished lot whose bill of materials is dispensed, carrying ``count``
    scheduled runs on distinct lines. Samples may be recorded while a run is
    still scheduled."""
    bundle = fixtures.reagent_lot_with_bom(api)
    runs = []
    for index in range(count):
        runs.append(fixtures.schedule_fill_run(
            api, bundle["lot"]["id"],
            scheduled_start=constants.clock_plus(days=2 + index),
            scheduled_end=constants.clock_plus(days=2 + index, hours=4)))
    return bundle, runs


class TestEnvironmentalLimitAndGradeBoundaries:

    def test_result_equal_to_the_action_limit_is_conforming(self, api):
        """PRD §3.4: "`excursion` is true exactly when `result_value` is strictly
        greater than `limit_value`; a result equal to its limit is conforming."
        PRD §3.4: "The four monitoring channels each have their own action limit,
        which the server writes onto the sample as `limit_value`: viable air is
        limited to 10 colony-forming units per cubic metre, surface sampling to 5
        colony-forming units, non-viable particle counting to 3,520 particles per
        cubic metre, and bulk bioburden to 10 colony-forming units per
        millilitre."
        PRD §3.4: "`excursion_grade` is `MAJOR` when `result_value` is at least
        twice `limit_value`, `MINOR` when the sample is an excursion but has not
        reached twice the limit, and `NONE` when it is not an excursion at all."

        Design: Difficulty/boundary_precision_check/environmental_limit_equality_conforming_double_limit_major_and_third_minor_disqualifies
        """
        bundle, runs = _lot_with_scheduled_runs(api, 2)
        at_limit_run, above_limit_run = runs

        at_limit = fixtures.record_monitoring_sample(
            api, at_limit_run["id"], "VIABLE_AIR", 10.0)
        assertions.assert_monitoring_sample(at_limit)
        assert at_limit["limit_value"] == _VIABLE_AIR_LIMIT
        assert at_limit["result_value"] == 10.0
        assert at_limit["excursion"] is False
        assert at_limit["excursion_grade"] == "NONE"

        run = validate_success(api.get_fill_run(at_limit_run["id"],
                                               PRODUCTION_OPERATOR))
        assert run["minor_excursion_count"] == 0
        assert run["major_excursion_count"] == 0
        assert run["environmental_state"] == "CONFORMING"

        # One step above the limit is an excursion, and a minor one.
        above_limit = fixtures.record_monitoring_sample(
            api, above_limit_run["id"], "VIABLE_AIR", 10.1)
        assertions.assert_monitoring_sample(above_limit)
        assert above_limit["excursion"] is True
        assert above_limit["excursion_grade"] == "MINOR"

        second = validate_success(api.get_fill_run(above_limit_run["id"],
                                                  PRODUCTION_OPERATOR))
        assert second["minor_excursion_count"] == 1
        assert second["major_excursion_count"] == 0
        assert second["environmental_state"] == "EXCURSION"

        # Exactly one sample across both runs has excursion true.
        lot = validate_success(api.get_reagent_lot(bundle["lot"]["id"],
                                                   PRODUCTION_OPERATOR))
        assert lot["em_excursion_count"] == 1

    def test_twice_the_limit_is_major_and_one_step_under_it_is_minor(self, api):
        """PRD §3.4: "`excursion_grade` is `MAJOR` when `result_value` is at least
        twice `limit_value`, `MINOR` when the sample is an excursion but has not
        reached twice the limit, and `NONE` when it is not an excursion at all."
        PRD §3.4: "From those counts comes `environmental_state`: `DISQUALIFIED`
        when `major_excursion_count` is at least 1 or `minor_excursion_count` is
        at least 3, otherwise `EXCURSION` when `minor_excursion_count` is at least
        1, and otherwise `CONFORMING`."

        Design: Difficulty/boundary_precision_check/environmental_limit_equality_conforming_double_limit_major_and_third_minor_disqualifies
        """
        bundle, runs = _lot_with_scheduled_runs(api, 2)
        major_run, minor_run = runs

        # Exactly twice the limit reaches the major threshold, which is
        # inclusive.
        major = fixtures.record_monitoring_sample(
            api, major_run["id"], "VIABLE_AIR", 20.0)
        assert major["limit_value"] == _VIABLE_AIR_LIMIT
        assert major["excursion"] is True
        assert major["excursion_grade"] == "MAJOR"

        run = validate_success(api.get_fill_run(major_run["id"],
                                               PRODUCTION_OPERATOR))
        assert run["major_excursion_count"] == 1
        assert run["minor_excursion_count"] == 0
        # A single major excursion disqualifies the run on its own.
        assert run["environmental_state"] == "DISQUALIFIED"

        # One step below twice the limit is still only a minor excursion.
        minor = fixtures.record_monitoring_sample(
            api, minor_run["id"], "VIABLE_AIR", 19.9)
        assert minor["excursion"] is True
        assert minor["excursion_grade"] == "MINOR"

        second = validate_success(api.get_fill_run(minor_run["id"],
                                                  PRODUCTION_OPERATOR))
        assert second["major_excursion_count"] == 0
        assert second["minor_excursion_count"] == 1
        assert second["environmental_state"] == "EXCURSION"

    def test_third_minor_excursion_disqualifies_the_run(self, api):
        """PRD §3.4: "From those counts comes `environmental_state`:
        `DISQUALIFIED` when `major_excursion_count` is at least 1 or
        `minor_excursion_count` is at least 3, otherwise `EXCURSION` when
        `minor_excursion_count` is at least 1, and otherwise `CONFORMING`."
        PRD §3.4: "`minor_excursion_count` is the count of the run's samples
        graded `MINOR`; `major_excursion_count` is the count graded `MAJOR`;
        `bioburden_cfu_per_ml` on the run is the largest `result_value` among that
        run's `BIOBURDEN_BULK` samples, and stays null while the run has never
        been sampled on that channel."

        Design: Difficulty/boundary_precision_check/environmental_limit_equality_conforming_double_limit_major_and_third_minor_disqualifies
        """
        bundle, runs = _lot_with_scheduled_runs(api, 1)
        run_id = runs[0]["id"]

        for value, expected_minors, expected_state in ((10.1, 1, "EXCURSION"),
                                                       (10.2, 2, "EXCURSION"),
                                                       (10.3, 3, "DISQUALIFIED")):
            sample = fixtures.record_monitoring_sample(api, run_id,
                                                       "VIABLE_AIR", value)
            assert sample["excursion_grade"] == "MINOR"
            run = validate_success(api.get_fill_run(run_id,
                                                    PRODUCTION_OPERATOR))
            assert run["minor_excursion_count"] == expected_minors
            assert run["major_excursion_count"] == 0
            assert run["environmental_state"] == expected_state

        # The run has never been sampled on the bulk bioburden channel.
        final = validate_success(api.get_fill_run(run_id, PRODUCTION_OPERATOR))
        assert final["bioburden_cfu_per_ml"] is None
        lot = validate_success(api.get_reagent_lot(bundle["lot"]["id"],
                                                   PRODUCTION_OPERATOR))
        assert lot["em_excursion_count"] == 3
        assert lot["bioburden_cfu_per_ml"] is None

    def test_lot_excursion_count_spans_every_run_of_the_lot(self, api):
        """PRD §3.4: "On the parent lot, `em_excursion_count` is recomputed as the
        count of samples with `excursion` true across **all** of that lot's runs,
        not just the run being sampled, and the lot's `bioburden_cfu_per_ml` is
        recomputed as the largest `BIOBURDEN_BULK` `result_value` across all of
        its runs, staying null while no such sample exists anywhere on the lot."
        PRD §3.4: "All samples of a run participate in these figures, including
        samples recorded while the run was still `SCHEDULED`; an aborted run keeps
        its samples on file, but they no longer feed any lot disposition
        decision."

        Design: Difficulty/boundary_precision_check/environmental_limit_equality_conforming_double_limit_major_and_third_minor_disqualifies
        """
        bundle, runs = _lot_with_scheduled_runs(api, 3)
        conforming_run, minor_run, major_run = runs

        # A result exactly on the limit contributes nothing to the count.
        fixtures.record_monitoring_sample(api, conforming_run["id"],
                                          "VIABLE_AIR", 10.0)
        for value in (10.1, 10.2, 10.3):
            fixtures.record_monitoring_sample(api, minor_run["id"],
                                              "VIABLE_AIR", value)
        fixtures.record_monitoring_sample(api, major_run["id"],
                                          "VIABLE_AIR", 20.0)

        lot = validate_success(api.get_reagent_lot(bundle["lot"]["id"],
                                                   PRODUCTION_OPERATOR))
        # Three minors plus one major have excursion true; the sample at the
        # limit does not.
        assert lot["em_excursion_count"] == 4
        # Every one of those samples was recorded while its run was scheduled,
        # so the lot itself has not moved off PLANNED.
        assert lot["disposition_status"] == "PLANNED"

        states = {}
        for run in runs:
            fetched = validate_success(api.get_fill_run(run["id"],
                                                        PRODUCTION_OPERATOR))
            assert fetched["status"] == "SCHEDULED"
            states[run["id"]] = fetched["environmental_state"]
        assert states[conforming_run["id"]] == "CONFORMING"
        assert states[minor_run["id"]] == "DISQUALIFIED"
        assert states[major_run["id"]] == "DISQUALIFIED"

        samples, meta = validate_paginated(api.list_monitoring_samples(
            minor_run["id"], QC_ANALYST))
        assert meta["total_count"] == 3
        assert all(sample["excursion"] is True for sample in samples)
