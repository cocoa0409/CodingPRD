"""The placement install gate: validation tiers and fiscal fencing (PRD §2.7, §3.4)."""
import pytest

from test_helpers import (
    NON_EXISTENT_UUID,
    STORE_BETA,
    STORE_GAMMA,
    ApiErrorId,
    create_agreement,
    create_chiller,
    create_chiller_batch,
    create_placement_payload,
    create_site_evaluation,
    create_store,
    set_clock,
    setup_active_placement,
    setup_signed_agreement,
    sign_agreement,
    validate_error,
    validate_paginated,
    validate_success,
)


def test_install_state_error_shadows_fiscal_error(api, placement_manager_headers):
    """PRD §2.7: "When several checks could reject the same request, the system
    evaluates them in a fixed priority order, and the earliest failing tier
    determines the response"
    PRD §3.4: "The gates, in validation-tier order: the agreement must be
    `SIGNED` (otherwise 409 `ERR_AGREEMENT_NOT_SIGNED`); ..."

    Design: Difficulty/priority_pair_validation_conflict/install_state_beats_fiscal
    """
    store = create_store()
    create_site_evaluation(store["id"])
    agreement = create_agreement(store["id"], max_capex_cents=1)  # PROPOSED; quote would exceed 1 cent
    chiller = create_chiller()
    payload = create_placement_payload(store["id"], agreement["id"], chiller["id"], agreement["version"])
    resp = api.create_placement(payload, placement_manager_headers)
    validate_error(resp, ApiErrorId.ERR_AGREEMENT_NOT_SIGNED)
    assert resp.status_code == 409, (
        "state tier (4) precedes business fiscal tier (9): ERR_AGREEMENT_NOT_SIGNED, "
        "not ERR_CAPEX_BUDGET_EXCEEDED, though both would fail"
    )


def test_install_rejected_by_state_gate_leaves_no_trace(api, placement_manager_headers):
    """PRD §3.4: "The gates, in validation-tier order: the agreement must be
    `SIGNED` (otherwise 409 `ERR_AGREEMENT_NOT_SIGNED`); the chiller must be
    `IN_STOCK` (otherwise 409 `ERR_CHILLER_NOT_IN_STOCK`); ..."
    PRD §2.12: "`registered_units` is the count of all `Chiller` rows ever
    created, in any status including `DECOMMISSIONED`."

    Design: Difficulty/priority_pair_validation_conflict/install_state_beats_fiscal
    """
    store = create_store()
    create_site_evaluation(store["id"])
    agreement = create_agreement(store["id"], max_capex_cents=1)
    chiller = create_chiller()
    payload = create_placement_payload(store["id"], agreement["id"], chiller["id"], agreement["version"])
    resp = api.create_placement(payload, placement_manager_headers)
    validate_error(resp, ApiErrorId.ERR_AGREEMENT_NOT_SIGNED)

    chiller_after = validate_success(api.get_chiller(chiller["id"], placement_manager_headers))
    assert chiller_after["status"] == "IN_STOCK", "rejected install must not move the chiller"
    _, meta = validate_paginated(api.list_placements(placement_manager_headers, params={"store_id": store["id"]}))
    assert meta["total_count"] == 0, "no Placement row may persist from the rejected install"


def test_existence_beats_state_on_install(api, placement_manager_headers):
    """PRD §2.7: "3. **Existence.** Unresolvable path identifiers or body
    foreign keys yield 404 `ERR_NOT_FOUND`, left to right per §2.6.
    4. **State.** ..."

    Design: Corner/validations/existence_beats_state_on_install
    """
    store = create_store()
    create_site_evaluation(store["id"])
    agreement = create_agreement(store["id"])  # PROPOSED: state gate would also fail
    payload = create_placement_payload(store["id"], agreement["id"], NON_EXISTENT_UUID, agreement["version"])
    resp = api.create_placement(payload, placement_manager_headers)
    validate_error(resp, ApiErrorId.ERR_NOT_FOUND)
    assert resp.status_code == 404, "existence (tier 3) precedes state (tier 4)"


def test_stale_evaluation_shadows_ineligible_verdict(api, placement_manager_headers):
    """PRD §3.4: "the store's latest SiteEvaluation must be fresh, created
    within 90 days of the logical now (otherwise 422 `ERR_EVALUATION_STALE`);
    ... and the store's latest SiteEvaluation `verdict` must be `ELIGIBLE`
    (otherwise 422 `ERR_PAYBACK_INELIGIBLE`)."
    PRD §2.7: "6. **Business temporal.** Time-window rules: delivering beyond
    the transit window yields 422 `ERR_TRANSIT_WINDOW_EXCEEDED`; installing or
    relocating against a stale site evaluation yields 422
    `ERR_EVALUATION_STALE`; ..."

    Design: Corner/validations/stale_evaluation_beats_ineligible_verdict
    """
    store = create_store()
    evaluation = create_site_evaluation(store["id"], forecast_weekly_units=5)
    # round_half_up(5*13/3) = 22; margin 3960; 399250/3960 = 100.82 > 36.
    assert evaluation["payback_months"] == pytest.approx(100.82, abs=0.005)
    assert evaluation["verdict"] == "INELIGIBLE"
    agreement = sign_agreement(create_agreement(store["id"])["id"])
    chiller = create_chiller()
    set_clock("2026-12-01T00:00:01Z")  # 91 days after the evaluation's creation
    payload = create_placement_payload(store["id"], agreement["id"], chiller["id"], agreement["version"])
    resp = api.create_placement(payload, placement_manager_headers)
    validate_error(resp, ApiErrorId.ERR_EVALUATION_STALE)
    assert resp.status_code == 422, "temporal tier (6) precedes fiscal tier (9): not ERR_PAYBACK_INELIGIBLE"


def test_footprint_insufficient_on_install(api, placement_manager_headers):
    """PRD §3.4: "the chiller's `footprint_sqft` must not exceed the
    agreement's `allocated_sqft` (otherwise 422
    `ERR_STORE_FOOTPRINT_INSUFFICIENT`)"
    PRD §3.3: "Derived unit economics are fixed by model: a `STANDARD` chiller
    holds 240 units of product on a `footprint_sqft` of 8, while a `COMPACT`
    holds 120 units on 5 square feet."

    Design: Corner/validations/footprint_insufficient_on_install
    """
    store = create_store()
    create_site_evaluation(store["id"])
    agreement = sign_agreement(create_agreement(store["id"], allocated_sqft=5)["id"])
    chiller = create_chiller()  # STANDARD footprint 8 > 5
    payload = create_placement_payload(store["id"], agreement["id"], chiller["id"], agreement["version"])
    resp = api.create_placement(payload, placement_manager_headers)
    validate_error(resp, ApiErrorId.ERR_STORE_FOOTPRINT_INSUFFICIENT)
    assert resp.status_code == 422

    chiller_after = validate_success(api.get_chiller(chiller["id"], placement_manager_headers))
    assert chiller_after["status"] == "IN_STOCK", "no partial install"
    listed = validate_success(api.list_placement_agreements(store["id"], placement_manager_headers))
    assert listed[0]["status"] == "SIGNED", "agreement must not advance on a rejected install"


def test_capex_budget_exceeded_on_install(api, placement_manager_headers):
    """PRD §3.4: "the freshly computed `installed_quote_cents` must not exceed
    the agreement's `max_capex_cents` (otherwise 422
    `ERR_CAPEX_BUDGET_EXCEEDED`)"

    Design: Corner/validations/capex_budget_exceeded_on_install
    """
    store = create_store()
    create_site_evaluation(store["id"])
    agreement = sign_agreement(create_agreement(store["id"], max_capex_cents=300000)["id"])
    chiller = create_chiller()
    payload = create_placement_payload(store["id"], agreement["id"], chiller["id"], agreement["version"])
    resp = api.create_placement(payload, placement_manager_headers)
    validate_error(resp, ApiErrorId.ERR_CAPEX_BUDGET_EXCEEDED)
    assert resp.status_code == 422, "quote 399250 > 300000 ceiling"

    _, meta = validate_paginated(api.list_placements(placement_manager_headers, params={"store_id": store["id"]}))
    assert meta["total_count"] == 0
    listed = validate_success(api.list_placement_agreements(store["id"], placement_manager_headers))
    assert listed[0]["status"] == "SIGNED"


def test_agreement_store_mismatch_on_install(api, placement_manager_headers):
    """PRD §3.4: "the placement's `store_id` must equal the agreement's own
    store (otherwise 422 `ERR_AGREEMENT_STORE_MISMATCH`)"

    Design: Corner/validations/agreement_store_mismatch_on_install
    """
    store_a = create_store()
    create_site_evaluation(store_a["id"])
    store_b = create_store(payload=STORE_BETA)
    create_site_evaluation(store_b["id"])
    agreement_b = sign_agreement(create_agreement(store_b["id"])["id"])
    chiller = create_chiller()
    payload = create_placement_payload(store_a["id"], agreement_b["id"], chiller["id"], agreement_b["version"])
    resp = api.create_placement(payload, placement_manager_headers)
    validate_error(resp, ApiErrorId.ERR_AGREEMENT_STORE_MISMATCH)
    assert resp.status_code == 422, "the agreement belongs to Store Beta, not Store Alpha"


def test_duplicate_active_placement_rejected(api, placement_manager_headers):
    """PRD §3.4: "the store must not already have a placement with `status`
    `ACTIVE` (otherwise 409 `ERR_DUPLICATE_ACTIVE_PLACEMENT`)"

    Design: Corner/validations/duplicate_active_placement_rejected
    """
    ctx = setup_active_placement()
    store = ctx["store"]
    chiller2 = create_chiller()  # second IN_STOCK chiller
    agreement2 = sign_agreement(create_agreement(store["id"], allocated_sqft=10, max_capex_cents=400000,
                                                 term_months=36)["id"])
    payload = create_placement_payload(store["id"], agreement2["id"], chiller2["id"], agreement2["version"])
    resp = api.create_placement(payload, placement_manager_headers)
    validate_error(resp, ApiErrorId.ERR_DUPLICATE_ACTIVE_PLACEMENT)
    assert resp.status_code == 409

    chiller2_after = validate_success(api.get_chiller(chiller2["id"], placement_manager_headers))
    assert chiller2_after["status"] == "IN_STOCK", "second chiller must not be burned by the failed install"
    listed = validate_success(api.list_placement_agreements(store["id"], placement_manager_headers))
    by_id = {a["id"]: a for a in listed}
    assert by_id[agreement2["id"]]["status"] == "SIGNED", "second agreement stays SIGNED"


def test_install_chiller_not_in_stock_returns_409(api, placement_manager_headers):
    """PRD §3.4: "the chiller must be `IN_STOCK` (otherwise 409
    `ERR_CHILLER_NOT_IN_STOCK`)"

    Design: Corner/errors/install_chiller_not_in_stock_returns_409
    """
    ctx = setup_active_placement()  # chiller INSTALLED at Store Alpha
    store_b = create_store(payload=STORE_BETA)
    create_site_evaluation(store_b["id"])
    agreement_b = sign_agreement(create_agreement(store_b["id"])["id"])
    payload = create_placement_payload(store_b["id"], agreement_b["id"], ctx["chiller"]["id"],
                                       agreement_b["version"])
    resp = api.create_placement(payload, placement_manager_headers)
    validate_error(resp, ApiErrorId.ERR_CHILLER_NOT_IN_STOCK)
    assert resp.status_code == 409


def test_install_ineligible_fresh_eval_returns_422(api, placement_manager_headers):
    """PRD §3.4: "the store's latest SiteEvaluation `verdict` must be
    `ELIGIBLE` (otherwise 422 `ERR_PAYBACK_INELIGIBLE`)"

    Design: Corner/errors/install_ineligible_fresh_eval_returns_422
    """
    store = create_store()
    evaluation = create_site_evaluation(store["id"], forecast_weekly_units=5)
    assert evaluation["verdict"] == "INELIGIBLE"
    assert evaluation["payback_months"] == pytest.approx(100.82, abs=0.005)
    agreement = sign_agreement(create_agreement(store["id"])["id"])
    chiller = create_chiller()
    payload = create_placement_payload(store["id"], agreement["id"], chiller["id"], agreement["version"])
    resp = api.create_placement(payload, placement_manager_headers)
    validate_error(resp, ApiErrorId.ERR_PAYBACK_INELIGIBLE)
    assert resp.status_code == 422, "evaluation is fresh — staleness is not in play"

    chiller_after = validate_success(api.get_chiller(chiller["id"], placement_manager_headers))
    assert chiller_after["status"] == "IN_STOCK"


def test_placement_install_computed_snapshot_immediate(api, placement_manager_headers):
    """PRD §3.4: "The installation snapshots `installed_quote_cents` from the
    installation-quote calculation using the chiller's model, the agreement's
    `allocated_sqft`, and the store's `distance_miles_from_plant`, and
    initializes `standing_deliveries_per_week` and `safety_stock_units` from
    the governing evaluation's `forecast_weekly_units` per the delivery plan of
    §3.6."
    PRD §3.4: "In the same transaction the chiller moves `IN_STOCK` to
    `INSTALLED` (its `version` increments) and the agreement moves `SIGNED` to
    `ACTIVE` (its `version` increments)."

    Design: Corner/endpoints/placement_install_computed_snapshot_immediate
    """
    store, evaluation, agreement = setup_signed_agreement()
    chiller = create_chiller()
    payload = create_placement_payload(store["id"], agreement["id"], chiller["id"], agreement["version"])
    resp = api.create_placement(payload, placement_manager_headers)
    placement = validate_success(resp, expected_status=201)
    assert placement["installed_quote_cents"] == 399250, "325000 + 45000 + 16*1250 + 10*925"
    assert placement["standing_deliveries_per_week"] == 3, "forecast 200 -> tier 150..299"
    assert placement["safety_stock_units"] == 240, "min(240, round_half_up(200*45/7*1.25) = 1607)"
    assert placement["performance_status"] == "PENDING"
    assert placement["operational_status"] == "OK"

    listed = validate_success(api.list_placement_agreements(store["id"], placement_manager_headers))
    assert listed[0]["status"] == "ACTIVE"
    assert listed[0]["version"] == agreement["version"] + 1, "agreement version bumps by 1 in the same transaction"


def test_placements_filtered_by_chiller_fk(api, placement_manager_headers):
    """PRD §3.4: "Placements can be listed with optional filters on `store_id`,
    `chiller_id`, `agreement_id`, `status`, and `relocated_to_placement_id`."

    Design: Corner/endpoints/placements_filtered_by_chiller_fk
    """
    store, evaluation, agreement = setup_signed_agreement()
    chiller1, chiller2 = create_chiller_batch(quantity=2)
    resp = api.create_placement(
        create_placement_payload(store["id"], agreement["id"], chiller1["id"], agreement["version"]),
        placement_manager_headers,
    )
    placement = validate_success(resp, expected_status=201)

    data, meta = validate_paginated(api.list_placements(placement_manager_headers,
                                                        params={"chiller_id": chiller1["id"]}))
    assert meta["total_count"] == 1 and len(data) == 1
    assert data[0]["id"] == placement["id"]

    data, meta = validate_paginated(api.list_placements(placement_manager_headers,
                                                        params={"chiller_id": chiller2["id"]}))
    assert data == [] and meta["total_count"] == 0, "never-installed chiller filters to empty"
