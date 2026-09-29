"""Boundary precision on the activation waiting period and the audit threshold.

Two boundaries of very different kinds live in this file.  The first is a
millisecond-resolution instant: PRD S3.6 makes ``activation_eligible_at``
itself the first permitted activation instant.  The second is a two-decimal
computed score: PRD S3.7 fails a new-entrant audit at exactly 40.00.  Each is
exercised one unit below the threshold, at the threshold and one unit above it.
"""

import pytest

from test_helpers import (
    ACTIVATING_OFFICER,
    ApiErrorId,
    REGISTRY_ADMIN,
    assert_operating_authority,
    assert_revocation_proceeding,
    assert_risk_score,
    assert_safety_audit,
    expected_audited_score,
    get_success_data,
    read_authority,
    record_audit,
    set_clock,
    setup_pending_authority_with_coverage,
    setup_scheduled_audit,
    validate_error,
    validate_paginated,
    validate_success,
)

PUBLICATION_AT = "2026-08-05T00:00:00.000Z"
ELIGIBLE_AT = "2026-08-26T00:00:00.000Z"
ONE_MS_EARLIER = "2026-08-25T23:59:59.999Z"
ONE_MS_LATER = "2026-08-26T00:00:00.001Z"
AUDIT_DEADLINE_AT = "2028-02-26T00:00:00.000Z"


# ---------------------------------------------------------------------------
# The activation waiting period, to the millisecond
# ---------------------------------------------------------------------------
def test_activation_one_millisecond_before_the_eligibility_instant_is_rejected(api):
    """PRD S3.4: "`publication_at` is stamped with the current logical time and
    `activation_eligible_at` is set to `publication_at` plus 21 days."
    PRD S3.6: "The waiting period must have elapsed — the current logical time
    must be at or after `activation_eligible_at`, which was stamped at
    publication as `publication_at` plus 21 days. The boundary is inclusive:
    activation at exactly `activation_eligible_at` succeeds, and one
    millisecond earlier fails with `ERR_WAITING_PERIOD_NOT_ELAPSED`."

    Design: Difficulty/boundary_precision_check/activation_at_the_exact_eligibility_instant_is_permitted
    """
    env = setup_pending_authority_with_coverage(api)

    assert env.authority["publication_at"] == PUBLICATION_AT
    assert env.authority["activation_eligible_at"] == ELIGIBLE_AT, (
        "activation_eligible_at must be publication_at plus 21 days, got "
        f"{env.authority['activation_eligible_at']}"
    )

    set_clock(api, ONE_MS_EARLIER)
    response = api.activate_authority(env.authority_id, ACTIVATING_OFFICER)
    validate_error(response, ApiErrorId.WAITING_PERIOD_NOT_ELAPSED)

    after = read_authority(api, env.authority_id)
    assert after["authority_status"] == "PENDING", (
        "a refused activation must leave the authority PENDING"
    )
    assert after["activated_at"] is None
    application = get_success_data(
        api.get_application(env.application_id, REGISTRY_ADMIN)
    )
    assert application["status"] == "PUBLISHED", (
        "the originating application must not move when activation is refused"
    )


def test_activation_at_the_exact_eligibility_instant_is_permitted(api):
    """PRD S3.6: "The waiting period must have elapsed — the current logical
    time must be at or after `activation_eligible_at`, which was stamped at
    publication as `publication_at` plus 21 days. The boundary is inclusive:
    activation at exactly `activation_eligible_at` succeeds, and one
    millisecond earlier fails with `ERR_WAITING_PERIOD_NOT_ELAPSED`."
    PRD S3.6: "The authority's `authority_status` becomes `ACTIVE`, its
    `activated_at` is stamped with the current logical time, and its
    `insurance_status` is set to `FILED`. The originating application moves
    `PUBLISHED → GRANTED`."
    PRD S3.6: "On the owning carrier, `unified_registration_status` becomes
    `REGISTERED` and `active_authority_count` increases by one."

    Design: Difficulty/boundary_precision_check/activation_at_the_exact_eligibility_instant_is_permitted
    """
    env = setup_pending_authority_with_coverage(api)
    assert env.authority["activation_eligible_at"] == ELIGIBLE_AT

    set_clock(api, "2026-08-26T00:00:00Z")
    authority = validate_success(
        api.activate_authority(env.authority_id, ACTIVATING_OFFICER)
    )
    assert_operating_authority(authority)

    assert authority["authority_status"] == "ACTIVE", (
        "activation at exactly activation_eligible_at must succeed"
    )
    assert authority["activated_at"] == ELIGIBLE_AT
    assert authority["insurance_status"] == "FILED"

    application = get_success_data(
        api.get_application(env.application_id, REGISTRY_ADMIN)
    )
    assert application["status"] == "GRANTED"

    carrier = get_success_data(api.get_carrier(env.carrier_id, REGISTRY_ADMIN))
    assert carrier["unified_registration_status"] == "REGISTERED"
    assert carrier["active_authority_count"] == 1


def test_activation_at_the_eligibility_instant_schedules_the_eighteen_month_audit(api):
    """PRD S3.6: "If the carrier's `entrant_status` is `NEW_ENTRANT` at the
    moment of activation, the authority's `new_entrant_audit_status` becomes
    `PENDING`, its `new_entrant_audit_deadline_at` is set to the audit window
    described below, and a `SafetyAudit` is created for that carrier with
    `status` `SCHEDULED`, `audit_window_opens_at` equal to the current logical
    time (that is, the authority's `activated_at`) and `audit_deadline_at`
    equal to the same window figure."
    PRD S3.6: "The audit window runs 18 calendar months from `activated_at`,
    preserving the day of month and the time of day; when the target month has
    fewer days than the source day-of-month, the deadline clamps to that
    month's last day with the time of day unchanged. Both the authority's
    `new_entrant_audit_deadline_at` and the audit's `audit_deadline_at` receive
    that instant."

    Design: Difficulty/boundary_precision_check/activation_at_the_exact_eligibility_instant_is_permitted
    """
    env = setup_pending_authority_with_coverage(api)
    set_clock(api, "2026-08-26T00:00:00Z")
    authority = validate_success(
        api.activate_authority(env.authority_id, ACTIVATING_OFFICER)
    )

    assert authority["activated_at"] == ELIGIBLE_AT
    assert authority["new_entrant_audit_status"] == "PENDING"
    assert authority["new_entrant_audit_deadline_at"] == AUDIT_DEADLINE_AT, (
        "18 calendar months from 2026-08-26T00:00:00.000Z is "
        f"{AUDIT_DEADLINE_AT}, got {authority['new_entrant_audit_deadline_at']}"
    )

    audits, meta = validate_paginated(
        api.list_carrier_safety_audits(env.carrier_id, REGISTRY_ADMIN)
    )
    assert meta["total_count"] == 1, "activation creates exactly one SafetyAudit"
    audit = assert_safety_audit(audits[0])
    assert audit["status"] == "SCHEDULED"
    assert audit["audit_window_opens_at"] == ELIGIBLE_AT
    assert audit["audit_deadline_at"] == AUDIT_DEADLINE_AT
    assert audit["result_recorded_at"] is None


def test_activation_one_millisecond_after_the_eligibility_instant_is_permitted(api):
    """PRD S3.6: "The waiting period must have elapsed — the current logical
    time must be at or after `activation_eligible_at`, which was stamped at
    publication as `publication_at` plus 21 days. The boundary is inclusive:
    activation at exactly `activation_eligible_at` succeeds, and one
    millisecond earlier fails with `ERR_WAITING_PERIOD_NOT_ELAPSED`."
    PRD S3.6: "The authority's `authority_status` becomes `ACTIVE`, its
    `activated_at` is stamped with the current logical time, and its
    `insurance_status` is set to `FILED`. The originating application moves
    `PUBLISHED → GRANTED`."

    Design: Difficulty/boundary_precision_check/activation_at_the_exact_eligibility_instant_is_permitted
    """
    env = setup_pending_authority_with_coverage(api)
    set_clock(api, ONE_MS_LATER)
    authority = validate_success(
        api.activate_authority(env.authority_id, ACTIVATING_OFFICER)
    )

    assert authority["authority_status"] == "ACTIVE"
    assert authority["activated_at"] == ONE_MS_LATER, (
        "activated_at is read from the logical clock, to the millisecond"
    )
    assert authority["insurance_status"] == "FILED"
    application = get_success_data(
        api.get_application(env.application_id, REGISTRY_ADMIN)
    )
    assert application["status"] == "GRANTED"


# ---------------------------------------------------------------------------
# The new-entrant audit failure threshold, to the second decimal
# ---------------------------------------------------------------------------
def test_audit_score_just_below_the_failure_threshold_passes_the_audit(api):
    """PRD S3.7: "the out-of-service component is `audited_oos_rate_pct`
    multiplied by 2, capped at 100; the driver component is
    `audited_driver_violation_count` multiplied by 5, capped at 100; the vehicle
    component is `audited_vehicle_defect_count` multiplied by 4, capped at 100;
    and this variant does carry a penalty, namely 12.0 points for each acute
    violation, that is 12.0 multiplied by `acute_violation_count`, added to the
    weighted sum before clamping."
    PRD S3.7: "The outcome is then decided from the already-rounded two-decimal
    `audit_score`: the audit `FAILED` when `audit_score` is at least 40.00 **or**
    when `acute_violation_count` is 1 or more, and `PASSED` otherwise. The
    threshold is inclusive, so a score of exactly 40.00 fails, and a single
    acute violation fails the audit regardless of how low the score came out."
    PRD S3.7: "On `SCHEDULED → PASSED`: the carrier's `entrant_status` becomes
    `PERMANENT`, and every `OperatingAuthority` of that carrier whose
    `new_entrant_audit_status` is `PENDING`, walked in `created_at` ascending
    order, moves to `PASSED`. Nothing is suspended and no proceeding opens."

    Design: Difficulty/boundary_precision_check/audit_score_exactly_at_the_failure_threshold_fails_the_audit
    """
    env = setup_scheduled_audit(api)
    assert expected_audited_score(19.99, 10, 7, 0) == 39.99

    env = record_audit(
        api,
        env,
        audited_oos_rate_pct=19.99,
        audited_driver_violation_count=10,
        audited_vehicle_defect_count=7,
        acute_violation_count=0,
    )

    audit = assert_safety_audit(env.audit)
    assert_risk_score(audit["audit_score"], 39.99)
    assert audit["status"] == "PASSED", (
        "39.99 is below the inclusive 40.00 threshold, so the audit passes"
    )

    assert env.carrier["entrant_status"] == "PERMANENT"
    assert_risk_score(env.carrier["compliance_risk_score"], 39.99)
    assert env.carrier["compliance_risk_variant"] == "AUDITED"

    assert env.authority["new_entrant_audit_status"] == "PASSED"
    assert env.authority["authority_status"] == "ACTIVE", (
        "nothing is suspended when the audit passes"
    )
    assert env.authority["suspension_reason"] == "NONE"

    proceedings, meta = validate_paginated(
        api.list_authority_proceedings(env.authority_id, REGISTRY_ADMIN)
    )
    assert meta["total_count"] == 0, "no proceeding opens on a passed audit"
    assert proceedings == []


def test_audit_score_exactly_at_the_failure_threshold_fails_the_audit(api):
    """PRD S3.7: "The outcome is then decided from the already-rounded
    two-decimal `audit_score`: the audit `FAILED` when `audit_score` is at least
    40.00 **or** when `acute_violation_count` is 1 or more, and `PASSED`
    otherwise. The threshold is inclusive, so a score of exactly 40.00 fails,
    and a single acute violation fails the audit regardless of how low the score
    came out."
    PRD S3.7: "The result is written to the audit's `audit_score`, and the same
    figure is written to the carrier's `compliance_risk_score` with
    `compliance_risk_variant` set to `AUDITED`; the carrier's
    `audited_oos_rate_pct` is set to the submitted `audited_oos_rate_pct`."

    Design: Difficulty/boundary_precision_check/audit_score_exactly_at_the_failure_threshold_fails_the_audit
    """
    env = setup_scheduled_audit(api)
    assert expected_audited_score(20.0, 10, 7, 0) == 40.00

    env = record_audit(
        api,
        env,
        audited_oos_rate_pct=20.0,
        audited_driver_violation_count=10,
        audited_vehicle_defect_count=7,
        acute_violation_count=0,
    )

    audit = assert_safety_audit(env.audit)
    assert_risk_score(audit["audit_score"], 40.00)
    assert audit["status"] == "FAILED", (
        "the threshold is inclusive: a score of exactly 40.00 fails"
    )
    assert audit["result_recorded_at"] == ELIGIBLE_AT

    assert_risk_score(env.carrier["compliance_risk_score"], 40.00)
    assert env.carrier["compliance_risk_variant"] == "AUDITED"
    assert env.carrier["audited_oos_rate_pct"] == pytest.approx(20.0)
    assert env.carrier["entrant_status"] == "NEW_ENTRANT", (
        "a failed audit leaves the carrier a new entrant"
    )


def test_audit_failure_at_the_threshold_suspends_and_opens_a_proceeding(api):
    """PRD S3.7: "On `SCHEDULED → FAILED`: the carrier's `entrant_status`
    **stays** `NEW_ENTRANT`, every `OperatingAuthority` of that carrier whose
    `new_entrant_audit_status` is `PENDING`, in `created_at` ascending order,
    moves to `FAILED`, and then for each of those authorities whose
    `authority_status` is `ACTIVE` — again in `created_at` ascending order — a
    `RevocationProceeding` is opened with `reason` `SAFETY_AUDIT_FAILURE`,
    `status` `NOTICE_ISSUED`, `notice_issued_at` at the current logical time and
    `cure_deadline_at` 30 days later, and the suspension cascade of §2.10 runs
    against that authority with `suspension_reason` `SAFETY_AUDIT_FAILURE`."
    PRD S2.10: "Hop one sets the authority's `authority_status` to `SUSPENDED`,
    sets `suspended_at` to the current logical time, and sets
    `suspension_reason` to the defect that caused it — one of `INSURANCE_LAPSE`,
    `DESIGNATION_GAP`, `SAFETY_AUDIT_FAILURE` or `AUDIT_WINDOW_MISSED`."

    Design: Difficulty/boundary_precision_check/audit_score_exactly_at_the_failure_threshold_fails_the_audit
    """
    env = setup_scheduled_audit(api)
    env = record_audit(
        api,
        env,
        audited_oos_rate_pct=20.0,
        audited_driver_violation_count=10,
        audited_vehicle_defect_count=7,
        acute_violation_count=0,
    )
    assert_risk_score(env.audit["audit_score"], 40.00)
    assert env.audit["status"] == "FAILED"

    assert env.authority["new_entrant_audit_status"] == "FAILED"
    assert env.authority["authority_status"] == "SUSPENDED"
    assert env.authority["suspension_reason"] == "SAFETY_AUDIT_FAILURE"
    assert env.authority["suspended_at"] == ELIGIBLE_AT
    assert env.authority["active_contract_count"] == 0
    assert env.authority["suspended_contract_count"] == 0

    proceedings, meta = validate_paginated(
        api.list_authority_proceedings(env.authority_id, REGISTRY_ADMIN)
    )
    assert meta["total_count"] == 1
    proceeding = assert_revocation_proceeding(proceedings[0])
    assert proceeding["reason"] == "SAFETY_AUDIT_FAILURE"
    assert proceeding["status"] == "NOTICE_ISSUED"
    assert proceeding["notice_issued_at"] == ELIGIBLE_AT
    assert proceeding["cure_deadline_at"] == "2026-09-25T00:00:00.000Z", (
        "cure_deadline_at is exactly 30 days after notice_issued_at"
    )
    assert proceeding["cured_at"] is None
    assert proceeding["revoked_at"] is None


def test_audit_score_just_above_the_failure_threshold_fails_the_audit(api):
    """PRD S3.7: "The outcome is then decided from the already-rounded
    two-decimal `audit_score`: the audit `FAILED` when `audit_score` is at least
    40.00 **or** when `acute_violation_count` is 1 or more, and `PASSED`
    otherwise. The threshold is inclusive, so a score of exactly 40.00 fails,
    and a single acute violation fails the audit regardless of how low the score
    came out."

    Design: Difficulty/boundary_precision_check/audit_score_exactly_at_the_failure_threshold_fails_the_audit
    """
    env = setup_scheduled_audit(api)
    assert expected_audited_score(20.01, 10, 7, 0) == 40.01

    env = record_audit(
        api,
        env,
        audited_oos_rate_pct=20.01,
        audited_driver_violation_count=10,
        audited_vehicle_defect_count=7,
        acute_violation_count=0,
    )

    assert_risk_score(env.audit["audit_score"], 40.01)
    assert env.audit["status"] == "FAILED"
    assert env.carrier["entrant_status"] == "NEW_ENTRANT"
    assert env.authority["new_entrant_audit_status"] == "FAILED"
    assert env.authority["authority_status"] == "SUSPENDED"
    assert env.authority["suspension_reason"] == "SAFETY_AUDIT_FAILURE"
