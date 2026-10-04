"""Payer authorization, concurrent review and the step-down pressure score."""

import pytest
from test_helpers import (
    C,
    ApiErrorId,
    appoint_level_change,
    approve_authorization,
    complete_level_change,
    deny_authorization,
    read_authorization,
    read_episode,
    request_authorization,
    run_ops,
    set_clock,
    open_episode,
    place_episode,
    setup_accumulated_episode,
    setup_admitted_episode,
    setup_claimed_episode,
    setup_staged_episode,
    setup_exhausted_episode,
    setup_site,
    submit_concurrent_review,
    utilization_summary,
    validate_error,
)


# ------------------------------------------------------------- concurrent review

def test_concurrent_review_extends_authorized_days_by_exactly_the_interval(api):
    """PRD §2.8: "Filing a concurrent review extends `authorized_days` by the payer's
    `concurrent_review_interval_days`, recomputes `review_due_at` from the new total and
    increments `concurrent_review_count` by one."

    Design: Corner/endpoints/concurrent_review_extends_the_authorized_days_by_exactly_the_interval
    """
    site = setup_site()
    claim = setup_claimed_episode(site=site)
    before = read_authorization(claim.auth_id)
    assert before["authorized_days"] == 14
    assert before["concurrent_review_count"] == 0

    updated = submit_concurrent_review(site, claim.auth_id)
    assert updated["authorized_days"] == 21, "14 granted days plus the payer's 7-day interval"
    assert updated["concurrent_review_count"] == 1
    assert updated["days_used"] == 0, "only a facility-ops run banks days (PRD §2.8)"


def test_days_used_only_moves_on_a_facility_ops_epoch(api):
    """PRD §2.8: "The bank is burned by the facility-ops cycle, not by wall time."
    PRD §2.8: "The order matters: the clock advances first, then `days_used` and
    `days_remaining` are recomputed from the advanced clock."

    Design: Corner/cross_cutting_complexity_layers/ops_run_checkpoint_is_the_only_mover_of_days_used
    """
    site = setup_site()
    setup = setup_accumulated_episode(
        site=site, admitted_at=C.CLOCK_2026_09_02, burn_clock=C.CLOCK_2026_09_08, burns=1
    )
    assert setup.authorization["days_used"] == 6
    assert setup.authorization["days_remaining"] == 8

    run_ops(site.id)
    after = read_authorization(setup.auth_id)
    assert after["days_used"] == 6, "the burn interval opens at last_ops_run_at"
    assert after["posture"] == "APPROVED", "8 remaining exceeds the 7-day review interval"


def test_days_remaining_at_the_review_interval_is_due_and_zero_wins(api):
    """
    PRD §2.8: "Otherwise, a `days_remaining` at or below the payer's
    `concurrent_review_interval_days` makes the posture `CONCURRENT_REVIEW_DUE`; a
    `days_remaining` of one more day than that interval does not." PRD §2.8: "A `days_remaining`
    of exactly 0 makes the posture `EXHAUSTED`, and this case wins outright — an authorization
    at exactly zero remaining days is never reported as due for review, even when the payer's
    review interval is 0." PRD §2.8: "the sum is capped at `authorized_days`."

    Design: Difficulty/boundary_precision_check/boundary_review_due_at_exact_interval
    """
    site = setup_site()
    setup = setup_accumulated_episode(
        site=site, admitted_at=C.CLOCK_2026_09_02, burn_clock=C.CLOCK_2026_09_08, burns=1,
        closes_interval=True,
    )
    at_interval = read_authorization(setup.auth_id)
    assert (at_interval["days_used"], at_interval["days_remaining"]) == (7, 7)
    assert at_interval["posture"] == "CONCURRENT_REVIEW_DUE", (
        "exactly the review interval is inclusive (PRD §2.8)"
    )

    # The arm at the interval has been observed, so the second half of the claim —
    # zero remaining days wins outright over the review-due test — is exercised by
    # burning the remaining seven days of the grant in one run.
    set_clock("2026-09-16T00:00:00Z")
    run_ops(site.id)
    exhausted = read_authorization(setup.auth_id)
    assert (exhausted["days_used"], exhausted["days_remaining"]) == (14, 0)
    assert exhausted["posture"] == "EXHAUSTED"
    assert exhausted["posture"] != "CONCURRENT_REVIEW_DUE", (
        "zero remaining wins over the review-due test even when 0 <= the interval"
    )

    set_clock(C.CLOCK_2026_09_20)
    run_ops(site.id)
    still = read_authorization(setup.auth_id)
    assert (still["days_used"], still["days_remaining"]) == (14, 0), (
        "days_used is capped at authorized_days and never goes negative"
    )


def test_admission_against_an_exhausted_authorization_is_refused_as_a_payment_required(api):
    """PRD §3.3: "The authorization's `days_remaining` must be strictly greater than 0,
    reported as `ERR_AUTHORIZATION_DAYS_EXHAUSTED` (HTTP 402)."

    Design: Difficulty/boundary_precision_check/boundary_review_due_at_exact_interval
    """
    site = setup_site()
    setup = setup_exhausted_episode(site=site, admit_clock=C.CLOCK_2026_09_01)

    from test_helpers import INTAKE_NURSE_HEADERS

    response = api.admit_episode(site.id, setup.id, {}, INTAKE_NURSE_HEADERS)
    validate_error(response, ApiErrorId.ERR_AUTHORIZATION_DAYS_EXHAUSTED, 402)


# ---------------------------------------------------- the two urgency readings

def test_persisted_urgency_uses_the_granted_days_denominator(api):
    """
    PRD §3.2: "The first variant, which is the one persisted as `urgency_score` on the
    authorization, sets the time-pressure term by dividing `days_used` by `authorized_days` and
    multiplying by a time weight of 60; the term is 0 when `authorized_days` is 0." PRD §3.2:
    "the score is 30.0 plus 16 plus 15, rounded half up to one decimal place, giving 61.0."

    Design: Difficulty/dual_variant_calc/stepdown_urgency_consumed_vs_extended_window
    """
    site = setup_site()
    setup = setup_accumulated_episode(
        site=site, admitted_at=C.CLOCK_2026_09_02, burn_clock=C.CLOCK_2026_09_08, burns=1
    )
    submit_concurrent_review(site, setup.auth_id)

    auth = read_authorization(setup.auth_id)
    assert auth["authorized_days"] == 21, "the review extends the running total by 7 days"
    assert (auth["days_used"], auth["days_remaining"]) == (6, 15)
    assert auth["concurrent_review_count"] == 1
    # PRD §3.2 measures the persisted variant "against the granted days alone", so the
    # denominator is the 14 granted at approval, not the 21 the review has widened.
    assert auth["urgency_score"] == pytest.approx(56.7, abs=0.01), (
        "(6/14)*60 + (3-1)*8 + 15 = 25.714... + 16 + 15"
    )


def test_projected_urgency_widens_the_denominator_by_each_review(api):
    """PRD §3.2: "The second variant, exposed only as `projected_step_down_urgency` on the
    episode's utilization summary and never persisted, widens the denominator instead."
    PRD §3.2: "The projected figure is strictly lower than the persisted one as soon as any
    concurrent review has been filed."

    Design: Difficulty/dual_variant_calc/stepdown_urgency_consumed_vs_extended_window
    """
    site = setup_site()
    setup = setup_accumulated_episode(
        site=site, admitted_at=C.CLOCK_2026_09_02, burn_clock=C.CLOCK_2026_09_08, burns=1
    )
    submit_concurrent_review(site, setup.auth_id)
    summary = utilization_summary(setup.id, authorization_id=setup.auth_id)

    assert summary["authorization_id"] == setup.auth_id
    assert summary["days_used"] == 6 and summary["days_remaining"] == 15
    assert summary["projected_step_down_urgency"] == pytest.approx(48.1, abs=0.01), (
        "(6/21)*60 + 16 + 15 = 17.142... + 31"
    )
    assert summary["projected_step_down_urgency"] < read_authorization(setup.auth_id)["urgency_score"]


def test_utilization_summary_reproduces_the_stored_authorization_picture(api):
    """
    PRD §3.8: "For an episode it reports the authorization's `urgency_score`, the
    `projected_step_down_urgency` from the extended-window variant, the authorization's
    `days_used` and `days_remaining`, the `curriculum_compliance_percent`, the facility's
    `committed_bed_nights`, an `outstanding_formula` string, a `formula_version` integer and the
    episode's `discharged_at`; an `authorization_id` may be supplied to select which
    authorization is summarized." PRD §2.9: "the facility's committed bed nights, defined as the
    count of `Bed` rows whose `status` is `OCCUPIED`."

    Design: Corner/endpoints/utilization_summary_computed_read_agrees_with_the_stored_authorization
    """
    site = setup_site()
    setup = setup_staged_episode(site=site)
    summary = utilization_summary(setup.id, authorization_id=setup.auth_id)

    stored = read_authorization(setup.auth_id)
    assert summary["days_used"] == stored["days_used"]
    assert summary["days_remaining"] == stored["days_remaining"]
    assert summary["committed_bed_nights"] == 1, "the ASAM_3_5 hold is the only OCCUPIED bed"
    assert summary["discharged_at"] is None
    assert isinstance(summary["outstanding_formula"], str) and summary["outstanding_formula"]
    assert isinstance(summary["formula_version"], int)


def test_denied_authorizations_bank_no_days_and_carry_no_pressure(api):
    """PRD §3.2: "A `PENDING` authorization becomes `DENIED` outright."
    PRD §3.2: "The new row starts at posture `PENDING`, with `days_used` at 0 and
    `concurrent_review_count` at 0."

    Design: Corner/calculations/urgency_score_input_set_excludes_denied_and_expired_authorizations
    """
    site = setup_site()
    claim = setup_claimed_episode(site=site)
    # PRD §3.2 stacks a second authorization only when the level differs; the second
    # row starts PENDING with nothing banked, is denied outright, and carries no
    # pressure of its own.
    second = request_authorization(site, claim.id, requested_level="ASAM_3_1", bed_id=None)
    second = deny_authorization(site, second["id"])
    assert second["posture"] == "DENIED"
    assert second["days_used"] == 0
    assert second["urgency_score"] == 0


# ------------------------------------------------------- authorization stacking

def test_a_second_authorization_at_the_same_level_is_refused_while_one_is_live(api):
    """PRD §3.2: "A second authorization for the same episode is refused with
    `ERR_AUTHORIZATION_NOT_REOPENABLE` unless every prior authorization for that episode is
    already `DENIED`, `EXPIRED` or `EXHAUSTED`, or the new `requested_level` differs from
    every prior authorization's `requested_level`."

    Design: Difficulty/non_linear_state_machine/episode_clinical_status_reassessment_cycle
    """
    site = setup_site()
    # The episode rests in AWAITING_AUTHORIZATION holding one PENDING grant at
    # ASAM_3_5, so the state gate passes and only the stacking rule can fire.
    episode = open_episode(site)
    place_episode(site, episode["id"], scores=C.SCORES_ASAM_3_5)
    request_authorization(
        site, episode["id"], requested_level="ASAM_3_5", bed_id=site.bed_35["id"]
    )
    assert read_episode(episode["id"])["clinical_status"] == "AWAITING_AUTHORIZATION"

    from test_helpers import UTILIZATION_REVIEWER_HEADERS

    response = api.create_authorization(
        site.id,
        episode["id"],
        {"payer_id": site.payer["id"], "requested_level": "ASAM_3_5"},
        UTILIZATION_REVIEWER_HEADERS,
    )
    validate_error(response, ApiErrorId.ERR_AUTHORIZATION_NOT_REOPENABLE)


def test_a_step_down_may_not_be_appointed_before_any_days_are_burned(api):
    """PRD §3.6: "A step-down may not be appointed against an authorization whose
    `days_used` is exactly 0, or the request fails with `ERR_AUTHORIZATION_UNUSED`."

    Design: Corner/endpoints/step_up_is_conditional_on_a_complicated_withdrawal_plan
    """
    site = setup_site()
    setup = setup_admitted_episode(site=site, admit_clock=C.CLOCK_2026_09_02)

    # A fresh authorization at the target level, approved but never burnt: its
    # days_used is exactly 0, which is what the appointment rule refuses.
    from test_helpers import CLINICAL_DIRECTOR_HEADERS, read_episode as _read

    target = request_authorization(site, setup.id, requested_level="ASAM_3_1", bed_id=None)
    target = approve_authorization(site, target["id"])
    assert target["days_used"] == 0

    version = _read(setup.id)["version"]
    response = api.create_level_of_care_change(
        site.id,
        setup.id,
        {
            "authorization_id": target["id"],
            "to_level": "ASAM_3_1",
            "effective_at": C.CLOCK_2026_09_05,
            "expected_treatment_episode_version": version,
        },
        CLINICAL_DIRECTOR_HEADERS,
    )
    validate_error(response, ApiErrorId.ERR_AUTHORIZATION_UNUSED)


# ------------------------------------------- level change bound on another entity

def test_level_change_completion_waits_on_its_funding_authorization(api):
    """
    PRD §3.6: "Such a change moves directly from `PLANNED` to `COMPLETED`, but only when its
    target authorization's posture is `APPROVED`, or it is refused with
    `ERR_AUTHORIZATION_NOT_APPROVED`." PRD §3.6: "On completion the source bed moves from
    `OCCUPIED` to `CLEANING` and the target bed from `AVAILABLE` to `OCCUPIED`; the episode's
    `care_level_status` becomes `STEPPED_DOWN`; `step_down_count` increments by one;
    `revcap_pre_step_down_cents` and `revcap_post_step_down_cents` are frozen as the pre- and
    post-transition revenue-cap snapshots; and the committed bed nights drop by one through the
    forward leg of the ledger."

    Design: Difficulty/cross_entity_state_dependency/level_change_legality_bound_on_facility_ops_epoch
    """
    from test_helpers import CLINICAL_DIRECTOR_HEADERS, UTILIZATION_REVIEWER_HEADERS

    site = setup_site()
    setup = setup_accumulated_episode(
        site=site, admitted_at=C.CLOCK_2026_09_02, burn_clock=C.CLOCK_2026_09_08, burns=1
    )

    # A second authorization at the lower level funds the change, is approved, and has
    # one day burnt against it — the appointment rule refuses an authorization whose
    # days_used is exactly 0 — leaving it at CONCURRENT_REVIEW_DUE rather than APPROVED.
    target = request_authorization(site, setup.id, requested_level="ASAM_3_1", bed_id=None)
    target = approve_authorization(site, target["id"])
    set_clock("2026-09-11T00:00:00Z")
    run_ops(site.id)
    setup.refresh()
    target = read_authorization(target["id"])
    assert target["posture"] == "CONCURRENT_REVIEW_DUE"
    assert target["days_used"] == 3

    change = appoint_level_change(
        site, setup.id, target["id"], to_level="ASAM_3_1",
        effective_at="2026-09-11T00:00:00Z", bed_id=site.bed_31["id"],
    )
    assert change["status"] == "PLANNED"

    refused = api.complete_level_of_care_change(
        site.id, change["id"], {}, CLINICAL_DIRECTOR_HEADERS
    )
    error = validate_error(refused, ApiErrorId.ERR_AUTHORIZATION_NOT_APPROVED)
    assert error["error_id"] != ApiErrorId.ERR_CHANGE_NOT_DUE
    assert error["error_id"] != ApiErrorId.ERR_EPOCH_STALE

    # Extending the grant restores the APPROVED posture the completion branch requires.
    submit_concurrent_review(site, target["id"])
    completed = complete_level_change(site, change["id"])
    assert completed["status"] == "COMPLETED"

    refreshed = read_episode(setup.id)
    assert refreshed["care_level_status"] == "STEPPED_DOWN"
    assert refreshed["step_down_count"] == 1
