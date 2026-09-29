"""Breadth probes over the declared error identifiers.

Each probe drives its refusals and then repeats the identical request in a form
that must succeed, so an implementation cannot pass by refusing everything.
"""

from prd_bench_local_runner.testing import validate_error, validate_paginated, validate_success

from test_helpers import assertions as a
from test_helpers import factories, fixtures
from test_helpers.api_errors import ApiErrorId
from test_helpers.constants import (
    CLOSURE_STATE_ACTIVE,
    CLOSURE_STATE_CLOSURE_PLANNED,
    DEFAULT_LIMIT,
    DOC_SHA256_ALT,
    DOC_URI_ALT,
    GHOST_UUID,
    PLAN_STATUS_COST_CERTIFIED,
    POSTING_CLOSURE_PLAN,
    POSTING_STABILITY_ASSESSMENT,
    POSTURE_COMPLIANT,
    TIMELINESS_PENDING,
)
from test_helpers.test_users import (
    UTILITY_ADMIN_HEADERS,
    headers_with_empty_role,
    headers_with_undeclared_role,
    make_engineer_headers,
    make_hydrogeologist_headers,
)


def test_the_three_authentication_gates_stay_distinguishable(api):
    """An empty role is 401, an undeclared role is 403, and an unknown professional is 404.

    PRD: If either header is absent, or is present but sent as the empty string, the request is rejected with `ERR_UNAUTHENTICATED` (HTTP 401); a header whose value is the empty string is treated exactly as if it had never been sent. If both headers are present but the declared role is not one of the seven roles below, or is a recognised role that the target endpoint does not admit, the request is rejected with `ERR_UNAUTHORIZED` (HTTP 403).
    PRD: a missing `QualifiedProfessional` reference — whether it arrived as the acting header identity of an entity-backed role or as a professional identifier in a request body — yields `ERR_PROFESSIONAL_NOT_FOUND`.
    Design: Corner/errors/unauthenticated_unknown_role_and_unknown_professional_are_rejected
    """
    hydro = fixtures.register_professional(api, factories.hydrogeologist_payload())
    caller = UTILITY_ADMIN_HEADERS["X-User-ID"]

    validate_error(
        api.list_units(headers_with_empty_role(caller)), ApiErrorId.UNAUTHENTICATED.value
    )
    validate_error(
        api.list_units(headers_with_undeclared_role(caller)), ApiErrorId.UNAUTHORIZED.value
    )
    validate_error(
        api.list_sampling_events(make_hydrogeologist_headers(GHOST_UUID)),
        ApiErrorId.PROFESSIONAL_NOT_FOUND.value,
    )

    rows, meta = validate_paginated(
        api.list_sampling_events(make_hydrogeologist_headers(hydro["id"]))
    )

    assert rows == []
    a.assert_page_meta(meta, DEFAULT_LIMIT, 0, 0, False)


def test_the_discipline_gate_is_independent_of_the_role_gate(api):
    """Three refusals with the right role and the wrong licence, then the qualified signature.

    PRD: Filing a structural stability assessment and signing the engineering half of a closure plan both require `GEOTECHNICAL` or `CIVIL`. Signing the cost half of a closure plan requires `CIVIL` and nothing else. Certifying closure construction complete, recording a cap inspection, and certifying post-closure care complete all require `CIVIL` or `GEOTECHNICAL`. Every well operation, every sampling-round operation and the network certification require `HYDROGEOLOGY`. Issuing a statistical evaluation requires `STATISTICS`. A professional whose discipline is outside the admitted set for the operation is refused with `ERR_DISCIPLINE_NOT_QUALIFIED` (HTTP 403).
    Design: Corner/errors/discipline_gate_rejects_the_wrong_discipline_on_three_endpoints
    """
    world = fixtures.seed_unit(api, "IMP-0144")
    plan = fixtures.draft_plan(api, world, "CP-0144")

    wrong_cost_signer = api.certify_plan_cost(
        plan["id"], factories.cost_certification_payload("2026-08-01"), world["geotech_headers"]
    )
    validate_error(wrong_cost_signer, ApiErrorId.DISCIPLINE_NOT_QUALIFIED.value)

    wrong_assessor = api.create_stability_assessment(
        factories.stability_payload(world["unit_id"], "2026-07-15"),
        make_engineer_headers(world["hydro_id"]),
    )
    validate_error(wrong_assessor, ApiErrorId.DISCIPLINE_NOT_QUALIFIED.value)

    wrong_well_installer = api.create_well(
        factories.background_well_payload(world["unit_id"], "BG-01"),
        make_hydrogeologist_headers(world["stats_id"]),
    )
    validate_error(wrong_well_installer, ApiErrorId.DISCIPLINE_NOT_QUALIFIED.value)

    signed = validate_success(
        api.certify_plan_cost(
            plan["id"], factories.cost_certification_payload("2026-08-01"), world["civil_headers"]
        )
    )

    assert signed["cost_certified_by"] == world["civil_id"]
    a.assert_date(signed["cost_certified_on"], "2026-08-01", "cost_certified_on")
    assert signed["status"] == PLAN_STATUS_COST_CERTIFIED
    assert signed["engineering_certified_by"] is None

    _, assessments = validate_paginated(
        api.list_stability_assessments(UTILITY_ADMIN_HEADERS, {"unit_id": world["unit_id"]})
    )
    assert assessments["total_count"] == 0
    _, wells = validate_paginated(
        api.list_wells(UTILITY_ADMIN_HEADERS, {"unit_id": world["unit_id"]})
    )
    assert wells["total_count"] == 0


def test_the_missing_plan_and_the_missed_deadline_are_reported_separately(api):
    """The state gate passes an ACTIVE unit through so the real diagnosis surfaces.

    PRD: The unit's `closure_state` check admits both `ACTIVE` and `CLOSURE_PLANNED`, so a unit with no approved plan gets past it and is then refused by the approved-plan gate with `ERR_NO_APPROVED_CLOSURE_PLAN` (HTTP 409) — the diagnosis a caller actually needs — rather than being masked by a generic invalid-state refusal. Before that, a `FROZEN` unit is refused with `ERR_UNIT_FROZEN`. And after it, the current date must be on or before the unit's `closure_deadline_date`, or the refusal is `ERR_CLOSURE_DEADLINE_MISSED` (HTTP 409); a unit sitting exactly on its deadline may still begin.
    PRD: It is `PENDING` while `closure_initiated_on` is still null.
    Design: Corner/errors/begin_closure_separates_the_missing_plan_from_the_missed_deadline
    """
    planless = fixtures.seed_unit(api, "IMP-0145")
    unplanned = api.begin_closure(
        planless["unit_id"], factories.begin_closure_payload("2026-08-01"), UTILITY_ADMIN_HEADERS
    )
    validate_error(unplanned, ApiErrorId.NO_APPROVED_CLOSURE_PLAN.value)
    assert fixtures.read_unit(api, planless["unit_id"])["closure_state"] == CLOSURE_STATE_ACTIVE

    approved = fixtures.seed_unit(api, "IMP-0146")
    fixtures.file_stability(api, approved, "2026-07-15")
    fixtures.post_document(api, approved, POSTING_STABILITY_ASSESSMENT, "2026-08-01")
    plan = fixtures.draft_plan(api, approved, "CP-0146")
    fixtures.certify_plan_both_halves(api, approved, plan["id"], "2026-08-01")
    fixtures.approve_plan(api, plan["id"], "2026-08-01", "PERMIT-2026-D")
    fixtures.post_document(
        api,
        approved,
        POSTING_CLOSURE_PLAN,
        "2026-08-01",
        document_uri=DOC_URI_ALT,
        document_sha256=DOC_SHA256_ALT,
    )

    fixtures.set_clock(api, "2031-04-01T00:00:00Z")

    unfrozen = fixtures.read_unit(api, approved["unit_id"])
    assert unfrozen["compliance_posture"] == POSTURE_COMPLIANT
    assert unfrozen["overdue_posting_types"] == []

    too_late = api.begin_closure(
        approved["unit_id"], factories.begin_closure_payload("2031-04-01"), UTILITY_ADMIN_HEADERS
    )

    validate_error(too_late, ApiErrorId.CLOSURE_DEADLINE_MISSED.value)
    unit = fixtures.read_unit(api, approved["unit_id"])
    assert unit["closure_state"] == CLOSURE_STATE_CLOSURE_PLANNED
    assert unit["closure_initiated_on"] is None
    assert unit["closure_timeliness"] == TIMELINESS_PENDING
    a.assert_date(unit["closure_deadline_date"], "2031-03-31", "closure_deadline_date")
    assert unit["granted_extension_months"] == 0
