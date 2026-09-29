"""Lifecycle transitions: openings, side effects, refusals and cascades.

Each entity here has one legal path in and several illegal ones. The refusals
must leave the world exactly as they found it, and the legal moves must carry
out every side effect the contract attaches to them.
"""

from prd_bench_local_runner.testing import validate_error, validate_success

from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.api_errors import ERR_INVALID_STATE, ERR_PSM_REVIEW_MISSING
from test_helpers.assertions import (
    assert_freight_breakdown,
    assert_gas_price,
    assert_hours,
    assert_integer,
    assert_mmbtu,
    assert_money,
    assert_position,
    assert_status,
    assert_tons,
)
from test_helpers.test_users import (
    ADMIN,
    COMMERCIAL,
    ENG_APPROVER,
    ENG_AUTHOR,
    ENGINEER,
    LOGISTICS_HEADERS,
    SO_APPROVER,
    SO_REVIEWER,
    make_process_engineer_headers,
    make_safety_officer_headers,
    make_terminal_operator_headers,
)


class TestCampaignCannotStartUnapproved:
    def test_starting_a_merely_planned_campaign_is_refused(self, api):
        """A campaign must be approved before it can be put on line.

        Design: Corner/state_machines/start_a_planned_run_before_approval_is_rejected
        """
        site = fx.commissioned_site(
            api,
            rated_ammonia_tpd=1200.0,
            design_life_hours=40000.0,
            baseline_operating_hours=0.0,
            poisoning_index=0.00,
        )
        run = fx.schedule_run(
            api,
            site["train"]["id"],
            window_start="2026-09-01T00:00:00.000Z",
            window_end="2026-09-11T00:00:00.000Z",
            target_ammonia_tons=1000.000,
        )

        response = api.start_production_run(
            run["id"], make_process_engineer_headers(ENG_AUTHOR)
        )
        validate_error(response, ERR_INVALID_STATE, 409)

        blocked = validate_success(api.get_production_run(run["id"], ENGINEER))
        assert_status(blocked, "PLANNED", label="run")
        assert blocked["provisional_unit_cost_usd_per_ton"] is None

        train = validate_success(
            api.get_reformer_train(site["train"]["id"], ENGINEER)
        )
        assert_status(train, "IDLE", label="train")


class TestCampaignApprovalIsNotRepeatable:
    def test_approving_twice_is_refused_and_bumps_nothing(self, api):
        """The second approval is an illegal transition, not a no-op.

        Design: Corner/state_machines/approving_an_already_approved_run_is_rejected
        """
        site = fx.commissioned_site(
            api,
            rated_ammonia_tpd=1200.0,
            design_life_hours=40000.0,
            baseline_operating_hours=0.0,
            poisoning_index=0.00,
        )
        run = fx.approved_run(
            api,
            site["train"]["id"],
            author=ENG_AUTHOR,
            approver=ENG_APPROVER,
            window_start="2026-09-01T00:00:00.000Z",
            window_end="2026-09-11T00:00:00.000Z",
            target_ammonia_tons=1000.000,
        )
        settled_version = run["version"]

        response = api.approve_production_run(
            run["id"], make_process_engineer_headers(ENG_APPROVER)
        )
        validate_error(response, ERR_INVALID_STATE, 409)

        unchanged = validate_success(api.get_production_run(run["id"], ENGINEER))
        assert_status(unchanged, "APPROVED", label="run")
        assert unchanged["version"] == settled_version, (
            f"expected version {settled_version}, got {unchanged['version']}"
        )


class TestCampaignStartSideEffects:
    def test_starting_a_campaign_claims_its_train_and_its_charge(self, api):
        """The campaign records the charge it will consume and prices itself.

        Design: Corner/state_machines/run_start_sets_train_running_and_stamps_the_charge
        """
        site = fx.commissioned_site(
            api,
            spot_gas_index_usd_per_mmbtu=4.2000,
            rated_ammonia_tpd=1200.0,
            design_life_hours=40000.0,
            baseline_operating_hours=0.0,
            poisoning_index=0.00,
        )
        run = fx.approved_run(
            api,
            site["train"]["id"],
            author=ENG_AUTHOR,
            approver=ENG_APPROVER,
            window_start="2026-09-01T00:00:00.000Z",
            window_end="2026-09-11T00:00:00.000Z",
            target_ammonia_tons=1000.000,
        )
        fx.set_clock(api, "2026-09-01T00:00:00Z")

        response = api.start_production_run(
            run["id"], make_process_engineer_headers(ENG_AUTHOR)
        )
        started = validate_success(response, 200)

        assert_status(started, "RUNNING", label="run")
        assert started["catalyst_charge_id"] == site["charge"]["id"]
        assert_money(
            started["provisional_unit_cost_usd_per_ton"],
            181.10,
            "run.provisional_unit_cost_usd_per_ton",
        )
        assert started["final_unit_cost_usd_per_ton"] is None
        assert_mmbtu(started["consumed_gas_mmbtu"], 0, "run.consumed_gas_mmbtu")

    def test_starting_a_campaign_does_not_yet_wear_the_charge(self, api):
        """The train is on line but no operating hours have been clocked.

        Design: Corner/state_machines/run_start_sets_train_running_and_stamps_the_charge
        """
        site = fx.commissioned_site(
            api,
            spot_gas_index_usd_per_mmbtu=4.2000,
            rated_ammonia_tpd=1200.0,
            design_life_hours=40000.0,
            baseline_operating_hours=0.0,
            poisoning_index=0.00,
        )
        fx.running_run(
            api,
            site["train"]["id"],
            clock_at="2026-09-01T00:00:00Z",
            author=ENG_AUTHOR,
            approver=ENG_APPROVER,
            window_start="2026-09-01T00:00:00.000Z",
            window_end="2026-09-11T00:00:00.000Z",
            target_ammonia_tons=1000.000,
        )

        train = validate_success(
            api.get_reformer_train(site["train"]["id"], ENGINEER)
        )
        assert_status(train, "RUNNING", label="train")

        charge = validate_success(
            api.get_catalyst_charge(site["charge"]["id"], ENGINEER)
        )
        assert_status(charge, "ACTIVE", label="charge")
        assert_hours(
            charge["cumulative_operating_hours"],
            0,
            "charge.cumulative_operating_hours",
        )


class TestOutageOpening:
    def test_a_new_outage_opens_as_an_unreviewed_draft(self, api):
        """An authored outage carries its window arithmetic and nothing else.

        Design: Corner/state_machines/new_turnaround_starts_in_draft_with_no_psm_review
        """
        plant = fx.register_plant(api)
        train = fx.commission_train(api, plant["id"], rated_ammonia_tpd=1200.0)

        response = api.create_turnaround(
            f.turnaround_payload(
                plant["id"],
                train["id"],
                scope="VESSEL_INSPECTION",
                window_start="2026-10-01T00:00:00.000Z",
                window_end="2026-10-27T00:00:00.000Z",
            ),
            make_process_engineer_headers(ENG_AUTHOR),
        )
        outage = validate_success(response, 201)

        assert_status(outage, "DRAFT", label="turnaround")
        assert_status(outage, "NONE", field="psm_review_decision", label="turnaround")
        assert outage["psm_reviewed_by_user_id"] is None
        assert outage["approved_by_user_id"] is None
        assert outage["authored_by_user_id"] == ENG_AUTHOR
        assert_integer(outage["window_days"], 26, "turnaround.window_days")
        assert_integer(outage["critical_path_days"], 0, "turnaround.critical_path_days")
        assert_integer(outage["tasks_total_count"], 0, "turnaround.tasks_total_count")
        assert_integer(outage["tasks_done_count"], 0, "turnaround.tasks_done_count")

        idle = validate_success(api.get_reformer_train(train["id"], ENGINEER))
        assert_status(idle, "IDLE", label="train")


class TestOutageApprovalNeedsItsSafetyReview:
    def _submitted_outage(self, api):
        plant = fx.register_plant(api)
        train = fx.commission_train(api, plant["id"], rated_ammonia_tpd=1200.0)
        outage = fx.author_turnaround(
            api,
            plant["id"],
            train["id"],
            author=ENG_AUTHOR,
            scope="VESSEL_INSPECTION",
            window_start="2026-10-01T00:00:00.000Z",
            window_end="2026-10-27T00:00:00.000Z",
        )
        task = fx.add_task(api, outage["id"], 5)
        fx.submit_turnaround(api, outage["id"], actor=ENG_AUTHOR)
        return {"plant": plant, "train": train, "outage": outage, "task": task}

    def test_an_unreviewed_outage_cannot_be_approved(self, api):
        """Approval has a safety review as a hard precondition.

        Design: Corner/state_machines/turnaround_approve_without_endorsed_psm_review_is_rejected
        """
        world = self._submitted_outage(api)

        response = api.approve_turnaround(
            world["outage"]["id"], make_safety_officer_headers(SO_APPROVER)
        )
        validate_error(response, ERR_PSM_REVIEW_MISSING, 409)

        outage = validate_success(api.get_turnaround(world["outage"]["id"], ENGINEER))
        assert_status(outage, "SUBMITTED", label="turnaround")
        assert_status(outage, "NONE", field="psm_review_decision", label="turnaround")
        assert outage["approved_by_user_id"] is None

        task = validate_success(api.get_turnaround_task(world["task"]["id"], ENGINEER))
        assert_status(task, "PENDING", label="task")

    def test_an_endorsed_outage_is_approved_with_its_third_signature(self, api):
        """Approval records the approver and keeps the review it inherited.

        Design: Corner/state_machines/turnaround_approve_arm_stamps_approver_and_leaves_tasks_pending
        """
        world = self._submitted_outage(api)
        fx.psm_review(
            api,
            world["outage"]["id"],
            decision="ENDORSED",
            findings_count=2,
            reviewer=SO_REVIEWER,
        )

        response = api.approve_turnaround(
            world["outage"]["id"], make_safety_officer_headers(SO_APPROVER)
        )
        approved = validate_success(response, 200)

        assert_status(approved, "APPROVED", label="turnaround")
        assert_status(
            approved, "ENDORSED", field="psm_review_decision", label="turnaround"
        )
        assert approved["psm_reviewed_by_user_id"] == SO_REVIEWER
        assert_integer(approved["psm_findings_count"], 2, "turnaround.psm_findings_count")
        assert approved["approved_by_user_id"] == SO_APPROVER
        assert approved["rejection_reason"] is None
        assert_integer(approved["critical_path_days"], 5, "turnaround.critical_path_days")
        assert_integer(approved["window_days"], 26, "turnaround.window_days")

    def test_approval_alone_does_not_open_the_task_graph(self, api):
        """The single step is still pending and the train is still idle.

        Design: Corner/state_machines/turnaround_approve_arm_stamps_approver_and_leaves_tasks_pending
        """
        world = self._submitted_outage(api)
        fx.psm_review(
            api,
            world["outage"]["id"],
            decision="ENDORSED",
            findings_count=2,
            reviewer=SO_REVIEWER,
        )
        approved = fx.approve_turnaround(api, world["outage"]["id"])

        task = validate_success(api.get_turnaround_task(world["task"]["id"], ENGINEER))
        assert_status(task, "PENDING", label="task")
        assert_integer(task["earliest_start_day"], 0, "task.earliest_start_day")
        assert_integer(approved["tasks_total_count"], 1, "turnaround.tasks_total_count")
        assert_integer(approved["tasks_done_count"], 0, "turnaround.tasks_done_count")

        train = validate_success(api.get_reformer_train(world["train"]["id"], ENGINEER))
        assert_status(train, "IDLE", label="train")


class TestShipmentDelivery:
    def _departed_movement(self, api):
        plant = fx.register_plant(api)
        fx.define_product_line(
            api,
            plant["id"],
            product_code="UREA",
            ammonia_tons_per_product_ton=0.580,
            conversion_cost_usd_per_ton=38.000,
            regulated=False,
            priority_rank=1,
        )
        pair = fx.terminal_pair(
            api,
            plant["id"],
            product_code="UREA",
            capacity_tons=20000.000,
            security_class="BASIC",
            seasonal_reserve_pct=0.00,
            origin_opening_tons=1000.000,
        )
        shipment = fx.draft_shipment(
            api,
            pair["origin"]["id"],
            pair["dest"]["id"],
            mode="RAIL",
            tons=100.000,
            distance_miles=100.0,
            window_start="2026-08-05T00:00:00.000Z",
            window_end="2026-08-10T00:00:00.000Z",
        )
        fx.book_shipment(api, shipment["id"], pair["origin"]["id"])
        # PRD 3.7: departure requires the logical clock to have reached
        # window_start, so the clock is moved onto the occupation window first.
        fx.set_clock(api, "2026-08-05T00:00:00Z")
        fx.depart_shipment(api, shipment["id"])
        return {"pair": pair, "shipment": shipment}

    def test_receipt_closes_the_movement_at_its_booked_freight(self, api):
        """The received tonnage is recorded and the freight is left as booked.

        Design: Corner/state_machines/shipment_deliver_moves_tons_from_origin_to_destination
        """
        world = self._departed_movement(api)

        response = api.deliver_shipment(
            world["shipment"]["id"],
            98.000,
            make_terminal_operator_headers(world["pair"]["dest"]["id"]),
        )
        delivered = validate_success(response, 200)

        assert_status(delivered, "DELIVERED", label="shipment")
        assert_tons(delivered["received_tons"], 98.000, "shipment.received_tons")
        assert_freight_breakdown(
            delivered,
            base=2200.00,
            surcharge=187.00,
            total=2387.00,
            per_ton=23.8700,
            label="shipment",
        )

    def test_receipt_moves_the_tons_off_the_origin_and_onto_the_receiver(self, api):
        """The origin loses the booked tonnage and the receiver gains what arrived.

        Design: Corner/state_machines/shipment_deliver_moves_tons_from_origin_to_destination
        """
        world = self._departed_movement(api)
        fx.deliver_shipment(
            api, world["shipment"]["id"], world["pair"]["dest"]["id"], 98.000
        )

        origin = validate_success(
            api.get_storage_asset(world["pair"]["origin"]["id"], LOGISTICS_HEADERS)
        )
        assert_position(
            origin, on_hand=900.000, reserved=0.000, available=900.000, label="origin"
        )

        dest = validate_success(
            api.get_storage_asset(world["pair"]["dest"]["id"], LOGISTICS_HEADERS)
        )
        assert_position(dest, on_hand=98.000, available=98.000, label="destination")

    def test_a_delivered_movement_can_no_longer_be_cancelled(self, api):
        """Delivery is terminal, so the cancellation is an illegal transition.

        Design: Corner/state_machines/cancel_a_delivered_shipment_is_rejected
        """
        world = self._departed_movement(api)
        fx.deliver_shipment(
            api, world["shipment"]["id"], world["pair"]["dest"]["id"], 98.000
        )

        response = api.cancel_shipment(
            world["shipment"]["id"], "CUSTOMER_CANCELLED", LOGISTICS_HEADERS
        )
        validate_error(response, ERR_INVALID_STATE, 409)

        shipment = validate_success(
            api.get_shipment(world["shipment"]["id"], LOGISTICS_HEADERS)
        )
        assert_status(shipment, "DELIVERED", label="shipment")
        assert shipment["cancel_reason"] is None

    def test_the_refused_cancellation_moves_no_tons_back(self, api):
        """Both positions stand exactly as the delivery left them.

        Design: Corner/state_machines/cancel_a_delivered_shipment_is_rejected
        """
        world = self._departed_movement(api)
        fx.deliver_shipment(
            api, world["shipment"]["id"], world["pair"]["dest"]["id"], 98.000
        )
        validate_error(
            api.cancel_shipment(
                world["shipment"]["id"], "CUSTOMER_CANCELLED", LOGISTICS_HEADERS
            ),
            ERR_INVALID_STATE,
            409,
        )

        dest = validate_success(
            api.get_storage_asset(world["pair"]["dest"]["id"], LOGISTICS_HEADERS)
        )
        assert_position(dest, on_hand=98.000, label="destination")

        origin = validate_success(
            api.get_storage_asset(world["pair"]["origin"]["id"], LOGISTICS_HEADERS)
        )
        assert_position(origin, on_hand=900.000, label="origin")


class TestFreezingThePlantStopsCampaignApprovals:
    def _two_train_world(self, api):
        site = fx.two_train_site(
            api,
            spot_gas_index_usd_per_mmbtu=4.2000,
            rated_ammonia_tpd=1200.0,
            design_life_hours=40000.0,
            baseline_operating_hours=0.0,
            poisoning_index=0.00,
        )
        approved = fx.approved_run(
            api,
            site["train"]["id"],
            author=ENG_AUTHOR,
            approver=ENG_APPROVER,
            window_start="2026-09-01T00:00:00.000Z",
            window_end="2026-09-11T00:00:00.000Z",
            target_ammonia_tons=1000.000,
        )
        live = fx.running_run(
            api,
            site["train_b"]["id"],
            clock_at="2026-09-01T00:00:00Z",
            author=ENG_AUTHOR,
            approver=ENG_APPROVER,
            window_start="2026-09-01T00:00:00.000Z",
            window_end="2026-09-11T00:00:00.000Z",
            target_ammonia_tons=1000.000,
        )
        site["approved"] = approved
        site["live"] = live
        return site

    def test_suspending_the_permit_freezes_the_plant(self, api):
        """A suspended permit reads through to a frozen posture at once.

        Design: Corner/state_machines/frozen_posture_reverts_approved_runs_but_leaves_running_ones
        """
        world = self._two_train_world(api)

        response = api.post_permit_status(
            world["plant"]["id"], "SUSPENDED", ADMIN
        )
        frozen = validate_success(response, 200)

        assert_status(frozen, "SUSPENDED", field="permit_status", label="plant")
        assert_status(frozen, "FROZEN", field="operating_posture", label="plant")

    def test_the_freeze_takes_back_the_approval_but_spares_the_live_campaign(self, api):
        """An approved campaign reverts while a running one is left alone.

        Design: Corner/state_machines/frozen_posture_reverts_approved_runs_but_leaves_running_ones
        """
        world = self._two_train_world(api)
        validate_success(
            api.post_permit_status(world["plant"]["id"], "SUSPENDED", ADMIN), 200
        )

        reverted = validate_success(
            api.get_production_run(world["approved"]["id"], ENGINEER)
        )
        assert_status(reverted, "PLANNED", label="approved campaign")

        live = validate_success(api.get_production_run(world["live"]["id"], ENGINEER))
        assert_status(live, "RUNNING", label="live campaign")

        idle = validate_success(
            api.get_reformer_train(world["train"]["id"], ENGINEER)
        )
        assert_status(idle, "IDLE", label="first train")

        busy = validate_success(
            api.get_reformer_train(world["train_b"]["id"], ENGINEER)
        )
        assert_status(busy, "RUNNING", label="second train")


class TestOverduePsmProgramWithdrawsIssuedQuotes:
    def _quoted_world(self, api):
        plant = fx.register_plant(api, spot_gas_index_usd_per_mmbtu=4.2000)
        line = fx.define_product_line(
            api,
            plant["id"],
            product_code="UREA",
            ammonia_tons_per_product_ton=0.580,
            conversion_cost_usd_per_ton=38.000,
            regulated=False,
            priority_rank=1,
        )
        quote = fx.issued_quote(
            api,
            plant["id"],
            line["id"],
            tons=6000.000,
            pass_through_basis="HEDGED_BLEND",
            expires_at="2027-04-15T00:00:00.000Z",
        )
        return {"plant": plant, "line": line, "quote": quote}

    def test_an_overdue_safety_programme_restricts_the_plant(self, api):
        """The posture drops on a safety finding, with no pollutant named.

        Design: Corner/state_machines/issued_quote_withdrawn_when_psm_program_goes_overdue
        """
        world = self._quoted_world(api)

        response = api.post_psm_program_status(
            world["plant"]["id"], "OVERDUE", make_safety_officer_headers(SO_APPROVER)
        )
        restricted = validate_success(response, 200)

        assert_status(
            restricted, "OVERDUE", field="psm_program_status", label="plant"
        )
        assert_status(
            restricted, "RESTRICTED", field="operating_posture", label="plant"
        )
        assert restricted["exceeded_pollutants"] == []

    def test_the_restriction_withdraws_the_quote_it_had_already_issued(self, api):
        """The quote is pulled but keeps the price and basis it was issued at.

        Design: Corner/state_machines/issued_quote_withdrawn_when_psm_program_goes_overdue
        """
        world = self._quoted_world(api)
        validate_success(
            api.post_psm_program_status(
                world["plant"]["id"],
                "OVERDUE",
                make_safety_officer_headers(SO_APPROVER),
            ),
            200,
        )

        quote = validate_success(
            api.get_price_quote(world["quote"]["id"], COMMERCIAL)
        )
        assert_status(quote, "WITHDRAWN", label="quote")
        assert quote["withdraw_reason"] == "PLANT_POSTURE_DEGRADED"
        assert_money(
            quote["quoted_price_usd_per_ton"], 199.74, "quote.quoted_price_usd_per_ton"
        )
        assert_gas_price(
            quote["gas_basis_usd_per_mmbtu"], 4.2000, "quote.gas_basis_usd_per_mmbtu"
        )
