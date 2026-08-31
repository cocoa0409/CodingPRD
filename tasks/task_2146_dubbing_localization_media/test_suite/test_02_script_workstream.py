"""The script workstream: translation, the two fidelity variants, the revision
cycle and native review."""

import pytest

from test_helpers import (
    ADAPTOR_1,
    PC,
    REVIEWER_1,
    ApiErrorId,
    adapt_payload,
    assert_script_adaptation,
    make_adaptor_headers,
    make_native_reviewer_headers,
    setup_canon,
    submit_review_payload,
    validate_error,
    validate_paginated,
    validate_success,
)

ADAPTOR_HEADERS = make_adaptor_headers(ADAPTOR_1)
REVIEWER_HEADERS = make_native_reviewer_headers(REVIEWER_1)


def test_submit_review_stamps_a_final_score_that_diverges_from_the_provisional_one(api):
    """PRD §3.4: "Because it reads only what the adaptor declared, a perfectly-covered
    but badly-synced adaptation scores high here; it never reads
    `measured_sync_deviation_ms_total` or `lines_over_deviation`."
    PRD §3.4: "This variant never reads the cut's `loop_count` coverage at all, which
    is why the same adaptation row legitimately carries two different numbers at once,
    and why the two must be stamped by two different steps rather than recomputed
    together."
    PRD §3.4: "That sum is then multiplied by the tier weight of the order's
    `priority_tier` — 1.00 for a `STANDARD` order, 0.97 for an `EXPEDITED` order and
    0.94 for a `RUSH` order — and the product is rounded half up to four decimal
    places."

    Design: Difficulty/dual_variant_calc/adaptation_provisional_vs_final_fidelity_diverge
    """
    ctx = setup_canon(14)
    data = validate_success(
        api.submit_adaptation_review(
            ctx["sa_id"],
            submit_review_payload(
                measured_sync_deviation_ms_total=22800, lines_over_deviation=38
            ),
            ADAPTOR_HEADERS,
        )
    )
    assert_script_adaptation(data)
    assert data["provisional_fidelity_score"] == pytest.approx(0.9409, abs=1e-4)
    assert data["final_fidelity_score"] == pytest.approx(0.6596, abs=1e-4)
    assert data["provisional_fidelity_score"] != data["final_fidelity_score"], (
        "the declared-count and measured-deviation variants must diverge"
    )
    assert data["status"] == "IN_REVIEW"


def test_provisional_score_is_stamped_at_adapt_before_any_measurement_exists(api):
    """PRD §3.4: "The adaptation is stored in `DRAFT` with `revision_round` at 1,
    `adapted_by_user_id` and `reviewed_by_user_id` null, `declared_loop_count`,
    `measured_sync_deviation_ms_total` and `lines_over_deviation` all at 0, and both
    `provisional_fidelity_score` and `final_fidelity_score` null."
    PRD §3.4: "The pass is accepted from either `TRANSLATED` or
    `REVISION_REQUESTED`, and in both cases it stores the supplied
    `declared_loop_count`, stamps `adapted_by_user_id` with the acting `X-User-ID`,
    recomputes `provisional_fidelity_score`, sets the adaptation to `ADAPTED` and
    increments the adaptation's `version` by 1."
    PRD §3.4: "On the *first* submission only, the owning order cascades
    `SCRIPT_IN_PROGRESS → CASTING` with its own `version` incremented by 1;
    submissions in later revision rounds find the order already past
    `SCRIPT_IN_PROGRESS` and leave it alone."

    Design: Difficulty/dual_variant_calc/adaptation_provisional_vs_final_fidelity_diverge
    """
    ctx = setup_canon(14)
    after_adapt = validate_success(api.get_script_adaptation(ctx["sa_id"], PC))
    assert after_adapt["status"] == "ADAPTED"
    assert after_adapt["declared_loop_count"] == 380
    assert after_adapt["provisional_fidelity_score"] == pytest.approx(0.9409, abs=1e-4)
    assert after_adapt["final_fidelity_score"] is None, (
        "the measured variant cannot exist before the sync pass is submitted"
    )

    validate_success(
        api.submit_adaptation_review(
            ctx["sa_id"],
            submit_review_payload(
                measured_sync_deviation_ms_total=22800, lines_over_deviation=38
            ),
            ADAPTOR_HEADERS,
        )
    )
    order = validate_success(api.get_localization_order(ctx["o_id"], PC))
    assert order["status"] == "CASTING"


def test_revision_cycle_reenters_adapted_and_restamps_both_scores(api):
    """PRD §3.4: "The two entry paths differ in exactly one respect: when the pass
    arrives from `REVISION_REQUESTED`, closing the
    `ADAPTED → IN_REVIEW → REVISION_REQUESTED → ADAPTED` cycle, `revision_round` is
    first incremented by 1; when it arrives from `TRANSLATED`, `revision_round` stays
    where it is."
    PRD §3.4: "Both supplied values are stored, `final_fidelity_score` is recomputed
    and stamped, and the adaptation's `version` increments by 1."

    Design: Difficulty/non_linear_state_machine/script_adaptation_revision_cycle_reenters_adapted
    """
    ctx = setup_canon(15)
    validate_success(
        api.review_adaptation(
            ctx["sa_id"], {"decision": "REQUEST_REVISION", "notes": "Loop 42 flaps"},
            REVIEWER_HEADERS,
        )
    )
    validate_success(
        api.adapt_adaptation(
            ctx["sa_id"], adapt_payload(declared_loop_count=420), ADAPTOR_HEADERS
        )
    )
    data = validate_success(
        api.submit_adaptation_review(
            ctx["sa_id"],
            submit_review_payload(
                measured_sync_deviation_ms_total=15200, lines_over_deviation=10
            ),
            ADAPTOR_HEADERS,
        )
    )
    assert data["status"] == "IN_REVIEW"
    assert data["revision_round"] == 2
    assert data["declared_loop_count"] == 420
    assert data["provisional_fidelity_score"] == pytest.approx(0.9506, abs=1e-4)
    assert data["final_fidelity_score"] == pytest.approx(0.7987, abs=1e-4)


def test_revision_round_advances_only_on_the_revision_entry_path(api):
    """PRD §3.4: "`REQUEST_REVISION` moves `IN_REVIEW → REVISION_REQUESTED` and
    imposes no further condition."
    PRD §3.4: "The two entry paths differ in exactly one respect: when the pass
    arrives from `REVISION_REQUESTED`, closing the
    `ADAPTED → IN_REVIEW → REVISION_REQUESTED → ADAPTED` cycle, `revision_round` is
    first incremented by 1; when it arrives from `TRANSLATED`, `revision_round` stays
    where it is."
    PRD §3.4: "On the *first* submission only, the owning order cascades
    `SCRIPT_IN_PROGRESS → CASTING` with its own `version` incremented by 1;
    submissions in later revision rounds find the order already past
    `SCRIPT_IN_PROGRESS` and leave it alone."

    Design: Difficulty/non_linear_state_machine/script_adaptation_revision_cycle_reenters_adapted
    """
    ctx = setup_canon(15)
    first_pass = validate_success(api.get_script_adaptation(ctx["sa_id"], PC))
    assert first_pass["revision_round"] == 1, (
        "the TRANSLATED entry path leaves revision_round where it is"
    )

    sent_back = validate_success(
        api.review_adaptation(
            ctx["sa_id"], {"decision": "REQUEST_REVISION"}, REVIEWER_HEADERS
        )
    )
    assert sent_back["status"] == "REVISION_REQUESTED"
    assert sent_back["revision_round"] == 1, (
        "the round advances at the re-adapt, not at the review"
    )

    readapted = validate_success(
        api.adapt_adaptation(
            ctx["sa_id"], adapt_payload(declared_loop_count=420), ADAPTOR_HEADERS
        )
    )
    assert readapted["status"] == "ADAPTED"
    assert readapted["revision_round"] == 2

    validate_success(
        api.submit_adaptation_review(
            ctx["sa_id"],
            submit_review_payload(
                measured_sync_deviation_ms_total=15200, lines_over_deviation=10
            ),
            ADAPTOR_HEADERS,
        )
    )
    order = validate_success(api.get_localization_order(ctx["o_id"], PC))
    assert order["status"] == "CASTING", (
        "a later submission finds the order already past SCRIPT_IN_PROGRESS"
    )


def test_opening_the_script_workstream_advances_the_order_out_of_draft(api):
    """PRD §3.4: "The adaptation is stored in `DRAFT` with `revision_round` at 1,
    `adapted_by_user_id` and `reviewed_by_user_id` null, `declared_loop_count`,
    `measured_sync_deviation_ms_total` and `lines_over_deviation` all at 0, and both
    `provisional_fidelity_score` and `final_fidelity_score` null."
    PRD §3.4: "Creating it cascades the owning order `DRAFT → SCRIPT_IN_PROGRESS` and
    increments the order's `version` by 1."

    Design: Corner/state_machines/creating_script_adaptation_advances_order_to_script_in_progress
    """
    ctx = setup_canon(11)
    adaptation = validate_success(
        api.create_script_adaptation({"order_id": ctx["o_id"]}, ADAPTOR_HEADERS), 201
    )
    assert adaptation["status"] == "DRAFT"
    assert adaptation["revision_round"] == 1

    order = validate_success(api.get_localization_order(ctx["o_id"], PC))
    assert order["status"] == "SCRIPT_IN_PROGRESS"
    assert order["version"] == 2, (
        f"the cascade is exactly one order mutation, got version {order['version']}"
    )
    rows, _ = validate_paginated(
        api.list_script_adaptations(PC, {"order_id": ctx["o_id"]})
    )
    assert len(rows) == 1


def test_a_freshly_created_order_is_in_draft_with_no_script_workstream(api):
    """PRD §3.3: "A new order lands in `DRAFT` with `committed_cents`,
    `released_cents`, `gross_accrued_cents` and `retake_cycles` all at 0,
    `metadata_locale_fields` an empty object, and `delivered_at` null."
    PRD §3.4: "Two preconditions apply: the order must be in `DRAFT`, and it must not
    already carry a script adaptation — one order has exactly one adaptation row for
    its whole life, and revision rounds happen inside that single row rather than by
    creating new ones."

    Design: Corner/state_machines/new_order_starts_in_draft
    """
    from test_helpers import setup_draft_order

    ctx = setup_draft_order(
        spec_overrides={"metadata_fields_required": ["title_local"]},
        priority_tier="STANDARD",
    )
    order = validate_success(api.get_localization_order(ctx["o_id"], PC))
    assert order["status"] == "DRAFT"
    rows, _ = validate_paginated(
        api.list_script_adaptations(PC, {"order_id": ctx["o_id"]})
    )
    assert rows == [], "no script workstream exists until one is opened"


def test_replaying_translate_on_a_translated_adaptation_is_refused(api):
    """PRD §3.4: "Recording the raw translation pass advances `DRAFT → TRANSLATED` and
    takes no payload."
    PRD §2.6 ladder step 11: "On every action endpoint: the target row currently sits
    in a state from which the requested transition is declared; otherwise
    `ERR_INVALID_STATE` (409)."

    Design: Corner/state_machines/second_translate_on_same_adaptation_is_rejected
    """
    ctx = setup_canon(13)
    resp = api.translate_adaptation(ctx["sa_id"], ADAPTOR_HEADERS)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)
    assert resp.status_code == 409
    data = validate_success(api.get_script_adaptation(ctx["sa_id"], PC))
    assert data["status"] == "TRANSLATED"
    assert data["version"] == 2, (
        f"create then translate is exactly two writes, got version {data['version']}"
    )


def test_approval_below_the_specification_fidelity_floor_is_refused(api):
    """PRD §3.4: "`APPROVE` moves `IN_REVIEW → APPROVED` and imposes exactly one
    further condition: the stamped `final_fidelity_score` must be greater than or
    equal to the `min_fidelity_score` of the order's platform specification, the
    comparison being inclusive so that an exact match approves."
    PRD §3.4: "A score strictly below the specification is refused with
    `ERR_FIDELITY_BELOW_SPEC`."

    Design: Corner/validations/approval_below_the_spec_fidelity_floor_is_rejected
    """
    ctx = setup_canon(15, spec={"min_fidelity_score": 0.7})
    before = validate_success(api.get_script_adaptation(ctx["sa_id"], PC))
    assert before["final_fidelity_score"] == pytest.approx(0.6596, abs=1e-4)

    resp = api.review_adaptation(ctx["sa_id"], {"decision": "APPROVE"}, REVIEWER_HEADERS)
    validate_error(resp, ApiErrorId.ERR_FIDELITY_BELOW_SPEC.value)
    assert resp.status_code == 409
    assert validate_success(api.get_script_adaptation(ctx["sa_id"], PC))["status"] == "IN_REVIEW"


def test_the_adaptor_of_a_script_may_not_review_their_own_work(api):
    """PRD §3.4: "Either way the adaptation must currently be `IN_REVIEW`, the acting
    `X-User-ID` must differ from `adapted_by_user_id` — a self-review is refused with
    `ERR_SEGREGATION_OF_DUTIES` — the acting `X-User-ID` is stamped into
    `reviewed_by_user_id`, and the adaptation's `version` increments by 1."
    PRD §2.11: "First, the `X-User-ID` that most recently adapted a script — recorded
    as `adapted_by_user_id` — may not be the `X-User-ID` that reviews that adaptation."

    Design: Corner/rbac/the_adaptor_of_a_script_may_not_review_it
    """
    ctx = setup_canon(15)
    self_review = api.review_adaptation(
        ctx["sa_id"], {"decision": "APPROVE"}, make_native_reviewer_headers(ADAPTOR_1)
    )
    validate_error(self_review, ApiErrorId.ERR_SEGREGATION_OF_DUTIES.value)
    assert self_review.status_code == 403

    approved = validate_success(
        api.review_adaptation(ctx["sa_id"], {"decision": "APPROVE"}, REVIEWER_HEADERS)
    )
    assert approved["status"] == "APPROVED"
    assert approved["reviewed_by_user_id"] == REVIEWER_1
