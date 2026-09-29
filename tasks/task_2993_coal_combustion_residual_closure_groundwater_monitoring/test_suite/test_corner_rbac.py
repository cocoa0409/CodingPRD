"""Breadth probes over the role model.

The seven roles are peers rather than a hierarchy, the PublicViewer surface is
exactly three routes wide, and the two closure-plan signatures must come from
two different people even when one person is qualified for both.
"""

from prd_bench_local_runner.testing import validate_error, validate_paginated, validate_success

from test_helpers import assertions as a
from test_helpers import factories, fixtures
from test_helpers.api_errors import ApiErrorId
from test_helpers.constants import (
    GHOST_UUID,
    METHOD_CLOSURE_IN_PLACE,
    PLAN_STATUS_DRAFT,
    PLAN_STATUS_ENGINEERING_CERTIFIED,
    PLAN_STATUS_FULLY_CERTIFIED,
    POSTING_ANNUAL_GW_REPORT,
    POSTING_STABILITY_ASSESSMENT,
    POSTING_STATUS_POSTED,
    POSTURE_COMPLIANT,
    STABILITY_ADEQUATE,
)
from test_helpers.test_users import (
    COMPLIANCE_OFFICER_HEADERS,
    PUBLIC_VIEWER_HEADERS,
    REGULATOR_HEADERS,
    UTILITY_ADMIN_HEADERS,
    make_statistical_reviewer_headers,
)


def test_no_role_may_reach_into_another_roles_exclusive_operation(api):
    """Four exclusive operations refused across four roles, then the owning role succeeds.

    PRD: If both headers are present but the declared role is not one of the seven roles below, or is a recognised role that the target endpoint does not admit, the request is rejected with `ERR_UNAUTHORIZED` (HTTP 403).
    PRD: 2. The declared role is one of the seven and is admitted by the target endpoint, else `ERR_UNAUTHORIZED`.
    Design: Corner/rbac/each_role_cannot_perform_another_roles_exclusive_operation
    """
    world = fixtures.seed_unit(api, "IMP-0147")
    plan = fixtures.draft_plan(api, world, "CP-0147")
    posting = factories.posting_payload(
        world["unit_id"], "2026-08-01", POSTING_ANNUAL_GW_REPORT
    )

    validate_error(
        api.create_unit(factories.unit_payload("IMP-0147X"), REGULATOR_HEADERS),
        ApiErrorId.UNAUTHORIZED.value,
    )
    validate_error(
        api.approve_closure_plan(
            plan["id"], factories.approve_plan_payload("2026-08-01", "PERMIT-2026-E"),
            UTILITY_ADMIN_HEADERS,
        ),
        ApiErrorId.UNAUTHORIZED.value,
    )
    validate_error(
        api.create_statistical_evaluation(
            factories.evaluation_payload(world["program_id"], GHOST_UUID, "EV-CO"),
            COMPLIANCE_OFFICER_HEADERS,
        ),
        ApiErrorId.UNAUTHORIZED.value,
    )
    validate_error(
        api.create_public_posting(posting, make_statistical_reviewer_headers(world["stats_id"])),
        ApiErrorId.UNAUTHORIZED.value,
    )

    accepted = validate_success(
        api.create_public_posting(posting, COMPLIANCE_OFFICER_HEADERS), 201
    )

    assert accepted["status"] == POSTING_STATUS_POSTED
    assert accepted["posting_type"] == POSTING_ANNUAL_GW_REPORT

    _, units = validate_paginated(api.list_units(UTILITY_ADMIN_HEADERS))
    assert units["total_count"] == 1
    assert (
        validate_success(api.get_closure_plan(plan["id"], UTILITY_ADMIN_HEADERS))["status"]
        == PLAN_STATUS_DRAFT
    )
    _, evaluations = validate_paginated(api.list_statistical_evaluations(UTILITY_ADMIN_HEADERS))
    assert evaluations["total_count"] == 0


def test_the_public_viewer_sees_the_public_record_and_not_the_unit_row(api):
    """Three open routes answer 200 while the neighbouring unit detail route answers 403.

    PRD: A separate compliance rollup exists for the public and for oversight readers, and it is the only unit read a `PublicViewer` may perform besides browsing the postings.
    PRD: 2. The declared role is one of the seven and is admitted by the target endpoint, else `ERR_UNAUTHORIZED`.
    Design: Corner/rbac/public_viewer_reads_the_public_record_and_nothing_else
    """
    world = fixtures.seed_unit(api, "IMP-0148")
    fixtures.file_stability(api, world, "2026-07-15")
    posting = fixtures.post_document(api, world, POSTING_STABILITY_ASSESSMENT, "2026-08-01")

    listed, meta = validate_paginated(api.list_public_postings(PUBLIC_VIEWER_HEADERS))
    assert meta["total_count"] == 1
    assert meta["has_more"] is False
    assert [row["id"] for row in listed] == [posting["id"]]

    detail = validate_success(api.get_public_posting(posting["id"], PUBLIC_VIEWER_HEADERS))
    assert detail["status"] == POSTING_STATUS_POSTED
    assert detail["satisfied_obligation"] is True
    assert detail["days_late"] == 0

    summary = validate_success(
        api.get_compliance_summary(world["unit_id"], PUBLIC_VIEWER_HEADERS)
    )
    assert summary["compliance_posture"] == POSTURE_COMPLIANT
    assert summary["governing_stability_verdict"] == STABILITY_ADEQUATE

    validate_error(
        api.get_unit(world["unit_id"], PUBLIC_VIEWER_HEADERS), ApiErrorId.UNAUTHORIZED.value
    )

    internal = validate_success(api.get_unit(world["unit_id"], COMPLIANCE_OFFICER_HEADERS))
    assert internal["unit_code"] == "IMP-0148"


def test_one_engineer_cannot_sign_both_halves_of_the_same_plan(api):
    """The second signature differs only in X-User-ID, and that alone decides it.

    PRD: Whichever order is used, the second signer's `X-User-ID` must differ from the identity already recorded on the other half, or the request is refused with `ERR_SEGREGATION_OF_DUTIES` (HTTP 403).
    PRD: The cost half is signed by a `ProfessionalEngineer` whose discipline is `CIVIL` and nothing else
    Design: Corner/rbac/same_engineer_cannot_sign_both_certifications_on_one_plan
    """
    world = fixtures.seed_unit(api, "IMP-0149")
    fixtures.file_stability(api, world, "2026-07-15")
    plan = fixtures.draft_plan(api, world, "CP-0149")
    engineering = validate_success(
        api.certify_plan_engineering(
            plan["id"],
            factories.engineering_certification_payload("2026-08-01"),
            world["civil_headers"],
        )
    )
    assert engineering["status"] == PLAN_STATUS_ENGINEERING_CERTIFIED
    assert engineering["engineering_certified_by"] == world["civil_id"]

    conflicted = api.certify_plan_cost(
        plan["id"], factories.cost_certification_payload("2026-08-01"), world["civil_headers"]
    )

    validate_error(conflicted, ApiErrorId.SEGREGATION_OF_DUTIES.value)
    held = validate_success(api.get_closure_plan(plan["id"], UTILITY_ADMIN_HEADERS))
    assert held["cost_certified_by"] is None
    assert held["status"] == PLAN_STATUS_ENGINEERING_CERTIFIED

    signed = validate_success(
        api.certify_plan_cost(
            plan["id"],
            factories.cost_certification_payload("2026-08-01"),
            world["second_civil_headers"],
        )
    )

    assert signed["status"] == PLAN_STATUS_FULLY_CERTIFIED
    assert signed["cost_certified_by"] == world["second_civil_id"]
    a.assert_cents(signed["in_place_pv_usd_cents"], 119600444, "in_place_pv_usd_cents")
    a.assert_cents(signed["removal_pv_usd_cents"], 919600444, "removal_pv_usd_cents")
    assert signed["recommended_method"] == METHOD_CLOSURE_IN_PLACE
