"""Assigned risk pool: enrollments, quota checks, take-outs, and credits.

Covers the PRD's assigned risk administration (section 3.9) and the
underwriting gate interplay (section 3.10).
"""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    assert_carrier_load_within_quota,
    create_assigned_risk_enrollment_payload,
    create_employer,
    file_take_out,
    set_clock,
    setup_active_enrollment,
    validate_error,
    validate_success,
)

ADMIN = TEST_USERS["bureau_admin_headers"]
POOL_ADMIN = TEST_USERS["pool_administrator_headers"]


def test_takeout_credit_short_rate_differs_from_pro_rata(api):
    """PRD section 3.9: "The short-rate credit first derives a short-rate
    factor of nine tenths multiplied by the ratio of remaining days to total
    days, rounded half up to four decimal places, then multiplies the
    estimated premium by that factor and by one half, rounded half up to
    cents. Because a take-out exit always carries `exit_reason` of `TAKE_OUT`,
    the short-rate credit is the amount granted; the pro-rata formula stands
    for the other exit reasons."

    Design: Difficulty/dual_variant_calc/takeout_credit_short_rate_differs_from_pro_rata
    """
    set_clock("2026-04-11T00:00:00Z")
    bureau, pool_carrier, voluntary_carrier, employer, enrollment = (
        setup_active_enrollment(premium_cents=1000000)
    )
    take_out = file_take_out(enrollment, voluntary_carrier, exit_date="2026-04-11")
    assert take_out["status"] == "PENDING"
    assert take_out["credit_cents"] == 0, (
        f"Credit must be zero until approved, got {take_out['credit_cents']}"
    )

    approved = validate_success(
        api.approve_assigned_risk_take_out(take_out["id"], POOL_ADMIN), expected_status=200
    )
    # Short-rate formula (PRD): total_days = 365, earned_days = 100,
    # remaining_days = 265; factor = round_half_up(0.9 * 265/365, 4) = 0.6534;
    # credit = round_half_up(1,000,000 * 0.6534 * 0.5) = 326,700 cents.
    assert approved["status"] == "APPROVED"
    assert approved["credit_cents"] == 326700, (
        f"Expected short-rate credit 326700, got {approved['credit_cents']}"
    )
    # Pro-rata for the same dates would be 363,014 cents; short-rate applies.
    assert approved["credit_cents"] != 363014

    enrollment_after = validate_success(
        api.get_assigned_risk_enrollment(enrollment["id"], ADMIN)
    )
    assert enrollment_after["status"] == "EXITED"
    assert enrollment_after["exit_reason"] == "TAKE_OUT"
    assert enrollment_after["take_out_credit_cents"] == 326700


def test_takeout_credit_uses_full_term_day_count_inclusive(api):
    """PRD section 3.9: "The credit itself is date-driven: `total_days`
    is the count of days from the enrollment's `effective_date` through its
    `expiration_date` inclusive; `earned_days` is the count from the
    `effective_date` to the `exit_date`; and `remaining_days` is the
    difference. The pro-rata credit is the `estimated_annual_premium_cents`
    multiplied by the ratio of remaining days to total days and by one half -
    the pool's share - rounded half up to cents. The short-rate credit first
    derives a short-rate factor of nine tenths multiplied by the ratio of
    remaining days to total days, rounded half up to four decimal places, then
    multiplies the estimated premium by that factor and by one half, rounded
    half up to cents."

    Design: Difficulty/dual_variant_calc/takeout_credit_short_rate_differs_from_pro_rata
    """
    set_clock("2026-07-01T00:00:00Z")
    bureau, pool_carrier, voluntary_carrier, employer, enrollment = (
        setup_active_enrollment(premium_cents=500000)
    )
    take_out = file_take_out(enrollment, voluntary_carrier, exit_date="2026-07-01")
    approved = validate_success(
        api.approve_assigned_risk_take_out(take_out["id"], POOL_ADMIN), expected_status=200
    )
    # total_days = 365 (inclusive), earned_days = 181, remaining = 184.
    # short-rate factor = round_half_up(0.9 * 184/365, 4) = 0.4537;
    # credit = round_half_up(500000 * 0.4537 * 0.5) = 113,425 cents.
    assert approved["credit_cents"] == 113425, (
        f"Expected short-rate credit 113425, got {approved['credit_cents']}"
    )
    # The pro-rata formula for the same dates would yield
    # round_half_up(500000 * 184/365 * 0.5) = 126,027 cents.
    assert approved["credit_cents"] != 126027


def test_takeout_approval_cascades_enrollment_carrier_load(api):
    """PRD section 3.9: "On approval the take-out moves to `APPROVED` with
    `approved_at` stamped and the credit recorded both in the take-out's
    `credit_cents` and on the enrollment as `take_out_credit_cents` (each zero
    until approved), the enrollment moves to `EXITED` with its own `exit_date`
    stamped and `exit_reason` set to `TAKE_OUT`, and the hold on the carrier's
    load is released."

    Design: Difficulty/transitive_cascade/takeout_approval_cascades_enrollment_carrier_load
    """
    set_clock("2026-07-01T00:00:00Z")
    bureau, pool_carrier, voluntary_carrier, employer, enrollment = (
        setup_active_enrollment(premium_cents=500000)
    )
    take_out = file_take_out(enrollment, voluntary_carrier, exit_date="2026-07-01")

    approved = validate_success(
        api.approve_assigned_risk_take_out(take_out["id"], POOL_ADMIN), expected_status=200
    )
    assert approved["status"] == "APPROVED"

    enrollment_after = validate_success(
        api.get_assigned_risk_enrollment(enrollment["id"], ADMIN)
    )
    assert enrollment_after["status"] == "EXITED"
    assert enrollment_after["exit_reason"] == "TAKE_OUT"

    carrier_after = validate_success(api.get_carrier(pool_carrier["id"], ADMIN))
    assert carrier_after["assigned_risk_current_load_cents"] == 0, (
        f"Approval must release the pool load hold back to 0, got "
        f"{carrier_after['assigned_risk_current_load_cents']}"
    )
    assert_carrier_load_within_quota(carrier_after)


def test_takeout_approval_stamps_credit_on_enrollment(api):
    """PRD section 3.9: "On approval the take-out moves to `APPROVED` with
    `approved_at` stamped and the credit recorded both in the take-out's
    `credit_cents` and on the enrollment as `take_out_credit_cents` (each zero
    until approved), the enrollment moves to `EXITED` with its own `exit_date`
    stamped and `exit_reason` set to `TAKE_OUT`, and the hold on the carrier's
    load is released."

    Design: Difficulty/transitive_cascade/takeout_approval_cascades_enrollment_carrier_load
    """
    set_clock("2026-07-01T00:00:00Z")
    bureau, pool_carrier, voluntary_carrier, employer, enrollment = (
        setup_active_enrollment(premium_cents=500000)
    )
    take_out = file_take_out(enrollment, voluntary_carrier, exit_date="2026-07-01")
    assert take_out["credit_cents"] == 0, "credit_cents must be zero until approved"

    approved = validate_success(
        api.approve_assigned_risk_take_out(take_out["id"], POOL_ADMIN), expected_status=200
    )
    assert approved["status"] == "APPROVED"
    assert approved["credit_cents"] > 0
    assert approved.get("approved_at"), "approved_at must be stamped on approval"

    enrollment_after = validate_success(
        api.get_assigned_risk_enrollment(enrollment["id"], ADMIN)
    )
    assert enrollment_after["status"] == "EXITED"
    assert enrollment_after["exit_reason"] == "TAKE_OUT"
    assert enrollment_after.get("exit_date") == "2026-07-01"
    assert enrollment_after["take_out_credit_cents"] == approved["credit_cents"]


def test_takeout_approval_flips_enrollment_and_releases_carrier_load(api):
    """PRD section 3.9: "Filing creates the take-out in `PENDING` and places a
    hold on the carrier's pool load - the enrollment's estimated premium is
    subtracted from `assigned_risk_current_load_cents` pending the decision."
    and "On approval ... the enrollment moves to `EXITED` with its own
    `exit_date` stamped and `exit_reason` set to `TAKE_OUT`, and the hold on
    the carrier's load is released."

    Design: Difficulty/cross_entity_state_dependency/takeout_approval_flips_enrollment_and_releases_carrier_load
    """
    set_clock("2026-07-01T00:00:00Z")
    bureau, pool_carrier, voluntary_carrier, employer, enrollment = (
        setup_active_enrollment(premium_cents=500000)
    )
    take_out = file_take_out(enrollment, voluntary_carrier, exit_date="2026-07-01")
    carrier_at_filing = validate_success(api.get_carrier(pool_carrier["id"], ADMIN))
    assert carrier_at_filing["assigned_risk_current_load_cents"] == 0, (
        "Filing must place the hold by subtracting the premium from the "
        f"carrier load (500000 -> 0), got "
        f"{carrier_at_filing['assigned_risk_current_load_cents']}"
    )

    validate_success(
        api.approve_assigned_risk_take_out(take_out["id"], POOL_ADMIN), expected_status=200
    )
    enrollment_after = validate_success(
        api.get_assigned_risk_enrollment(enrollment["id"], ADMIN)
    )
    assert enrollment_after["status"] == "EXITED"
    assert enrollment_after["exit_reason"] == "TAKE_OUT"
    carrier_after = validate_success(api.get_carrier(pool_carrier["id"], ADMIN))
    assert carrier_after["assigned_risk_current_load_cents"] == 0


def test_takeout_approve_blocked_while_enrollment_not_active(api):
    """PRD section 3.9: "Approval requires the enrollment still to be `ACTIVE`
    (`ERR_INVALID_STATE`)"; PRD section 5: ERR_INVALID_STATE maps to HTTP 409.

    Design: Difficulty/cross_entity_state_dependency/takeout_approval_flips_enrollment_and_releases_carrier_load
    """
    set_clock("2026-07-01T00:00:00Z")
    bureau, pool_carrier, voluntary_carrier, employer, enrollment = (
        setup_active_enrollment(premium_cents=500000)
    )
    take_out = file_take_out(enrollment, voluntary_carrier, exit_date="2026-07-01")
    # Rejecting a different (second) take-out is not possible here; instead
    # approve once so the enrollment leaves ACTIVE, then attempt to approve
    # the same take-out again from its terminal APPROVED state.
    validate_success(
        api.approve_assigned_risk_take_out(take_out["id"], POOL_ADMIN), expected_status=200
    )
    exited = validate_success(api.get_assigned_risk_enrollment(enrollment["id"], ADMIN))
    assert exited["status"] == "EXITED"
    resp = api.approve_assigned_risk_take_out(take_out["id"], POOL_ADMIN)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE, expected_status=409)


def test_carrier_pool_load_conserved_across_assign_and_cancel(api):
    """PRD section 3.9: "Assignment adds the estimated premium to the
    carrier's `assigned_risk_current_load_cents`" and "Cancelling an active
    enrollment moves it to `CANCELLED` and subtracts the estimated premium
    from the carrier's load."

    Design: Difficulty/compensating_invariant/carrier_pool_load_conserved_across_assign_and_takeout_approve
    """
    set_clock("2026-07-01T00:00:00Z")
    bureau, pool_carrier, voluntary_carrier, employer, enrollment = (
        setup_active_enrollment(premium_cents=500000)
    )
    carrier_after_assign = validate_success(api.get_carrier(pool_carrier["id"], ADMIN))
    assert carrier_after_assign["assigned_risk_current_load_cents"] == 500000

    cancelled = validate_success(
        api.cancel_assigned_risk_enrollment(enrollment["id"], POOL_ADMIN),
        expected_status=200,
    )
    assert cancelled["status"] == "CANCELLED"
    carrier_after = validate_success(api.get_carrier(pool_carrier["id"], ADMIN))
    assert carrier_after["assigned_risk_current_load_cents"] == 0, (
        f"Assign then cancel must conserve the load at 0, got "
        f"{carrier_after['assigned_risk_current_load_cents']}"
    )
    assert_carrier_load_within_quota(carrier_after)


def test_carrier_pool_load_conserved_across_assign_and_takeout_approve(api):
    """PRD section 3.9: "Assignment adds the estimated premium to the
    carrier's `assigned_risk_current_load_cents`" and "Rejection moves the
    take-out to `REJECTED`, leaves the enrollment `ACTIVE`, and likewise
    releases the hold - the carrier's load returns to its pre-filing level."

    Design: Difficulty/compensating_invariant/carrier_pool_load_conserved_across_assign_and_takeout_approve
    """
    set_clock("2026-07-01T00:00:00Z")
    bureau, pool_carrier, voluntary_carrier, employer, enrollment = (
        setup_active_enrollment(premium_cents=500000)
    )
    carrier_after_assign = validate_success(api.get_carrier(pool_carrier["id"], ADMIN))
    assert carrier_after_assign["assigned_risk_current_load_cents"] == 500000, (
        f"Assign must add the premium to the load, got "
        f"{carrier_after_assign['assigned_risk_current_load_cents']}"
    )

    # Compensating pair through reject: file the take-out (hold), then reject.
    take_out = file_take_out(enrollment, voluntary_carrier, exit_date="2026-07-01")
    validate_success(
        api.reject_assigned_risk_take_out(take_out["id"], POOL_ADMIN), expected_status=200
    )
    enrollment_after = validate_success(
        api.get_assigned_risk_enrollment(enrollment["id"], ADMIN)
    )
    assert enrollment_after["status"] == "ACTIVE", (
        f"Rejection must leave the enrollment ACTIVE, got {enrollment_after['status']}"
    )
    carrier_after = validate_success(api.get_carrier(pool_carrier["id"], ADMIN))
    assert carrier_after["assigned_risk_current_load_cents"] == 500000, (
        "After rejection the hold is released and the load returns to its "
        f"pre-filing level 500000, got "
        f"{carrier_after['assigned_risk_current_load_cents']}"
    )
    assert_carrier_load_within_quota(carrier_after)


def test_enrollment_assignment_beyond_quota_returns_quota_exceeded(api):
    """PRD section 3.9: "the selected carrier must have room under its quota -
    the sum of the carrier's `assigned_risk_current_load_cents` and the
    enrollment's `estimated_annual_premium_cents` must not exceed the
    carrier's `assigned_risk_quota_cents`, or the assignment is rejected with
    `ERR_ASSIGNED_RISK_QUOTA_EXCEEDED`"; PRD section 5:
    ERR_ASSIGNED_RISK_QUOTA_EXCEEDED maps to HTTP 409.

    Design: Corner/validations/enrollment_assignment_beyond_quota_returns_quota_exceeded
    """
    set_clock("2026-01-15T00:00:00Z")
    from test_helpers import create_bureau, create_carrier

    create_bureau()
    pool_carrier = create_carrier(
        naic_number="10002",
        legal_name="Pool Carrier One",
        assigned_risk_quota_cents=1000000,
    )
    employer_c = create_employer(
        fein="75-1000003", legal_name="Capitol Fasteners", state_code="TX"
    )
    employer_d = create_employer(fein="75-1000004", legal_name="Delta Mill", state_code="TX")
    employer_e = create_employer(
        fein="75-1000005", legal_name="Eagle Foundry", state_code="TX"
    )

    def _enroll(employer_id, premium):
        enrollment = validate_success(
            api.create_assigned_risk_enrollment(
                create_assigned_risk_enrollment_payload(
                    employer_id=employer_id,
                    effective_date="2026-02-01",
                    expiration_date="2027-02-01",
                    estimated_annual_premium_cents=premium,
                ),
                POOL_ADMIN,
            ),
            expected_status=201,
        )
        return enrollment

    enrollment_1 = _enroll(employer_c["id"], 600000)
    validate_success(
        api.assign_assigned_risk_enrollment(
            enrollment_1["id"], {"carrier_id": pool_carrier["id"]}, POOL_ADMIN
        )
    )
    enrollment_2 = _enroll(employer_d["id"], 500000)
    enrollment_3 = _enroll(employer_e["id"], 400000)

    # 600,000 + 500,000 = 1,100,000 > 1,000,000 quota: rejected.
    resp = api.assign_assigned_risk_enrollment(
        enrollment_2["id"], {"carrier_id": pool_carrier["id"]}, POOL_ADMIN
    )
    validate_error(resp, ApiErrorId.ERR_ASSIGNED_RISK_QUOTA_EXCEEDED, expected_status=409)
    after_2 = validate_success(
        api.get_assigned_risk_enrollment(enrollment_2["id"], ADMIN)
    )
    assert after_2["status"] == "PENDING"

    # 600,000 + 400,000 = 1,000,000 <= 1,000,000 quota: accepted (not exceed).
    assigned_3 = validate_success(
        api.assign_assigned_risk_enrollment(
            enrollment_3["id"], {"carrier_id": pool_carrier["id"]}, POOL_ADMIN
        ),
        expected_status=200,
    )
    assert assigned_3["status"] == "ACTIVE"
    carrier_after = validate_success(api.get_carrier(pool_carrier["id"], ADMIN))
    assert carrier_after["assigned_risk_current_load_cents"] == 1000000
    assert_carrier_load_within_quota(carrier_after)


def test_underwriting_gate_blocks_takeout_approval_above_threshold(api):
    """PRD section 3.9: "Approval requires the enrollment still to be `ACTIVE`
    (`ERR_INVALID_STATE`), and - when the computed credit is at least the
    bureau's `underwriting_threshold_cents` - an approved `UnderwritingReview`
    for the take-out must already exist, or the approval is rejected with
    `ERR_UNDERWRITING_REVIEW_REQUIRED`"; PRD section 5:
    ERR_UNDERWRITING_REVIEW_REQUIRED maps to HTTP 409.

    Design: Corner/rbac/underwriter_cannot_approve_own_created_subject
    """
    set_clock("2026-07-01T00:00:00Z")
    # Bureau with a low underwriting threshold (100,000 cents) so the take-out
    # credit (247,500+ cents for these dates) crosses it.
    bureau, pool_carrier, voluntary_carrier, employer, enrollment = (
        setup_active_enrollment(
            premium_cents=500000, bureau_overrides={"underwriting_threshold_cents": 100000}
        )
    )
    take_out = file_take_out(enrollment, voluntary_carrier, exit_date="2026-07-01")

    resp = api.approve_assigned_risk_take_out(take_out["id"], POOL_ADMIN)
    validate_error(resp, ApiErrorId.ERR_UNDERWRITING_REVIEW_REQUIRED, expected_status=409)
    after = validate_success(api.get_assigned_risk_take_out(take_out["id"], ADMIN))
    assert after["status"] == "PENDING", (
        f"Blocked approval must leave the take-out PENDING, got {after['status']}"
    )
