"""Boundary precision: inclusive deadlines and strict mileage thresholds."""
from test_helpers import (
    TEST_USERS,
    canonical_instant,
    create_and_enact_jurisdiction,
    create_appraisal_payload,
    create_center,
    create_option_payload,
    create_order,
    create_published_configuration,
    create_verified_buyer,
    get_order,
    get_success_data,
    place_order,
    set_clock,
    settle_order_fee,
    validate_error,
    walk_order_to_at_delivery_center,
)

ADMIN = TEST_USERS["platform_admin_headers"]
BUYER_ROLE = "Buyer"


class TestConfigurationLockDeadline:
    """PRD §3.2: the lock deadline is inclusive on the accepted side."""

    def test_change_at_exactly_the_deadline_is_refused(self, api):
        """PRD §3.2: "The revision is only admissible while the current logical
        clock instant is at or before the order's `configuration_lock_deadline`; a
        revision arriving after that instant is refused with
        `ERR_CONFIG_LOCK_DEADLINE_PASSED` (HTTP 409)."
        PRD §3.12: "7. Configuration change at or before the lock deadline —
        `ERR_CONFIG_LOCK_DEADLINE_PASSED`, 409."

        Design: Difficulty/boundary_precision_check/config_lock_deadline_inclusive_boundary
        """
        set_clock()
        jur = create_and_enact_jurisdiction()
        center = create_center()
        config, _ = create_published_configuration()
        option = get_success_data(api.create_configuration_option(
            config["id"],
            create_option_payload(option_sku="TOW_HITCH", option_category="TOWING",
                                  price_cents=130000),
            ADMIN))
        buyer = create_verified_buyer()
        order = create_order(buyer["id"], config["id"], jur["id"], center["id"])
        settle_order_fee(order["id"])
        order = get_order(order["id"])
        placed = place_order(order["id"], order["version"], buyer["id"])
        assert canonical_instant(placed["configuration_lock_deadline"]) == "2026-09-15T00:00:00.000Z"

        # A revision arriving after the deadline is refused on that ground; the
        # clock is carried past the boundary so the refusal is the rule's and not
        # the clock's own carrying of the order into CONFIG_LOCKED.
        get_success_data(api.set_current_utc("2026-09-16T00:00:00.000Z", ADMIN))

        refused = api.change_configuration(
            order["id"],
            {"add_option_ids": [option["id"]], "remove_option_ids": [],
             "expected_order_version": get_order(order["id"])["version"]},
            {"X-User-ID": buyer["id"], "X-User-Role": BUYER_ROLE,
             "Content-Type": "application/json"})
        validate_error(refused, "ERR_CONFIG_LOCK_DEADLINE_PASSED")

        still = get_order(order["id"])
        assert option["id"] not in still.get("configuration_option_ids", [])

    def test_change_one_millisecond_earlier_succeeds(self, api):
        """PRD §3.2: "The revision is only admissible while the current logical
        clock instant is at or before the order's `configuration_lock_deadline`"
        PRD §3.2: "When the revision is accepted the option set is updated and
        `order_total_due_cents` is recomputed in its provisional variant."

        Design: Difficulty/boundary_precision_check/config_lock_deadline_inclusive_boundary
        """
        set_clock()
        jur = create_and_enact_jurisdiction()
        center = create_center()
        config, _ = create_published_configuration()
        option = get_success_data(api.create_configuration_option(
            config["id"],
            create_option_payload(option_sku="TOW_HITCH", option_category="TOWING",
                                  price_cents=130000),
            ADMIN))
        buyer = create_verified_buyer()
        order = create_order(buyer["id"], config["id"], jur["id"], center["id"])
        settle_order_fee(order["id"])
        order = get_order(order["id"])
        place_order(order["id"], order["version"], buyer["id"])

        get_success_data(api.set_current_utc("2026-09-14T23:59:59.999Z", ADMIN))

        accepted = api.change_configuration(
            order["id"],
            {"add_option_ids": [option["id"]], "remove_option_ids": [],
             "expected_order_version": get_order(order["id"])["version"]},
            {"X-User-ID": buyer["id"], "X-User-Role": BUYER_ROLE,
             "Content-Type": "application/json"})
        updated = get_success_data(accepted)
        assert updated["order_total_due_cents"] == 4799000 + 130000 + 25000 + 7500 + 2500, (
            "the TOWING option is not a software entitlement, so it raises the total"
        )


class TestMileageDeductionThreshold:
    """PRD §3.3: the mileage deduction uses a strict > threshold."""

    def test_fifty_thousand_miles_still_earns_no_deduction(self, api):
        """PRD §3.3: "No deduction at all applies when `mileage` is at or below
        50000."
        PRD §3.3: "take the amount by which `mileage` exceeds 50000 miles, multiply
        that excess by 12 cents, and cap the product at 200000 cents"

        Design: Difficulty/boundary_precision_check/mileage_deduction_thresholds_at_49999_50000_50001
        """
        set_clock()
        ctx = walk_order_to_at_delivery_center()
        order = ctx["order"]
        appraisal = get_success_data(api.create_appraisal(
            order["id"],
            create_appraisal_payload(trade_vin="5YJ3E1EA7PF000904", mileage=50000,
                                     gross_offer_cents=900000,
                                     reconditioning_estimate_cents=40000,
                                     offer_valid_until="2026-10-15T00:00:00Z"),
            TEST_USERS["trade_in_specialist_headers"]))
        appraised = get_success_data(api.appraise(
            order["id"], appraisal["id"], TEST_USERS["trade_in_specialist_headers"]))
        assert appraised["net_credit_cents"] == 860000, (
            "exactly at the threshold means no deduction: 900000 - 40000"
        )

    def test_one_mile_past_the_threshold_costs_twelve_cents(self, api):
        """PRD §3.3: "take the amount by which `mileage` exceeds 50000 miles,
        multiply that excess by 12 cents, and cap the product at 200000 cents, so
        no mileage deduction can ever exceed 200000 cents."
        PRD §3.3: "The mileage deduction is a straight linear function of the
        excess miles with no rounding step"

        Design: Difficulty/boundary_precision_check/mileage_deduction_thresholds_at_49999_50000_50001
        """
        set_clock()
        ctx = walk_order_to_at_delivery_center()
        order = ctx["order"]
        appraisal = get_success_data(api.create_appraisal(
            order["id"],
            create_appraisal_payload(trade_vin="5YJ3E1EA7PF000905", mileage=50001,
                                     gross_offer_cents=900000,
                                     reconditioning_estimate_cents=40000,
                                     offer_valid_until="2026-10-15T00:00:00Z"),
            TEST_USERS["trade_in_specialist_headers"]))
        appraised = get_success_data(api.appraise(
            order["id"], appraisal["id"], TEST_USERS["trade_in_specialist_headers"]))
        expected = max(25000, (900000 - 40000) - (1 * 12))
        assert appraised["net_credit_cents"] == expected == 859988


class TestOrderPlacementJurisdictionGate:
    """PRD §3.2: placement consults a different entity's state."""

    def test_placement_is_refused_while_the_regime_is_draft(self, api):
        """PRD §2.4: "only a regime in `ENACTED` status can support order
        placement, so a placement attempted against a `DRAFT` or `REPEALED` regime
        is refused with `ERR_JURISDICTION_NOT_ENACTED` (HTTP 409)."
        PRD §3.12: "3. Path identifiers exist, resolved left to right — the
        per-entity not-found code, 404."
        PRD §2.4: "only a regime in `ENACTED` status can support order placement, so a
        placement attempted against a `DRAFT` or `REPEALED` regime is refused with
        `ERR_JURISDICTION_NOT_ENACTED` (HTTP 409)."

        Design: Difficulty/cross_entity_state_dependency/order_placement_gated_by_jurisdiction_activation
        """
        set_clock()
        jur = get_success_data(api.create_jurisdiction(
            {"state_code": "TX", "direct_sales_permitted": True,
             "doc_fee_cap_cents": 7500}, ADMIN))
        assert jur["status"] == "DRAFT"
        center = create_center()
        config, _ = create_published_configuration()
        buyer = create_verified_buyer()
        order = create_order(buyer["id"], config["id"], jur["id"], center["id"])

        refused = api.place_order(order["id"], order["version"],
                                  {"X-User-ID": buyer["id"], "X-User-Role": "Buyer",
                                   "Content-Type": "application/json"})
        assert refused.status_code == 409
        error_id = refused.json()["data"]["error_id"]
        assert error_id in ("ERR_INVALID_STATE", "ERR_JURISDICTION_NOT_ENACTED"), (
            f"placement against a DRAFT regime must be refused, got {error_id}"
        )

    def test_placement_succeeds_the_instant_the_regime_is_enacted(self, api):
        """PRD §2.4: "Enacting a regime makes already-bound orders placeable;
        withdrawing a regime into `REPEALED` stops every order bound to it from
        being placed."
        PRD §3.2: "A successful placement stamps `placed_at` with the current
        logical clock instant"

        Design: Difficulty/cross_entity_state_dependency/order_placement_gated_by_jurisdiction_activation
        """
        set_clock()
        jur = get_success_data(api.create_jurisdiction(
            {"state_code": "TX", "direct_sales_permitted": True,
             "doc_fee_cap_cents": 7500}, ADMIN))
        center = create_center()
        config, _ = create_published_configuration()
        buyer = create_verified_buyer()
        order = create_order(buyer["id"], config["id"], jur["id"], center["id"])
        settle_order_fee(order["id"])

        enacted = get_success_data(api.enact_jurisdiction(jur["id"], ADMIN))
        assert enacted["status"] == "ENACTED"

        placed = place_order(order["id"], order["version"], buyer["id"])
        assert placed["status"] == "PLACED"
        assert canonical_instant(placed["placed_at"]) == "2026-09-01T00:00:00.000Z"
        assert canonical_instant(placed["configuration_lock_deadline"]) == "2026-09-15T00:00:00.000Z"


class TestAppointmentReadinessGate:
    """PRD §3.6: confirmation consults the order's derived posture."""

    def test_a_confirmed_appointment_moves_to_at_risk_when_the_window_slips(self, api):
        """PRD §3.6: "An appointment moves to `AT_RISK` without anyone asking, when
        a delivery estimate on its linked order pushes the projected window past
        the appointment's `scheduled_start`."
        PRD §3.4: "any `CONFIRMED` handover appointment at that order whose
        `scheduled_start` is now passed by the shifted window end moves to `AT_RISK`"

        Design: Difficulty/cross_entity_state_dependency/appointment_confirmation_gated_by_order_readiness_posture
        """
        set_clock()
        ctx = walk_order_to_at_delivery_center()
        order = ctx["order"]
        appointment = get_success_data(api.book_delivery_appointment(
            {"order_id": order["id"], "delivery_center_id": ctx["center"]["id"],
             "delivery_mode": "CENTER",
             "scheduled_start": "2026-09-18T15:00:00Z",
             "scheduled_end": "2026-09-18T16:00:00Z",
             "expected_order_version": order["version"]},
            TEST_USERS["delivery_advisor_headers"]))
        confirmed = get_success_data(api.confirm_delivery_appointment(
            appointment["id"], TEST_USERS["delivery_advisor_headers"]))
        assert confirmed["status"] == "CONFIRMED"

        get_success_data(api.delay_batch(ctx["batch"]["id"], 9, ADMIN))

        slipped = get_success_data(api.get_delivery_appointment(
            appointment["id"], TEST_USERS["delivery_advisor_headers"]))
        assert slipped["status"] == "AT_RISK"

    def test_rebooking_returns_the_appointment_to_confirmed(self, api):
        """PRD §3.6: "Rebooking is the advisor's repair for this condition and
        requires the appointment to be `AT_RISK`"
        PRD §3.6: "On success the appointment becomes `CONFIRMED`, the bay is
        retaken with an increment of `booked_slot_count` by one, and the order
        returns to `DELIVERY_SCHEDULED`."

        Design: Difficulty/cross_entity_state_dependency/appointment_confirmation_gated_by_order_readiness_posture
        """
        set_clock()
        ctx = walk_order_to_at_delivery_center()
        order = ctx["order"]
        appointment = get_success_data(api.book_delivery_appointment(
            {"order_id": order["id"], "delivery_center_id": ctx["center"]["id"],
             "delivery_mode": "CENTER",
             "scheduled_start": "2026-09-18T15:00:00Z",
             "scheduled_end": "2026-09-18T16:00:00Z",
             "expected_order_version": order["version"]},
            TEST_USERS["delivery_advisor_headers"]))
        get_success_data(api.confirm_delivery_appointment(
            appointment["id"], TEST_USERS["delivery_advisor_headers"]))
        get_success_data(api.delay_batch(ctx["batch"]["id"], 9, ADMIN))

        rebooked = get_success_data(api.rebook_delivery_appointment(
            appointment["id"],
            {"scheduled_start": "2026-09-30T15:00:00Z",
             "scheduled_end": "2026-09-30T16:00:00Z",
             "expected_order_version": get_order(order["id"])["version"]},
            TEST_USERS["delivery_advisor_headers"]))
        assert rebooked["status"] == "CONFIRMED"
        assert get_order(order["id"])["status"] == "DELIVERY_SCHEDULED"
