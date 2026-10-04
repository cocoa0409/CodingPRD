"""Non-linear state machines: the project's draft-review revision cycle and
the donation's two divergent exits from CHOICE_PENDING."""

from test_helpers import (
    assert_instant,
    assert_cents,
    fixtures,
    validate_success,
)
from test_helpers.constants import BASE_CLOCK, CHOICE_DEADLINE, FUNDING_DEADLINE


# ── Project revision cycle ─────────────────────────────────────────────────


def test_screen_return_lets_the_teacher_resubmit(api):
    """IN_REVIEW -> RETURNED -> IN_REVIEW: the screen-return half of the loop.

    PRD: "Screening — `stage` value `SCREEN` — applies to a project in `IN_REVIEW`: `APPROVE` advances it to `VETTING` and records the acting reviewer's `X-User-ID` as the project's `screened_by_id`; `RETURN` sends it back to `RETURNED`, where the teacher may edit items and resubmit."
    PRD: "A resubmission from `RETURNED` re-pins prices and re-checks the goal identically, and additionally clears `screened_by_id` and `vetted_by_id` so the next review round starts clean."
    Design: Difficulty/non_linear_state_machine/project_revision_cycle_returns_to_review
    """
    world = fixtures.setup_draft_project(api)
    project_id = world["project"]["id"]

    submitted = fixtures.submit_project(api, project_id, world["teacher"])
    assert submitted["status"] == "IN_REVIEW"

    returned = fixtures.review_project(api, project_id, "SCREEN", "RETURN", "rev-ana")
    assert returned["status"] == "RETURNED"

    # The revision loop: the teacher edits (adds are legal again) and resubmits.
    resubmitted = fixtures.submit_project(api, project_id, world["teacher"])
    assert resubmitted["status"] == "IN_REVIEW"
    assert resubmitted["goal_cents"] == 10959, "resubmit re-checks the same computed goal"


def test_full_revision_cycle_terminates_in_funding(api):
    """The loop runs through a vet return as well before both stages approve.

    PRD: "Vetting applies to a project in `VETTING` and admits three outcomes: `APPROVE` moves the project to `FUNDING`, records the acting reviewer as `vetted_by_id`, stamps `funding_started_at` with the current logical-clock time, and computes `funding_deadline` as that instant plus the project's `funding_window_days`; `RETURN` sends the project back to `RETURNED`; and `REJECT` terminates it as `REJECTED`."
    Design: Difficulty/non_linear_state_machine/project_revision_cycle_returns_to_review
    """
    world = fixtures.setup_draft_project(api)
    project_id = world["project"]["id"]

    # First pass: screen returns the project.
    fixtures.submit_project(api, project_id, world["teacher"])
    returned = fixtures.review_project(api, project_id, "SCREEN", "RETURN", "rev-ana")
    assert returned["status"] == "RETURNED"

    # Second pass: screen approves, vetting returns it.
    fixtures.submit_project(api, project_id, world["teacher"])
    vetting = fixtures.review_project(api, project_id, "SCREEN", "APPROVE", "rev-ana")
    assert vetting["status"] == "VETTING"
    assert vetting["screened_by_id"] == "rev-ana"
    returned_again = fixtures.review_project(api, project_id, "VET", "RETURN", "rev-ben")
    assert returned_again["status"] == "RETURNED"

    # Resubmission clears the reviewer attribution so the next round starts clean.
    resubmitted = fixtures.submit_project(api, project_id, world["teacher"])
    assert resubmitted["status"] == "IN_REVIEW"
    assert resubmitted["screened_by_id"] is None, "resubmit clears screened_by_id"
    assert resubmitted["vetted_by_id"] is None, "resubmit clears vetted_by_id"

    # Third pass: both stages approve in order; the funding window is stamped.
    fixtures.review_project(api, project_id, "SCREEN", "APPROVE", "rev-ana")
    final = fixtures.review_project(api, project_id, "VET", "APPROVE", "rev-ben")

    assert final["status"] == "FUNDING"
    assert final["screened_by_id"] == "rev-ana", "re-recorded on the final pass"
    assert final["vetted_by_id"] == "rev-ben"
    assert_instant(final["funding_started_at"], BASE_CLOCK, "funding_started_at")
    assert_instant(final["funding_deadline"], FUNDING_DEADLINE, "funding_deadline")


# ── Donation choice fork ───────────────────────────────────────────────────


def test_refund_branch_credits_only_the_refund_bucket(api):
    """CHOICE_PENDING -> REFUNDED via the donor's REFUND choice.

    PRD: "Choosing `REFUND` moves the donation to `REFUNDED` with `refund_reason` set to `EXPIRED_CHOICE`; the project's `funded_cents` decreases by `amount_cents` (and nothing more — the match left at expiry), and the donor's `lifetime_refunded_cents` increases by `amount_cents`."
    Design: Difficulty/non_linear_state_machine/donation_choice_fork_divergent_side_effects
    """
    world = fixtures.setup_expired_project(api, amounts=(4000, 4000))
    donor = world["donor"]
    dn1, dn2 = world["donations"]
    assert dn1["status"] == "CHOICE_PENDING"
    assert_instant(dn1["choice_deadline"], CHOICE_DEADLINE, "choice_deadline")

    refunded = validate_success(fixtures.donor_choice(api, dn1, donor, "REFUND"), 200)
    assert refunded["status"] == "REFUNDED"
    assert refunded["refund_reason"] == "EXPIRED_CHOICE"

    donor_after = fixtures.read_donor(api, donor["id"])
    assert_cents(donor_after["lifetime_refunded_cents"], 4000, "lifetime_refunded_cents")
    assert_cents(donor_after["lifetime_reallocated_cents"], 0, "lifetime_reallocated_cents")
    assert_cents(donor_after["lifetime_donated_cents"], 8000, "lifetime_donated_cents")

    project_after = fixtures.read_project(api, world["project"]["id"])
    assert_cents(project_after["funded_cents"], 4000, "funded_cents")  # dn2 still pending
    assert fixtures.read_donation(api, dn2["id"])["status"] == "CHOICE_PENDING"


def test_reallocate_branch_credits_the_fund_and_the_reallocated_bucket(api):
    """CHOICE_PENDING -> REALLOCATED via the donor's REALLOCATE choice.

    PRD: "Choosing `REALLOCATE` additionally names an `equity_fund_id`, which must reference an equity fund that is `ACTIVE` and whose closed window covers now"
    PRD: "On success the donation moves to `REALLOCATED` with its `equity_fund_id` set to the receiving fund, the fund's `remaining_cents` increases by `amount_cents` (and a `DEPLETED` fund flips back to `ACTIVE` if its window still covers now), the donor's `lifetime_reallocated_cents` increases by `amount_cents`, and the project's `funded_cents` decreases by `amount_cents`."
    Design: Difficulty/non_linear_state_machine/donation_choice_fork_divergent_side_effects
    """
    world = fixtures.setup_expired_project(api, amounts=(4000, 4000), with_equity_fund=True)
    donor = world["donor"]
    fund = world["equity_fund"]
    dn1, dn2 = world["donations"]

    reallocated = validate_success(
        fixtures.donor_choice(api, dn2, donor, "REALLOCATE", equity_fund_id=fund["id"]), 200
    )
    assert reallocated["status"] == "REALLOCATED"
    assert reallocated["equity_fund_id"] == fund["id"]

    fund_after = fixtures.read_equity_fund(api, fund["id"])
    assert_cents(fund_after["remaining_cents"], 50000 + 4000, "fund remaining_cents")
    assert fund_after["status"] == "ACTIVE"

    donor_after = fixtures.read_donor(api, donor["id"])
    assert_cents(donor_after["lifetime_reallocated_cents"], 4000, "lifetime_reallocated_cents")
    assert_cents(donor_after["lifetime_refunded_cents"], 0, "lifetime_refunded_cents")

    project_after = fixtures.read_project(api, world["project"]["id"])
    assert_cents(project_after["funded_cents"], 4000, "funded_cents")  # dn1 still pending
    assert fixtures.read_donation(api, dn1["id"])["status"] == "CHOICE_PENDING"
