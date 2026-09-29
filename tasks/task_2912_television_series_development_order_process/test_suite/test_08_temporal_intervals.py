"""Opposite interval conventions: a closed holdback window and a half-open hold term."""

from prd_bench_local_runner.testing import validate_error, validate_success
from test_helpers import api_errors as e
from test_helpers import assertions as a
from test_helpers import factories as f
from test_helpers.constants import (
    DEV_ACTIVE_DEVELOPMENT,
    EXCLUSIVITY_HOLDING_DEAL,
    PITCH_ADVANCED,
    PITCH_COVERED,
    PLATFORM_BROADCAST,
    RIGHTS_RESULT_CLEAR,
    TERM_IN_TERM,
    TERM_PENDING_START,
)
from test_helpers import fixtures as fx
from test_helpers.fixtures import build_scenario
from test_helpers.test_users import (
    agency_rep_headers,
    business_affairs_headers,
    development_exec_headers,
)

SALT_ROAD = {
    "agency": {"name": "Fennmore Literary", "agency_code": "FEN"},
    "slate": {"platform": PLATFORM_BROADCAST},
    "pitch": {
        "title": "Salt Road",
        "logline": "A caravan of smugglers crosses a border that no longer exists.",
        "underlying_ip_key": "IP-SALT-ROAD",
    },
    "rights": {
        "underlying_ip_key": "IP-SALT-ROAD",
        "holdback_start_date": "2026-05-01",
        "holdback_end_date": "2026-06-01",
    },
}


def _salt_road(api):
    return build_scenario(api, "covered", **{k: dict(v) for k, v in SALT_ROAD.items()})


def test_the_last_day_of_the_closed_holdback_window_still_blocks_the_advance(api):
    """A CLEAR clearance is not enough while the clock sits on holdback_end_date itself.

    PRD 3.2: "if the logical clock's current date falls anywhere inside that newest
    check's closed holdback interval from `holdback_start_date` through
    `holdback_end_date`, or anywhere in the quiet buffer that runs through
    `quiet_period_end_date` inclusive, the advance is refused with
    `ERR_RIGHTS_HOLDBACK_CONFLICT` even though the title itself is clean."

    Design: Difficulty/resource_temporal_overlap/rights_holdback_closed_interval_and_quiet_buffer_are_both_inclusive
    """
    ctx = _salt_road(api)

    checks = validate_success(
        api.list_rights_checks(ctx.pitch_id, business_affairs_headers())
    )
    check = checks[-1]
    assert check["result"] == RIGHTS_RESULT_CLEAR
    assert check["quiet_period_end_date"] == "2026-08-30"

    fx.set_clock(api, "2026-06-01T00:00:00Z")
    refused = api.advance_pitch(ctx.pitch_id, development_exec_headers())
    validate_error(refused, e.ERR_RIGHTS_HOLDBACK_CONFLICT, 422)

    pitch = validate_success(api.get_pitch(ctx.pitch_id, business_affairs_headers()))
    assert pitch["status"] == PITCH_COVERED
    assert (
        validate_success(
            api.list_projects(business_affairs_headers(), {"pitch_id": ctx.pitch_id})
        )
        == []
    ), "no development project exists while the holdback still bites"


def test_the_quiet_buffer_clears_the_day_after_its_inclusive_last_day(api):
    """2026-08-30 still blocks and 2026-08-31 advances, so the buffer end is inclusive.

    PRD 3.2: "`quiet_period_end_date` extends the window by a quiet buffer of 90
    calendar days beyond `holdback_end_date`, inclusive".

    Design: Difficulty/resource_temporal_overlap/rights_holdback_closed_interval_and_quiet_buffer_are_both_inclusive
    """
    ctx = _salt_road(api)

    fx.set_clock(api, "2026-08-30T00:00:00Z")
    blocked = api.advance_pitch(ctx.pitch_id, development_exec_headers())
    validate_error(blocked, e.ERR_RIGHTS_HOLDBACK_CONFLICT, 422)
    assert (
        validate_success(api.get_pitch(ctx.pitch_id, business_affairs_headers()))["status"]
        == PITCH_COVERED
    )

    fx.set_clock(api, "2026-08-31T00:00:00Z")
    project = validate_success(
        api.advance_pitch(ctx.pitch_id, development_exec_headers()), 201
    )
    assert project["dev_status"] == DEV_ACTIVE_DEVELOPMENT
    a.assert_cents(project["cumulative_dev_cost_cents"], 0, "cumulative_dev_cost_cents")
    a.assert_created_version_one(project)

    pitch = validate_success(api.get_pitch(ctx.pitch_id, business_affairs_headers()))
    assert pitch["status"] == PITCH_ADVANCED


def _held_through_february(api):
    """One ACTIVE hold whose half-open term runs 2026-08-01 up to but not into 2027-02-01."""
    ctx = build_scenario(
        api,
        "writer",
        agency={"name": "Arbor Talent", "agency_code": "ARB"},
        writer={"full_name": "Nadia Roth", "quote_per_step_cents": 6000000},
    )
    ctx.holding_deal_id = fx.add_holding_deal(
        api, ctx, annual_cost_cents=20000000, start_date="2026-08-01", end_date="2027-02-01"
    )["id"]
    return ctx


def test_a_second_hold_sharing_one_day_with_the_first_term_is_refused(api):
    """A term starting 2027-01-31 collides on the single day the first term still covers.

    PRD 3.3: "The writer must not already have another `ACTIVE` holding deal whose
    half-open term intersects the requested term, else `ERR_HOLDING_DEAL_OVERLAP`".

    Design: Difficulty/resource_temporal_overlap/holding_deal_half_open_term_permits_abutting_but_not_one_day_overlap
    """
    ctx = _held_through_february(api)

    refused = api.create_holding_deal(
        f.holding_deal_payload(
            ctx.writer_id,
            ctx.slate_id,
            annual_cost_cents=18000000,
            start_date="2027-01-31",
            end_date="2027-07-01",
        ),
        business_affairs_headers(),
    )
    validate_error(refused, e.ERR_HOLDING_DEAL_OVERLAP, 422)

    slate = validate_success(api.get_slate(ctx.slate_id, business_affairs_headers()))
    a.assert_slate_dollar_ledger(
        slate, committed=0, reserved=20000000, available=380000000
    )
    rows = validate_success(
        api.list_holding_deals(business_affairs_headers(), {"writer_id": ctx.writer_id})
    )
    assert len(rows) == 1, "the refused hold created no row"


def test_a_second_hold_abutting_the_exclusive_end_date_is_legal(api):
    """A term starting exactly on 2027-02-01 does not overlap, because the end is exclusive.

    PRD 3.3: "The term is half-open: it covers the start date and every date up to but
    not including the end date. That detail is what makes back-to-back holds legal - one
    term ending on exactly the date the next begins does not overlap it."

    Design: Difficulty/resource_temporal_overlap/holding_deal_half_open_term_permits_abutting_but_not_one_day_overlap
    """
    ctx = _held_through_february(api)

    second = validate_success(
        api.create_holding_deal(
            f.holding_deal_payload(
                ctx.writer_id,
                ctx.slate_id,
                annual_cost_cents=18000000,
                start_date="2027-02-01",
                end_date="2027-08-01",
            ),
            business_affairs_headers(),
        ),
        201,
    )
    assert second["term_state"] == TERM_PENDING_START

    first = validate_success(
        api.get_holding_deal(ctx.holding_deal_id, business_affairs_headers())
    )
    assert first["term_state"] == TERM_IN_TERM

    slate = validate_success(api.get_slate(ctx.slate_id, business_affairs_headers()))
    a.assert_slate_dollar_ledger(
        slate, committed=0, reserved=38000000, available=362000000
    )

    writer = validate_success(
        api.get_writer(ctx.writer_id, agency_rep_headers(ctx.agency_id))
    )
    assert writer["exclusivity_status"] == EXCLUSIVITY_HOLDING_DEAL, (
        "the in-term hold decides exclusivity; the pending one does not"
    )
