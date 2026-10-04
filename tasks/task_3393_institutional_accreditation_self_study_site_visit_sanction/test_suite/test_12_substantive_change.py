"""Substantive change requests: accreditation gate, sanction gate, dues gate,
state-before-fiscal ordering, and status-filtered listing."""
from test_helpers import (
    ARREARS_AFTER_FTE_900,
    DUES_900_A_B,
    ApiErrorId,
    apply_sanction_transition,
    change_request_payload,
    create_candidate_institution,
    create_change_request,
    get_institution,
    list_change_requests,
    make_liaison_headers,
    patch_institution,
    setup_accredited_institution,
    setup_panel_band_sanction,
    submit_change_request,
    validate_error,
    validate_paginated,
)


def test_change_request_requires_accredited_institution(api):
    """PRD section 3.9: "Drafting is restricted to institutions whose `accreditation_status` is `ACCREDITED` — drafting against any other standing is rejected with `ERR_INSTITUTION_NOT_ACCREDITED` (HTTP 409) — and the request records its institution on `institution_id` and is born in `DRAFT`."

    Design: Difficulty/cross_entity_state_dependency/substantive_change_gated_on_accredited_institution
    """
    ctx = create_candidate_institution()
    institution_id = ctx["institution"]["id"]

    response = api.create_substantive_change_request(
        institution_id,
        change_request_payload("DISTANCE_DELIVERY"),
        make_liaison_headers(institution_id),
    )
    validate_error(response, ApiErrorId.ERR_INSTITUTION_NOT_ACCREDITED)
    assert list_change_requests(institution_id) == []


def test_probation_blocks_change_submit(api):
    """PRD section 3.9: "Submission is gated twice, in a pinned order: first the institution's `sanction_status` must be `NONE` or `NOTICE` — a request submitted while the institution sits at `PROBATION` or `SHOW_CAUSE` is rejected with `ERR_SANCTION_BLOCKS_CHANGE` — and then `outstanding_dues_cents` must be zero, arrears being rejected with `ERR_DUES_ARREARS` (HTTP 402)."

    Design: Corner/validations/sanction_blocks_substantive_change_submit
    """
    ctx = setup_accredited_institution()
    institution_id = ctx["institution"]["id"]
    change = create_change_request(institution_id, "NEW_LOCATION")

    outcome_id = setup_panel_band_sanction(institution_id)["outcome"]["id"]
    escalated = apply_sanction_transition(outcome_id, "ESCALATE")
    assert escalated["sanction_level"] == "PROBATION"

    response = api.submit_substantive_change(
        change["id"], {}, make_liaison_headers(institution_id)
    )
    validate_error(response, ApiErrorId.ERR_SANCTION_BLOCKS_CHANGE)
    assert list_change_requests(institution_id)[0]["status"] == "DRAFT"


def test_dues_arrears_blocks_change_submit(api):
    """PRD section 3.9: "Submission is gated twice, in a pinned order: first the institution's `sanction_status` must be `NONE` or `NOTICE` — a request submitted while the institution sits at `PROBATION` or `SHOW_CAUSE` is rejected with `ERR_SANCTION_BLOCKS_CHANGE` — and then `outstanding_dues_cents` must be zero, arrears being rejected with `ERR_DUES_ARREARS` (HTTP 402)."

    Design: Corner/validations/dues_arrears_blocks_change_submit
    """
    ctx = setup_accredited_institution()
    institution_id = ctx["institution"]["id"]

    patched = patch_institution(institution_id, fte_enrollment=900)
    assert patched["current_annual_dues_cents"] == DUES_900_A_B
    assert patched["outstanding_dues_cents"] == ARREARS_AFTER_FTE_900

    change = create_change_request(institution_id, "DISTANCE_DELIVERY")
    response = api.submit_substantive_change(
        change["id"], {}, make_liaison_headers(institution_id)
    )
    validate_error(response, ApiErrorId.ERR_DUES_ARREARS)
    assert list_change_requests(institution_id)[0]["status"] == "DRAFT"


def test_state_error_precedes_dues_error_on_resubmit(api):
    """PRD section 2.8: "A request that would fail several checks receives the error of the first check in the evaluation order — the first failure wins."
    PRD section 2.8: "The global order is: (1) authentication of the two headers, failing as `ERR_UNAUTHENTICATED`; (2) role permission and entity-backed ownership, failing as `ERR_UNAUTHORIZED_ROLE`; (3) existence of every identifier in the path, validated left to right, where the first unresolved identifier produces the not-found code belonging to its own path root — one of `ERR_INSTITUTION_NOT_FOUND`, `ERR_ELIGIBILITY_APPLICATION_NOT_FOUND`, `ERR_REVIEW_CYCLE_NOT_FOUND`, `ERR_ASSURANCE_ARGUMENT_NOT_FOUND`, `ERR_EVIDENCE_ITEM_NOT_FOUND`, `ERR_REVIEWER_NOT_FOUND`, `ERR_REVIEW_TEAM_NOT_FOUND`, `ERR_TEAM_ASSIGNMENT_NOT_FOUND`, `ERR_DECISION_PANEL_NOT_FOUND`, `ERR_ACTION_OUTCOME_NOT_FOUND`, `ERR_SUBSTANTIVE_CHANGE_NOT_FOUND`, or `ERR_INDICATOR_REPORT_NOT_FOUND`, each an HTTP 404; (4) state-machine checks — whether the target resource stands in a state that permits the requested transition, failing as `ERR_INVALID_STATE` — together with the creation guards on review cycles (`ERR_CYCLE_ALREADY_OPEN`) and substantive-change requests (`ERR_INSTITUTION_NOT_ACCREDITED`); and finally (5) the business rules of the endpoint — safety, constraint, temporal, referential, and fiscal checks — each named where it applies in §3."

    Design: Difficulty/priority_pair_validation_conflict/priority_state_over_fiscal_on_change_resubmit_rejected
    """
    ctx = setup_accredited_institution()
    institution_id = ctx["institution"]["id"]
    change = create_change_request(institution_id, "NEW_LOCATION")
    submit_change_request(change["id"], institution_id)

    patched = patch_institution(institution_id, fte_enrollment=900)
    assert patched["current_annual_dues_cents"] == DUES_900_A_B
    assert patched["outstanding_dues_cents"] == ARREARS_AFTER_FTE_900

    # The change is already SUBMITTED (state violation) and arrears are armed
    # (fiscal violation); the state error must win.
    response = api.submit_substantive_change(
        change["id"], {}, make_liaison_headers(institution_id)
    )
    validate_error(response, ApiErrorId.ERR_INVALID_STATE)


def test_change_request_list_filters_by_status(api, staff_headers):
    """PRD section 2.3: "Beyond pagination, several directories expose filter parameters that the workflow narratives rely on: the institution directory filters on `accreditation_status`, `sanction_status`, and `legal_status`; the review-cycle, substantive-change, and indicator-report listings filter on `status`; an argument's evidence listing filters on `criterion_code`; a team's assignment listing filters on `reviewer_id`; and the reviewer directory filters on `affiliation_institution_id`, `specialty`, and `is_active`."

    Design: Corner/endpoints/substantive_change_list_filters_by_status
    """
    ctx = setup_accredited_institution()
    institution_id = ctx["institution"]["id"]

    change_a = create_change_request(institution_id, "NEW_LOCATION")
    submit_change_request(change_a["id"], institution_id)
    change_b = create_change_request(institution_id, "DISTANCE_DELIVERY")

    drafts, meta_draft = validate_paginated(
        api.list_substantive_change_requests(
            institution_id, staff_headers, params={"status": "DRAFT"}
        )
    )
    assert [c["id"] for c in drafts] == [change_b["id"]]
    assert meta_draft["total_count"] == 1

    submitted, meta_submitted = validate_paginated(
        api.list_substantive_change_requests(
            institution_id, staff_headers, params={"status": "SUBMITTED"}
        )
    )
    assert [c["id"] for c in submitted] == [change_a["id"]]
    assert meta_submitted["total_count"] == 1
