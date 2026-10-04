"""Role-based access: exclusive operations, entity-backed ownership, segregation of duties."""

from prd_bench_local_runner.testing import validate_error, validate_success

from test_helpers import (
    QA_LEAD_HEADERS,
    fixtures,
    make_cashier_headers,
    make_store_manager_headers,
    make_supplier_rep_headers,
)


def test_supplierrep_cannot_create_tender(api):
    """A SupplierRep calling POST /v1/tenders is forbidden: 403 ERR_FORBIDDEN.

    PRD §2.1: "A request whose role is not permitted for the target endpoint — or that fails an entity-backed ownership check described below — is rejected with `ERR_FORBIDDEN` (HTTP 403)."
    PRD §2.1: "When `X-User-Role` is `SupplierRep`, `X-User-ID` is the `id` of the acting `Supplier`; ownership checks on any resource that references a `Supplier` compare the resource's foreign-key field to `X-User-ID`. A supplier representative bids only as their own supplier."

    Design: Corner/rbac/supplierrep_cannot_create_tender
    """
    category = fixtures.create_category(api)
    supplier = fixtures.create_supplier(api)
    product = fixtures.create_product(api, category["id"])

    response = api.create_tender(
        {"product_id": product["id"], "bid_ceiling_cents": 1000},
        make_supplier_rep_headers(supplier["id"]),
    )
    validate_error(response, "ERR_FORBIDDEN", 403)


def test_storemanager_scope_mismatch_forbidden(api):
    """A StoreManager of store S2 cannot open a shift in store S1: 403.

    PRD §2.1: "When `X-User-Role` is `StoreManager`, `X-User-ID` is the `id` of the acting `Store`; ownership checks on any resource that references a `Store` compare the resource's store foreign-key field to `X-User-ID`. A store manager operates exactly one store."
    PRD §2.1: "A request whose role is not permitted for the target endpoint — or that fails an entity-backed ownership check described below — is rejected with `ERR_FORBIDDEN` (HTTP 403)."

    Design: Corner/rbac/storemanager_scope_mismatch_forbidden
    """
    store1 = fixtures.create_store(api, code="S1")
    store2 = fixtures.create_store(api, code="S2")
    cashier = fixtures.create_employee(api, store1, role="CASHIER")

    response = api.create_register_shift(
        store1["id"],
        {"cashier_id": cashier["id"]},
        make_store_manager_headers(store2["id"]),
    )
    validate_error(response, "ERR_FORBIDDEN", 403)


def test_cashier_cannot_close_shift(api):
    """Closing a shift is a StoreManager action; a Cashier is forbidden even on their own.

    PRD §3.7: "Closing a shift — a `StoreManager` action restricted to the manager's own store — moves it `OPEN → CLOSED`, stamps `closed_at` from the logical clock, and computes the final variant exactly once: the count of scanned items minus 2 per void, multiplied by 3600 and divided by the shift's full duration in seconds (again with a denominator of at least 1), rounded half-up to 2 decimal places, stored as `final_scan_rate`."
    PRD §2.1: "A request whose role is not permitted for the target endpoint — or that fails an entity-backed ownership check described below — is rejected with `ERR_FORBIDDEN` (HTTP 403)."

    Design: Corner/rbac/cashier_cannot_close_shift
    """
    world = fixtures.store_with_cashier(api)
    shift = fixtures.open_shift(api, world["store"], world["cashier"])

    response = api.close_shift(shift["id"], make_cashier_headers(world["cashier"]["id"]))
    validate_error(response, "ERR_FORBIDDEN", 403)


def test_qa_lead_cannot_score_locked_panel_or_award_tender(api):
    """Scoring a LOCKED panel fails 409; awarding as QA fails 403 (segregation of duties).

    PRD §3.4: "Scoring against a panel that is not `SCHEDULED`, or whose tender has moved past `CLOSED`, is a state violation."
    PRD §2.1: "Segregation of duties is deliberate: the `QualityAssuranceLead` runs blind quality panels but cannot create, open, evaluate, or award tenders; the `ProcurementLead` runs tendering but never scores panels; the `OperationsAdmin` provisions stores and drives the logical clock but touches neither."

    Design: Corner/rbac/qa_lead_cannot_score_panel_on_closed_tender_after_evaluate
    """
    category = fixtures.create_category(api)
    sup_a = fixtures.create_supplier(api)
    sup_b = fixtures.create_supplier(api)
    product = fixtures.create_product(api, category["id"])
    tender, bids, panels = fixtures.tender_in_evaluating(
        api, product["id"], bids=[(sup_a, 700, 80), (sup_b, 800, 70)],
    )

    # Evaluation locked the panels: scoring again is a state violation.
    locked = api.score_panel(panels[0]["id"], {"score": 99}, QA_LEAD_HEADERS)
    validate_error(locked, "ERR_INVALID_STATE", 409)

    # The QA lead may never run the award step.
    forbidden = api.award_tender(
        tender["id"],
        {"primary_bid_id": bids[0]["id"], "secondary_bid_id": bids[1]["id"]},
        QA_LEAD_HEADERS,
    )
    validate_error(forbidden, "ERR_FORBIDDEN", 403)
