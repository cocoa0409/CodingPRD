"""Corner probes against the calculation rules: tier ceilings, proration, the
hold-fee base, and pool reconciliation across an award's life."""

from prd_bench_local_runner.testing import get_success_data, validate_error, validate_paginated

from test_helpers import (
    BRANCH_DIRECTOR_HEADERS,
    assert_branch_pool_invariants,
    assert_cents,
    assert_fraction,
    assert_ratio,
    make_member_headers,
)
from test_helpers import fixtures


def test_ratio_exactly_point_eight_is_ineligible(api):
    """A ratio rounding to exactly 0.8000 is at the ceiling: not below it.

    PRD §3.4: "the final `income_ratio` is recomputed from the verified inputs
    and must yield an `award_pct` among 0.25, 0.50, or 0.75 — a ratio at or
    above the 0.80 ceiling is ineligible and the application must be denied
    instead; approving it anyway is `ERR_AWARD_INELIGIBLE`."
    PRD §3.4: "a ratio of exactly 0.80 or above is ineligible."

    Design: Corner/calculations/sliding_scale_boundary_zero_point_eight_is_ineligible
    """
    world = fixtures.setup_application_under_review(api, household_size=1, annual_income_cents=4_000_000)
    application = world["application"]
    assert_ratio(application["income_ratio"], 0.8000, "application.income_ratio")

    response = api.approve_application(
        application["id"],
        {"expected_membership_version": world["membership"]["version"]},
        BRANCH_DIRECTOR_HEADERS,
    )
    validate_error(response, "ERR_AWARD_INELIGIBLE")

    membership = get_success_data(api.get_membership(world["membership"]["id"], BRANCH_DIRECTOR_HEADERS))
    assert membership["assistance_pct"] == 0
    current = get_success_data(api.get_application(application["id"], BRANCH_DIRECTOR_HEADERS))
    assert current["status"] == "UNDER_REVIEW"


def test_activation_month_draft_is_prorated_and_later_months_are_full(api):
    """The first REGULAR draft prorates from the activation day; the next month
    bills the full assisted dues and the anniversary day is the activation day.

    PRD §3.2: "That first regular draft is prorated — its `amount_cents` is the
    full assisted monthly amount multiplied by the number of remaining days in
    the activation month counted inclusively from the activation day, divided by
    the total days in the activation month, rounded half-up to integer cents."
    PRD §3.2: "A new membership is born with `status` `ACTIVE`, `draft_status`
    `CURRENT`, `version` 1, and an `anniversary_day` equal to the day-of-month
    of the activation date capped at 28"
    PRD §3.3: "when the membership is `ON_HOLD` the base is the category's
    `hold_fee_cents` and the draft `kind` is `HOLD_FEE`; otherwise the base is
    the category's `monthly_dues_cents` and the `kind` is `REGULAR`."

    Design: Corner/calculations/monthly_draft_proration_mid_month_activation
    """
    fixtures.set_clock(api, "2026-09-16T00:00:00Z")
    assoc = fixtures.create_association(api)
    branch = fixtures.create_branch(api, assoc["id"])
    category = fixtures.create_category(api, branch["id"], monthly_dues_cents=8_000)
    member = fixtures.create_member(api, branch["id"])

    membership = get_success_data(
        api.create_membership(
            {
                "branch_id": branch["id"],
                "category_id": category["id"],
                "primary_member_id": member["id"],
                "member_ids": [member["id"]],
            },
            make_member_headers(member["id"]),
        )
    )
    assert membership["anniversary_day"] == 16

    drafts, _meta = validate_paginated(
        api.list_membership_drafts(membership["id"], BRANCH_DIRECTOR_HEADERS)
    )
    activation_draft = [d for d in drafts if d["kind"] == "REGULAR"][0]
    assert activation_draft["period_month"] == "2026-09"
    # round_half_up(8000 * 15 / 30) = 4000: the 16th through the 30th inclusive.
    assert_cents(activation_draft["amount_cents"], 4_000, "activation draft amount")

    fixtures.set_clock(api, "2026-10-16T00:00:00Z")
    october = get_success_data(api.create_draft_for_membership(membership["id"], BRANCH_DIRECTOR_HEADERS))
    assert october["period_month"] == "2026-10"
    assert october["kind"] == "REGULAR"
    assert_cents(october["amount_cents"], 8_000, "october draft amount")


def test_hold_fee_base_applies_before_assistance(api):
    """During a hold the draft base switches to the hold fee and assistance
    applies to that base, not to dues.

    PRD §3.3: "The draft's `amount_cents` is computed by first selecting the
    base: when the membership is `ON_HOLD` the base is the category's
    `hold_fee_cents` and the draft `kind` is `HOLD_FEE`; otherwise the base is
    the category's `monthly_dues_cents` and the `kind` is `REGULAR`. The amount
    is then that base multiplied by one minus the membership's `assistance_pct`,
    rounded half-up to integer cents. This base-first, assistance-second
    ordering is deliberate: assistance discounts dues, but hold status changes
    what the dues are."

    Design: Corner/calculations/hold_fee_replaces_dues_during_hold_and_assistance_applies
    """
    world = fixtures.setup_approved_award(
        api, pool_cents=200_000, annual_income_cents=2_000_000, hold_fee_cents=1_000
    )
    membership = get_success_data(api.get_membership(world["membership"]["id"], BRANCH_DIRECTOR_HEADERS))
    assert_fraction(membership["assistance_pct"], 0.50, "membership.assistance_pct")

    get_success_data(
        api.hold_membership(
            membership["id"], {"hold_until": "2026-11-15"}, make_member_headers(world["member"]["id"])
        )
    )

    fixtures.set_clock(api, "2026-10-01T00:00:00Z")
    hold_draft = get_success_data(api.create_draft_for_membership(membership["id"], BRANCH_DIRECTOR_HEADERS))
    assert hold_draft["kind"] == "HOLD_FEE"
    # round_half_up(1000 * (1 - 0.50)) = 500.
    assert_cents(hold_draft["amount_cents"], 500, "hold draft amount")


def test_pool_reconciles_across_obligation_and_expiry(api):
    """Approval obligates; the clock reaching award_end_on expires and releases;
    the forward counter equals the replayed ledger at every step.

    PRD §2.8: "The stored counters are recomputed eagerly on every triggering
    mutation — donation receipt or refund, award approval, award expiry, or the
    cancellation or lapse of an awarded membership — and an audit read that
    replays donation and application state events in `created_at` ascending
    order must arrive at exactly the same value; the compensating refund
    transition is what keeps both consistent."
    PRD §3.4: "A successful approval writes `award_pct`, computes
    `award_obligation_cents` as that annualized amount, sets `award_start_on` to
    the current date and `award_end_on` to `award_start_on` plus 365 days (the
    annual renewal boundary)"
    PRD §3.4: "When the clock reaches `award_end_on`, or when the underlying
    membership is cancelled or lapses, an approved application moves to
    `EXPIRED`. Expiry releases the obligation: the branch's
    `scholarship_pool_obligated_cents` decreases by `award_obligation_cents`,
    raising the available pool accordingly."

    Design: Corner/calculations/pool_available_matches_forward_and_replay_variants
    """
    world = fixtures.setup_approved_award(api, pool_cents=200_000, annual_income_cents=2_000_000)
    application = world["application"]
    assert_fraction(application["award_pct"], 0.50, "application.award_pct")
    assert_cents(application["award_obligation_cents"], 48_000, "application.award_obligation_cents")

    after_approve = get_success_data(api.get_branch(world["branch"]["id"], BRANCH_DIRECTOR_HEADERS))
    assert_cents(after_approve["scholarship_pool_available_cents"], 152_000, "pool available after approve")
    assert_branch_pool_invariants(after_approve)

    # Past the annual renewal boundary the award expires and releases.
    fixtures.set_clock(api, "2027-09-02T00:00:00Z")
    expired = get_success_data(api.get_application(application["id"], BRANCH_DIRECTOR_HEADERS))
    assert expired["status"] == "EXPIRED"

    after_expiry = get_success_data(api.get_branch(world["branch"]["id"], BRANCH_DIRECTOR_HEADERS))
    assert_cents(after_expiry["scholarship_pool_available_cents"], 200_000, "pool available after expiry")
    assert_branch_pool_invariants(after_expiry)

    membership = get_success_data(api.get_membership(world["membership"]["id"], BRANCH_DIRECTOR_HEADERS))
    assert membership["assistance_pct"] == 0
