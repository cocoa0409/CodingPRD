"""Medical clearance windows and the admission gate."""

import datetime

import pytest

from test_helpers import (
    C,
    INTAKE_NURSE_HEADERS,
    ApiErrorId,
    author_withdrawal_management,
    clear_clearance,
    order_clearance,
    read_clearance,
    read_episode,
    draft_plan,
    setup_staged_episode,
    setup_site,
    submit_plan_for_cosign,
    validate_error,
    validate_success,
)


def _push_clearance_clock(hours_before_expiry):
    """Move the logical clock to ``hours_before_expiry`` integer hours before an
    expiry instant that sits at 2026-09-08T00:00:00Z."""
    expiry = datetime.datetime(2026, 9, 8)
    instant = expiry - datetime.timedelta(hours=hours_before_expiry)
    return instant.strftime("%Y-%m-%dT%H:%M:%SZ")


def test_clearance_hours_and_days_round_in_the_pinned_order(api):
    """
    PRD §3.3: "First, the exact number of hours between `expires_at` and the logical now is
    taken as a decimal and may be negative; that figure is floored at 0 and then rounded half up
    to a whole number of hours. That whole-hour figure is `window_hours_remaining`. Only then is
    `window_days_remaining` derived, by dividing the *already-rounded* hour figure by 24 and
    rounding half up to a whole number." PRD §3.3: "The two orders disagree: an exact delta of
    35.7 hours rounds to 36 whole hours, and 36 divided by 24 is 1.5, which rounds half up to 2
    days; dividing 35.7 by 24 first gives 1.4875, which rounds to 1 day."

    Design: Difficulty/combinatorial_formula/clearance_window_nested_rounding_order
    """
    from test_helpers import set_clock

    site = setup_site()
    claim = setup_staged_episode(site=site)
    clearance = order_clearance(site, claim.id, "TB_SCREEN")

    set_clock("2026-09-01T00:00:00Z")
    clear_clearance(site, clearance["id"])

    # expires_at is cleared_at + 7 days. Move the clock to leave 35.7 hours.
    set_clock(_push_clearance_clock(35.7))
    stored = read_clearance(site.id, claim.id, clearance["id"])

    assert stored["status"] == "CLEARED"
    assert stored["window_hours_remaining"] == 36, "35.7 hours rounds half up to 36"
    assert stored["window_days_remaining"] == 2, (
        "the pinned order divides the ALREADY-ROUNDED 36 hours by 24; the rejected opposite "
        "order would divide 35.7 first and report 1"
    )


def test_a_clearance_at_exactly_zero_hours_reads_expired(api):
    """PRD §3.3: "A clearance whose raw status is `CLEARED` reads as `CLEARED` while
    `window_hours_remaining` is strictly greater than 0, and reads as `EXPIRED` when
    `window_hours_remaining` is exactly 0."
    PRD §3.3: "a clearance whose `expires_at` coincides exactly with the logical now reads
    `EXPIRED` rather than `CLEARED`."

    Design: Difficulty/combinatorial_formula/clearance_window_nested_rounding_order
    """
    from test_helpers import set_clock

    site = setup_site()
    claim = setup_staged_episode(site=site)
    clearance = order_clearance(site, claim.id, "TB_SCREEN")

    set_clock("2026-09-01T00:00:00Z")
    clear_clearance(site, clearance["id"])

    set_clock("2026-09-08T00:00:00Z")  # exactly the expiry instant
    stored = read_clearance(site.id, claim.id, clearance["id"])

    assert stored["status"] == "CLEARED", "the raw status is untouched"
    assert stored["window_hours_remaining"] == 0
    assert stored["window_days_remaining"] == 0
    assert stored["effective_status"] == "EXPIRED"


def test_admission_is_refused_when_the_tb_window_has_closed(api):
    """PRD §3.3: "The `TB_SCREEN` clearance's `expires_at` must be strictly after the logical
    now, and a lapse is reported as `ERR_MEDICAL_CLEARANCE_EXPIRED` with HTTP 410."

    Design: Difficulty/combinatorial_formula/clearance_window_nested_rounding_order
    """
    from test_helpers import INTAKE_NURSE_HEADERS, set_clock

    site = setup_site()
    claim = setup_staged_episode(site=site)
    tb = order_clearance(site, claim.id, "TB_SCREEN")

    set_clock("2026-09-01T00:00:00Z")
    clear_clearance(site, tb["id"])
    set_clock("2026-09-08T00:00:00Z")

    response = api.admit_episode(site.id, claim.id, {}, INTAKE_NURSE_HEADERS)
    validate_error(response, ApiErrorId.ERR_MEDICAL_CLEARANCE_EXPIRED, 410)


def test_the_clearance_hour_boundary_separates_expired_from_cleared(api):
    """PRD §3.3: "reads as `CLEARED` while `window_hours_remaining` is strictly greater
    than 0, and reads as `EXPIRED` when `window_hours_remaining` is exactly 0."

    Design: Difficulty/boundary_precision_check/boundary_curriculum_exact_requirement_plus_clearance_zero
    """
    from test_helpers import set_clock

    site = setup_site()
    claim = setup_staged_episode(site=site)
    clearance = order_clearance(site, claim.id, "TB_SCREEN")
    set_clock("2026-09-01T00:00:00Z")
    clear_clearance(site, clearance["id"])

    set_clock(_push_clearance_clock(1))
    alive = read_clearance(site.id, claim.id, clearance["id"])
    assert alive["window_hours_remaining"] == 1
    assert alive["effective_status"] == "CLEARED", "one hour of validity is still CLEARED"

    set_clock("2026-09-08T00:00:00Z")
    lapsed = read_clearance(site.id, claim.id, clearance["id"])
    assert lapsed["window_hours_remaining"] == 0
    assert lapsed["effective_status"] == "EXPIRED"


def test_admission_waits_on_a_cleared_tb_screen_from_another_entity(api):
    """
    PRD §3.3: "The episode must hold at least one `MEDICAL` clearance reading `CLEARED` and at
    least one `TB_SCREEN` clearance whose `effective_status` is `CLEARED`; a clearance that is
    not cleared is reported as `ERR_MEDICAL_CLEARANCE_NOT_CLEARED`." PRD §3.3: "On success the
    episode's `admitted_at` is stamped, `clinical_status` becomes `IN_TREATMENT`,
    `care_level_status` moves from `NOT_STARTED` to `ACTIVE`, and the episode's version
    advances."

    Design: Difficulty/cross_entity_state_dependency/admission_gated_on_authorization_days_and_clearance_effective_status
    """
    from test_helpers import clear_clearance as _clear, order_clearance as _order

    site = setup_site()
    # A single-clearance episode: only MEDICAL is recorded, so the episode is one
    # clearance short of the approval's promotion test and rests in AWAITING_AUTHORIZATION.
    from test_helpers import open_episode, place_episode, request_authorization, approve_authorization

    episode = open_episode(site, patient_ref="PT-8002")
    place_episode(site, episode["id"], scores=C.SCORES_ASAM_3_5)
    auth = request_authorization(
        site, episode["id"], requested_level="ASAM_3_5", bed_id=site.beds["ASAM_3_5"]["id"]
    )
    _clear(site, _order(site, episode["id"], "MEDICAL")["id"])
    approve_authorization(site, auth["id"])

    _clear(site, _order(site, episode["id"], "TB_SCREEN")["id"])
    assert read_episode(episode["id"])["clinical_status"] == "AWAITING_ADMISSION"

    author_withdrawal_management(site, episode["id"])
    plan = draft_plan(site, episode["id"])
    submit_plan_for_cosign(site, plan["id"])

    # The admission gate reads the MEDICAL and TB_SCREEN pair the PRD names; a
    # PSYCHIATRIC clearance ordered alongside them is not one of the two conditions,
    # so admitting succeeds while it is still PENDING.
    _order(site, episode["id"], "PSYCHIATRIC")
    admitted = validate_success(
        api.admit_episode(site.id, episode["id"], {}, INTAKE_NURSE_HEADERS), 200
    )
    assert admitted["clinical_status"] == "IN_TREATMENT"
    assert admitted["care_level_status"] == "ACTIVE"


def test_a_lapsed_state_license_blocks_the_next_authorization(api):
    """PRD §3.1: "A facility must hold a `GRANTED`, unexpired `STATE_LICENSE` accreditation
    for its own `state_code` before any assessment, authorization request, admission or
    level-of-care change may proceed; without it the request fails with
    `ERR_FACILITY_NOT_LICENSED`."
    PRD §3.9: "when a `STATE_LICENSE` expires the facility drops to `ASAM_1_0` and stops
    accepting admissions."

    Design: Corner/validations/license_expiry_is_detected_before_an_admission_is_attempted
    """
    from test_helpers import (UTILIZATION_REVIEWER_HEADERS, open_episode, place_episode,
                              read_facility, run_ops, set_clock, setup_site as _site)

    site = _site()
    episode = open_episode(site)
    place_episode(site, episode["id"], scores=C.SCORES_ASAM_3_5)

    # The site's own licence is the one that governs it, so it is the row that lapses:
    # granting a second, short-lived licence under the same class is not permitted for
    # the same granting body, and the facility remains licensed through the original.
    from test_helpers import revoke_accreditation

    set_clock(C.CLOCK_2026_09_15)
    revoke_accreditation(site.id, site.accreditations["STATE_LICENSE"]["id"])
    run_ops(site.id)

    facility = read_facility(site.id)
    assert facility["licensed"] is False, "the licence is gone, so the facility is unlicensed"

    response = api.create_authorization(
        site.id,
        episode["id"],
        {"payer_id": site.payer["id"], "requested_level": "ASAM_3_5"},
        UTILIZATION_REVIEWER_HEADERS,
    )
    error = validate_error(response, ApiErrorId.ERR_FACILITY_NOT_LICENSED)
    assert error["error_id"] != ApiErrorId.ERR_LEVEL_EXCEEDS_FACILITY_LICENSE


def test_admission_runs_the_clearance_checks_before_the_fiscal_days_check(api):
    """PRD §3.3: "The `TB_SCREEN` clearance's `expires_at` must be strictly after the logical
    now, and a lapse is reported as `ERR_MEDICAL_CLEARANCE_EXPIRED` with HTTP 410."
    PRD §3.3: "The authorization's `days_remaining` must be strictly greater than 0, reported
    as `ERR_AUTHORIZATION_DAYS_EXHAUSTED` (HTTP 402)."

    Design: Corner/validations/admit_runs_clearance_checks_before_the_fiscal_days_check
    """
    from test_helpers import set_clock

    site = setup_site()
    claim = setup_staged_episode(site=site)
    tb = order_clearance(site, claim.id, "TB_SCREEN")

    set_clock("2026-09-01T00:00:00Z")
    clear_clearance(site, tb["id"])
    set_clock("2026-09-08T00:00:00Z")  # the TB window has closed

    response = api.admit_episode(site.id, claim.id, {}, INTAKE_NURSE_HEADERS)
    error = validate_error(response, ApiErrorId.ERR_MEDICAL_CLEARANCE_EXPIRED, 410)
    assert error["error_id"] != ApiErrorId.ERR_AUTHORIZATION_DAYS_EXHAUSTED


def test_the_safety_priority_beats_the_fiscal_priority_on_one_admission(api):
    """
    PRD §3.3: "A facility whose `facility_posture` is `FROZEN` refuses admission with
    `ERR_FACILITY_POSTURE_FROZEN`, and a `ClinicalDirector` who has already performed a gated
    utilization step on the episode is refused with `ERR_SEGREGATION_OF_DUTIES_VIOLATION`." PRD
    §2.7a: "A request that would violate several rules is therefore reported against the
    earliest one in this sequence."

    Design: Difficulty/priority_pair_validation_conflict/priority_conflict_safety_vs_fiscal_on_admit
    """
    from test_helpers import (create_facility, grant_accreditation, run_ops, set_clock,
                              setup_staged_episode, read_facility)

    site = setup_site()
    claim = setup_staged_episode(site=site)

    # Drive the site to FROZEN: three lapsed rows, both missing classes.
    for body in ("CARF-2", "JCAHO", "COA"):
        grant_accreditation(
            site.id, accreditation_class="ACCREDITATION_BODY",
            granting_body=body, expires_at="2026-01-01T00:00:00Z",
        )
    run_ops(site.id)
    assert read_facility(site.id)["facility_posture"] == "FROZEN"

    response = api.admit_episode(site.id, claim.id, {}, INTAKE_NURSE_HEADERS)
    error = validate_error(response, ApiErrorId.ERR_FACILITY_POSTURE_FROZEN, 409)
    assert error["error_id"] != ApiErrorId.ERR_MEDICAL_CLEARANCE_EXPIRED
    assert error["error_id"] != ApiErrorId.ERR_AUTHORIZATION_DAYS_EXHAUSTED


def test_admission_is_an_unauthorized_operation_for_a_utilization_reviewer(api):
    """
    PRD §2.1: "A request whose role is not permitted on the targeted operation, or whose
    `X-User-ID` fails to resolve where the role demands a persisted identity, is rejected with
    `ERR_INSUFFICIENT_PERMISSIONS`." PRD §2.1: "`AdmissionsIntakeNurse` opens episodes, starts
    assessments, orders clearances and performs the admission itself."

    Design: Corner/validations/utilization_reviewer_cannot_approve_its_own_concurrent_review_then_admit
    """
    from test_helpers import UTILIZATION_REVIEWER_HEADERS

    site = setup_site()
    claim = setup_staged_episode(site=site)

    response = api.admit_episode(site.id, claim.id, {}, UTILIZATION_REVIEWER_HEADERS)
    validate_error(response, ApiErrorId.ERR_INSUFFICIENT_PERMISSIONS, 403)
    assert read_episode(claim.id)["clinical_status"] == "AWAITING_ADMISSION"


def test_a_missing_user_context_header_is_reported_first(api):
    """
    PRD §2.1: "A request missing either header, or carrying an `X-User-Role` that does not name
    one of the roles declared below, is rejected with `ERR_MISSING_USER_CONTEXT_HEADER`." PRD
    §2.7a: "Identity comes first: header presence and role membership are settled before
    anything else, and a request that fails there is never evaluated further."

    Design: Corner/validations/admit_without_user_context_headers_returns_missing_header
    """
    from test_helpers import make_headers

    site = setup_site()
    claim = setup_staged_episode(site=site)

    response = api.admit_episode(site.id, claim.id, {}, make_headers("intake-1", "WardClerk"))
    error = validate_error(response, ApiErrorId.ERR_MISSING_USER_CONTEXT_HEADER, 400)
    assert error["error_id"] != ApiErrorId.ERR_INSUFFICIENT_PERMISSIONS
