"""Cross-cutting layers: optimistic concurrency on order submit and component
restock, plus the error envelope shape."""
from test_helpers import (
    ApiErrorId,
    NON_EXISTENT_UUID,
    TEST_USERS,
    allocate_job,
    create_account,
    create_chassis,
    create_component,
    add_allowed_rule,
    create_validated_configuration,
    create_order_with_lines,
    get_order_build_jobs,
    submit_order,
    setup_submitted_order,
    make_customer_user_headers,
    get_success_data,
    validate_error,
)

ADMIN = TEST_USERS["platform_admin_headers"]
MANAGER = TEST_USERS["account_manager_headers"]
OPS = TEST_USERS["factory_ops_headers"]


def test_order_submit_stale_configuration_version_occ(api):
    """PRD §2.6: "A submission request must carry
    `expected_configuration_version` holding the client's last observed
    `version` of the configuration referenced by the order's lines. If the
    referenced configuration's current `version` has advanced since that
    observation — for example because the configuration was unlocked, edited,
    and re-validated after the client priced it — the submission is rejected
    with `ERR_STALE_CONFIGURATION_VERSION` (HTTP 412). A successful submission
    itself increments each referenced configuration's `version` by 1."

    Design: Corner/cross_cutting_layers/order_submit_stale_configuration_version_occ
    """
    account = create_account(company_name="XL1")
    chassis = create_chassis(model_code="XLL1")
    cpu = create_component(sku="XLC1")
    add_allowed_rule(chassis["id"], cpu["id"])
    config = create_validated_configuration(account, chassis["id"],
                                            [{"component_id": cpu["id"], "qty": 1}])
    observed_version = config["version"]
    order_a, _ = create_order_with_lines(
        account, [{"configuration_id": config["id"], "qty": 1, "ship_to_mode": "SINGLE_ADDRESS"}],
        po_number="PO-XL1A",
    )
    submit_order(account, order_a, observed_version)  # bumps config version
    order_b, _ = create_order_with_lines(
        account, [{"configuration_id": config["id"], "qty": 1, "ship_to_mode": "SINGLE_ADDRESS"}],
        po_number="PO-XL1B",
    )
    resp = api.submit_order(
        order_b["id"], {"expected_configuration_version": observed_version},
        make_customer_user_headers(account["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_STALE_CONFIGURATION_VERSION.value, 412)
    order_b_after = get_success_data(api.get_order(order_b["id"], MANAGER))
    assert order_b_after["build_status"] == "DRAFT"


def test_restock_stale_component_version_occ(api):
    """PRD §2.6: "A restock request must carry `expected_component_version`
    holding the client's last observed `version` of the component being
    replenished. If the component's current `version` has advanced since the
    client read its stock — because an allocation cycle or a prior restock has
    already moved the pool — the restock is rejected with
    `ERR_STALE_COMPONENT_VERSION` (HTTP 412)."

    Design: Corner/cross_cutting_layers/restock_stale_component_version_occ
    """
    account = create_account(company_name="XL2")
    chassis = create_chassis(model_code="XLL2")
    cpu = create_component(sku="XLC2")
    observed_version = cpu["version"]
    add_allowed_rule(chassis["id"], cpu["id"])
    config = create_validated_configuration(account, chassis["id"],
                                            [{"component_id": cpu["id"], "qty": 1}])
    order, _ = create_order_with_lines(
        account, [{"configuration_id": config["id"], "qty": 1, "ship_to_mode": "SINGLE_ADDRESS"}],
        po_number="PO-XL2",
    )
    submit_order(account, order, config["version"])
    job = get_order_build_jobs(order["id"])[0]
    allocate_job(job["id"])  # allocation cycle moves the pool
    resp = api.restock_component(
        cpu["id"], {"add_units": 5, "expected_component_version": observed_version}, OPS,
    )
    validate_error(resp, ApiErrorId.ERR_STALE_COMPONENT_VERSION.value, 412)
    cpu_after = get_success_data(api.get_component(cpu["id"], OPS))
    assert cpu_after["stock_on_hand"] == 10


def test_error_envelope_shape(api):
    """PRD §2.2: "The `meta` object for error responses contains only
    `api_request_id` and `api_request_timestamp`."
    PRD §2.2: "The `error_id` is a unique, machine-readable string that
    identifies the specific error. The `message` provides a human-readable
    explanation of what went wrong."

    Design: Corner/errors/error_envelope_shape
    """
    resp = api.get_account(NON_EXISTENT_UUID, ADMIN)
    body = resp.json()
    assert body["response_type"] == "error"
    assert set(body["meta"].keys()) == {"api_request_id", "api_request_timestamp"}
    assert isinstance(body["data"]["error_id"], str)
    assert body["data"]["error_id"] == "ERR_NOT_FOUND"
    assert isinstance(body["data"]["message"], str) and body["data"]["message"].strip()
