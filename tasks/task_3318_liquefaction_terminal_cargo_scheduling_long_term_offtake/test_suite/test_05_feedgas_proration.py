"""Feed-gas pipelines, day schedules, nominations, and the proration waterfall."""
import pytest

from test_helpers import (
    CM,
    GS,
    MS,
    OP,
    ApiErrorId,
    NON_EXISTENT_UUID,
    begin_turnaround_at,
    create_commercial_train,
    create_confirmed_adp_with_slots,
    create_day_schedule_payload,
    create_nomination_payload,
    create_pipeline_payload,
    get_success_data,
    propose_and_approve_turnaround,
    setup_proration_schedule,
    validate_error,
    validate_success,
)


class TestProration:
    def test_proration_floor_and_largest_remainder(self, api):
        """PRD §3.6: "Otherwise a pro-rata factor is formed as the day's capacity
        divided by the total nominated volume, and each nomination's base
        allocation is the smallest of three quantities: its nominated volume, a
        floor of 5,000 MMBTU applied as the lesser of the nomination's volume and
        the floor itself, or its nominated volume times the factor rounded down to
        a whole MMBTU. The remainder — capacity minus the sum of base allocations —
        is then distributed one MMBTU at a time to the nominations with the
        largest fractional part of their nominated-times-factor product, ties on
        the fractional part broken by nomination creation time with the earliest
        first, and no nomination may receive more than it nominated."
        (Capacity 100,000 vs 60,000/50,000/20,000 -> 46,154 / 38,461 / 15,385.)

        Design: Difficulty/combinatorial_formula/proration_floor_and_largest_remainder
        """
        ctx = setup_proration_schedule()
        nom_a, nom_b, nom_c = ctx["nominations"]
        assert nom_a["confirmed_mmbtu"] == 46154, (
            f"nomination A must be confirmed at 46154, got {nom_a['confirmed_mmbtu']}"
        )
        assert nom_a["cut_mmbtu"] == 13846
        assert nom_a["status"] == "CONFIRMED"
        assert nom_b["confirmed_mmbtu"] == 38461
        assert nom_b["cut_mmbtu"] == 11539
        assert nom_c["confirmed_mmbtu"] == 15385
        assert nom_c["cut_mmbtu"] == 4615
        schedule = get_success_data(api.get_day_schedule(ctx["schedule"]["id"], GS))
        assert schedule["total_confirmed_mmbtu"] == 100000

    def test_proration_cut_equals_nominated_minus_confirmed(self, api):
        """PRD §3.6: "A nomination whose confirmed volume comes out at zero becomes
        `CUT` with `cut_mmbtu` equal to its `nominated_mmbtu`; every other
        nomination becomes `CONFIRMED`."
        PRD §3.6: "`total_cut_mmbtu` over `CUT` nominations plus the cut volume on
        `CONFIRMED` nominations."

        Design: Difficulty/combinatorial_formula/proration_floor_and_largest_remainder
        """
        ctx = setup_proration_schedule()
        for nom in ctx["nominations"]:
            assert (
                nom["nominated_mmbtu"] - nom["confirmed_mmbtu"] == nom["cut_mmbtu"]
            ), (
                f"cut must equal nominated minus confirmed for nomination {nom['id']}"
            )
            assert nom["status"] == "CONFIRMED"
        schedule = get_success_data(api.get_day_schedule(ctx["schedule"]["id"], GS))
        assert schedule["total_cut_mmbtu"] == 30000

    def test_proration_no_scaling_under_capacity(self, api):
        """PRD §3.6: "If the total nominated volume is no more than the day's
        capacity, every nomination is confirmed in full: `confirmed_mmbtu` equals
        `nominated_mmbtu`, `cut_mmbtu` is zero, and the nomination becomes
        `CONFIRMED`."

        Design: Corner/calculations/proration_no_scaling_under_capacity
        """
        ctx = setup_proration_schedule(nomination_amounts=(60000, 30000))
        nom_a, nom_b = ctx["nominations"]
        assert nom_a["confirmed_mmbtu"] == 60000
        assert nom_a["cut_mmbtu"] == 0
        assert nom_b["confirmed_mmbtu"] == 30000
        assert nom_b["cut_mmbtu"] == 0
        schedule = get_success_data(api.get_day_schedule(ctx["schedule"]["id"], GS))
        assert schedule["total_confirmed_mmbtu"] == 90000
        assert schedule["total_cut_mmbtu"] == 0

    def test_pipeline_day_gas_conservation_after_close(self, api):
        """PRD §3.6: "The conservation invariant holds at all times: the sum of
        confirmed volumes plus the sum of cut volumes equals the sum of nominated
        volumes."

        Design: Difficulty/compensating_invariant/pipeline_day_gas_conservation
        """
        ctx = setup_proration_schedule()
        schedule = get_success_data(api.get_day_schedule(ctx["schedule"]["id"], GS))
        assert schedule["total_nominated_mmbtu"] == 130000
        assert schedule["total_confirmed_mmbtu"] == 100000
        assert schedule["total_cut_mmbtu"] == 30000
        assert (
            schedule["total_confirmed_mmbtu"] + schedule["total_cut_mmbtu"]
            == schedule["total_nominated_mmbtu"]
        )

    def test_pipeline_day_gas_conservation_after_cancellation(self, api):
        """PRD §3.6: "The conservation invariant holds at all times: the sum of
        confirmed volumes plus the sum of cut volumes equals the sum of nominated
        volumes."
        PRD §3.7: "Every feed-gas nomination of the slot still in `SUBMITTED` or
        `CONFIRMED` becomes `CUT` with `confirmed_mmbtu` set to zero and
        `cut_mmbtu` set to its `nominated_mmbtu`, and each such cut triggers a
        recompute of its day schedule's totals and a fresh run of the proration
        waterfall over that schedule's remaining non-`CUT` nominations."

        Design: Difficulty/compensating_invariant/pipeline_day_gas_conservation
        """
        ctx = setup_proration_schedule()
        get_success_data(api.set_clock("2027-04-15T00:00:00Z", OP))
        # cancel slot B (the second slot, nomination 50,000)
        get_success_data(api.cancel_cargo_slot(ctx["slots"][1]["id"], ctx["rep"]))
        schedule = get_success_data(api.get_day_schedule(ctx["schedule"]["id"], GS))
        assert schedule["total_nominated_mmbtu"] == 130000
        assert schedule["total_confirmed_mmbtu"] == 80000, (
            f"re-proration must restore surviving nominations to full volume, got "
            f"{schedule['total_confirmed_mmbtu']}"
        )
        assert schedule["total_cut_mmbtu"] == 50000
        assert (
            schedule["total_confirmed_mmbtu"] + schedule["total_cut_mmbtu"]
            == schedule["total_nominated_mmbtu"]
        )

    def test_cancellation_depth3_reproration_cascade(self, api):
        """PRD §3.7: "Cancellation cascades widely. The slot's `lift_status`
        becomes `CANCELLED`. Every feed-gas nomination of the slot still in
        `SUBMITTED` or `CONFIRMED` becomes `CUT` with `confirmed_mmbtu` set to zero
        and `cut_mmbtu` set to its `nominated_mmbtu`, and each such cut triggers a
        recompute of its day schedule's totals and a fresh run of the proration
        waterfall over that schedule's remaining non-`CUT` nominations."
        PRD §3.7: "the fixed fee `fixed_fee_due_usd` is computed immediately as the
        slot's `quantity_mmbtu` times the SPA's `fixed_liquefaction_fee_usd_per_mmbtu`".

        Design: Difficulty/transitive_cascade/cancellation_depth3_reproration_cascade
        """
        ctx = setup_proration_schedule()
        nom_a, nom_b, nom_c = [n["id"] for n in ctx["nominations"]]
        get_success_data(api.set_clock("2027-04-15T00:00:00Z", OP))
        cancellation = get_success_data(
            api.cancel_cargo_slot(ctx["slots"][1]["id"], ctx["rep"])
        )
        slot_b = get_success_data(api.get_cargo_slot(ctx["slots"][1]["id"], CM))
        assert slot_b["lift_status"] == "CANCELLED"
        nb = get_success_data(api.get_nomination(nom_b, GS))
        assert nb["status"] == "CUT"
        assert nb["confirmed_mmbtu"] == 0
        assert nb["cut_mmbtu"] == 50000
        na = get_success_data(api.get_nomination(nom_a, GS))
        nc = get_success_data(api.get_nomination(nom_c, GS))
        assert na["confirmed_mmbtu"] == 60000, (
            f"re-proration must restore nomination A to full volume, got "
            f"{na['confirmed_mmbtu']}"
        )
        assert nc["confirmed_mmbtu"] == 20000
        # fixed fee = 5,000,000 * 3.50 == 17,500,000.00
        assert cancellation["fixed_fee_due_usd"] == pytest.approx(17500000.00, abs=0.01)

    def test_cancellation_cascade_recomputes_schedule_totals(self, api):
        """PRD §3.7: "each such cut triggers a recompute of its day schedule's
        totals and a fresh run of the proration waterfall over that schedule's
        remaining non-`CUT` nominations."
        PRD §3.6: "`total_nominated_mmbtu` over all nominations regardless of
        status, `total_confirmed_mmbtu` over `CONFIRMED` nominations, and
        `total_cut_mmbtu` over `CUT` nominations plus the cut volume on `CONFIRMED`
        nominations."

        Design: Difficulty/transitive_cascade/cancellation_depth3_reproration_cascade
        """
        ctx = setup_proration_schedule()
        get_success_data(api.set_clock("2027-04-15T00:00:00Z", OP))
        get_success_data(api.cancel_cargo_slot(ctx["slots"][1]["id"], ctx["rep"]))
        schedule = get_success_data(api.get_day_schedule(ctx["schedule"]["id"], GS))
        assert schedule["total_nominated_mmbtu"] == 130000
        assert schedule["total_confirmed_mmbtu"] == 80000
        assert schedule["total_cut_mmbtu"] == 50000


class TestScheduleLifecycle:
    def test_schedule_double_close_and_late_nomination_rejected(self, api):
        """PRD §3.6: "A `GasScheduler` closes an `OPEN` schedule — closing twice
        is rejected with `ERR_SCHEDULE_INVALID_STATE`". PRD §3.6: "Nominating
        against a schedule that has been closed is rejected with
        `ERR_SCHEDULE_INVALID_STATE`".

        Design: Corner/state_machines/schedule_double_close_and_late_nomination_rejected
        """
        pipeline = get_success_data(
            api.create_pipeline(create_pipeline_payload(), OP)
        )
        schedule = get_success_data(
            api.create_day_schedule(
                pipeline["id"], create_day_schedule_payload(), GS
            )
        )
        get_success_data(api.close_day_schedule(schedule["id"], GS))
        resp = api.close_day_schedule(schedule["id"], GS)
        err = validate_error(resp, ApiErrorId.ERR_SCHEDULE_INVALID_STATE.value)
        assert err["error_id"] == "ERR_SCHEDULE_INVALID_STATE"
        schedule = get_success_data(api.get_day_schedule(schedule["id"], GS))
        assert schedule["status"] == "CLOSED"

    def test_late_nomination_with_bogus_slot_is_not_found(self, api):
        """PRD §2.6: "Body-supplied foreign-key references — `customer_id`,
        `spa_id`, `berth_id`, `cargo_slot_id`, and their analogues — are likewise
        validated for existence, and a dangling reference produces the same
        `ERR_NOT_FOUND`." PRD §2.9: "then existence of every path identifier and
        referenced body foreign key, then state legality of the requested
        transition". (Existence precedes state legality, so a dangling
        cargo_slot_id on a CLOSED schedule surfaces the not-found error.)

        Design: Corner/state_machines/schedule_double_close_and_late_nomination_rejected
        """
        pipeline = get_success_data(api.create_pipeline(create_pipeline_payload(), OP))
        schedule = get_success_data(
            api.create_day_schedule(pipeline["id"], create_day_schedule_payload(), GS)
        )
        get_success_data(api.close_day_schedule(schedule["id"], GS))
        resp = api.create_nomination(
            schedule["id"],
            {"cargo_slot_id": NON_EXISTENT_UUID, "nominated_mmbtu": 10000},
            GS,
        )
        err = validate_error(resp, ApiErrorId.ERR_NOT_FOUND.value)
        assert err["error_id"] == "ERR_NOT_FOUND"
        schedule = get_success_data(api.get_day_schedule(schedule["id"], GS))
        assert schedule["status"] == "CLOSED"

    def test_schedule_capacity_exceeds_pipeline(self, api):
        """PRD §3.6: "the firm `capacity_mmbtu` offered that day, which must be
        greater than zero and no more than the pipeline's daily capacity; breaches
        of either rule are rejected with `ERR_SCHEDULE_CAPACITY_EXCEEDED`."

        Design: Corner/validations/schedule_capacity_exceeds_pipeline
        """
        pipeline = get_success_data(api.create_pipeline(create_pipeline_payload(), OP))
        resp = api.create_day_schedule(
            pipeline["id"],
            {"gas_day": "2027-06-03", "capacity_mmbtu": 500001},
            GS,
        )
        err = validate_error(resp, ApiErrorId.ERR_SCHEDULE_CAPACITY_EXCEEDED.value)
        assert err["error_id"] == "ERR_SCHEDULE_CAPACITY_EXCEEDED"

    def test_duplicate_gas_day_rejected(self, api):
        """PRD §3.6: "a `gas_day` (a calendar date unique per pipeline) and the
        firm `capacity_mmbtu` offered that day, which must be greater than zero and
        no more than the pipeline's daily capacity; breaches of either rule are
        rejected with `ERR_SCHEDULE_CAPACITY_EXCEEDED`."

        Design: Corner/validations/duplicate_gas_day_rejected
        """
        pipeline = get_success_data(api.create_pipeline(create_pipeline_payload(), OP))
        get_success_data(
            api.create_day_schedule(
                pipeline["id"],
                {"gas_day": "2027-06-03", "capacity_mmbtu": 100000},
                GS,
            )
        )
        resp = api.create_day_schedule(
            pipeline["id"],
            {"gas_day": "2027-06-03", "capacity_mmbtu": 200000},
            GS,
        )
        err = validate_error(resp, ApiErrorId.ERR_SCHEDULE_CAPACITY_EXCEEDED.value)
        assert err["error_id"] == "ERR_SCHEDULE_CAPACITY_EXCEEDED"

    def test_nomination_exceeds_slot_feed_gas(self, api):
        """PRD §3.6: "a `nominated_mmbtu` volume greater than zero and no more
        than the linked slot's `scheduled_feed_gas_mmbtu`; a volume outside that
        band is rejected with `ERR_NOMINATION_QUANTITY_MISMATCH`."

        Design: Corner/validations/nomination_exceeds_slot_feed_gas
        """
        ctx = create_confirmed_adp_with_slots([{"quantity_mmbtu": 5000000}])
        pipeline = get_success_data(
            api.create_pipeline(
                create_pipeline_payload(daily_capacity_mmbtu=6000000), OP
            )
        )
        schedule = get_success_data(
            api.create_day_schedule(
                pipeline["id"],
                {"gas_day": "2027-06-03", "capacity_mmbtu": 6000000},
                GS,
            )
        )
        # slot feed gas = ceil(5,000,000 * 1.10) == 5,500,000; one over fails
        resp = api.create_nomination(
            schedule["id"],
            create_nomination_payload(ctx["slots"][0]["id"], 5500001),
            GS,
        )
        err = validate_error(resp, ApiErrorId.ERR_NOMINATION_QUANTITY_MISMATCH.value)
        assert err["error_id"] == "ERR_NOMINATION_QUANTITY_MISMATCH"

    def test_nomination_during_pipeline_outage_rejected(self, api):
        """PRD §3.6: "nominating while the pipeline is in `OUTAGE` (a turnaround
        in progress) is rejected with `ERR_PIPELINE_NOT_SERVICEABLE`."
        PRD §2.10: "While any maintenance turnaround on any train is in progress,
        every berth is taken `OUT_OF_SERVICE` and every pipeline enters `OUTAGE`".

        Design: Corner/validations/nomination_during_pipeline_outage_rejected
        """
        ctx = create_confirmed_adp_with_slots([{"quantity_mmbtu": 3600000}])
        train = create_commercial_train()
        pipeline = get_success_data(api.create_pipeline(create_pipeline_payload(), OP))
        schedule = get_success_data(
            api.create_day_schedule(
                pipeline["id"], create_day_schedule_payload(), GS
            )
        )
        ta = propose_and_approve_turnaround(train["id"], "2027-03-01", "2027-03-05")
        begin_turnaround_at(ta["id"], "2027-03-01T00:00:00Z")
        resp = api.create_nomination(
            schedule["id"],
            create_nomination_payload(ctx["slots"][0]["id"], 10000),
            GS,
        )
        err = validate_error(resp, ApiErrorId.ERR_PIPELINE_NOT_SERVICEABLE.value)
        assert err["error_id"] == "ERR_PIPELINE_NOT_SERVICEABLE"

    def test_nomination_reconcile_from_submitted_rejected(self, api):
        """PRD §3.6: "the nomination's day schedule must already be `CLOSED`, and
        reconciling a nomination that is not `CONFIRMED` is rejected with
        `ERR_NOMINATION_INVALID_STATE`."

        Design: Corner/errors/nomination_reconcile_from_submitted_rejected
        """
        ctx = create_confirmed_adp_with_slots([{"quantity_mmbtu": 3600000}])
        pipeline = get_success_data(api.create_pipeline(create_pipeline_payload(), OP))
        schedule = get_success_data(
            api.create_day_schedule(
                pipeline["id"], create_day_schedule_payload(), GS
            )
        )
        nomination = get_success_data(
            api.create_nomination(
                schedule["id"],
                create_nomination_payload(ctx["slots"][0]["id"], 10000),
                GS,
            )
        )
        resp = api.reconcile_nomination(nomination["id"], GS)
        err = validate_error(resp, ApiErrorId.ERR_NOMINATION_INVALID_STATE.value)
        assert err["error_id"] == "ERR_NOMINATION_INVALID_STATE"

    def test_marine_scheduler_cannot_close_schedule(self, api):
        """PRD §2.1: "A request whose role is not listed for the target endpoint is
        rejected with `ERR_FORBIDDEN` (HTTP 403)." PRD §4: POST
        `/api/pipeline-day-schedules/{id}/close` is listed for `GasScheduler`.

        Design: Corner/rbac/marine_scheduler_cannot_close_schedule
        """
        pipeline = get_success_data(api.create_pipeline(create_pipeline_payload(), OP))
        schedule = get_success_data(
            api.create_day_schedule(
                pipeline["id"], create_day_schedule_payload(), GS
            )
        )
        resp = api.close_day_schedule(schedule["id"], MS)
        err = validate_error(resp, ApiErrorId.ERR_FORBIDDEN.value)
        assert err["error_id"] == "ERR_FORBIDDEN"
        schedule = get_success_data(api.get_day_schedule(schedule["id"], GS))
        assert schedule["status"] == "OPEN"
