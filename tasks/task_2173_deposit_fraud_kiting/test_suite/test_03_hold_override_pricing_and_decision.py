"""Early-release reviews: pricing, the revision loop, decisions and their guards."""

from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    assert_account_balances,
    assert_hold_override_review,
    assert_same_instant,
    create_active_account,
    first_hold,
    open_case,
    open_override_review,
    read_account,
    read_check_hold,
    read_review,
    set_clock,
    setup_account_with_hold,
    setup_draft_review,
    setup_submitted_review,
    settle_item,
    submit_override_review,
    take_deposit,
    validate_error,
    validate_paginated,
    validate_success,
)

SUPERVISOR = TEST_USERS["supervisor_headers"]
SUPERVISOR_2 = TEST_USERS["supervisor_2_headers"]


# ===========================================================================
# Two-stage rounding: per line first, then the band multiplier
# ===========================================================================
def _elevated_account_with_two_seven_hundred_cent_holds():
    """TIER_3 + BRANCH + verified funding scores 35, which is the ELEVATED band.

    Two 23200-cent CHECK items each leave exactly 700 cents held.
    """
    scenario = create_active_account(
        legal_name="Imani Followell", tin_last4="6401", kyc_tier="TIER_3",
        watchlist_hit=False, product_type="CHECKING", open_channel="BRANCH",
    )
    first_item = take_deposit(scenario["account_id"], item_type="CHECK", amount_cents=23200)
    second_item = take_deposit(scenario["account_id"], item_type="CHECK", amount_cents=23200)
    return scenario, first_item, second_item


def test_loss_exposure_rounds_each_line_before_summing_then_scales_once_more(api, analyst_headers):
    """PRD §3.4: "For each hold in scope, the return-risk of that line is its
    current `held_amount_cents` multiplied by the return rate for the parent item's
    instrument and divided by 10,000, and that line figure is **rounded half up to
    whole cents immediately**. The return rates are 275 basis points for a `CHECK`,
    120 basis points for an `ACH`, and 0 basis points for `CASH`.
    `loss_exposure_cents` is then the sum of the already-rounded lines. Rounding
    once at the end over a raw sum is explicitly not the rule and gives a different
    answer whenever the discarded fractions add past half a cent."
    PRD §3.4: "`adjusted_exposure_cents` is `loss_exposure_cents` multiplied by the
    account's risk-band multiplier, divided by 10,000, and rounded half up to whole
    cents a second time. The multipliers are 10,000 basis points for a `STANDARD`
    band — that is, no adjustment — 12,500 basis points for `ELEVATED`, and 16,000
    basis points for `HIGH`."

    Design: Difficulty/combinatorial_formula/loss_exposure_rounds_each_hold_line_before_summing_then_scales
    """
    scenario, first_item, _second_item = _elevated_account_with_two_seven_hundred_cent_holds()
    hold = first_hold(first_item["id"], analyst_headers)
    assert hold["held_amount_cents"] == 700, "23200 less the 22500 immediate credit"

    review = open_override_review(
        hold["id"], hold["version"],
        requested_release_cents=700,
        release_effective_at="2026-08-01T00:00:00Z",
        release_window_end_at="2026-08-02T00:00:00Z",
        justification="Payroll customer, funds needed today",
    )
    assert_hold_override_review(review)

    # 700 * 275 / 10000 = 19.25 -> 19 per line; 19 + 19 = 38.
    assert review["loss_exposure_cents"] == 38, (
        f"Per-line rounding gives 19 + 19 = 38, got {review['loss_exposure_cents']}"
    )
    assert review["loss_exposure_cents"] != 39, (
        "39 is the value a sum-then-round implementation produces"
    )
    # 38 * 12500 / 10000 = 47.5 -> 48 under half-up rounding.
    assert review["adjusted_exposure_cents"] == 48, (
        f"The ELEVATED multiplier scales 38 to 48, got {review['adjusted_exposure_cents']}"
    )
    assert review["adjusted_exposure_cents"] != 49, (
        "49 is the value a sum-then-round implementation produces"
    )


def test_loss_exposure_scope_covers_every_active_hold_on_the_same_account(api, analyst_headers):
    """PRD §3.4: "The scope is every check hold in `ACTIVE` status that belongs to
    the **same deposit account** as the review's hold — not merely the one hold
    under review — walked in the holds' `created_at` ascending order, ties broken
    by the parent deposited item's `created_at` ascending."
    PRD §3.4: "For each hold in scope, the return-risk of that line is its current
    `held_amount_cents` multiplied by the return rate for the parent item's
    instrument and divided by 10,000, and that line figure is **rounded half up to
    whole cents immediately**."
    PRD §3.1: "The band follows from the score with an inclusive comparison at both
    edges: a score of 60 or more is `HIGH`, a score of at least 35 but below 60 is
    `ELEVATED`, and anything below 35 is `STANDARD`."

    Design: Difficulty/combinatorial_formula/loss_exposure_rounds_each_hold_line_before_summing_then_scales
    """
    scenario, _first_item, second_item = _elevated_account_with_two_seven_hundred_cent_holds()

    account = read_account(scenario["account_id"], analyst_headers)
    # TIER_3 (35) + funding VERIFIED (0) + BRANCH (0) = 35.
    assert account["risk_score"] == 35
    assert account["risk_band"] == "ELEVATED"
    assert_account_balances(account, ledger=46400, available=45000, held=1400)

    second_hold = first_hold(second_item["id"], analyst_headers)
    review = open_override_review(
        second_hold["id"], second_hold["version"],
        requested_release_cents=700,
        release_effective_at="2026-08-01T00:00:00Z",
        release_window_end_at="2026-08-02T00:00:00Z",
        justification="Second hold, same account",
    )
    assert review["loss_exposure_cents"] == 38, (
        "Both ACTIVE holds on the account are in scope, not merely the review's own hold"
    )
    assert review["adjusted_exposure_cents"] == 48


# ===========================================================================
# The revision loop SUBMITTED -> RETURNED_FOR_INFO -> SUBMITTED
# ===========================================================================
def test_returning_a_review_for_information_and_resubmitting_bumps_revision_count(api):
    """PRD §3.4: "`APPROVE` moves the review to `APPROVED`, `DENY` to `DENIED`, and
    `RETURN_FOR_INFO` back to `RETURNED_FOR_INFO`; all three stamp
    `decided_by_user_id` from `X-User-ID`, `decided_at` from the logical clock, and
    the supplied `decision_note`."
    PRD §3.4: "**Submission.** A review in `DRAFT` or in `RETURNED_FOR_INFO` is
    sent to the supervisor queue by a `FraudAnalyst` or a `FraudSupervisor`; both
    edges land in `SUBMITTED` and stamp `submitted_at` from the logical clock, and
    the edge out of `RETURNED_FOR_INFO` additionally increments `revision_count` by
    1, closing the revision loop `SUBMITTED → RETURNED_FOR_INFO → SUBMITTED`."

    Design: Difficulty/non_linear_state_machine/hold_override_review_returns_for_info_and_resubmits_in_a_loop
    """
    scenario = setup_submitted_review(
        legal_name="Halvor Brandt", tin_last4="9012", kyc_tier="TIER_2", watchlist_hit=False
    )

    returned = validate_success(
        api.decide_override_review(
            scenario["review_id"],
            {"decision": "RETURN_FOR_INFO", "decision_note": "Attach the drawer statement"},
            SUPERVISOR,
        )
    )
    assert returned["status"] == "RETURNED_FOR_INFO"
    assert returned["revision_count"] == 0, "revision_count moves on the way back out, not in"

    resubmitted = submit_override_review(scenario["review_id"])
    assert resubmitted["status"] == "SUBMITTED"
    assert resubmitted["revision_count"] == 1, (
        f"The edge out of RETURNED_FOR_INFO increments revision_count, "
        f"got {resubmitted['revision_count']}"
    )


def test_a_resubmitted_review_is_still_eligible_for_approval(api, analyst_headers):
    """PRD §3.4: "**Decision.** Only a `FraudSupervisor` records a decision, and
    only against a review in `SUBMITTED` — anything else is
    `ERR_REVIEW_NOT_SUBMITTED`."
    PRD §3.4: "`APPROVE` moves the review to `APPROVED`, `DENY` to `DENIED`, and
    `RETURN_FOR_INFO` back to `RETURNED_FOR_INFO`; all three stamp
    `decided_by_user_id` from `X-User-ID`, `decided_at` from the logical clock, and
    the supplied `decision_note`."
    PRD §3.4: "**Execution and its four-hop cascade.** A `FraudSupervisor` executes
    an approved release."

    Design: Difficulty/non_linear_state_machine/hold_override_review_returns_for_info_and_resubmits_in_a_loop
    """
    scenario = setup_submitted_review(
        legal_name="Halvor Brandt", tin_last4="9012", kyc_tier="TIER_2", watchlist_hit=False
    )
    validate_success(
        api.decide_override_review(
            scenario["review_id"],
            {"decision": "RETURN_FOR_INFO", "decision_note": "Attach the drawer statement"},
            SUPERVISOR,
        )
    )
    submit_override_review(scenario["review_id"])

    approved = validate_success(
        api.decide_override_review(
            scenario["review_id"],
            {"decision": "APPROVE", "decision_note": "Statement received"},
            SUPERVISOR,
        )
    )
    assert approved["status"] == "APPROVED"

    reread = read_review(scenario["review_id"], analyst_headers)
    assert reread["decided_by_user_id"] == "sup-1"
    assert reread["revision_count"] == 1

    hold = read_check_hold(scenario["hold_id"], analyst_headers)
    assert hold["status"] == "ACTIVE", "The revision loop never touches the hold"
    assert hold["held_amount_cents"] == 7500


# ===========================================================================
# The decision is gated by the CheckHold still being ACTIVE
# ===========================================================================
def test_decision_is_refused_once_the_underlying_hold_has_left_active(api):
    """PRD §3.4: "**Decision.** Only a `FraudSupervisor` records a decision, and
    only against a review in `SUBMITTED` — anything else is
    `ERR_REVIEW_NOT_SUBMITTED`. The underlying hold must still be `ACTIVE`."
    PRD §3.3: "A **cleared** item transitions `PENDING → CLEARED`. Every hold on
    that item still in `ACTIVE` transitions `ACTIVE → RELEASED` with `released_at`
    stamped."
    PRD §5: "`ERR_HOLD_NOT_ACTIVE` | 409"

    Design: Difficulty/cross_entity_state_dependency/override_decision_gated_by_check_hold_remaining_active
    """
    scenario = setup_submitted_review(
        legal_name="Gideon Marsh", tin_last4="4949", kyc_tier="TIER_2", watchlist_hit=False
    )
    settle_item(scenario["item_id"], "CLEARED")

    response = api.decide_override_review(
        scenario["review_id"],
        {"decision": "APPROVE", "decision_note": "Attempted approval after settlement"},
        SUPERVISOR,
    )
    validate_error(response, ApiErrorId.ERR_HOLD_NOT_ACTIVE.value)


def test_the_refused_decision_leaves_review_hold_and_balances_untouched(api, analyst_headers):
    """PRD §3.4: "**Decision.** Only a `FraudSupervisor` records a decision, and
    only against a review in `SUBMITTED` — anything else is
    `ERR_REVIEW_NOT_SUBMITTED`. The underlying hold must still be `ACTIVE`."
    PRD §3.4: "The server records `prepared_by_user_id` from `X-User-ID`, sets
    `status` to `DRAFT`, leaves `decided_by_user_id`, `decision_note`,
    `submitted_at`, `decided_at`, and `executed_at` null, sets `revision_count` to
    0, and stores the hold's identity as `check_hold_id`."
    PRD §3.3: "Because those holds left `ACTIVE`, the depositing account's
    `available_balance_cents` rises by the total `held_amount_cents` just released
    and its `held_amount_cents` is recomputed; `ledger_balance_cents` is unchanged,
    because the money was already on the ledger."

    Design: Difficulty/cross_entity_state_dependency/override_decision_gated_by_check_hold_remaining_active
    """
    scenario = setup_submitted_review(
        legal_name="Gideon Marsh", tin_last4="4949", kyc_tier="TIER_2", watchlist_hit=False
    )
    settle_item(scenario["item_id"], "CLEARED")
    validate_error(
        api.decide_override_review(
            scenario["review_id"],
            {"decision": "APPROVE", "decision_note": "Attempted approval after settlement"},
            SUPERVISOR,
        ),
        ApiErrorId.ERR_HOLD_NOT_ACTIVE.value,
    )

    review = read_review(scenario["review_id"], analyst_headers)
    assert review["status"] == "SUBMITTED", "The refused decision must not have moved the review"
    assert review["decided_by_user_id"] is None

    hold = read_check_hold(scenario["hold_id"], analyst_headers)
    assert hold["status"] == "RELEASED"

    account = read_account(scenario["account_id"], analyst_headers)
    assert_account_balances(account, ledger=30000, available=30000, held=0)


# ===========================================================================
# Half-open release windows claimed on one account
# ===========================================================================
def _account_with_two_independent_holds():
    scenario = create_active_account(
        legal_name="Priya Vanterpool", tin_last4="7474", kyc_tier="TIER_2", watchlist_hit=False
    )
    first_item = take_deposit(scenario["account_id"], item_type="CHECK", amount_cents=30000)
    second_item = take_deposit(scenario["account_id"], item_type="CHECK", amount_cents=30000)
    return scenario, first_item, second_item


def test_a_straddling_release_window_on_the_same_account_is_rejected(api, analyst_headers):
    """PRD §3.4: "The claimed window must not overlap the window of any other
    review on the **same deposit account** whose status is `DRAFT`, `SUBMITTED`,
    `RETURNED_FOR_INFO`, `APPROVED`, or `EXECUTED`; an overlap is
    `ERR_RELEASE_WINDOW_OVERLAP` (HTTP 409)."
    PRD §3.4: "The creation payload names `requested_release_cents`, an integer of
    at least 1; a half-open release window bounded by `release_effective_at`
    inclusive and `release_window_end_at` exclusive, where the end must be strictly
    after the start; a `justification` of 1 to 500 non-blank characters recorded
    for audit; and the `expected_check_hold_version` demanded by §2.7."

    Design: Difficulty/resource_temporal_overlap/early_release_windows_on_one_account_use_half_open_intervals_with_adjacency_allowed
    """
    _scenario, first_item, second_item = _account_with_two_independent_holds()
    hold_a = first_hold(first_item["id"], analyst_headers)
    hold_b = first_hold(second_item["id"], analyst_headers)

    open_override_review(
        hold_a["id"], hold_a["version"],
        requested_release_cents=7500,
        release_effective_at="2026-08-01T00:00:00Z",
        release_window_end_at="2026-08-03T00:00:00Z",
        justification="First early-release window",
    )

    response = api.create_override_review(
        hold_b["id"],
        {
            "requested_release_cents": 7500,
            "release_effective_at": "2026-08-02T00:00:00Z",
            "release_window_end_at": "2026-08-04T00:00:00Z",
            "justification": "Straddling window",
            "expected_check_hold_version": hold_b["version"],
        },
        analyst_headers,
    )
    validate_error(response, ApiErrorId.ERR_RELEASE_WINDOW_OVERLAP.value)

    _rows, meta = validate_paginated(
        api.list_hold_override_reviews(hold_b["id"], analyst_headers)
    )
    assert meta["total_count"] == 0, "The rejected window must not have created a review"


def test_a_release_window_starting_exactly_where_another_ends_is_accepted(api, analyst_headers):
    """PRD §3.4: "Because the windows are half-open, touching endpoints do not
    overlap: an existing window ending at an instant and a new window starting at
    exactly that instant are both accepted."
    PRD §3.4: "The claimed window must not overlap the window of any other review
    on the **same deposit account** whose status is `DRAFT`, `SUBMITTED`,
    `RETURNED_FOR_INFO`, `APPROVED`, or `EXECUTED`; an overlap is
    `ERR_RELEASE_WINDOW_OVERLAP` (HTTP 409)."

    Design: Difficulty/resource_temporal_overlap/early_release_windows_on_one_account_use_half_open_intervals_with_adjacency_allowed
    """
    _scenario, first_item, second_item = _account_with_two_independent_holds()
    hold_a = first_hold(first_item["id"], analyst_headers)
    hold_b = first_hold(second_item["id"], analyst_headers)

    first_review = open_override_review(
        hold_a["id"], hold_a["version"],
        requested_release_cents=7500,
        release_effective_at="2026-08-01T00:00:00Z",
        release_window_end_at="2026-08-03T00:00:00Z",
        justification="First early-release window",
    )

    validate_error(
        api.create_override_review(
            hold_b["id"],
            {
                "requested_release_cents": 7500,
                "release_effective_at": "2026-08-02T00:00:00Z",
                "release_window_end_at": "2026-08-04T00:00:00Z",
                "justification": "Straddling window",
                "expected_check_hold_version": hold_b["version"],
            },
            analyst_headers,
        ),
        ApiErrorId.ERR_RELEASE_WINDOW_OVERLAP.value,
    )

    adjacent = validate_success(
        api.create_override_review(
            hold_b["id"],
            {
                "requested_release_cents": 7500,
                "release_effective_at": "2026-08-03T00:00:00Z",
                "release_window_end_at": "2026-08-05T00:00:00Z",
                "justification": "Adjacent window starting exactly where the first ends",
                "expected_check_hold_version": hold_b["version"],
            },
            analyst_headers,
        ),
        201,
    )
    assert adjacent["status"] == "DRAFT"

    rows_a, meta_a = validate_paginated(
        api.list_hold_override_reviews(hold_a["id"], analyst_headers)
    )
    assert meta_a["total_count"] == 1
    assert rows_a[0]["id"] == first_review["id"]
    assert rows_a[0]["status"] == "DRAFT", (
        "A review on a different hold never supersedes this one"
    )

    _rows_b, meta_b = validate_paginated(
        api.list_hold_override_reviews(hold_b["id"], analyst_headers)
    )
    assert meta_b["total_count"] == 1


# ===========================================================================
# Creation guards
# ===========================================================================
def test_requesting_more_than_the_hold_holds_is_rejected_at_exactly_one_cent_over(
    api, analyst_headers
):
    """PRD §3.4: "Finally, `requested_release_cents` must be less than or equal to
    the hold's current `held_amount_cents`, else `ERR_RELEASE_EXCEEDS_HOLD`
    (HTTP 422)."

    Design: Corner/validations/override_review_requesting_more_than_the_hold_is_rejected
    """
    scenario = setup_account_with_hold(
        legal_name="Release Cap Depositor", tin_last4="0028"
    )

    validate_error(
        api.create_override_review(
            scenario["hold_id"],
            {
                "requested_release_cents": 7501,
                "release_effective_at": "2026-08-01T00:00:00Z",
                "release_window_end_at": "2026-08-02T00:00:00Z",
                "justification": "Over-request",
                "expected_check_hold_version": scenario["hold_version"],
            },
            analyst_headers,
        ),
        ApiErrorId.ERR_RELEASE_EXCEEDS_HOLD.value,
    )

    accepted = validate_success(
        api.create_override_review(
            scenario["hold_id"],
            {
                "requested_release_cents": 7500,
                "release_effective_at": "2026-08-01T00:00:00Z",
                "release_window_end_at": "2026-08-02T00:00:00Z",
                "justification": "Exact-amount request",
                "expected_check_hold_version": scenario["hold_version"],
            },
            analyst_headers,
        ),
        201,
    )
    assert accepted["requested_release_cents"] == 7500, (
        "The comparison is less-than-or-equal, so the exact hold amount is allowed"
    )
    assert accepted["status"] == "DRAFT"

    _rows, meta = validate_paginated(
        api.list_hold_override_reviews(scenario["hold_id"], analyst_headers)
    )
    assert meta["total_count"] == 1, "The rejected over-request created nothing"


def test_a_matured_hold_no_longer_admits_an_early_release_review(api, analyst_headers):
    """PRD §3.4: "The logical clock must be strictly before the hold's
    `hold_release_at`, because a matured hold no longer admits an override; a
    request at or past that instant is refused with `ERR_HOLD_ALREADY_MATURED`
    (HTTP 422)."
    PRD §3.3: "Reaching `hold_release_at` does not transition the hold by itself;
    maturity only closes the window in which an early release may be requested."

    Design: Corner/validations/matured_hold_cannot_receive_a_new_override_review
    """
    scenario = setup_account_with_hold(legal_name="Matured Hold Depositor", tin_last4="0029")
    assert_same_instant(
        scenario["hold"]["hold_release_at"], "2026-08-10T00:00:00Z", "hold_release_at"
    )

    set_clock("2026-08-10T00:00:00Z")

    validate_error(
        api.create_override_review(
            scenario["hold_id"],
            {
                "requested_release_cents": 7500,
                "release_effective_at": "2026-08-10T00:00:00Z",
                "release_window_end_at": "2026-08-11T00:00:00Z",
                "justification": "Too late to matter",
                "expected_check_hold_version": scenario["hold_version"],
            },
            analyst_headers,
        ),
        ApiErrorId.ERR_HOLD_ALREADY_MATURED.value,
    )

    hold = read_check_hold(scenario["hold_id"], analyst_headers)
    assert hold["status"] == "ACTIVE", "Maturity alone never transitions the hold"
    assert hold["held_amount_cents"] == 7500
    assert hold["version"] == scenario["hold_version"], (
        "A rejected creation must not advance the hold's version"
    )


def test_stale_check_hold_version_on_review_creation_is_refused(api, analyst_headers):
    """PRD §2.7: "Opening an early-release review against a check hold requires a
    non-optional `expected_check_hold_version` field in the request body, carrying
    the client's last observed `version` of that `CheckHold`. If it does not equal
    the hold's current `version`, the request is rejected with
    `ERR_STALE_CHECK_HOLD_VERSION` (HTTP 412) and nothing is created."
    PRD §2.7: "On success the hold's own `version` advances by 1."
    PRD §3.4: "On success, every *other* review against the same hold whose status
    is `DRAFT`, `SUBMITTED`, `RETURNED_FOR_INFO`, or `APPROVED` is moved to
    `SUPERSEDED` — including one already approved but not yet executed, which can
    consequently never be executed — while their `decided_by_user_id` and
    `decision_note` are left exactly as they were."

    Design: Corner/cross_cutting_complexity_layers/stale_check_hold_version_on_override_review_creation_is_refused
    """
    scenario = setup_account_with_hold(legal_name="Occ Hold Depositor", tin_last4="0043")
    assert scenario["hold_version"] == 1, "A freshly minted hold is at version 1"

    first = open_override_review(
        scenario["hold_id"], scenario["hold_version"],
        requested_release_cents=7500,
        release_effective_at="2026-08-01T00:00:00Z",
        release_window_end_at="2026-08-02T00:00:00Z",
        justification="First review",
    )

    validate_error(
        api.create_override_review(
            scenario["hold_id"],
            {
                "requested_release_cents": 7500,
                "release_effective_at": "2026-08-01T00:00:00Z",
                "release_window_end_at": "2026-08-02T00:00:00Z",
                "justification": "Replay with a stale hold version",
                "expected_check_hold_version": scenario["hold_version"],
            },
            analyst_headers,
        ),
        ApiErrorId.ERR_STALE_CHECK_HOLD_VERSION.value,
    )

    refreshed = read_check_hold(scenario["hold_id"], analyst_headers)
    assert refreshed["version"] == 2, "The first successful creation advanced the hold's version"

    second = open_override_review(
        scenario["hold_id"], refreshed["version"],
        requested_release_cents=7500,
        release_effective_at="2026-08-03T00:00:00Z",
        release_window_end_at="2026-08-04T00:00:00Z",
        justification="Revised review on a fresh hold version",
    )

    assert read_review(first["id"], analyst_headers)["status"] == "SUPERSEDED"
    assert read_review(second["id"], analyst_headers)["status"] == "DRAFT"

    _rows, meta = validate_paginated(
        api.list_hold_override_reviews(scenario["hold_id"], analyst_headers)
    )
    assert meta["total_count"] == 2


# ===========================================================================
# Duty separation and premature state transitions
# ===========================================================================
def test_a_supervisor_may_not_decide_the_review_they_prepared(api, analyst_headers):
    """PRD §2.1: "The operator who records a decision on an early-release review
    may not be the operator whose `X-User-ID` was captured as that review's
    `prepared_by_user_id`, and the counsel who signs a subpoena response may not be
    the counsel whose `X-User-ID` was captured as that subpoena's
    `legal_reviewed_by_user_id`. A violation of either is
    `ERR_SEGREGATION_OF_DUTIES` (HTTP 403)."
    PRD §3.4: "The deciding supervisor's `X-User-ID` must differ from the review's
    `prepared_by_user_id`, else `ERR_SEGREGATION_OF_DUTIES`; this is the rule that
    bites inside a single role, because a supervisor is perfectly entitled to
    prepare a review and simply may not then decide their own."

    Design: Corner/rbac/supervisor_cannot_decide_a_review_they_prepared_themselves
    """
    scenario = setup_account_with_hold(
        legal_name="Duty Separation Depositor", tin_last4="0041"
    )

    review = open_override_review(
        scenario["hold_id"], scenario["hold_version"], headers=SUPERVISOR,
        requested_release_cents=7500,
        justification="Prepared by the supervisor personally",
    )
    assert review["prepared_by_user_id"] == "sup-1"
    submit_override_review(review["id"], SUPERVISOR)

    validate_error(
        api.decide_override_review(
            review["id"], {"decision": "APPROVE", "decision_note": "Self approval attempt"},
            SUPERVISOR,
        ),
        ApiErrorId.ERR_SEGREGATION_OF_DUTIES.value,
    )

    approved = validate_success(
        api.decide_override_review(
            review["id"], {"decision": "APPROVE", "decision_note": "Independent approval"},
            SUPERVISOR_2,
        )
    )
    assert approved["status"] == "APPROVED"
    assert approved["decided_by_user_id"] == "sup-2"


def test_deciding_a_draft_review_and_drafting_a_referral_too_early_are_both_refused(
    api, analyst_headers
):
    """PRD §3.4: "**Decision.** Only a `FraudSupervisor` records a decision, and
    only against a review in `SUBMITTED` — anything else is
    `ERR_REVIEW_NOT_SUBMITTED`."
    PRD §3.7: "A `FraudAnalyst` drafts the referral against a case whose `status`
    is `SUBSTANTIATED` — against any other status the draft is refused with
    `ERR_CASE_NOT_SUBSTANTIATED` (HTTP 409) — supplying a `narrative` of 1 to 2,000
    non-blank characters and a `suspected_activity_code` of `KITING`,
    `MULE_ACTIVITY`, `STRUCTURING`, or `ACCOUNT_TAKEOVER`."

    Design: Corner/validations/deciding_a_draft_review_and_drafting_a_referral_too_early_are_rejected
    """
    scenario = setup_draft_review(legal_name="Early Action Depositor", tin_last4="0033")
    case = open_case(scenario["account_id"], "MULE")

    validate_error(
        api.decide_override_review(
            scenario["review_id"],
            {"decision": "APPROVE", "decision_note": "Premature decision"},
            SUPERVISOR,
        ),
        ApiErrorId.ERR_REVIEW_NOT_SUBMITTED.value,
    )

    validate_error(
        api.create_bsa_referral(
            case["id"],
            {"narrative": "Premature referral.", "suspected_activity_code": "STRUCTURING"},
            analyst_headers,
        ),
        ApiErrorId.ERR_CASE_NOT_SUBSTANTIATED.value,
    )

    assert read_review(scenario["review_id"], analyst_headers)["status"] == "DRAFT"

    _rows, meta = validate_paginated(api.list_case_bsa_referrals(case["id"], analyst_headers))
    assert meta["total_count"] == 0
