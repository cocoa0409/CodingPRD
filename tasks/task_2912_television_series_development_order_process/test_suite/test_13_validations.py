"""Validation corners: conditional rules, aggregates across parents and ladder order.

A refused write must leave every derived figure exactly where it was, so each test
here reads the ledgers and the parent state back after the refusal.
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
    CHAIN_OF_TITLE_DISPUTED,
    DEV_ACTIVE_DEVELOPMENT,
    PITCH_ADVANCED,
    PITCH_COVERED,
    POSTURE_LOCKED,
    POSTURE_OPEN,
    RIGHTS_RESULT_CLEAR,
    STEP_PENDING,
    TURNAROUND_NONE,
)
from test_helpers.fixtures import build_scenario
from test_helpers.test_users import (
    agency_rep_headers,
    business_affairs_headers,
    development_exec_headers,
)

LAPSED_HOLDBACK = {"holdback_start_date": "2025-01-01", "holdback_end_date": "2025-03-01"}
PACKAGED = [
    "Ada Reyes as showrunner",
    "Nia Cole attached to star",
]
SALT_FLATS = {
    "title": "Salt Flats",
    "logline": "A land-speed team races the drought that is erasing their track.",
    "underlying_ip_key": "IP-SALT-FLATS",
}


def test_a_later_disputed_clearance_overrides_the_earlier_clean_one(api):
    """A CLEAN check filed first does not rescue the pitch once a DISPUTED one lands after it.

    PRD 3.2: "the pitch must have at least one rights check on file and the most
    recent one, meaning the one with the highest `created_at`, must have `result`
    `CLEAR`; a pitch with no clearance at all, or one whose newest clearance came
    back `ENCUMBERED` or `BLOCKED`, is refused with `ERR_RIGHTS_NOT_CLEAR`."

    Design: Corner/validations/advancing_a_pitch_whose_latest_rights_check_is_disputed_returns_rights_not_clear
    """
    ctx = build_scenario(api, "covered")

    # The clock has to move so the second filing genuinely holds the higher created_at.
    fx.set_clock(api, "2026-08-02T00:00:00Z")
    fx.file_rights_check(
        api, ctx.pitch_id, {"chain_of_title_status": CHAIN_OF_TITLE_DISPUTED}
    )

    refused = api.advance_pitch(ctx.pitch_id, development_exec_headers())
    validate_error(refused, e.ERR_RIGHTS_NOT_CLEAR, 422)

    pitch = validate_success(api.get_pitch(ctx.pitch_id, business_affairs_headers()))
    assert pitch["status"] == PITCH_COVERED, "the refused advance leaves the pitch covered"

    rows, meta = validate_paginated(
        api.list_projects(
            business_affairs_headers(),
            {"slate_id": ctx.slate_id, "limit": 10, "offset": 0},
        )
    )
    assert rows == [], "no project may exist on the slate"
    a.assert_pagination_meta(meta, total_count=0)


def test_packaging_is_refused_only_once_the_element_list_is_non_empty(api):
    """The same agency submits fine with an empty list and is refused with two elements.

    PRD 3.2: "an agency whose `packaging_allowed` is false may not submit a pitch
    that carries any at all, which is refused with `ERR_PACKAGING_NOT_PERMITTED`."

    Design: Corner/validations/packaging_elements_from_an_agency_without_permission_are_rejected
    """
    ctx = fx.bootstrap(
        api, agency={"name": "Cinder Row Management", "packaging_allowed": False}
    )

    permitted = validate_success(
        api.create_pitch(
            f.pitch_payload(ctx.agency_id, ctx.slate_id, {"packaging_elements": []}),
            agency_rep_headers(ctx.agency_id),
        ),
        201,
    )
    assert permitted["packaging_elements"] == []

    refused = api.create_pitch(
        f.pitch_payload(
            ctx.agency_id, ctx.slate_id, dict(SALT_FLATS, packaging_elements=list(PACKAGED))
        ),
        agency_rep_headers(ctx.agency_id),
    )
    validate_error(refused, e.ERR_PACKAGING_NOT_PERMITTED, 422)

    rows, meta = validate_paginated(
        api.list_pitches(
            business_affairs_headers(),
            {"agency_id": ctx.agency_id, "limit": 10, "offset": 0},
        )
    )
    assert len(rows) == 1, "only the unpackaged pitch was filed"
    a.assert_pagination_meta(meta, total_count=1)

    agency = validate_success(api.get_agency(ctx.agency_id, business_affairs_headers()))
    assert agency["submissions_used_count"] == 1
    assert agency["packaging_allowed"] is False


def test_a_holdback_and_quiet_buffer_that_both_lapsed_no_longer_block_the_advance(api):
    """A 2025 holdback with a quiet period ending 2025-05-30 is history at 2026-08-01.

    PRD 3.2: "if the logical clock's current date falls anywhere inside that newest
    check's closed holdback interval from `holdback_start_date` through
    `holdback_end_date`, or anywhere in the quiet buffer that runs through
    `quiet_period_end_date` inclusive, the advance is refused with
    `ERR_RIGHTS_HOLDBACK_CONFLICT` even though the title itself is clean."

    Design: Corner/validations/rights_check_whose_holdback_and_quiet_buffer_have_both_lapsed_permits_the_advance
    """
    ctx = build_scenario(api, "covered", rights=dict(LAPSED_HOLDBACK))

    project = validate_success(
        api.advance_pitch(ctx.pitch_id, development_exec_headers()), 201
    )
    assert project["dev_status"] == DEV_ACTIVE_DEVELOPMENT
    assert project["title"] == "Fault Lines"
    assert project["pitch_id"] == ctx.pitch_id
    assert project["slate_id"] == ctx.slate_id
    assert project["turnaround_status"] == TURNAROUND_NONE
    assert project["predecessor_project_id"] is None

    pitch = validate_success(api.get_pitch(ctx.pitch_id, business_affairs_headers()))
    assert pitch["status"] == PITCH_ADVANCED

    checks, _ = validate_paginated(
        api.list_rights_checks(ctx.pitch_id, business_affairs_headers())
    )
    filed = next(row for row in checks if row["id"] == ctx.rights_check_id)
    assert filed["quiet_period_end_date"] == "2025-05-30", "90 days beyond 2025-03-01"
    assert filed["result"] == RIGHTS_RESULT_CLEAR


def test_the_open_step_ceiling_is_counted_across_every_deal_the_writer_is_on(api):
    """Three legal single-step deals, two exercises, and the third exercise is refused.

    PRD 3.4: "a writer may carry at most two open steps at once across every deal
    they are on, so an exercise is refused with `ERR_WRITER_STEP_LOAD_EXCEEDED`
    unless the writer's `open_step_count` is below 2 before the exercise."

    Design: Corner/validations/a_third_open_step_for_one_writer_exceeds_the_step_load
    """
    ctx = build_scenario(api, "deal")
    second = fx.execute_script_deal(api, ctx.project_id, ctx.writer_id)["id"]
    third = fx.execute_script_deal(api, ctx.project_id, ctx.writer_id)["id"]
    third_step = fx.deal_step_ids(api, third)[0]

    validate_success(
        api.exercise_step(ctx.deal_id, ctx.step_ids[0], business_affairs_headers())
    )
    validate_success(
        api.exercise_step(second, fx.deal_step_ids(api, second)[0], business_affairs_headers())
    )

    loaded = validate_success(api.get_writer(ctx.writer_id, business_affairs_headers()))
    assert loaded["open_step_count"] == 2, "the ceiling is reached but not breached"

    refused = api.exercise_step(third, third_step, business_affairs_headers())
    validate_error(refused, e.ERR_WRITER_STEP_LOAD_EXCEEDED, 422)

    writer = validate_success(api.get_writer(ctx.writer_id, business_affairs_headers()))
    assert writer["open_step_count"] == 2, "the refused exercise opened nothing"

    steps = validate_success(api.list_deal_steps(third, business_affairs_headers()))
    pending = a.find_step(steps, 1)
    assert pending["status"] == STEP_PENDING
    assert pending["exercised_at"] is None

    slate = validate_success(api.get_slate(ctx.slate_id, business_affairs_headers()))
    # Three guaranteed HIGH-tier STORY steps floored at 4375000 each were encumbered
    # at execution; the refused exercise moves no money.
    a.assert_slate_dollar_ledger(slate, committed=13125000, available=386875000)


def test_an_incoherent_ownership_split_is_reported_before_the_fee_cap_breach(api):
    """70 plus 40 percent and a 35000000 fee against a 30000000 cap reports the split.

    PRD 3.7: "The term sheet must be internally coherent - `network_ownership_pct`
    and `studio_ownership_pct` must add to exactly 100, `backend_points_bps` must
    not exceed the slate's `max_backend_points_bps`, and `episode_count` must be at
    least 1 - else `ERR_TERM_SHEET_INVALID`. Then `license_fee_per_episode_cents`
    must be at or below the slate's `license_fee_cap_per_episode_cents`, else
    `ERR_LICENSE_FEE_ABOVE_CAP`."

    Design: Corner/validations/incoherent_ownership_split_outranks_the_license_fee_cap_breach
    """
    ctx = build_scenario(api, "certified")

    refused = api.create_negotiation(
        f.negotiation_payload(
            ctx.project_id,
            episode_count=10,
            license_fee_per_episode_cents=35000000,
            backend_points_bps=1500,
            network_ownership_pct=70,
            studio_ownership_pct=40,
        ),
        business_affairs_headers(),
    )
    validate_error(refused, e.ERR_TERM_SHEET_INVALID, 422)

    standing = validate_success(
        api.list_project_negotiations(ctx.project_id, business_affairs_headers())
    )
    assert standing == [], "the refused opening reserves nothing"

    slate = validate_success(api.get_slate(ctx.slate_id, business_affairs_headers()))
    a.assert_slate_episode_ledger(
        slate, committed=0, reserved=0, available=20, posture=POSTURE_OPEN
    )


def test_a_flawless_pitch_cannot_advance_onto_a_slate_locked_by_a_sibling_project(api):
    """An AGREED 20-episode order fills the slate, so a clean second pitch is refused.

    PRD 2.8: "The slate is `LOCKED` when `committed_episode_count` is greater than
    or equal to `episode_capacity`." and PRD 3.2: "Fourth, the target slate's
    `posture` must not be `LOCKED`, else `ERR_SLATE_POSTURE_LOCKED`."

    Design: Corner/validations/advancing_a_pitch_onto_a_locked_slate_returns_slate_posture_locked
    """
    ctx = build_scenario(api, "agreed", negotiation={"episode_count": 20})

    locked = validate_success(api.get_slate(ctx.slate_id, business_affairs_headers()))
    a.assert_slate_episode_ledger(
        locked, committed=20, reserved=0, available=0, posture=POSTURE_LOCKED
    )

    pitch2 = fx.covered_second_pitch(
        api, ctx, pitch=dict(SALT_FLATS), rights=dict(LAPSED_HOLDBACK)
    )

    refused = api.advance_pitch(pitch2, development_exec_headers())
    validate_error(refused, e.ERR_SLATE_POSTURE_LOCKED, 409)

    blocked = validate_success(api.get_pitch(pitch2, business_affairs_headers()))
    assert blocked["status"] == PITCH_COVERED

    rows, meta = validate_paginated(
        api.list_projects(
            business_affairs_headers(), {"pitch_id": pitch2, "limit": 10, "offset": 0}
        )
    )
    assert rows == [], "a locked slate takes no new development"
    a.assert_pagination_meta(meta, total_count=0)

    after = validate_success(api.get_slate(ctx.slate_id, business_affairs_headers()))
    a.assert_slate_episode_ledger(
        after, committed=20, reserved=0, available=0, posture=POSTURE_LOCKED
    )
