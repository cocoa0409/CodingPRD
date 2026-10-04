"""Validation priority pairs: the earlier tier decides which error surfaces."""

from prd_bench_local_runner.testing import get_success_data, validate_error, validate_error_is_one_of

from test_helpers import BRANCH_DIRECTOR_HEADERS, make_member_headers
from test_helpers import factories, fixtures


def test_hold_on_cancelled_membership_reports_state_not_allowance(api):
    """A hold on a CANCELLED membership fails on state legality even when the
    trailing-allowance ledger would also overflow: the state tier runs first.

    PRD §3.3: "A `Member` or `BranchDirector` may place an `ACTIVE` membership
    on hold by supplying a `hold_until` date; attempting it from any other
    status is `ERR_INVALID_STATE`."
    PRD §2.7: "Authentication (missing or malformed identity headers,
    `ERR_UNAUTHENTICATED`) comes first, then authorization and member-ownership
    checks (`ERR_UNAUTHORIZED`)."
    PRD §2.7: "Next come state-legality checks (`ERR_INVALID_STATE`,
    `ERR_CAMPAIGN_NOT_ACTIVE`, `ERR_ALREADY_TERMINAL`), then request-schema and
    composition checks (`ERR_INVALID_REQUEST`, `ERR_DOCUMENTATION_MISSING`,
    `ERR_HOUSEHOLD_CAP_EXCEEDED`, `ERR_TIME_RANGE_INVALID`)."
    PRD §2.7: "Fiscal limits are evaluated second to last (`ERR_POOL_EXHAUSTED`,
    `ERR_POOL_WOULD_GO_NEGATIVE`, `ERR_AWARD_INELIGIBLE`,
    `ERR_HOLD_ALLOWANCE_EXCEEDED`, `ERR_REINSTATE_WINDOW_PASSED`), and the
    optimistic-concurrency stale-version check (`ERR_STALE_VERSION`) runs last
    of all."

    Design: Difficulty/priority_pair_validation_conflict/hold_rejected_by_state_before_hold_allowance
    """
    world = fixtures.setup_membership(api)
    member_headers = make_member_headers(world["member"]["id"])
    membership = world["membership"]

    # Burn 99 days of trailing hold allowance: hold 2026-09-01 .. 2026-12-10,
    # resume early on 2026-12-09 (one day before hold_until, so the clock has
    # not auto-resumed the hold); the window clips to the actual resume date.
    get_success_data(api.hold_membership(membership["id"], {"hold_until": "2026-12-10"}, member_headers))
    fixtures.set_clock(api, "2026-12-09T00:00:00Z")
    get_success_data(api.resume_membership(membership["id"], member_headers))
    resumed = get_success_data(api.get_membership(membership["id"], BRANCH_DIRECTOR_HEADERS))
    assert resumed["hold_days_used_trailing_12mo"] == 99

    # Terminal cancel, then a 91-day hold request that would also break the allowance.
    # PRD §3.3 names both state-legality errors for a CANCELLED membership
    # ("any further transition attempt ... is `ERR_ALREADY_TERMINAL`" versus
    # hold "from any other status is `ERR_INVALID_STATE`"); both sit in the
    # same §2.7 state-legality tier, which precedes the fiscal allowance tier.
    get_success_data(api.cancel_membership(membership["id"], member_headers))
    response = api.hold_membership(membership["id"], {"hold_until": "2027-03-10"}, member_headers)
    error_id = validate_error_is_one_of(response, ["ERR_INVALID_STATE", "ERR_ALREADY_TERMINAL"])
    assert error_id != "ERR_HOLD_ALLOWANCE_EXCEEDED"

    current = get_success_data(api.get_membership(membership["id"], BRANCH_DIRECTOR_HEADERS))
    assert current["status"] == "CANCELLED"


def test_hold_window_rejection_precedes_allowance_accounting(api):
    """A hold whose window is itself illegal fails on the window rule, and no
    hold days accrue to the trailing allowance.

    PRD §3.3: "The hold duration — `hold_until` measured from the current date —
    must be at least 30 days and at most 180 days, and `hold_until` must be in
    the future, else the request is rejected with `ERR_HOLD_WINDOW_INVALID`."
    PRD §2.7: "Childcare licensing-ratio safety is checked after that
    (`ERR_RATIO_CAPACITY_EXCEEDED`), followed by temporal-window rules
    (`ERR_REGISTRATION_WINDOW_CLOSED`, `ERR_MEMBER_PRIORITY_ONLY`,
    `ERR_HOLD_WINDOW_INVALID`, `ERR_PARTICIPANT_AGE_INVALID`,
    `ERR_MEMBER_ONLY_PROGRAM`), then capacity-and-uniqueness constraints
    (`ERR_SESSION_FULL`, `ERR_SPACE_CONFLICT`, `ERR_DUPLICATE_ACTIVE_AWARD`,
    `ERR_CAMPAIGN_ALREADY_ACTIVE`, `ERR_DUPLICATE_DRAFT`, `ERR_DUPLICATE_EMAIL`,
    `ERR_DUPLICATE_BRANCH_CODE`)."
    PRD §2.7: "Fiscal limits are evaluated second to last (`ERR_POOL_EXHAUSTED`,
    `ERR_POOL_WOULD_GO_NEGATIVE`, `ERR_AWARD_INELIGIBLE`,
    `ERR_HOLD_ALLOWANCE_EXCEEDED`, `ERR_REINSTATE_WINDOW_PASSED`), and the
    optimistic-concurrency stale-version check (`ERR_STALE_VERSION`) runs last
    of all."

    Design: Difficulty/priority_pair_validation_conflict/hold_rejected_by_state_before_hold_allowance
    """
    world = fixtures.setup_membership(api)
    member_headers = make_member_headers(world["member"]["id"])
    membership = world["membership"]

    validate_error(
        api.hold_membership(membership["id"], {"hold_until": "2026-09-21"}, member_headers),
        "ERR_HOLD_WINDOW_INVALID",
    )
    current = get_success_data(api.get_membership(membership["id"], BRANCH_DIRECTOR_HEADERS))
    assert current["status"] == "ACTIVE"
    assert current["hold_days_used_trailing_12mo"] == 0


def test_cross_branch_category_is_referential_not_fiscal(api):
    """A category from a different branch is a foreign-key failure; the
    membership row is untouched and no dues recompute happens.

    PRD §3.2: "The category must belong to the same branch as the membership; a
    `category_id` that does not resolve or that belongs to a different branch is
    `ERR_CATEGORY_NOT_FOUND`."
    PRD §2.7: "Existence of every path identifier follows (`ERR_NOT_FOUND`),
    then resolution of body foreign keys (`ERR_BRANCH_NOT_FOUND`,
    `ERR_CATEGORY_NOT_FOUND`, `ERR_MEMBER_NOT_FOUND`, `ERR_SPACE_NOT_FOUND`,
    `ERR_SESSION_NOT_FOUND`, `ERR_APPLICATION_NOT_FOUND`)."
    PRD §2.7: "Fiscal limits are evaluated second to last"

    Design: Difficulty/priority_pair_validation_conflict/approve_rejected_by_referential_before_pool_solvency
    """
    world = fixtures.setup_branch_with_category(api)
    branch_up = fixtures.create_branch(
        api, world["association"]["id"], code="UP", name="Uptown", branch_goal_cents=500_000
    )
    category_up = fixtures.create_category(
        api, branch_up["id"], name="Family", household_type="FAMILY",
        monthly_dues_cents=12_000, max_adults=2, max_dependents=6,
    )
    member = fixtures.create_member(api, world["branch"]["id"])
    membership = get_success_data(
        api.create_membership(
            factories.membership_payload(world["branch"]["id"], world["category"]["id"], member["id"]),
            make_member_headers(member["id"]),
        )
    )

    response = api.update_membership(
        membership["id"],
        {"category_id": category_up["id"], "expected_membership_version": membership["version"]},
        BRANCH_DIRECTOR_HEADERS,
    )
    validate_error(response, "ERR_CATEGORY_NOT_FOUND")

    current = get_success_data(api.get_membership(membership["id"], BRANCH_DIRECTOR_HEADERS))
    assert current["category_id"] == world["category"]["id"]
    assert current["version"] == membership["version"], "the failed PATCH must not bump the version"


def test_unresolvable_category_is_the_same_referential_failure(api):
    """An unknown category id and a foreign-branch category id surface the same
    referential error, ahead of every business rule.

    PRD §3.2: "The category must belong to the same branch as the membership; a
    `category_id` that does not resolve or that belongs to a different branch is
    `ERR_CATEGORY_NOT_FOUND`."

    Design: Difficulty/priority_pair_validation_conflict/approve_rejected_by_referential_before_pool_solvency
    """
    world = fixtures.setup_membership(api)
    membership = world["membership"]

    response = api.update_membership(
        membership["id"],
        {
            "category_id": "11111111-2222-3333-4444-555555555555",
            "expected_membership_version": membership["version"],
        },
        BRANCH_DIRECTOR_HEADERS,
    )
    validate_error(response, "ERR_CATEGORY_NOT_FOUND")

    current = get_success_data(api.get_membership(membership["id"], BRANCH_DIRECTOR_HEADERS))
    assert current["category_id"] == world["category"]["id"]
    assert current["version"] == membership["version"]
