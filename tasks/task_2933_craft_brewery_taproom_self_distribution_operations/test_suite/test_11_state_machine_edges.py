"""Declared edges, terminal lockdowns, initial states and the side effects each edge owes."""

from test_helpers import (
    ADMIN,
    APPT_ACTIVE,
    APPT_TERMINATION_REQUESTED,
    BATCH_BREWING,
    BATCH_SCHEDULED,
    CELLAR,
    COMPLIANCE,
    DESTINATION_DISTRIBUTION,
    DESTINATION_TAPROOM,
    ERR_BATCH_TRANSITION_INVALID,
    ERR_NOTICE_TRANSITION_INVALID,
    ERR_RUN_NOT_COMPLETED,
    GOOD_CAUSE_NONPAYMENT,
    KEG_CLEANED,
    KEG_SIZE_HALF_BBL,
    LICENSE_ACTIVE,
    LICENSE_EXPIRED,
    LICENSE_SELF_DISTRIBUTION,
    LICENSE_SUSPENDED,
    LICENSE_WHOLESALER_ONLY,
    NOTICE_ACTION_ACTIVATE,
    NOTICE_ACTION_REINSTATE,
    NOTICE_ACTION_REVOKE,
    NOTICE_ACTIVE,
    NOTICE_REVOKED,
    ORDER_CHANNEL_SELF_DISTRIBUTED,
    ORDER_REJECTED,
    ORDER_SUBMITTED,
    PACKAGE_HALF_BBL_KEG,
    RECON_NOT_APPLICABLE,
    REGULATOR,
    REJECTION_LICENSE_NOT_ACTIVE,
    RUN_PLANNED,
    SCOPE_ALL_BRANDS,
    TANK_IDLE,
    TANK_OCCUPIED,
    TERMINATION_REQUEST,
    TERMINATION_WITHDRAW,
    assert_bbl,
    assert_cents,
    assert_instant_equals,
    assert_oz,
    condition_payload,
    keg_fill_payload,
    notice_payload,
    order_payload,
    termination_payload,
    validate_error,
    validate_success,
)
from test_helpers.fixtures import (
    bootstrap_brewery,
    create_active_appointment,
    create_allocated_order,
    create_cleaned_keg,
    create_completed_run,
    create_conditioning_batch,
    create_distribution_ready_beer,
    create_exempt_beer,
    create_license,
    create_scheduled_batch,
    create_tank,
    plan_run,
    set_clock,
    suspend_notice,
)

DEFAULT_CLOCK = "2026-08-01T00:00:00Z"


class TestUndeclaredEdges:
    def test_conditioning_a_batch_that_never_brewed_is_refused(self, api):
        """condition is declared only from BREWING, and the refusal writes no yield.

        PRD §3.2: "`DUMPED` is terminal, and any of start, condition or dump
        attempted from a state that does not declare it — including anything at all
        from `PACKAGED` or `DUMPED` — is refused with
        `ERR_BATCH_TRANSITION_INVALID`."

        Design: Corner/state_machines/condition_a_scheduled_batch_returns_batch_transition_invalid
        """
        bootstrap_brewery(api)
        beer = create_exempt_beer(api, name="Ridgeline IPA")
        tank = create_tank(api, code="FV-01", capacity_bbl=30.00)
        batch = create_scheduled_batch(
            api,
            beer["id"],
            tank["id"],
            batch_code="B-1001",
            planned_volume_bbl=16.00,
            brew_start_utc="2026-08-01T06:00:00Z",
            brew_end_utc="2026-08-08T06:00:00Z",
        )

        validate_error(
            api.condition_batch(batch["id"], condition_payload(16.000), CELLAR),
            ERR_BATCH_TRANSITION_INVALID,
            409,
        )

        stored = validate_success(api.get_batch(batch["id"], CELLAR))
        assert stored["state"] == BATCH_SCHEDULED
        assert stored["actual_yield_bbl"] is None
        assert stored["version"] == 1
        assert validate_success(api.get_tank(tank["id"], CELLAR))["status"] == TANK_IDLE

    def test_replaying_activate_on_a_live_notice_is_refused(self, api):
        """The second ACTIVATE is an error, not a no-op, and re-stamps nothing.

        PRD §3.1: "An action that the current `notice_status` does not declare —
        `REVOKE` straight from `ACTIVE`, `ACTIVATE` on an already-active notice,
        anything at all from `REVOKED` — is refused with
        `ERR_NOTICE_TRANSITION_INVALID`."

        Design: Corner/state_machines/second_activate_of_brewers_notice_is_refused
        """
        activated = bootstrap_brewery(api)
        version_when_active = activated["version"]
        set_clock(api, "2026-08-05T00:00:00Z")

        validate_error(
            api.drive_notice(notice_payload(NOTICE_ACTION_ACTIVATE), REGULATOR),
            ERR_NOTICE_TRANSITION_INVALID,
            409,
        )

        stored = validate_success(api.get_brewery(ADMIN))
        assert stored["notice_status"] == NOTICE_ACTIVE
        assert_instant_equals(
            stored["notice_effective_utc"], DEFAULT_CLOCK, "notice_effective_utc"
        )
        assert stored["version"] == version_when_active


class TestTerminalLockdown:
    def test_a_revoked_notice_cannot_be_reinstated(self, api):
        """REVOKED admits no action, and its licences stay suspended one hop away.

        PRD §3.1: "`REVOKE` takes `SUSPENDED` to `REVOKED` and likewise requires a
        non-blank `reason`, stored as `suspension_reason`; `REVOKED` is terminal,
        and once reached no notice action of any kind is legal again."

        Design: Corner/state_machines/reinstate_after_revoked_notice_is_refused
        """
        bootstrap_brewery(api, home_state_code="OR")
        license_row = create_license(
            api,
            "ID",
            LICENSE_SELF_DISTRIBUTION,
            annual_barrel_cap=1000.00,
            effective_from_utc="2026-01-01T00:00:00Z",
            expires_at_utc="2027-01-01T00:00:00Z",
        )
        suspend_notice(api, reason="records audit opened by the state")
        revocation_reason = "notice surrendered after repeat findings"
        validate_success(
            api.drive_notice(
                notice_payload(NOTICE_ACTION_REVOKE, reason=revocation_reason), REGULATOR
            )
        )

        validate_error(
            api.drive_notice(notice_payload(NOTICE_ACTION_REINSTATE), REGULATOR),
            ERR_NOTICE_TRANSITION_INVALID,
            409,
        )

        stored = validate_success(api.get_brewery(ADMIN))
        assert stored["notice_status"] == NOTICE_REVOKED
        assert stored["suspension_reason"] == revocation_reason
        assert (
            validate_success(api.get_state_license(license_row["id"], REGULATOR))["status"]
            == LICENSE_SUSPENDED
        )


class TestInitialState:
    def test_a_new_order_opens_submitted_with_nothing_reserved(self, api):
        """The landed cost is already frozen while the ledger fields are still empty.

        PRD §3.7: "The order opens in `state` `SUBMITTED` with an empty
        `allocation_lines` list, an `allocated_bbl` of 0.000, and null
        `rejection_reason`, `cancel_reason` and `shipped_at_utc`."

        Design: Corner/state_machines/new_distribution_order_starts_submitted_with_an_empty_allocation
        """
        bootstrap_brewery(api, home_state_code="OR")
        beer = create_distribution_ready_beer(
            api, name="Ridgeline IPA", abv_pct=6.8, price_per_bbl_cents=42000
        )
        license_row = create_license(
            api,
            "ID",
            LICENSE_SELF_DISTRIBUTION,
            annual_barrel_cap=1000.00,
            franchise_state=False,
            effective_from_utc="2026-01-01T00:00:00Z",
            expires_at_utc="2027-01-01T00:00:00Z",
        )

        order = validate_success(
            api.create_distribution_order(
                order_payload(
                    beer["id"],
                    license_row["id"],
                    bbl_requested=2.00,
                    ship_to_state_code="ID",
                    distance_miles=100,
                    requested_ship_utc="2026-08-15T15:00:00Z",
                    order_code="SO-5001",
                ),
                ADMIN,
            ),
            201,
        )

        assert order["state"] == ORDER_SUBMITTED
        assert order["channel"] == ORDER_CHANNEL_SELF_DISTRIBUTED
        assert order["appointment_id"] is None
        assert_bbl(order["allocated_bbl"], 0.000, "allocated_bbl")
        assert order["allocation_lines"] == []
        assert order["rejection_reason"] is None
        assert order["cancel_reason"] is None
        assert order["shipped_at_utc"] is None
        assert_cents(order["product_cents"], 84000, "product_cents")
        assert_cents(order["franchise_fee_cents"], 0, "franchise_fee_cents")
        assert order["version"] == 1


class TestCrossEntityPreconditions:
    def test_a_keg_cannot_be_filled_from_a_run_that_has_not_been_certified(self, api):
        """A PLANNED run holds no beer, so the fill is refused and nothing moves.

        PRD §3.4: "The cited run's `state` must be `COMPLETED` — a run still in
        `PLANNED` has no beer yet and a run in `VOIDED` never will, and either is
        refused with `ERR_RUN_NOT_COMPLETED`."

        Design: Corner/state_machines/keg_fill_from_a_planned_run_returns_run_not_completed
        """
        bootstrap_brewery(api)
        beer = create_exempt_beer(api, name="Ridgeline IPA")
        tank = create_tank(api, code="FV-01", capacity_bbl=30.00)
        batch = create_conditioning_batch(
            api,
            beer["id"],
            tank["id"],
            actual_yield_bbl=16.000,
            batch_code="B-1001",
            planned_volume_bbl=16.00,
            brew_start_utc="2026-08-01T06:00:00Z",
            brew_end_utc="2026-08-08T06:00:00Z",
        )
        run = plan_run(
            api,
            batch["id"],
            package_type=PACKAGE_HALF_BBL_KEG,
            destination=DESTINATION_TAPROOM,
            units_planned=10,
            run_code="R-TAP-1",
        )
        keg = create_cleaned_keg(api, KEG_SIZE_HALF_BBL, keg_serial="KEG-0001")

        validate_error(
            api.fill_keg_asset(keg["id"], keg_fill_payload(run["id"]), CELLAR),
            ERR_RUN_NOT_COMPLETED,
            409,
        )

        stored_keg = validate_success(api.get_keg_asset(keg["id"], CELLAR))
        assert stored_keg["state"] == KEG_CLEANED
        assert stored_keg["packaging_run_id"] is None
        assert_oz(stored_keg["filled_volume_oz"], 0.00, "filled_volume_oz")
        stored_run = validate_success(api.get_packaging_run(run["id"], CELLAR))
        assert stored_run["state"] == RUN_PLANNED
        assert stored_run["reconciliation_state"] == RECON_NOT_APPLICABLE
        assert stored_run["kegs_filled_count"] == 0


class TestSideEffectExecution:
    def test_starting_a_brew_takes_the_vessel_and_names_its_occupant(self, api):
        """Both rows move in the one request, and the start is not a wash.

        PRD §3.2: "Across the two rows, the vessel moves `IDLE → OCCUPIED` with its
        `occupying_batch_id` set to the starting batch, and both the batch's
        `version` and the tank's `version` increment by 1."

        Design: Corner/state_machines/batch_start_marks_the_tank_occupied_and_records_the_occupant
        """
        bootstrap_brewery(api)
        beer = create_exempt_beer(api, name="Ridgeline IPA")
        tank = create_tank(api, code="FV-01", capacity_bbl=30.00)
        batch = create_scheduled_batch(
            api,
            beer["id"],
            tank["id"],
            batch_code="B-1001",
            planned_volume_bbl=16.00,
            brew_start_utc="2026-08-01T06:00:00Z",
            brew_end_utc="2026-08-08T06:00:00Z",
        )
        batch_version_before = batch["version"]
        tank_version_before = tank["version"]

        started = validate_success(api.start_batch(batch["id"], CELLAR))

        assert started["state"] == BATCH_BREWING
        assert started["version"] > batch_version_before
        stored_tank = validate_success(api.get_tank(tank["id"], CELLAR))
        assert stored_tank["status"] == TANK_OCCUPIED
        assert stored_tank["occupying_batch_id"] == batch["id"]
        assert stored_tank["version"] > tank_version_before
        assert stored_tank["last_cip_utc"] is None
        assert stored_tank["cip_cycle_count"] == 0


class TestGuardedTransitions:
    def test_merely_reading_a_lapsed_licence_expires_it_and_rejects_its_order(self, api):
        """The read performs the transition and releases the reserved barrels.

        PRD §3.6: "`ACTIVE → EXPIRED` is **lazy**: the system re-evaluates expiry on
        any request that reads the licence, and when the logical clock has reached
        or passed `expires_at_utc` the licence moves to `EXPIRED`, at which point
        every distribution order citing it whose `state` is `SUBMITTED` or
        `ALLOCATED` moves to `REJECTED` with `rejection_reason` `LICENSE_NOT_ACTIVE`,
        and each released allocation entry decrements the cited run's
        `allocated_bbl` while incrementing its `available_bbl`."

        Design: Corner/state_machines/license_lazy_expiry_on_read_rejects_its_allocated_order
        """
        bootstrap_brewery(api, home_state_code="OR")
        beer = create_distribution_ready_beer(
            api, name="Ridgeline IPA", abv_pct=6.8, price_per_bbl_cents=42000
        )
        license_row = create_license(
            api,
            "ID",
            LICENSE_SELF_DISTRIBUTION,
            annual_barrel_cap=1000.00,
            franchise_state=False,
            effective_from_utc="2026-01-01T00:00:00Z",
            expires_at_utc="2026-08-10T00:00:00Z",
        )
        tank = create_tank(api, code="FV-01", capacity_bbl=30.00)
        batch = create_conditioning_batch(
            api,
            beer["id"],
            tank["id"],
            actual_yield_bbl=16.000,
            batch_code="B-1001",
            planned_volume_bbl=16.00,
            brew_start_utc="2026-08-01T06:00:00Z",
            brew_end_utc="2026-08-08T06:00:00Z",
        )
        run = create_completed_run(
            api,
            batch["id"],
            package_type=PACKAGE_HALF_BBL_KEG,
            destination=DESTINATION_DISTRIBUTION,
            units_planned=10,
            run_code="R-DIST-1",
        )
        order = create_allocated_order(
            api,
            beer["id"],
            license_row["id"],
            bbl_requested=3.00,
            ship_to_state_code="ID",
            distance_miles=120,
            requested_ship_utc="2026-08-09T15:00:00Z",
            order_code="SO-5002",
        )
        set_clock(api, "2026-08-10T00:00:00Z")

        expired = validate_success(api.get_state_license(license_row["id"], COMPLIANCE))

        assert expired["status"] == LICENSE_EXPIRED
        stored_order = validate_success(api.get_distribution_order(order["id"], ADMIN))
        assert stored_order["state"] == ORDER_REJECTED
        assert stored_order["rejection_reason"] == REJECTION_LICENSE_NOT_ACTIVE
        assert stored_order["allocation_lines"] == []
        assert_bbl(stored_order["allocated_bbl"], 0.000, "allocated_bbl")
        stored_run = validate_success(api.get_packaging_run(run["id"], CELLAR))
        assert_bbl(stored_run["allocated_bbl"], 0.000, "allocated_bbl")
        assert_bbl(stored_run["available_bbl"], 5.000, "available_bbl")


class TestCompensatingPhase:
    def test_withdrawing_a_termination_leaves_no_notice_residue(self, api):
        """The appointment returns to ACTIVE with all three notice fields cleared.

        PRD §3.6: "A `WITHDRAW` is legal only from `TERMINATION_REQUESTED` and
        returns the appointment to `ACTIVE`, clearing `termination_requested_at_utc`,
        `termination_effective_utc` and `good_cause_code`."

        Design: Corner/state_machines/appointment_termination_withdraw_restores_active_and_clears_notice_timestamps
        """
        bootstrap_brewery(api, home_state_code="OR")
        license_row = create_license(
            api,
            "WA",
            LICENSE_WHOLESALER_ONLY,
            annual_barrel_cap=0.00,
            franchise_state=True,
            termination_notice_days=90,
            effective_from_utc="2026-01-01T00:00:00Z",
            expires_at_utc="2027-01-01T00:00:00Z",
        )
        appointment = create_active_appointment(
            api, license_row["id"], brand_scope=SCOPE_ALL_BRANDS
        )
        requested = validate_success(
            api.terminate_appointment(
                appointment["id"],
                termination_payload(
                    TERMINATION_REQUEST, good_cause_code=GOOD_CAUSE_NONPAYMENT
                ),
                COMPLIANCE,
            )
        )
        assert requested["state"] == APPT_TERMINATION_REQUESTED

        withdrawn = validate_success(
            api.terminate_appointment(
                appointment["id"], termination_payload(TERMINATION_WITHDRAW), COMPLIANCE
            )
        )

        assert withdrawn["state"] == APPT_ACTIVE
        assert withdrawn["termination_requested_at_utc"] is None
        assert withdrawn["termination_effective_utc"] is None
        assert withdrawn["good_cause_code"] is None
        assert withdrawn["terminated_at_utc"] is None
        assert withdrawn["proposed_by_user_id"] is not None
        assert withdrawn["approved_by_user_id"] is not None
        assert withdrawn["approved_by_user_id"] != withdrawn["proposed_by_user_id"]
        stored_license = validate_success(api.get_state_license(license_row["id"], ADMIN))
        assert stored_license["active_appointment_count"] == 1
        assert stored_license["status"] == LICENSE_ACTIVE
