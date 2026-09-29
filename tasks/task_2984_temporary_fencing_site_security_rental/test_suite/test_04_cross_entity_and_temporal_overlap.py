"""Cross-entity state dependencies and temporal overlap.

Covers the dispatch gates of PRD §3.5 that read another entity's state and
another entity's window, the conversion gate of PRD §3.3, the crew travel buffer
of PRD §3.5 and the municipal closure corridor of PRD §3.4.
"""

from prd_bench_local_runner.testing import validate_error, validate_success

from test_helpers import constants as C
from test_helpers import factories as F
from test_helpers import fixtures as FX
from test_helpers import test_users as U
from test_helpers.api_errors import (
    ERR_CLOSURE_CAPACITY_EXCEEDED,
    ERR_CREW_WINDOW_CONFLICT,
    ERR_PERMIT_NOT_APPROVED,
    ERR_PERMIT_WINDOW_ELAPSED,
    ERR_QUOTE_STATE,
)
from test_helpers.assertions import (
    assert_cents,
    assert_instant,
    assert_integer,
    assert_labor_hours,
)


# ---------------------------------------------------------------------------
# cross_entity_state_dependency
# ---------------------------------------------------------------------------


def _permitted_site_world(api):
    """A closure-bearing jobsite with a submitted permit and two planned visits.

    The permit asks for 300 feet of `PARTIAL` closure over the half-open window
    [2026-08-10, 2026-08-20); it is submitted at clock 2026-08-01, which clears
    the jurisdiction's five-day lead time, and left undecided.  The contract is
    500 feet of `CONSTRUCTION` fence, so the install estimates 4.25 hours and the
    relocation 6.25 hours.
    """
    world = FX.seed_world(
        api,
        crews=(C.CREW_A, C.CREW_B),
        jobsite={
            "site_label": "Quay Street Tower",
            "address_line": "11 Quay Street",
            "requires_sidewalk_closure": True,
        },
    )
    committed_before = FX.read_municipality(api, world["municipality"]["id"])[
        "committed_closure_linear_feet"
    ]
    permit = FX.seed_permit(api, world["jobsite"]["id"])
    submitted = FX.submit_permit(api, permit["id"])
    contract, _quote = FX.seed_contract(
        api, world["jobsite"]["id"], world["account"]["id"], linear_feet=500
    )
    install = FX.plan_work_order(api, contract["id"], C.WO_DELIVERY_INSTALL, 500)
    relocation = FX.plan_work_order(api, contract["id"], C.WO_RELOCATION, 500)
    FX.set_clock(api, C.CLOCK_AUG_19)
    return {
        "world": world,
        "committed_before": committed_before,
        "permit": submitted,
        "contract": contract,
        "install": install,
        "relocation": relocation,
    }


def test_dispatch_refused_while_the_jobsite_permit_is_only_submitted(api):
    """PRD §3.5: "When the contract's jobsite has `requires_sidewalk_closure`
    true and the visit type is `DELIVERY_INSTALL`, `RELOCATION` or `RESET`, some
    permit application on that jobsite must have `status` `APPROVED`, and failing
    that the dispatch is refused with `ERR_PERMIT_NOT_APPROVED`."

    Design: Difficulty/cross_entity_state_dependency/dispatch_requires_approved_permit_covering_the_whole_order
    """
    state = _permitted_site_world(api)

    assert_integer(state["committed_before"], 0, "committed_closure_linear_feet")
    assert state["permit"]["status"] == C.PERMIT_SUBMITTED

    response = api.dispatch_work_order(
        state["install"]["id"],
        F.dispatch_payload(
            state["world"]["crews"][C.CREW_A]["id"], "2026-08-19T18:00:00Z"
        ),
        U.DISPATCH_COORDINATOR,
    )
    validate_error(response, ERR_PERMIT_NOT_APPROVED, 409)

    unmoved = FX.read_work_order(api, state["install"]["id"])
    assert unmoved["status"] == C.WO_PLANNED
    assert unmoved["crew_id"] is None
    assert unmoved["estimated_labor_hours"] is None


def test_dispatch_admitted_once_the_permit_reaches_approved(api):
    """PRD §3.4: "`APPROVE` moves the application `SUBMITTED → APPROVED`" and
    PRD §3.5: "When such a permit exists, its half-open closure window must
    contain **both** `scheduled_start_utc` and `scheduled_end_utc`".

    Design: Difficulty/cross_entity_state_dependency/dispatch_requires_approved_permit_covering_the_whole_order
    """
    state = _permitted_site_world(api)
    crew_a = state["world"]["crews"][C.CREW_A]

    approved = FX.decide_permit(
        api,
        state["permit"]["id"],
        C.DECISION_APPROVE,
        reviewer_note="lane shift approved as drawn",
    )
    assert approved["status"] == C.PERMIT_APPROVED
    assert_instant(approved["decided_at_utc"], C.CLOCK_AUG_19, "decided_at_utc")
    assert_integer(approved["revision_round"], 0, "revision_round")

    scheduled = validate_success(
        api.dispatch_work_order(
            state["install"]["id"],
            F.dispatch_payload(crew_a["id"], "2026-08-19T18:00:00Z"),
            U.DISPATCH_COORDINATOR,
        )
    )
    assert scheduled["status"] == C.WO_SCHEDULED
    assert scheduled["crew_id"] == crew_a["id"]
    assert_labor_hours(scheduled["estimated_labor_hours"], 4.25)
    assert_instant(
        scheduled["scheduled_end_utc"], "2026-08-19T22:15:00Z", "scheduled_end_utc"
    )

    municipality = FX.read_municipality(api, state["world"]["municipality"]["id"])
    assert_integer(
        municipality["committed_closure_linear_feet"],
        300,
        "committed_closure_linear_feet",
    )


def test_visit_whose_computed_end_leaves_the_closure_window_is_refused(api):
    """PRD §3.5: "each of the two instants must be at or after
    `closure_start_utc` and strictly before `closure_end_utc` — and a visit whose
    interval is not entirely inside the window is refused with
    `ERR_PERMIT_WINDOW_ELAPSED`."

    Design: Difficulty/cross_entity_state_dependency/dispatch_requires_approved_permit_covering_the_whole_order
    """
    state = _permitted_site_world(api)
    FX.decide_permit(api, state["permit"]["id"], C.DECISION_APPROVE)

    # A 500 ft relocation books 6.25 hours, so a 20:00 start on 2026-08-19 ends
    # at 02:15 on 2026-08-20 — outside the window that closes at midnight.
    response = api.dispatch_work_order(
        state["relocation"]["id"],
        F.dispatch_payload(
            state["world"]["crews"][C.CREW_B]["id"], "2026-08-19T20:00:00Z"
        ),
        U.DISPATCH_COORDINATOR,
    )
    validate_error(response, ERR_PERMIT_WINDOW_ELAPSED, 409)

    unmoved = FX.read_work_order(api, state["relocation"]["id"])
    assert unmoved["status"] == C.WO_PLANNED
    assert unmoved["crew_id"] is None
    assert unmoved["estimated_labor_hours"] is None
    assert FX.read_permit(api, state["permit"]["id"])["status"] == C.PERMIT_APPROVED


def test_conversion_refused_while_the_quote_is_draft_and_while_it_is_issued(api):
    """PRD §3.3: "An `AccountManager` converts by naming the `quote_id` of an
    `ACCEPTED` quote ... a conversion attempted against a quote in any other
    status is `ERR_QUOTE_STATE`."

    Design: Difficulty/cross_entity_state_dependency/contract_conversion_requires_accepted_quote_and_pins_version
    """
    world = FX.seed_world(api)
    quote = FX.seed_quote(api, world["jobsite"]["id"], linear_feet=500)
    assert quote["status"] == C.QUOTE_DRAFT

    body = F.contract_payload(quote["id"], C.ACCEPTOR_CONSTRUCTION)
    validate_error(
        api.create_contract(body, U.ACCOUNT_MANAGER), ERR_QUOTE_STATE, 409
    )

    issued = FX.issue_quote(api, quote["id"])
    assert issued["status"] == C.QUOTE_ISSUED
    validate_error(
        api.create_contract(body, U.ACCOUNT_MANAGER), ERR_QUOTE_STATE, 409
    )

    assert FX.read_quote(api, quote["id"])["status"] == C.QUOTE_ISSUED
    assert (
        api.list_contracts(U.ACCOUNT_MANAGER, params={"limit": C.MAX_LIMIT}).json()[
            "data"
        ]
        == []
    )


def test_conversion_succeeds_once_and_pins_the_accepted_version(api):
    """PRD §3.3: "`pinned_quote_version`, which records the quote's `version` as
    observed at the moment of conversion — the value read before this
    conversion's own increment."

    Design: Difficulty/cross_entity_state_dependency/contract_conversion_requires_accepted_quote_and_pins_version
    """
    world = FX.seed_world(api)
    quote = FX.seed_quote(api, world["jobsite"]["id"], linear_feet=500)
    FX.issue_quote(api, quote["id"])
    accepted = FX.accept_quote(api, quote["id"], world["account"]["id"])
    assert accepted["status"] == C.QUOTE_ACCEPTED

    body = F.contract_payload(quote["id"], C.ACCEPTOR_CONSTRUCTION)
    contract = validate_success(
        api.create_contract(body, U.ACCOUNT_MANAGER), expected_status=201
    )
    assert_integer(
        contract["pinned_quote_version"], accepted["version"], "pinned_quote_version"
    )

    validate_error(
        api.create_contract(body, U.ACCOUNT_MANAGER), ERR_QUOTE_STATE, 409
    )

    assert FX.read_quote(api, quote["id"])["status"] == C.QUOTE_CONVERTED
    rows = api.list_contracts(
        U.ACCOUNT_MANAGER, params={"quote_id": quote["id"], "limit": C.MAX_LIMIT}
    ).json()["data"]
    assert len(rows) == 1, rows

    assert contract["contract_type"] == C.CONTRACT_TYPE_CONSTRUCTION
    assert_cents(contract["monthly_recurring_cents"], 27000, "monthly_recurring_cents")
    assert_cents(contract["install_labor_cents"], 47500, "install_labor_cents")
    assert_cents(contract["one_time_cents"], 78500, "one_time_cents")
    assert_integer(contract["ordered_linear_feet"], 500, "ordered_linear_feet")
    assert_integer(contract["deployed_linear_feet"], 0, "deployed_linear_feet")
    assert contract["lifecycle_status"] == C.LIFECYCLE_PENDING_MOBILIZATION
    assert contract["billing_status"] == C.BILLING_NOT_BILLED
    assert_integer(contract["current_phase"], 1, "current_phase")
    assert contract["fleet_commitments"] == [
        {"product_code": C.PANEL_CODE, "unit_count": 50}
    ]


# ---------------------------------------------------------------------------
# resource_temporal_overlap
# ---------------------------------------------------------------------------


def _buffer_world(api):
    """One crew already holding a 5.75-hour install from 08:00 on 2026-08-20.

    Contract A is 500 feet with two gates and four water barriers, so its install
    books 5.75 hours and ends at 13:45; the ninety-minute travel buffer carries
    the crew's occupied interval to 15:15.  Contract B is 200 feet with the same
    add-ons and books 3.25 hours, and the crew's 12.0-hour daily capacity leaves
    room for both.
    """
    addons = [F.addon_line(C.GATE_CODE, 2), F.addon_line(C.WATER_BARRIER_CODE, 4)]
    world = FX.seed_world(
        api,
        clock=C.CLOCK_AUG_20,
        addons=(C.GATE_CODE, C.WATER_BARRIER_CODE),
        jobsite={"site_label": "Site A", "address_line": "1 Foundry Road"},
    )
    site_b = FX.add_jobsite(
        world, api, site_label="Site B", address_line="2 Foundry Road"
    )
    contract_a, quote_a = FX.seed_contract(
        api,
        world["jobsite"]["id"],
        world["account"]["id"],
        linear_feet=500,
        addon_lines=addons,
    )
    contract_b, quote_b = FX.seed_contract(
        api,
        site_b["id"],
        world["account"]["id"],
        linear_feet=200,
        addon_lines=addons,
    )
    install_a = FX.plan_work_order(api, contract_a["id"], C.WO_DELIVERY_INSTALL, 500)
    install_b = FX.plan_work_order(api, contract_b["id"], C.WO_DELIVERY_INSTALL, 200)
    scheduled_a = FX.dispatch(
        api, install_a["id"], world["crew"]["id"], "2026-08-20T08:00:00Z"
    )
    return {
        "crew": world["crew"],
        "quote_a": quote_a,
        "quote_b": quote_b,
        "install_a": scheduled_a,
        "install_b": install_b,
    }


def test_crew_buffer_blocks_a_start_one_minute_before_the_trailing_edge(api):
    """PRD §3.5: "The interval a `SCHEDULED` visit occupies runs from its
    `scheduled_start_utc` inclusive to its buffered end — `scheduled_end_utc`
    plus ninety minutes — exclusive." A collision is `ERR_CREW_WINDOW_CONFLICT`.

    Design: Difficulty/resource_temporal_overlap/crew_buffer_trailing_edge_exact_boundary
    """
    state = _buffer_world(api)

    assert_cents(
        state["quote_a"]["monthly_recurring_cents"], 44800, "monthly_recurring_cents"
    )
    assert_cents(state["quote_a"]["install_labor_cents"], 62500, "install_labor_cents")
    assert_cents(state["quote_a"]["one_time_cents"], 93500, "one_time_cents")
    assert_cents(
        state["quote_b"]["monthly_recurring_cents"], 30200, "monthly_recurring_cents"
    )
    assert_cents(state["quote_b"]["install_labor_cents"], 35000, "install_labor_cents")
    assert_cents(state["quote_b"]["one_time_cents"], 66000, "one_time_cents")
    assert_labor_hours(state["install_a"]["estimated_labor_hours"], 5.75)
    assert_instant(
        state["install_a"]["scheduled_end_utc"],
        "2026-08-20T13:45:00Z",
        "scheduled_end_utc",
    )

    response = api.dispatch_work_order(
        state["install_b"]["id"],
        F.dispatch_payload(state["crew"]["id"], "2026-08-20T15:14:00Z"),
        U.DISPATCH_COORDINATOR,
    )
    validate_error(response, ERR_CREW_WINDOW_CONFLICT, 409)

    unmoved = FX.read_work_order(api, state["install_b"]["id"])
    assert unmoved["status"] == C.WO_PLANNED
    assert unmoved["crew_id"] is None


def test_crew_accepts_a_start_at_exactly_the_buffered_end(api):
    """PRD §3.5: "a candidate starting at the precise instant an existing visit's
    buffered interval ends does **not** collide."

    Design: Difficulty/resource_temporal_overlap/crew_buffer_trailing_edge_exact_boundary
    """
    state = _buffer_world(api)

    scheduled = validate_success(
        api.dispatch_work_order(
            state["install_b"]["id"],
            F.dispatch_payload(state["crew"]["id"], "2026-08-20T15:15:00Z"),
            U.DISPATCH_COORDINATOR,
        )
    )

    assert scheduled["status"] == C.WO_SCHEDULED
    assert scheduled["crew_id"] == state["crew"]["id"]
    assert_labor_hours(scheduled["estimated_labor_hours"], 3.25)
    assert_instant(
        scheduled["scheduled_start_utc"], "2026-08-20T15:15:00Z", "scheduled_start_utc"
    )
    assert_instant(
        scheduled["scheduled_end_utc"], "2026-08-20T18:30:00Z", "scheduled_end_utc"
    )


def _corridor_world(api):
    """A jurisdiction capped at 800 feet holding one approved 300-foot closure.

    The approved permit runs over the half-open window [2026-08-10, 2026-08-20);
    every later request in these tests asks for a closure starting on or after
    2026-08-10, so the five-day lead time never fires from clock 2026-08-01.
    """
    world = FX.seed_world(
        api,
        jobsite={
            "site_label": "Quay Street Tower",
            "address_line": "11 Quay Street",
            "site_condition": C.CONDITION_CONCRETE,
            "requires_sidewalk_closure": True,
        },
    )
    approved = FX.seed_approved_permit(api, world["jobsite"]["id"])
    assert approved["status"] == C.PERMIT_APPROVED
    return world, approved


def test_corridor_cap_refuses_an_overlapping_collective_but_admits_an_adjacent_window(
    api,
):
    """PRD §3.4: "refused with `ERR_CLOSURE_CAPACITY_EXCEEDED` when it strictly
    exceeds it" and "A window that begins at the precise instant another ends
    does not contend."

    Design: Difficulty/resource_temporal_overlap/municipal_corridor_aggregate_and_adjacent_window
    """
    world, _approved = _corridor_world(api)
    site_id = world["jobsite"]["id"]

    overlapping = FX.seed_permit(
        api,
        site_id,
        closure_linear_feet=600,
        closure_start_utc="2026-08-15T00:00:00Z",
        closure_end_utc="2026-08-25T00:00:00Z",
        sidewalk_closure_type=C.CLOSURE_FULL,
    )
    response = api.submit_permit(
        overlapping["id"], U.MUNICIPAL_LIAISON, F.submit_payload()
    )
    validate_error(response, ERR_CLOSURE_CAPACITY_EXCEEDED, 409)

    refused = FX.read_permit(api, overlapping["id"])
    assert refused["status"] == C.PERMIT_DRAFT
    assert refused["submitted_at_utc"] is None

    adjacent = FX.seed_permit(
        api,
        site_id,
        closure_linear_feet=600,
        closure_start_utc="2026-08-20T00:00:00Z",
        closure_end_utc="2026-08-30T00:00:00Z",
        sidewalk_closure_type=C.CLOSURE_FULL,
    )
    submitted = validate_success(
        api.submit_permit(adjacent["id"], U.MUNICIPAL_LIAISON, F.submit_payload())
    )
    assert submitted["status"] == C.PERMIT_SUBMITTED
    assert_instant(submitted["submitted_at_utc"], C.CLOCK_AUG_01, "submitted_at_utc")


def test_corridor_cap_admits_a_projection_landing_exactly_on_the_cap(api):
    """PRD §3.4: "The submission is admitted when the projected footage is at or
    below the jurisdiction's `max_concurrent_closure_linear_feet` — equality is
    admitted."

    Design: Difficulty/resource_temporal_overlap/municipal_corridor_aggregate_and_adjacent_window
    """
    world, approved = _corridor_world(api)
    site_id = world["jobsite"]["id"]

    holder = FX.seed_permit(
        api,
        site_id,
        closure_linear_feet=600,
        closure_start_utc="2026-08-20T00:00:00Z",
        closure_end_utc="2026-08-30T00:00:00Z",
        sidewalk_closure_type=C.CLOSURE_FULL,
    )
    FX.submit_permit(api, holder["id"])

    too_wide = FX.seed_permit(
        api,
        site_id,
        closure_linear_feet=500,
        closure_start_utc="2026-08-22T00:00:00Z",
        closure_end_utc="2026-08-24T00:00:00Z",
        sidewalk_closure_type=C.CLOSURE_LANE_SHIFT,
    )
    validate_error(
        api.submit_permit(too_wide["id"], U.MUNICIPAL_LIAISON, F.submit_payload()),
        ERR_CLOSURE_CAPACITY_EXCEEDED,
        409,
    )
    assert FX.read_permit(api, too_wide["id"])["status"] == C.PERMIT_DRAFT

    exact = FX.seed_permit(
        api,
        site_id,
        closure_linear_feet=200,
        closure_start_utc="2026-08-22T00:00:00Z",
        closure_end_utc="2026-08-24T00:00:00Z",
        sidewalk_closure_type=C.CLOSURE_LANE_SHIFT,
    )
    admitted = validate_success(
        api.submit_permit(exact["id"], U.MUNICIPAL_LIAISON, F.submit_payload())
    )
    assert admitted["status"] == C.PERMIT_SUBMITTED

    assert FX.read_permit(api, approved["id"])["status"] == C.PERMIT_APPROVED
    assert FX.read_permit(api, holder["id"])["status"] == C.PERMIT_SUBMITTED
