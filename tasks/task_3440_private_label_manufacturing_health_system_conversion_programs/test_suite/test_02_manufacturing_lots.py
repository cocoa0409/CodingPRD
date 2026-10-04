"""Manufacturing lots, QA disposition, and segregation-of-duties tests."""
from test_helpers import (
    NON_EXISTENT_UUID,
    TEST_USERS,
    ApiErrorId,
    assert_manufacturing_lot,
    create_batch,
    create_lot,
    create_product,
    create_registered_product,
    get_success_data,
    make_planner_headers,
    make_quality_headers,
    record_qa_disposition,
    record_sterility_result,
    validate_error,
    validate_success,
)

ADMIN = TEST_USERS["admin_headers"]
QUALITY = TEST_USERS["quality_headers"]


def test_lot_create_branded_product_422(api):
    """PRD §3.2: "the product's `brand_type` must be `PRIVATE_LABEL` (a lot
    against a `BRANDED` product is rejected with `ERR_NOT_PRIVATE_LABEL`,
    HTTP 422)".

    Design: Corner/entities/lot_create_branded_product_rejected
    """
    branded = create_product(sku="BP-1", brand_type="BRANDED")
    resp = api.create_manufacturing_lot(
        {
            "lot_code": "LOT-B1",
            "product_id": branded["id"],
            "quantity": 100,
            "manufacture_date": "2026-08-01",
            "expiry_date": "2027-08-01",
        },
        headers=make_planner_headers("planner-1"),
    )
    validate_error(resp, ApiErrorId.ERR_NOT_PRIVATE_LABEL.value)


def test_lot_create_unregistered_product_422(api):
    """PRD §3.2: "the product's `registration_status` must be `REGISTERED`
    (otherwise `ERR_PRODUCT_NOT_REGISTERED`, HTTP 422)".

    Design: Corner/entities/lot_create_unregistered_product_rejected
    """
    unregistered = create_product(sku="UP-1", brand_type="PRIVATE_LABEL")
    resp = api.create_manufacturing_lot(
        {
            "lot_code": "LOT-U1",
            "product_id": unregistered["id"],
            "quantity": 100,
            "manufacture_date": "2026-08-01",
            "expiry_date": "2027-08-01",
        },
        headers=make_planner_headers("planner-1"),
    )
    validate_error(resp, ApiErrorId.ERR_PRODUCT_NOT_REGISTERED.value)


def test_lot_nonsterile_sterility_not_required(api):
    """PRD §3.2: "Its computed `sterility_status` starts as `NOT_REQUIRED` when
    the product's `sterile` flag is false, and `PENDING` otherwise."
    PRD §3.2: "A new lot starts in `AWAITING_QA` status with `created_by`
    stamped to the acting planner's `X-User-ID`".

    Design: Corner/entities/lot_nonsterile_product_marks_sterility_not_required
    """
    product = create_registered_product(
        sku="NP-1", brand_type="PRIVATE_LABEL", sterile=False
    )
    lot = create_lot(product["id"], lot_code="LOT-N1")
    assert_manufacturing_lot(lot)
    assert lot["sterility_status"] == "NOT_REQUIRED"
    assert lot["status"] == "AWAITING_QA"
    assert lot["created_by"] == "planner-1"


def test_lot_create_equal_dates_422(api):
    """PRD §3.2: "an `expiry_date` that must fall strictly after the manufacture
    date — a lot whose expiry does not strictly follow its manufacture date is
    rejected with `ERR_LOT_DATES_INVALID` (HTTP 422)".

    Design: Corner/entities/lot_create_reversed_dates_rejected
    """
    product = create_registered_product(sku="NP-2", brand_type="PRIVATE_LABEL")
    resp = api.create_manufacturing_lot(
        {
            "lot_code": "LOT-D1",
            "product_id": product["id"],
            "quantity": 100,
            "manufacture_date": "2026-08-01",
            "expiry_date": "2026-08-01",
        },
        headers=make_planner_headers("planner-1"),
    )
    validate_error(resp, ApiErrorId.ERR_LOT_DATES_INVALID.value)


def test_lot_create_duplicate_code_409(api):
    """PRD §3.2: "A `ManufacturingPlanner` creates a `ManufacturingLot` by naming
    a `lot_code` (globally unique; a collision is rejected with
    `ERR_DUPLICATE_LOT_CODE`, HTTP 409)".

    Design: Corner/validations/duplicate_lot_code_rejected
    """
    product = create_registered_product(sku="DL-1", brand_type="PRIVATE_LABEL")
    create_lot(product["id"], lot_code="LOT-DUP")
    resp = api.create_manufacturing_lot(
        {
            "lot_code": "LOT-DUP",
            "product_id": product["id"],
            "quantity": 50,
            "manufacture_date": "2026-08-02",
            "expiry_date": "2027-08-02",
        },
        headers=make_planner_headers("planner-1"),
    )
    validate_error(resp, ApiErrorId.ERR_DUPLICATE_LOT_CODE.value)


def test_lot_disposition_from_terminal_409(api):
    """PRD §3.2: "A `RELEASE` is valid only from `AWAITING_QA` (anything else is
    `ERR_INVALID_STATE`)". PRD §3.2: "transitions the lot to `RELEASED` or
    `REJECTED` accordingly — both terminal".

    Design: Corner/state_machines/lot_disposition_from_terminal_rejected
    """
    product = create_registered_product(
        sku="TL-1", brand_type="PRIVATE_LABEL", sterile=False
    )
    lot = create_lot(product["id"], lot_code="LOT-T1", planner_id="planner-1")
    released = record_qa_disposition(lot["id"], "RELEASE", qm_id="qm-1")
    assert released["status"] == "RELEASED"
    resp = api.record_qa_disposition(
        lot["id"], {"disposition": "REJECT"}, make_quality_headers("qm-1")
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)
    reread = get_success_data(api.get_manufacturing_lot(lot["id"], QUALITY))
    assert reread["status"] == "RELEASED"
    assert reread["qa_disposition_by"] == "qm-1"


def test_qa_disposition_unknown_lot_404(api):
    """PRD §2.9: "the server validates existence before any business rule runs,
    resolving identifiers left-to-right and rejecting with `ERR_NOT_FOUND`
    (HTTP 404) at the first identifier that does not resolve."

    Design: Corner/validations/qa_disposition_unknown_lot_not_found
    """
    resp = api.record_qa_disposition(
        NON_EXISTENT_UUID, {"disposition": "RELEASE"}, QUALITY
    )
    validate_error(resp, ApiErrorId.ERR_NOT_FOUND.value, 404)


def test_quality_manager_cannot_create_lots_403(api):
    """PRD §2.1: "A request whose role is not among the roles authorized for the
    target endpoint is rejected with `ERR_UNAUTHORIZED_ROLE` (HTTP 403)".
    PRD §4: lot creation is authorized for `ManufacturingPlanner` only.

    Design: Corner/rbac/quality_manager_cannot_create_lots
    """
    product = create_registered_product(sku="RB2-P", brand_type="PRIVATE_LABEL")
    resp = api.create_manufacturing_lot(
        {
            "lot_code": "LOT-RB2",
            "product_id": product["id"],
            "quantity": 10,
            "manufacture_date": "2026-08-01",
            "expiry_date": "2027-08-01",
        },
        headers=make_quality_headers("qm-1"),
    )
    validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED_ROLE.value, 403)


def test_sod_lot_self_disposition_403(api):
    """PRD §3.2: "the planner who created the lot is barred from dispositioning
    it: on any disposition call, `created_by` must differ from the acting
    `X-User-ID`, otherwise `ERR_SOD_LOT_DISPOSITION` (HTTP 403)".

    Design: Corner/rbac/sod_lot_self_disposition_rejected
    """
    product = create_registered_product(
        sku="RB3-P", brand_type="PRIVATE_LABEL", sterile=False
    )
    lot = create_lot(product["id"], lot_code="LOT-RB3", planner_id="planner-1")
    # QualityManager role, but the same person id that created the lot.
    resp = api.record_qa_disposition(
        lot["id"], {"disposition": "RELEASE"}, make_quality_headers("planner-1")
    )
    validate_error(resp, ApiErrorId.ERR_SOD_LOT_DISPOSITION.value, 403)
    reread = get_success_data(api.get_manufacturing_lot(lot["id"], QUALITY))
    assert reread["status"] == "AWAITING_QA"


def test_lot_release_blocked_while_sterility_pending(api):
    """PRD §3.2: "A `RELEASE` is valid only from `AWAITING_QA` (anything else is
    `ERR_INVALID_STATE`) and stacks three further guards, evaluated in this order
    after the state check: the lot's product must be `REGISTERED` (else
    `ERR_PRODUCT_NOT_REGISTERED`), the lot's `sterility_status` must be `PASSED`
    or `NOT_REQUIRED` (else `ERR_STERILITY_NOT_PASSED`, HTTP 422), and only then
    the segregation-of-duties check."

    Design: Difficulty/cross_entity_state_dependency/lot_release_requires_sterility_passed
    """
    product = create_registered_product(
        sku="LS-1", brand_type="PRIVATE_LABEL", sterile=True, category="STERILIZATION_SUPPLIES"
    )
    lot = create_lot(product["id"], lot_code="LOT-9001", quantity=500, planner_id="planner-1")
    assert lot["sterility_status"] == "PENDING"
    resp = api.record_qa_disposition(
        lot["id"], {"disposition": "RELEASE"}, make_quality_headers("qm-1")
    )
    validate_error(resp, ApiErrorId.ERR_STERILITY_NOT_PASSED.value, 422)
    reread = get_success_data(api.get_manufacturing_lot(lot["id"], QUALITY))
    assert reread["status"] == "AWAITING_QA"


def test_lot_release_after_batch_passed(api):
    """PRD §3.2: "On `PASSED`, each lot's `sterility_status` becomes `PASSED`
    while the lot's own `status` is left unchanged."
    PRD §3.2: "the lot's `sterility_status` must be `PASSED` or `NOT_REQUIRED`
    (else `ERR_STERILITY_NOT_PASSED`, HTTP 422)".

    Design: Difficulty/cross_entity_state_dependency/lot_release_requires_sterility_passed
    """
    product = create_registered_product(
        sku="LS-2", brand_type="PRIVATE_LABEL", sterile=True, category="STERILIZATION_SUPPLIES"
    )
    lot = create_lot(product["id"], lot_code="LOT-9002", quantity=500, planner_id="planner-1")
    batch = create_batch(
        [lot["id"]],
        batch_code="SB-001",
        chamber_id="CH-1",
        scheduled_start="2026-09-10T08:00:00Z",
        scheduled_end="2026-09-10T12:00:00Z",
    )
    record_sterility_result(batch["id"], "PASSED", qm_id="qm-1")
    mid = get_success_data(api.get_manufacturing_lot(lot["id"], QUALITY))
    assert mid["sterility_status"] == "PASSED"
    assert mid["status"] == "AWAITING_QA"
    released = record_qa_disposition(lot["id"], "RELEASE", qm_id="qm-1")
    assert released["status"] == "RELEASED"
    assert released["qa_disposition_by"] == "qm-1"


def test_immediate_consistency_action_response(api):
    """PRD §2.2: "Unless otherwise noted, operations that create or modify a
    resource will return the created or updated resource object in the data
    field." PRD §3.2: "Either accepted disposition stamps `qa_disposition_by`
    with the acting manager's `X-User-ID`, sets `qa_disposition_at` to the
    current logical clock, transitions the lot to `RELEASED` or `REJECTED`
    accordingly — both terminal — and increments the lot's `version` by 1."

    Design: Corner/consistency_model/immediate_consistency_action_response_reflects_mutation
    """
    product = create_registered_product(
        sku="IC-P", brand_type="PRIVATE_LABEL", sterile=False
    )
    lot = create_lot(product["id"], lot_code="LOT-IC1", quantity=10, planner_id="planner-1")
    resp = api.record_qa_disposition(
        lot["id"], {"disposition": "RELEASE"}, make_quality_headers("qm-9")
    )
    data = validate_success(resp)
    assert data["status"] == "RELEASED"
    assert data["version"] == 2
    assert data["qa_disposition_by"] == "qm-9"
    reread = get_success_data(api.get_manufacturing_lot(lot["id"], QUALITY))
    assert reread["status"] == data["status"]
    assert reread["version"] == data["version"]
