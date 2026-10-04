"""Confirm gauntlet tests: FIFO reservation, atomicity, credit/cap gates,
specialty compliance, OCC on order create."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    confirm_order,
    create_branch,
    create_order,
    create_order_line,
    create_product,
    create_sales_order_payload,
    create_specialty_product_payload,
    get_builder,
    get_lot,
    get_order,
    receive_lot,
    set_clock,
    setup_builder_with_job,
    validate_error,
    validate_success,
)
from test_helpers import api_client as api
from test_helpers.fixtures import ACCT


def test_confirm_reserves_oldest_lot_first_fifo():
    """PRD §3.6: "For each line, the candidate lots are those at the order's
    branch_id for the line's product with qty_available_mbf greater than 0,
    walked oldest-first by received_at ascending with created_at ascending as
    tie-break. From each lot in turn the reservation takes the smaller of the
    line's remaining quantity and the lot's qty_available_mbf, incrementing
    the lot's qty_reserved_mbf and decrementing qty_available_mbf
    accordingly, until the line's qty_mbf is fully satisfied".

    Design: Corner/state_machines/confirm_reserves_oldest_lot_first_fifo
    """
    set_clock("2026-09-01T00:00:00Z")
    product = create_product()
    branch = create_branch()
    set_clock("2026-09-02T08:00:00Z")
    lot1 = receive_lot(branch["id"], product["id"], 10, 50000)
    set_clock("2026-09-03T08:00:00Z")
    lot2 = receive_lot(branch["id"], product["id"], 10, 60000)

    builder, job = setup_builder_with_job(5000000)
    order = create_order(
        job["id"], branch["id"], builder["id"],
        qty_mbf=8, unit_price_cents=100000, product_id=product["id"],
    )
    confirmed = confirm_order(order["id"])

    l1 = get_lot(lot1["id"])
    assert l1["qty_reserved_mbf"] == 8
    assert l1["qty_available_mbf"] == 2
    assert l1["lot_status"] == "ON_HAND"

    l2 = get_lot(lot2["id"])
    assert l2["qty_reserved_mbf"] == 0
    assert l2["qty_available_mbf"] == 10

    assert confirmed["order_status"] == "CONFIRMED"
    assert confirmed["order_total_cents"] == 800000


def test_confirm_with_insufficient_inventory_is_atomic():
    """PRD §3.6: "If the total available across all candidate lots falls
    short of the line quantity, the entire confirm is rejected with
    ERR_INSUFFICIENT_INVENTORY (HTTP 409) and nothing is reserved — there are
    no partial reservations."

    Design: Corner/errors/confirm_with_insufficient_inventory_is_atomic
    """
    set_clock("2026-09-01T00:00:00Z")
    product = create_product()
    branch = create_branch()
    lot1 = receive_lot(branch["id"], product["id"], 10, 50000)
    lot2 = receive_lot(branch["id"], product["id"], 10, 60000)
    builder, job = setup_builder_with_job(9000000)
    order = create_order(
        job["id"], branch["id"], builder["id"],
        qty_mbf=25, unit_price_cents=100000, product_id=product["id"],
    )

    resp = api.confirm_sales_order(order["id"], ACCT)
    validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_INVENTORY)

    assert get_order(order["id"])["order_status"] == "DRAFT"
    assert get_lot(lot1["id"])["qty_reserved_mbf"] == 0
    assert get_lot(lot2["id"])["qty_reserved_mbf"] == 0
    assert get_builder(builder["id"])["exposure_committed_cents"] == 0


def test_job_exposure_cap_exceeded_at_confirm():
    """PRD §3.6: "likewise the job's exposure_committed_cents plus
    order_total_cents must not exceed job_exposure_cap_cents, equality
    allowed, or the confirm is ERR_JOB_EXPOSURE_CAP_EXCEEDED (HTTP 402)."

    Design: Corner/errors/job_exposure_cap_exceeded_at_confirm
    """
    set_clock("2026-09-01T00:00:00Z")
    product = create_product()
    branch = create_branch()
    receive_lot(branch["id"], product["id"], 100, 40000)
    builder, job = setup_builder_with_job(
        credit_limit_cents=9000000, job_exposure_cap_cents=1500000
    )
    order = create_order(
        job["id"], branch["id"], builder["id"],
        qty_mbf=20, unit_price_cents=100000, product_id=product["id"],
    )

    resp = api.confirm_sales_order(order["id"], ACCT)
    validate_error(resp, ApiErrorId.ERR_JOB_EXPOSURE_CAP_EXCEEDED)
    assert get_order(order["id"])["order_status"] == "DRAFT"
    assert get_builder(builder["id"])["exposure_committed_cents"] == 0


def test_confirm_specialty_product_without_code_report_rejected():
    """PRD §3.6: "Specialty compliance requires that if any line's product
    has requires_code_report true, the order's code_report_reference must be
    non-null, else ERR_CODE_REPORT_REQUIRED (HTTP 400)."

    Design: Corner/errors/confirm_specialty_product_without_code_report_rejected
    """
    set_clock("2026-09-01T00:00:00Z")
    product = validate_success(
        api.create_product(
            create_specialty_product_payload(), TEST_USERS["ops_admin_headers"]
        ),
        expected_status=201,
    )
    branch = create_branch(
        branch_code="BR-ATL", region_code="SE",
        species_preference="SOUTHERN_PINE", activity_score=80,
    )
    receive_lot(branch["id"], product["id"], 100, 70000)
    builder, job = setup_builder_with_job(9000000)

    o_no = create_order(
        job["id"], branch["id"], builder["id"],
        qty_mbf=5, unit_price_cents=120000, product_id=product["id"],
    )
    o_yes = create_order(
        job["id"], branch["id"], builder["id"],
        qty_mbf=5, unit_price_cents=120000, product_id=product["id"],
        code_report_reference="ICC-ESR-1153",
    )

    resp = api.confirm_sales_order(o_no["id"], ACCT)
    validate_error(resp, ApiErrorId.ERR_CODE_REPORT_REQUIRED)
    assert get_order(o_no["id"])["order_status"] == "DRAFT"

    confirmed = confirm_order(o_yes["id"])
    assert confirmed["order_status"] == "CONFIRMED"
    assert confirmed["order_total_cents"] == 600000


def test_index_line_without_any_index_entry_rejected():
    """PRD §3.2: "If no entry qualifies, the pricing attempt fails with
    ERR_PRICE_INDEX_MISSING (HTTP 409)."

    Design: Corner/errors/index_line_without_any_index_entry_rejected
    """
    set_clock("2026-09-01T00:00:00Z")
    product = create_product()
    branch = create_branch()
    receive_lot(branch["id"], product["id"], 100, 40000)
    builder, job = setup_builder_with_job(9000000)
    order = create_order(
        job["id"], branch["id"], builder["id"],
        qty_mbf=10, price_basis="INDEX", product_id=product["id"],
    )

    resp = api.confirm_sales_order(order["id"], ACCT)
    validate_error(resp, ApiErrorId.ERR_PRICE_INDEX_MISSING)
    order_now = get_order(order["id"])
    assert order_now["order_status"] == "DRAFT"
    assert order_now["order_total_cents"] == 0
    assert get_builder(builder["id"])["exposure_committed_cents"] == 0


def test_occ_stale_builder_version_on_order_create_rejected_412():
    """PRD §2.7: "Creating a direct sales order against a job requires the
    request body to carry expected_builder_version, the client-last-observed
    version of the Builder that owns the job. Order creation mutates the
    builder's exposure basis and bumps Builder.version, so if the builder's
    current version no longer matches expected_builder_version ... the create
    is rejected with ERR_STALE_VERSION (HTTP 412)."

    Design: Corner/cross_cutting_layers/occ_stale_builder_version_on_order_create_rejected_412
    """
    set_clock("2026-09-01T00:00:00Z")
    product = create_product()
    branch = create_branch()
    builder, job = setup_builder_with_job(9000000)
    observed_version = get_builder(builder["id"])["version"]

    o1 = create_order(
        job["id"], branch["id"], builder["id"],
        qty_mbf=1, unit_price_cents=100000, product_id=product["id"],
    )
    assert o1["order_status"] == "DRAFT"

    resp = api.create_sales_order(
        job["id"],
        create_sales_order_payload(
            branch["id"],
            observed_version,
            lines=[create_order_line(product["id"], qty_mbf=2)],
        ),
        ACCT,
    )
    validate_error(resp, ApiErrorId.ERR_STALE_VERSION)

    fresh_version = get_builder(builder["id"])["version"]
    assert fresh_version == observed_version + 1

    resp = api.create_sales_order(
        job["id"],
        create_sales_order_payload(
            branch["id"],
            fresh_version,
            lines=[create_order_line(product["id"], qty_mbf=2)],
        ),
        ACCT,
    )
    o2 = validate_success(resp, expected_status=201)
    assert o2["order_status"] == "DRAFT"
