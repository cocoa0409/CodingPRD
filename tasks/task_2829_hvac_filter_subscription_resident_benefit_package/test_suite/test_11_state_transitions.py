"""
State-machine corners: the happy legs, the refused legs, terminal lockdown,
initial states, and the transitions whose side effects reach other entities.
"""

from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import assertions as a
from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.api_errors import (
    ERR_CASE_STATE_INVALID,
    ERR_SHIPMENT_STATE_INVALID,
)
from test_helpers.test_users import OPERATOR


class TestShipmentLegs:
    """Dispatch, the refused delivery, and the two arms after a return request."""

    def test_dispatching_a_scheduled_shipment_stamps_the_logical_clock(self, api):
        """
        The first shipment accepts /ship while its subscription is ACTIVE: it moves
        to SHIPPED with the carrier's tracking code and a shipped_at read off the
        logical clock rather than wall time, and delivery has not happened yet.

        PRD §3.5: "It requires the shipment to be `SCHEDULED` **and** the owning subscription to be `ACTIVE`, stores the `tracking_code` the carrier assigned, and stamps `shipped_at` with the logical-clock instant."

        Design: Corner/state_machines/shipment_ship_moves_scheduled_to_shipped
        """
        env = fx.build_base_env(api)
        shipment = fx.first_shipment(api, env.subscription_id)
        assert shipment["status"] == "SCHEDULED"

        shipped = validate_success(
            api.ship_shipment(shipment["id"], f.ship_payload("TRK-A-0001"), OPERATOR)
        )
        assert shipped["status"] == "SHIPPED"
        assert shipped["tracking_code"] == "TRK-A-0001"
        a.assert_instant_equals(shipped["shipped_at"], "2026-08-05T00:00:00Z")
        assert shipped["delivered_at"] is None
        assert shipped["version"] == 2
        assert fx.read_subscription(api, env.subscription_id)["status"] == "ACTIVE"

    def test_delivering_a_shipment_that_was_never_shipped_is_refused(self, api):
        """
        /deliver belongs to the SHIPPED state, so invoking it on a still-SCHEDULED
        shipment is refused and writes neither the delivery instant nor a version.

        PRD §2.10: "The shipment's `status` permits the requested transition — otherwise `ERR_SHIPMENT_STATE_INVALID` (409)."

        Design: Corner/state_machines/deliver_a_scheduled_shipment_returns_409_shipment_state_invalid
        """
        env = fx.build_base_env(api)
        shipment = fx.first_shipment(api, env.subscription_id)

        validate_error(
            api.deliver_shipment(
                shipment["id"], f.deliver_payload("2026-08-06T00:00:00Z"), OPERATOR
            ),
            ERR_SHIPMENT_STATE_INVALID,
            409,
        )

        after = validate_success(api.get_shipment(shipment["id"], OPERATOR))
        assert after["status"] == "SCHEDULED"
        assert after["delivered_at"] is None
        assert after["version"] == 1

    def test_returning_a_shipment_before_the_return_is_opened_is_refused(self, api):
        """
        From DELIVERED only /request-return is offered; the /return arm hangs off
        RETURN_REQUESTED, so calling it one step early leaves the shipment
        DELIVERED at the version its three accepted writes produced.

        PRD §3.5: "Opening a return moves the shipment `DELIVERED → RETURN_REQUESTED` and records the `return_reason` supplied with the request, and from `RETURN_REQUESTED` exactly two arms lead out, with deliberately divergent consequences."

        Design: Corner/state_machines/shipment_return_without_request_return_rejected
        """
        env = fx.build_base_env(api)
        delivered = fx.deliver_first_shipment(
            api, env.subscription_id, "2026-08-06T00:00:00Z"
        )
        assert delivered["status"] == "DELIVERED"

        validate_error(
            api.return_shipment(
                delivered["id"], f.return_payload("2026-08-10T00:00:00Z"), OPERATOR
            ),
            ERR_SHIPMENT_STATE_INVALID,
            409,
        )

        after = validate_success(api.get_shipment(delivered["id"], OPERATOR))
        assert after["status"] == "DELIVERED"
        assert after["returned_at"] is None
        assert after["version"] == 3

    def test_a_returned_shipment_refuses_the_sibling_write_off_arm(self, api):
        """
        RETURNED is terminal, so the write-off arm that was legal one step earlier
        is refused: the shipment keeps its returned_at, no unreturned fee row is
        posted and the property balance is untouched.

        PRD §3.5: "`RETURNED`, `UNRETURNED_WRITTEN_OFF` and `CANCELLED` are all terminal for a shipment; any action attempted from a terminal status is rejected with `ERR_SHIPMENT_STATE_INVALID`."

        Design: Corner/state_machines/returned_shipment_accepts_no_further_trigger
        """
        env = fx.build_base_env(api)
        delivered = fx.deliver_first_shipment(
            api, env.subscription_id, "2026-08-06T00:00:00Z"
        )
        fx.request_return_on(api, delivered["id"])
        returned = validate_success(
            api.return_shipment(
                delivered["id"], f.return_payload("2026-08-10T00:00:00Z"), OPERATOR
            )
        )
        assert returned["status"] == "RETURNED"
        assert a.property_balance(api, env.property_id, OPERATOR) == 5588

        validate_error(
            api.write_off_shipment(delivered["id"], OPERATOR),
            ERR_SHIPMENT_STATE_INVALID,
            409,
        )

        after = validate_success(api.get_shipment(delivered["id"], OPERATOR))
        assert after["status"] == "RETURNED"
        a.assert_instant_equals(after["returned_at"], "2026-08-10T00:00:00Z")
        a.assert_cents(after["unreturned_fee_cents"], 0, "unreturned_fee_cents")
        rows = fx.read_ledger(api, env.subscription_id)
        assert a.find_ledger_rows(rows, "UNRETURNED_SHIPMENT_FEE") == []
        assert a.property_balance(api, env.property_id, OPERATOR) == 5588


class TestSubscriptionOpeningStates:
    """The initial cell of both parallel dimensions, and the activation leg."""

    def test_a_new_subscription_starts_in_the_initial_cell_of_both_dimensions(self, api):
        """
        Enrolment lands on (PENDING_SETUP, UNVERIFIED) with version 1, no evidence
        yet, no shipment, no money, four PENDING entitlement rows with no
        effective_from, and neither the resident nor the unit advanced.

        PRD §3.3: "A freshly enrolled subscription is `PENDING_SETUP` on the commercial dimension and `UNVERIFIED` on the compliance dimension, with `version` 1."

        Design: Corner/state_machines/subscription_starts_pending_setup_and_unverified
        """
        env = fx.build_base_env(api, activate=False)

        subscription = fx.read_subscription(api, env.subscription_id)
        assert subscription["status"] == "PENDING_SETUP"
        assert subscription["installation_posture"] == "UNVERIFIED"
        assert subscription["latest_detection_method"] is None
        assert subscription["latest_evidence_score"] is None
        assert subscription["activated_at"] is None
        assert subscription["shipment_sequence_counter"] == 0
        assert subscription["next_ship_date"] is None
        assert subscription["version"] == 1

        rows = fx.read_entitlements(api, env.subscription_id)
        assert len(rows) == 4
        for row in rows:
            a.assert_entitlement(row, "PENDING", forfeit_reason=None)
            assert row["effective_from"] is None

        shipments, ship_meta = validate_paginated(
            api.list_shipments(OPERATOR, {"subscription_id": env.subscription_id})
        )
        assert shipments == []
        assert ship_meta["total_count"] == 0
        assert fx.read_ledger(api, env.subscription_id) == []
        assert a.property_balance(api, env.property_id, OPERATOR) == 0

        assert validate_success(api.get_resident(env.resident_id, OPERATOR))["status"] == (
            "PROSPECT"
        )
        assert validate_success(api.get_unit(env.unit_id, OPERATOR))["status"] == "AVAILABLE"

    def test_activation_applies_its_whole_side_effect_set_in_one_step(self, api):
        """
        One activate call is checked across every entity it touches: the
        subscription and its stamps, the resident, the unit, all four
        entitlements, shipment #1 with the derived cadence fields, both opening
        ledger rows, and the property rollup.

        PRD §3.4: "Everything activation touches, it touches in one atomic step."

        Design: Corner/state_machines/subscription_activate_applies_full_side_effect_set
        """
        env = fx.build_base_env(api, activate=False)

        activated = validate_success(api.activate_subscription(env.subscription_id, OPERATOR))
        assert activated["status"] == "ACTIVE"
        a.assert_instant_equals(activated["activated_at"], "2026-08-05T00:00:00Z")
        assert activated["installation_posture"] == "UNVERIFIED"
        assert activated["shipment_sequence_counter"] == 1
        assert activated["next_ship_date"] == "2026-08-05"
        assert activated["version"] == 2

        assert validate_success(api.get_resident(env.resident_id, OPERATOR))["status"] == (
            "RESIDING"
        )
        assert validate_success(api.get_unit(env.unit_id, OPERATOR))["status"] == "OCCUPIED"

        rows = fx.read_entitlements(api, env.subscription_id)
        assert sorted(row["benefit_code"] for row in rows) == [
            "AIR_QUALITY_GUARANTEE",
            "CREDIT_REPORTING",
            "DAMAGE_WAIVER",
            "RENTERS_INSURANCE",
        ]
        for row in rows:
            a.assert_entitlement(row, "ACTIVE", forfeit_reason=None)
            a.assert_instant_equals(row["effective_from"], "2026-08-05T00:00:00Z")

        shipments, ship_meta = validate_paginated(
            api.list_shipments(OPERATOR, {"subscription_id": env.subscription_id})
        )
        assert ship_meta["total_count"] == 1
        shipment = shipments[0]
        assert shipment["status"] == "SCHEDULED"
        assert shipment["sequence_number"] == 1
        assert shipment["scheduled_ship_date"] == "2026-08-05"
        assert shipment["quantity"] == 2
        assert shipment["sku_id"] == env.sku_id

        ledger = fx.read_ledger(api, env.subscription_id)
        assert len(ledger) == 2
        by_type = {row["entry_type"]: row for row in ledger}
        a.assert_ledger_row(
            by_type["ENROLLMENT_FEE"],
            "ENROLLMENT_FEE",
            2500,
            "PROPERTY_MANAGER",
            env.subscription_id,
        )
        a.assert_ledger_row(
            by_type["MONTHLY_FEE"],
            "MONTHLY_FEE",
            3088,
            "PROPERTY_MANAGER",
            env.subscription_id,
        )
        assert a.property_balance(api, env.property_id, OPERATOR) == 5588


class TestNonInstallCaseNotice:
    """The OPEN -> NOTICE_SENT leg, and its refusal to run twice."""

    def test_the_notice_leg_is_not_idempotent(self, api):
        """
        The first /send-notice stamps the notice instant and sets the remediation
        deadline twenty-one days later; the second finds the case already in
        NOTICE_SENT and is refused without re-stamping either field or bumping the
        version.

        PRD §3.6: "Sending the resident notice moves the case `OPEN → NOTICE_SENT`, stamps `notice_sent_at` with the logical-clock instant, and sets `remediation_deadline` to the date of that notice advanced by a twenty-one-day grace period."

        Design: Corner/state_machines/second_send_notice_on_notice_sent_case_rejected
        """
        env = fx.build_base_env(api)
        fx.set_clock(api, "2026-08-07T00:00:00Z")
        fx.submit_renewal_survey(
            api,
            env.subscription_id,
            installed_last_shipment=False,
            filters_on_hand_count=0,
            self_reported_change_date="2026-08-06",
        )
        case = fx.open_case(api, env.subscription_id, "RENEWAL_SURVEY", "2026-08-07")
        assert case["status"] == "OPEN"
        assert case["evidence_score"] == 70
        assert case["suspect_threshold"] == 55
        assert case["confirm_threshold"] == 80

        noticed = validate_success(api.send_case_notice(case["id"], OPERATOR))
        assert noticed["status"] == "NOTICE_SENT"
        a.assert_instant_equals(noticed["notice_sent_at"], "2026-08-07T00:00:00Z")
        assert noticed["remediation_deadline"] == "2026-08-28"
        assert noticed["version"] == 2

        validate_error(
            api.send_case_notice(case["id"], OPERATOR), ERR_CASE_STATE_INVALID, 409
        )

        after = validate_success(api.get_non_install_case(case["id"], OPERATOR))
        assert after["status"] == "NOTICE_SENT"
        a.assert_instant_equals(after["notice_sent_at"], "2026-08-07T00:00:00Z")
        assert after["remediation_deadline"] == "2026-08-28"
        assert after["version"] == 2
        assert after["evidence_score"] == 70


class TestMoneyBearingAndCascadingLegs:
    """Legs whose transition reaches the ledger, the units or the resident."""

    def test_the_write_off_arm_posts_its_fee_and_moves_the_property_balance(self, api):
        """
        The money-bearing arm out of RETURN_REQUESTED sets the unreturned fee to
        the lesser of the shipment's own snapshotted cost times quantity and the
        cap, posts it as one positive row against the shipment, and the property's
        derived balance moves by exactly that fee.

        PRD §3.5: "On the **second arm**, the filters never came back: the shipment moves `RETURN_REQUESTED → UNRETURNED_WRITTEN_OFF`, and its `unreturned_fee_cents` is set to the lesser of two figures — the `unit_cost_cents` of the catalog entry named by the shipment's own `sku_id` snapshot multiplied by the shipment's `quantity`, and a per-shipment cap of two thousand five hundred cents."

        Design: Corner/state_machines/shipment_write_off_inserts_fee_and_updates_property_balance
        """
        env = fx.build_base_env(api)
        delivered = fx.deliver_first_shipment(
            api, env.subscription_id, "2026-08-06T00:00:00Z"
        )
        fx.request_return_on(api, delivered["id"])
        assert len(fx.read_ledger(api, env.subscription_id)) == 2
        assert a.property_balance(api, env.property_id, OPERATOR) == 5588

        written_off = validate_success(api.write_off_shipment(delivered["id"], OPERATOR))
        assert written_off["status"] == "UNRETURNED_WRITTEN_OFF"
        a.assert_cents(written_off["unreturned_fee_cents"], 1360, "unreturned_fee_cents")

        fees, fee_meta = validate_paginated(
            api.list_ledger_entries(
                env.subscription_id, OPERATOR, {"entry_type": "UNRETURNED_SHIPMENT_FEE"}
            )
        )
        assert fee_meta["total_count"] == 1
        a.assert_ledger_row(
            fees[0], "UNRETURNED_SHIPMENT_FEE", 1360, "PROPERTY_MANAGER", delivered["id"]
        )

        assert a.property_balance(api, env.property_id, OPERATOR) == 6948
        assert fx.read_subscription(api, env.subscription_id)["status"] == "ACTIVE"

    def test_completing_a_transfer_mints_the_successor_and_retires_the_outgoing_leg(
        self, api
    ):
        """
        One completion re-prices the subscription against the destination unit
        (cadence 90, one filter per shipment, 3077 a month), freezes the two
        prorated legs and their signed difference, cancels the outgoing leg with
        the reserved reason, books exactly one adjustment row against the successor
        and swaps which unit is occupied while the resident stays put.

        PRD §3.8: "A successor subscription is minted on the destination unit in `status` `ACTIVE` and `installation_posture` `UNVERIFIED`, with `predecessor_subscription_id` pointing back at the outgoing subscription, `assigned_sku_id` set to `remapped_sku_id`, `property_id` denormalised afresh from the destination unit, and its own recomputed `ship_cadence_days`, `filters_per_shipment`, `entitled_benefit_codes` and `monthly_fee_cents`; the transfer's `successor_subscription_id` records it."

        Design: Corner/state_machines/transfer_complete_mints_successor_and_cancels_outgoing
        """
        env = fx.build_base_env(api)
        unit_b = fx.create_unit(
            api,
            env.property_id,
            unit_label="B-201",
            hvac_system_type="SINGLE_STAGE",
            filter_slot_count=1,
            return_grille_count=1,
            nominal_size_code="16x25x1",
        )
        shipment = fx.first_shipment(api, env.subscription_id)
        fx.set_clock(api, "2026-09-11T00:00:00Z")

        transfer = validate_success(
            api.create_subscription_transfer(
                f.transfer_payload(env.subscription_id, unit_b["id"], "2026-09-11", 2),
                OPERATOR,
            ),
            201,
        )
        validate_success(api.remap_transfer_sku(transfer["id"], OPERATOR))

        completed = validate_success(api.complete_transfer(transfer["id"], OPERATOR))
        assert completed["status"] == "COMPLETED"
        a.assert_cents(completed["proration_credit_cents"], 2364, "proration_credit_cents")
        a.assert_cents(completed["proration_charge_cents"], 2051, "proration_charge_cents")
        a.assert_cents(completed["net_adjustment_cents"], -313, "net_adjustment_cents")

        successors, successor_meta = validate_paginated(
            api.list_subscriptions(
                OPERATOR, {"predecessor_subscription_id": env.subscription_id}
            )
        )
        assert successor_meta["total_count"] == 1
        successor = successors[0]
        assert completed["successor_subscription_id"] == successor["id"]
        assert successor["status"] == "ACTIVE"
        assert successor["installation_posture"] == "UNVERIFIED"
        assert successor["unit_id"] == unit_b["id"]
        assert successor["assigned_sku_id"] == env.sku_id
        assert successor["ship_cadence_days"] == 90
        assert successor["filters_per_shipment"] == 1
        a.assert_cents(successor["monthly_fee_cents"], 3077, "monthly_fee_cents")
        assert successor["predecessor_subscription_id"] == env.subscription_id

        outgoing = fx.read_subscription(api, env.subscription_id)
        assert outgoing["status"] == "CANCELLED"
        assert outgoing["cancel_reason"] == "TRANSFER_SUPERSEDED"
        assert outgoing["cancel_effective_date"] == "2026-09-11"
        for row in fx.read_entitlements(api, env.subscription_id):
            a.assert_entitlement(row, "EXPIRED", forfeit_reason="TRANSFER_SUPERSEDED")
        assert validate_success(api.get_shipment(shipment["id"], OPERATOR))["status"] == (
            "CANCELLED"
        )

        successor_ledger = fx.read_ledger(api, successor["id"])
        assert len(successor_ledger) == 1
        a.assert_ledger_row(
            successor_ledger[0],
            "TRANSFER_ADJUSTMENT",
            -313,
            "PROPERTY_MANAGER",
            transfer["id"],
        )
        assert a.property_balance(api, env.property_id, OPERATOR) == 5275

        assert validate_success(api.get_unit(env.unit_id, OPERATOR))["status"] == "AVAILABLE"
        assert validate_success(api.get_unit(unit_b["id"], OPERATOR))["status"] == "OCCUPIED"
        assert validate_success(api.get_resident(env.resident_id, OPERATOR))["status"] == (
            "RESIDING"
        )

    def test_offboarding_retires_both_an_occupied_and_an_available_unit(self, api):
        """
        Offboarding a suspended property covers both inbound legs of the unit's
        terminal state in one request — the occupied unit and the never-let one —
        while the subscription the earlier suspension parked stays SUSPENDED.

        PRD §3.2: "On success the property becomes `OFFBOARDED` — terminal — and every unit at the property whose `status` is `AVAILABLE` or `OCCUPIED` is driven to `OUT_OF_SERVICE`, which is likewise terminal for a unit."

        Design: Corner/state_machines/property_offboard_pushes_every_unit_out_of_service
        """
        env = fx.build_base_env(api)
        unit_b = fx.create_unit(
            api,
            env.property_id,
            unit_label="B-201",
            hvac_system_type="SINGLE_STAGE",
            filter_slot_count=1,
            return_grille_count=1,
            nominal_size_code="16x25x1",
        )
        assert validate_success(api.get_unit(env.unit_id, OPERATOR))["status"] == "OCCUPIED"
        assert unit_b["status"] == "AVAILABLE"

        suspended = validate_success(
            api.suspend_property(
                env.property_id,
                f.suspend_payload(suspend_reason="PM_PAYMENT_DELINQUENT"),
                OPERATOR,
            )
        )
        assert fx.read_subscription(api, env.subscription_id)["status"] == "SUSPENDED"

        offboarded = validate_success(api.offboard_property(env.property_id, OPERATOR))
        assert offboarded["status"] == "OFFBOARDED"
        assert offboarded["version"] == suspended["version"] + 1

        units, unit_meta = validate_paginated(
            api.list_property_units(env.property_id, OPERATOR)
        )
        assert unit_meta["total_count"] == 2
        assert {row["status"] for row in units} == {"OUT_OF_SERVICE"}
        assert validate_success(api.get_unit(env.unit_id, OPERATOR))["status"] == (
            "OUT_OF_SERVICE"
        )
        assert validate_success(api.get_unit(unit_b["id"], OPERATOR))["status"] == (
            "OUT_OF_SERVICE"
        )

        assert fx.read_subscription(api, env.subscription_id)["status"] == "SUSPENDED"

    def test_cancelling_the_only_subscription_frees_the_unit_and_the_resident(self, api):
        """
        Cancelling the resident's only subscription lets two ancestors re-derive
        themselves: the unit falls back to AVAILABLE and the resident reaches the
        terminal MOVED_OUT, each with exactly one version increment, while the
        subscription's own rows expire and its scheduled shipment is cancelled.

        PRD §3.9: "The resident moves `RESIDING → MOVED_OUT` only when no other subscription of that resident remains in `PENDING_SETUP`, `ACTIVE`, `SUSPENDED` or `TRANSFER_PENDING`; this is precisely why a cancellation produced by a completed transfer leaves the resident `RESIDING`, since the successor subscription is already `ACTIVE`."

        Design: Corner/state_machines/unit_returns_to_available_when_last_subscription_cancelled
        """
        env = fx.build_base_env(api)
        shipment = fx.first_shipment(api, env.subscription_id)
        unit_before = validate_success(api.get_unit(env.unit_id, OPERATOR))
        resident_before = validate_success(api.get_resident(env.resident_id, OPERATOR))
        assert unit_before["status"] == "OCCUPIED"
        assert resident_before["status"] == "RESIDING"
        fx.set_clock(api, "2026-09-11T00:00:00Z")

        cancelled = validate_success(
            api.cancel_subscription(
                env.subscription_id,
                f.cancel_payload("2026-09-11", "Lease terminated early"),
                OPERATOR,
            )
        )
        assert cancelled["status"] == "CANCELLED"
        assert cancelled["cancel_effective_date"] == "2026-09-11"

        unit_after = validate_success(api.get_unit(env.unit_id, OPERATOR))
        assert unit_after["status"] == "AVAILABLE"
        assert unit_after["version"] == unit_before["version"] + 1

        resident_after = validate_success(api.get_resident(env.resident_id, OPERATOR))
        assert resident_after["status"] == "MOVED_OUT"
        assert resident_after["version"] == resident_before["version"] + 1

        for row in fx.read_entitlements(api, env.subscription_id):
            a.assert_entitlement(row, "EXPIRED", forfeit_reason="SUBSCRIPTION_CANCELLED")
        assert validate_success(api.get_shipment(shipment["id"], OPERATOR))["status"] == (
            "CANCELLED"
        )
