"""Validation corners II: interval well-formedness, planogram-lock aggregate
validity, the budget clamp's MOQ floor, the LAUNCH_READY product gate, the
product-advance referential chain, suspended-manufacturer blocks, lifecycle-
scoped name uniqueness, one-dossier-per-product, and lazy quote expiry.
"""

from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    create_approved_formula,
    create_compliance_dossier_payload,
    create_concept,
    create_concept_payload,
    create_cost_quote_payload,
    create_formula_project_payload,
    create_line_review,
    create_line_review_payload,
    create_manufacturer,
    create_partner,
    create_planogram_slot_payload,
    create_product,
    create_product_payload,
    create_quote,
    create_selected_concept,
    create_selected_trend,
    evaluate_quote,
    make_manufacturer_rep_headers,
    open_dossier,
    open_line_review,
    read_cost_quote,
    read_launch_plan,
    read_product,
    set_clock,
    setup_decided_review_with_slot,
    setup_draft_plan,
    setup_product_with_approved_formula,
    setup_sourcing_product,
    transition_concept,
    transition_line_review,
    transition_manufacturer,
    transition_product,
    validate_error,
    validate_paginated,
    validate_success,
    withdraw_slot,
)

_SCOUT = TEST_USERS["trend_scout_headers"]
_PM = TEST_USERS["product_manager_headers"]
_SOURCING = TEST_USERS["sourcing_lead_headers"]
_COMPLIANCE = TEST_USERS["compliance_officer_headers"]
_PLANNER = TEST_USERS["retail_planner_headers"]


def test_line_review_invalid_date_ranges_are_rejected(api):
    """PRD §3.7: "The window is a half-open interval — it includes the start
    instant and excludes the end instant — and the dates must be internally
    valid: the window end must be later than the start, and the review date
    must fall on or after the window end, else creation is rejected with
    `ERR_INVALID_DATE_RANGE`."
    End before start: 422. Review date before the window end: 422.

    Design: Corner/validations/line_review_invalid_date_range_rejected
    """
    set_clock()
    partner = create_partner()

    validate_error(
        api.create_line_review(
            create_line_review_payload(
                retail_partner_id=partner["id"],
                season="2026-BAD",
                submission_window_start="2026-10-15T00:00:00Z",
                submission_window_end="2026-10-01T00:00:00Z",
                review_date="2026-10-20T00:00:00Z",
            ),
            _PLANNER,
        ),
        ApiErrorId.ERR_INVALID_DATE_RANGE.value,
    )
    validate_error(
        api.create_line_review(
            create_line_review_payload(
                retail_partner_id=partner["id"],
                season="2026-BAD2",
                review_date="2026-10-10T00:00:00Z",
            ),
            _PLANNER,
        ),
        ApiErrorId.ERR_INVALID_DATE_RANGE.value,
    )

    rows, meta = validate_paginated(
        api.list_line_reviews(headers=_PLANNER, params={"retail_partner_id": partner["id"]})
    )
    assert meta["total_count"] == 0


def test_planogram_lock_with_unresolved_slots_rejected(api):
    """PRD §3.7: "Locking the planogram — `DECIDED` to `PLANOGRAM_LOCKED` —
    requires that no slot of the review remains in `PROPOSED`, else
    `ERR_UNRESOLVED_SLOTS`."
    One PROPOSED slot blocks the lock; withdrawing it lets the retry through.

    Design: Corner/validations/planogram_lock_with_unresolved_slots_rejected
    """
    ctx = setup_decided_review_with_slot()

    response = api.patch_line_review(
        ctx["line_review"]["id"], {"status": "PLANOGRAM_LOCKED"}, _PLANNER
    )

    validate_error(response, ApiErrorId.ERR_UNRESOLVED_SLOTS.value)

    withdraw_slot(ctx["slot"]["id"])
    locked = transition_line_review(ctx["line_review"]["id"], "PLANOGRAM_LOCKED")
    assert locked["status"] == "PLANOGRAM_LOCKED"


def test_budget_clamp_below_moq_returns_budget_exceeded(api):
    """PRD §3.8: "Otherwise the clamp applies once: the landed cost is
    evaluated a single time at the manufacturer's minimum order quantity, the
    budget is divided by that figure and floored to a whole unit count, and if
    that floored count falls below the minimum order quantity the lock is
    rejected with `ERR_BUDGET_EXCEEDED`; otherwise the floored count becomes
    `qty_locked_units`."
    Demand 800 at landed 237 -> 189600 > 100000 triggers the clamp;
    floor(100000 / landed(500)=244) == 409 < MOQ 500, so the lock is rejected
    and the plan stays DRAFT.

    Design: Corner/validations/budget_clamp_below_moq_returns_budget_exceeded
    """
    ctx = setup_draft_plan(plan_overrides={"cogs_budget_cents": 100000})

    response = api.patch_launch_plan(
        ctx["plan"]["id"], {"status": "QUANTITY_LOCKED", "variant": "DEMAND"}, _PM
    )

    validate_error(response, ApiErrorId.ERR_BUDGET_EXCEEDED.value)
    plan = read_launch_plan(ctx["plan"]["id"])
    assert plan["status"] == "DRAFT"
    assert plan["qty_locked_units"] is None


def test_slot_create_for_not_launch_ready_product_rejected(api):
    """PRD §3.7: "Within an open window, the planner proposes planogram slots.
    Creation names the `line_review_id`, the `product_id` — which must be
    `LAUNCH_READY`, else `ERR_PRODUCT_NOT_LAUNCH_READY` — ..."
    The review is SUBMISSION_OPEN and the version matches, but the product is
    only SOURCING: 422, and no slot row persists.

    Design: Corner/validations/slot_create_for_not_launch_ready_product_rejected
    """
    ctx = setup_sourcing_product()
    ctx["partner"] = create_partner()
    ctx["line_review"] = create_line_review(ctx["partner"]["id"])
    ctx["line_review"] = open_line_review(ctx["line_review"]["id"])

    response = api.create_planogram_slot(
        create_planogram_slot_payload(
            line_review_id=ctx["line_review"]["id"],
            product_id=ctx["product"]["id"],
            facings=4,
            expected_line_review_version=ctx["line_review"]["version"],
        ),
        _PLANNER,
    )

    validate_error(response, ApiErrorId.ERR_PRODUCT_NOT_LAUNCH_READY.value)
    rows, meta = validate_paginated(
        api.list_planogram_slots(
            headers=_PLANNER, params={"line_review_id": ctx["line_review"]["id"]}
        )
    )
    assert meta["total_count"] == 0


def test_product_advance_referential_gates_fire_in_chain_order(api):
    """PRD §3.3: "The concept must be in `SELECTED` status, else the creation
    is rejected with `ERR_CONCEPT_NOT_SELECTED`; ..."
    PRD §3.3: "Moving a product from `FORMULATION` to `SOURCING` requires that
    at least one formula project for the product is in `APPROVED` status, else
    the advance is rejected with `ERR_FORMULA_NOT_APPROVED`. Moving from
    `SOURCING` to `COMPLIANCE_GATE` requires at least one quote for the
    product in `ACCEPTED` status, else `ERR_QUOTE_NOT_ACCEPTED`."
    Each gate is observed at its own step: PITCHED concept, missing approved
    formula, missing accepted quote.

    Design: Corner/validations/product_advance_referential_gates_fire_in_chain_order
    """
    set_clock()
    trend = create_selected_trend()
    concept = create_concept(trend["id"])
    manufacturer = create_manufacturer()

    validate_error(
        api.create_product(create_product_payload(concept_id=concept["id"]), _PM),
        ApiErrorId.ERR_CONCEPT_NOT_SELECTED.value,
    )

    transition_concept(concept["id"], "SELECTED")
    product = create_product(concept["id"])

    validate_error(
        api.patch_product(product["id"], {"status": "SOURCING"}, _PM),
        ApiErrorId.ERR_FORMULA_NOT_APPROVED.value,
    )
    assert read_product(product["id"])["status"] == "FORMULATION"

    create_approved_formula(product["id"], manufacturer["id"])
    sourcing = transition_product(product["id"], "SOURCING")
    assert sourcing["status"] == "SOURCING"

    validate_error(
        api.patch_product(product["id"], {"status": "COMPLIANCE_GATE"}, _PM),
        ApiErrorId.ERR_QUOTE_NOT_ACCEPTED.value,
    )
    assert read_product(product["id"])["status"] == "SOURCING"


def test_suspended_manufacturer_blocks_formula_and_quote_creation(api):
    """PRD §3.4: "Suspending one — a `SourcingLead` decision moving it to
    `SUSPENDED` — blocks the creation of new formula projects and new quotes
    against it, and blocks acceptance of its pending quotes; any of these
    against a suspended manufacturer is rejected with `ERR_CM_SUSPENDED`."
    Identical requests that succeeded while the manufacturer was ACTIVE fail
    after suspension; nothing is persisted.

    Design: Corner/validations/suspended_cm_blocks_formula_create_and_quote_create
    """
    ctx = setup_sourcing_product()
    concept_b = create_selected_concept(ctx["trend"]["id"], name="Second Skin")
    product_b = create_product(concept_b["id"])
    transition_manufacturer(ctx["manufacturer"]["id"], "SUSPENDED")

    validate_error(
        api.create_cost_quote(
            create_cost_quote_payload(
                product_id=ctx["product"]["id"],
                contract_manufacturer_id=ctx["manufacturer"]["id"],
                expected_product_version=read_product(ctx["product"]["id"])["version"],
            ),
            make_manufacturer_rep_headers(ctx["manufacturer"]["id"]),
        ),
        ApiErrorId.ERR_CM_SUSPENDED.value,
    )
    validate_error(
        api.create_formula_project(
            create_formula_project_payload(
                product_id=product_b["id"],
                contract_manufacturer_id=ctx["manufacturer"]["id"],
            ),
            _SOURCING,
        ),
        ApiErrorId.ERR_CM_SUSPENDED.value,
    )

    rows, meta = validate_paginated(
        api.list_cost_quotes(headers=_SOURCING, params={"product_id": ctx["product"]["id"]})
    )
    assert meta["total_count"] == 0
    rows, meta = validate_paginated(
        api.list_formula_projects(
            headers=_SOURCING, params={"product_id": product_b["id"]}
        )
    )
    assert meta["total_count"] == 0


def test_concept_name_is_unique_until_the_concept_is_killed(api):
    """PRD §3.2: "A concept's `name` must be unique across all concepts not in
    `KILLED` status; reusing a live name is rejected with
    `ERR_DUPLICATE_CONCEPT_NAME`."
    The duplicate is a 409 while the original lives; killing the original
    frees the name for immediate reuse under a new id.

    Design: Corner/validations/concept_name_unique_until_killed
    """
    set_clock()
    trend = create_selected_trend()
    concept = create_concept(trend["id"], name="Alpha Lash")

    validate_error(
        api.create_concept(
            create_concept_payload(
                trend_signal_id=trend["id"], name="Alpha Lash",
                target_price_point_cents=600,
            ),
            _SCOUT,
        ),
        ApiErrorId.ERR_DUPLICATE_CONCEPT_NAME.value,
    )

    transition_concept(concept["id"], "KILLED")
    reused = validate_success(
        api.create_concept(
            create_concept_payload(
                trend_signal_id=trend["id"], name="Alpha Lash",
                target_price_point_cents=600,
            ),
            _SCOUT,
        ),
        expected_status=201,
    )
    assert reused["id"] != concept["id"]
    assert reused["name"] == "Alpha Lash"


def test_second_dossier_for_the_same_product_conflicts(api):
    """PRD §3.6: "A `ComplianceOfficer` opens at most one dossier per product;
    opening a second is rejected with `ERR_DOSSIER_ALREADY_EXISTS`."
    The second POST is a 409 and the first dossier is untouched.

    Design: Corner/validations/second_dossier_for_same_product_conflict
    """
    ctx = setup_product_with_approved_formula()
    open_dossier(ctx["product"]["id"])

    response = api.create_compliance_dossier(
        create_compliance_dossier_payload(product_id=ctx["product"]["id"]),
        _COMPLIANCE,
    )

    validate_error(response, ApiErrorId.ERR_DOSSIER_ALREADY_EXISTS.value)
    rows, meta = validate_paginated(
        api.list_compliance_dossiers(
            headers=_COMPLIANCE, params={"product_id": ctx["product"]["id"]}
        )
    )
    assert meta["total_count"] == 1


def test_quote_acceptance_after_valid_until_lazily_expires(api):
    """PRD §3.5: "...the logical clock must not have passed `valid_until`,
    else `ERR_QUOTE_EXPIRED` with the quote lazily moved to `EXPIRED`; ..."
    PRD §2.4: "...a quote whose `valid_until` has passed transitions to
    `EXPIRED` the next time it is read or written..."
    Evaluated at 2026-09-01 with valid_until 2026-10-15; the acceptance at
    2026-10-16 is a 422 and a subsequent read shows EXPIRED.

    Design: Corner/validations/quote_lazy_expiry_blocks_accept
    """
    ctx = setup_sourcing_product()
    quote = create_quote(
        ctx["product"]["id"],
        ctx["manufacturer"]["id"],
        valid_until="2026-10-15T00:00:00Z",
    )
    evaluate_quote(quote["id"])
    set_clock("2026-10-16T00:00:00Z")

    response = api.patch_cost_quote(quote["id"], {"status": "ACCEPTED"}, _SOURCING)

    validate_error(response, ApiErrorId.ERR_QUOTE_EXPIRED.value)
    assert read_cost_quote(quote["id"])["status"] == "EXPIRED"
