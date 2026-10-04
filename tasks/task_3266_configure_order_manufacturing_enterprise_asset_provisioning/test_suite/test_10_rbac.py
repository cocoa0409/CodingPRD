"""RBAC: role denials, entity-backed ownership isolation, and segregation of
duties between the customer, the account team, and the factory."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    create_account,
    create_chassis,
    create_component,
    add_allowed_rule,
    create_program,
    create_validated_configuration,
    create_order_with_lines,
    get_order_build_jobs,
    setup_submitted_order,
    make_customer_user_headers,
    get_success_data,
    validate_error,
)

ADMIN = TEST_USERS["platform_admin_headers"]
MANAGER = TEST_USERS["account_manager_headers"]
OPS = TEST_USERS["factory_ops_headers"]


def test_customer_cannot_allocate_build_job(api):
    """PRD §2.1: "`FactoryOps` is the factory operator responsible for
    allocation, build sequencing, build completion, substitution proposals,
    and wave shipment."
    PRD §2.1: "A request whose role is not permitted to invoke the target
    endpoint — including an entity-backed ownership mismatch — is rejected
    with `ERR_FORBIDDEN` (HTTP 403)."

    Design: Corner/roles/customer_cannot_allocate_build_job
    """
    env = setup_submitted_order()
    job = env["jobs"][0]
    resp = api.allocate_build_job(job["id"], make_customer_user_headers(env["account"]["id"]))
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN.value, 403)
    job_after = get_success_data(api.get_build_job(job["id"], OPS))
    assert job_after["status"] == "QUEUED"


def test_account_manager_cannot_submit_order(api):
    """PRD §2.1: "This role creates and validates configurations, builds and
    submits orders, approves or rejects substitution requests, confirms wave
    receipt, and initiates or cancels asset-recovery requests."
    PRD §2.1: "A request whose role is not permitted to invoke the target
    endpoint — including an entity-backed ownership mismatch — is rejected
    with `ERR_FORBIDDEN` (HTTP 403)."

    Design: Corner/roles/account_manager_cannot_submit_order
    """
    account = create_account(company_name="RB2")
    chassis = create_chassis(model_code="RBL2")
    cpu = create_component(sku="RBC2")
    add_allowed_rule(chassis["id"], cpu["id"])
    config = create_validated_configuration(account, chassis["id"],
                                            [{"component_id": cpu["id"], "qty": 1}])
    order, _ = create_order_with_lines(
        account, [{"configuration_id": config["id"], "qty": 1, "ship_to_mode": "SINGLE_ADDRESS"}],
        po_number="PO-RB2",
    )
    resp = api.submit_order(
        order["id"], {"expected_configuration_version": config["version"]}, MANAGER,
    )
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN.value, 403)
    order_after = get_success_data(api.get_order(order["id"], MANAGER))
    assert order_after["build_status"] == "DRAFT"


def test_factory_ops_cannot_lock_program(api):
    """PRD §2.1: "`AccountManager` is the manufacturer account-team member
    responsible for enterprise programs, configuration templates,
    configuration locking, deployment waves, and support entitlements."
    PRD §2.1: "A request whose role is not permitted to invoke the target
    endpoint — including an entity-backed ownership mismatch — is rejected
    with `ERR_FORBIDDEN` (HTTP 403)."

    Design: Corner/roles/factory_ops_cannot_lock_program
    """
    account = create_account(company_name="RB3")
    program = create_program(account["id"], name="P-RB3")
    resp = api.lock_program(program["id"], OPS)
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN.value, 403)
    program_after = get_success_data(api.get_program(program["id"], MANAGER))
    assert program_after["status"] == "OPEN"


def test_customer_cannot_access_other_accounts_order(api):
    """PRD §2.1: "When `X-User-Role` is `CustomerUser`, `X-User-ID` is the `id`
    of the acting `CustomerAccount`; ownership checks on any resource that
    references a `CustomerAccount` — directly or through a chain such as order
    to account, or order line to order to account — compare the resource's
    owning-account foreign key to `X-User-ID`, and a mismatch is rejected with
    `ERR_FORBIDDEN`."

    Design: Corner/roles/customer_cannot_access_other_accounts_order
    """
    account_a = create_account(company_name="RB4A")
    account_b = create_account(company_name="RB4B")
    resp = api.create_order(
        {"account_id": account_a["id"], "po_number": "PO-RB4"},
        make_customer_user_headers(account_a["id"]),
    )
    order = get_success_data(resp)
    resp = api.get_order(order["id"], make_customer_user_headers(account_b["id"]))
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN.value, 403)
