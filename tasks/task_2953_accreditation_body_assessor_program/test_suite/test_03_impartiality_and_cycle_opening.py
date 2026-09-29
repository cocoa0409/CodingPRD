"""The append-only disclosure log, the cooling-off verdict, and cycle opening.

Every test in this module translates exactly one design instance; the
``Design:`` line closing each docstring names it.
"""

from prd_bench_local_runner.testing import get_success_data, validate_error, validate_success

from test_helpers.assertions import (
    assert_append_only_fields,
    assert_instant_equals,
    assert_total_count,
)
from test_helpers.api_errors import (
    ERR_DUPLICATE_ACTIVE_APPLICATION,
    ERR_IMPARTIALITY_CONFLICT,
    ERR_INVALID_NOTICE_PERIOD,
    ERR_SCHEME_NOT_FOUND,
)
from test_helpers.constants import (
    APP_SUBMITTED,
    APP_TEAM_ASSIGNED,
    COOLING_OFF_MONTHS_STRUCTURAL,
    CYCLE_INITIAL,
    EMPLOYMENT_CONTRACT,
    EMPLOYMENT_INTERNAL,
    IMPARTIALITY_RESTRICTED,
    IMPARTIALITY_SCREENED,
    NOTICE_DAYS_MINIMUM_ANNOUNCED,
    ORG_APPLIED,
    ORG_UNDER_ASSESSMENT,
    QUALIFICATION_STATUS_QUALIFIED,
    RELATIONSHIP_EMPLOYMENT,
    ROLE_ASSESSMENT_MANAGER,
    ROLE_TYPE_LEAD_ASSESSOR,
    ROLE_TYPE_TECHNICAL_EXPERT,
    SEVERITY_STRUCTURAL,
    STANDARD_REF_17020,
    TA_CONFIRMED,
    TA_PROPOSED,
    UNKNOWN_UUID,
    VERDICT_CLEARED,
)
from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.test_users import ASSESSMENT_MANAGER, SCHEME_MANAGER


def test_impartiality_declaration_is_append_only_and_carries_no_version(client):
    """A disclosure is immutable, and a second row for the same pair is
    appended rather than replacing the first.

    PRD section 2.4: "Declarations therefore carry only `id` and
    `created_at`: they have neither `updated_at` nor `version`, and neither
    field appears in a declaration payload."

    Design: Corner/entities/impartiality_declaration_is_append_only_and_carries_no_version
    """
    fx.set_clock(client, fx.CLOCK_BUILD_INSTANT)
    assessor = fx.register_assessor(
        client, "Lena Ahlgren", "lena.ahlgren@ab.test", EMPLOYMENT_INTERNAL, 20
    )
    organization = fx.register_organization(
        client, "Northlight Testing AB", "SE", "qa@northlight.test"
    )

    response = client.create_declaration(
        assessor["id"],
        f.declaration_payload(
            organization["id"],
            RELATIONSHIP_EMPLOYMENT,
            "2023-01-01",
            detail="salaried quality manager, still in post",
        ),
        ASSESSMENT_MANAGER,
    )

    first = validate_success(response, 201)
    assert_append_only_fields(first)
    assert first["severity_class"] == SEVERITY_STRUCTURAL
    assert first["cooling_off_months"] == COOLING_OFF_MONTHS_STRUCTURAL
    assert first["declared_by_role"] == ROLE_ASSESSMENT_MANAGER
    assert first["ended_on"] is None
    assert (
        fx.read_assessor(client, assessor["id"])["impartiality_status"]
        == IMPARTIALITY_RESTRICTED
    )

    get_success_data(
        client.create_declaration(
            assessor["id"],
            f.declaration_payload(
                organization["id"],
                RELATIONSHIP_EMPLOYMENT,
                "2023-01-01",
                ended_on="2024-06-30",
            ),
            ASSESSMENT_MANAGER,
        )
    )
    assert_total_count(
        client.list_declarations(
            ASSESSMENT_MANAGER,
            {"assessor_id": assessor["id"], "organization_id": organization["id"]},
        ),
        2,
    )
    stored = validate_success(
        client.get_declaration(first["id"], ASSESSMENT_MANAGER), 200
    )
    assert stored["ended_on"] is None, "Appending a newer row never edits the older one"
    assert_append_only_fields(stored)


def test_qualification_and_impartiality_dimensions_evolve_independently(client):
    """Filing a structural disclosure restricts the assessor without
    touching the competence dimension, and re-screening clears it back.

    PRD section 3.2: "`qualification_status` begins at `APPLICANT` and
    evolves through `SCREENING`, `QUALIFIED` and `SUSPENDED` toward the
    terminal `WITHDRAWN`. `impartiality_status` begins at `UNDECLARED` and
    moves between `SCREENED` and `RESTRICTED` with no terminal state at all.
    Neither dimension constrains the other: a `RESTRICTED` assessor may still
    be `QUALIFIED`, and a `SUSPENDED` assessor may still be `SCREENED`."

    Design: Difficulty/non_linear_state_machine/assessor_qualification_and_impartiality_dimensions_evolve_independently
    """
    ctx = fx.new_context(client, "ISO17025-PAR")
    fx.with_lead(ctx)
    fx.with_organization(ctx)
    screened = fx.read_assessor(client, ctx["lead_id"])
    assert screened["qualification_status"] == QUALIFICATION_STATUS_QUALIFIED
    assert screened["impartiality_status"] == IMPARTIALITY_SCREENED

    open_declaration = get_success_data(
        client.create_declaration(
            ctx["lead_id"],
            f.declaration_payload(
                ctx["org_id"],
                RELATIONSHIP_EMPLOYMENT,
                "2019-03-01",
                detail="Quality manager, still on the payroll.",
            ),
            ASSESSMENT_MANAGER,
        )
    )
    restricted = fx.read_assessor(client, ctx["lead_id"])
    assert restricted["impartiality_status"] == IMPARTIALITY_RESTRICTED
    assert restricted["qualification_status"] == QUALIFICATION_STATUS_QUALIFIED, (
        "Filing a disclosure must not touch the competence dimension"
    )
    closing_declaration = get_success_data(
        client.create_declaration(
            ctx["lead_id"],
            f.declaration_payload(
                ctx["org_id"],
                RELATIONSHIP_EMPLOYMENT,
                "2019-03-01",
                ended_on="2026-08-05",
                detail="Employment closed; supersedes the open-ended declaration.",
            ),
            ASSESSMENT_MANAGER,
        )
    )

    response = client.screen_assessor(ctx["lead_id"], SCHEME_MANAGER)

    assessor = validate_success(response, 200)
    assert assessor["impartiality_status"] == IMPARTIALITY_SCREENED
    assert assessor["qualification_status"] == QUALIFICATION_STATUS_QUALIFIED
    assert assessor["granted_qualification_count"] == 1
    assert assessor["last_screened_on"] == fx.CLOCK_BUILD_DATE
    assert open_declaration["severity_class"] == SEVERITY_STRUCTURAL
    assert open_declaration["ended_on"] is None
    assert open_declaration["cooling_off_months"] == COOLING_OFF_MONTHS_STRUCTURAL
    assert closing_declaration["severity_class"] == SEVERITY_STRUCTURAL
    assert closing_declaration["cooling_off_months"] == COOLING_OFF_MONTHS_STRUCTURAL
    still_there = validate_success(
        client.get_declaration(open_declaration["id"], ASSESSMENT_MANAGER), 200
    )
    assert still_there["ended_on"] is None
    assert_append_only_fields(still_there)


def test_cooling_off_cleared_at_twenty_four_months_and_blocked_at_twenty_three(client):
    """The window is satisfied at exactly 24 whole calendar months and one
    day short of it still blocks.

    PRD section 3.3: "If `ended_on` is set, compute the whole calendar months
    elapsed from `ended_on` to the reference date using the year-and-month
    difference with a day-of-month borrow described in §2.7. If that number
    of months is strictly less than the cooling-off window, the pair
    contributes `BLOCKED`."

    Design: Corner/validations/cooling_off_cleared_at_exactly_twenty_four_months_and_blocked_at_twenty_three
    """
    fx.set_clock(client, fx.CLOCK_BUILD_INSTANT)
    scheme = fx.create_published_scheme(
        client, "ISO17025-CAL", witness_min_count=2, qualification_points_required=60.0
    )
    lead = fx.register_assessor(
        client, "Lena Ahlgren", "lena.ahlgren@ab.test", EMPLOYMENT_INTERNAL, 20
    )
    lead_qualification = fx.register_qualification(
        client, lead["id"], scheme["id"], ROLE_TYPE_LEAD_ASSESSOR, 8, 6, 3, "2026-05-10"
    )
    fx.verify_qualification(client, lead_qualification["id"], 8, 5, 2)
    fx.screen_assessor(client, lead["id"])
    expert = fx.register_assessor(
        client, "Ines Solberg", "ines.solberg@ab.test", EMPLOYMENT_CONTRACT, 12
    )
    expert_qualification = fx.register_qualification(
        client,
        expert["id"],
        scheme["id"],
        ROLE_TYPE_TECHNICAL_EXPERT,
        12,
        2,
        2,
        "2026-05-10",
    )
    fx.verify_qualification(client, expert_qualification["id"], 12, 2, 2)
    fx.screen_assessor(client, expert["id"])
    organization = fx.register_organization(
        client, "Northlight Testing AB", "SE", "qa@northlight.test"
    )
    application = fx.open_initial_cycle(
        client,
        organization["id"],
        scheme["id"],
        [
            "mass calibration 1 mg - 20 kg",
            "temperature calibration -40 C - 250 C",
            "pressure calibration 0 - 700 bar",
        ],
        30,
    )
    ta_lead = fx.propose_team_member(
        client, application["id"], lead["id"], ROLE_TYPE_LEAD_ASSESSOR
    )
    ta_expert = fx.propose_team_member(
        client, application["id"], expert["id"], ROLE_TYPE_TECHNICAL_EXPERT
    )
    declaration_lead = get_success_data(
        client.create_declaration(
            lead["id"],
            f.declaration_payload(
                organization["id"],
                RELATIONSHIP_EMPLOYMENT,
                "2020-01-01",
                ended_on="2024-08-10",
                detail="former quality manager, left exactly 24 months before the reference date",
            ),
            ASSESSMENT_MANAGER,
        )
    )
    declaration_expert = get_success_data(
        client.create_declaration(
            expert["id"],
            f.declaration_payload(
                organization["id"],
                RELATIONSHIP_EMPLOYMENT,
                "2020-01-01",
                ended_on="2024-08-11",
                detail="former metrologist, left one day inside the cooling-off window",
            ),
            ASSESSMENT_MANAGER,
        )
    )
    confirmed_lead = fx.confirm_team_member(client, ta_lead["id"])

    response = client.confirm_team_assignment(ta_expert["id"], ASSESSMENT_MANAGER)

    validate_error(response, ERR_IMPARTIALITY_CONFLICT, 422)
    stored_expert = validate_success(
        client.get_team_assignment(ta_expert["id"], ASSESSMENT_MANAGER), 200
    )
    assert stored_expert["status"] == TA_PROPOSED
    assert stored_expert["conflict_verdict"] is None
    assert confirmed_lead["status"] == TA_CONFIRMED
    assert confirmed_lead["conflict_verdict"] == VERDICT_CLEARED
    assert_instant_equals(confirmed_lead["conflict_checked_at"], fx.CLOCK_BUILD_INSTANT)
    assert declaration_lead["severity_class"] == SEVERITY_STRUCTURAL
    assert declaration_lead["cooling_off_months"] == COOLING_OFF_MONTHS_STRUCTURAL
    assert declaration_expert["severity_class"] == SEVERITY_STRUCTURAL
    assert declaration_expert["cooling_off_months"] == COOLING_OFF_MONTHS_STRUCTURAL
    assert (
        fx.read_assessor(client, lead["id"])["impartiality_status"]
        == IMPARTIALITY_SCREENED
    )
    assert (
        fx.read_assessor(client, expert["id"])["impartiality_status"]
        == IMPARTIALITY_SCREENED
    )
    assert fx.read_application(client, application["id"])["status"] == APP_TEAM_ASSIGNED
    stored_org = validate_success(
        client.get_organization(organization["id"], ASSESSMENT_MANAGER), 200
    )
    assert stored_org["status"] == ORG_UNDER_ASSESSMENT


def test_cycle_with_unknown_scheme_reference_is_not_found(client):
    """A body-supplied ``scheme_id`` that names no live row is a 404.

    PRD section 2.9: "A body-supplied foreign key that names no live row
    produces the same 404 family — `ERR_SCHEME_NOT_FOUND`,
    `ERR_ASSESSOR_NOT_FOUND`, `ERR_ORGANIZATION_NOT_FOUND`,
    `ERR_APPLICATION_NOT_FOUND` or `ERR_SCOPE_NOT_FOUND` — for the six
    endpoints that accept one: opening an initial cycle, proposing a team
    member, registering a declared qualification, filing an impartiality
    declaration, filing a complaint or appeal, and assigning a case
    reviewer."

    Design: Corner/entities/create_application_with_unknown_scheme_reference_not_found
    """
    fx.set_clock(client, fx.CLOCK_BUILD_INSTANT)
    organization = fx.register_organization(
        client, "Northlight Testing AB", "SE", "qa@northlight.test"
    )

    response = client.create_application(
        f.application_payload(
            organization["id"],
            UNKNOWN_UUID,
            CYCLE_INITIAL,
            ["mass calibration 1 mg - 20 kg"],
            30,
        ),
        ASSESSMENT_MANAGER,
    )

    validate_error(response, ERR_SCHEME_NOT_FOUND, 404)
    stored = validate_success(
        client.get_organization(organization["id"], ASSESSMENT_MANAGER), 200
    )
    assert stored["status"] == ORG_APPLIED
    assert_total_count(
        client.list_applications(
            ASSESSMENT_MANAGER, {"organization_id": organization["id"]}
        ),
        0,
    )


def test_initial_cycle_with_notice_below_the_minimum_is_rejected(client):
    """An announced cycle must carry at least fourteen notice days.

    PRD section 3.4: "`notice_days` defaults to 30 and must lie between 0 and
    120 inclusive; beyond that range check, an `UNANNOUNCED` cycle must carry
    exactly 0 notice days while every other `cycle_type` must carry at least
    14 — a violation of either half is `ERR_INVALID_NOTICE_PERIOD`."

    Design: Corner/validations/initial_cycle_with_notice_below_the_minimum_rejected
    """
    fx.set_clock(client, fx.CLOCK_BUILD_INSTANT)
    scheme = fx.create_published_scheme(
        client, "ISO17025-CAL", witness_min_count=2, qualification_points_required=60.0
    )
    organization = fx.register_organization(
        client, "Northlight Testing AB", "SE", "qa@northlight.test"
    )

    response = client.create_application(
        f.application_payload(
            organization["id"],
            scheme["id"],
            CYCLE_INITIAL,
            ["mass calibration 1 mg - 20 kg"],
            10,
        ),
        ASSESSMENT_MANAGER,
    )

    validate_error(response, ERR_INVALID_NOTICE_PERIOD, 422)
    assert_total_count(
        client.list_applications(
            ASSESSMENT_MANAGER, {"organization_id": organization["id"]}
        ),
        0,
    )
    stored_org = validate_success(
        client.get_organization(organization["id"], ASSESSMENT_MANAGER), 200
    )
    assert stored_org["status"] == ORG_APPLIED
    accepted = validate_success(
        client.create_application(
            f.application_payload(
                organization["id"],
                scheme["id"],
                CYCLE_INITIAL,
                ["mass calibration 1 mg - 20 kg"],
                NOTICE_DAYS_MINIMUM_ANNOUNCED,
            ),
            ASSESSMENT_MANAGER,
        ),
        201,
    )
    assert accepted["notice_days"] == NOTICE_DAYS_MINIMUM_ANNOUNCED
    assert accepted["status"] == APP_SUBMITTED
    assert accepted["pinned_scheme_rule_revision"] == 1


def test_second_active_cycle_for_the_same_organization_and_scheme_is_rejected(client):
    """The duplicate guard is keyed on the pair, so another programme is free.

    PRD section 3.4: "The programme must be `PUBLISHED`
    (`ERR_SCHEME_NOT_PUBLISHED`), and the organization must not already have
    another cycle for the same programme sitting in a non-terminal status —
    the terminal statuses being `GRANTED` and `WITHDRAWN` — or the request is
    rejected with `ERR_DUPLICATE_ACTIVE_APPLICATION`."

    Design: Corner/validations/second_active_cycle_for_the_same_organization_and_scheme_rejected
    """
    fx.set_clock(client, fx.CLOCK_BUILD_INSTANT)
    scheme_a = fx.create_published_scheme(
        client, "ISO17025-CAL", witness_min_count=2, qualification_points_required=60.0
    )
    scheme_b = fx.create_published_scheme(
        client,
        "ISO17020-INSP",
        name="Inspection bodies",
        standard_ref=STANDARD_REF_17020,
        witness_min_count=2,
        qualification_points_required=60.0,
    )
    organization = fx.register_organization(
        client, "Northlight Testing AB", "SE", "qa@northlight.test"
    )
    first = fx.open_initial_cycle(
        client,
        organization["id"],
        scheme_a["id"],
        ["mass calibration 1 mg - 20 kg"],
        30,
    )

    response = client.create_application(
        f.application_payload(
            organization["id"],
            scheme_a["id"],
            CYCLE_INITIAL,
            ["temperature calibration -40 C - 250 C"],
            30,
        ),
        ASSESSMENT_MANAGER,
    )

    validate_error(response, ERR_DUPLICATE_ACTIVE_APPLICATION, 409)
    rows = assert_total_count(
        client.list_applications(
            ASSESSMENT_MANAGER,
            {"organization_id": organization["id"], "scheme_id": scheme_a["id"]},
        ),
        1,
    )
    assert rows[0]["id"] == first["id"]
    other_programme = client.create_application(
        f.application_payload(
            organization["id"],
            scheme_b["id"],
            CYCLE_INITIAL,
            ["temperature calibration -40 C - 250 C"],
            30,
        ),
        ASSESSMENT_MANAGER,
    )
    validate_success(other_programme, 201)
