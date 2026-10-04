"""Validation corners, part two: the temporal windows (funding, match,
choice, equity), the referential target checks, the fiscal donation cap, and
the one-open-fraud-case rule."""

from test_helpers import (
    ADMIN_HEADERS,
    ApiErrorId,
    assert_cents,
    fixtures,
    validate_error,
)
from test_helpers import factories as f
from test_helpers.constants import AFTER_CHOICE_DEADLINE, FUNDING_DEADLINE
from test_helpers.test_users import make_donor_headers


def test_equity_allocate_with_an_empty_pool_returns_no_eligible_project(api):
    """A fund whose state matches no FUNDING project finds an empty candidate
    set.

    PRD: "The eligible candidate set is every project in `FUNDING` whose `funding_deadline` is still strictly ahead of the clock, whose school's `state_code` equals the fund's, whose school's `poverty_pct` is at least the fund's `min_poverty_pct`, and whose `subject` equals the fund's `subject` whenever the fund restricts one."
    PRD: "An empty candidate set fails with `ERR_NO_ELIGIBLE_PROJECT`."
    Design: Corner/validations/equity_allocate_with_empty_pool_returns_no_eligible_project
    """
    world = fixtures.setup_funding_project(api)  # school in TX
    fund = fixtures.create_equity_fund(
        api, name="Nevada Equity Fund", state_code="NV", min_poverty_pct=50.0, budget_cents=50000
    )

    res = api.allocate_equity_fund(fund["id"], {}, ADMIN_HEADERS)
    validate_error(res, ApiErrorId.ERR_NO_ELIGIBLE_PROJECT, 422)

    fund_after = fixtures.read_equity_fund(api, fund["id"])
    assert_cents(fund_after["remaining_cents"], 50000, "fund untouched")
    assert fund_after["status"] == "ACTIVE"
    project = fixtures.read_project(api, world["project"]["id"])
    assert project["status"] == "FUNDING"
    assert_cents(project["funded_cents"], 0, "project untouched")


def test_allocate_before_the_window_returns_equity_window_closed(api):
    """The closed window is checked before the selector runs: a future fund
    cannot allocate even to an eligible project.

    PRD: "Allocating from the fund identified by `fund_id` is a `PlatformAdmin` action with no request body. The fund must be `ACTIVE` (`ERR_INVALID_STATE` otherwise) and its closed window must cover now (`ERR_EQUITY_WINDOW_CLOSED`)."
    Design: Corner/validations/allocate_before_window_returns_equity_window_closed
    """
    world = fixtures.setup_funding_project(api)  # eligible TX project exists
    fund = fixtures.create_equity_fund(
        api, name="TX Spring Fund", window_start="2027-01-01T00:00:00Z",
        window_end="2027-06-30T00:00:00Z",
    )

    res = api.allocate_equity_fund(fund["id"], {}, ADMIN_HEADERS)
    validate_error(res, ApiErrorId.ERR_EQUITY_WINDOW_CLOSED, 409)

    assert_cents(fixtures.read_equity_fund(api, fund["id"])["remaining_cents"], 50000, "untouched")


def test_match_campaign_target_mismatch_returns_target_mismatch(api):
    """A SUBJECT=SCIENCE campaign does not match a LITERACY project.

    PRD: "The campaign's target must match the project: a `SCHOOL` target requires `target_value` equal to the project's `school_id`, a `SUBJECT` target requires it equal to the project's `subject`, and a `STATE` target requires it equal to the school's `state_code`; a mismatch fails with `ERR_MATCH_TARGET_MISMATCH`."
    Design: Corner/validations/match_campaign_target_mismatch_returns_target_mismatch
    """
    world = fixtures.setup_funding_project(api)  # LITERACY project
    campaign = fixtures.create_match_campaign(
        api, sponsor_name="STEM Boosters", target_type="SUBJECT", target_value="SCIENCE"
    )
    donor = fixtures.create_donor(api)

    res = api.create_donation(
        world["project"]["id"], f.donation_payload(5000, campaign["id"]),
        make_donor_headers(donor["id"]),
    )
    validate_error(res, ApiErrorId.ERR_MATCH_TARGET_MISMATCH, 422)

    assert_cents(fixtures.read_project(api, world["project"]["id"])["funded_cents"], 0, "funded")
    assert_cents(
        fixtures.read_match_campaign(api, campaign["id"])["matched_so_far_cents"], 0, "matched"
    )


def test_donation_below_match_minimum_returns_below_match_min(api):
    """A valid 100c principal still fails a campaign whose minimum is 5000c.

    PRD: "Finally, `amount_cents` must be at least the campaign's `min_donation_cents` (which defaults to 0), otherwise `ERR_DONATION_BELOW_MATCH_MIN`."
    Design: Corner/validations/donation_below_match_minimum_returns_below_match_min
    """
    world = fixtures.setup_funding_project(api)
    campaign = fixtures.create_match_campaign(api, sponsor_name="Big Gifts Only",
                                              min_donation_cents=5000)
    donor = fixtures.create_donor(api)

    res = api.create_donation(
        world["project"]["id"], f.donation_payload(100, campaign["id"]),
        make_donor_headers(donor["id"]),
    )
    validate_error(res, ApiErrorId.ERR_DONATION_BELOW_MATCH_MIN, 422)
    assert_cents(fixtures.read_project(api, world["project"]["id"])["funded_cents"], 0, "funded")


def test_reallocate_to_an_out_of_window_fund_returns_invalid_target(api):
    """The reallocation target must be ACTIVE with a window covering now; a
    fund the sweep already CLOSED fails, and the donation stays choosable.

    PRD: "Choosing `REALLOCATE` additionally names an `equity_fund_id`, which must reference an equity fund that is `ACTIVE` and whose closed window covers now; a missing fund id, a non-`ACTIVE` fund, or an out-of-window fund all fail with `ERR_INVALID_REALLOCATION_TARGET`."
    Design: Corner/validations/reallocate_to_out_of_window_fund_returns_invalid_target
    """
    world = fixtures.setup_funding_project(api)
    donor = fixtures.create_donor(api)
    donation = fixtures.donate(api, world["project"]["id"], donor, 5000)
    fund = fixtures.create_equity_fund(
        api, name="TX Spring Fund (past)", window_start="2026-01-01T00:00:00Z",
        window_end="2026-06-01T00:00:00Z",
    )

    fixtures.set_clock(api, FUNDING_DEADLINE)
    fixtures.run_sweep(api)
    assert fixtures.read_equity_fund(api, fund["id"])["status"] == "CLOSED"

    pending = fixtures.read_donation(api, donation["id"])
    assert pending["status"] == "CHOICE_PENDING"

    res = api.reallocation_choice(
        donation["id"],
        f.reallocation_choice_payload("REALLOCATE", pending["version"], fund["id"]),
        make_donor_headers(donor["id"]),
    )
    validate_error(res, ApiErrorId.ERR_INVALID_REALLOCATION_TARGET, 422)

    after = fixtures.read_donation(api, donation["id"])
    assert after["status"] == "CHOICE_PENDING", "the choice can still be retried"
    assert_cents(fixtures.read_donor(api, donor["id"])["lifetime_reallocated_cents"], 0, "no movement")


def test_match_campaign_ended_returns_match_window_closed(api):
    """The named campaign's half-open window ended before now (and no sweep
    has run, so the row still reads ACTIVE): the temporal rule fires.

    PRD: "The campaign must be `ACTIVE` (a non-`ACTIVE` campaign fails with `ERR_INVALID_STATE`) and its half-open window must cover now — `starts_at` at or before now, and now strictly before `ends_at` — otherwise `ERR_MATCH_WINDOW_CLOSED`."
    Design: Corner/validations/match_campaign_ended_returns_match_window_closed
    """
    world = fixtures.setup_funding_project(api)  # deadline 2026-10-01
    campaign = fixtures.create_match_campaign(
        api, sponsor_name="September Sprint", ends_at="2026-09-15T00:00:00Z"
    )
    donor = fixtures.create_donor(api)

    # Inside the funding window but past the campaign window; no sweep runs.
    fixtures.set_clock(api, "2026-09-20T00:00:00Z")

    res = api.create_donation(
        world["project"]["id"], f.donation_payload(5000, campaign["id"]),
        make_donor_headers(donor["id"]),
    )
    validate_error(res, ApiErrorId.ERR_MATCH_WINDOW_CLOSED, 409)

    assert_cents(fixtures.read_project(api, world["project"]["id"])["funded_cents"], 0, "funded")
    assert_cents(
        fixtures.read_match_campaign(api, campaign["id"])["matched_so_far_cents"], 0, "matched"
    )


def test_choice_after_the_deadline_returns_choice_window_expired(api):
    """With the clock past the choice deadline and no sweep run, the donation
    still reads CHOICE_PENDING yet the donor's choice is temporally rejected.

    PRD: "The donation must still be `CHOICE_PENDING` (`ERR_INVALID_STATE` otherwise), the logical clock must be strictly before the donation's `choice_deadline` (`ERR_CHOICE_WINDOW_EXPIRED`), and the acting donor must own the donation — its `donor_id` must equal `X-User-ID` (`ERR_FORBIDDEN`)."
    Design: Corner/validations/choice_after_deadline_returns_choice_window_expired
    """
    world = fixtures.setup_expired_project(api, amounts=(5000,))
    donor = world["donor"]
    donation = world["donations"][0]
    assert donation["status"] == "CHOICE_PENDING"
    assert donation["choice_deadline"] is not None

    # Past the choice deadline, but no sweep has auto-refunded the donation.
    fixtures.set_clock(api, AFTER_CHOICE_DEADLINE)

    res = api.reallocation_choice(
        donation["id"],
        f.reallocation_choice_payload("REFUND", donation["version"]),
        make_donor_headers(donor["id"]),
    )
    validate_error(res, ApiErrorId.ERR_CHOICE_WINDOW_EXPIRED, 409)

    after = fixtures.read_donation(api, donation["id"])
    assert after["status"] == "CHOICE_PENDING", "no sweep ran to auto-refund it"
    assert_cents(fixtures.read_donor(api, donor["id"])["lifetime_refunded_cents"], 0, "no movement")


def test_second_diversion_report_with_an_open_case_is_rejected(api):
    """At most one OPEN fraud case per teacher: a second diversion report
    while the first case is open creates nothing.

    PRD: "When materials never reach the classroom, a `PlatformAdmin` reports diversion on the shipment: advancing a purchase order with `action` value `REPORT_DIVERSION` requires the order to be `SHIPPED` (`ERR_INVALID_STATE` otherwise) and requires that no `OPEN` fraud case already exist for that teacher — at most one case per teacher may be open at a time, and a duplicate report fails with `ERR_FRAUD_CASE_ALREADY_OPEN`."
    Design: Corner/validations/second_diversion_with_open_case_returns_fraud_case_already_open
    """
    world = fixtures.setup_two_vendor_funded_project(api)
    po_book, po_rug = world["po_book"], world["po_rug"]
    fixtures.ship_purchase_order(api, po_book)
    fixtures.ship_purchase_order(api, po_rug, tracking="1Z888BB20123456789")
    fixtures.report_diversion(api, po_book["id"])

    res = api.advance_purchase_order(
        po_rug["id"],
        f.po_advance_payload("REPORT_DIVERSION", reason="Second shipment also diverted"),
        ADMIN_HEADERS,
    )
    validate_error(res, ApiErrorId.ERR_FRAUD_CASE_ALREADY_OPEN, 409)

    cases = fixtures.fraud_cases_for_teacher(api, world["teacher"]["id"])
    assert len(cases) == 1
    assert cases[0]["status"] == "OPEN"
    assert fixtures.read_purchase_order(api, po_rug["id"])["status"] == "SHIPPED"


def test_donation_above_remaining_need_returns_donation_exceeds_remaining(api):
    """Donor principal may not overshoot the goal: 2000c against a 1959c
    remaining need is the fiscal violation, inside the funding window.

    PRD: "The `amount_cents` must be at least 100 cents and no more than the project's remaining need (`goal_cents` minus `funded_cents`); violating either bound fails with `ERR_DONATION_EXCEEDS_REMAINING`. Donor principal may never overshoot the goal."
    Design: Corner/validations/donation_above_remaining_need_returns_donation_exceeds_remaining
    """
    world = fixtures.setup_funding_project(api)  # goal 10959
    donor = fixtures.create_donor(api)
    fixtures.donate(api, world["project"]["id"], donor, 9000)

    res = api.create_donation(
        world["project"]["id"], f.donation_payload(2000), make_donor_headers(donor["id"])
    )
    validate_error(res, ApiErrorId.ERR_DONATION_EXCEEDS_REMAINING, 422)

    project = fixtures.read_project(api, world["project"]["id"])
    assert_cents(project["funded_cents"], 9000, "unchanged")
    assert project["status"] == "FUNDING"
