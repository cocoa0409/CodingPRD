"""Corner coverage: RBAC denials and identity scoping."""
from test_helpers import (
    ApiErrorId, certify_pair, create_factory_payload, get_claim, get_document,
    get_order, get_run, lock_allocation, make_claim, make_factory, make_order,
    make_run, reserve_run, set_clock, standard_kit, start_run,
    upload_document, validate_error, validate_paginated, validate_success,
)
from test_helpers import (
    TEST_USERS, api_client, make_customer_headers, make_factory_manager_headers,
)

api = api_client
ADMIN = TEST_USERS["admin"]
SOURCING = TEST_USERS["sourcing"]
PLANNER = TEST_USERS["planner"]
COMPLIANCE = TEST_USERS["compliance"]
TRAINING = TEST_USERS["training"]

SM1 = {"X-User-ID": "sm-1", "X-User-Role": "SourcingManager"}
CO1 = {"X-User-ID": "co-1", "X-User-Role": "ComplianceOfficer"}
CO2 = {"X-User-ID": "co-2", "X-User-Role": "ComplianceOfficer"}
CUST1 = {"X-User-ID": "cust-1", "X-User-Role": "CustomProgramCustomer"}


def test_sourcing_manager_cannot_verify_evidence():
    """PRD §2.1: "Each endpoint declares the roles permitted to call it. A
    caller whose role is not listed for that endpoint is rejected with
    `ERR_FORBIDDEN_ROLE` (HTTP 403)."
    PRD §3.8: "Verification moves a document from `SUBMITTED` to `VERIFIED`,
    and rejection from `SUBMITTED` to `REJECTED`, both `ComplianceOfficer`
    actions"

    Design: Corner/rbac/sourcing_manager_cannot_verify_evidence
    """
    kit = standard_kit(with_allocation=False, with_run=False)
    doc = upload_document("SUPPLIER_ORIGIN_CERT", "material_lot_id",
                          kit["lot"]["id"], uploader_id="sm-1")
    resp = api.verify_document(doc["id"], SM1)
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE)
    assert get_document(doc["id"])["status"] == "SUBMITTED"


def test_training_coordinator_cannot_create_factory():
    """PRD §2.1: "Each endpoint declares the roles permitted to call it. A
    caller whose role is not listed for that endpoint is rejected with
    `ERR_FORBIDDEN_ROLE` (HTTP 403)."
    PRD §3.1: "A `PlatformAdmin` creates a factory with a display
    `factory_name`"

    Design: Corner/rbac/training_coordinator_cannot_create_factory
    """
    resp = api.create_factory(create_factory_payload(factory_name="Rogue Plant"),
                              TRAINING)
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE)
    factories, meta = validate_paginated(api.list_factories(ADMIN))
    assert factories == [] and meta["total_count"] == 0


def test_production_planner_cannot_publish_claim():
    """PRD §2.1: "Each endpoint declares the roles permitted to call it. A
    caller whose role is not listed for that endpoint is rejected with
    `ERR_FORBIDDEN_ROLE` (HTTP 403)."
    PRD §2.8: "A failure in an earlier family masks every later family"

    Design: Corner/rbac/production_planner_cannot_publish_claim
    """
    kit = standard_kit(with_allocation=False, with_run=False)
    claim = make_claim(kit["model"]["id"], "MADE_IN_USA")  # DRAFT
    # Role authorization (family 2) fires before the wrong-state error a
    # DRAFT claim would otherwise produce.
    resp = api.publish_claim(claim["id"], PLANNER)
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE)
    assert get_claim(claim["id"])["status"] == "DRAFT"


def test_custom_program_customer_cannot_accept_orders():
    """PRD §2.1: "Each endpoint declares the roles permitted to call it. A
    caller whose role is not listed for that endpoint is rejected with
    `ERR_FORBIDDEN_ROLE` (HTTP 403)."
    PRD §3.7: "Acceptance is a `ProductionPlanner` action from `SUBMITTED`"

    Design: Corner/rbac/custom_program_customer_cannot_accept_orders
    """
    kit = standard_kit(with_allocation=False, with_run=False)
    order = make_order(kit["model"]["id"], buyer="cust-1")
    assert order["production_status"] == "SUBMITTED"

    resp = api.accept_order(order["id"], CUST1)
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE)
    after = get_order(order["id"])
    assert after["production_status"] == "SUBMITTED"
    assert after["quoted_price_cents"] is None


def test_factory_manager_holds_own_factory_run_but_not_others():
    """PRD §2.1: "When `X-User-Role` is `FactoryManager`, `X-User-ID` is the
    `id` of the acting `Factory`; ownership checks on any resource that
    references a `Factory` compare the resource's foreign-key field to
    `X-User-ID`."
    PRD §2.1: "A `FactoryManager` may place a production run on hold or resume
    it only when the run's `factory_id` equals `X-User-ID`; otherwise the call
    is rejected with `ERR_FACTORY_OWNERSHIP_MISMATCH` (HTTP 403)."

    Design: Corner/rbac/factory_manager_holds_own_factory_run_but_not_others
    """
    kit = standard_kit()
    lock_allocation(kit["allocation"]["id"])
    reserve_run(kit["run"]["id"])
    certify_pair(kit["factory"]["id"])
    kit["run"] = start_run(kit["run"]["id"])  # IN_PRODUCTION at factory 1
    f2 = make_factory(factory_name="Second Plant", weekly_capacity_units=500,
                      line_count=1)
    run2 = make_run(kit["model"]["id"], f2["id"], planned_units=5)  # PLANNED

    fm_own = make_factory_manager_headers(kit["factory"]["id"])
    held = validate_success(api.hold_run(kit["run"]["id"], fm_own))
    assert held["status"] == "QUALITY_HOLD"

    # Same manager on another factory's run: ownership (family 3) fires before
    # the wrong-state error the PLANNED run would otherwise produce.
    foreign = api.hold_run(run2["id"], fm_own)
    validate_error(foreign, ApiErrorId.ERR_FACTORY_OWNERSHIP_MISMATCH)
    planner_view = api.hold_run(run2["id"], PLANNER)
    validate_error(planner_view, ApiErrorId.ERR_INVALID_STATE)


def test_customer_cancels_own_order_but_not_foreign_order():
    """PRD §3.7: "Cancellation is available from `SUBMITTED`, `ACCEPTED`, or
    `SCHEDULED`, to a `ProductionPlanner` or to the `CustomProgramCustomer` who
    owns the order — the customer-scoped caller's `buyer_ref` must equal their
    `X-User-ID` or the request is rejected with `ERR_BUYER_REF_MISMATCH`."

    Design: Corner/rbac/customer_cancels_own_order_but_not_foreign_order
    """
    kit = standard_kit(with_allocation=False, with_run=False)
    order_a = make_order(kit["model"]["id"], buyer="cust-1")
    order_b = make_order(kit["model"]["id"], buyer="cust-2", as_customer=False)

    own = validate_success(api.cancel_order(order_a["id"], CUST1))
    assert own["production_status"] == "CANCELLED"

    foreign = api.cancel_order(order_b["id"], CUST1)
    validate_error(foreign, ApiErrorId.ERR_BUYER_REF_MISMATCH)

    # ProductionPlanner shares the cancel operation without the ownership clause.
    by_planner = validate_success(api.cancel_order(order_b["id"], PLANNER))
    assert by_planner["production_status"] == "CANCELLED"


def test_evidence_uploader_cannot_self_verify():
    """PRD §2.1: "And no one may verify or reject an evidence document they
    themselves uploaded: when the document's `uploaded_by` equals `X-User-ID`,
    verification or rejection is refused with `ERR_SELF_ATTESTATION_FORBIDDEN`
    (HTTP 403)."
    PRD §3.8: "The server records the uploader's `X-User-ID` in `uploaded_by`,
    and the document starts `SUBMITTED`."

    Design: Corner/rbac/evidence_uploader_cannot_self_verify
    """
    kit = standard_kit(with_allocation=False, with_run=False)
    # ComplianceOfficer may upload evidence; co-1 is then barred from review.
    resp = api.create_evidence_document({
        "doc_type": "SUPPLIER_ORIGIN_CERT", "issuer": "Fall River Mills",
        "valid_from": "2026-08-01", "valid_until": "2027-08-31",
        "material_lot_id": kit["lot"]["id"],
    }, CO1)
    doc = validate_success(resp, 201)
    assert doc["uploaded_by"] == "co-1"

    validate_error(api.verify_document(doc["id"], CO1),
                   ApiErrorId.ERR_SELF_ATTESTATION_FORBIDDEN)
    validate_error(api.reject_document(doc["id"], CO1),
                   ApiErrorId.ERR_SELF_ATTESTATION_FORBIDDEN)

    # A peer in the same role may verify it.
    verified = validate_success(api.verify_document(doc["id"], CO2))
    assert verified["status"] == "VERIFIED"
    assert verified["uploaded_by"] == "co-1"
