"""Composite setup helpers — the state-building layer of the test suite.

Every helper here builds its preconditions from scratch through the public API:
the server starts empty before each test and no state is seeded out of band.
Each helper returns the created resources so a test can assert against them.

Layers, from the bottom up:

* **Readers** — fetch and unwrap a resource, or list a project's children.
* **Primitives** — one meaningful API call, with the correct role headers and
  payload factory already applied.
* **Composites** — multi-step scenarios (fund + subscription + pay-in, project
  + allocation + commit, the full milestone chain into the compliance period,
  a defaulted subscription, an escalated review, a frozen fund, and so on).

Identity threading: every call made on behalf of an entity-backed role is built
with ``make_developer_headers`` / ``make_investor_headers`` from the actual
entity id, never from the shared ``TEST_USERS`` constant.
"""

from .api_client import api_client
from .constants import (
    CLOCK_2026_09_02,
    CLOCK_2026_10_05,
    CLOCK_2026_12_05,
    CLOCK_2027_02_05,
    CLOCK_2027_04_10,
    COMPLIANCE_PERIOD_MONTHS_DEFAULT,
    FUND_CLOSE_THRESHOLD_DEFAULT,
    SCENARIO,
)
from .factories import (
    PAYIN_SCHEDULE_FIVE,
    PAYIN_SCHEDULE_SINGLE,
    capital_call_transition_payload,
    close_allocation_payload,
    create_allocation_payload,
    create_capital_call_payload,
    create_developer_payload,
    create_exit_event_payload,
    create_fund_payload,
    create_guarantee_payload,
    create_investor_payload,
    create_payin_payload,
    create_project_payload,
    create_review_payload,
    create_subscription_payload,
    distribute_allocation_payload,
    draw_guarantee_payload,
    record_delivery_payload,
    record_milestone_payload,
    rescind_allocation_payload,
    resolve_review_payload,
    update_fund_payload,
    update_project_payload,
)
from .test_users import (
    TEST_USERS,
    make_asset_manager_headers,
    make_compliance_officer_headers,
    make_developer_headers,
    make_investor_headers,
    make_platform_admin_headers,
    make_underwriter_headers,
)

__all__ = [
    "Scenario",
    # readers
    "read_developer",
    "read_investor",
    "read_fund",
    "read_project",
    "read_subscription",
    "list_subscriptions_data",
    "list_project_capital_calls",
    "list_project_allocations",
    "list_project_guarantees",
    "list_project_reviews",
    "list_project_exit_events",
    "find_capital_call",
    # primitives
    "set_logical_clock",
    "advance_clock_to",
    "onboard_developer",
    "onboard_investor",
    "form_fund",
    "open_subscription",
    "record_payin",
    "add_project",
    "add_allocation",
    "finalize_underwriting",
    "commit_project",
    "schedule_capital_call",
    "issue_call",
    "settle_call",
    "adjust_call",
    "record_project_milestone",
    "add_guarantee",
    "draw_on_guarantee",
    "open_review",
    "resolve_review",
    "plan_exit_event",
    "exercise_exit_action",
    # composites
    "setup_canonical_scenario",
    "setup_fund_with_subscription",
    "setup_project_with_allocation",
    "setup_finalized_project",
    "setup_committed_project",
    "setup_project_with_paid_call",
    "setup_project_in_compliance_period",
    "setup_exit_eligible_project",
    "setup_two_projects_under_one_fund",
    "setup_fund_at_close_threshold",
    "setup_delivery_ratio_scenario",
    "setup_defaulted_subscription",
    "setup_suspended_investor",
    "setup_escalated_review",
    "setup_distressed_project",
    "setup_frozen_fund",
    "setup_developer_near_coverage_boundary",
    "setup_capital_call_buffer_scenario",
    "setup_guarantee_scenario",
]

from prd_bench_local_runner.testing import get_success_data

_ADMIN = TEST_USERS["platform_admin_headers"]
_UW = TEST_USERS["underwriter_headers"]
_AM = TEST_USERS["asset_manager_headers"]
_CO = TEST_USERS["compliance_officer_headers"]

#: The milestone chain that walks a COMMITTED project into COMPLIANCE_PERIOD.
#: Each entry is (capital-call milestone, project milestone it unlocks,
#: scheduled_date, due_date, clock instant at issue). The dates satisfy the
#: 30-day buffer between consecutive calls, and each issue instant is at or
#: after its scheduled date.
_MILESTONE_CHAIN = (
    (
        "CONSTRUCTION_START",
        "CONSTRUCTION_START",
        "2026-10-01T00:00:00Z",
        "2026-10-31T00:00:00Z",
        CLOCK_2026_10_05,
    ),
    (
        "CONSTRUCTION_50PCT",
        "LEASE_UP_50PCT",
        "2026-12-01T00:00:00Z",
        "2026-12-31T00:00:00Z",
        CLOCK_2026_12_05,
    ),
    (
        "LEASE_UP_50PCT",
        "LEASE_UP_STABILIZED",
        "2027-02-01T00:00:00Z",
        "2027-03-03T00:00:00Z",
        CLOCK_2027_02_05,
    ),
    (
        "LEASE_UP_STABILIZED",
        "PLACED_IN_SERVICE",
        "2027-04-05T00:00:00Z",
        "2027-05-05T00:00:00Z",
        CLOCK_2027_04_10,
    ),
)


class Scenario(dict):
    """A dict of created resources that also supports attribute access.

    ``scenario.fund["id"]`` and ``scenario["fund"]["id"]`` are equivalent.
    """

    def __getattr__(self, name):
        try:
            return self[name]
        except KeyError as exc:  # pragma: no cover - defensive
            raise AttributeError(name) from exc

    def __setattr__(self, name, value):
        self[name] = value


# =============================================================================
# Readers
# =============================================================================

def read_developer(developer_id, headers=None):
    """GET a developer (Underwriter by default)."""
    return get_success_data(
        api_client.get_developer(developer_id, headers or _UW)
    )


def read_investor(investor_id, headers=None):
    """GET an investor (Underwriter by default)."""
    return get_success_data(api_client.get_investor(investor_id, headers or _UW))


def read_fund(fund_id, headers=None):
    """GET a fund — recomputes both valuations and the portfolio counters."""
    return get_success_data(api_client.get_fund(fund_id, headers or _UW))


def read_project(project_id, headers=None):
    """GET a project (Underwriter by default)."""
    return get_success_data(api_client.get_project(project_id, headers or _UW))


def read_subscription(subscription_id, headers=None):
    """GET a subscription (Underwriter by default)."""
    return get_success_data(
        api_client.get_subscription(subscription_id, headers or _UW)
    )


def list_subscriptions_data(headers=None, **params):
    """GET /subscriptions and return the data list.

    Pass filters as keyword arguments, e.g. ``fund_id=..., status="PLEDGED"``.
    """
    return get_success_data(
        api_client.list_subscriptions(headers or _UW, params or None)
    )


def list_project_capital_calls(project_id, headers=None, **params):
    """List a project's capital calls, newest-last."""
    return get_success_data(
        api_client.list_capital_calls(project_id, headers or _AM, params or None)
    )


def list_project_allocations(project_id, headers=None, **params):
    """List a project's allocations."""
    return get_success_data(
        api_client.list_allocations(project_id, headers or _UW, params or None)
    )


def list_project_guarantees(project_id, headers=None, **params):
    """List a project's guarantees."""
    return get_success_data(
        api_client.list_guarantees(project_id, headers or _AM, params or None)
    )


def list_project_reviews(project_id, headers=None, **params):
    """List a project's compliance reviews."""
    return get_success_data(
        api_client.list_reviews(project_id, headers or _CO, params or None)
    )


def list_project_exit_events(project_id, headers=None, **params):
    """List a project's exit events."""
    return get_success_data(
        api_client.list_exit_events(project_id, headers or _UW, params or None)
    )


def find_capital_call(project_id, call_id, headers=None):
    """Return one capital call out of the project's list (there is no GET-one)."""
    for call in list_project_capital_calls(project_id, headers):
        if call["id"] == call_id:
            return call
    raise AssertionError(f"CapitalCall {call_id} not found under project {project_id}")


# =============================================================================
# Primitives
# =============================================================================

def set_logical_clock(current_utc=CLOCK_2026_09_02, headers=None):
    """Advance the logical clock (PlatformAdmin only); returns the new value."""
    response = api_client.set_current_utc(current_utc, headers or _ADMIN)
    data = get_success_data(response)
    return data.get("current_utc", current_utc) if isinstance(data, dict) else current_utc


def advance_clock_to(current_utc, headers=None):
    """Alias for :func:`set_logical_clock` that reads better in a test body."""
    return set_logical_clock(current_utc, headers)


def onboard_developer(headers=None, **overrides):
    """Create a Developer (PlatformAdmin) and return the resource."""
    return get_success_data(
        api_client.create_developer(create_developer_payload(**overrides), headers or _ADMIN)
    )


def onboard_investor(headers=None, **overrides):
    """Create an Investor (PlatformAdmin) and return the resource."""
    return get_success_data(
        api_client.create_investor(create_investor_payload(**overrides), headers or _ADMIN)
    )


def form_fund(headers=None, **overrides):
    """Create a SyndicationFund (Underwriter) and return the resource."""
    return get_success_data(
        api_client.create_fund(create_fund_payload(**overrides), headers or _UW)
    )


def open_subscription(
    fund,
    investor,
    committed_cents=None,
    payin_schedule_entries=None,
    headers=None,
    **overrides,
):
    """Create a subscription for ``investor`` against ``fund``.

    The fund's current version is read fresh so ``expected_fund_version`` is
    always the live revision. The call is made with the investor's own headers,
    built from the investor's id.
    """
    fund_id = fund["id"] if isinstance(fund, dict) else fund
    investor_id = investor["id"] if isinstance(investor, dict) else investor
    live_fund = read_fund(fund_id)
    payload = create_subscription_payload(
        investor_id=investor_id,
        expected_fund_version=live_fund["version"],
        committed_cents=(
            committed_cents
            if committed_cents is not None
            else SCENARIO["subscription_meridian"]["committed_cents"]
        ),
        payin_schedule_entries=payin_schedule_entries,
        **overrides,
    )
    return get_success_data(
        api_client.create_subscription(
            fund_id, payload, headers or make_investor_headers(investor_id)
        )
    )


def record_payin(subscription, amount_cents, investor_id=None, headers=None):
    """Record an equity pay-in against a subscription (owning Investor)."""
    subscription_id = subscription["id"] if isinstance(subscription, dict) else subscription
    owner_id = investor_id or (
        subscription.get("investor_id") if isinstance(subscription, dict) else None
    )
    assert owner_id, "record_payin needs the owning investor's id"
    return get_success_data(
        api_client.create_payin(
            subscription_id,
            create_payin_payload(amount_cents),
            headers or make_investor_headers(owner_id),
        )
    )


def add_project(developer_id, fund_id, headers=None, **overrides):
    """Create a Project (Underwriter) and return the resource."""
    return get_success_data(
        api_client.create_project(
            create_project_payload(developer_id, fund_id, **overrides), headers or _UW
        )
    )


def add_allocation(project_id, headers=None, **overrides):
    """Create an Allocation award (Underwriter); starts at AWARDED."""
    return get_success_data(
        api_client.create_allocation(
            project_id, create_allocation_payload(**overrides), headers or _UW
        )
    )


def finalize_underwriting(project, headers=None, **overrides):
    """PUT the project with ``underwriting_action=FINALIZE`` (Underwriter)."""
    project_id = project["id"] if isinstance(project, dict) else project
    live = read_project(project_id)
    payload = update_project_payload(
        live["version"], underwriting_action="FINALIZE", **overrides
    )
    return get_success_data(
        api_client.update_project(project_id, payload, headers or _UW)
    )


def commit_project(project_id, headers=None, payload=None):
    """POST the project's commit (Underwriter only)."""
    return get_success_data(
        api_client.commit_project(project_id, headers or _UW, payload)
    )


def schedule_capital_call(project_id, milestone, headers=None, **overrides):
    """Schedule a capital call against the project's live version."""
    live = read_project(project_id)
    payload = create_capital_call_payload(
        milestone, live["version"], **overrides
    )
    return get_success_data(
        api_client.create_capital_call(project_id, payload, headers or _AM)
    )


def issue_call(call_id, headers=None):
    """Issue a SCHEDULED call (AssetManager); computes called_amount_cents."""
    return get_success_data(api_client.issue_capital_call(call_id, headers or _AM))


def settle_call(call_id, funded_amount_cents, investor_id, headers=None):
    """Settle an ISSUED call (Investor holding a subscription in its fund)."""
    return get_success_data(
        api_client.settle_capital_call(
            call_id, funded_amount_cents, headers or make_investor_headers(investor_id)
        )
    )


def adjust_call(call_id, headers=None):
    """Adjust a call against a re-derived delivery band (AssetManager)."""
    return get_success_data(api_client.adjust_capital_call(call_id, headers or _AM))


def record_project_milestone(project_id, milestone, headers=None):
    """Record a construction, lease-up or placed-in-service milestone."""
    return get_success_data(
        api_client.record_milestone(
            project_id, record_milestone_payload(milestone), headers or _AM
        )
    )


def add_guarantee(project_id, headers=None, **overrides):
    """Record a guarantee (AssetManager); starts ACTIVE with full capacity."""
    return get_success_data(
        api_client.create_guarantee(
            project_id, create_guarantee_payload(**overrides), headers or _AM
        )
    )


def draw_on_guarantee(guarantee_id, requested_amount_cents, headers=None):
    """Draw against a guarantee (AssetManager only); zero is a reinstatement."""
    return get_success_data(
        api_client.draw_guarantee(
            guarantee_id, draw_guarantee_payload(requested_amount_cents), headers or _AM
        )
    )


def open_review(project_id, headers=None, **overrides):
    """Open a compliance review (AssetManager or ComplianceOfficer)."""
    return get_success_data(
        api_client.create_review(
            project_id, create_review_payload(**overrides), headers or _CO
        )
    )


def resolve_review(
    review_id,
    outcome=None,
    corrected_reserve_balance_cents=None,
    headers=None,
    **overrides,
):
    """Resolve a review; omitting ``outcome`` derives it from the risk score."""
    payload = resolve_review_payload(
        outcome=outcome,
        corrected_reserve_balance_cents=corrected_reserve_balance_cents,
        **overrides,
    )
    return get_success_data(
        api_client.resolve_review(review_id, headers or _CO, payload=payload)
    )


def plan_exit_event(project_id, headers=None, **overrides):
    """Create a year-fifteen exit event (Underwriter or AssetManager)."""
    return get_success_data(
        api_client.create_exit_event(
            project_id, create_exit_event_payload(**overrides), headers or _UW
        )
    )


def exercise_exit_action(exit_event_id, action, headers=None):
    """Run one exit action, defaulting to the role the action requires."""
    if headers is None:
        headers = _AM if action in ("OPEN_ROFR", "CLOSE") else _UW
    return get_success_data(
        api_client.exercise_exit_event(exit_event_id, action, headers)
    )


# =============================================================================
# Composite scenarios
# =============================================================================

def setup_canonical_scenario(
    clock=CLOCK_2026_09_02,
    developer_overrides=None,
    investor_overrides=None,
    fund_overrides=None,
    project_overrides=None,
    with_subscription=True,
    subscription_committed_cents=None,
    payin_schedule_entries=None,
    pay_in_full=False,
    with_project=True,
    with_allocation=False,
    with_finalized_underwriting=False,
    with_commit=False,
):
    """The workhorse scenario: developer + investor + fund (+ project).

    Every flag is additive, so one helper covers the whole ladder from "a fund
    exists" to "a committed project with a COMMITTED allocation".

    Returns a :class:`Scenario` with the keys ``clock``, ``developer``,
    ``investor``, ``fund``, ``subscription``, ``project`` and ``allocation``;
    keys whose step was skipped are ``None``.
    """
    set_logical_clock(clock)

    developer = onboard_developer(**(developer_overrides or {}))
    investor = onboard_investor(**(investor_overrides or {}))
    fund = form_fund(**(fund_overrides or {}))

    subscription = None
    if with_subscription:
        subscription = open_subscription(
            fund,
            investor,
            committed_cents=subscription_committed_cents,
            payin_schedule_entries=payin_schedule_entries or [
                dict(entry) for entry in PAYIN_SCHEDULE_FIVE
            ],
        )
        if pay_in_full:
            record_payin(subscription, subscription["committed_cents"], investor["id"])
            subscription = read_subscription(subscription["id"])

    project = None
    allocation = None
    if with_project:
        project = add_project(
            developer["id"], fund["id"], **(project_overrides or {})
        )
        if with_allocation:
            allocation = add_allocation(project["id"])
        if with_finalized_underwriting:
            project = finalize_underwriting(project)
        if with_commit:
            project = commit_project(project["id"])
            if allocation is not None:
                allocation = list_project_allocations(project["id"])[0]

    return Scenario(
        clock=clock,
        developer=developer,
        investor=investor,
        fund=fund,
        subscription=subscription,
        project=project,
        allocation=allocation,
    )


def setup_fund_with_subscription(
    committed_cents=None,
    pay_in=False,
    pay_in_amount_cents=None,
    clock=CLOCK_2026_09_02,
    **overrides,
):
    """Developer + investor + fund + one subscription (optionally paid in).

    ``overrides`` may carry ``developer_overrides``, ``investor_overrides``,
    ``fund_overrides`` and ``payin_schedule_entries``.
    """
    scenario = setup_canonical_scenario(
        clock=clock,
        developer_overrides=overrides.pop("developer_overrides", None),
        investor_overrides=overrides.pop("investor_overrides", None),
        fund_overrides=overrides.pop("fund_overrides", None),
        with_subscription=True,
        subscription_committed_cents=committed_cents,
        payin_schedule_entries=overrides.pop("payin_schedule_entries", None),
        with_project=False,
    )
    if pay_in:
        amount = (
            pay_in_amount_cents
            if pay_in_amount_cents is not None
            else scenario.subscription["committed_cents"]
        )
        record_payin(scenario.subscription, amount, scenario.investor["id"])
        scenario.subscription = read_subscription(scenario.subscription["id"])
    scenario.fund = read_fund(scenario.fund["id"])
    return scenario


def setup_project_with_allocation(
    with_subscription=True, pay_in_full=True, **overrides
):
    """Fund (optionally subscribed) + project + one AWARDED allocation."""
    scenario = setup_canonical_scenario(
        with_subscription=with_subscription,
        pay_in_full=pay_in_full,
        with_project=True,
        with_allocation=True,
        **overrides,
    )
    return scenario


def setup_finalized_project(with_subscription=True, pay_in_full=True, **overrides):
    """Fund + subscription + FINAL underwriting + AWARDED allocation.

    This is :func:`setup_committed_project` stopped one step short of the
    commit: every PRD §3.4 commitment precondition is already satisfied
    (``underwriting_stage`` is ``FINAL``, the fund is committable and the
    project carries an ``AWARDED`` allocation), so a test can drive the commit
    itself and observe the totals it moves.
    """
    return setup_canonical_scenario(
        with_subscription=with_subscription,
        pay_in_full=pay_in_full,
        with_project=True,
        with_allocation=True,
        with_finalized_underwriting=True,
        **overrides,
    )


def setup_committed_project(with_subscription=True, pay_in_full=True, **overrides):
    """Fund + subscription + FINAL underwriting + COMMITTED project.

    The commit moves every AWARDED or RESERVED allocation to COMMITTED and
    leaves the project in status COMMITTED. Pass ``allocation_overrides``
    through ``setup_canonical_scenario`` only before the commit; after the
    commit the allocation's award values are fixed.
    """
    return setup_canonical_scenario(
        with_subscription=with_subscription,
        pay_in_full=pay_in_full,
        with_project=True,
        with_allocation=True,
        with_finalized_underwriting=True,
        with_commit=True,
        **overrides,
    )


def setup_project_with_paid_call(
    milestone="CONSTRUCTION_START",
    milestone_share=0.20,
    delivered_credit_dollars_cents=None,
    scheduled_date=None,
    due_date=None,
    issue_clock=CLOCK_2026_10_05,
    funded_amount_cents=None,
    settle=True,
    **overrides,
):
    """Committed project + one capital call driven to ISSUED or PAID.

    ``delivered_credit_dollars_cents`` records a delivery against the committed
    allocation before the call is issued, which is what selects the
    credit-delivery band used to compute ``called_amount_cents``.

    Returns a :class:`Scenario` with ``call`` (the latest state), plus the
    underlying ``project``, ``allocation``, ``fund``, ``investor`` and
    ``subscription``.
    """
    scenario = setup_committed_project(**overrides)
    if delivered_credit_dollars_cents is not None:
        allocation_id = scenario.allocation["id"]
        get_success_data(
            api_client.record_allocation_delivery(
                scenario.project["id"],
                allocation_id,
                delivered_credit_dollars_cents,
                _AM,
            )
        )
        scenario.allocation = list_project_allocations(scenario.project["id"])[0]

    call = schedule_capital_call(
        scenario.project["id"],
        milestone,
        milestone_share=milestone_share,
        scheduled_date=scheduled_date,
        due_date=due_date,
    )
    set_logical_clock(issue_clock)
    call = issue_call(call["id"])
    if settle:
        funded = (
            funded_amount_cents
            if funded_amount_cents is not None
            else call["called_amount_cents"]
        )
        call = settle_call(call["id"], funded, scenario.investor["id"])
    scenario.call = call
    scenario.project = read_project(scenario.project["id"])
    scenario.fund = read_fund(scenario.fund["id"])
    scenario.subscription = read_subscription(scenario.subscription["id"])
    return scenario


def setup_project_in_compliance_period(
    compliance_period_months=COMPLIANCE_PERIOD_MONTHS_DEFAULT,
    with_subscription=True,
    pay_in_full=True,
    **overrides,
):
    """Drive a committed project all the way into COMPLIANCE_PERIOD.

    Creates and settles the four gating capital calls — CONSTRUCTION_START,
    CONSTRUCTION_50PCT, LEASE_UP_50PCT and LEASE_UP_STABILIZED — and records
    the milestone each one unlocks, then stamps PLACED_IN_SERVICE. The clock is
    left at the placed-in-service instant.

    Returns a :class:`Scenario` with ``calls`` (the four settled calls) in
    addition to the usual keys.
    """
    scenario = setup_committed_project(
        with_subscription=with_subscription,
        pay_in_full=pay_in_full,
        project_overrides=dict(
            {"compliance_period_months": compliance_period_months},
            **(overrides.pop("project_overrides", None) or {}),
        ),
        **overrides,
    )
    calls = []
    for (
        call_milestone,
        project_milestone,
        scheduled_date,
        due_date,
        issue_clock,
    ) in _MILESTONE_CHAIN:
        call = schedule_capital_call(
            scenario.project["id"],
            call_milestone,
            scheduled_date=scheduled_date,
            due_date=due_date,
        )
        set_logical_clock(issue_clock)
        call = issue_call(call["id"])
        call = settle_call(call["id"], call["called_amount_cents"], scenario.investor["id"])
        calls.append(call)
        scenario.project = record_project_milestone(
            scenario.project["id"], project_milestone
        )
    scenario.calls = calls
    scenario.fund = read_fund(scenario.fund["id"])
    scenario.subscription = read_subscription(scenario.subscription["id"])
    return scenario


def setup_exit_eligible_project(
    compliance_period_months=COMPLIANCE_PERIOD_MONTHS_DEFAULT,
    exit_clock=None,
    **overrides,
):
    """A project in EXIT_ELIGIBLE, ready for an exit event to be planned.

    The compliance period must have run in full and the project must carry no
    compliance failure, so the clock is advanced past the placed-in-service
    stamp plus ``compliance_period_months`` before the project is read back.
    """
    scenario = setup_project_in_compliance_period(
        compliance_period_months=compliance_period_months, **overrides
    )
    if exit_clock is None:
        # The placed-in-service stamp is the last chain instant; step well past
        # the derived compliance end.
        exit_clock = "2043-06-01T00:00:00Z"
    set_logical_clock(exit_clock)
    scenario.project = read_project(scenario.project["id"])
    scenario.clock = exit_clock
    return scenario


def setup_two_projects_under_one_fund(second_project_overrides=None, **overrides):
    """Two committed projects under the same developer and fund.

    The fund is subscribed and both projects are finalized, awarded and
    committed, which is the precondition for the two-distressed-project
    cascades. The second project defaults to Juniper Flats.
    """
    scenario = setup_committed_project(**overrides)
    second = add_project(
        scenario.developer["id"],
        scenario.fund["id"],
        **(second_project_overrides or dict(SCENARIO["project_juniper"])),
    )
    add_allocation(second["id"])
    second = finalize_underwriting(second)
    second = commit_project(second["id"])
    scenario.project2 = second
    scenario.allocation2 = list_project_allocations(second["id"])[0]
    scenario.fund = read_fund(scenario.fund["id"])
    return scenario


def setup_fund_at_close_threshold(
    target_equity_cents=500_000_000,
    close_threshold_pct=FUND_CLOSE_THRESHOLD_DEFAULT,
    at_threshold_cents=None,
    under_threshold_cents=None,
    **overrides,
):
    """Two funds built to sit exactly on either side of the close threshold.

    The first fund is subscribed exactly to
    ``target_equity_cents * close_threshold_pct`` and must reach CLOSING; the
    second is subscribed one cent below and must stay FORMING.

    Both subscribers are TIER_3 by default because a TIER_1 investor is capped
    at 300000000 cents and a TIER_2 investor at 400000000 cents per fund, so a
    near-threshold commitment on a 500000000-cent target is only expressible
    with an uncapped tier.
    """
    exact = (
        at_threshold_cents
        if at_threshold_cents is not None
        else int(round(target_equity_cents * close_threshold_pct))
    )
    under = under_threshold_cents if under_threshold_cents is not None else exact - 1

    scenario = setup_canonical_scenario(
        with_project=False,
        with_subscription=False,
        fund_overrides={
            "target_equity_cents": target_equity_cents,
            "close_threshold_pct": close_threshold_pct,
        },
        **overrides,
    )
    fund_at = scenario.fund
    subscription_at = open_subscription(fund_at, scenario.investor, committed_cents=exact)

    second_investor = onboard_investor(
        **dict(SCENARIO["investor_northline"], risk_tier="TIER_3")
    )
    second_fund = form_fund(
        **dict(
            SCENARIO["fund_ix"],
            target_equity_cents=target_equity_cents,
            close_threshold_pct=close_threshold_pct,
        )
    )
    subscription_under = open_subscription(
        second_fund, second_investor, committed_cents=under
    )

    scenario.fund_at_threshold = read_fund(fund_at["id"])
    scenario.subscription_at_threshold = subscription_at
    scenario.investor_under = second_investor
    scenario.fund_under_threshold = read_fund(second_fund["id"])
    scenario.subscription_under_threshold = subscription_under
    return scenario


def setup_delivery_ratio_scenario(
    delivered_credit_dollars_cents,
    awarded_credit_dollars_cents=None,
    milestone="CONSTRUCTION_START",
    milestone_share=0.20,
    issue_clock=CLOCK_2026_10_05,
    **overrides,
):
    """A committed project whose COMMITTED allocation carries a known delivery.

    The delivery ratio of the committed allocation is what selects the
    credit-delivery band, so this is the setup for the band-boundary and
    ratchet tests. ``called_amount_cents`` is computed at issue time and is
    readable off ``scenario.call``.
    """
    scenario = setup_committed_project(**overrides)
    if awarded_credit_dollars_cents is not None:
        # The award is an input; re-awarding after commit is not permitted, so
        # callers who need a different award build the project themselves and
        # pass the resulting allocation in. This guard keeps the mismatch loud.
        assert scenario.allocation["awarded_credit_dollars_cents"] == (
            awarded_credit_dollars_cents
        ), (
            "setup_delivery_ratio_scenario cannot change the award after commit; "
            "build the allocation through setup_committed_project's "
            "project_overrides instead"
        )
    get_success_data(
        api_client.record_allocation_delivery(
            scenario.project["id"],
            scenario.allocation["id"],
            delivered_credit_dollars_cents,
            _AM,
        )
    )
    scenario.allocation = list_project_allocations(scenario.project["id"])[0]
    call = schedule_capital_call(
        scenario.project["id"], milestone, milestone_share=milestone_share
    )
    set_logical_clock(issue_clock)
    scenario.call = issue_call(call["id"])
    scenario.project = read_project(scenario.project["id"])
    scenario.fund = read_fund(scenario.fund["id"])
    return scenario


def setup_defaulted_subscription(
    committed_cents=None,
    paid_in_cents=100_000_000,
    funded_amount_cents=1_000_000,
    milestone_share=0.20,
    **overrides,
):
    """A subscription driven to DEFAULTED by a short settlement.

    The shortfall is the whole called amount less the funded amount; it lands
    on every subscription of the project's fund, so with a large enough call
    the subscription breaches the 20-percent band, defaults, and suspends its
    investor. ``scenario.fund`` is re-read so the caller can assert the equity
    invariant.
    """
    scenario = setup_canonical_scenario(
        with_subscription=True,
        subscription_committed_cents=committed_cents,
        with_project=True,
        with_allocation=True,
        with_finalized_underwriting=True,
        with_commit=True,
        **overrides,
    )
    record_payin(scenario.subscription, paid_in_cents, scenario.investor["id"])
    call = schedule_capital_call(
        scenario.project["id"], "CONSTRUCTION_START", milestone_share=milestone_share
    )
    set_logical_clock(CLOCK_2026_10_05)
    call = issue_call(call["id"])
    call = settle_call(call["id"], funded_amount_cents, scenario.investor["id"])
    scenario.call = call
    scenario.subscription = read_subscription(scenario.subscription["id"])
    scenario.investor = read_investor(scenario.investor["id"])
    scenario.fund = read_fund(scenario.fund["id"])
    return scenario


def setup_suspended_investor(**overrides):
    """An investor suspended by one of its own defaulted subscriptions."""
    return setup_defaulted_subscription(**overrides)


def setup_escalated_review(
    project_id=None,
    review_overrides=None,
    outcome="ESCALATED",
    resolve_headers=None,
    **overrides,
):
    """Open a review that scores into the ESCALATED band and escalate it.

    Escalating moves the owning project to DISTRESSED, recomputes the
    developer's status and recomputes the fund's posture. The review defaults
    score 81 (occupancy 0.78, DSCR 0.95, reserves 30000000).
    """
    scenario = setup_committed_project(**overrides)
    review = open_review(
        project_id or scenario.project["id"], **(review_overrides or {})
    )
    review = resolve_review(review["id"], outcome=outcome, headers=resolve_headers)
    scenario.review = review
    scenario.project = read_project(scenario.project["id"])
    scenario.fund = read_fund(scenario.fund["id"])
    scenario.developer = read_developer(scenario.developer["id"])
    return scenario


def setup_distressed_project(**overrides):
    """A committed project pushed into DISTRESSED by an escalated review."""
    return setup_escalated_review(**overrides)


def setup_frozen_fund(**overrides):
    """A fund with two DISTRESSED projects, so its posture is FROZEN.

    Escalating a review on each of the fund's two projects distresses both,
    which drives the derived posture past WATCH to FROZEN.
    """
    scenario = setup_two_projects_under_one_fund(**overrides)
    first = open_review(scenario.project["id"])
    resolve_review(first["id"], outcome="ESCALATED")
    second = open_review(scenario.project2["id"], review_period_index=2)
    resolve_review(second["id"], outcome="ESCALATED")
    scenario.review = first
    scenario.review2 = second
    scenario.project = read_project(scenario.project["id"])
    scenario.project2 = read_project(scenario.project2["id"])
    scenario.fund = read_fund(scenario.fund["id"])
    scenario.developer = read_developer(scenario.developer["id"])
    return scenario


def setup_developer_near_coverage_boundary(
    net_worth_cents=2_000_000_000,
    guarantee_amount_cents=1_000_000_000,
    **overrides,
):
    """A developer whose first guarantee puts its coverage ratio at exactly 2.0.

    ``net_worth_cents`` divided by the guarantee exposure is exactly 2.0, which
    is the inclusive boundary that still derives ELIGIBLE; a further cent of
    exposure drops the ratio below 2.0 and flips the developer to WATCH.
    """
    scenario = setup_canonical_scenario(
        developer_overrides=dict(
            SCENARIO["developer_riverstone"], net_worth_cents=net_worth_cents
        ),
        with_subscription=False,
        with_project=True,
        **overrides,
    )
    scenario.guarantee = add_guarantee(
        scenario.project["id"],
        guarantee_type="OPERATING_DEFICIT",
        guaranteed_amount_cents=guarantee_amount_cents,
        recapture_pct=0.0,
    )
    scenario.developer = read_developer(scenario.developer["id"])
    return scenario


def setup_capital_call_buffer_scenario(
    first_scheduled_date="2026-10-01T00:00:00Z",
    first_due_date="2026-10-31T00:00:00Z",
    first_issue_clock=CLOCK_2026_10_05,
    second_scheduled_date="2026-11-29T00:00:00Z",
    second_due_date="2026-12-29T00:00:00Z",
    second_issue_clock="2026-11-30T00:00:00Z",
    **overrides,
):
    """A PAID first call plus a second SCHEDULED call on a different milestone.

    The default second call starts 29 days after the first call's due date, so
    issuing it is rejected with ``ERR_CALL_BUFFER_TOO_SHORT``; passing a
    ``second_scheduled_date`` at least 30 days after the first due date makes
    the same issue succeed.
    """
    scenario = setup_committed_project(**overrides)
    first = schedule_capital_call(
        scenario.project["id"],
        "CONSTRUCTION_START",
        scheduled_date=first_scheduled_date,
        due_date=first_due_date,
    )
    set_logical_clock(first_issue_clock)
    first = issue_call(first["id"])
    first = settle_call(first["id"], first["called_amount_cents"], scenario.investor["id"])

    second = schedule_capital_call(
        scenario.project["id"],
        "CONSTRUCTION_50PCT",
        scheduled_date=second_scheduled_date,
        due_date=second_due_date,
    )
    set_logical_clock(second_issue_clock)
    scenario.call = first
    scenario.call2 = second
    scenario.project = read_project(scenario.project["id"])
    return scenario


def setup_guarantee_scenario(
    guarantee_type="COMPLETION",
    guaranteed_amount_cents=90_000_000,
    with_escalated_review=True,
    **overrides,
):
    """A committed project carrying one guarantee, optionally already escalated.

    A COMPLETION or RECAPTURE draw requires an ESCALATED review on the project,
    so ``with_escalated_review=True`` makes the guarantee drawable on the
    merits.
    """
    scenario = setup_committed_project(**overrides)
    scenario.guarantee = add_guarantee(
        scenario.project["id"],
        guarantee_type=guarantee_type,
        guaranteed_amount_cents=guaranteed_amount_cents,
        recapture_pct=0.0,
    )
    if with_escalated_review:
        review = open_review(scenario.project["id"])
        review = resolve_review(review["id"], outcome="ESCALATED")
        scenario.review = review
    scenario.project = read_project(scenario.project["id"])
    scenario.developer = read_developer(scenario.developer["id"])
    scenario.fund = read_fund(scenario.fund["id"])
    return scenario
