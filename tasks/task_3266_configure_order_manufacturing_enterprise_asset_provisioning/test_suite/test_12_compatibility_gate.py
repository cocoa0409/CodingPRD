"""The compatibility gate: MIN_QTY floors, end-of-life components, and the
interaction of the rule set with validation."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    create_account,
    create_chassis,
    create_component,
    add_allowed_rule,
    create_configuration,
    make_customer_user_headers,
    get_success_data,
    validate_error,
    validate_success,
)

ADMIN = TEST_USERS["platform_admin_headers"]
MANAGER = TEST_USERS["account_manager_headers"]


def test_min_qty_rule_violation_detected(api):
    """PRD §3.2: "Three preconditions must hold: the owning account's `status`
    is `ACTIVE`; every compatibility rule of the chassis passes over the
    selection — `ALLOWED` membership, `REQUIRES` closure, `EXCLUDES` absence,
    and `MIN_QTY` floors — with any failure rejected as
    `ERR_COMPATIBILITY_VIOLATION` (HTTP 422); and no selected component is in
    `EOL` status, with an end-of-life selection (or an end-of-life chassis)
    rejected as `ERR_COMPONENT_EOL` (HTTP 422)."
    PRD §3.1: "For a `MIN_QTY` rule, `min_qty` states the minimum quantity of
    the subject component that any valid selection must contain; otherwise
    `min_qty` is null."

    Design: Corner/calculations/min_qty_rule_violation_detected
    """
    account = create_account(company_name="CC2")
    chassis = create_chassis(model_code="CCL2", category="SERVER", base_price_cents=200_000)
    mem = create_component(sku="CCM2", kind="MEMORY", price_cents=9_000, lead_time_days=2)
    add_allowed_rule(chassis["id"], mem["id"])
    resp = api.create_compatibility_rule(
        {"chassis_model_id": chassis["id"], "component_id": mem["id"],
         "rule_type": "MIN_QTY", "min_qty": 2},
        ADMIN,
    )
    assert resp.status_code == 201
    config = create_configuration(account, chassis["id"],
                                  [{"component_id": mem["id"], "qty": 1}])
    resp = api.validate_configuration(config["id"], make_customer_user_headers(account["id"]))
    validate_error(resp, ApiErrorId.ERR_COMPATIBILITY_VIOLATION.value, 422)
    config_after = get_success_data(api.get_configuration(config["id"], MANAGER))
    assert config_after["status"] == "DRAFT"
    assert config_after["compatibility_ok"] is False


def test_eol_component_rejected_on_validate(api):
    """PRD §3.2: "no selected component is in `EOL` status, with an end-of-life
    selection (or an end-of-life chassis) rejected as `ERR_COMPONENT_EOL`
    (HTTP 422)."
    PRD §3.1: "A component begins `ACTIVE`; discontinuing it moves it to `EOL`
    — which blocks both future configuration validation and future
    substitutions naming it — and bumps the component's `version` by 1."

    Design: Corner/validations/eol_component_rejected_on_validate
    """
    account = create_account(company_name="VV2B")
    chassis = create_chassis(model_code="VVL2B")
    cpu = create_component(sku="VVC2B")
    add_allowed_rule(chassis["id"], cpu["id"])
    config = create_configuration(account, chassis["id"],
                                  [{"component_id": cpu["id"], "qty": 1}])
    resp = api.discontinue_component(cpu["id"], ADMIN)
    validate_success(resp, 200)
    resp = api.validate_configuration(config["id"], make_customer_user_headers(account["id"]))
    validate_error(resp, ApiErrorId.ERR_COMPONENT_EOL.value, 422)
    config_after = get_success_data(api.get_configuration(config["id"], MANAGER))
    assert config_after["status"] == "DRAFT"
