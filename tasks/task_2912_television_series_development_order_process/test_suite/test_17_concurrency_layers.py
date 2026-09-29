"""Optimistic concurrency and clock-evaluated windows.

Both version guards are self-invalidating: the write that installs the state also
bumps the parent the client captured, so replaying a body that was valid one call
earlier is exactly the race the contract describes. Each refusal is followed by the
same body carrying the version the parent now reports, which must be accepted.
"""

from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers import api_errors as e
from test_helpers import assertions as a
from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.constants import (
    CLOCK_STARTUP_DEFAULT_STAMP,
    DEAL_EXECUTED,
    DEV_PILOT_DELIVERED,
    GL_OPEN,
    GL_SUPERSEDED,
    SCREENING_CERTIFIED,
    SCREENING_FIELDED,
    SCREENING_INVALIDATED,
    STEP_EXERCISED,
    STEP_PENDING,
    STEP_POLISH,
    STEP_STORY,
)
from test_helpers.fixtures import build_scenario
from test_helpers.test_users import (
    business_affairs_headers,
    development_exec_headers,
    research_analyst_headers,
)

TWO_STEP_LADDER = [f.step_spec(STEP_STORY, 3000000), f.step_spec(STEP_POLISH, 1000000)]
BIG_PANEL = {
    "panel_size": 400,
    "overall_score": 80,
    "intent_to_view_score": 75,
    "appeal_score": 70,
    "comp_norm_index": 100.0,
}
WRAP_STAMP = "2026-09-26T00:00:00.000Z"


def test_refiling_a_greenlight_request_on_the_pre_filing_project_version_is_stale(api):
    """The filing that created the open request is what made the client's version stale.

    PRD 2.9: "If `expected_project_version` does not equal the project's current
    `version`, the request is rejected with `ERR_STALE_PROJECT_VERSION` (HTTP 412)."

    Design: Corner/cross-cutting complexity layers/refiling_a_greenlight_request_on_the_pre_filing_project_version_returns_412
    """
    ctx = build_scenario(api, "agreed")
    observed = fx.project_version(api, ctx.project_id)
    first = fx.file_greenlight_request(
        api, ctx.project_id, ctx.negotiation_id, observed
    )
    assert first["project_version_at_request"] == observed

    stale = api.create_greenlight_request(
        f.greenlight_payload(ctx.project_id, ctx.negotiation_id, observed),
        business_affairs_headers(),
    )
    validate_error(stale, e.ERR_STALE_PROJECT_VERSION, 412)

    rows, meta = validate_paginated(
        api.list_greenlight_requests(
            business_affairs_headers(),
            {"project_id": ctx.project_id, "limit": 10, "offset": 0},
        )
    )
    a.assert_ids(rows, [first["id"]])
    assert rows[0]["status"] == GL_OPEN, "no half-supersession from the refused filing"
    a.assert_pagination_meta(meta, total_count=1)

    project = validate_success(api.get_project(ctx.project_id, business_affairs_headers()))
    assert project["version"] == observed + 1, "the first filing moved it by exactly one"
    assert project["dev_status"] == DEV_PILOT_DELIVERED

    second = validate_success(
        api.create_greenlight_request(
            f.greenlight_payload(
                ctx.project_id, ctx.negotiation_id, project["version"]
            ),
            business_affairs_headers(),
        ),
        201,
    )
    assert second["status"] == GL_OPEN
    assert second["project_version_at_request"] == observed + 1

    superseded = validate_success(
        api.get_greenlight_request(first["id"], business_affairs_headers())
    )
    assert superseded["status"] == GL_SUPERSEDED, (
        "only the accepted refiling supersedes the earlier request"
    )


def test_refielding_a_screening_on_the_pre_screening_pilot_version_is_stale(api):
    """Fielding bumped the pilot, so the researcher's own captured version is now stale.

    PRD 2.9: "A mismatch against the pilot order's current `version` is rejected with
    `ERR_STALE_PILOT_ORDER_VERSION` (HTTP 412)."

    Design: Corner/cross-cutting complexity layers/refielding_a_screening_on_the_pre_screening_pilot_version_returns_412
    """
    ctx = build_scenario(api, "wrapped")
    wrapped = validate_success(
        api.get_pilot_order(ctx.pilot_order_id, research_analyst_headers())
    )
    observed = wrapped["version"]

    first = fx.field_screening(api, ctx.pilot_order_id, observed)
    fx.certify_screening(api, first["id"])

    stale = api.field_screening(
        ctx.pilot_order_id,
        f.screening_payload(observed, **BIG_PANEL),
        research_analyst_headers(),
    )
    validate_error(stale, e.ERR_STALE_PILOT_ORDER_VERSION, 412)

    rows, meta = validate_paginated(
        api.list_screenings(ctx.pilot_order_id, research_analyst_headers())
    )
    a.assert_ids(rows, [first["id"]])
    assert rows[0]["status"] == SCREENING_CERTIFIED, "the refusal invalidated nothing"
    a.assert_pagination_meta(meta, total_count=1)

    pilot = validate_success(
        api.get_pilot_order(ctx.pilot_order_id, research_analyst_headers())
    )
    assert pilot["version"] == observed + 1, "the accepted fielding bumped the pilot once"

    fresh = validate_success(
        api.field_screening(
            ctx.pilot_order_id,
            f.screening_payload(pilot["version"], **BIG_PANEL),
            research_analyst_headers(),
        ),
        201,
    )
    assert fresh["status"] == SCREENING_FIELDED
    # 36.40 + 22.31 + 17.33 is 76.04, and 76.04 * 100 / 100.0 rounds to 76.0.
    a.assert_score(fresh["norm_adjusted_score"], 76.0, "norm_adjusted_score")

    after, _ = validate_paginated(
        api.list_screenings(ctx.pilot_order_id, research_analyst_headers())
    )
    superseded = next(row for row in after if row["id"] == first["id"])
    assert superseded["status"] == SCREENING_INVALIDATED, (
        "only the accepted refielding supersedes the certified research"
    )


def test_the_project_version_advances_by_exactly_one_per_write_and_never_on_a_read(api):
    """The guard is only usable if the counter is a strict single step, cascades included.

    PRD 2.5: "`version` is an integer that begins at 1 when the row is created and
    increments by exactly 1 on every mutation, including mutations that only change a
    derived field." and PRD 3.5: "Both the pilot's `version` and the project's
    `version` are incremented by 1."

    Design: Corner/cross-cutting complexity layers/the_project_version_ladder_advances_by_exactly_one_per_write_and_never_on_a_read
    """
    ctx = build_scenario(api, "green_to_shoot")
    before_wrap = validate_success(
        api.get_project(ctx.project_id, business_affairs_headers())
    )
    a.assert_instant(
        before_wrap["created_at"], CLOCK_STARTUP_DEFAULT_STAMP, "created_at"
    )

    wrapped = fx.wrap_pilot(api, ctx.pilot_order_id)
    after_wrap = validate_success(
        api.get_project(ctx.project_id, business_affairs_headers())
    )
    # The wrap touches the pilot order as well, and the project still moves by one.
    assert after_wrap["version"] == before_wrap["version"] + 1
    assert after_wrap["dev_status"] == DEV_PILOT_DELIVERED

    repeated = [
        validate_success(api.get_project(ctx.project_id, business_affairs_headers()))[
            "version"
        ]
        for _ in range(3)
    ]
    assert repeated == [after_wrap["version"]] * 3, "reads never advance the counter"

    screening = fx.field_screening(api, ctx.pilot_order_id, wrapped["version"])
    fx.certify_screening(api, screening["id"])
    negotiation = fx.open_negotiation(api, ctx.project_id)
    fx.accept_negotiation_as_studio(api, negotiation["id"])

    observed = fx.project_version(api, ctx.project_id)
    fx.file_greenlight_request(api, ctx.project_id, negotiation["id"], observed)

    final = validate_success(api.get_project(ctx.project_id, business_affairs_headers()))
    assert final["version"] == observed + 1, "the filing was the last write on the project"
    a.assert_instant(final["created_at"], CLOCK_STARTUP_DEFAULT_STAMP, "created_at")
    a.assert_instant(final["updated_at"], WRAP_STAMP, "updated_at")

    still = [
        validate_success(api.get_project(ctx.project_id, business_affairs_headers()))[
            "version"
        ]
        for _ in range(3)
    ]
    assert still == [final["version"]] * 3


def test_one_second_separates_a_live_option_from_an_expired_one(api):
    """Two identical ladders: the exercise at 23:59:59 lands and the one at the expiry does not.

    PRD 3.4: "The logical clock's current instant must be strictly before the step's
    `option_expires_at`; an exercise at exactly `option_expires_at` is one instant too
    late and is refused with `ERR_OPTION_PERIOD_EXPIRED`."

    Design: Corner/cross-cutting complexity layers/one_clock_move_to_exactly_the_option_expiry_instant_shuts_the_exercise_window
    """
    ctx = build_scenario(api, "project")
    late_deal = fx.execute_script_deal(
        api,
        ctx.project_id,
        ctx.writer_id,
        steps=list(TWO_STEP_LADDER),
        option_period_days=60,
    )
    second_writer = fx.add_second_writer(api, ctx)
    early_deal = fx.execute_script_deal(
        api,
        ctx.project_id,
        second_writer,
        steps=list(TWO_STEP_LADDER),
        option_period_days=60,
    )

    ladder = validate_success(
        api.list_deal_steps(late_deal["id"], business_affairs_headers())
    )
    first_step = a.find_step(ladder, 1)
    second_step = a.find_step(ladder, 2)
    # The anchor is the deal's own created_at, so the expiries walk outward from it:
    # 2026-08-01 plus 1 * 60 days, then plus 2 * 60 days.
    a.assert_instant(
        first_step["option_expires_at"], "2026-09-30T00:00:00.000Z", "option_expires_at"
    )
    a.assert_instant(
        second_step["option_expires_at"], "2026-11-29T00:00:00.000Z", "option_expires_at"
    )

    fx.set_clock(api, "2026-09-29T23:59:59Z")
    early_step = a.find_step(
        validate_success(api.list_deal_steps(early_deal["id"], business_affairs_headers())),
        1,
    )
    in_time = validate_success(
        api.exercise_step(early_deal["id"], early_step["id"], business_affairs_headers())
    )
    assert in_time["status"] == STEP_EXERCISED, "one second before the expiry is inside"

    fx.set_clock(api, "2026-09-30T00:00:00Z")
    unmoved = a.find_step(
        validate_success(api.list_deal_steps(late_deal["id"], business_affairs_headers())),
        1,
    )
    assert unmoved["status"] == STEP_PENDING, "the clock endpoint transitions nothing"

    refused = api.exercise_step(
        late_deal["id"], first_step["id"], business_affairs_headers()
    )
    validate_error(refused, e.ERR_OPTION_PERIOD_EXPIRED, 422)

    after = validate_success(
        api.list_deal_steps(late_deal["id"], development_exec_headers())
    )
    assert a.find_step(after, 1)["status"] == STEP_PENDING
    assert a.find_step(after, 1)["exercised_at"] is None
    a.assert_instant(
        a.find_step(after, 1)["option_expires_at"],
        "2026-09-30T00:00:00.000Z",
        "option_expires_at",
    )
    a.assert_instant(
        a.find_step(after, 2)["option_expires_at"],
        "2026-11-29T00:00:00.000Z",
        "option_expires_at",
    )

    deal = validate_success(
        api.get_script_deal(late_deal["id"], business_affairs_headers())
    )
    assert deal["deal_status"] == DEAL_EXECUTED
    # The guaranteed STORY step was encumbered at execution at its HIGH-tier floor of
    # 4375000, and the refused exercise moves nothing.
    a.assert_cents(deal["encumbered_cents"], 4375000, "encumbered_cents")
