"""Remaining design-index targets: cascades, priority conflicts and ledger edges."""

import pytest

from test_helpers import (
    C,
    CLINICAL_DIRECTOR_HEADERS,
    INTAKE_NURSE_HEADERS,
    ApiErrorId,
    grant_accreditation,
    list_episode_changes,
    list_episode_sessions,
    open_episode,
    read_assessment,
    read_episode,
    read_facility,
    read_plan,
    run_ops,
    schedule_session,
    set_clock,
    setup_claimed_episode,
    setup_site,
    setup_staged_episode,
    validate_error,
)


def test_a_frozen_run_demotes_the_plan_and_cancels_the_scheduled_sessions(api):
    """PRD §3.9: "An episode already `IN_TREATMENT` at a facility that loses its
    `ACCREDITATION_BODY` standing — a revocation or an expiry — has its treatment plan forced to
    `PENDING_COSIGN` and every `SCHEDULED` session row rewritten to `CANCELLED` with a
    replacement scheduled, which is precisely the situation stage four of the ops cycle handles
    when the facility's posture lands at `FROZEN`." PRD §3.5: "When `facility_posture` is
    `FROZEN`, every `IN_TREATMENT` episode's treatment plan is forced to `PENDING_COSIGN` and
    every `SCHEDULED` session row for those episodes is rewritten to `CANCELLED`, with a
    replacement row scheduled for each — the compensating leg of the attendance ledger, which
    must leave `therapy_revenue_cents` exactly where it stood before."

    Design: Difficulty/transitive_cascade/cascade_site_expiry_to_stale_authorization_to_stepdown
    """
    from test_helpers import (admit_episode, draft_plan, setup_admitted_episode,
                              submit_plan_for_cosign)

    # Four lapsed ACCREDITATION_BODY rows (48 raw) plus the absent RECOVERY_HOUSE class
    # (5 raw) give a raw 53, which is the HI tier at 1.25 and stores 66 points.
    site = setup_site(
        clock=C.CLOCK_2026_09_02,
        body_accreditation_expires_at=C.CLOCK_2026_09_15,
        extra_body_accreditations=("JCAHO", "COA", "TJC"),
    )
    setup = setup_admitted_episode(site=site, admit_clock=C.CLOCK_2026_09_02)
    sessions = [
        schedule_session(site, setup.id, scheduled_at="2026-09-16T09:00:00Z"),
        schedule_session(site, setup.id, scheduled_at="2026-09-17T09:00:00Z"),
    ]

    set_clock(C.CLOCK_2026_09_15)
    run_ops(site.id)

    facility = read_facility(site.id)
    assert facility["compliance_risk_points"] == 66
    assert facility["facility_posture"] == "FROZEN"

    assert read_plan(setup.plan_id)["status"] == "PENDING_COSIGN"
    rows, _ = list_episode_sessions(site.id, setup.id, limit=100)
    scheduled_ids = {s["id"] for s in sessions}
    assert all(
        r["status"] == "CANCELLED" for r in rows if r["id"] in scheduled_ids
    ), "every scheduled row is rewritten to CANCELLED"
    assert read_episode(setup.id)["clinical_status"] == "IN_TREATMENT"


def test_a_frozen_posture_outranks_a_lapsed_clearance_on_admission(api):
    """PRD §3.3: "A facility whose `facility_posture` is `FROZEN` refuses admission with
    `ERR_FACILITY_POSTURE_FROZEN`, and a `ClinicalDirector` who has already performed a gated
    utilization step on the episode is refused with `ERR_SEGREGATION_OF_DUTIES_VIOLATION`." PRD
    §3.3: "The `TB_SCREEN` clearance's `expires_at` must be strictly after the logical now, and
    a lapse is reported as `ERR_MEDICAL_CLEARANCE_EXPIRED` with HTTP 410."

    Design: Difficulty/priority_pair_validation_conflict/priority_conflict_safety_vs_fiscal_on_admit
    """
    site = setup_site()
    claim = setup_claimed_episode(site=site)

    for body in ("CARF-X", "JCAHO-X", "COA-X"):
        grant_accreditation(
            site.id, accreditation_class="ACCREDITATION_BODY",
            granting_body=body, expires_at="2026-01-01T00:00:00Z",
        )
    run_ops(site.id)
    assert read_facility(site.id)["facility_posture"] == "FROZEN"

    # The clearance window is closed at the same instant.
    set_clock("2026-09-08T00:00:00Z")
    response = api.admit_episode(site.id, claim.id, {}, INTAKE_NURSE_HEADERS)
    error = validate_error(response, ApiErrorId.ERR_FACILITY_POSTURE_FROZEN, 409)
    assert error["error_id"] != ApiErrorId.ERR_MEDICAL_CLEARANCE_EXPIRED


def test_the_state_rule_answers_before_the_referential_route_rule(api):
    """PRD §3.6: "Level-of-Care Changes: Stepping Down and Stepping Up A `ClinicalDirector` or
    `UtilizationReviewer` appoints a level-of-care change against an episode that is
    `IN_TREATMENT`, supplying the `authorization_id` funding the target level, the `to_level`,
    the `effective_at` instant, the required `expected_treatment_episode_version`, and
    optionally a `bed_id`." PRD §2.7a: "Only after all of that do the state and posture rules
    run"

    Design: Difficulty/priority_pair_validation_conflict/priority_conflict_referential_vs_state_on_step_down
    """
    site = setup_site()
    claim = setup_staged_episode(site=site)
    assert read_episode(claim.id)["clinical_status"] == "AWAITING_ADMISSION"

    version = read_episode(claim.id)["version"]
    response = api.create_level_of_care_change(
        site.id,
        claim.id,
        {
            "authorization_id": claim.auth_id,
            "to_level": "ASAM_2_1",
            "effective_at": C.CLOCK_2026_09_05,
            "expected_treatment_episode_version": version,
        },
        CLINICAL_DIRECTOR_HEADERS,
    )
    error = validate_error(response, ApiErrorId.ERR_EPISODE_NOT_IN_TREATMENT, 409)
    assert error["error_id"] != ApiErrorId.ERR_LEVEL_ROUTE_NOT_ALLOWED
    assert error["error_id"] != ApiErrorId.ERR_LEVEL_EXCEEDS_FACILITY_LICENSE

    changes, _ = list_episode_changes(site.id, claim.id)
    assert changes == []


def test_a_refused_level_change_leaves_the_row_planned_for_a_later_retry(api):
    """PRD §3.6: "A change that is not in `PLANNED` status is refused with
    `ERR_CHANGE_NOT_PLANNED`." PRD §3.6: "Such a change moves directly from `PLANNED` to
    `COMPLETED`, but only when its target authorization's posture is `APPROVED`, or it is
    refused with `ERR_AUTHORIZATION_NOT_APPROVED`."

    Design: Difficulty/cross_entity_state_dependency/level_change_legality_bound_on_facility_ops_epoch
    """
    from test_helpers import (
        appoint_level_change, approve_authorization, complete_level_change, read_authorization,
        read_change, request_authorization, run_ops, set_clock, setup_accumulated_episode,
        submit_concurrent_review,
    )

    site = setup_site()
    setup = setup_accumulated_episode(
        site=site, admitted_at=C.CLOCK_2026_09_02, burn_clock=C.CLOCK_2026_09_08, burns=1
    )
    # The funding authorization is burnt enough to clear the unused-days rule, but its
    # posture is still PENDING, so the completion branch refuses it.
    # The funding authorization is approved and then burnt by an ops run, which turns
    # it to CONCURRENT_REVIEW_DUE — used days, but no longer APPROVED — while the
    # appointment rule's unused-days precondition is satisfied.
    target = request_authorization(site, setup.id, requested_level="ASAM_3_1", bed_id=None)
    target = approve_authorization(site, target["id"])
    set_clock("2026-09-11T00:00:00Z")
    run_ops(site.id)
    setup.refresh()
    target = read_authorization(target["id"])
    assert target["days_used"] > 0 and target["posture"] != "APPROVED"

    change = appoint_level_change(
        site, setup.id, target["id"], to_level="ASAM_3_1",
        effective_at="2026-09-11T00:00:00Z", bed_id=site.bed_31["id"],
    )
    assert change["status"] == "PLANNED"

    refused = api.complete_level_of_care_change(
        site.id, change["id"], {}, CLINICAL_DIRECTOR_HEADERS
    )
    validate_error(refused, ApiErrorId.ERR_AUTHORIZATION_NOT_APPROVED)
    assert read_change(change["id"])["status"] == "PLANNED", (
        "the refused completion performs no mutation, so the row can be retried"
    )

    submit_concurrent_review(site, target["id"])
    assert complete_level_change(site, change["id"])["status"] == "COMPLETED"


def test_a_completed_assessment_returns_the_episode_for_re_assessment_when_cancelled(api):
    """PRD §3.1: "The floor reading is reachable in normal operation. An assessment is created
    under the default reading, completed — which places the episode — and then cancelled,
    returning the episode to `AWAITING_ASSESSMENT` with the original `dimension_scores` intact; it is then re-created with the same scores and a `placement_basis` of `HIGHEST_DIMENSION_FLOOR`."
    PRD §3.1: "Both assessment rows are then readable side by side, one recording each reading."

    Design: Corner/state_machines/assessment_cancel_from_completed_returns_assessment_not_in_progress
    """
    from test_helpers import cancel_assessment, complete_assessment, start_assessment

    site = setup_site()
    episode = open_episode(site)
    scores = C.SCORES_ASAM_3_5
    assessment = start_assessment(site, episode["id"], scores=scores)
    complete_assessment(site, assessment["id"])

    # The cancelling director reverts the episode, but the placement's own inputs survive and
    # the audit row is never deleted (PRD §2.10's retention principle).
    cancel_assessment(site, assessment["id"], headers=CLINICAL_DIRECTOR_HEADERS)

    stored = read_assessment(site.id, episode["id"], assessment["id"])
    assert stored["dimension_scores"] == scores, (
        "the original dimension_scores are intact for the second reading"
    )
    assert stored["status"] in ("CANCELLED", "SUPERSEDED")
    assert read_episode(episode["id"])["clinical_status"] == "AWAITING_ASSESSMENT"


def test_the_compliance_tier_boundary_at_exactly_ten_raw_points_is_the_base_tier(api):
    """PRD §2.6: "the `BASE` tier applies at 10 raw points or fewer."
    PRD §2.6: "exactly 10 lands `BASE`; the multiplier is applied to the raw score as a whole"
    PRD §2.6: "`FROZEN` applies at 45 or more compliance risk points"

    Design: Corner/calculations/compliance_risk_tier_boundary_is_strictly_greater_than
    """
    from test_helpers import create_facility

    set_clock(C.CLOCK_2026_09_01)
    facility = create_facility()
    # A GRANTED, unexpired ACCREDITATION_BODY leaves RECOVERY_HOUSE and STATE_LICENSE absent:
    # raw = 0 lapsed rows * 12 + 2 missing classes * 5 + 0 aged = exactly 10, the BASE boundary.
    grant_accreditation(facility["id"], accreditation_class="ACCREDITATION_BODY",
                        granting_body="CARF", expires_at=C.CREDENTIAL_EXPIRES_AT)

    run_ops(facility["id"])
    after = read_facility(facility["id"])

    assert after["compliance_risk_points"] == 10, (
        "the strictly-greater-than boundary keeps a raw 10 in the BASE tier, where the "
        "multiplier is 1.0, so the stored score equals the raw score"
    )
    assert after["facility_posture"] == "OPEN", "10 points sits far below the 45 cut"
