"""Credit-boundary and cross-entity gating tests."""
from test_helpers import (
    ApiErrorId,
    confirm_order,
    create_branch,
    create_builder,
    create_job,
    create_order,
    create_product,
    get_builder,
    get_order,
    receive_lot,
    set_clock,
    setup_builder_with_job,
    validate_error,
    validate_success,
)
from test_helpers import api_client as api
from test_helpers.fixtures import ACCT, CREDIT


def _credit_boundary_setup():
    """Branch stocked 1000 mbf; builder ACTIVE with limit 5000000; job with a
    generous cap; three DRAFT orders A=20 mbf, B=30 mbf, C=1 mbf FIXED @ 100000."""
    product = create_product()
    branch = create_branch()
    receive_lot(branch["id"], product["id"], 1000, 40000)
    builder, job = setup_builder_with_job(5000000, 100000000)
    o_a = create_order(job["id"], branch["id"], builder["id"], qty_mbf=20,
                       unit_price_cents=100000, product_id=product["id"])
    confirm_order(o_a["id"])
    o_b = create_order(job["id"], branch["id"], builder["id"], qty_mbf=30,
                       unit_price_cents=100000, product_id=product["id"])
    o_c = create_order(job["id"], branch["id"], builder["id"], qty_mbf=1,
                       unit_price_cents=100000, product_id=product["id"])
    return builder, o_b, o_c


def test_credit_headroom_exactly_zero_confirm_allowed():
    """PRD §3.6: "the builder's exposure_committed_cents plus this order's
    order_total_cents must not exceed credit_limit_cents — equality is
    allowed — or the confirm is ERR_CREDIT_LIMIT_EXCEEDED (HTTP 402)".

    Design: Difficulty/boundary_precision_check/credit_headroom_exactly_zero_confirm_allowed
    """
    set_clock("2026-09-01T00:00:00Z")
    builder, o_b, o_c = _credit_boundary_setup()

    confirmed_b = confirm_order(o_b["id"])
    assert confirmed_b["order_status"] == "CONFIRMED", (
        "2000000 + 3000000 == 5000000 must be allowed (equality)"
    )

    resp = api.confirm_sales_order(o_c["id"], ACCT)
    validate_error(resp, ApiErrorId.ERR_CREDIT_LIMIT_EXCEEDED)

    assert get_builder(builder["id"])["exposure_committed_cents"] == 5000000


def test_credit_headroom_one_cent_over_limit_rejected():
    """PRD §3.6: "the builder's exposure_committed_cents plus this order's
    order_total_cents must not exceed credit_limit_cents — equality is
    allowed — or the confirm is ERR_CREDIT_LIMIT_EXCEEDED (HTTP 402)". An
    order one cent past the remaining headroom is rejected while the
    exact-headroom order still confirms.

    Design: Difficulty/boundary_precision_check/credit_headroom_exactly_zero_confirm_allowed
    """
    set_clock("2026-09-01T00:00:00Z")
    product = create_product()
    branch = create_branch()
    receive_lot(branch["id"], product["id"], 1000, 40000)
    builder, job = setup_builder_with_job(5000000, 100000000)
    o_a = create_order(job["id"], branch["id"], builder["id"], qty_mbf=20,
                       unit_price_cents=100000, product_id=product["id"])
    confirm_order(o_a["id"])

    # Order priced at 3000001 cents: 2000000 + 3000001 > 5000000.
    version = get_builder(builder["id"])["version"]
    resp = api.create_sales_order(
        job["id"],
        {
            "branch_id": branch["id"],
            "pricing_week_mode": "LOCK_AT_ACCEPT",
            "lines": [{
                "product_id": product["id"],
                "qty_mbf": 30,
                "price_basis": "FIXED",
                "fixed_unit_price_cents_per_mbf": 100000,
            }, {
                "product_id": product["id"],
                "qty_mbf": 1,
                "price_basis": "FIXED",
                "fixed_unit_price_cents_per_mbf": 1,
            }],
            "expected_builder_version": version,
        },
        ACCT,
    )
    o_over = validate_success(resp, expected_status=201)
    resp = api.confirm_sales_order(o_over["id"], ACCT)
    validate_error(resp, ApiErrorId.ERR_CREDIT_LIMIT_EXCEEDED)
    assert get_order(o_over["id"])["order_status"] == "DRAFT"
    assert get_builder(builder["id"])["exposure_committed_cents"] == 2000000


def test_order_confirm_gated_by_builder_credit_active():
    """PRD §3.6: "First the order must belong to a builder whose credit_status
    is ACTIVE, with the same split of ERR_BUILDER_CREDIT_SUSPENDED versus
    ERR_BUILDER_NOT_CREDIT_ACTIVE as take-off acceptance." PRD §3.4:
    "Approving a SUSPENDED builder returns it to ACTIVE and updates
    credit_limit_cents under the same requirement".

    Design: Difficulty/cross_entity_state_dependency/order_confirm_gated_by_builder_credit_active
    """
    set_clock("2026-09-01T00:00:00Z")
    product = create_product()
    branch = create_branch()
    receive_lot(branch["id"], product["id"], 20, 40000)
    builder, job = setup_builder_with_job(5000000)
    order = create_order(job["id"], branch["id"], builder["id"], qty_mbf=10,
                         unit_price_cents=100000, product_id=product["id"])

    resp = api.credit_review(builder["id"], {"decision": "SUSPEND"}, CREDIT)
    validate_success(resp)

    resp = api.confirm_sales_order(order["id"], ACCT)
    validate_error(resp, ApiErrorId.ERR_BUILDER_CREDIT_SUSPENDED)

    resp = api.credit_review(
        builder["id"],
        {"decision": "APPROVE", "credit_limit_cents": 5000000},
        CREDIT,
    )
    validate_success(resp)

    confirmed = confirm_order(order["id"])
    assert confirmed["order_status"] == "CONFIRMED"
    assert get_builder(builder["id"])["exposure_committed_cents"] == 1000000


def test_order_confirm_on_provisional_builder_rejected_not_credit_active():
    """PRD §3.6: "First the order must belong to a builder whose credit_status
    is ACTIVE, with the same split of ERR_BUILDER_CREDIT_SUSPENDED versus
    ERR_BUILDER_NOT_CREDIT_ACTIVE as take-off acceptance." PRD §3.5: "the
    builder's credit_status must be ACTIVE, with SUSPENDED rejecting as
    ERR_BUILDER_CREDIT_SUSPENDED (HTTP 402) and PROVISIONAL or CLOSED
    rejecting as ERR_BUILDER_NOT_CREDIT_ACTIVE (HTTP 402)".

    Design: Difficulty/cross_entity_state_dependency/order_confirm_gated_by_builder_credit_active
    """
    set_clock("2026-09-01T00:00:00Z")
    product = create_product()
    branch = create_branch()
    receive_lot(branch["id"], product["id"], 20, 40000)

    # PROVISIONAL builder (never approved). Order creation still requires OCC
    # on the builder version but is not credit-gated at create time.
    provisional = create_builder("Provisional Builders", "OR")
    job = create_job(provisional["id"])

    version = provisional["version"]
    resp = api.create_sales_order(
        job["id"],
        {
            "branch_id": branch["id"],
            "pricing_week_mode": "LOCK_AT_ACCEPT",
            "lines": [{
                "product_id": product["id"],
                "qty_mbf": 10,
                "price_basis": "FIXED",
                "fixed_unit_price_cents_per_mbf": 100000,
            }],
            "expected_builder_version": version,
        },
        ACCT,
    )
    order = validate_success(resp, expected_status=201)

    resp = api.confirm_sales_order(order["id"], ACCT)
    validate_error(resp, ApiErrorId.ERR_BUILDER_NOT_CREDIT_ACTIVE)
    assert get_order(order["id"])["order_status"] == "DRAFT"
