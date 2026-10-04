"""Validation corners I: authentication, existence-before-state ordering,
optimistic-concurrency stale versions, segregation of duties, entity-backed
ownership, per-dimension review outcomes, and the MOQ floor at acceptance.
"""

from test_helpers import (
    NON_EXISTENT_UUID,
    PRODUCT_MANAGER_USER_ID,
    TEST_USERS,
    ApiErrorId,
    create_cost_quote_payload,
    create_line_review,
    create_manufacturer,
    create_partner,
    create_planogram_slot_payload,
    create_quote,
    create_slot,
    create_trend_signal_payload,
    evaluate_quote,
    make_manufacturer_rep_headers,
    make_retail_planner_headers,
    open_dossier,
    open_line_review,
    propose_discontinuation,
    read_cost_quote,
    read_discontinuation_review,
    read_dossier,
    read_line_review,
    read_product,
    set_clock,
    setup_compliance_gate_product,
    setup_executed_plan,
    setup_launch_ready_product,
    setup_sourcing_product,
    validate_error,
    validate_paginated,
)

_SCOUT = TEST_USERS["trend_scout_headers"]
_PM = TEST_USERS["product_manager_headers"]
_SOURCING = TEST_USERS["sourcing_lead_headers"]
_COMPLIANCE = TEST_USERS["compliance_officer_headers"]
_PLANNER = TEST_USERS["retail_planner_headers"]


def test_trend_create_without_identity_headers_is_unauthenticated(api):
    """PRD §2.1: "Every request carries two headers: `X-User-ID`, identifying
    the acting user, and `X-User-Role`, naming the acting role. A request
    missing either header, or carrying a role name that is not one of the
    declared roles, is rejected with `ERR_UNAUTHENTICATED` (HTTP 401) before
    any other check runs."

    Design: Corner/validations/trend_create_missing_auth_returns_unauthenticated
    """
    set_clock()

    response = api.create_trend_signal(create_trend_signal_payload(), headers=None)

    validate_error(response, ApiErrorId.ERR_UNAUTHENTICATED.value)
    rows, meta = validate_paginated(api.list_trend_signals(headers=_SCOUT))
    assert meta["total_count"] == 0


def test_product_patch_unknown_id_resolves_existence_before_state(api):
    """PRD §2.8: "Fourth, path identifiers resolve, checked left to right
    (else the entity-specific not-found error, such as
    `ERR_PRODUCT_NOT_FOUND` or `ERR_LINE_REVIEW_NOT_FOUND`)." — evaluated
    before "Seventh, state-machine from-state validity, ... (else
    `ERR_INVALID_STATE`)."
    A well-formed status payload on an unknown product id is a 404, never a
    409.

    Design: Corner/validations/product_patch_unknown_id_returns_not_found_before_state_check
    """
    set_clock()

    response = api.patch_product(NON_EXISTENT_UUID, {"status": "SOURCING"}, _PM)

    validate_error(response, ApiErrorId.ERR_PRODUCT_NOT_FOUND.value)


def test_quote_create_with_stale_product_version_returns_412(api):
    """PRD §2.7: "A quote creation request must carry
    `expected_product_version` equal to the `version` of the target product as
    the client last observed it; ... If the parent's current `version` has
    advanced since that observation — for example because another writer
    created a quote for the same product, or another slot was added to the
    same review — the create is rejected with `ERR_STALE_VERSION` (HTTP 412),
    so the client never writes against a view of the parent it has not
    observed."
    The product reads version 2 after the SOURCING transition; quote A's
    creation advances it to 3, so a second create still carrying 2 is stale.

    Design: Corner/validations/quote_create_with_stale_product_version_returns_412
    """
    ctx = setup_sourcing_product()
    stale_version = ctx["product"]["version"]
    create_quote(ctx["product"]["id"], ctx["manufacturer"]["id"])
    assert read_product(ctx["product"]["id"])["version"] == stale_version + 1

    response = api.create_cost_quote(
        create_cost_quote_payload(
            product_id=ctx["product"]["id"],
            contract_manufacturer_id=ctx["manufacturer"]["id"],
            unit_cost_cents=210,
            expected_product_version=stale_version,
        ),
        make_manufacturer_rep_headers(ctx["manufacturer"]["id"]),
    )

    validate_error(response, ApiErrorId.ERR_STALE_VERSION.value)
    rows, meta = validate_paginated(
        api.list_cost_quotes(headers=_SOURCING, params={"product_id": ctx["product"]["id"]})
    )
    assert meta["total_count"] == 1
    assert rows[0]["status"] == "SUBMITTED"


def test_slot_create_with_stale_line_review_version_returns_412(api):
    """PRD §2.7: "...a slot creation request must carry
    `expected_line_review_version` equal to the `version` of the target line
    review as the client last observed it. If the parent's current `version`
    has advanced since that observation ... the create is rejected with
    `ERR_STALE_VERSION` (HTTP 412)..."
    The first slot creation bumps the open review 2 -> 3; a second create
    carrying 2 is stale.

    Design: Corner/validations/slot_create_with_stale_line_review_version_returns_412
    """
    ctx = setup_launch_ready_product()
    ctx["partner"] = create_partner()
    ctx["line_review"] = create_line_review(ctx["partner"]["id"])
    ctx["line_review"] = open_line_review(ctx["line_review"]["id"])
    stale_version = ctx["line_review"]["version"]
    create_slot(ctx["line_review"]["id"], ctx["product"]["id"])
    assert read_line_review(ctx["line_review"]["id"])["version"] == stale_version + 1

    response = api.create_planogram_slot(
        create_planogram_slot_payload(
            line_review_id=ctx["line_review"]["id"],
            product_id=ctx["product"]["id"],
            position_code="EYES-A2",
            facings=2,
            expected_line_review_version=stale_version,
        ),
        _PLANNER,
    )

    validate_error(response, ApiErrorId.ERR_STALE_VERSION.value)
    rows, meta = validate_paginated(
        api.list_planogram_slots(
            headers=_PLANNER, params={"line_review_id": ctx["line_review"]["id"]}
        )
    )
    assert meta["total_count"] == 1


def test_discontinuation_decided_by_proposer_is_segregation_of_duties(api):
    """PRD §3.9: "Both approval and rejection enforce segregation of duties:
    the decider's `X-User-ID` must differ from `proposed_by_user_id`, else the
    decision is rejected with `ERR_SEGREGATION_OF_DUTIES`."
    The review was proposed by pm-nadia; an approval carrying the RetailPlanner
    role but the same X-User-ID is a 403.

    Design: Corner/validations/discontinuation_approve_by_proposing_user_returns_forbidden
    """
    ctx = setup_executed_plan()
    review = propose_discontinuation(ctx["product"]["id"], reason="PERFORMANCE")

    response = api.patch_discontinuation_review(
        review["id"],
        {"status": "APPROVED"},
        make_retail_planner_headers(PRODUCT_MANAGER_USER_ID),
    )

    validate_error(response, ApiErrorId.ERR_SEGREGATION_OF_DUTIES.value)
    assert read_discontinuation_review(review["id"])["status"] == "PROPOSED"
    assert read_product(ctx["product"]["id"])["status"] == "LAUNCHED"


def test_manufacturer_rep_cannot_quote_for_a_foreign_manufacturer(api):
    """PRD §3.5: "A quote creation names the `product_id` and the
    `contract_manufacturer_id` — which must equal the caller's `X-User-ID`
    when the caller is a `ManufacturerRep`, else `ERR_FORBIDDEN_ROLE` — ..."
    A rep whose X-User-ID is FastLab submitting a quote that names
    SecondSource is a 403; no quote is persisted.

    Design: Corner/validations/manufacturer_rep_quote_for_foreign_cm_forbidden
    """
    ctx = setup_sourcing_product()
    foreign = create_manufacturer(
        name="SecondSource Labs", capabilities=["EYES"], base_lead_time_weeks=6
    )

    response = api.create_cost_quote(
        create_cost_quote_payload(
            product_id=ctx["product"]["id"],
            contract_manufacturer_id=foreign["id"],
            expected_product_version=read_product(ctx["product"]["id"])["version"],
        ),
        make_manufacturer_rep_headers(ctx["manufacturer"]["id"]),
    )

    validate_error(response, ApiErrorId.ERR_FORBIDDEN_ROLE.value)
    rows, meta = validate_paginated(
        api.list_cost_quotes(headers=_SOURCING, params={"product_id": ctx["product"]["id"]})
    )
    assert meta["total_count"] == 0


def test_review_outcome_must_belong_to_the_requested_dimension(api):
    """PRD §3.6: "An outcome that is not a member of the requested dimension's
    outcome set is rejected with `ERR_INVALID_REQUEST`."
    CERTIFIED is a certification outcome; on the ingredient dimension it is a
    400, not a state error, and the dimension stays PENDING.

    Design: Corner/validations/review_dimension_outcome_mismatch_invalid_request
    """
    ctx = setup_compliance_gate_product()
    dossier = open_dossier(ctx["product"]["id"])

    response = api.submit_dossier_review(
        dossier["id"], {"dimension": "INGREDIENT", "outcome": "CERTIFIED"}, _COMPLIANCE
    )

    validate_error(response, ApiErrorId.ERR_INVALID_REQUEST.value)
    assert read_dossier(dossier["id"])["ingredient_status"] == "PENDING"


def test_quote_accept_below_moq_rejected(api):
    """PRD §3.5: "...the `initial_order_qty` must meet the manufacturer's
    `moq_units`, else `ERR_BELOW_MOQ`; ..."
    The quote's 400 units fall below the 500-unit MOQ even though its landed
    cost (200 + ceil(10000/400)=25 + 4 + 20 == 249) passes the 260-cent
    target — the constraint error, not the fiscal one, fires.

    Design: Corner/validations/quote_accept_below_moq_rejected
    """
    ctx = setup_sourcing_product()
    quote = create_quote(
        ctx["product"]["id"], ctx["manufacturer"]["id"], initial_order_qty=400
    )
    assert quote["landed_provisional_cents"] == 249
    evaluate_quote(quote["id"])

    response = api.patch_cost_quote(quote["id"], {"status": "ACCEPTED"}, _SOURCING)

    error = validate_error(response, ApiErrorId.ERR_BELOW_MOQ.value)
    assert error["error_id"] != ApiErrorId.ERR_COST_TARGET_EXCEEDED.value
    assert read_cost_quote(quote["id"])["status"] == "UNDER_EVALUATION"
