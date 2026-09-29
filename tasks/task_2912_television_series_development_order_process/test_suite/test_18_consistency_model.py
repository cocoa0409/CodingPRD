"""The consistency model: a write's own response is already the settled truth.

Every read issued straight after the write has to agree with the write's own body,
and repeating those reads has to return the same values, so no field in this domain
is allowed to converge late.
"""

from prd_bench_local_runner.testing import validate_paginated, validate_success
from test_helpers import assertions as a
from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.constants import (
    CLOCK_STARTUP_DEFAULT_STAMP,
    COMMITTEE_FINANCE,
    DEAL_COMPLETED,
    DECISION_APPROVED,
    DEV_ACTIVE_DEVELOPMENT,
    DEV_SERIES_ORDERED,
    GL_APPROVED,
    PITCH_ADVANCED,
    POSTURE_OPEN,
    TURNAROUND_NONE,
)
from test_helpers.fixtures import build_scenario
from test_helpers.test_users import (
    business_affairs_headers,
    development_exec_headers,
    finance_controller_headers,
)

DECIDED_STAMP = "2026-09-26T00:00:00.000Z"


def test_the_advance_response_already_carries_the_project_its_own_call_created(api):
    """One call creates the project and moves the pitch, and both are visible at once.

    PRD 3.2: "the pitch moves `COVERED -> ADVANCED` - also terminal - and a
    development project is created in the same request. ... The created project - not
    the pitch - is what the response returns."

    Design: Corner/consistency model/the_advance_response_already_carries_the_project_its_own_call_created
    """
    ctx = build_scenario(api, "covered")

    response = api.advance_pitch(ctx.pitch_id, development_exec_headers())
    created = validate_success(response, 201)
    a.assert_response_type(response, "object")
    assert created["id"], "the response body is the project, not an accepted-for-work stub"
    assert created["dev_status"] == DEV_ACTIVE_DEVELOPMENT
    assert created["pitch_id"] == ctx.pitch_id
    assert created["slate_id"] == ctx.slate_id
    assert created["title"] == "Fault Lines"
    assert created["turnaround_status"] == TURNAROUND_NONE
    assert created["predecessor_project_id"] is None
    a.assert_created_version_one(created)
    a.assert_instant(created["created_at"], CLOCK_STARTUP_DEFAULT_STAMP, "created_at")
    a.assert_cents(
        created["cumulative_dev_cost_cents"], 0, "cumulative_dev_cost_cents"
    )

    reread = validate_success(api.get_project(created["id"], business_affairs_headers()))
    assert reread == created, "the immediate re-read must agree field for field"

    pitch = validate_success(api.get_pitch(ctx.pitch_id, business_affairs_headers()))
    assert pitch["status"] == PITCH_ADVANCED, (
        "the mutation and the creation are visible in the same instant"
    )

    rows, meta = validate_paginated(
        api.list_projects(
            business_affairs_headers(),
            {"pitch_id": ctx.pitch_id, "limit": 10, "offset": 0},
        )
    )
    a.assert_ids(rows, [created["id"]])
    a.assert_pagination_meta(meta, total_count=1)


def test_the_greenlight_approval_and_every_derived_read_land_in_the_same_instant(api):
    """The third vote's own 200 reports APPROVED and the whole cascade is already settled.

    PRD 3.8: "The request moves `OPEN -> APPROVED` and `decided_at` is stamped from
    the logical clock. Because of that, the project moves `PILOT_DELIVERED ->
    SERIES_ORDERED`. Because of that, every script deal of the project whose
    `deal_status` is `EXECUTED` becomes `COMPLETED`, and within each such deal every
    step still `PENDING` becomes `CUT_OFF`."

    Design: Corner/consistency model/the_greenlight_approval_response_and_every_derived_read_land_in_the_same_instant
    """
    ctx = build_scenario(api, "greenlight")
    fx.record_creative_decision(api, ctx.greenlight_id)
    fx.record_business_decision(api, ctx.greenlight_id)

    before = validate_success(api.get_slate(ctx.slate_id, business_affairs_headers()))
    a.assert_slate_dollar_ledger(before, committed=37375000, available=362625000)

    approved = validate_success(
        api.record_decision(
            ctx.greenlight_id,
            f.decision_payload(COMMITTEE_FINANCE, DECISION_APPROVED),
            finance_controller_headers(),
        )
    )
    assert approved["status"] == GL_APPROVED, "not still OPEN pending a later sweep"
    assert approved["finance_decision"] == DECISION_APPROVED
    a.assert_instant(approved["decided_at"], DECIDED_STAMP, "decided_at")

    def derived():
        project = validate_success(
            api.get_project(ctx.project_id, finance_controller_headers())
        )
        deal = validate_success(
            api.get_script_deal(ctx.deal_id, business_affairs_headers())
        )
        slate = validate_success(api.get_slate(ctx.slate_id, business_affairs_headers()))
        return project, deal, slate

    project, deal, slate = derived()
    assert project["dev_status"] == DEV_SERIES_ORDERED
    assert deal["deal_status"] == DEAL_COMPLETED
    # This deal's only step was ACCEPTED, so the cut-off link releases nothing and the
    # committed figure must not move: 4375000 of script work plus a 33000000 pilot.
    a.assert_slate_dollar_ledger(slate, committed=37375000, available=362625000)
    a.assert_slate_episode_ledger(
        slate, committed=10, reserved=0, available=10, posture=POSTURE_OPEN
    )

    again = derived()
    assert again == (project, deal, slate), "nothing converges late on a repeated read"
