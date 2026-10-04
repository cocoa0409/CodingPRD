"""RBAC corners: role-level denials and entity-backed ownership checks."""
from test_helpers import (
    ApiErrorId,
    NON_EXISTENT_UUID,
    create_product_line_payload,
    get_success_data,
    make_active_formulation,
    make_completed_run,
    make_contractor,
    make_contractor_headers,
    make_dealer,
    make_dealer_headers,
    make_order,
    make_plant,
    make_product_line,
    make_registration,
    make_supplier,
    set_clock,
    stock_resin,
    validate_error,
)
from test_helpers.test_users import TEST_USERS

QE = TEST_USERS["quality_engineer_headers"]
PA = TEST_USERS["program_admin_headers"]
DSR = TEST_USERS["dealer_sales_rep_headers"]


def test_quality_engineer_cannot_create_product_lines(api):
    """PRD §2.1: "A request whose role is not permitted for the endpoint is
    rejected with `ERR_UNAUTHORIZED` (HTTP 403)."
    PRD §4: the product-line create row lists only `ProductManager`.

    Design: Corner/roles/quality_engineer_cannot_create_product_lines
    """
    form = make_active_formulation(lines=[{"material": "VIRGIN_PE", "weight_fraction_bp": 10000}])
    resp = api.create_product_line(
        create_product_line_payload(formulation_id=form["id"]), QE)
    validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED)


def test_dealer_cannot_confirm_own_order(api):
    """PRD §2.1: "A request whose role is not permitted for the endpoint is
    rejected with `ERR_UNAUTHORIZED` (HTTP 403)."
    PRD §4: the order-confirm row lists only `DealerSalesRep`.

    Design: Corner/roles/dealer_cannot_confirm_own_order
    """
    dealer = make_dealer(credit_limit_cents=1000000)
    form = make_active_formulation(lines=[{"material": "VIRGIN_PE", "weight_fraction_bp": 10000}])
    line = make_product_line(form["id"])
    order = make_order(dealer["id"], line["id"], 10, "2026-09-07")
    resp = api.confirm_shipment_order(order["id"], make_dealer_headers(dealer["id"]))
    validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED)
    order_after = get_success_data(api.get_shipment_order(order["id"], DSR))
    assert order_after["status"] == "REQUESTED"


def test_contractor_cannot_mark_other_contractors_registration(api):
    """PRD §2.1: "A contractor acting on another contractor's registration is
    rejected with `ERR_NOT_OWNER` (HTTP 403)"

    Design: Corner/roles/contractor_cannot_mark_other_contractors_registration
    """
    set_clock("2026-03-01T00:00:00Z")
    plant = make_plant()
    form = make_active_formulation(lines=[{"material": "VIRGIN_PE", "weight_fraction_bp": 10000}])
    line = make_product_line(form["id"])
    dealer = make_dealer(credit_limit_cents=1000000)
    supplier = make_supplier()
    stock_resin(plant, supplier["id"], materials=("VIRGIN_PE",), weight_lbs=500)
    _run, lot = make_completed_run(plant["id"], line["id"], 100, "2026-03-01")

    contractor_a = make_contractor(name="Pro A", email="a@build.example")
    contractor_b = make_contractor(name="Pro B", email="b@build.example")
    reg = make_registration(contractor_a["id"], dealer["id"], line["id"],
                            "2026-03-01", lot["id"])
    resp = api.cancel_install_registration(reg["id"], make_contractor_headers(contractor_b["id"]))
    validate_error(resp, ApiErrorId.ERR_NOT_OWNER)
    reg_after = get_success_data(api.get_install_registration(reg["id"], PA))
    assert reg_after["status"] == "PENDING"


def test_program_admin_cannot_adjudicate_claims(api):
    """PRD §2.1: "A request whose role is not permitted for the endpoint is
    rejected with `ERR_UNAUTHORIZED` (HTTP 403)."
    PRD §2.5: "Authorization comes second: a well-authenticated caller whose
    role is not permitted for the endpoint yields `ERR_UNAUTHORIZED`.
    Existence comes third"
    PRD §4: the claim-adjudicate row lists only `ClaimsAdjuster`.

    Design: Corner/roles/program_admin_cannot_adjudicate_claims
    """
    resp = api.adjudicate_claim(NON_EXISTENT_UUID,
                                {"decision": "APPROVE", "adjudication": "CREDIT"}, PA)
    validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED)
