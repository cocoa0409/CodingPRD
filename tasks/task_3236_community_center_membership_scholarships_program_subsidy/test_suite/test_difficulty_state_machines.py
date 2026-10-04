"""Non-linear state machines: the scholarship review cycle and the membership's
two parallel state dimensions."""

from prd_bench_local_runner.testing import get_success_data, validate_error

from test_helpers import (
    BRANCH_DIRECTOR_HEADERS,
    assert_membership,
    make_member_headers,
)
from test_helpers import fixtures


def test_review_info_cycle_repeats_until_decision(api):
    """The UNDER_REVIEW -> MORE_INFO_REQUIRED -> UNDER_REVIEW cycle can repeat;
    decision endpoints remain reachable only from UNDER_REVIEW.

    PRD §3.4: "From `UNDER_REVIEW` the director may either push the application
    to `MORE_INFO_REQUIRED` or decide it. When more information is requested,
    only the applicant member — the acting `X-User-ID` must equal the
    application's `applicant_member_id`, else `ERR_UNAUTHORIZED` — may supply
    further `documentation` (again requiring at least one recognized kind, else
    `ERR_DOCUMENTATION_MISSING`) and optionally corrected `annual_income_cents`
    or `household_size`, cycling the application back to `UNDER_REVIEW`."
    PRD §3.4: "The `UNDER_REVIEW` → `MORE_INFO_REQUIRED` → `UNDER_REVIEW` cycle
    may repeat as often as the director and applicant need."

    Design: Difficulty/non_linear_state_machine/scholarship_review_info_cycle_repeats_until_decision
    """
    world = fixtures.setup_application_under_review(api, annual_income_cents=2_000_000)
    application = world["application"]
    member_headers = make_member_headers(world["member"]["id"])

    # First loop.
    out = get_success_data(api.request_info_application(application["id"], BRANCH_DIRECTOR_HEADERS))
    assert out["status"] == "MORE_INFO_REQUIRED"
    out = get_success_data(
        api.submit_info_application(
            application["id"], {"documentation": ["PAY_STUB", "BENEFITS_LETTER"]}, member_headers
        )
    )
    assert out["status"] == "UNDER_REVIEW"

    # Second loop: the cycle has no iteration cap.
    out = get_success_data(api.request_info_application(application["id"], BRANCH_DIRECTOR_HEADERS))
    assert out["status"] == "MORE_INFO_REQUIRED"
    out = get_success_data(
        api.submit_info_application(application["id"], {"documentation": ["TAX_RETURN"]}, member_headers)
    )
    assert out["status"] == "UNDER_REVIEW"

    # A third loop is still legal, and deny decides from UNDER_REVIEW.
    get_success_data(api.request_info_application(application["id"], BRANCH_DIRECTOR_HEADERS))
    get_success_data(
        api.submit_info_application(application["id"], {"documentation": ["TAX_RETURN"]}, member_headers)
    )
    denied = get_success_data(api.deny_application(application["id"], BRANCH_DIRECTOR_HEADERS))
    assert denied["status"] == "DENIED"


def test_deny_from_more_info_required_is_rejected(api):
    """Decisions are legal only from UNDER_REVIEW; MORE_INFO_REQUIRED is a
    waiting state, not a decidable one.

    PRD §3.4: "A `BranchDirector` moves the application `SUBMITTED` →
    `UNDER_REVIEW` (a review attempt from any other status is `ERR_INVALID_STATE`)."
    PRD §3.4: "Denial is the sibling decision: `UNDER_REVIEW` → `DENIED`, with
    no side effects, and like approval it is terminal."

    Design: Difficulty/non_linear_state_machine/scholarship_review_info_cycle_repeats_until_decision
    """
    world = fixtures.setup_application_under_review(api)
    application = world["application"]

    get_success_data(api.request_info_application(application["id"], BRANCH_DIRECTOR_HEADERS))
    validate_error(api.deny_application(application["id"], BRANCH_DIRECTOR_HEADERS), "ERR_INVALID_STATE")
    validate_error(
        api.approve_application(
            application["id"],
            {"expected_membership_version": world["membership"]["version"]},
            BRANCH_DIRECTOR_HEADERS,
        ),
        "ERR_INVALID_STATE",
    )

    current = get_success_data(api.get_application(application["id"], BRANCH_DIRECTOR_HEADERS))
    assert current["status"] == "MORE_INFO_REQUIRED"


def test_hold_and_draft_failure_move_independent_dimensions(api):
    """A hold moves only the status dimension; a failed draft moves only the
    draft dimension.

    PRD §3.3: "A membership carries two parallel state dimensions on the same
    row. The `status` dimension runs `ACTIVE`, `ON_HOLD`, `LAPSED`, and the
    terminal `CANCELLED`. The `draft_status` dimension runs `CURRENT`,
    `RETRY_PENDING`, and `DELINQUENT`. Billing failures move only the draft
    dimension; 45 consecutive days of delinquency is what moves the status
    dimension to `LAPSED`."
    PRD §3.3: "Each failure increments `attempt_count` and sets the draft's
    `status` to `FAILED`. When the count reaches 3, the membership's
    `draft_status` flips to `DELINQUENT` and `delinquent_since` records the
    current date; before that threshold the draft dimension sits in
    `RETRY_PENDING`."

    Design: Difficulty/non_linear_state_machine/membership_parallel_status_and_draft_dimensions
    """
    world = fixtures.setup_membership(api, hold_fee_cents=1_000)
    membership = world["membership"]
    member_headers = make_member_headers(world["member"]["id"])
    draft = fixtures.first_draft_of(api, membership["id"])

    # First dimension: ACTIVE -> ON_HOLD.
    held = get_success_data(api.hold_membership(membership["id"], {"hold_until": "2026-11-15"}, member_headers))
    assert held["status"] == "ON_HOLD"
    assert held["draft_status"] == "CURRENT", "the hold must not touch the draft dimension"

    # Second dimension: one failure -> RETRY_PENDING, status untouched.
    get_success_data(api.fail_draft(draft["id"], BRANCH_DIRECTOR_HEADERS))
    current = get_success_data(api.get_membership(membership["id"], BRANCH_DIRECTOR_HEADERS))
    assert current["status"] == "ON_HOLD", "the failed draft must not move the status dimension"
    assert current["draft_status"] == "RETRY_PENDING"
    assert_membership(current)


def test_draft_failures_do_not_move_status_until_delinquency(api):
    """Two failures sit in RETRY_PENDING with status still ACTIVE; only the
    third failure flips the draft dimension to DELINQUENT.

    PRD §3.3: "Recording a failed collection attempt — a `BranchDirector` or
    `AssociationAdmin` action — is legal while the draft is `PENDING` or
    `FAILED` and its `attempt_count` is below 3. Each failure increments
    `attempt_count` and sets the draft's `status` to `FAILED`. When the count
    reaches 3, the membership's `draft_status` flips to `DELINQUENT` and
    `delinquent_since` records the current date; before that threshold the draft
    dimension sits in `RETRY_PENDING`."

    Design: Difficulty/non_linear_state_machine/membership_parallel_status_and_draft_dimensions
    """
    world = fixtures.setup_membership(api)
    membership = world["membership"]
    draft = fixtures.first_draft_of(api, membership["id"])

    get_success_data(api.fail_draft(draft["id"], BRANCH_DIRECTOR_HEADERS))
    midway = get_success_data(api.get_membership(membership["id"], BRANCH_DIRECTOR_HEADERS))
    assert midway["status"] == "ACTIVE"
    assert midway["draft_status"] == "RETRY_PENDING"

    get_success_data(api.fail_draft(draft["id"], BRANCH_DIRECTOR_HEADERS))
    midway = get_success_data(api.get_membership(membership["id"], BRANCH_DIRECTOR_HEADERS))
    assert midway["status"] == "ACTIVE"
    assert midway["draft_status"] == "RETRY_PENDING"

    get_success_data(api.fail_draft(draft["id"], BRANCH_DIRECTOR_HEADERS))
    delinquent = get_success_data(api.get_membership(membership["id"], BRANCH_DIRECTOR_HEADERS))
    assert delinquent["status"] == "ACTIVE", "delinquency alone does not lapse the membership"
    assert delinquent["draft_status"] == "DELINQUENT"
    assert delinquent["delinquent_since"] is not None
