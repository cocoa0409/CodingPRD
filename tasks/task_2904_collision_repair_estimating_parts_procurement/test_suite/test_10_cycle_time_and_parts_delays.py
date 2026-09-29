"""Late parts, the interruptions they cause, and the shop's cycle-time report card.

A vehicle sits in the building while the shop waits for an adjuster to answer a
supplement and for a supplier to deliver a back-ordered panel. Those two waits
often overlap, and the shop may only charge the customer's keys-to-keys clock
once for a single wall of dead time. These tests drive the logical clock through
such a day: a supplement is raised and answered, the late-parts report opens an
interruption against the overdue line, the part finally lands (or lands as the
wrong part), and the cycle-time read is asked to reconcile all of it.

Alongside the metrics they pin the live count of unclosed interruptions on the
order, which must come back down when the part arrives while the interruption
itself stays on the record with its duration stamped.
"""

from prd_bench_local_runner.testing import validate_success

from test_helpers import assertions as A
from test_helpers import constants as C
from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.test_users import (
    ESTIMATOR_HEADERS,
    PARTS_MANAGER_HEADERS,
    SHOP_ADMIN_HEADERS,
)

# Instants on the default clock day that the fixtures do not already name.
_T0100 = "2026-08-01T01:00:00Z"
_T0200 = "2026-08-01T02:00:00Z"
_T0230 = "2026-08-01T02:30:00Z"
_T0300 = "2026-08-01T03:00:00Z"
_T0400 = "2026-08-01T04:00:00Z"
_T0500 = "2026-08-01T05:00:00Z"
_T0600 = "2026-08-01T06:00:00Z"

# Two days on from check-in, and six hours after that.
_THIRD_DAY = "2026-08-03T00:00:00Z"
_THIRD_DAY_0600 = "2026-08-03T06:00:00Z"

# An instant six weeks away, for the clock-governance test.
_MID_SEPTEMBER = "2026-09-15T13:45:00Z"

_QUOTED_UNIT_CENTS = 20000
_LIST_PRICE_CENTS = 30000
_OWNER_DEDUCTIBLE_CENTS = 25000


def _locked_order_at_midnight(api):
    """A locked estimate on the default clock instant, with one 4.5 h body line.

    The owner's deductible is 25,000 cents so that the owner's share stays
    inside what the insurer authorised once the parts are bought, leaving the
    order free to place its orders and advance.
    """
    fx.set_clock(api, C.CLOCK_DEFAULT)
    return fx.locked_world(
        api, order_overrides={"deductible_cents": _OWNER_DEDUCTIBLE_CENTS}
    )


def _zero_discount_supplier(api, name):
    """An original-equipment dealer with no discount and a generous line cap."""
    return fx.create_vendor(api, name=name, max_qty_per_line=5)


def _ordered_oem_part(api, world, vendor_id, promised_eta):
    """One original-equipment part quoted, price-locked and ordered."""
    return fx.ordered_part(
        api,
        world["line_ids"][0],
        vendor_id,
        _QUOTED_UNIT_CENTS,
        promised_eta=promised_eta,
        list_price_cents=_LIST_PRICE_CENTS,
        qty=1,
    )


def _open_delay_count(api, order_id):
    return fx.read_order(api, order_id)["open_parts_delay_count"]


class TestCycleTimeOverInterruptions:
    """The keys-to-keys window, the interruptions inside it, and the net figure."""

    def test_an_overlapping_supplement_wait_and_parts_delay_are_charged_once(self, api):
        """Two hold-ups that overlap by an hour cost the shop one merged block.

        PRD: "Every surviving interval is clamped into the window, then sorted by start and by end, then merged — and the merge is closed at the boundary, so intervals that merely touch, with a gap of exactly zero, merge into one."
        PRD: "When a supplement wait and a parts delay overlap in time, those two sums together exceed `excluded_minutes`, and only `excluded_minutes` may ever be subtracted from the gross — which is precisely why the net figure is strictly greater than `gross_minutes` minus the two sums whenever two hold-ups overlap: two concurrent hold-ups are charged once, not twice."
        Design: Corner/calculations/cycle_time_merges_an_overlapping_supplement_wait_and_parts_delay
        """
        world = _locked_order_at_midnight(api)
        order_id = world["order_id"]
        vendor = _zero_discount_supplier(api, "Eastside Honda")
        part = _ordered_oem_part(api, world, vendor["id"], _T0230)

        # 02:00 — the estimator asks the adjuster for more money.
        fx.set_clock(api, _T0200)
        supplement = fx.raise_supplement(
            api,
            order_id,
            reason_code="PARTS_PRICE_VARIANCE",
            requested_amount_cents=12000,
        )
        A.assert_instant(supplement["submitted_at"], _T0200, "submitted_at")

        # 03:00 — the promised arrival has slipped, so the sweep opens a delay.
        fx.set_clock(api, _T0300)
        sweep = validate_success(
            api.run_parts_delay_sweep(order_id, None, PARTS_MANAGER_HEADERS)
        )
        A.assert_count(sweep["opened_count"], 1, "opened_count")
        A.assert_count(sweep["open_parts_delay_count"], 1, "open_parts_delay_count")
        A.assert_count(_open_delay_count(api, order_id), 1, "open_parts_delay_count")

        # 04:00 — the adjuster says no, which closes the supplement's wait.
        fx.set_clock(api, _T0400)
        decided = fx.decide_supplement(api, supplement["id"], world["insurer_id"], "DENY")
        A.assert_instant(decided["decided_at"], _T0400, "decided_at")

        # 05:00 — the right part lands, closing the delay.
        fx.set_clock(api, _T0500)
        fx.receive_part(api, part["id"], 1, "CORRECT")
        A.assert_count(_open_delay_count(api, order_id), 0, "open_parts_delay_count")

        # 06:00 — the report card is read on an undelivered order.
        fx.set_clock(api, _T0600)
        metrics = validate_success(api.get_cycle_time(order_id, SHOP_ADMIN_HEADERS))
        A.assert_count(metrics["gross_minutes"], 360, "gross_minutes")
        A.assert_count(
            metrics["supplement_wait_minutes"], 120, "supplement_wait_minutes"
        )
        A.assert_count(metrics["parts_delay_minutes"], 120, "parts_delay_minutes")
        A.assert_count(metrics["excluded_minutes"], 180, "excluded_minutes")
        A.assert_count(metrics["net_touch_minutes"], 180, "net_touch_minutes")
        unmerged_sum = (
            metrics["supplement_wait_minutes"] + metrics["parts_delay_minutes"]
        )
        assert metrics["net_touch_minutes"] > metrics["gross_minutes"] - unmerged_sum, (
            "the overlapping hour must not be subtracted twice: net "
            f"{metrics['net_touch_minutes']} should exceed "
            f"{metrics['gross_minutes']} - {unmerged_sum}"
        )
        A.assert_count(metrics["open_interval_count"], 0, "open_interval_count")

        rows, meta = fx.page(
            api.list_order_parts_delay_events(order_id, PARTS_MANAGER_HEADERS)
        )
        A.assert_page(meta, total_count=1)
        event = rows[0]
        assert event["reason"] == "ETA_BREACH", (
            f"delay reason: expected ETA_BREACH, got {event['reason']}"
        )
        A.assert_instant(event["opened_at"], _T0300, "opened_at")
        A.assert_instant(event["closed_at"], _T0500, "closed_at")
        A.assert_count(event["delay_minutes"], 120, "delay_minutes")

    def test_a_zero_length_supplement_wait_is_dropped_and_an_open_delay_runs_to_the_window_end(
        self, api
    ):
        """A wait answered in the same instant counts for nothing; an unfinished delay runs to the read.

        PRD: "Zero-length intervals are dropped."
        PRD: "Each parts delay event contributes one interval from its `opened_at` to its `closed_at`, or to the window end if it is still open."
        PRD: "Finally, `open_interval_count` is the number of assembled intervals whose end came from the window end rather than from a real closing instant, and it tells the reader how much of the report is still provisional."
        Design: Corner/calculations/cycle_time_drops_a_zero_length_wait_and_runs_an_open_delay_to_the_window_end
        """
        world = _locked_order_at_midnight(api)
        order_id = world["order_id"]
        vendor = _zero_discount_supplier(api, "Westside Honda")
        part = _ordered_oem_part(api, world, vendor["id"], _T0100)

        # 02:00 — raised and refused without the clock moving at all.
        fx.set_clock(api, _T0200)
        supplement = fx.raise_supplement(
            api, order_id, reason_code="HIDDEN_DAMAGE", requested_amount_cents=12000
        )
        decided = fx.decide_supplement(api, supplement["id"], world["insurer_id"], "DENY")
        A.assert_instant(decided["submitted_at"], _T0200, "submitted_at")
        A.assert_instant(decided["decided_at"], _T0200, "decided_at")

        # 03:00 — the sweep opens a delay that is never closed.
        fx.set_clock(api, _T0300)
        sweep = validate_success(
            api.run_parts_delay_sweep(order_id, None, PARTS_MANAGER_HEADERS)
        )
        A.assert_count(sweep["opened_count"], 1, "opened_count")

        # 05:00 — the report card is read with the delay still running.
        fx.set_clock(api, _T0500)
        metrics = validate_success(api.get_cycle_time(order_id, ESTIMATOR_HEADERS))
        A.assert_count(metrics["gross_minutes"], 300, "gross_minutes")
        A.assert_count(metrics["supplement_wait_minutes"], 0, "supplement_wait_minutes")
        A.assert_count(metrics["parts_delay_minutes"], 120, "parts_delay_minutes")
        A.assert_count(metrics["excluded_minutes"], 120, "excluded_minutes")
        A.assert_count(metrics["net_touch_minutes"], 180, "net_touch_minutes")
        A.assert_count(metrics["open_interval_count"], 1, "open_interval_count")

        rows, meta = fx.page(
            api.list_parts_line_delay_events(part["id"], PARTS_MANAGER_HEADERS)
        )
        A.assert_page(meta, total_count=1)
        A.assert_null(rows[0]["closed_at"], "closed_at")
        A.assert_null(rows[0]["delay_minutes"], "delay_minutes")


class TestTheLatePartsSweep:
    """The bulk late-parts report and the interruptions it opens."""

    def test_the_sweep_opens_one_event_for_the_overdue_line_and_nothing_on_a_rerun(
        self, api
    ):
        """Only the line whose promise has expired is written up, and never a second time.

        PRD: "Running the sweep opens one event, with `reason` `ETA_BREACH` and `opened_at` at the logical clock, for every `ORDERED` line on the order whose `promised_eta` has passed and that has no open event already."
        PRD: "It answers with an `opened_count` and the resulting `open_parts_delay_count`."
        PRD: "The sweep is idempotent within a clock instant: repeating it before the clock moves opens nothing, because every eligible line now already has an open event."
        Design: Corner/endpoints/the_delay_sweep_opens_one_event_per_overdue_line_and_never_twice
        """
        world = _locked_order_at_midnight(api)
        order_id = world["order_id"]
        vendor = _zero_discount_supplier(api, "Riverside Honda")
        late = _ordered_oem_part(api, world, vendor["id"], _T0200)
        on_time = _ordered_oem_part(api, world, vendor["id"], fx.NEXT_DAY)

        # 03:00 — one promise has expired, the other has not.
        fx.set_clock(api, _T0300)
        sweep = validate_success(
            api.run_parts_delay_sweep(order_id, None, PARTS_MANAGER_HEADERS)
        )
        A.assert_count(sweep["opened_count"], 1, "opened_count")
        A.assert_count(sweep["open_parts_delay_count"], 1, "open_parts_delay_count")

        late_rows, late_meta = fx.page(
            api.list_parts_line_delay_events(late["id"], PARTS_MANAGER_HEADERS)
        )
        A.assert_page(late_meta, total_count=1)
        assert late_rows[0]["reason"] == "ETA_BREACH", (
            f"delay reason: expected ETA_BREACH, got {late_rows[0]['reason']}"
        )
        A.assert_instant(late_rows[0]["opened_at"], _T0300, "opened_at")
        A.assert_null(late_rows[0]["closed_at"], "closed_at")
        A.assert_null(late_rows[0]["delay_minutes"], "delay_minutes")

        _, on_time_meta = fx.page(
            api.list_parts_line_delay_events(on_time["id"], PARTS_MANAGER_HEADERS)
        )
        A.assert_page(on_time_meta, total_count=0)
        A.assert_count(_open_delay_count(api, order_id), 1, "open_parts_delay_count")

        # 04:00 — the clock has moved, but the line is already written up.
        fx.set_clock(api, _T0400)
        rerun = validate_success(
            api.run_parts_delay_sweep(order_id, None, PARTS_MANAGER_HEADERS)
        )
        A.assert_count(rerun["opened_count"], 0, "opened_count")
        A.assert_count(rerun["open_parts_delay_count"], 1, "open_parts_delay_count")
        A.assert_count(_open_delay_count(api, order_id), 1, "open_parts_delay_count")

    def test_receiving_the_wrong_part_opens_a_second_delay_rather_than_closing_the_first(
        self, api
    ):
        """The wrong panel is still booked in, but the shop is still waiting for the right one.

        PRD: "Receipt stamps `received_at` from the logical clock, records the `received_qty`, and computes `on_time` as whether `received_at` is at or before the `promised_eta` — a part arriving exactly at its promised instant is on time."
        PRD: "When the `condition` is anything other than `CORRECT`, nothing is closed; instead a new delay event is opened against the line with `reason` `INCORRECT_PART`, so the order's `open_parts_delay_count` stays raised."
        PRD: "The score is 100 multiplied by the sum of those three ratios each weighted in turn by 0.6 for on-time delivery, 0.25 for no returns and 0.15 for first-round agreement, the final product rounded half up to a whole number."
        Design: Corner/endpoints/receiving_the_wrong_part_opens_a_delay_instead_of_closing_one
        """
        world = _locked_order_at_midnight(api)
        order_id = world["order_id"]
        vendor = _zero_discount_supplier(api, "Lakeside Honda")
        part = _ordered_oem_part(api, world, vendor["id"], _T0200)

        fx.set_clock(api, _T0300)
        validate_success(api.run_parts_delay_sweep(order_id, None, PARTS_MANAGER_HEADERS))

        # 04:00 — the box arrives, and the wrong panel is inside it.
        fx.set_clock(api, _T0400)
        received = validate_success(
            api.receive_parts_line(
                part["id"], f.receive_payload(1, "INCORRECT"), PARTS_MANAGER_HEADERS
            )
        )
        A.assert_parts_line_state(received, procurement_status="RECEIVED")
        A.assert_count(received["received_qty"], 1, "received_qty")
        A.assert_instant(received["received_at"], _T0400, "received_at")
        assert received["on_time"] is False, (
            f"on_time: expected False for a 04:00 arrival against a 02:00 promise, "
            f"got {received['on_time']!r}"
        )

        rows, meta = fx.page(
            api.list_parts_line_delay_events(part["id"], PARTS_MANAGER_HEADERS)
        )
        A.assert_page(meta, total_count=2)
        breach = [row for row in rows if row["reason"] == "ETA_BREACH"]
        wrong_part = [row for row in rows if row["reason"] == "INCORRECT_PART"]
        assert len(breach) == 1 and len(wrong_part) == 1, (
            "expected one ETA_BREACH and one INCORRECT_PART event, got "
            f"{[row['reason'] for row in rows]}"
        )
        A.assert_null(breach[0]["closed_at"], "ETA_BREACH closed_at")
        A.assert_instant(
            wrong_part[0]["opened_at"], _T0400, "INCORRECT_PART opened_at"
        )
        assert wrong_part[0]["parts_line_id"] == part["id"], (
            "the new delay must belong to the line whose supply slipped: expected "
            f"{part['id']}, got {wrong_part[0]['parts_line_id']}"
        )
        A.assert_count(_open_delay_count(api, order_id), 2, "open_parts_delay_count")

        # One closed outcome, late, unreturned, agreed at the first round: 40.
        A.assert_scores(fx.read_vendor(api, vendor["id"]), 40, 40)


class TestTheLogicalClock:
    """Every server-stamped instant is read from the clock, per request."""

    def test_moving_the_clock_governs_new_stamps_and_leaves_old_ones_alone(self, api):
        """Two orders either side of one clock move carry different check-in instants.

        PRD: "An admin-only test-driving capability moves the clock to a supplied `to_iso8601` instant and answers with the resulting `current_utc`; instants already stamped onto existing rows are left untouched."
        PRD: "On creation the order's `checkin_at` is stamped from the logical clock, opening the cycle-time window; `stage` is `INTAKE`, `authorization_posture` is `OPEN`, `consent_state` is `NONE`, and `version` is 1."
        PRD: "The **first** finding on an order moves `stage` from `INTAKE` to `TEARDOWN`, recomputes `teardown_finding_count`, and increments the order's `version`."
        Design: Corner/endpoints/the_clock_endpoint_governs_every_system_timestamp
        """
        opening = validate_success(
            api.set_clock(f.clock_payload(C.CLOCK_DEFAULT), SHOP_ADMIN_HEADERS)
        )
        A.assert_instant(opening["current_utc"], C.CLOCK_DEFAULT, "current_utc")

        world = fx.open_order_world(api)
        early_id = world["order_id"]
        A.assert_instant(world["order"]["checkin_at"], C.CLOCK_DEFAULT, "checkin_at")

        moved = validate_success(
            api.set_clock(f.clock_payload(_MID_SEPTEMBER), SHOP_ADMIN_HEADERS)
        )
        A.assert_instant(moved["current_utc"], _MID_SEPTEMBER, "current_utc")
        assert set(moved.keys()) == {"current_utc"}, (
            "the clock answers with the bare current_utc projection, got keys "
            f"{sorted(moved.keys())}"
        )

        A.assert_instant(
            fx.read_order(api, early_id)["checkin_at"],
            C.CLOCK_DEFAULT,
            "checkin_at of the earlier order",
        )

        later = fx.create_repair_order(
            api, world["customer_id"], world["insurer_id"]
        )
        A.assert_instant(
            later["checkin_at"], _MID_SEPTEMBER, "checkin_at of the later order"
        )

        finding = fx.add_finding(api, early_id)
        A.assert_instant(finding["created_at"], _MID_SEPTEMBER, "finding created_at")
        reread = fx.read_order(api, early_id)
        A.assert_stage(reread, C.STAGE_TEARDOWN)
        A.assert_count(reread["teardown_finding_count"], 1, "teardown_finding_count")


class TestTheOpenDelayCountReconciles:
    """The live count of unclosed interruptions, up and back down again."""

    def test_the_open_delay_count_returns_to_zero_when_the_late_part_finally_lands(
        self, api
    ):
        """The arrival closes the interruption and keeps it on the record with its duration.

        PRD: "Three counters on the order are pure roll-ups and are recomputed rather than incremented: `teardown_finding_count` is the number of teardown findings on the order, `open_parts_delay_count` is the number of parts delay events on the order whose `closed_at` is still null, and `qc_inspection_count` is the number of inspections filed on the order."
        PRD: "When the `condition` is `CORRECT`, receipt **closes** every open delay event on that line, stamping each event's `closed_at` from the logical clock and computing its `delay_minutes` as the whole minutes, floored, between its `opened_at` and its `closed_at`; the order's `open_parts_delay_count` is then recomputed."
        Design: Corner/cross_cutting_complexity_layers/the_open_parts_delay_count_reconciles_when_a_late_part_arrives
        """
        world = _locked_order_at_midnight(api)
        order_id = world["order_id"]
        vendor = _zero_discount_supplier(api, "Harbour Honda")
        part = _ordered_oem_part(api, world, vendor["id"], fx.NEXT_DAY)
        A.assert_count(_open_delay_count(api, order_id), 0, "open_parts_delay_count")

        fx.advance_stage(api, order_id, C.STAGE_PARTS_STAGED)

        # Two days on, the promise is a day stale and the sweep says so.
        fx.set_clock(api, _THIRD_DAY)
        sweep = validate_success(
            api.run_parts_delay_sweep(order_id, None, PARTS_MANAGER_HEADERS)
        )
        A.assert_count(sweep["opened_count"], 1, "opened_count")
        A.assert_count(_open_delay_count(api, order_id), 1, "open_parts_delay_count")

        # Six hours later the right part lands, late.
        fx.set_clock(api, _THIRD_DAY_0600)
        received = validate_success(
            api.receive_parts_line(
                part["id"], f.receive_payload(1, "CORRECT"), PARTS_MANAGER_HEADERS
            )
        )
        A.assert_parts_line_state(received, procurement_status="RECEIVED")
        A.assert_instant(received["received_at"], _THIRD_DAY_0600, "received_at")
        assert received["on_time"] is False, (
            "on_time: expected False for an arrival a day after the promise, got "
            f"{received['on_time']!r}"
        )

        A.assert_count(_open_delay_count(api, order_id), 0, "open_parts_delay_count")

        rows, meta = fx.page(
            api.list_parts_line_delay_events(part["id"], PARTS_MANAGER_HEADERS)
        )
        A.assert_page(meta, total_count=1)
        event = rows[0]
        assert event["reason"] == "ETA_BREACH", (
            f"delay reason: expected ETA_BREACH, got {event['reason']}"
        )
        A.assert_instant(event["opened_at"], _THIRD_DAY, "opened_at")
        A.assert_instant(event["closed_at"], _THIRD_DAY_0600, "closed_at")
        A.assert_count(event["delay_minutes"], 360, "delay_minutes")

        # The closed interruption still feeds the cycle-time ledger.
        metrics = validate_success(api.get_cycle_time(order_id, SHOP_ADMIN_HEADERS))
        A.assert_count(metrics["gross_minutes"], 3240, "gross_minutes")
        A.assert_count(metrics["parts_delay_minutes"], 360, "parts_delay_minutes")

        A.assert_scores(fx.read_vendor(api, vendor["id"]), 40, 40)
