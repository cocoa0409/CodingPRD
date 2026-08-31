"""Mixing, the music-and-effects stem gate and the conformance index."""

import pytest

from test_helpers import (
    ADMIN,
    MIXER,
    PC,
    ApiErrorId,
    assert_mix_job,
    book_session,
    create_mix_job_payload,
    run_session_to_completed,
    setup_canon,
    validate_error,
    validate_paginated,
    validate_success,
)


def _stem_checked_job_with_one_unrecorded_sibling(api):
    """ca1 RECORDED through a completed session, ca2 still merely CONFIRMED."""
    ctx = setup_canon(27)
    run_session_to_completed(ctx, "s1_id", "2026-09-10T09:00:00Z")
    job = validate_success(
        api.create_mix_job(create_mix_job_payload(ctx["o_id"]), MIXER), 201
    )
    ctx["mj_id"] = job["id"]
    validate_success(api.stem_check_mix_job(ctx["mj_id"], MIXER))
    return ctx


def test_printing_the_mix_with_one_unrecorded_assignment_is_refused(api):
    """PRD §3.8: "Before the print is accepted, every non-superseded casting
    assignment of the order that sits in `PROPOSED`, `HOLD_REQUESTED`, `HELD`,
    `CONFIRMED` or `RECORDED` must have a `casting_status` of `RECORDED`; a single
    live assignment short of that earns `ERR_CAST_NOT_FULLY_RECORDED`."

    Design: Difficulty/cross_entity_state_dependency/mix_print_gated_on_every_casting_assignment_recorded
    """
    ctx = _stem_checked_job_with_one_unrecorded_sibling(api)
    assert validate_success(
        api.get_casting_assignment(ctx["ca2_id"], MIXER)
    )["casting_status"] == "CONFIRMED"

    resp = api.mix_mix_job(ctx["mj_id"], {"loudness_lufs": -24.8}, MIXER)
    validate_error(resp, ApiErrorId.ERR_CAST_NOT_FULLY_RECORDED.value)
    assert resp.status_code == 409
    assert validate_success(api.get_mix_job(ctx["mj_id"], MIXER))["status"] == "STEM_CHECKED"


def test_the_mix_prints_once_the_last_assignment_reaches_recorded(api):
    """PRD §3.8: "The supplied `loudness_lufs` is stored, `conformance_index` is
    recomputed and stamped, the job's `version` increments by 1, and the owning order
    cascades — `RECORDING → MIXING` on a first pass, or `RECALLED → MIXING` when the
    order is being re-mixed after a recall — with the order's `version` incremented by
    1."
    PRD §3.8: "The index is four tenths of the loudness component plus thirty-five
    hundredths of the stem component plus twenty-five hundredths of the cast-coverage
    component, rounded half up to four decimal places."

    Design: Difficulty/cross_entity_state_dependency/mix_print_gated_on_every_casting_assignment_recorded
    """
    ctx = _stem_checked_job_with_one_unrecorded_sibling(api)
    book_session(ctx, "s2b_id", "ca2_id", "2026-09-10T12:00:00Z", "2026-09-10T13:08:00Z")
    run_session_to_completed(ctx, "s2b_id", "2026-09-10T12:00:00Z")
    assert validate_success(
        api.get_casting_assignment(ctx["ca2_id"], MIXER)
    )["casting_status"] == "RECORDED"

    mixed = validate_success(api.mix_mix_job(ctx["mj_id"], {"loudness_lufs": -24.8}, MIXER))
    assert_mix_job(mixed)
    assert mixed["status"] == "MIXED"
    assert mixed["conformance_index"] == pytest.approx(0.8400, abs=1e-4)
    assert validate_success(api.get_localization_order(ctx["o_id"], PC))["status"] == "MIXING"


def test_stem_check_refuses_a_layout_that_disagrees_with_the_specification(api):
    """PRD §3.8: "The stem check advances `QUEUED → STEM_CHECKED` and is a pure gate:
    the job must be `QUEUED`, `me_stem_present` must be true, and the job's
    `stem_layout` must equal the `stem_layout` of the order's platform specification."
    PRD §3.8: "A missing stem or a layout that disagrees with the specification is
    refused with `ERR_STEM_LAYOUT_MISMATCH`."

    Design: Corner/validations/stem_check_rejects_a_layout_that_differs_from_the_spec
    """
    ctx = setup_canon(36)
    job = validate_success(
        api.create_mix_job(
            create_mix_job_payload(ctx["o_id"], stem_layout="STEREO_ME",
                                   me_stem_present=True),
            MIXER,
        ),
        201,
    )
    resp = api.stem_check_mix_job(job["id"], MIXER)
    validate_error(resp, ApiErrorId.ERR_STEM_LAYOUT_MISMATCH.value)
    assert resp.status_code == 422
    assert validate_success(api.get_mix_job(job["id"], MIXER))["status"] == "QUEUED"


def test_a_conformance_index_below_the_minimum_blocks_the_conform(api):
    """PRD §3.8: "The loudness component starts from the absolute difference between
    the mix's measured `loudness_lufs` and the platform specification's
    `loudness_target_lufs`; that difference is divided by a tolerance of two loudness
    units, the quotient is subtracted from 1, and the result is floored at 0.0 so that
    a wildly off-target mix scores zero rather than negative."
    PRD §3.8: "Conforming the mix advances `MIXED → CONFORMED` and is permitted only
    when the stamped `conformance_index` is greater than or equal to 0.80, the
    comparison being inclusive so that an index of exactly 0.80 conforms."
    PRD §3.8: "A strictly lower index is refused with `ERR_CONFORMANCE_BELOW_MIN`."

    Design: Corner/calculations/conformance_index_below_minimum_blocks_conform
    """
    ctx = setup_canon(36)
    job = validate_success(
        api.create_mix_job(create_mix_job_payload(ctx["o_id"]), MIXER), 201
    )
    validate_success(api.stem_check_mix_job(job["id"], MIXER))
    mixed = validate_success(api.mix_mix_job(job["id"], {"loudness_lufs": -26.5}, MIXER))
    assert mixed["conformance_index"] == pytest.approx(0.6000, abs=1e-4)

    resp = api.conform_mix_job(job["id"], MIXER)
    validate_error(resp, ApiErrorId.ERR_CONFORMANCE_BELOW_MIN.value)
    assert resp.status_code == 409
    assert validate_success(api.get_mix_job(job["id"], MIXER))["status"] == "MIXED"
    assert validate_success(api.get_localization_order(ctx["o_id"], PC))["status"] == "MIXING"


def test_opening_a_mix_job_with_no_recorded_cast_is_refused(api):
    """PRD §3.8: "The job may only be opened on an order that already has at least one
    non-superseded casting assignment sitting in `casting_status` of `RECORDED`; an
    order with none earns `ERR_NO_RECORDED_CAST`."

    Design: Corner/validations/mix_job_without_any_recorded_cast_is_rejected
    """
    ctx = setup_canon(21)
    resp = api.create_mix_job(create_mix_job_payload(ctx["o_id"]), MIXER)
    validate_error(resp, ApiErrorId.ERR_NO_RECORDED_CAST.value)
    assert resp.status_code == 409
    rows, _ = validate_paginated(api.list_mix_jobs(MIXER, {"order_id": ctx["o_id"]}))
    assert rows == []


def test_the_platform_admin_is_not_a_superset_and_cannot_open_a_mix(api):
    """PRD §2.1: "A `PlatformAdmin` is the operational back office responsible for
    talent money and for the test-driving logical clock; it is deliberately **not** a
    superset of the other roles and cannot cast, book, mix or review."
    PRD §2.6 ladder step 3: "The acting role appears in the set of roles authorised
    for the requested endpoint, on every endpoint; otherwise `ERR_ROLE_FORBIDDEN`
    (403)."
    PRD §3.8: "A new job is stored in `QUEUED` with `mix_round` at 1, `loudness_lufs`
    null and `conformance_index` null."

    Design: Corner/rbac/platform_admin_is_not_a_superset_and_cannot_mix
    """
    ctx = setup_canon(36)
    resp = api.create_mix_job(create_mix_job_payload(ctx["o_id"]), ADMIN)
    validate_error(resp, ApiErrorId.ERR_ROLE_FORBIDDEN.value)
    assert resp.status_code == 403

    job = validate_success(
        api.create_mix_job(create_mix_job_payload(ctx["o_id"]), MIXER), 201
    )
    assert job["status"] == "QUEUED"
    assert job["mix_round"] == 1


def test_the_conform_cascade_is_visible_in_the_very_next_read(api):
    """PRD §3.8: "A successful conform increments the job's `version` by 1 and
    cascades the owning order `MIXING → QC`, incrementing the order's `version` by 1 —
    this is the handoff that puts the deliverable in front of a native reviewer."
    PRD §2.4: "Where a workflow narrative in Section 3 says a cascade "advances" or
    "regresses" an entity, that entity's `version` increments and its `updated_at`
    refreshes even though the client addressed a different resource."

    Design: Corner/consistency_model/cascade_is_visible_immediately_in_the_same_request_cycle
    """
    ctx = setup_canon(36)
    job = validate_success(
        api.create_mix_job(create_mix_job_payload(ctx["o_id"]), MIXER), 201
    )
    validate_success(api.stem_check_mix_job(job["id"], MIXER))
    validate_success(api.mix_mix_job(job["id"], {"loudness_lufs": -24.8}, MIXER))
    version_in_mixing = validate_success(api.get_localization_order(ctx["o_id"], PC))["version"]

    conformed = validate_success(api.conform_mix_job(job["id"], MIXER))
    assert conformed["status"] == "CONFORMED", (
        "the conform response itself already reports the new state"
    )
    order = validate_success(api.get_localization_order(ctx["o_id"], PC))
    assert order["status"] == "QC"
    assert order["version"] == version_in_mixing + 1
    assert conformed["conformance_index"] == pytest.approx(0.8400, abs=1e-4)
