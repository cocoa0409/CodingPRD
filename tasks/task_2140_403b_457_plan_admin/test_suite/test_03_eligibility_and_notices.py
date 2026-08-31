"""Universal availability notices and the eligibility determination cascade."""

from test_helpers import (
    ApiErrorId,
    create_active_plan,
    determine_eligibility,
    file_notice,
    make_officer_headers,
    make_sponsor_headers,
    register_employer,
    register_participant,
    set_clock,
    setup_plan_env,
    validate_error,
    validate_paginated,
    validate_success,
)


def _hours_env():
    """One ACTIVE 403(b) plan under a governmental sponsor, no notice filed."""
    return setup_plan_env(plan_type="PLAN_403B", num_vendors=0)


def test_twenty_scheduled_hours_is_not_excludable(api):
    """PRD §3.3: "Both prongs of that third rung must hold together. Exactly 20.0
    scheduled hours is not excludable, and neither is exactly 1000 prior-year hours — a
    participant scheduled for 19 hours who nonetheless worked 1000 hours last year
    remains eligible."
    PRD §3.3: "`universal_availability_applies` is true exactly when the plan's
    `nondiscrimination_regime` is `UA_ONLY` or `UA_PLUS_410B_401A4`."

    Design: Difficulty/boundary_precision_check/universal_availability_hours_boundary_at_twenty_and_one_thousand
    """
    env = _hours_env()
    at_twenty = register_participant(
        env["employer_id"], full_name="Edge Twenty", date_of_birth="1985-04-04",
        hire_date="2020-01-01", scheduled_hours_per_week=20, prior_year_hours_worked=900,
        includible_compensation_cents=3_000_000, years_of_service=6,
    )
    below_twenty = register_participant(
        env["employer_id"], full_name="Under Twenty", date_of_birth="1985-04-04",
        hire_date="2020-01-01", scheduled_hours_per_week=19.5, prior_year_hours_worked=900,
        includible_compensation_cents=3_000_000, years_of_service=6,
    )

    at_twenty_determination = validate_success(
        api.create_eligibility_determination(
            {"plan_id": env["plan_id"], "participant_id": at_twenty["id"]},
            make_officer_headers(),
        ),
        expected_status=201,
    )
    below_twenty_determination = validate_success(
        api.create_eligibility_determination(
            {"plan_id": env["plan_id"], "participant_id": below_twenty["id"]},
            make_officer_headers(),
        ),
        expected_status=201,
    )

    assert at_twenty_determination["status"] == "ELIGIBLE", "20.0 is not strictly below 20"
    assert below_twenty_determination["status"] == "EXCLUDED_LESS_THAN_20_HOURS"
    assert at_twenty_determination["universal_availability_applies"] is True
    assert at_twenty_determination["notice_status"] == "MISSING"


def test_one_thousand_prior_year_hours_defeats_the_part_time_exclusion(api):
    """PRD §3.3: "otherwise if `scheduled_hours_per_week` is strictly less than 20 *and*
    `prior_year_hours_worked` is strictly less than 1000 the status is
    `EXCLUDED_LESS_THAN_20_HOURS`; otherwise the status is `ELIGIBLE`."
    PRD §3.3: "if there are none, `notice_status` is `MISSING`; if at least one of them
    has `is_valid` true, `notice_status` is `CURRENT`; if some exist but none is valid,
    `notice_status` is `INVALID`."

    Design: Difficulty/boundary_precision_check/universal_availability_hours_boundary_at_twenty_and_one_thousand
    """
    env = _hours_env()
    thousand_hours = register_participant(
        env["employer_id"], full_name="Thousand Hours", date_of_birth="1985-04-04",
        hire_date="2020-01-01", scheduled_hours_per_week=19.5, prior_year_hours_worked=1000,
        includible_compensation_cents=3_000_000, years_of_service=6,
    )

    determination = validate_success(
        api.create_eligibility_determination(
            {"plan_id": env["plan_id"], "participant_id": thousand_hours["id"]},
            make_officer_headers(),
        ),
        expected_status=201,
    )

    assert determination["status"] == "ELIGIBLE", "1000 is not strictly below 1000"
    assert determination["exclusion_basis"] is None
    assert determination["notice_status"] == "MISSING"
    assert determination["universal_availability_applies"] is True


def test_notice_validity_rejects_intranet_posting_and_short_reach(api):
    """PRD §3.3: "The server sets `is_valid` true exactly when all three of the following
    hold: `describes_effective_opportunity` is true; `recipient_count` is greater than
    or equal to the plan's `reported_participant_count`, so a count exactly equal to the
    participant count is sufficient; and `delivery_method` is anything other than
    `INTRANET_POSTING`."
    PRD §3.3: "if there are none, `notice_status` is `MISSING`; if at least one of them
    has `is_valid` true, `notice_status` is `CURRENT`; if some exist but none is valid,
    `notice_status` is `INVALID`."

    Design: Corner/calculations/universal_availability_notice_validity_rejects_posting_and_short_reach
    """
    set_clock()
    employer = register_employer()
    plan_one = create_active_plan(employer["id"], plan_name="Riverbend 403(b)")
    plan_two = create_active_plan(employer["id"], plan_name="Riverbend Legacy 403(b)")
    participant = register_participant(employer["id"])

    intranet_notice = validate_success(
        api.create_notice(
            plan_one["id"],
            {
                "plan_year": 2026, "issued_date": "2026-01-05",
                "delivery_method": "INTRANET_POSTING", "recipient_count": 250,
                "describes_effective_opportunity": True,
            },
            make_sponsor_headers(employer["id"]),
        ),
        expected_status=201,
    )
    short_reach_notice = validate_success(
        api.create_notice(
            plan_two["id"],
            {
                "plan_year": 2026, "issued_date": "2026-01-05",
                "delivery_method": "EMAIL", "recipient_count": 249,
                "describes_effective_opportunity": True,
            },
            make_sponsor_headers(employer["id"]),
        ),
        expected_status=201,
    )
    determination = validate_success(
        api.create_eligibility_determination(
            {"plan_id": plan_one["id"], "participant_id": participant["id"]},
            make_officer_headers(),
        ),
        expected_status=201,
    )

    assert intranet_notice["is_valid"] is False, "intranet posting alone is never effective"
    assert short_reach_notice["is_valid"] is False, "249 recipients is below 250 participants"
    assert determination["status"] == "ELIGIBLE"
    assert determination["notice_status"] == "INVALID"
    assert determination["universal_availability_applies"] is True


def test_duplicate_notice_for_a_plan_year_is_rejected(api):
    """PRD §3.3: "At most one notice may exist for a given plan and `plan_year`; a second
    filing for the same pair is refused with `ERR_DUPLICATE_UA_NOTICE`."

    Design: Corner/validations/duplicate_universal_availability_notice_for_a_plan_year_is_rejected
    """
    env = setup_plan_env(plan_type="PLAN_403B", num_vendors=0)
    file_notice(env["plan_id"], env["employer_id"])

    duplicate = api.create_notice(
        env["plan_id"],
        {
            "plan_year": 2026, "issued_date": "2026-02-01", "delivery_method": "PAPER_MAIL",
            "recipient_count": 260, "describes_effective_opportunity": True,
        },
        make_sponsor_headers(env["employer_id"]),
    )
    validate_error(duplicate, ApiErrorId.ERR_DUPLICATE_UA_NOTICE.value)

    next_year = validate_success(
        api.create_notice(
            env["plan_id"],
            {
                "plan_year": 2027, "issued_date": "2026-07-01", "delivery_method": "PAPER_MAIL",
                "recipient_count": 260, "describes_effective_opportunity": True,
            },
            make_sponsor_headers(env["employer_id"]),
        ),
        expected_status=201,
    )
    assert next_year["is_valid"] is True

    rows, _meta = validate_paginated(
        api.list_notices(env["plan_id"], make_officer_headers(), {"plan_year": 2026})
    )
    assert len(rows) == 1, "only one notice may exist for the 2026 plan year"


def test_asserted_exclusion_unsupported_by_facts_is_rejected(api):
    """PRD §3.3: "The server does not take the assertion on trust: it derives the outcome
    independently and, if the participant's facts do not support the assertion made,
    refuses the determination with `ERR_UA_EXCLUSION_NOT_PERMITTED`."
    PRD §3.3: "when the status is `ELIGIBLE`, `exclusion_basis` is null"

    Design: Corner/validations/asserted_exclusion_unsupported_by_participant_facts_is_rejected
    """
    env = setup_plan_env(plan_type="PLAN_403B", num_vendors=0)
    participant = register_participant(env["employer_id"])

    refused = api.create_eligibility_determination(
        {
            "plan_id": env["plan_id"], "participant_id": participant["id"],
            "asserted_exclusion": "STUDENT",
        },
        make_officer_headers(),
    )
    validate_error(refused, ApiErrorId.ERR_UA_EXCLUSION_NOT_PERMITTED.value)

    accepted = validate_success(
        api.create_eligibility_determination(
            {
                "plan_id": env["plan_id"], "participant_id": participant["id"],
                "asserted_exclusion": "NONE",
            },
            make_officer_headers(),
        ),
        expected_status=201,
    )

    assert accepted["status"] == "ELIGIBLE"
    assert accepted["exclusion_basis"] is None
    rows, _meta = validate_paginated(
        api.list_eligibility_determinations(
            make_officer_headers(), {"participant_id": participant["id"]}
        )
    )
    assert len(rows) == 1, "the refused assertion must not have persisted a determination"


def test_plan_sponsor_admin_cannot_run_an_eligibility_determination(api):
    """PRD §2.1: "If both headers are well formed but the named role is not among the
    roles the addressed endpoint admits, the refusal is `ERR_UNAUTHORIZED_ROLE`
    (HTTP 403)."
    PRD §4: "| POST | `/plan-admin/eligibility-determinations` | Run the
    eligibility_determination calculation for one (plan, participant) pair and persist
    the outcome, superseding any earlier determination for that pair | `ComplianceOfficer` |"

    Design: Corner/rbac/plan_sponsor_admin_cannot_run_an_eligibility_determination
    """
    env = setup_plan_env(plan_type="PLAN_403B", num_vendors=0)
    participant = register_participant(env["employer_id"])

    refused = api.create_eligibility_determination(
        {"plan_id": env["plan_id"], "participant_id": participant["id"]},
        make_sponsor_headers(env["employer_id"]),
    )
    validate_error(refused, ApiErrorId.ERR_UNAUTHORIZED_ROLE.value)

    allowed = validate_success(
        api.create_eligibility_determination(
            {"plan_id": env["plan_id"], "participant_id": participant["id"]},
            make_officer_headers(),
        ),
        expected_status=201,
    )
    assert allowed["status"] == "ELIGIBLE"

    rows, _meta = validate_paginated(
        api.list_eligibility_determinations(
            make_officer_headers(), {"participant_id": participant["id"]}
        )
    )
    assert len(rows) == 1
