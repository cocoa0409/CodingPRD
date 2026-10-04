"""Difficulty depth index: priority-pair validation conflicts. The PRD fixes
a single evaluation order and lets the first failing check determine the
error, so a request violating two checks at once must surface the earlier one.
"""
from test_helpers import (
    HTTP_STATUS_CODES,
    ApiClient,
    ApiErrorId,
    PROJECT_ENGINEER_HEADERS,
    create_coating_system,
    create_specification,
    create_work_order,
    create_world,
    issue_payload,
    read_project,
    read_specification,
    validate_error,
    validate_error_is_one_of,
    warranty_payload,
)


def test_spec_issue_state_beats_voc_business_safety(api: ApiClient):
    """PRD §2.9: "When several checks could reject the same request, the
    server evaluates them in a fixed priority order, and the first failing
    check determines the error returned."
    PRD §3.4: "no other specification on this project may currently be
    `ISSUED` unless this issuance supersedes it through the draft's
    `supersedes_specification_id` link (`ERR_ACTIVE_SPEC_EXISTS`)".

    Note: §2.9's ordered priority list places VOC compliance at item 6 but
    never names ERR_ACTIVE_SPEC_EXISTS (the item-4 alias enumeration omits
    it), so the PRD does not uniquely derive which of the two rejections a
    doubly-violating issuance surfaces; the assertion accepts either.

    Design: Difficulty/priority_pair_validation_conflict/spec_issue_state_beats_voc_business_safety
    """
    world = create_world(api, system_overrides={"system_code": "SW-OK-100", "base_voc_gpl": 300})
    project_id = world["project"]["id"]
    non_compliant_system = create_coating_system(
        api, system_code="SW-BAD-900", base_voc_gpl=500
    )
    spec_b = create_specification(api, project_id, non_compliant_system["id"])
    project_now = read_project(api, project_id)

    response = api.issue_specification(
        project_id, spec_b["id"],
        issue_payload(project_now["version"]),
        PROJECT_ENGINEER_HEADERS,
    )

    # Both preconditions are broken at once: a sibling specification is ISSUED
    # (ERR_ACTIVE_SPEC_EXISTS, §3.4) and the draft's as-supplied VOC breaches
    # the covering regulation's limit (ERR_VOC_LIMIT_EXCEEDED, §2.9 item 6).
    # §2.9's fixed priority order never names ERR_ACTIVE_SPEC_EXISTS — the
    # item-4 state-precondition alias list omits it — so the relative order of
    # these two checks is not uniquely derivable from the PRD and either
    # rejection is conformant. What is pinned: one of the two fires and a
    # rejected issue mutates nothing.
    actual = validate_error_is_one_of(
        response, [ApiErrorId.ERR_ACTIVE_SPEC_EXISTS, ApiErrorId.ERR_VOC_LIMIT_EXCEEDED]
    )
    assert response.status_code == HTTP_STATUS_CODES[ApiErrorId(actual)]
    assert read_specification(api, spec_b["id"])["status"] == "DRAFT", (
        "a rejected issue mutates nothing"
    )


def test_warranty_issue_fiscal_beats_referential(api: ApiClient):
    """PRD §2.9: "When several checks could reject the same request, the
    server evaluates them in a fixed priority order, and the first failing
    check determines the error returned." — with "The warranty budget gate"
    at item 16 and "Referential linkability of named resources" at item 17.
    PRD §3.7: "the project's `committed_warranty_exposure_cents` plus the new
    `exposure_cents` must not exceed its `warranty_budget_cents`; the boundary
    is inclusive, so landing exactly on the budget is allowed and only a
    strictly greater sum is rejected with `ERR_WARRANTY_BUDGET_EXCEEDED`
    (HTTP 422)."

    Design: Difficulty/priority_pair_validation_conflict/warranty_issue_fiscal_beats_referential
    """
    world = create_world(
        api,
        asset_type="STRUCTURAL_STEEL",
        warranty_budget_cents=50_000,
        system_overrides={"system_code": "SW-FIS-100"},
        applicator_overrides={"company_name": "Depot Floor Crews"},
    )
    project_id = world["project"]["id"]
    work_order = create_work_order(
        api, project_id, world["spec"]["id"], world["applicator"]["id"], asset_zone="FLOOR-A"
    )

    # Both rules are broken at once: the work order is SCHEDULED (not
    # COMPLETED) and the exposure breaches the budget. The fiscal gate (16)
    # precedes the referential gate (17).
    response = api.create_warranty(
        project_id,
        warranty_payload(work_order["id"], term_years=5, exposure_cents=60_000),
        PROJECT_ENGINEER_HEADERS,
    )

    validate_error(response, ApiErrorId.ERR_WARRANTY_BUDGET_EXCEEDED, expected_status=422)
    assert read_project(api, project_id)["committed_warranty_exposure_cents"] == 0, (
        "no warranty was created"
    )
