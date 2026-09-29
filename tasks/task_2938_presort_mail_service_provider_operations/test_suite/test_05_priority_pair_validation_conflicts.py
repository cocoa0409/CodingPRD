"""Requests that break two rules at once, and which rule must answer.

Every world below is rigged so that two rungs of the validation ladder are
violated by a single call. What is under test is not that the call fails but
which of the two failures is reported, and that the loser of each pair genuinely
was violated too — otherwise the ordering is not being exercised at all.
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
    assert_field_values,
    assert_job_state,
    assert_pct_2dp,
    assert_permit_funds,
)
from test_helpers.test_users import POSTAGE_MANAGER, PRESORT_OPERATOR


class TestStatePrecedesFiscalOnResubmittedStatement:
    """A statement already submitted, on an account with nothing left."""

    def test_the_second_submit_reports_the_statement_state_not_the_shortfall(self, api):
        """Rung 13 answers before rung 46 is ever reached.

        "13. **Statement own-state** — the target `PostageStatement` is in a status the
        operation allows: `DRAFT` for submission and for voiding". The funding rung is
        deliberately last: "This rung sits at the very bottom deliberately: a request
        that is malformed, unauthorized, out of state or non-compliant must report that
        fact rather than a money shortfall."

        Design: Difficulty/priority_pair_validation_conflict/state_precedes_fiscal_on_resubmitted_statement
        """
        world = fx.build_submitted_world(
            api, funding_cents=fx.EXACT_FUNDING_CENTS, reference="WIRE-7788"
        )

        validate_error(
            api.submit_postage_statement(world.statement_id, POSTAGE_MANAGER),
            e.ERR_INVALID_STATEMENT_STATE,
            expected_status=409,
        )

    def test_the_losing_rung_was_genuinely_violated_by_the_same_call(self, api):
        """The account really is empty, so the pair is a real conflict.

        "46. **Postage funding sufficiency, evaluated last** — on submission, the
        account's `balance_cents` is at least the statement's
        `declared_postage_cents`."

        Design: Difficulty/priority_pair_validation_conflict/state_precedes_fiscal_on_resubmitted_statement
        """
        world = fx.build_submitted_world(
            api, funding_cents=fx.EXACT_FUNDING_CENTS, reference="WIRE-7788"
        )

        permit = validate_success(
            api.get_permit_account(world.permit_house_id, POSTAGE_MANAGER)
        )
        # The first submit moved every funded cent into the encumbrance, so a second
        # one has 0 spendable against 79152 declared.
        assert_permit_funds(
            permit, balance_cents=0, reserved_cents=fx.POOLED_POSTAGE_CENTS
        )
        statement = validate_success(
            api.get_postage_statement(world.statement_id, POSTAGE_MANAGER)
        )
        assert statement["declared_postage_cents"] == fx.POOLED_POSTAGE_CENTS

    def test_the_first_submit_proved_the_equality_boundary_of_the_funding_rung(self, api):
        """Funding exactly equal to the declared postage is sufficient.

        The rung is satisfied when "the account's `balance_cents` is at least the
        statement's `declared_postage_cents`", and filing "moves the declared postage
        from spendable to encumbered: `declared_postage_cents` is subtracted from the
        account's `balance_cents` and added to its `reserved_cents`, which changes
        nothing about the account's total funds."

        Design: Difficulty/priority_pair_validation_conflict/state_precedes_fiscal_on_resubmitted_statement
        """
        world = fx.build_submitted_world(
            api, funding_cents=fx.EXACT_FUNDING_CENTS, reference="WIRE-7788"
        )

        statement = validate_success(
            api.get_postage_statement(world.statement_id, POSTAGE_MANAGER)
        )
        assert_field_values(statement, {"status": "SUBMITTED", "revision_index": 0})

    def test_the_refused_resubmission_moved_nothing(self, api):
        """A rejected request is not allowed to half-apply.

        The ladder returns "the error of the **first** rule violated; no later rule can
        mask an earlier one, and no earlier rule can be skipped because a later one
        also fails."

        Design: Difficulty/priority_pair_validation_conflict/state_precedes_fiscal_on_resubmitted_statement
        """
        world = fx.build_submitted_world(
            api, funding_cents=fx.EXACT_FUNDING_CENTS, reference="WIRE-7788"
        )
        validate_error(
            api.submit_postage_statement(world.statement_id, POSTAGE_MANAGER),
            e.ERR_INVALID_STATEMENT_STATE,
        )

        statement = validate_success(
            api.get_postage_statement(world.statement_id, POSTAGE_MANAGER)
        )
        assert_field_values(statement, {"status": "SUBMITTED", "revision_index": 0})
        permit = validate_success(
            api.get_permit_account(world.permit_house_id, POSTAGE_MANAGER)
        )
        assert_permit_funds(
            permit, balance_cents=0, reserved_cents=fx.POOLED_POSTAGE_CENTS
        )
        batch = validate_success(
            api.get_commingle_batch(world.batch_id, POSTAGE_MANAGER)
        )
        assert batch["status"] == "DOCUMENTED"


class TestSafetyBeatsReferentialOnPooling:
    """A first-class job with a four-month-old move update, offered to a
    marketing-mail pool."""

    def test_pooling_reports_the_stale_move_update_not_the_class_mismatch(self, api):
        """Rung 23 answers before rung 25.

        "23. **Move update currency** — the job's `move_update_compliant` is true.
        Violation: `ERR_MOVE_UPDATE_STALE` (422)." The mismatch rung sits two rungs
        lower: "25. **Mail class agreement** — the job's `mail_class` equals the
        batch's `mail_class`. Violation: `ERR_MAIL_CLASS_MISMATCH` (422)."

        Design: Difficulty/priority_pair_validation_conflict/safety_beats_referential_on_stale_move_update_and_class_mismatch
        """
        world = fx.build_first_class_world(api)

        validate_error(
            api.add_batch_member(
                world.batch_id, f.batch_member_payload(world.job_c_id), PRESORT_OPERATOR
            ),
            e.ERR_MOVE_UPDATE_STALE,
            expected_status=422,
        )

    def test_the_class_mismatch_was_real_and_the_hygiene_floor_was_not(self, api):
        """Both rungs of the pair are live, and the rung between them is not.

        "The job's `move_update_compliant` must be true, otherwise
        `ERR_MOVE_UPDATE_STALE`. The job's `address_quality_pct` must be at least 95.00
        percent, otherwise `ERR_ADDRESS_QUALITY_BELOW_MINIMUM` — a job at exactly 95.00
        passes, a job at 94.99 does not. And the job's `mail_class` and
        `processing_category` must each equal the batch's, otherwise
        `ERR_MAIL_CLASS_MISMATCH` or `ERR_PROCESSING_CATEGORY_MISMATCH`."

        Design: Difficulty/priority_pair_validation_conflict/safety_beats_referential_on_stale_move_update_and_class_mismatch
        """
        world = fx.build_first_class_world(api)

        job = validate_success(api.get_mail_job(world.job_c_id, PRESORT_OPERATOR))
        assert_pct_2dp(job, "address_quality_pct", 99.00)
        assert job["move_update_compliant"] is False
        assert job["mail_class"] == "FIRST_CLASS"

        batch = validate_success(
            api.get_commingle_batch(world.batch_id, PRESORT_OPERATOR)
        )
        assert batch["mail_class"] == "MARKETING_MAIL"

    def test_the_hygiene_run_itself_records_the_two_deciding_figures(self, api):
        """The run is where compliance was settled, before pooling was tried.

        "Its `move_update_compliant` is true when `move_update_age_days` is less than
        or equal to the maximum permitted age of 95 days, so a data set exactly 95 days
        old is compliant while one 96 days old is not."

        Design: Difficulty/priority_pair_validation_conflict/safety_beats_referential_on_stale_move_update_and_class_mismatch
        """
        world = fx.build_first_class_world(api)

        runs, _meta = validate_paginated(
            api.list_hygiene_runs(world.job_c_id, PRESORT_OPERATOR)
        )
        assert len(runs) == 1
        assert_pct_2dp(runs[0], "address_quality_pct", 99.00)
        assert_field_values(
            runs[0], {"move_update_age_days": 120, "move_update_compliant": False}
        )

    def test_the_refused_pooling_created_no_member(self, api):
        """Nothing is half-pooled.

        Pooling is what would have moved the job: "The job itself moves
        `HYGIENE_CLEARED → POOLED` and has its denormalized `commingle_batch_id` pointer
        set to the batch. On the batch side, `total_piece_count` grows by the new
        member's `contributed_piece_count` and `member_job_count` grows by one."

        Design: Difficulty/priority_pair_validation_conflict/safety_beats_referential_on_stale_move_update_and_class_mismatch
        """
        world = fx.build_first_class_world(api)
        validate_error(
            api.add_batch_member(
                world.batch_id, f.batch_member_payload(world.job_c_id), PRESORT_OPERATOR
            ),
            e.ERR_MOVE_UPDATE_STALE,
        )

        job = validate_success(api.get_mail_job(world.job_c_id, PRESORT_OPERATOR))
        assert_job_state(job, "HYGIENE_CLEARED", commingle_batch_id=None)

        batch = validate_success(
            api.get_commingle_batch(world.batch_id, PRESORT_OPERATOR)
        )
        assert_field_values(batch, {"member_job_count": 0, "total_piece_count": 0})
        members, meta = validate_paginated(
            api.list_batch_members(world.batch_id, PRESORT_OPERATOR)
        )
        assert members == [] and meta["total_count"] == 0


class TestStateBeatsTemporalOnBooking:
    """A closed facility whose dock is also already full."""

    def test_the_booking_reports_the_closed_facility_not_the_full_dock(self, api):
        """Rung 20 answers before rung 39.

        "20. **Entry facility open** — the `EntryFacility` being booked has status
        `OPEN`. Violation: `ERR_ENTRY_FACILITY_CLOSED` (409)." The capacity rung is far
        lower: "39. **Dock aggregate capacity** — the pallets already committed over
        overlapping half-open windows plus the requested `pallet_count` do not exceed
        the facility's `dock_capacity_pallets_per_slot`".

        Design: Difficulty/priority_pair_validation_conflict/state_beats_temporal_on_closed_facility_and_full_dock
        """
        world = fx.build_closed_facility_world(api)

        validate_error(
            api.create_drop_shipment(
                f.drop_shipment_payload(
                    world.batch_2_id,
                    world.facility_id,
                    f.instant(2026, 8, 12, 12, 0, 0),
                    f.instant(2026, 8, 12, 13, 0, 0),
                    pallet_count=1,
                ),
                PRESORT_OPERATOR,
            ),
            e.ERR_ENTRY_FACILITY_CLOSED,
            expected_status=409,
        )

    def test_the_dock_really_was_over_capacity_for_that_window(self, api):
        """The losing rung would have refused this booking on its own.

        "The booking is refused with `ERR_DOCK_CAPACITY_EXCEEDED` exactly when those
        occupied pallets plus the requested `pallet_count` are strictly greater than
        the facility's `dock_capacity_pallets_per_slot`; a total exactly equal to
        capacity is accepted."

        Design: Difficulty/priority_pair_validation_conflict/state_beats_temporal_on_closed_facility_and_full_dock
        """
        world = fx.build_closed_facility_world(api)

        facility = validate_success(
            api.get_entry_facility(world.facility_id, PRESORT_OPERATOR)
        )
        assert_field_values(
            facility, {"status": "CLOSED", "dock_capacity_pallets_per_slot": 4}
        )
        # The standing appointment fills the dock exactly over 10:00 to 14:00, which
        # overlaps the 12:00 to 13:00 window being requested.
        shipment = validate_success(
            api.get_drop_shipment(world.shipment_1_id, PRESORT_OPERATOR)
        )
        assert_field_values(shipment, {"status": "SCHEDULED", "pallet_count": 4})

    def test_closing_the_facility_left_the_standing_appointment_alone(self, api):
        """Closure is prospective, which is why the dock is still occupied.

        "Closing a facility is forward-looking only: dock appointments already booked
        there are untouched and continue to their conclusion, but a new booking against
        a `CLOSED` facility is refused with `ERR_ENTRY_FACILITY_CLOSED`."

        Design: Difficulty/priority_pair_validation_conflict/state_beats_temporal_on_closed_facility_and_full_dock
        """
        world = fx.build_closed_facility_world(api)
        validate_error(
            api.create_drop_shipment(
                f.drop_shipment_payload(
                    world.batch_2_id,
                    world.facility_id,
                    f.instant(2026, 8, 12, 12, 0, 0),
                    f.instant(2026, 8, 12, 13, 0, 0),
                    pallet_count=1,
                ),
                PRESORT_OPERATOR,
            ),
            e.ERR_ENTRY_FACILITY_CLOSED,
        )

        shipment = validate_success(
            api.get_drop_shipment(world.shipment_1_id, PRESORT_OPERATOR)
        )
        assert_field_values(shipment, {"status": "SCHEDULED", "pallet_count": 4})

    def test_the_refused_booking_created_no_shipment_for_its_batch(self, api):
        """A batch that was never booked has no appointment to show.

        A successful booking is the only way a shipment appears: "A successful booking
        opens the shipment in `SCHEDULED` with `deposited_at_utc` and `cancel_reason`
        both null."

        Design: Difficulty/priority_pair_validation_conflict/state_beats_temporal_on_closed_facility_and_full_dock
        """
        world = fx.build_closed_facility_world(api)
        validate_error(
            api.create_drop_shipment(
                f.drop_shipment_payload(
                    world.batch_2_id,
                    world.facility_id,
                    f.instant(2026, 8, 12, 12, 0, 0),
                    f.instant(2026, 8, 12, 13, 0, 0),
                    pallet_count=1,
                ),
                PRESORT_OPERATOR,
            ),
            e.ERR_ENTRY_FACILITY_CLOSED,
        )

        shipments, meta = validate_paginated(
            api.list_batch_drop_shipments(world.batch_2_id, PRESORT_OPERATOR)
        )
        assert shipments == [] and meta["total_count"] == 0
