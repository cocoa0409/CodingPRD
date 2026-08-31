"""Quality review, the retake items it raises, and the four-link regression
cascade that a failing round fires."""

import pytest

from test_helpers import (
    CASTING,
    MIXER,
    PC,
    REVIEWER_1,
    REVIEWER_2,
    REVIEWER_9,
    ApiErrorId,
    assert_order_money_conserved,
    assert_quality_review,
    assert_retake_item,
    book_session,
    create_mix_job_payload,
    defect_entry,
    fail_review_round,
    first_retake_item_id,
    make_native_reviewer_headers,
    open_quality_review,
    run_session_to_completed,
    setup_after_qc_failure,
    setup_canon,
    setup_open_retake_with_order_back_in_qc,
    setup_order_in_qc,
    start_review_round,
    validate_error,
    validate_paginated,
    validate_success,
)

QC_REVIEWER = make_native_reviewer_headers(REVIEWER_2)
SCRIPT_REVIEWER = make_native_reviewer_headers(REVIEWER_1)


# --------------------------------------------------------------------------
# The four-link regression cascade
# --------------------------------------------------------------------------
def test_a_failing_round_regresses_the_review_the_mix_and_the_order(api):
    """PRD §3.9: "A surviving fail stores `defect_count`, stamps `pass_rate`, sets
    `decision` to `FAIL` and the review to `FAILED_RETAKE`, increments the review's
    `version` by 1, and then fires a four-link regression cascade that must run in
    order and in full."
    PRD §3.9: "**Link 2** regresses the order's newest mix job
    `CONFORMED → STEM_CHECKED`, incrementing its `mix_round` by 1 and clearing its
    `conformance_index` to null."
    PRD §3.9: "**Link 3** regresses the owning order `QC → RECORDING`, increments the
    order's `retake_cycles` by 1, and increments the order's `version` by 1."

    Design: Difficulty/transitive_cascade/qc_failure_four_link_regression_chain
    """
    ctx = setup_canon(43)
    review = validate_success(
        api.decide_quality_review(
            ctx["qr_id"],
            {"decision": "FAIL", "defect_count": 30,
             "defects": [defect_entry(ctx["ca1_id"], "L-0042", "LIPSYNC")]},
            QC_REVIEWER,
        )
    )
    assert_quality_review(review)
    assert review["status"] == "FAILED_RETAKE"
    assert review["pass_rate"] == pytest.approx(0.8500, abs=1e-4)
    assert review["decision"] == "FAIL"

    items, _ = validate_paginated(
        api.list_retake_items(QC_REVIEWER, {"quality_review_id": ctx["qr_id"]})
    )
    assert len(items) == 1
    assert_retake_item(items[0])
    assert items[0]["status"] == "OPEN"
    assert items[0]["defect_category"] == "LIPSYNC"

    job = validate_success(api.get_mix_job(ctx["mj_id"], MIXER))
    assert job["status"] == "STEM_CHECKED"
    assert job["mix_round"] == 2
    assert job["conformance_index"] is None

    order = validate_success(api.get_localization_order(ctx["o_id"], PC))
    assert order["status"] == "RECORDING"
    assert order["retake_cycles"] == 1


def test_the_fourth_link_regresses_the_named_assignment_and_voids_its_money(api):
    """PRD §3.9: "**Link 4** acts on every casting assignment named by an `OPEN`
    retake item of the failing review. Each such assignment regresses
    `RECORDED → CONFIRMED` on its booking dimension. On its payment dimension, the
    behaviour is conditional and this condition is what makes the cascade safe to run
    twice: when the assignment's `payment_status` is currently `ACCRUED`, its newest
    talent payment is moved `ACCRUED → VOIDED`, the assignment's payment dimension
    follows `ACCRUED → VOIDED`, and the amount to void — the sum of
    `session_cost_cents` over that assignment's `COMPLETED` sessions whose `is_retake`
    is false — is subtracted from the order's `committed_cents` and added to its
    `released_cents`, with `gross_accrued_cents` left exactly as it was."

    Design: Difficulty/transitive_cascade/qc_failure_four_link_regression_chain
    """
    ctx = setup_canon(43)
    fail_review_round(ctx)

    ca1 = validate_success(api.get_casting_assignment(ctx["ca1_id"], CASTING))
    assert ca1["casting_status"] == "CONFIRMED"
    assert ca1["payment_status"] == "VOIDED"
    assert validate_success(api.get_talent_payment(ctx["tp1_id"], PC))["status"] == "VOIDED"

    ca2 = validate_success(api.get_casting_assignment(ctx["ca2_id"], CASTING))
    assert ca2["casting_status"] == "RECORDED", (
        "an assignment named by no retake item is untouched by link 4"
    )
    order = validate_success(api.get_localization_order(ctx["o_id"], PC))
    assert order["committed_cents"] == 70000
    assert order["released_cents"] == 120000


# --------------------------------------------------------------------------
# Money is a conserved quantity across the compensating action
# --------------------------------------------------------------------------
def test_the_retake_void_conserves_gross_accrued_money(api):
    """PRD §2.9: "`gross_accrued_cents` is the conserved quantity: every accrual ever
    booked against the order, regardless of what happened to it afterwards."
    PRD §2.9: "After every single request, the invariant `gross_accrued_cents` equals
    `committed_cents` plus `released_cents` must hold."
    PRD §2.9: "A cascade that runs end to end must therefore leave
    `gross_accrued_cents` at exactly the value it held before the compensating action
    began."

    Design: Difficulty/compensating_invariant/order_money_conserved_across_retake_void
    """
    ctx = setup_canon(43)
    before = validate_success(api.get_localization_order(ctx["o_id"], PC))
    assert before["committed_cents"] == 190000
    assert before["released_cents"] == 0
    assert before["gross_accrued_cents"] == 190000
    assert_order_money_conserved(before)

    fail_review_round(ctx)

    after = validate_success(api.get_localization_order(ctx["o_id"], PC))
    assert after["gross_accrued_cents"] == 190000, (
        "the compensating action moves money between buckets, it never destroys it"
    )
    assert after["committed_cents"] == 70000
    assert after["released_cents"] == 120000
    assert_order_money_conserved(after)


def test_the_voided_payment_keeps_its_historical_figures(api):
    """PRD §2.9: "A compensating action — the fourth link of the quality-failure
    cascade acting on one casting assignment — computes the amount to void as the sum
    of the session costs over that assignment's completed non-retake sessions, but
    only when that assignment's `payment_status` is currently `ACCRUED`; when the
    payment dimension sits anywhere else, the amount to void is zero and no money
    moves at all, which is precisely what keeps the compensation idempotent across
    repeated retake rounds."
    PRD §3.10: "The payment is stored in `ACCRUED` with `settled_at` null, its
    `talent_id` denormalized from the assignment for territory checking, and its
    `variant` copied from the assignment's `usage_variant` at accrual time so that a
    later change of deal terms cannot rewrite history."

    Design: Difficulty/compensating_invariant/order_money_conserved_across_retake_void
    """
    ctx = setup_canon(43)
    accrued = validate_success(api.get_talent_payment(ctx["tp1_id"], PC))
    assert accrued["status"] == "ACCRUED"
    assert accrued["total_fee_cents"] == 198000

    fail_review_round(ctx)

    voided = validate_success(api.get_talent_payment(ctx["tp1_id"], PC))
    assert voided["status"] == "VOIDED"
    assert voided["total_fee_cents"] == 198000, (
        "voiding changes the payment's status, not the figures it recorded"
    )
    assert_order_money_conserved(
        validate_success(api.get_localization_order(ctx["o_id"], PC))
    )


# --------------------------------------------------------------------------
# The pass-rate threshold boundary
# --------------------------------------------------------------------------
def test_a_pass_rate_one_defect_below_the_threshold_is_refused(api):
    """PRD §3.9: "**The pass rate** is computed and stamped on both outcomes: it is 1
    minus the quotient of `defect_count` divided by the round's stored
    `sampled_loop_count`, rounded half up to four decimal places."
    PRD §3.9: "A rate strictly below it is refused with `ERR_QC_BELOW_THRESHOLD`."

    Design: Difficulty/boundary_precision_check/qc_pass_rate_exactly_at_threshold_is_a_pass
    """
    ctx = setup_canon(43)
    resp = api.decide_quality_review(
        ctx["qr_id"], {"decision": "PASS", "defect_count": 21}, QC_REVIEWER
    )
    validate_error(resp, ApiErrorId.ERR_QC_BELOW_THRESHOLD.value)
    assert resp.status_code == 409
    assert validate_success(api.get_quality_review(ctx["qr_id"], PC))["status"] == "IN_REVIEW"


def test_a_pass_rate_exactly_on_the_threshold_passes(api):
    """PRD §3.9: "A `PASS` decision is permitted only when the computed `pass_rate` is
    greater than or equal to the platform specification's `qc_pass_threshold`, the
    comparison being inclusive so that a rate exactly equal to the threshold passes."
    PRD §3.9: "A surviving pass stores `defect_count`, stamps `pass_rate`, advances
    the review `IN_REVIEW → PASSED`, sets `decision` to `PASS`, and increments the
    review's `version` by 1; `PASSED` is terminal."
    PRD §3.9: "Note carefully what a pass does *not* do: it does not move the order
    out of `QC`."

    Design: Difficulty/boundary_precision_check/qc_pass_rate_exactly_at_threshold_is_a_pass
    """
    ctx = setup_canon(43)
    passed = validate_success(
        api.decide_quality_review(
            ctx["qr_id"], {"decision": "PASS", "defect_count": 20}, QC_REVIEWER
        )
    )
    assert passed["pass_rate"] == pytest.approx(0.9000, abs=1e-4)
    assert passed["status"] == "PASSED"
    assert passed["decision"] == "PASS"
    assert validate_success(api.get_localization_order(ctx["o_id"], PC))["status"] == "QC"


# --------------------------------------------------------------------------
# Retake items
# --------------------------------------------------------------------------
def test_completing_a_retake_session_closes_the_open_retake_item(api):
    """PRD §3.7: "When `is_retake` is true, every retake item still `OPEN` whose
    `casting_assignment_id` matches this session's assignment is first moved to
    `RECORDED`, and then the casting assignment advances `CONFIRMED → RECORDED` as
    well."
    PRD §3.7: "The retake credit line is four tenths of the assignment's
    `agreed_rate_cents_per_hour` multiplied by the actual `duration_minutes` and
    divided by sixty, and it is zero unless the session's `is_retake` is true."
    PRD §3.9: "An assignment's `retake_minutes` — the sum of `duration_minutes` over
    its `COMPLETED` sessions whose `is_retake` is true — accumulates across these
    rounds and is reported alongside its `recorded_minutes`, which counts only the
    non-retake completions."

    Design: Corner/state_machines/retake_session_completion_closes_open_retake_items
    """
    ctx = setup_after_qc_failure()
    book_session(ctx, "s3_id", "ca1_id", "2026-09-11T09:00:00Z", "2026-09-11T11:00:00Z",
                 is_retake=True)
    completed = run_session_to_completed(ctx, "s3_id", "2026-09-11T09:00:00Z")

    assert validate_success(api.get_retake_item(ctx["ri_id"], PC))["status"] == "RECORDED"
    assert completed["is_retake"] is True
    assert completed["session_cost_cents"] == 91200
    assert completed["status"] == "COMPLETED"

    ca1 = validate_success(api.get_casting_assignment(ctx["ca1_id"], CASTING))
    assert ca1["casting_status"] == "RECORDED"
    assert ca1["retake_minutes"] == 120
    order = validate_success(api.get_localization_order(ctx["o_id"], PC))
    assert order["committed_cents"] == 161200


def test_a_lipsync_retake_item_can_never_be_waived(api):
    """PRD §3.9: "Alternatively the reviewer may waive it, advancing
    `OPEN → WAIVED`, but only under two conditions: the acting `X-User-ID` must equal
    the `reviewer_user_id` of the item's parent review, and the item's
    `defect_category` must not be `LIPSYNC`."
    PRD §3.9: "Lip-sync defects can never be waived and must be re-recorded; an
    attempt earns `ERR_RETAKE_NOT_WAIVABLE`."

    Design: Corner/state_machines/waiving_a_lipsync_retake_item_is_refused
    """
    ctx = setup_after_qc_failure()
    resp = api.waive_retake_item(ctx["ri_id"], QC_REVIEWER)
    validate_error(resp, ApiErrorId.ERR_RETAKE_NOT_WAIVABLE.value)
    assert resp.status_code == 409
    assert validate_success(api.get_retake_item(ctx["ri_id"], PC))["status"] == "OPEN"


def test_cascade_raised_retake_items_surface_only_through_the_filtered_list(api):
    """PRD §3.9: "**Link 1** creates one **retake item** per entry in the supplied
    `defects` list, each in `OPEN`."
    PRD §3.9: "Retake items are created only by this cascade — no direct create exists
    — and listing them filtered by `quality_review_id` and by `casting_assignment_id`
    is the only discovery channel for them."
    PRD §3.9: "Each item records the `quality_review_id` of the failing review, the
    `casting_assignment_id` of the performance that must be re-recorded, a non-empty
    `loop_ref` identifying the loop on the dubbing sheet, a `defect_category` of
    `LIPSYNC`, `PERFORMANCE`, `AUDIO` or `TRANSLATION` classifying which downstream
    step must repeat, and an `estimated_minutes` of at least 0 giving the booth time
    the reviewer estimates the retake needs."

    Design: Corner/endpoints/cascade_created_retake_items_are_only_discoverable_by_filtered_list
    """
    ctx = setup_canon(43)
    fail_review_round(ctx)

    by_review, _ = validate_paginated(
        api.list_retake_items(QC_REVIEWER, {"quality_review_id": ctx["qr_id"]})
    )
    by_assignment, _ = validate_paginated(
        api.list_retake_items(QC_REVIEWER, {"casting_assignment_id": ctx["ca1_id"]})
    )
    assert len(by_review) == 1 and len(by_assignment) == 1
    assert by_review[0]["id"] == by_assignment[0]["id"]

    item = by_review[0]
    assert item["status"] == "OPEN"
    assert item["defect_category"] == "LIPSYNC"
    assert item["loop_ref"] == "L-0042"
    assert item["estimated_minutes"] == 20

    other, _ = validate_paginated(
        api.list_retake_items(QC_REVIEWER, {"casting_assignment_id": ctx["ca2_id"]})
    )
    assert other == []


def test_restarting_a_review_while_a_retake_is_still_open_is_refused(api):
    """PRD §3.9: "That path carries one extra precondition and one extra effect: every
    retake item belonging to the review must have reached either `RECORDED` or
    `WAIVED`, and a review with even one item still `OPEN` is refused with
    `ERR_OPEN_RETAKES`; and on re-entry `round_number` is incremented by 1 before the
    new `sampled_loop_count` is stored."

    Design: Corner/validations/restarting_a_review_with_open_retakes_is_rejected
    """
    # The re-entry start also requires the owning order to be in QC, so the order is
    # walked back to QC with the retake item deliberately left OPEN.
    ctx = setup_open_retake_with_order_back_in_qc()
    assert validate_success(api.get_retake_item(ctx["ri_id"], PC))["status"] == "OPEN"

    resp = api.start_quality_review(ctx["qr_id"], {"sampled_loop_count": 200}, QC_REVIEWER)
    validate_error(resp, ApiErrorId.ERR_OPEN_RETAKES.value)
    assert resp.status_code == 409
    review = validate_success(api.get_quality_review(ctx["qr_id"], PC))
    assert review["status"] == "FAILED_RETAKE"
    assert review["round_number"] == 1


def test_starting_a_review_round_with_an_empty_sample_is_refused(api):
    """PRD §3.9: "Starting a round advances `PENDING → IN_REVIEW` and carries
    `sampled_loop_count`, the number of loops sampled in this round, which must be at
    least 1 — a start with a sample of 0 is refused with `ERR_EMPTY_QC_SAMPLE`."
    PRD §3.9: "The review is stored in `PENDING` with `round_number` at 1,
    `reviewer_user_id` null, `sampled_loop_count` and `defect_count` at 0, and
    `pass_rate` and `decision` null."

    Design: Corner/validations/starting_a_review_with_zero_sample_is_rejected
    """
    ctx = setup_order_in_qc()
    resp = api.start_quality_review(ctx["qr_id"], {"sampled_loop_count": 0}, QC_REVIEWER)
    validate_error(resp, ApiErrorId.ERR_EMPTY_QC_SAMPLE.value)
    assert resp.status_code == 422
    review = validate_success(api.get_quality_review(ctx["qr_id"], PC))
    assert review["status"] == "PENDING"
    assert review["pass_rate"] is None


def test_only_the_reviewer_who_started_a_round_may_decide_it(api):
    """PRD §3.9: "Whichever way the decision goes, the review must be `IN_REVIEW` and
    the acting `X-User-ID` must equal the `reviewer_user_id` stamped when the round
    was started, since a reviewer may not decide someone else's round; that refusal is
    `ERR_REVIEWER_MISMATCH`."
    PRD §2.11: "Third — and this is a continuity rule rather than a separation rule —
    the `X-User-ID` that decides a quality-review round must be the same `X-User-ID`
    that started it, recorded as `reviewer_user_id`; a mismatch is
    `ERR_REVIEWER_MISMATCH` at HTTP 403, and the same recorded reviewer is the only
    principal permitted to waive that review's retake items."

    Design: Corner/rbac/only_the_reviewer_who_started_a_round_may_decide_it
    """
    ctx = setup_order_in_qc()
    start_review_round(ctx, reviewer_user=REVIEWER_2, sampled_loop_count=200)

    resp = api.decide_quality_review(
        ctx["qr_id"], {"decision": "PASS", "defect_count": 20},
        make_native_reviewer_headers(REVIEWER_9),
    )
    validate_error(resp, ApiErrorId.ERR_REVIEWER_MISMATCH.value)
    assert resp.status_code == 403
    review = validate_success(api.get_quality_review(ctx["qr_id"], PC))
    assert review["status"] == "IN_REVIEW"
    assert review["pass_rate"] is None
    assert review["reviewer_user_id"] == REVIEWER_2


def test_the_script_reviewer_may_not_start_qc_on_the_same_order(api):
    """PRD §2.11: "Second, the `X-User-ID` recorded as `reviewed_by_user_id` on an
    order's script adaptation may not be the `X-User-ID` that starts a quality review
    on that same order."
    PRD §3.9: "Two further conditions apply: the owning order must be in `QC`, and the
    acting `X-User-ID` must differ from the `reviewed_by_user_id` recorded on that
    order's script adaptation, since the person who signed off the script may not also
    run QC on its recording — that refusal is `ERR_SEGREGATION_OF_DUTIES`."
    PRD §3.9: "The start stores `sampled_loop_count`, stamps `reviewer_user_id` with
    the acting `X-User-ID`, and increments the review's `version` by 1."

    Design: Corner/rbac/the_script_reviewer_may_not_run_qc_on_the_same_order
    """
    ctx = setup_order_in_qc()
    resp = api.start_quality_review(
        ctx["qr_id"], {"sampled_loop_count": 200}, SCRIPT_REVIEWER
    )
    validate_error(resp, ApiErrorId.ERR_SEGREGATION_OF_DUTIES.value)
    assert resp.status_code == 403

    started = validate_success(
        api.start_quality_review(ctx["qr_id"], {"sampled_loop_count": 200}, QC_REVIEWER)
    )
    assert started["status"] == "IN_REVIEW"
    assert started["reviewer_user_id"] == REVIEWER_2
    assert started["sampled_loop_count"] == 200


def test_a_third_failing_round_is_refused_once_two_cycles_are_spent(api):
    """PRD §3.9: "A `FAIL` decision is permitted only when the request carries at
    least one defect entry — an empty `defects` list on a fail is likewise refused
    with `ERR_QC_BELOW_THRESHOLD` — and only when the owning order's `retake_cycles`
    is strictly less than 2."
    PRD §3.9: "An order that has already been round-tripped twice cannot be failed a
    third time and earns `ERR_RETAKE_LIMIT_EXCEEDED`; at that point the reviewer must
    either pass the mix or the order must be cancelled."

    Design: Corner/validations/failing_a_third_retake_round_is_rejected
    """
    ctx = setup_canon(43)

    def _retake_round(session_key, day, loop_ref, category):
        fail_review_round(ctx, loop_ref=loop_ref, defect_category=category)
        book_session(ctx, session_key, "ca1_id",
                     f"{day}T09:00:00Z", f"{day}T11:00:00Z", is_retake=True)
        run_session_to_completed(ctx, session_key, f"{day}T09:00:00Z")
        validate_success(api.mix_mix_job(ctx["mj_id"], {"loudness_lufs": -24.8}, MIXER))
        validate_success(api.conform_mix_job(ctx["mj_id"], MIXER))
        start_review_round(ctx, reviewer_user=REVIEWER_2, sampled_loop_count=200)

    _retake_round("s3_id", "2026-09-11", "L-0042", "LIPSYNC")
    _retake_round("s4_id", "2026-09-12", "L-0100", "PERFORMANCE")

    order = validate_success(api.get_localization_order(ctx["o_id"], PC))
    assert order["retake_cycles"] == 2

    resp = api.decide_quality_review(
        ctx["qr_id"],
        {"decision": "FAIL", "defect_count": 30,
         "defects": [defect_entry(ctx["ca1_id"], "L-0200", "AUDIO")]},
        QC_REVIEWER,
    )
    validate_error(resp, ApiErrorId.ERR_RETAKE_LIMIT_EXCEEDED.value)
    assert resp.status_code == 409
    review = validate_success(api.get_quality_review(ctx["qr_id"], PC))
    assert review["status"] == "IN_REVIEW"
    assert review["round_number"] == 3
