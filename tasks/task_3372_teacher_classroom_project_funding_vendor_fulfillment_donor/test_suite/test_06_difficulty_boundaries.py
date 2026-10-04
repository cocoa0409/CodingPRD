"""Boundary precision: exact equality funds a project, and the poverty gate
is inclusive at the threshold."""

from test_helpers import (
    ApiErrorId,
    assert_cents,
    fixtures,
    validate_error,
    validate_paginated,
    validate_success,
)


# ── Exact-goal funding boundary ────────────────────────────────────────────


def test_exact_goal_equality_tips_project_funded(api):
    """A donation closing the gap exactly flips the project to FUNDED and
    fires purchase-order issuance and the thank-you package.

    PRD: "The instant a donation or an equity allocation makes `funded_cents` greater than or equal to `goal_cents` — the boundary is inclusive, so exact equality funds the project — the project transitions from `FUNDING` to `FUNDED` automatically."
    PRD: "At that moment the system groups the project's pinned items by vendor, auto-issues exactly one purchase order per distinct vendor with at least one item (§3.7), and auto-creates exactly one thank-you package for the project in status `PENDING` — there is exactly one package per funded project, enforced by uniqueness of the package's `project_id`."
    Design: Difficulty/boundary_precision_check/exact_goal_equality_tips_project_funded
    """
    world = fixtures.setup_funding_project(api)  # goal 10959
    project_id = world["project"]["id"]
    donor = fixtures.create_donor(api)

    fixtures.donate(api, project_id, donor, 9000)
    tip = fixtures.donate(api, project_id, donor, 1959)
    assert tip["status"] == "CAPTURED"

    project = fixtures.read_project(api, project_id)
    assert_cents(project["funded_cents"], 10959, "funded_cents")
    assert_cents(project["goal_cents"], 10959, "goal_cents")
    assert project["status"] == "FUNDED", "exact equality funds (the boundary is inclusive)"

    pos = fixtures.purchase_orders_for(api, project_id)
    assert len(pos) == 1, "single vendor -> exactly one purchase order"
    assert pos[0]["status"] == "ISSUED"
    assert_cents(pos[0]["line_total_cents"], 10000, "po line_total_cents")
    assert_cents(pos[0]["shipping_fee_cents"], 959, "po shipping_fee_cents")

    packages, meta = validate_paginated(api.get_thank_you_package(project_id, fixtures.ADMIN_HEADERS))
    assert len(packages) == 1, "one thank-you package auto-created at FUNDED"
    assert packages[0]["status"] == "PENDING"


def test_one_cent_short_of_the_goal_leaves_the_project_funding(api):
    """The same comparison one cent lower leaves the project in FUNDING.

    PRD: "The instant a donation or an equity allocation makes `funded_cents` greater than or equal to `goal_cents` — the boundary is inclusive, so exact equality funds the project — the project transitions from `FUNDING` to `FUNDED` automatically."
    Design: Difficulty/boundary_precision_check/exact_goal_equality_tips_project_funded
    """
    world = fixtures.setup_funding_project(api)  # goal 10959
    project_id = world["project"]["id"]
    donor = fixtures.create_donor(api)

    fixtures.donate(api, project_id, donor, 9000)
    short = fixtures.donate(api, project_id, donor, 1958)  # within remaining need 1959
    assert short["status"] == "CAPTURED"

    project = fixtures.read_project(api, project_id)
    assert_cents(project["funded_cents"], 10958, "funded_cents")
    assert project["status"] == "FUNDING", "10958 < 10959: one cent short does not fund"
    assert fixtures.purchase_orders_for(api, project_id) == []


# ── Inclusive poverty threshold on the equity selector ─────────────────────


def test_poverty_exactly_at_threshold_is_eligible(api):
    """poverty_pct equal to min_poverty_pct qualifies: the gate is inclusive.

    PRD: "A school qualifies for a fund when its `poverty_pct` is greater than or equal to `min_poverty_pct` — the boundary is inclusive."
    PRD: "The grant amount is the lesser of the project's remaining need (`goal_cents` minus `funded_cents`) and the fund's `remaining_cents`. It is recorded as a donation with `kind` set to `EQUITY_GRANT`, `donor_id` null, `equity_fund_id` set to the fund, `matched_cents` 0, and status `CAPTURED`."
    Design: Difficulty/boundary_precision_check/poverty_exactly_at_threshold_is_equity_eligible
    """
    world = fixtures.setup_funding_project(
        api, school_overrides={"name": "Boundary Elementary", "district": "Boundary ISD",
                               "poverty_pct": 75.0, "ell_pct": 50.0}
    )
    fund = fixtures.create_equity_fund(api, min_poverty_pct=75.0, budget_cents=500000)

    grant = validate_success(api.allocate_equity_fund(fund["id"], {}, fixtures.ADMIN_HEADERS), 200)
    assert grant["kind"] == "EQUITY_GRANT"
    assert grant["project_id"] == world["project"]["id"]
    assert grant["donor_id"] is None
    assert grant["equity_fund_id"] == fund["id"]
    assert grant["status"] == "CAPTURED"
    assert_cents(grant["amount_cents"], 10959, "min(remaining need 10959, fund 500000)")

    project = fixtures.read_project(api, world["project"]["id"])
    assert project["status"] == "FUNDED", "the grant tipped the project and fired issuance"
    fund_after = fixtures.read_equity_fund(api, fund["id"])
    assert_cents(fund_after["remaining_cents"], 489041, "fund remaining_cents")


def test_poverty_one_tenth_below_threshold_is_not_eligible(api):
    """poverty_pct one tenth below the threshold leaves the candidate set empty.

    PRD: "A school qualifies for a fund when its `poverty_pct` is greater than or equal to `min_poverty_pct` — the boundary is inclusive."
    PRD: "An empty candidate set fails with `ERR_NO_ELIGIBLE_PROJECT`."
    Design: Difficulty/boundary_precision_check/poverty_exactly_at_threshold_is_equity_eligible
    """
    world = fixtures.setup_funding_project(
        api, school_overrides={"name": "Just Below Elementary", "district": "Boundary ISD",
                               "poverty_pct": 74.9, "ell_pct": 50.0}
    )
    fund = fixtures.create_equity_fund(api, min_poverty_pct=75.0, budget_cents=500000)

    res = api.allocate_equity_fund(fund["id"], {}, fixtures.ADMIN_HEADERS)
    validate_error(res, ApiErrorId.ERR_NO_ELIGIBLE_PROJECT, 422)

    fund_after = fixtures.read_equity_fund(api, fund["id"])
    assert_cents(fund_after["remaining_cents"], 500000, "fund remaining_cents unchanged")
    assert fund_after["status"] == "ACTIVE"
    project = fixtures.read_project(api, world["project"]["id"])
    assert project["status"] == "FUNDING"
    assert_cents(project["funded_cents"], 0, "funded_cents unchanged")
