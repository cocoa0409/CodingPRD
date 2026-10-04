"""License agreements: input validation, exclusive marketing, decide branches,
window overlap semantics, pagination, and the active-grower decision gate."""
from test_helpers import (
    validate_success, validate_error, validate_paginated,
    ApiErrorId, TEST_USERS,
    create_agreement_payload, decide_agreement_payload,
    set_clock, create_variety, create_released_variety, create_grower,
    apply_for_agreement, decide_agreement, get_agreement, suspend_grower,
    make_grower_principal_headers, get_success_data,
)

ADMIN = TEST_USERS["platform_admin_headers"]
COMPLIANCE = TEST_USERS["compliance_officer_headers"]
SETTLEMENT = TEST_USERS["settlement_officer_headers"]


def test_agreement_create_bad_practice_enum_returns_400(api):
    """PRD section 3.3: "a non-empty `cultural_practice_codes` list whose
    members are drawn from `ORGANIC`, `CONVENTIONAL`, `DRIP_IRRIGATION`,
    `INTEGRATED_PEST_MANAGEMENT`, and `SOIL_FUMIGATION_FREE`".
    PRD section 2.8: "Required fields present, enum members valid, quantities
    positive, and temporal inputs well-formed — otherwise `ERR_INVALID_REQUEST`."

    Design: Corner/entities/agreement_create_bad_practice_enum_returns_400
    """
    set_clock("2026-06-01T00:00:00Z")
    variety = create_released_variety()
    grower = create_grower()
    payload = create_agreement_payload(
        grower["id"], variety["id"], cultural_practice_codes=["HYDROPONICS"])
    resp = api.create_agreement(payload, make_grower_principal_headers(grower["id"]))
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)
    rows, meta = validate_paginated(api.list_agreements(
        COMPLIANCE, params={"grower_id": grower["id"]}))
    assert rows == [] and meta["total_count"] == 0


def test_exclusive_marketing_false_rejected(api):
    """PRD section 3.3: "Exclusive marketing is not negotiable: all fruit grown
    under the agreement is marketed through the brand, and an application
    submitted with `exclusive_marketing` set to false is rejected with
    `ERR_EXCLUSIVE_MARKETING_REQUIRED`."

    Design: Corner/validations/exclusive_marketing_false_rejected
    """
    set_clock("2026-06-01T00:00:00Z")
    variety = create_released_variety()
    grower = create_grower()
    payload = create_agreement_payload(
        grower["id"], variety["id"], exclusive_marketing=False)
    resp = api.create_agreement(payload, make_grower_principal_headers(grower["id"]))
    validate_error(resp, ApiErrorId.ERR_EXCLUSIVE_MARKETING_REQUIRED)
    rows, meta = validate_paginated(api.list_agreements(
        COMPLIANCE, params={"grower_id": grower["id"]}))
    assert rows == [] and meta["total_count"] == 0


def test_agreement_decide_reject_branch_and_idempotency(api):
    """PRD section 3.3: "A decision of `REJECT` moves the agreement
    `PENDING_REVIEW → REJECTED` unconditionally and records the request's
    `reason` — which may be null — as the agreement's `reject_reason`."
    PRD section 3.3: "`REJECTED` and `TERMINATED` are the terminal states of an
    agreement."

    Design: Corner/state_machines/agreement_decide_reject_branch_and_idempotency
    """
    set_clock("2026-06-01T00:00:00Z")
    variety = create_released_variety()
    grower = create_grower()
    agreement = apply_for_agreement(grower, variety)
    resp = api.decide_agreement(
        agreement["id"],
        decide_agreement_payload("REJECT", reason="insufficient acreage history"),
        COMPLIANCE)
    data = validate_success(resp, 200)
    assert data["status"] == "REJECTED"
    assert data["reject_reason"] == "insufficient acreage history"
    assert data["decided_at"] is not None
    resp2 = api.decide_agreement(
        agreement["id"], decide_agreement_payload("APPROVE"), COMPLIANCE)
    validate_error(resp2, ApiErrorId.ERR_INVALID_STATE)


def test_decide_approve_on_development_variety_rejected(api):
    """PRD section 3.3: "A decision of `APPROVE` moves the agreement
    `PENDING_REVIEW → ACTIVE`, but only when the grower is `ACTIVE` at decision
    time (`ERR_GROWER_NOT_ACTIVE`) and the variety is `RELEASED`: a variety
    still in `DEVELOPMENT` rejects the approval with `ERR_VARIETY_NOT_RELEASED`".

    Design: Corner/errors/decide_approve_on_development_variety_rejected
    """
    set_clock("2026-06-01T00:00:00Z")
    variety = create_variety()  # never released: stays DEVELOPMENT
    grower = create_grower()
    agreement = apply_for_agreement(grower, variety)
    resp = api.decide_agreement(
        agreement["id"], decide_agreement_payload("APPROVE"), COMPLIANCE)
    validate_error(resp, ApiErrorId.ERR_VARIETY_NOT_RELEASED)
    current = get_agreement(agreement["id"])
    assert current["status"] == "PENDING_REVIEW"


def test_agreements_list_paginates_and_filters(api):
    """PRD section 3.3: "Agreements can be listed with filters on `grower_id`,
    `variety_id`, or `status`, and retrieved individually."
    PRD section 2.3: "`limit` is the maximum number of items returned; it
    defaults to 10, with a minimum of 1 and a maximum of 100. `offset` is the
    number of items skipped before the returned page and defaults to 0."

    Design: Corner/entities/agreements_list_paginates_and_filters
    """
    set_clock("2026-06-01T00:00:00Z")
    variety = create_released_variety()
    grower = create_grower()
    headers = make_grower_principal_headers(grower["id"])
    windows = [("2026-01-01T00:00:00Z", "2026-03-31T00:00:00Z"),
               ("2026-04-01T00:00:00Z", "2026-06-30T00:00:00Z"),
               ("2026-07-01T00:00:00Z", "2027-12-31T00:00:00Z")]
    ids = []
    for eff_from, eff_to in windows:
        a = get_success_data(api.create_agreement(
            create_agreement_payload(grower["id"], variety["id"],
                                     max_planting_units=1000,
                                     cultural_practice_codes=["ORGANIC"],
                                     effective_from=eff_from,
                                     effective_to=eff_to),
            headers))
        ids.append(a["id"])
    decide_agreement(ids[2], "APPROVE")
    page1, meta1 = validate_paginated(api.list_agreements(
        COMPLIANCE, params={"grower_id": grower["id"], "limit": 2, "offset": 0}))
    assert len(page1) == 2 and meta1["total_count"] == 3 and meta1["has_more"] is True
    page2, meta2 = validate_paginated(api.list_agreements(
        COMPLIANCE, params={"grower_id": grower["id"], "limit": 2, "offset": 2}))
    assert len(page2) == 1 and meta2["total_count"] == 3 and meta2["has_more"] is False
    active, meta3 = validate_paginated(api.list_agreements(
        COMPLIANCE, params={"grower_id": grower["id"], "status": "ACTIVE"}))
    assert len(active) == 1 and active[0]["id"] == ids[2]


def test_decide_approve_blocked_for_suspended_grower(api):
    """PRD section 3.3: "A decision of `APPROVE` moves the agreement
    `PENDING_REVIEW → ACTIVE`, but only when the grower is `ACTIVE` at decision
    time (`ERR_GROWER_NOT_ACTIVE`)".
    PRD section 3.2: "Suspension deliberately leaves everything else alone —
    `PENDING_REVIEW` agreements, plantings, and plant lots are untouched."

    Design: Difficulty/cross_entity_state_dependency/agreement_decide_requires_active_grower
    """
    set_clock("2026-06-01T00:00:00Z")
    variety = create_released_variety()
    grower = create_grower(legal_name="San Juan Bautista Growers")
    agreement = apply_for_agreement(grower, variety, max_planting_units=5000)
    suspend_grower(grower["id"], reason="compliance investigation")
    resp = api.decide_agreement(
        agreement["id"], decide_agreement_payload("APPROVE"), COMPLIANCE)
    validate_error(resp, ApiErrorId.ERR_GROWER_NOT_ACTIVE)
    current = get_agreement(agreement["id"])
    assert current["status"] == "PENDING_REVIEW"
    assert current["decided_at"] is None


def test_decide_reject_succeeds_for_suspended_grower(api):
    """PRD section 3.3: "A decision of `REJECT` moves the agreement
    `PENDING_REVIEW → REJECTED` unconditionally and records the request's
    `reason` — which may be null — as the agreement's `reject_reason`."

    Design: Difficulty/cross_entity_state_dependency/agreement_decide_requires_active_grower
    """
    set_clock("2026-06-01T00:00:00Z")
    variety = create_released_variety()
    grower = create_grower(legal_name="San Juan Bautista Growers")
    agreement = apply_for_agreement(grower, variety, max_planting_units=5000)
    suspend_grower(grower["id"], reason="compliance investigation")
    data = decide_agreement(agreement["id"], "REJECT", reason="grower under review")
    assert data["status"] == "REJECTED"
    assert data["reject_reason"] == "grower under review"
    assert data["decided_at"] is not None


def test_agreement_window_shared_boundary_day_overlaps(api):
    """PRD section 3.3: "the requested window must not overlap the window of any
    other non-terminal agreement of the same grower and variety — because
    agreement windows are closed intervals, two windows that share even a single
    boundary day count as overlapping, and such an application is rejected with
    `ERR_AGREEMENT_WINDOW_OVERLAP`."

    Design: Difficulty/resource_temporal_overlap/agreement_window_closed_overlap
    """
    set_clock("2026-06-01T00:00:00Z")
    variety = create_released_variety()
    grower = create_grower(legal_name="Watsonville Coast Produce")
    headers = make_grower_principal_headers(grower["id"])
    first = apply_for_agreement(
        grower, variety, max_planting_units=1000,
        cultural_practice_codes=["ORGANIC"],
        effective_from="2026-01-01T00:00:00Z",
        effective_to="2026-12-31T00:00:00Z")
    assert first["status"] == "PENDING_REVIEW"
    resp = api.create_agreement(
        create_agreement_payload(grower["id"], variety["id"],
                                 max_planting_units=500,
                                 cultural_practice_codes=["ORGANIC"],
                                 effective_from="2026-12-31T00:00:00Z",
                                 effective_to="2027-06-30T00:00:00Z"),
        headers)
    validate_error(resp, ApiErrorId.ERR_AGREEMENT_WINDOW_OVERLAP)


def test_agreement_window_day_after_boundary_accepted(api):
    """PRD section 3.3: "because agreement windows are closed intervals, two
    windows that share even a single boundary day count as overlapping, and such
    an application is rejected with `ERR_AGREEMENT_WINDOW_OVERLAP`."

    Design: Difficulty/resource_temporal_overlap/agreement_window_closed_overlap
    """
    set_clock("2026-06-01T00:00:00Z")
    variety = create_released_variety()
    grower = create_grower(legal_name="Watsonville Coast Produce")
    headers = make_grower_principal_headers(grower["id"])
    apply_for_agreement(
        grower, variety, max_planting_units=1000,
        cultural_practice_codes=["ORGANIC"],
        effective_from="2026-01-01T00:00:00Z",
        effective_to="2026-12-31T00:00:00Z")
    resp = api.create_agreement(
        create_agreement_payload(grower["id"], variety["id"],
                                 max_planting_units=500,
                                 cultural_practice_codes=["ORGANIC"],
                                 effective_from="2027-01-01T00:00:00Z",
                                 effective_to="2027-12-31T00:00:00Z"),
        headers)
    data = validate_success(resp, 201)
    assert data["status"] == "PENDING_REVIEW"
