"""Creation-time defaults and derived fields for the stand-alone resources."""
from test_helpers import (
    ApiErrorId,
    assert_agreement,
    assert_cohort,
    assert_instant_eq,
    assert_partner,
    assert_partner_billing_zeroed,
    anonymous_headers,
    assert_placement,
    assert_student,
    create_cohort,
    create_partner,
    register_student,
    setup_matched_placement,
    validate_error,
)


def test_student_registration_applies_declared_defaults(api):
    """PRD §3.1: "A newly registered applicant starts with `application_state` at
    `APPLIED`, `current_phase` null because no phase has begun, `roster_status`
    `ON_TRACK`, `total_stipend_paid_cents` 0, `lifetime_contract_points` 0 and
    `conversion_streak` 0."

    Design: Corner/entities/student_registration_applies_declared_defaults
    """
    student = register_student()

    assert student["application_state"] == "APPLIED", student["application_state"]
    assert student["current_phase"] is None, student["current_phase"]
    assert student["roster_status"] == "ON_TRACK", student["roster_status"]
    assert student["total_stipend_paid_cents"] == 0, student["total_stipend_paid_cents"]
    assert student["lifetime_contract_points"] == 0, student["lifetime_contract_points"]
    assert student["conversion_streak"] == 0, student["conversion_streak"]
    assert_student(student)


def test_cohort_creation_derives_graduation_date_and_status(api):
    """PRD §3.2: "The system writes the cohort's `graduation_date` at creation as the
    `start_date` plus 180 days"
    PRD §3.2: "A new cohort starts at `status` `PLANNED` with `enrolled_count` 0 and
    `awarded_points` 0."

    Design: Corner/entities/cohort_creation_derives_graduation_date_and_status
    """
    cohort = create_cohort(program_code="CYBER", location_code="BOS-02", capacity=12)

    assert_instant_eq(cohort["graduation_date"], "2027-02-28T00:00:00Z", "graduation_date")
    assert cohort["enrolled_count"] == 0, cohort["enrolled_count"]
    assert cohort["status"] == "PLANNED", cohort["status"]
    assert cohort["awarded_points"] == 0, cohort["awarded_points"]
    assert_cohort(cohort)


def test_partner_creation_zeroes_every_billing_field(api):
    """PRD §3.3: "A new partner starts at `status` `ACTIVE` with
    `placement_quality_score` 0.00, `on_time_payment_ratio` 0.0000, `credit_hold`
    false, every billing total — `outstanding_balance_cents`, `billed_cents` and
    `collected_cents` — at 0, `collection_ratio` 0.0000 and `oldest_open_due_date`
    null."

    Design: Corner/entities/partner_creation_zeroes_every_billing_field
    """
    partner = create_partner(
        legal_name="Contoso Retail", industry="RETAIL",
        billing_email="ap@contoso.example", fee_tier="TIER_C",
    )

    assert partner["status"] == "ACTIVE", partner["status"]
    assert_partner_billing_zeroed(partner)
    assert_partner(partner)


def test_duplicate_student_email_returns_conflict(api):
    """PRD §3.1: "it is refused with `ERR_DUPLICATE_EMAIL` (409) when another student
    already holds the same `email`"
    PRD §2.5: "No other student may already carry the same `email`"

    Design: Corner/entities/duplicate_student_email_returns_conflict
    """
    first = register_student()

    response = api.register_student(
        {
            "full_name": "Ava R Reyes",
            "email": first["email"],
            "date_of_birth": "2005-04-12",
            "education_status": "HS_DIPLOMA",
            "household_income_cents": 2_100_000,
        },
        anonymous_headers(),
    )

    validate_error(response, ApiErrorId.ERR_DUPLICATE_EMAIL, expected_status=409)
    assert first["email"] == "ava.reyes@example.com", first["email"]


def test_placement_starts_matched_with_copied_scope(api):
    """PRD §3.4: "A successful match creates a placement at `state` `MATCHED` with
    `interview_attempt` 0, its `project_scope` copied from the sponsoring agreement,
    and its `supervisor_name` copied from the sponsoring agreement's partner's
    `legal_name`; the placement's `placement_fee_cents`, `outcome` and
    `satisfaction_score` stay unset at this point."

    Design: Corner/state_machines/placement_starts_matched_with_copied_scope
    """
    scenario = setup_matched_placement()
    placement = scenario.placement

    assert placement["state"] == "MATCHED", placement["state"]
    assert placement["interview_attempt"] == 0, placement["interview_attempt"]
    assert placement["project_scope"] == scenario.agreement["project_scope"], placement["project_scope"]
    assert placement["supervisor_name"] == scenario.partner["legal_name"], placement["supervisor_name"]
    assert placement.get("placement_fee_cents") is None, placement.get("placement_fee_cents")
    assert placement.get("outcome") is None, placement.get("outcome")
    assert placement.get("satisfaction_score") is None, placement.get("satisfaction_score")
    assert_placement(placement)
    assert_agreement(scenario.agreement)
