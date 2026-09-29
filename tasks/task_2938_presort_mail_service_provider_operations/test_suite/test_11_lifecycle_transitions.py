"""How the bureau's records move: the states they open in and the edges they take.

Mail, pools, containers, appointments and postage statements each run a small
lifecycle, and this file walks those lifecycles from the outside. Every row is
read where it opens, driven across the edges the contract declares, and pushed
against the edges it does not: a state nothing leaves, a transition already
completed, a precondition that has not been met, and the one move the clock
makes on the bureau's behalf. Where a refusal is expected, the surrounding
ledgers are read back too, because a refused transition must cost nothing.
"""

from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import api_errors as e
from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.assertions import (
    assert_absent_or_none,
    assert_batch_ledger,
    assert_batch_pricing,
    assert_container_state,
    assert_field_values,
    assert_full_identity,
    assert_job_state,
    assert_permit_funds,
    assert_statement_figures,
    assert_sum_of_cents,
    find_by_id,
)
from test_helpers.constants import FIXTURE_CLOCK_UTC
from test_helpers.test_users import (
    ACCEPTANCE_CLERK,
    BUREAU_ADMIN,
    POSTAGE_MANAGER,
    PRESORT_OPERATOR,
)


def _one_of_everything(api):
    """One freshly created row of each of the seven stateful kinds.

    The clock is moved to the fixture instant first so the dock appointment can
    be booked into the future, and nothing beyond creation is done to any row.
    """
    world = fx.World()
    fx.set_clock(api, FIXTURE_CLOCK_UTC)

    world.client = fx.create_client(
        api,
        f.client_payload(
            name="Initial State Co",
            client_code="INIT",
            service_fee_rate_per_thousand_cents=1000,
        ),
    )
    world.permit = fx.create_permit_account(
        api,
        f.permit_account_payload(
            world.client["id"],
            permit_number="PI-111100",
            payment_method="PERMIT_IMPRINT",
        ),
    )
    world.facility = fx.create_entry_facility(api, f.entry_facility_payload())
    world.job = fx.create_mail_job(
        api,
        f.mail_job_payload(
            world.client["id"],
            world.permit["id"],
            mail_class="MARKETING_MAIL",
            processing_category="LETTERS",
            declared_piece_count=1000,
            declared_weight_oz_per_piece=1.0,
        ),
    )
    world.batch = fx.create_batch(
        api, f.commingle_batch_payload(world.facility["id"])
    )
    world.container = fx.add_container(
        api,
        world.batch["id"],
        f.sort_container_payload(
            container_type="TRAY",
            destination_zip3="021",
            sort_level="FIVE_DIGIT",
            piece_count=1000,
        ),
    )
    world.shipment = fx.create_drop_shipment(
        api,
        f.drop_shipment_payload(
            world.batch["id"],
            world.facility["id"],
            f.instant(2026, 8, 12, 8, 0, 0),
            f.instant(2026, 8, 12, 16, 0, 0),
            pallet_count=2,
        ),
    )
    return world


class TestInitialStatesOnCreation:
    """Every stateful row opens in the one state the contract names for it."""

    def test_the_registry_rows_open_ready_to_trade(self, api):
        """A mailer, its permit account and an entry point all open live.

        "A newly registered client opens in `ACTIVE` status with
        `suspension_reason` null, and with both of its running ledgers at zero".
        Its funding account opens the same way: "A permit account opens in `ACTIVE`
        status with `balance_cents` and `reserved_cents` both zero." And the entry
        point is available from the moment it is registered: "A facility opens in
        `OPEN` status."

        Each is a first write, so "`version` is an integer that starts at 1 when
        the resource is created and increases by exactly 1 on every mutation of
        that resource".

        Design: Corner/state_machines/initial_states_assigned_on_creation_of_every_entity
        """
        world = _one_of_everything(api)

        assert world.client["status"] == "ACTIVE"
        assert_absent_or_none(world.client, ["suspension_reason"])
        assert_full_identity(world.client, expected_version=1)

        assert world.permit["status"] == "ACTIVE"
        assert_permit_funds(world.permit, balance_cents=0, reserved_cents=0)
        assert_full_identity(world.permit, expected_version=1)

        assert world.facility["status"] == "OPEN"
        assert_full_identity(world.facility, expected_version=1)

    def test_the_job_and_the_pool_open_before_any_processing(self, api):
        """A tendered job is untouched mail and an opened pool is empty.

        "A tendered job opens in `RECEIVED`. Its `accepted_piece_count` starts
        equal to `declared_piece_count`, because nothing has yet been suppressed.
        Its `hygiene_run_count` and `rework_count` both start at 0, its
        `address_quality_pct` and `postage_due_cents` both start at 0, its
        `move_update_compliant` starts false, and its `commingle_batch_id`,
        `mailed_at_utc` and `cancel_reason` all start null."

        The pool opens with nothing in it and no price: "The batch opens in `OPEN`
        status with `achieved_tier` at `NONE` and with `member_job_count`,
        `total_piece_count`, `container_count`, `rate_mills_per_piece` and
        `batch_postage_cents` all at 0."

        Design: Corner/state_machines/initial_states_assigned_on_creation_of_every_entity
        """
        world = _one_of_everything(api)

        assert_job_state(
            world.job,
            status="RECEIVED",
            accepted_piece_count=1000,
            rework_count=0,
            postage_due_cents=0,
            commingle_batch_id=None,
        )
        assert_field_values(
            world.job,
            {
                "declared_piece_count": 1000,
                "hygiene_run_count": 0,
                "move_update_compliant": False,
            },
        )
        assert_absent_or_none(world.job, ["mailed_at_utc", "cancel_reason"])
        assert_full_identity(world.job, expected_version=1)

        assert_batch_pricing(
            world.batch,
            status="OPEN",
            achieved_tier="NONE",
            rate_mills=0,
            postage_cents=0,
        )
        assert_batch_ledger(
            world.batch, member_job_count=0, total_piece_count=0, container_count=0
        )
        assert_full_identity(world.batch, expected_version=1)

    def test_the_container_and_the_appointment_open_staged_and_scheduled(self, api):
        """A qualifying tray is still only staged, and a booking is only booked.

        "The container's `placard_id` starts null — documentation placards are
        stamped only at sortation — and its `status` starts at `STAGED`." Earning
        its keep is a separate question decided at once: "A `TRAY` built at the
        deep levels `THREE_DIGIT` or `FIVE_DIGIT` must hold at least 150 pieces."

        The appointment opens with neither outcome recorded: "A successful booking
        opens the shipment in `SCHEDULED` with `deposited_at_utc` and
        `cancel_reason` both null."

        Design: Corner/state_machines/initial_states_assigned_on_creation_of_every_entity
        """
        world = _one_of_everything(api)

        assert_container_state(
            world.container, status="STAGED", qualifies=True, placard_id=None
        )
        assert_full_identity(world.container, expected_version=1)

        assert world.shipment["status"] == "SCHEDULED"
        assert_absent_or_none(
            world.shipment, ["deposited_at_utc", "cancel_reason"]
        )
        assert_full_identity(world.shipment, expected_version=1)


def _toggle_client(api):
    """One ACTIVE mailer whose trading status is about to be driven both ways."""
    return fx.create_client(
        api,
        f.client_payload(
            name="Toggle Mail Co",
            client_code="TOGGLE",
            service_fee_rate_per_thousand_cents=1000,
        ),
    )


class TestClientTradingStatusCycle:
    """The two-state trading machine, driven around and around."""

    def test_suspending_a_mailer_stamps_the_supplied_reason(self, api):
        """The reason travels from the request onto the row.

        "A `BureauAdmin` may drive `ACTIVE → SUSPENDED`, supplying a `status` of
        `SUSPENDED` together with an optional `reason` that is stamped into
        `suspension_reason`; the transition requires the client to currently be
        `ACTIVE`, and it increments the client's `version`."

        Design: Corner/state_machines/valid_transition_client_suspend_then_reactivate_clears_reason
        """
        client = _toggle_client(api)

        suspended = validate_success(
            api.set_client_status(
                client["id"],
                f.client_status_payload("SUSPENDED", "unpaid service fees"),
                BUREAU_ADMIN,
            )
        )

        assert_field_values(
            suspended,
            {
                "status": "SUSPENDED",
                "suspension_reason": "unpaid service fees",
                "version": 2,
            },
        )

    def test_reactivating_clears_the_reason_and_the_edge_pair_is_reusable(self, api):
        """Coming back clears the stale text, and a later suspension replaces it.

        "The reverse move `SUSPENDED → ACTIVE` requires the client to currently be
        `SUSPENDED`, clears `suspension_reason` back to null, and likewise
        increments `version`." Driving the forward edge again stamps the new
        reason, because "A `BureauAdmin` may drive `ACTIVE → SUSPENDED`, supplying a
        `status` of `SUSPENDED` together with an optional `reason` that is stamped
        into `suspension_reason`".

        Three accepted transitions land on version 4, since "`version` is an
        integer that starts at 1 when the resource is created and increases by
        exactly 1 on every mutation of that resource".

        Design: Corner/state_machines/valid_transition_client_suspend_then_reactivate_clears_reason
        """
        client = _toggle_client(api)

        first = validate_success(
            api.set_client_status(
                client["id"],
                f.client_status_payload("SUSPENDED", "unpaid service fees"),
                BUREAU_ADMIN,
            )
        )
        reinstated = validate_success(
            api.set_client_status(
                client["id"], f.client_status_payload("ACTIVE"), BUREAU_ADMIN
            )
        )
        again = validate_success(
            api.set_client_status(
                client["id"],
                f.client_status_payload("SUSPENDED", "returned statement rework"),
                BUREAU_ADMIN,
            )
        )

        assert reinstated["status"] == "ACTIVE"
        assert_absent_or_none(reinstated, ["suspension_reason"])
        assert_field_values(
            again,
            {
                "status": "SUSPENDED",
                "suspension_reason": "returned statement rework",
            },
        )
        assert [first["version"], reinstated["version"], again["version"]] == [
            2,
            3,
            4,
        ], "each accepted transition bumps the counter by exactly one"


def _two_appointments_at_one_dock(api):
    """One SCF dock holding two bookings that end at different instants.

    EARLY runs from 08:00 to 12:00 and LATE from 08:00 to 20:00 on 12 August,
    each tendering two pallets against a twelve-pallet dock, so both fit.
    """
    world = fx.World()
    fx.set_clock(api, FIXTURE_CLOCK_UTC)
    world.facility = fx.create_entry_facility(api, f.entry_facility_payload())
    world.batch_1 = fx.create_batch(
        api, f.commingle_batch_payload(world.facility["id"])
    )
    world.batch_2 = fx.create_batch(
        api, f.commingle_batch_payload(world.facility["id"])
    )
    world.early = fx.create_drop_shipment(
        api,
        f.drop_shipment_payload(
            world.batch_1["id"],
            world.facility["id"],
            f.instant(2026, 8, 12, 8, 0, 0),
            f.instant(2026, 8, 12, 12, 0, 0),
            pallet_count=2,
        ),
    )
    world.late = fx.create_drop_shipment(
        api,
        f.drop_shipment_payload(
            world.batch_2["id"],
            world.facility["id"],
            f.instant(2026, 8, 12, 8, 0, 0),
            f.instant(2026, 8, 12, 20, 0, 0),
            pallet_count=2,
        ),
    )
    return world


WINDOW_END = f.instant(2026, 8, 12, 12, 0, 0)
ONE_MS_PAST_WINDOW_END = f.instant(2026, 8, 12, 12, 0, 0, 1)


class TestClockDrivenNoShowSweep:
    """The one transition the clock makes on the bureau's behalf."""

    def test_the_clock_landing_exactly_on_the_window_end_sweeps_nothing(self, api):
        """An appointment whose window ends at the new clock value survives.

        "When a `BureauAdmin` moves the logical clock to a supplied `to_iso8601`
        instant, the server walks all shipments still in `SCHEDULED` in `created_at`
        ascending order and, for each whose `window_end_utc` is strictly earlier
        than the new clock value, drives it `SCHEDULED → NO_SHOW`, releases its
        `pallet_count` from the dock occupancy of every overlapping window, and
        increments its `version`." The response is where the sweep is reported:
        "The response reports the new clock as `current_utc` together with
        `no_show_shipment_ids`, the array of identifiers of the shipments the
        advance just marked."

        Comparisons are exact to the millisecond: "all instant comparisons are made
        at millisecond resolution."

        Design: Corner/state_machines/shipment_becomes_no_show_when_clock_passes_window_end
        """
        world = _two_appointments_at_one_dock(api)

        advanced = validate_success(api.set_clock(WINDOW_END, BUREAU_ADMIN))

        assert advanced["current_utc"] == WINDOW_END
        assert advanced["no_show_shipment_ids"] == [], (
            "a window ending exactly at the clock is not yet strictly earlier"
        )
        still_scheduled = validate_success(
            api.get_drop_shipment(world.early["id"], PRESORT_OPERATOR)
        )
        assert still_scheduled["status"] == "SCHEDULED"

    def test_one_millisecond_past_the_window_end_sweeps_that_booking_alone(self, api):
        """The sweep takes the ended appointment and leaves the open one.

        "for each whose `window_end_utc` is strictly earlier than the new clock
        value, drives it `SCHEDULED → NO_SHOW`, releases its `pallet_count` from the
        dock occupancy of every overlapping window, and increments its `version`."
        The identifiers come back in the response, which "reports the new clock as
        `current_utc` together with `no_show_shipment_ids`, the array of identifiers
        of the shipments the advance just marked."

        Design: Corner/state_machines/shipment_becomes_no_show_when_clock_passes_window_end
        """
        world = _two_appointments_at_one_dock(api)

        validate_success(api.set_clock(WINDOW_END, BUREAU_ADMIN))
        swept = validate_success(
            api.set_clock(ONE_MS_PAST_WINDOW_END, BUREAU_ADMIN)
        )

        assert swept["no_show_shipment_ids"] == [world.early["id"]], (
            "exactly the appointment whose window has ended is marked"
        )
        early = validate_success(
            api.get_drop_shipment(world.early["id"], PRESORT_OPERATOR)
        )
        late = validate_success(
            api.get_drop_shipment(world.late["id"], PRESORT_OPERATOR)
        )
        assert early["status"] == "NO_SHOW"
        assert late["status"] == "SCHEDULED", (
            "the later window has not ended, so it is not swept"
        )

    def test_departing_a_swept_appointment_is_refused(self, api):
        """Nothing leaves a no-show; the truck cannot be dispatched afterwards.

        "`DEPOSITED`, `CANCELLED` and `NO_SHOW` are all terminal for a shipment."
        Dispatch therefore has nowhere to go: "a `PresortOperator` drives the load
        `SCHEDULED → IN_TRANSIT`, incrementing the shipment's `version`. Departure
        from any other status is refused with `ERR_INVALID_SHIPMENT_STATE`."

        Design: Corner/state_machines/shipment_becomes_no_show_when_clock_passes_window_end
        """
        world = _two_appointments_at_one_dock(api)
        validate_success(api.set_clock(ONE_MS_PAST_WINDOW_END, BUREAU_ADMIN))

        validate_error(
            api.depart_drop_shipment(world.early["id"], PRESORT_OPERATOR),
            e.ERR_INVALID_SHIPMENT_STATE,
            expected_status=409,
        )

        unchanged = validate_success(
            api.get_drop_shipment(world.early["id"], PRESORT_OPERATOR)
        )
        assert unchanged["status"] == "NO_SHOW"


POOLED_JOB_PIECES = 1200
CANCEL_REASON = "client pulled the file"


def _one_pooled_job(api):
    """One mailer whose only job of 1200 accepted pieces sits inside an OPEN pool."""
    world = fx.World()
    registry = fx.setup_client_with_permit(
        api,
        name="Pivot Print",
        client_code="PIVOT",
        service_fee_rate_per_thousand_cents=1100,
        permit_number="PI-400400",
        payment_method="PERMIT_IMPRINT",
    )
    world.client = registry.client
    world.permit = registry.permit
    world.facility = fx.setup_facility(api)
    tendered = fx.setup_cleared_job(
        api,
        registry.client_id,
        registry.permit_id,
        declared_piece_count=1250,
        declared_weight_oz_per_piece=1.2,
        submitted_piece_count=1250,
        cass_matched_count=1235,
        ncoa_move_updated_count=40,
        undeliverable_removed_count=50,
        move_update_age_days=30,
    )
    world.job = tendered.job
    world.batch = fx.create_batch(
        api, f.commingle_batch_payload(world.facility["id"])
    )
    world.member = fx.add_member(api, world.batch["id"], tendered.job_id)
    return world


class TestPooledJobCannotBeCancelled:
    """Cancellation has no edge out of a pool, and the ledger proves it."""

    def test_cancelling_a_pooled_job_is_refused(self, api):
        """Mail already contributing pieces to a pool cannot be withdrawn by cancelling.

        "Cancellation is only available before the job has been pooled; a job in
        any other status is refused with `ERR_INVALID_JOB_STATE`." The edges are
        named exactly: "the job moves `RECEIVED → CANCELLED` or `HYGIENE_CLEARED →
        CANCELLED` with its `version` incremented."

        Design: Corner/state_machines/invalid_transitions_cancel_a_pooled_mail_job_is_rejected
        """
        world = _one_pooled_job(api)

        validate_error(
            api.cancel_mail_job(
                world.job["id"], f.cancel_payload(CANCEL_REASON), PRESORT_OPERATOR
            ),
            e.ERR_INVALID_JOB_STATE,
            expected_status=409,
        )

        job = validate_success(api.get_mail_job(world.job["id"], PRESORT_OPERATOR))
        assert job["status"] == "POOLED"
        assert_absent_or_none(job, ["cancel_reason"])

    def test_the_refused_cancellation_leaves_the_pool_ledger_intact(self, api):
        """The pieces stay counted, because the refusal changed nothing at all.

        "A partial cascade is never an acceptable outcome: if any precondition of
        the driving operation fails, nothing at all changes." The ledger the refusal
        protects is the pool's own: "On the batch side, `total_piece_count` grows by
        the new member's `contributed_piece_count` and `member_job_count` grows by
        one."

        Design: Corner/state_machines/invalid_transitions_cancel_a_pooled_mail_job_is_rejected
        """
        world = _one_pooled_job(api)

        validate_error(
            api.cancel_mail_job(
                world.job["id"], f.cancel_payload(CANCEL_REASON), PRESORT_OPERATOR
            ),
            e.ERR_INVALID_JOB_STATE,
            expected_status=409,
        )

        batch = validate_success(
            api.get_commingle_batch(world.batch["id"], POSTAGE_MANAGER)
        )
        assert batch["total_piece_count"] == POOLED_JOB_PIECES
        assert batch["member_job_count"] == 1

    def test_withdrawing_the_member_first_makes_the_same_cancel_legal(self, api):
        """Out of the pool, the identical request is accepted and stamps the reason.

        Withdrawal puts the mail back where cancellation can reach it: "The batch
        member row is deleted, the job moves `POOLED → HYGIENE_CLEARED`, its
        `commingle_batch_id` is cleared back to null and its `postage_due_cents` is
        reset to 0." The pool gives the pieces back too: "The batch's
        `total_piece_count` decreases by exactly the `contributed_piece_count` the
        member had contributed and `member_job_count` decreases by one, restoring
        the batch piece ledger."

        The cancel then runs on its own terms: "A `PresortOperator` or a
        `BureauAdmin` supplies a required `reason`, which is stamped into
        `cancel_reason`".

        Design: Corner/state_machines/invalid_transitions_cancel_a_pooled_mail_job_is_rejected
        """
        world = _one_pooled_job(api)
        validate_error(
            api.cancel_mail_job(
                world.job["id"], f.cancel_payload(CANCEL_REASON), PRESORT_OPERATOR
            ),
            e.ERR_INVALID_JOB_STATE,
            expected_status=409,
        )

        withdrawal = api.remove_batch_member(
            world.batch["id"], world.member["id"], PRESORT_OPERATOR
        )
        assert withdrawal.status_code == 204, "withdrawal returns 204 with no body"
        assert not withdrawal.content

        cancelled = validate_success(
            api.cancel_mail_job(
                world.job["id"], f.cancel_payload(CANCEL_REASON), PRESORT_OPERATOR
            )
        )
        assert_field_values(
            cancelled, {"status": "CANCELLED", "cancel_reason": CANCEL_REASON}
        )

        batch = validate_success(
            api.get_commingle_batch(world.batch["id"], POSTAGE_MANAGER)
        )
        assert batch["total_piece_count"] == 0
        assert batch["member_job_count"] == 0


BALANCE_AFTER_FILING = fx.HOUSE_FUNDING_CENTS - fx.POOLED_POSTAGE_CENTS


class TestReturnRequiresAtLeastOneFinding:
    """The unwind edge is gated on a documented reason for unwinding."""

    def test_a_return_with_no_findings_recorded_is_refused(self, api):
        """Nothing goes back to the floor without a defect on the record.

        "When the outcome is `RETURN`, the statement moves `SUBMITTED →
        RETURNED_FOR_CORRECTION`, and this is only permitted when at least one
        finding has been recorded during the current filing episode — a return
        requested while `verification_error_count` is 0 is refused with
        `ERR_NO_VERIFICATION_FINDINGS`."

        Design: Corner/state_machines/precondition_enforcement_return_requires_at_least_one_finding
        """
        world = fx.build_submitted_world(api)

        validate_error(
            api.verify_postage_statement(
                world.statement_id, f.verify_payload("RETURN"), ACCEPTANCE_CLERK
            ),
            e.ERR_NO_VERIFICATION_FINDINGS,
            expected_status=422,
        )

        statement = validate_success(
            api.get_postage_statement(world.statement_id, POSTAGE_MANAGER)
        )
        assert_statement_figures(
            statement,
            status="SUBMITTED",
            declared_postage_cents=fx.POOLED_POSTAGE_CENTS,
            adjustment_cents=0,
            verified_postage_cents=0,
            verification_error_count=0,
        )

    def test_the_refused_return_unwinds_nothing_at_all(self, api):
        """No link of the four-link unwind fires on a refused return.

        "A partial cascade is never an acceptable outcome: if any precondition of
        the driving operation fails, nothing at all changes." So the encumbrance
        filing created stands — "`declared_postage_cents` is subtracted from the
        account's `balance_cents` and added to its `reserved_cents`, which changes
        nothing about the account's total funds. The batch moves `SORTED →
        DOCUMENTED`." — and none of link 3 happens: "every member job moves
        `PRESORTED → REWORK`, has its `rework_count` incremented by one and its
        `postage_due_cents` reset to 0, and has its `version` incremented; and every
        container of the batch moves `DOCUMENTED → RETURNED` with its `version`
        incremented."

        Design: Corner/state_machines/precondition_enforcement_return_requires_at_least_one_finding
        """
        world = fx.build_submitted_world(api)

        validate_error(
            api.verify_postage_statement(
                world.statement_id, f.verify_payload("RETURN"), ACCEPTANCE_CLERK
            ),
            e.ERR_NO_VERIFICATION_FINDINGS,
            expected_status=422,
        )

        permit = validate_success(
            api.get_permit_account(world.permit_house_id, POSTAGE_MANAGER)
        )
        assert_permit_funds(
            permit,
            balance_cents=BALANCE_AFTER_FILING,
            reserved_cents=fx.POOLED_POSTAGE_CENTS,
        )

        batch = validate_success(
            api.get_commingle_batch(world.batch_id, POSTAGE_MANAGER)
        )
        assert batch["status"] == "DOCUMENTED"

        job_a = validate_success(api.get_mail_job(world.job_a_id, POSTAGE_MANAGER))
        assert_job_state(job_a, status="PRESORTED", rework_count=0)

        container = validate_success(
            api.get_sort_container(world.container_1_id, POSTAGE_MANAGER)
        )
        assert container["status"] == "DOCUMENTED"

    def test_one_recorded_finding_opens_the_return_edge_and_the_unwind_runs(self, api):
        """With a defect on the record the identical return is accepted and cascades.

        Recording the defect moves the counter the gate reads: "`verification_error_count`
        is refreshed as the number of findings recorded." The return then unwinds the
        batch — "Link 1: `declared_postage_cents` is subtracted from the account's
        `reserved_cents` and added back to its `balance_cents`, so the account's total
        funds are unchanged and the encumbrance is released." and "Link 2: the batch
        moves `DOCUMENTED → REWORK`" and "every member job moves `PRESORTED → REWORK`,
        has its `rework_count` incremented by one and its `postage_due_cents` reset to
        0".

        Design: Corner/state_machines/precondition_enforcement_return_requires_at_least_one_finding
        """
        world = fx.build_submitted_world(api)
        validate_error(
            api.verify_postage_statement(
                world.statement_id, f.verify_payload("RETURN"), ACCEPTANCE_CLERK
            ),
            e.ERR_NO_VERIFICATION_FINDINGS,
            expected_status=422,
        )

        fx.add_finding(
            api,
            world.statement_id,
            f.finding_payload("BAD_ADDRESS_QUALITY", 75),
        )
        with_finding = validate_success(
            api.get_postage_statement(world.statement_id, POSTAGE_MANAGER)
        )
        assert with_finding["verification_error_count"] == 1

        returned = validate_success(
            api.verify_postage_statement(
                world.statement_id, f.verify_payload("RETURN"), ACCEPTANCE_CLERK
            )
        )
        assert returned["status"] == "RETURNED_FOR_CORRECTION"

        permit = validate_success(
            api.get_permit_account(world.permit_house_id, POSTAGE_MANAGER)
        )
        assert_permit_funds(
            permit, balance_cents=fx.HOUSE_FUNDING_CENTS, reserved_cents=0
        )
        batch = validate_success(
            api.get_commingle_batch(world.batch_id, POSTAGE_MANAGER)
        )
        assert batch["status"] == "REWORK"
        job_a = validate_success(api.get_mail_job(world.job_a_id, POSTAGE_MANAGER))
        assert_job_state(job_a, status="REWORK", rework_count=1)


class TestAcceptedStatementIsTerminal:
    """Nothing leaves a cleanly accepted statement, in either direction."""

    def test_a_clean_acceptance_verifies_the_declared_postage(self, api):
        """The accepted statement carries the declared total as verified.

        "When the outcome is `ACCEPT` and the pinned walk resolves
        `adjustment_cents` to exactly 0, the statement moves `SUBMITTED →
        ACCEPTED_CLEAN`. Its `adjustment_cents` is set to 0 and its
        `verified_postage_cents` to its `declared_postage_cents`."

        That status is a dead end: "`VOID`, `ACCEPTED_CLEAN` and
        `ACCEPTED_WITH_ADJUSTMENT` are all terminal for a statement."

        Design: Corner/state_machines/terminal_state_lockdown_accepted_statement_refuses_void_and_findings
        """
        world = fx.build_submitted_world(api)

        accepted = validate_success(
            api.verify_postage_statement(
                world.statement_id, f.verify_payload("ACCEPT"), ACCEPTANCE_CLERK
            )
        )

        assert_statement_figures(
            accepted,
            status="ACCEPTED_CLEAN",
            declared_postage_cents=fx.POOLED_POSTAGE_CENTS,
            adjustment_cents=0,
            verified_postage_cents=fx.POOLED_POSTAGE_CENTS,
            verification_error_count=0,
        )

    def test_voiding_an_accepted_statement_is_refused(self, api):
        """The consumed reservation cannot be handed back by voiding.

        Voiding has only two legal origins: "the statement moves to `VOID` from
        either `DRAFT` or `SUBMITTED`." Beyond those, the own-state rung bites: "the
        target `PostageStatement` is in a status the operation allows: `DRAFT` for
        submission and for voiding; `SUBMITTED` for recording findings, for
        verification and for voiding; `RETURNED_FOR_CORRECTION` for revision.
        Violation: `ERR_INVALID_STATEMENT_STATE` (409)."

        Design: Corner/state_machines/terminal_state_lockdown_accepted_statement_refuses_void_and_findings
        """
        world = fx.build_submitted_world(api)
        fx.verify_statement(api, world.statement_id, "ACCEPT")

        validate_error(
            api.void_postage_statement(
                world.statement_id, f.void_payload("too late"), POSTAGE_MANAGER
            ),
            e.ERR_INVALID_STATEMENT_STATE,
            expected_status=409,
        )

        statement = validate_success(
            api.get_postage_statement(world.statement_id, POSTAGE_MANAGER)
        )
        assert statement["status"] == "ACCEPTED_CLEAN"
        assert_absent_or_none(statement, ["void_reason"])

    def test_recording_a_finding_against_an_accepted_statement_is_refused(self, api):
        """A closed statement cannot be re-priced by a late defect.

        Findings only attach to a live filing episode: "an `AcceptanceClerk` records
        each defect as a **verification finding** against a statement in
        `SUBMITTED`". Anywhere else the own-state rung applies, whose "Violation:
        `ERR_INVALID_STATEMENT_STATE` (409)."

        The refusals cost the account nothing: "The reservation is consumed rather
        than returned: `declared_postage_cents` is subtracted from the account's
        `reserved_cents` and is not added back to `balance_cents`, which is the one
        moment postage genuinely leaves the account." and "The batch is left in
        `DOCUMENTED`."

        Design: Corner/state_machines/terminal_state_lockdown_accepted_statement_refuses_void_and_findings
        """
        world = fx.build_submitted_world(api)
        fx.verify_statement(api, world.statement_id, "ACCEPT")

        validate_error(
            api.create_finding(
                world.statement_id,
                f.finding_payload("SHORT_PAID", 100),
                ACCEPTANCE_CLERK,
            ),
            e.ERR_INVALID_STATEMENT_STATE,
            expected_status=409,
        )

        statement = validate_success(
            api.get_postage_statement(world.statement_id, POSTAGE_MANAGER)
        )
        assert statement["verification_error_count"] == 0
        assert statement["adjustment_cents"] == 0

        permit = validate_success(
            api.get_permit_account(world.permit_house_id, POSTAGE_MANAGER)
        )
        assert_permit_funds(
            permit, balance_cents=BALANCE_AFTER_FILING, reserved_cents=0
        )
        batch = validate_success(
            api.get_commingle_batch(world.batch_id, POSTAGE_MANAGER)
        )
        assert batch["status"] == "DOCUMENTED"


DOCK_WINDOW_START = f.instant(2026, 8, 12, 10, 0, 0)
DOCK_WINDOW_END = f.instant(2026, 8, 12, 14, 0, 0)
FULL_DOCK_PALLETS = 4
FIRST_CANCEL_REASON = "truck breakdown"
SECOND_CANCEL_REASON = "second thoughts"


def _full_dock_with_one_appointment(api):
    """A four-pallet DDU dock filled by a single four-pallet appointment.

    A second empty pool stands ready, so a re-booking of the identical window can
    only succeed if the first appointment has genuinely released its pallets.
    """
    world = fx.World()
    fx.set_clock(api, FIXTURE_CLOCK_UTC)
    world.facility = fx.setup_facility(
        api,
        facility_code="DDU-021",
        facility_type="DDU",
        zip3="021",
        dock_capacity_pallets_per_slot=FULL_DOCK_PALLETS,
        drop_ship_discount_bp=500,
        served_zip3_list=["021"],
    )
    world.batch_1 = fx.create_batch(
        api, f.commingle_batch_payload(world.facility["id"])
    )
    world.batch_2 = fx.create_batch(
        api, f.commingle_batch_payload(world.facility["id"])
    )
    world.shipment = fx.create_drop_shipment(
        api,
        f.drop_shipment_payload(
            world.batch_1["id"],
            world.facility["id"],
            DOCK_WINDOW_START,
            DOCK_WINDOW_END,
            pallet_count=FULL_DOCK_PALLETS,
        ),
    )
    return world


class TestShipmentCancellationIsNotIdempotent:
    """Repeating a completed cancellation is an error, not a quiet success."""

    def test_the_first_cancellation_stamps_its_reason_and_bumps_the_version(self, api):
        """One cancellation, one reason, one version increment.

        "A `PresortOperator` or a `BureauAdmin` supplies a required `reason`, stamped
        into `cancel_reason`, and the shipment moves `SCHEDULED → CANCELLED` or
        `IN_TRANSIT → CANCELLED` with its `version` incremented."

        Design: Corner/state_machines/idempotency_second_cancel_of_a_cancelled_shipment_is_rejected
        """
        world = _full_dock_with_one_appointment(api)

        cancelled = validate_success(
            api.cancel_drop_shipment(
                world.shipment["id"],
                f.cancel_payload(FIRST_CANCEL_REASON),
                PRESORT_OPERATOR,
            )
        )

        assert_field_values(
            cancelled,
            {
                "status": "CANCELLED",
                "cancel_reason": FIRST_CANCEL_REASON,
                "version": 2,
            },
        )

    def test_a_second_cancellation_is_refused_and_overwrites_nothing(self, api):
        """The repeat neither succeeds nor rewrites the recorded reason.

        "`DEPOSITED`, `CANCELLED` and `NO_SHOW` are all terminal for a shipment." The
        own-state rung names the statuses the operation admits: "the target
        `DropShipment` is in a status the operation allows: `SCHEDULED` for
        departure, `IN_TRANSIT` for deposit, `SCHEDULED` or `IN_TRANSIT` for
        cancellation. Violation: `ERR_INVALID_SHIPMENT_STATE` (409)." And a refusal
        writes nothing: "A partial cascade is never an acceptable outcome: if any
        precondition of the driving operation fails, nothing at all changes."

        Design: Corner/state_machines/idempotency_second_cancel_of_a_cancelled_shipment_is_rejected
        """
        world = _full_dock_with_one_appointment(api)
        validate_success(
            api.cancel_drop_shipment(
                world.shipment["id"],
                f.cancel_payload(FIRST_CANCEL_REASON),
                PRESORT_OPERATOR,
            )
        )

        validate_error(
            api.cancel_drop_shipment(
                world.shipment["id"],
                f.cancel_payload(SECOND_CANCEL_REASON),
                PRESORT_OPERATOR,
            ),
            e.ERR_INVALID_SHIPMENT_STATE,
            expected_status=409,
        )

        shipment = validate_success(
            api.get_drop_shipment(world.shipment["id"], PRESORT_OPERATOR)
        )
        assert_field_values(
            shipment,
            {
                "status": "CANCELLED",
                "cancel_reason": FIRST_CANCEL_REASON,
                "version": 2,
            },
        )

    def test_the_cancelled_appointment_no_longer_occupies_the_dock(self, api):
        """The freed pallets let an identical window be booked straight away.

        "Cancellation releases this shipment's `pallet_count` from the dock's
        occupancy for every window that overlapped it, so the freed capacity is
        immediately available to future bookings." The occupancy walk agrees:
        "shipments in `CANCELLED`, `NO_SHOW` or `DEPOSITED` have released their
        pallets and take no part."

        Design: Corner/state_machines/idempotency_second_cancel_of_a_cancelled_shipment_is_rejected
        """
        world = _full_dock_with_one_appointment(api)
        validate_success(
            api.cancel_drop_shipment(
                world.shipment["id"],
                f.cancel_payload(FIRST_CANCEL_REASON),
                PRESORT_OPERATOR,
            )
        )

        rebooked = validate_success(
            api.create_drop_shipment(
                f.drop_shipment_payload(
                    world.batch_2["id"],
                    world.facility["id"],
                    DOCK_WINDOW_START,
                    DOCK_WINDOW_END,
                    pallet_count=FULL_DOCK_PALLETS,
                ),
                PRESORT_OPERATOR,
            ),
            expected_status=201,
        )

        assert_field_values(
            rebooked,
            {
                "status": "SCHEDULED",
                "pallet_count": FULL_DOCK_PALLETS,
                "window_start_utc": DOCK_WINDOW_START,
                "window_end_utc": DOCK_WINDOW_END,
            },
        )


class TestCleanAcceptanceMovesPostageOntoTheClientLedgers:
    """Acceptance is where the pooled postage becomes each mailer's receivable."""

    def test_each_member_job_takes_its_own_allocation_as_postage_due(self, api):
        """The job owes exactly what its pooled share came to.

        "Every batch member has its `allocated_adjustment_cents` set to 0, and every
        member job has its `postage_due_cents` set to that member's
        `allocated_postage_cents`."

        Design: Corner/state_machines/ledger_sync_client_unbilled_postage_after_clean_acceptance
        """
        world = fx.build_submitted_world(api)
        fx.verify_statement(api, world.statement_id, "ACCEPT")

        members, _meta = validate_paginated(
            api.list_batch_members(world.batch_id, POSTAGE_MANAGER)
        )
        member_a = find_by_id(members, world.member_a_id)
        member_b = find_by_id(members, world.member_b_id)

        job_a = validate_success(api.get_mail_job(world.job_a_id, POSTAGE_MANAGER))
        job_b = validate_success(api.get_mail_job(world.job_b_id, POSTAGE_MANAGER))

        assert job_a["postage_due_cents"] == fx.MEMBER_A_POSTAGE_CENTS
        assert job_b["postage_due_cents"] == fx.MEMBER_B_POSTAGE_CENTS
        assert job_a["postage_due_cents"] == member_a["allocated_postage_cents"]
        assert job_b["postage_due_cents"] == member_b["allocated_postage_cents"]
        assert member_a["allocated_adjustment_cents"] == 0
        assert member_b["allocated_adjustment_cents"] == 0

    def test_the_client_ledgers_reconcile_with_the_pooled_postage(self, api):
        """Each mailer's receivable grows by its own job, and the two sum to the pool.

        "Each member job's `postage_due_cents` is then added to that job's client's
        `unbilled_postage_cents`." The pool they must reconcile with is the batch's
        own: "The batch's `batch_postage_cents` is then the batch's
        `total_piece_count` multiplied by `rate_mills_per_piece`, divided by one
        thousand to convert mills to cents, and rounded half up to a whole number of
        cents." — and "The invariant is absolute: the allocated amounts sum to the
        pool exactly, for every pool and every member set."

        Design: Corner/state_machines/ledger_sync_client_unbilled_postage_after_clean_acceptance
        """
        world = fx.build_submitted_world(api)
        fx.verify_statement(api, world.statement_id, "ACCEPT")

        client_a = validate_success(api.get_client(world.acme_id, POSTAGE_MANAGER))
        client_b = validate_success(api.get_client(world.bore_id, POSTAGE_MANAGER))

        assert client_a["unbilled_postage_cents"] == fx.MEMBER_A_POSTAGE_CENTS
        assert client_b["unbilled_postage_cents"] == fx.MEMBER_B_POSTAGE_CENTS
        assert_sum_of_cents(
            [
                client_a["unbilled_postage_cents"],
                client_b["unbilled_postage_cents"],
            ],
            fx.POOLED_POSTAGE_CENTS,
            what="client unbilled ledgers",
        )

    def test_the_paying_house_account_owner_owes_nothing(self, api):
        """The client that funded the statement owns no mail, so owes nothing.

        The receivable follows the mail, not the money: "every member job has its
        `postage_due_cents` set to that member's `allocated_postage_cents`. Each
        member job's `postage_due_cents` is then added to that job's client's
        `unbilled_postage_cents`." A clean acceptance moves no job either: sortation
        already put them where they stay, since "Every member job moves `POOLED →
        PRESORTED`, and each such job has its `postage_due_cents` set to 0", and
        acceptance touches only the money and the batch — "The batch is left in
        `DOCUMENTED`."

        Design: Corner/state_machines/ledger_sync_client_unbilled_postage_after_clean_acceptance
        """
        world = fx.build_submitted_world(api)
        fx.verify_statement(api, world.statement_id, "ACCEPT")

        house = validate_success(api.get_client(world.house_id, POSTAGE_MANAGER))
        assert house["unbilled_postage_cents"] == 0, (
            "the funding account's owner holds no member job"
        )

        job_a = validate_success(api.get_mail_job(world.job_a_id, POSTAGE_MANAGER))
        job_b = validate_success(api.get_mail_job(world.job_b_id, POSTAGE_MANAGER))
        assert job_a["status"] == "PRESORTED"
        assert job_b["status"] == "PRESORTED"
