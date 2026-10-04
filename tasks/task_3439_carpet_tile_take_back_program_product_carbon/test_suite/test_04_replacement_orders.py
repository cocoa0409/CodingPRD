"""Replacement orders (PRD §3.4): the match/rematch loop, quote factors,
completion guards and their evaluation order, the exact-fit budget boundary,
area conservation across the order lifecycle, cross-site integrity, and the
site-scoped optimistic concurrency check (PRD §2.7).
"""
from test_helpers import (
    ApiErrorId,
    api_client,
    cancel_order,
    complete_order,
    create_installed_site,
    create_order,
    create_released_batch,
    create_replacement_order_payload,
    create_site,
    get_site_version,
    install_site,
    lay_zone,
    make_installer_headers,
    make_specifier_headers,
    match_order,
    set_clock,
    setup_collection_with_batch,
    validate_error,
    validate_paginated,
    validate_success,
)

OTHER_LOT_MIX = [
    (300, 0.40, "POST_CONSUMER_TILE", "NETCO"),
    (300, 2.10, "VIRGIN", "POLYCO"),
]


def _setup_exhausted_single_batch(api):
    """DL-100 (100 m2) fully laid into zone Z-1: the batch is EXHAUSTED, so the
    candidate pool for a 100 m2 replacement is empty."""
    built = setup_collection_with_batch()
    site = create_installed_site()
    zone = lay_zone(site, built["batch"]["id"], zone_code="Z-1", area_m2=100)
    return built, site, zone


def test_first_match_with_exhausted_pool_lands_match_failed(api, admin_headers):
    """PRD §3.4: "The candidate set is every batch of the same collection as
    the zone's current batch whose status is `RELEASED` and whose
    `available_m2` is at least the zone's `area_m2`."
    PRD §3.4: "When the candidate set is empty, the match attempt moves the
    order from `DRAFT` to `MATCH_FAILED` with no side effects and
    `matched_batch_id` still null"

    Design: Difficulty/non_linear_state_machine/order_match_failed_rematch_loop
    """
    set_clock()
    built, site, zone = _setup_exhausted_single_batch(api)
    order = create_order(site, zone, reason="DAMAGE", new_zone_code="Z-1R")
    order = match_order(order, site)
    assert order["status"] == "MATCH_FAILED"
    assert order["matched_batch_id"] is None
    batch = validate_success(api.get_batch(built["batch"]["id"], admin_headers))
    assert batch["available_m2"] == 0
    assert batch["status"] == "EXHAUSTED"


def test_rematch_after_new_release_matches_with_other_lot_quote(api, admin_headers):
    """PRD §3.4: "a later re-match — typically after new batches are released —
    runs the same selection again, succeeding into `MATCHED` or remaining
    `MATCH_FAILED` when the pool is still empty."
    PRD §3.4: "The quote is the zone's `area_m2` multiplied by the program's
    base price of 1200 cents per square meter, multiplied by a dye-lot factor —
    exactly 1.00 when the matched batch shares the zone's batch's
    `dye_lot_code`, and 1.15 (a fifteen percent surcharge for a different lot)
    otherwise — with the result rounded half up to whole cents and stored as
    `quoted_cost_cents`."

    Design: Difficulty/non_linear_state_machine/order_match_failed_rematch_loop
    """
    set_clock()
    built, site, zone = _setup_exhausted_single_batch(api)
    order = create_order(site, zone, reason="DAMAGE", new_zone_code="Z-1R")
    order = match_order(order, site)
    assert order["status"] == "MATCH_FAILED"

    second = create_released_batch(
        built["collection"]["id"],
        mix=OTHER_LOT_MIX,
        dye_lot_code="DL-102",
        production_date="2026-09-08T00:00:00Z",
        produced_m2=150,
        mfg_intensity_kgco2e_per_m2=1.0,
        delta_e=0.5,
    )
    order = match_order(order, site)
    assert order["status"] == "MATCHED"
    assert order["matched_batch_id"] == second["batch"]["id"]
    # 100 m2 x 1200 x 1.15 (DL-102 != the zone's DL-100): other-lot quote.
    assert order["quoted_cost_cents"] == 138000
    batch = validate_success(api.get_batch(second["batch"]["id"], admin_headers))
    assert batch["available_m2"] == 50, "150 - 100 reserved"


def _setup_two_orders_one_completed_one_cancelled(api):
    """DL-100 (100 m2) + DL-101 (200 m2, delta_e 0.9); site budget 130000 with
    zones Z-1/Z-2 (50 m2 each, laid from DL-100 -> EXHAUSTED). ORD-1 and ORD-2
    both MATCHED against DL-101 (other-lot quotes 69000 each). ORD-2 completes
    (spent 69000); ORD-1 is cancelled by its creator."""
    built = setup_collection_with_batch()
    second = create_released_batch(
        built["collection"]["id"],
        mix=[(400, 0.40, "POST_CONSUMER_TILE", "NETCO"), (400, 2.10, "VIRGIN", "POLYCO")],
        dye_lot_code="DL-101",
        production_date="2026-09-09T00:00:00Z",
        produced_m2=200,
        mfg_intensity_kgco2e_per_m2=1.1,
        delta_e=0.9,
    )
    site = create_installed_site(annual_replacement_budget_cents=130000)
    z1 = lay_zone(site, built["batch"]["id"], zone_code="Z-1", area_m2=50)
    z2 = lay_zone(site, built["batch"]["id"], zone_code="Z-2", area_m2=50)
    ord1 = create_order(site, z1, reason="DAMAGE", new_zone_code="Z-1R")
    ord1 = match_order(ord1, site)
    ord2 = create_order(site, z2, reason="WEAR", new_zone_code="Z-2R")
    ord2 = match_order(ord2, site)
    assert ord1["quoted_cost_cents"] == 69000  # 50 x 1200 x 1.15
    assert ord2["quoted_cost_cents"] == 69000
    complete_order(ord2, site)  # spent 69000
    cancel_order(ord1)
    return site, ord1, ord2


def test_complete_cancelled_order_returns_state_error_not_fiscal(api, admin_headers):
    """PRD §2.8: "the pipeline is **first-failure-wins**: checks run in the
    priority order below, and the first check that fails determines the error
    response; later checks are not evaluated for that request."
    PRD §3.4: "The order must be `MATCHED` — completing anything else is
    rejected with `ERR_ORDER_NOT_MATCHED` (HTTP 409)"
    PRD §2.8 (rule 12): "Capacity and fiscal guards, evaluated last."

    Design: Difficulty/priority_pair_validation_conflict/complete_cancelled_order_over_budget_returns_state_error
    """
    set_clock()
    site, ord1, _ord2 = _setup_two_orders_one_completed_one_cancelled(api)
    # Completing the CANCELLED order would also breach the budget
    # (69000 + 69000 = 138000 > 130000), but the order-state guard (priority
    # 6) runs long before the fiscal guard (priority 12).
    resp = api.complete_replacement_order(
        ord1["id"], make_installer_headers(site["contractor_name"])
    )
    validate_error(resp, ApiErrorId.ERR_ORDER_NOT_MATCHED)


def test_failed_complete_leaves_cancelled_order_and_spend_untouched(api, admin_headers):
    """PRD §3.4: "The order must be `MATCHED` — completing anything else is
    rejected with `ERR_ORDER_NOT_MATCHED` (HTTP 409)"
    PRD §3.4: "`COMPLETED` and `CANCELLED` are the order's terminal states."
    PRD §3.4: "the site's `spent_replacement_cents` is always the sum of
    `quoted_cost_cents` over the site's `COMPLETED` replacement orders."

    Design: Difficulty/priority_pair_validation_conflict/complete_cancelled_order_over_budget_returns_state_error
    """
    set_clock()
    site, ord1, _ord2 = _setup_two_orders_one_completed_one_cancelled(api)
    resp = api.complete_replacement_order(
        ord1["id"], make_installer_headers(site["contractor_name"])
    )
    validate_error(resp, ApiErrorId.ERR_ORDER_NOT_MATCHED)
    order = validate_success(api.get_replacement_order(ord1["id"], admin_headers))
    assert order["status"] == "CANCELLED"
    site_after = validate_success(api.get_site(site["id"], admin_headers))
    assert site_after["spent_replacement_cents"] == 69000


def _setup_exact_fit_budget(api):
    """DL-100 + DL-102 (100 m2 each); site budget exactly 60000 with zones
    Z-1 (DL-100) and Z-2 (DL-102), 50 m2 each. ORD-1 matches its own dye lot
    DL-100 at exact availability (quote 60000 at factor 1.00); ORD-2 matches
    DL-102 the same way."""
    built = setup_collection_with_batch()
    second = create_released_batch(
        built["collection"]["id"],
        mix=[(200, 0.40, "POST_CONSUMER_TILE", "NETCO"), (200, 2.10, "VIRGIN", "POLYCO")],
        dye_lot_code="DL-102",
        production_date="2026-09-08T00:00:00Z",
        produced_m2=100,
        mfg_intensity_kgco2e_per_m2=1.0,
        delta_e=0.5,
    )
    site = create_installed_site(annual_replacement_budget_cents=60000)
    z1 = lay_zone(site, built["batch"]["id"], zone_code="Z-1", area_m2=50)
    z2 = lay_zone(site, second["batch"]["id"], zone_code="Z-2", area_m2=50)
    ord1 = create_order(site, z1, reason="DAMAGE", new_zone_code="Z-1R")
    ord1 = match_order(ord1, site)
    ord2 = create_order(site, z2, reason="WEAR", new_zone_code="Z-2R")
    ord2 = match_order(ord2, site)
    return built, second, site, z1, z2, ord1, ord2


def test_completion_at_exact_budget_fit_succeeds(api, admin_headers):
    """PRD §3.4: "the sum of the site's `spent_replacement_cents` and this
    order's `quoted_cost_cents` must not exceed the site's
    `annual_replacement_budget_cents`, otherwise
    `ERR_REPLACEMENT_BUDGET_EXCEEDED` (HTTP 422)" — must-not-exceed is an
    inclusive boundary: a completion landing exactly on the budget is allowed.
    PRD §3.4: "The candidate set is every batch of the same collection as the
    zone's current batch whose status is `RELEASED` and whose `available_m2`
    is at least the zone's `area_m2`."

    Design: Difficulty/boundary_precision_check/replacement_budget_exact_fit
    """
    set_clock()
    built, _second, site, _z1, _z2, ord1, _ord2 = _setup_exact_fit_budget(api)
    # Exact-fit eligibility: DL-100's 50 available m2 == the zone's 50 m2, and
    # the exact dye lot ranks first -> quote at factor 1.00.
    assert ord1["matched_batch_id"] == built["batch"]["id"]
    assert ord1["quoted_cost_cents"] == 60000
    completed = complete_order(ord1, site)
    assert completed["status"] == "COMPLETED"
    site_after = validate_success(api.get_site(site["id"], admin_headers))
    assert site_after["spent_replacement_cents"] == 60000
    assert (
        site_after["spent_replacement_cents"]
        == site_after["annual_replacement_budget_cents"]
    )


def test_completion_over_budget_rejected_and_state_kept(api, admin_headers):
    """PRD §3.4: "the sum of the site's `spent_replacement_cents` and this
    order's `quoted_cost_cents` must not exceed the site's
    `annual_replacement_budget_cents`, otherwise
    `ERR_REPLACEMENT_BUDGET_EXCEEDED` (HTTP 422)".
    PRD §3.4: "A successful completion moves the targeted zone from
    `IN_SERVICE` to `REPLACED`, creates the replacement zone with `zone_code`
    equal to the order's `new_zone_code`"

    Design: Difficulty/boundary_precision_check/replacement_budget_exact_fit
    """
    set_clock()
    _built, second, site, _z1, _z2, ord1, ord2 = _setup_exact_fit_budget(api)
    complete_order(ord1, site)  # spent 60000 == budget
    resp = api.complete_replacement_order(
        ord2["id"], make_installer_headers(site["contractor_name"])
    )
    # 60000 + 60000 > 60000: the second completion is over budget.
    validate_error(resp, ApiErrorId.ERR_REPLACEMENT_BUDGET_EXCEEDED)
    order = validate_success(api.get_replacement_order(ord2["id"], admin_headers))
    assert order["status"] == "MATCHED", "the rejected completion changes nothing"
    batch = validate_success(api.get_batch(second["batch"]["id"], admin_headers))
    assert batch["available_m2"] == 0
    assert batch["status"] == "EXHAUSTED", "the reservation is retained"
    rows, _ = validate_paginated(
        api.list_zones(admin_headers, params={"site_id": site["id"]})
    )
    by_code = {row["zone_code"]: row["status"] for row in rows}
    assert by_code["Z-1"] == "REPLACED"
    assert by_code["Z-1R"] == "IN_SERVICE"


def test_zone_lay_and_match_reservation_conserve_batch_area(api, admin_headers):
    """PRD §3.3: "A successful laying debits the batch's `available_m2` by the
    zone's area — exhausting the batch into `EXHAUSTED` if the debit brings
    availability to exactly zero — and creates the zone already `IN_SERVICE`."
    PRD §3.4: "The match also reserves inventory: the matched batch's
    `available_m2` is debited by the zone's `area_m2`, and a batch driven to
    zero moves to `EXHAUSTED`."

    Design: Difficulty/compensating_invariant/batch_area_conserved_across_order_lifecycle
    """
    set_clock()
    built = setup_collection_with_batch()
    batch_id = built["batch"]["id"]
    site = create_installed_site()
    zone = lay_zone(site, batch_id, zone_code="Z-1", area_m2=30)
    batch = validate_success(api.get_batch(batch_id, admin_headers))
    assert batch["available_m2"] == 70  # 70 + 30 laid == 100 produced

    order = create_order(site, zone, reason="DAMAGE", new_zone_code="Z-1R")
    order = match_order(order, site)
    assert order["status"] == "MATCHED"
    assert order["matched_batch_id"] == batch_id
    assert order["quoted_cost_cents"] == 36000  # 30 x 1200 x 1.00 (exact lot)
    batch = validate_success(api.get_batch(batch_id, admin_headers))
    # 40 free + 30 laid + 30 reserved == 100 produced.
    assert batch["available_m2"] == 40


def test_cancel_restores_then_exact_fit_lay_exhausts(api, admin_headers):
    """PRD §3.4: "From `MATCHED` the reservation is released: the matched
    batch's `available_m2` is credited back the zone's `area_m2`, and a batch
    sitting at `EXHAUSTED` reverts to `RELEASED` as availability returns."
    PRD §3.3: "A successful laying debits the batch's `available_m2` by the
    zone's area — exhausting the batch into `EXHAUSTED` if the debit brings
    availability to exactly zero"

    Design: Difficulty/compensating_invariant/batch_area_conserved_across_order_lifecycle
    """
    set_clock()
    built = setup_collection_with_batch()
    batch_id = built["batch"]["id"]
    site = create_installed_site()
    zone = lay_zone(site, batch_id, zone_code="Z-1", area_m2=30)
    order = create_order(site, zone, reason="DAMAGE", new_zone_code="Z-1R")
    order = match_order(order, site)
    assert order["status"] == "MATCHED"

    cancel_order(order)
    batch = validate_success(api.get_batch(batch_id, admin_headers))
    assert batch["available_m2"] == 70, "cancel restores the reservation exactly"

    lay_zone(site, batch_id, zone_code="Z-2", area_m2=70)  # exact fit
    batch = validate_success(api.get_batch(batch_id, admin_headers))
    assert batch["available_m2"] == 0
    assert batch["status"] == "EXHAUSTED"  # 0 free + 30 + 70 laid == 100


def test_order_terminal_and_state_guards(api, admin_headers):
    """PRD §3.4: "The order must be `MATCHED` — completing anything else is
    rejected with `ERR_ORDER_NOT_MATCHED` (HTTP 409)"
    PRD §3.4: "The zone must belong to the named site: an order whose
    `zone_id` resolves to a zone of a different site is rejected with
    `ERR_ZONE_SITE_MISMATCH` (HTTP 422), and a zone not currently `IN_SERVICE`
    rejects the create with `ERR_ZONE_NOT_IN_SERVICE` (HTTP 409)."
    PRD §3.4: "`COMPLETED` and `CANCELLED` are the order's terminal states."

    Design: Corner/state_machines/order_terminal_and_state_guards
    """
    set_clock()
    built = setup_collection_with_batch()
    site = create_installed_site()
    z1 = lay_zone(site, built["batch"]["id"], zone_code="Z-1", area_m2=50)
    ord1 = create_order(site, z1, reason="DAMAGE", new_zone_code="Z-1R")
    ord1 = match_order(ord1, site)
    ord1 = complete_order(ord1, site)
    assert ord1["status"] == "COMPLETED"

    # The replacement zone was created by the completion (PRD §3.4).
    rows, _ = validate_paginated(
        api.list_zones(
            admin_headers, params={"site_id": site["id"], "status": "IN_SERVICE"}
        )
    )
    assert len(rows) == 1
    z1r = rows[0]
    assert z1r["zone_code"] == "Z-1R"
    assert z1r["batch_id"] == built["batch"]["id"]
    assert z1r["area_m2"] == 50
    assert z1r["status"] == "IN_SERVICE"

    ord2 = create_order(site, z1r, reason="WEAR", new_zone_code="Z-1RR")

    installer = make_installer_headers(site["contractor_name"])
    # Matching a terminal (COMPLETED) order: no such transition.
    validate_error(
        api.match_replacement_order(ord1["id"], installer),
        ApiErrorId.ERR_INVALID_STATE,
    )
    # Completing a DRAFT order: the specific order-state guard.
    validate_error(
        api.complete_replacement_order(ord2["id"], installer),
        ApiErrorId.ERR_ORDER_NOT_MATCHED,
    )
    # Opening an order on the REPLACED zone: the zone-state guard.
    payload = create_replacement_order_payload(
        site["id"], z1["id"], get_site_version(site["id"]),
        reason="WEAR", new_zone_code="Z-1X",
    )
    validate_error(
        api.create_replacement_order(
            payload, make_specifier_headers(site["created_by"])
        ),
        ApiErrorId.ERR_ZONE_NOT_IN_SERVICE,
    )


def test_order_with_zone_of_other_site_returns_422(api, admin_headers):
    """PRD §3.4: "The zone must belong to the named site: an order whose
    `zone_id` resolves to a zone of a different site is rejected with
    `ERR_ZONE_SITE_MISMATCH` (HTTP 422)"
    PRD §3.4: "Orders can be listed with optional `site_id`, `zone_id`,
    `matched_batch_id`, and `status` filters."

    Design: Corner/validations/order_with_zone_of_other_site_returns_422
    """
    set_clock()
    built = setup_collection_with_batch()
    site1 = create_installed_site()
    z1 = lay_zone(site1, built["batch"]["id"], zone_code="Z-1", area_m2=10)
    site2 = create_site(
        contractor_name="inst-cory",
        address="9 Meadow Ln",
        installation_system="ADHESIVE_FREE",
        adhesive_free_certified=True,
    )
    site2 = install_site(site2)
    payload = create_replacement_order_payload(
        site2["id"], z1["id"], get_site_version(site2["id"]),
        reason="WEAR", new_zone_code="Z-9",
    )
    resp = api.create_replacement_order(
        payload, make_specifier_headers(site2["created_by"])
    )
    validate_error(resp, ApiErrorId.ERR_ZONE_SITE_MISMATCH)
    rows, meta = validate_paginated(
        api.list_replacement_orders(admin_headers, params={"site_id": site2["id"]})
    )
    assert rows == []
    assert meta["total_count"] == 0


def test_occ_order_create_stale_site_version_returns_412(api, admin_headers):
    """PRD §2.7: "Opening a replacement order requires `expected_site_version`,
    holding the version of the target customer site the client last observed.
    If the value presented does not match the parent's current `version` —
    because another writer's create has advanced that version since the client
    last read it — the request is rejected with `ERR_STALE_VERSION`
    (HTTP 412)"

    Design: Corner/cross_cutting_layers/occ_order_create_stale_site_version_returns_412
    """
    set_clock()
    built = setup_collection_with_batch()
    site = create_installed_site()
    z1 = lay_zone(site, built["batch"]["id"], zone_code="Z-1", area_m2=10)
    z2 = lay_zone(site, built["batch"]["id"], zone_code="Z-2", area_m2=10)
    captured = get_site_version(site["id"])
    ord_a = create_order(
        site, z1, expected_site_version=captured, reason="WEAR", new_zone_code="Z-1R"
    )
    # Replaying the pre-ORD-A version for a different zone is still stale:
    # ORD-A's creation advanced the site's version.
    payload = create_replacement_order_payload(
        site["id"], z2["id"], captured, reason="DAMAGE", new_zone_code="Z-2R"
    )
    validate_error(
        api.create_replacement_order(
            payload, make_specifier_headers(site["created_by"])
        ),
        ApiErrorId.ERR_STALE_VERSION,
    )
    ord_b = create_order(site, z2, reason="DAMAGE", new_zone_code="Z-2R")
    assert ord_b["status"] == "DRAFT"
    assert ord_b["zone_id"] == z2["id"]
    ord_a_after = validate_success(api.get_replacement_order(ord_a["id"], admin_headers))
    assert ord_a_after["status"] == "DRAFT", "ORD-A on Z-1 is untouched"
