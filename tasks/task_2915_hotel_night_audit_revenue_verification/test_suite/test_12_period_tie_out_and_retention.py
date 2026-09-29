"""Month-end tie-out, the open-date gate, archival and the retention horizon.

Covers PRD section 3.9 (tying out an accounting period, archiving its days and
computing the retention horizon) together with the period minting of PRD
section 3.1.
"""

from prd_bench_local_runner.testing import validate_error, validate_success

from test_helpers import api_errors as E
from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.assertions import assert_fields, assert_int, assert_money, assert_row_count
from test_helpers.test_users import AUDITOR, CONTROLLER


def _period_with_one_closed_day_and_one_open_day(api):
    """A period holding a CLOSED 2026-08-01 worth 217.75 and an untouched OPEN 2026-08-02."""
    fx.set_clock(api, "2026-08-01T09:00:00.000Z")
    prop = fx.create_property(api)
    day_one = fx.create_business_date(
        api,
        prop["id"],
        "2026-08-01",
        out_of_order_room_count=4,
        benchmark_calendar_room_revenue_amount=400.00,
        benchmark_weekday_room_revenue_amount=520.00,
    )
    folio = fx.create_folio(
        api,
        prop["id"],
        day_one["id"],
        confirmation_code="CF-TIE1",
        guest_name="Wen Ivar",
        room_number="1101",
        nights_count=1,
        contracted_rate_amount=200.00,
        scheduled_checkout_at="2026-08-02T11:00:00.000Z",
    )
    fx.check_in(api, folio["id"])
    fx.drive_to_closed(api, day_one["id"])
    day_two = fx.create_business_date(api, prop["id"], "2026-08-02", out_of_order_room_count=4)
    return prop, day_one, day_two


def test_a_single_open_day_refuses_the_whole_tie_out(api):
    """The open-date gate is a hard refusal, not a quiet exclusion from the arithmetic.

    PRD section 3.9 requires every operating day of the period to be CLOSED or ARCHIVED and
    otherwise refuses the attempt with ERR_PERIOD_HAS_OPEN_DATES (HTTP 409), leaving the
    period OPEN with `tie_out_attempt_count` at zero, `tie_out_variance_amount` and
    `audit_trail_retention_until_date` null, and the already-closed day unarchived. The
    period still reports its `subsystem_total_amount` of 217.75 over that one closed day.

    Design: Difficulty/cross_entity_state_dependency/period_tie_out_gated_on_every_child_date_being_closed
    """
    _prop, day_one, day_two = _period_with_one_closed_day_and_one_open_day(api)
    period_id = day_one["accounting_period_id"]

    validate_error(
        api.tie_out_period(period_id, f.build_tie_out_payload(217.75), CONTROLLER),
        E.ERR_PERIOD_HAS_OPEN_DATES,
    )

    period = fx.read_period(api, period_id)
    assert_fields(
        period,
        {
            "status": "OPEN",
            "tie_out_variance_amount": None,
            "audit_trail_retention_until_date": None,
        },
    )
    assert_int(period["tie_out_attempt_count"], 0, "tie_out_attempt_count")
    assert_money(period["subsystem_total_amount"], 217.75, "subsystem_total_amount")

    assert_fields(fx.read_business_date(api, day_one["id"]), {"status": "CLOSED"})
    assert_fields(fx.read_business_date(api, day_two["id"]), {"status": "OPEN"})

    both = validate_success(
        api.list_business_dates(AUDITOR, accounting_period_id=period_id)
    )
    assert_row_count(both, 2, "operating days of the period")


def test_closing_the_last_day_lets_the_period_tie_out_and_archive(api):
    """A zero variance passes, archives every closed day and sets the seven-year horizon.

    PRD section 3.9 passes an attempt only on an absolute variance of exactly 0.00, and a
    passing attempt sets TIED_OUT, archives every CLOSED day of the period and computes
    `audit_trail_retention_until_date` from `period_month` alone — the last calendar day of
    2026-08 advanced by seven years, which is 2033-08-31. The second day contributes nothing
    to the 217.75 subsystem total because it never carried a charge.

    Design: Difficulty/cross_entity_state_dependency/period_tie_out_gated_on_every_child_date_being_closed
    """
    _prop, day_one, day_two = _period_with_one_closed_day_and_one_open_day(api)
    period_id = day_one["accounting_period_id"]

    fx.drive_to_closed(api, day_two["id"])
    tied = validate_success(
        api.tie_out_period(period_id, f.build_tie_out_payload(217.75), CONTROLLER)
    )
    assert_fields(tied, {"status": "TIED_OUT", "audit_trail_retention_until_date": "2033-08-31"})
    assert_money(tied["tie_out_variance_amount"], 0.00, "tie_out_variance_amount")
    assert_money(tied["subsystem_total_amount"], 217.75, "subsystem_total_amount")
    assert tied["tied_out_by_user_id"] == CONTROLLER["X-User-ID"], (
        "expected the acting Controller on tied_out_by_user_id, got "
        f"{tied['tied_out_by_user_id']!r}"
    )

    assert_fields(fx.read_business_date(api, day_one["id"]), {"status": "ARCHIVED"})
    assert_fields(fx.read_business_date(api, day_two["id"]), {"status": "ARCHIVED"})
