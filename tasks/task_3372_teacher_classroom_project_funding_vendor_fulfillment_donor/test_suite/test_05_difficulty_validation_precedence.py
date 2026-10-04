"""Validation precedence: when one request violates two rules, the ladder in
the contract decides which error reports itself."""

from test_helpers import (
    ADMIN_HEADERS,
    ApiErrorId,
    assert_cents,
    fixtures,
    validate_error,
    validate_success,
)
from test_helpers import factories as f
from test_helpers.constants import FUNDING_DEADLINE
from test_helpers.test_users import make_donor_headers, make_teacher_headers


# ── Temporal (funding window) outranks fiscal (remaining need) ─────────────


def _late_funding_world(api):
    """FUNDING project at 9000 of 10959, with the clock exactly on the deadline
    and no sweep run, so the row still reads FUNDING."""
    world = fixtures.setup_funding_project(api)
    donor = fixtures.create_donor(api)
    fixtures.donate(api, world["project"]["id"], donor, 9000)
    fixtures.set_clock(api, FUNDING_DEADLINE)
    world["donor"] = donor
    return world


def test_late_oversized_donation_reports_the_temporal_error(api):
    """One donation violates both the funding window and the remaining need;
    the temporal rule sits earlier on the ladder.

    PRD: "When a single request violates several rules at once, the checks are evaluated in a fixed priority order and the earliest failing check determines the error returned."
    PRD: "**Temporal windows**, in this order: donation after the funding deadline (`ERR_FUNDING_WINDOW_CLOSED`)"
    PRD: "**Fiscal rules**, in this order: the project has no items at submit (`ERR_NO_ITEMS` — always checked before the goal range, so an empty project reports `ERR_NO_ITEMS` and never `ERR_GOAL_OUT_OF_RANGE`), the computed goal is out of range (`ERR_GOAL_OUT_OF_RANGE`), the donation exceeds the remaining need or is too small (`ERR_DONATION_EXCEEDS_REMAINING`)"
    Design: Difficulty/priority_pair_validation_conflict/late_oversized_donation_temporal_precedes_fiscal
    """
    world = _late_funding_world(api)
    project_id = world["project"]["id"]

    # 5000c exceeds the 1959c remaining need AND the clock is on the deadline.
    res = api.create_donation(
        project_id, f.donation_payload(5000), make_donor_headers(world["donor"]["id"])
    )
    validate_error(res, ApiErrorId.ERR_FUNDING_WINDOW_CLOSED, 409)

    project = fixtures.read_project(api, project_id)
    assert project["status"] == "FUNDING", "no sweep ran, so the row still reads FUNDING"
    assert_cents(project["funded_cents"], 9000, "funded_cents unchanged")


def test_donation_at_exact_deadline_is_late_even_within_remaining_need(api):
    """The temporal rule alone fires at the exact deadline: the clock must be
    strictly before it, so a compliant amount is still rejected.

    PRD: "The project must be in `FUNDING` — otherwise `ERR_INVALID_STATE` — and the logical clock must be strictly before the project's `funding_deadline`; note that a project past its deadline still reads `FUNDING` until the sweep runs, and donations into it are rejected with `ERR_FUNDING_WINDOW_CLOSED`."
    Design: Difficulty/priority_pair_validation_conflict/late_oversized_donation_temporal_precedes_fiscal
    """
    world = _late_funding_world(api)
    project_id = world["project"]["id"]

    # 1000c fits the 1959c remaining need; only the temporal rule is violated.
    res = api.create_donation(
        project_id, f.donation_payload(1000), make_donor_headers(world["donor"]["id"])
    )
    validate_error(res, ApiErrorId.ERR_FUNDING_WINDOW_CLOSED, 409)

    project = fixtures.read_project(api, project_id)
    assert_cents(project["funded_cents"], 9000, "funded_cents unchanged")


# ── Duplicate-item constraint outranks catalog referential check ───────────


def test_duplicate_discontinued_item_reports_the_duplicate_error(api):
    """Re-adding an item that is both already on the project and DISCONTINUED
    reports the duplicate constraint, which sits earlier on the ladder.

    PRD: "When a single request violates several rules at once, the checks are evaluated in a fixed priority order and the earliest failing check determines the error returned."
    PRD: "**Business constraints**, in this order: the teacher already has an active pipeline project (`ERR_ACTIVE_PROJECT_EXISTS`), the teacher owes a thank-you package (`ERR_THANK_YOU_OUTSTANDING`), the vetting reviewer also screened the project (`ERR_SEGREGATION_OF_DUTIES`), the project already contains the catalog item (`ERR_DUPLICATE_CATALOG_ITEM`), and an open fraud case already exists for the teacher (`ERR_FRAUD_CASE_ALREADY_OPEN`)."
    PRD: "**Referential business rules**, in this order: the catalog item is unavailable or over its per-project cap (`ERR_CATALOG_ITEM_UNAVAILABLE`)"
    Design: Difficulty/priority_pair_validation_conflict/duplicate_discontinued_item_constraint_precedes_referential
    """
    world = fixtures.setup_draft_project(api, item_specs=[(f.book_item_spec(), 1)])
    project_id = world["project"]["id"]
    item_id = world["items"][0]["id"]

    # Discontinue the item after it is already on the project.
    validate_success(
        api.patch_catalog_item(world["vendor"]["id"], item_id, {"status": "DISCONTINUED"},
                               ADMIN_HEADERS),
        200,
    )

    # Re-adding it violates the duplicate constraint AND the availability rule.
    res = api.add_project_item(
        project_id,
        f.add_item_payload(item_id, 2, fixtures.current_project_version(api, project_id)),
        make_teacher_headers(world["teacher"]["id"]),
    )
    validate_error(res, ApiErrorId.ERR_DUPLICATE_CATALOG_ITEM, 409)

    rows = fixtures.project_items_for(api, project_id)
    assert len(rows) == 1, "the rejected add left the item list untouched"


def test_duplicate_add_of_an_active_item_reports_the_duplicate_error(api):
    """The duplicate rule on its own: the item is healthy, the repeat is not.

    PRD: "Adding the same `catalog_item_id` twice within one project fails with `ERR_DUPLICATE_CATALOG_ITEM`."
    Design: Difficulty/priority_pair_validation_conflict/duplicate_discontinued_item_constraint_precedes_referential
    """
    world = fixtures.setup_draft_project(api, item_specs=[(f.book_item_spec(), 1)])
    project_id = world["project"]["id"]
    item_id = world["items"][0]["id"]

    res = api.add_project_item(
        project_id,
        f.add_item_payload(item_id, 2, fixtures.current_project_version(api, project_id)),
        make_teacher_headers(world["teacher"]["id"]),
    )
    validate_error(res, ApiErrorId.ERR_DUPLICATE_CATALOG_ITEM, 409)
    assert len(fixtures.project_items_for(api, project_id)) == 1
