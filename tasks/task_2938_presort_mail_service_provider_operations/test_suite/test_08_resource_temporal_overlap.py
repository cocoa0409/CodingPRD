"""Two intervals with opposite geometry over the same instants.

A dock window is half-open with an aggregate allowance, so appointments may share
a slot up to capacity and a shipment starting where another ends is no conflict at
all. A billing period is closed at both ends with no allowance, so the touching
instant that the dock accepts is exactly what the invoice refuses. The pair is
driven below on the same instants, because one shared overlap helper cannot
satisfy both.
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
    assert_invoice_figures,
    assert_job_state,
)
from test_helpers.test_users import ACCEPTANCE_CLERK, POSTAGE_MANAGER, PRESORT_OPERATOR

# The four bookings of the dock scenario, in the order they are made.
WINDOW_08_16 = (f.instant(2026, 8, 12, 8, 0, 0), f.instant(2026, 8, 12, 16, 0, 0))
WINDOW_16_20 = (f.instant(2026, 8, 12, 16, 0, 0), f.instant(2026, 8, 12, 20, 0, 0))
WINDOW_12_14 = (f.instant(2026, 8, 12, 12, 0, 0), f.instant(2026, 8, 12, 14, 0, 0))


def _book(api, world, batch_key, window, pallet_count):
    """Request one appointment at the dock world's facility."""
    start, end = window
    return api.create_drop_shipment(
        f.drop_shipment_payload(
            world[f"{batch_key}_id"],
            world.facility_id,
            start,
            end,
            pallet_count=pallet_count,
        ),
        PRESORT_OPERATOR,
    )


class TestDockHalfOpenAggregateCapacity:
    """Twelve pallets of capacity, four bookings, one refusal."""

    def test_an_appointment_starting_where_another_ends_does_not_overlap(self, api):
        """Adjacency is free under half-open geometry.

        "Of those candidates, keep the ones whose window overlaps the requested window
        under half-open geometry: a candidate overlaps when its own `window_start_utc` is
        strictly earlier than the requested `window_end_utc` **and** the requested
        `window_start_utc` is strictly earlier than the candidate's `window_end_utc`.
        Touching endpoints therefore do not overlap at all — a shipment beginning at the
        exact instant another ends is never a conflict."

        Design: Difficulty/resource_temporal_overlap/dock_half_open_aggregate_capacity_at_facility
        """
        world = fx.build_dock_world(api)

        first = validate_success(
            _book(api, world, "batch_1", WINDOW_08_16, 8), expected_status=201
        )
        assert_field_values(first, {"status": "SCHEDULED", "pallet_count": 8})

        # 8 pallets already stand over 08:00 to 16:00; a further 8 from 16:00 would
        # breach the 12-pallet dock if the instant were shared.
        second = validate_success(
            _book(api, world, "batch_2", WINDOW_16_20, 8), expected_status=201
        )
        assert_field_values(second, {"status": "SCHEDULED", "pallet_count": 8})

    def test_the_aggregate_at_exactly_capacity_is_accepted(self, api):
        """The comparison is strictly greater than, so equality passes.

        "Sum the `pallet_count` of the overlapping shipments to get the pallets already
        occupied. The booking is refused with `ERR_DOCK_CAPACITY_EXCEEDED` exactly when
        those occupied pallets plus the requested `pallet_count` are strictly greater
        than the facility's `dock_capacity_pallets_per_slot`; a total exactly equal to
        capacity is accepted."

        Design: Difficulty/resource_temporal_overlap/dock_half_open_aggregate_capacity_at_facility
        """
        world = fx.build_dock_world(api)
        validate_success(_book(api, world, "batch_1", WINDOW_08_16, 8), expected_status=201)
        validate_success(_book(api, world, "batch_2", WINDOW_16_20, 8), expected_status=201)

        # 8 occupied over the overlapping window plus 4 requested is exactly 12.
        third = validate_success(
            _book(api, world, "batch_3", WINDOW_12_14, 4), expected_status=201
        )
        assert_field_values(third, {"status": "SCHEDULED", "pallet_count": 4})

    def test_one_pallet_over_capacity_is_refused_however_small_it_is(self, api):
        """Capacity is aggregate over overlapping shipments, not per shipment.

        "The dock itself is an **aggregate capacity**, not an exclusive slot." "Any
        number of shipments may share a window as long as their pallets sum within
        capacity."

        Design: Difficulty/resource_temporal_overlap/dock_half_open_aggregate_capacity_at_facility
        """
        world = fx.build_dock_world(api)
        validate_success(_book(api, world, "batch_1", WINDOW_08_16, 8), expected_status=201)
        validate_success(_book(api, world, "batch_2", WINDOW_16_20, 8), expected_status=201)
        validate_success(_book(api, world, "batch_3", WINDOW_12_14, 4), expected_status=201)

        # The fourth booking asks for a single pallet over a two-hour window and is
        # still refused, because 12 are already committed across the overlap.
        validate_error(
            _book(api, world, "batch_4", WINDOW_12_14, 1),
            e.ERR_DOCK_CAPACITY_EXCEEDED,
            expected_status=409,
        )

    def test_the_refused_booking_left_the_facility_with_three_appointments(self, api):
        """No row is written for a booking that was never accepted.

        The candidates for the next booking are drawn from what stands: "take every drop
        shipment at the same facility whose status is `SCHEDULED` or `IN_TRANSIT`;
        shipments in `CANCELLED`, `NO_SHOW` or `DEPOSITED` have released their pallets
        and take no part."

        Design: Difficulty/resource_temporal_overlap/dock_half_open_aggregate_capacity_at_facility
        """
        world = fx.build_dock_world(api)
        validate_success(_book(api, world, "batch_1", WINDOW_08_16, 8), expected_status=201)
        validate_success(_book(api, world, "batch_2", WINDOW_16_20, 8), expected_status=201)
        validate_success(_book(api, world, "batch_3", WINDOW_12_14, 4), expected_status=201)
        validate_error(
            _book(api, world, "batch_4", WINDOW_12_14, 1), e.ERR_DOCK_CAPACITY_EXCEEDED
        )

        shipments, meta = validate_paginated(
            api.list_facility_drop_shipments(world.facility_id, PRESORT_OPERATOR)
        )
        assert meta["total_count"] == 3
        assert [s["pallet_count"] for s in shipments] == [8, 8, 4]

        own, own_meta = validate_paginated(
            api.list_batch_drop_shipments(world.batch_4_id, PRESORT_OPERATOR)
        )
        assert own == [] and own_meta["total_count"] == 0


class TestBillingPeriodClosedIntervalExclusivity:
    """One August invoice, then a period that only touches it."""

    def test_the_august_period_bills_the_month_it_covers(self, api):
        """The first period has no history to conflict with.

        "A `PostageManager` issues an invoice to a client for a closed billing period
        bounded by `period_start_utc` and `period_end_utc`, the latter strictly after the
        former." Selection is by the mailing instant: "select the client's jobs that are
        in `MAILED` and whose `mailed_at_utc` falls inside the requested period treated as
        closed at both ends, ordered by `created_at` ascending."

        Design: Difficulty/resource_temporal_overlap/billing_period_closed_interval_pairwise_exclusivity
        """
        world = fx.build_deposited_world(api)

        invoice = validate_success(
            api.create_client_invoice(
                world.acme_id,
                f.invoice_payload(f.AUGUST_2026_START, f.AUGUST_2026_END),
                POSTAGE_MANAGER,
            ),
            expected_status=201,
        )
        assert_field_values(
            invoice,
            {
                "period_start_utc": f.AUGUST_2026_START,
                "period_end_utc": f.AUGUST_2026_END,
            },
        )
        assert_invoice_figures(
            invoice,
            status="ISSUED",
            billed_piece_count=fx.JOB_A_ACCEPTED,
            included_job_count=1,
            postage_cents=fx.MEMBER_A_POSTAGE_CENTS,
            adjustment_cents=0,
            service_fee_cents=2500,
            total_cents=34160,
        )

    def test_a_period_starting_on_the_previous_end_instant_is_refused(self, api):
        """Under closed geometry the shared instant would be billed twice.

        "a conflict exists as soon as one is found whose `period_end_utc` is at or after
        the requested `period_start_utc` **and** whose `period_start_utc` is at or before
        the requested `period_end_utc`". "Adjacency is a conflict: a new period starting
        exactly on a prior period's end instant is rejected, because that instant would
        otherwise be billed twice."

        Design: Difficulty/resource_temporal_overlap/billing_period_closed_interval_pairwise_exclusivity
        """
        world = fx.build_deposited_world(api)
        validate_success(
            api.create_client_invoice(
                world.acme_id,
                f.invoice_payload(f.AUGUST_2026_START, f.AUGUST_2026_END),
                POSTAGE_MANAGER,
            ),
            expected_status=201,
        )

        validate_error(
            api.create_client_invoice(
                world.acme_id,
                f.invoice_payload(f.AUGUST_2026_END, f.SEPTEMBER_2026_END),
                POSTAGE_MANAGER,
            ),
            e.ERR_BILLING_PERIOD_OVERLAP,
            expected_status=409,
        )

    def test_the_two_resources_do_not_share_one_overlap_rule(self, api):
        """The dock accepts the very geometry the invoice rejects.

        "Before anything is computed, the period is tested for exclusivity against the
        client's own history, and the geometry here is deliberately the opposite of the
        dock rule: the interval is **closed at both ends** and there is no aggregate
        allowance."

        Design: Difficulty/resource_temporal_overlap/billing_period_closed_interval_pairwise_exclusivity
        """
        world = fx.build_deposited_world(api)
        validate_success(
            api.create_client_invoice(
                world.acme_id,
                f.invoice_payload(f.AUGUST_2026_START, f.AUGUST_2026_END),
                POSTAGE_MANAGER,
            ),
            expected_status=201,
        )
        validate_error(
            api.create_client_invoice(
                world.acme_id,
                f.invoice_payload(f.AUGUST_2026_END, f.SEPTEMBER_2026_END),
                POSTAGE_MANAGER,
            ),
            e.ERR_BILLING_PERIOD_OVERLAP,
        )

        # One millisecond of separation clears exclusivity, and the refusal then moves
        # to the empty-selection rule instead of the overlap rule.
        validate_error(
            api.create_client_invoice(
                world.acme_id,
                f.invoice_payload(f.SEPTEMBER_2026_START, f.SEPTEMBER_2026_END),
                POSTAGE_MANAGER,
            ),
            e.ERR_NO_BILLABLE_JOBS,
            expected_status=422,
        )

    def test_neither_refusal_billed_the_job_a_second_time(self, api):
        """Exactly one invoice exists, and the job left MAILED exactly once.

        "If that selection is empty the request is rejected with
        `ERR_NO_BILLABLE_JOBS`." A billed job cannot be selected again: "Every included
        job moves `MAILED → BILLED` with its `version` incremented, which is what makes
        re-issuing over the same jobs impossible — they are no longer in `MAILED` and so
        cannot be selected again."

        Design: Difficulty/resource_temporal_overlap/billing_period_closed_interval_pairwise_exclusivity
        """
        world = fx.build_deposited_world(api)
        validate_success(
            api.create_client_invoice(
                world.acme_id,
                f.invoice_payload(f.AUGUST_2026_START, f.AUGUST_2026_END),
                POSTAGE_MANAGER,
            ),
            expected_status=201,
        )
        validate_error(
            api.create_client_invoice(
                world.acme_id,
                f.invoice_payload(f.AUGUST_2026_END, f.SEPTEMBER_2026_END),
                POSTAGE_MANAGER,
            ),
            e.ERR_BILLING_PERIOD_OVERLAP,
        )
        validate_error(
            api.create_client_invoice(
                world.acme_id,
                f.invoice_payload(f.SEPTEMBER_2026_START, f.SEPTEMBER_2026_END),
                POSTAGE_MANAGER,
            ),
            e.ERR_NO_BILLABLE_JOBS,
        )

        invoices, meta = validate_paginated(
            api.list_client_invoices(world.acme_id, POSTAGE_MANAGER)
        )
        assert meta["total_count"] == 1 and len(invoices) == 1
        job_a = validate_success(api.get_mail_job(world.job_a_id, ACCEPTANCE_CLERK))
        assert_job_state(job_a, "BILLED")
