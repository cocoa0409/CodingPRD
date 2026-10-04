"""Configurations: initial state, validation gate, lock/unlock/supersede,
the program-lock constraint, and the configuration-in-use guard."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    create_account,
    create_chassis,
    create_component,
    add_allowed_rule,
    create_program,
    create_template,
    create_configuration,
    create_validated_configuration,
    create_order_with_lines,
    submit_order,
    make_customer_user_headers,
    get_success_data,
    validate_error,
    validate_success,
)

ADMIN = TEST_USERS["platform_admin_headers"]
MANAGER = TEST_USERS["account_manager_headers"]


def test_configuration_starts_in_draft(api):
    """PRD §3.2: "Validation is the gate that turns a draft into a purchasable
    object, moving the configuration from `DRAFT` to `VALIDATED`."
    PRD §3.2: "On success, `compatibility_ok` is set to true and the
    provisional lead-time estimate is recomputed onto
    `lead_time_estimate_days` as described in §3.3."

    Design: Corner/state_machines/configuration_starts_in_draft
    """
    account = create_account(company_name="SM-1")
    chassis = create_chassis(model_code="SML1")
    component = create_component(sku="SMC1")
    config = create_configuration(account, chassis["id"],
                                  [{"component_id": component["id"], "qty": 1}])
    assert config["status"] == "DRAFT"
    assert config["compatibility_ok"] is False


def test_validate_from_validated_is_invalid_state(api):
    """PRD §2.9: "then state-machine legality (the target resource is not in a
    state from which the requested transition is defined, `ERR_INVALID_STATE`)."
    PRD §3.2: "Validation is the gate that turns a draft into a purchasable
    object, moving the configuration from `DRAFT` to `VALIDATED`."

    Design: Corner/state_machines/validate_from_validated_is_invalid_state
    """
    account = create_account(company_name="SM-2")
    chassis = create_chassis(model_code="SML2")
    component = create_component(sku="SMC2")
    add_allowed_rule(chassis["id"], component["id"])
    config = create_validated_configuration(account, chassis["id"],
                                            [{"component_id": component["id"], "qty": 1}])
    resp = api.validate_configuration(config["id"], make_customer_user_headers(account["id"]))
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value, 409)
    again = get_success_data(api.get_configuration(config["id"], MANAGER))
    assert again["status"] == "VALIDATED"


def test_superseded_configuration_is_terminal(api):
    """PRD §3.2: "on success the old configuration moves from `DRAFT` to
    `SUPERSEDED` (its terminal state) while the new one is created in `DRAFT`,
    with no other field on the old record touched beyond the status flip."
    PRD §2.9: "then state-machine legality (the target resource is not in a
    state from which the requested transition is defined, `ERR_INVALID_STATE`)."

    Design: Corner/state_machines/superseded_configuration_is_terminal
    """
    account = create_account(company_name="SM-3")
    chassis = create_chassis(model_code="SML3")
    component = create_component(sku="SMC3")
    old = create_configuration(account, chassis["id"],
                               [{"component_id": component["id"], "qty": 1}])
    resp = api.create_configuration(
        {
            "account_id": account["id"],
            "chassis_model_id": chassis["id"],
            "component_selections": [{"component_id": component["id"], "qty": 2}],
            "supersedes_configuration_id": old["id"],
        },
        make_customer_user_headers(account["id"]),
    )
    validate_success(resp, 201)
    resp = api.validate_configuration(old["id"], make_customer_user_headers(account["id"]))
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value, 409)
    stale = get_success_data(api.get_configuration(old["id"], MANAGER))
    assert stale["status"] == "SUPERSEDED"


def test_configuration_lock_state_outranks_program_lock_constraint(api):
    """PRD §2.9: "then state-machine legality (the target resource is not in a
    state from which the requested transition is defined, `ERR_INVALID_STATE`).
    ... Business rules follow in their declared order — compatibility
    violations before end-of-life checks, program-lock violations before
    configuration-in-use ..."
    PRD §3.2: "Locking is how account programs freeze standards into place,
    moving a `VALIDATED` configuration to `LOCKED`."

    Design: Difficulty/priority_pair_validation_conflict/configuration_lock_state_outranks_program_lock_constraint
    """
    account = create_account(company_name="A11")
    program = create_program(account["id"], name="P11")
    chassis = create_chassis(model_code="L11", category="WORKSTATION", base_price_cents=150_000)
    gpu = create_component(sku="GPU11", kind="GPU", price_cents=50_000, lead_time_days=6)
    add_allowed_rule(chassis["id"], gpu["id"])
    template = create_template(program["id"], chassis["id"],
                               [{"component_id": gpu["id"], "revision": "A01", "qty": 1}],
                               name="T11")
    resp = api.publish_template(template["id"], MANAGER)
    assert resp.status_code == 200
    # Configuration from the template, left in DRAFT (never validated);
    # program never locked — both gates would fail.
    config = create_configuration(account, chassis["id"],
                                  [{"component_id": gpu["id"], "qty": 1}],
                                  template_id=template["id"])
    resp = api.lock_configuration(config["id"], MANAGER)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value, 409)
    data = resp.json()["data"]
    assert data["error_id"] != ApiErrorId.ERR_PROGRAM_LOCK_VIOLATION.value
    after = get_success_data(api.get_configuration(config["id"], MANAGER))
    assert after["status"] == "DRAFT"


def test_configuration_lock_draft_rejected_even_when_program_locked(api):
    """PRD §3.2: "Locking is how account programs freeze standards into place,
    moving a `VALIDATED` configuration to `LOCKED`."
    PRD §2.9: "then state-machine legality (the target resource is not in a
    state from which the requested transition is defined, `ERR_INVALID_STATE`)."

    Design: Difficulty/priority_pair_validation_conflict/configuration_lock_state_outranks_program_lock_constraint
    """
    account = create_account()
    program = create_program(account["id"])
    chassis = create_chassis()
    component = create_component()
    add_allowed_rule(chassis["id"], component["id"])
    template = create_template(program["id"], chassis["id"],
                               [{"component_id": component["id"], "revision": "A01", "qty": 1}])
    api.publish_template(template["id"], MANAGER)
    resp = api.lock_program(program["id"], MANAGER)
    assert resp.status_code == 200
    config = create_configuration(account, chassis["id"],
                                  [{"component_id": component["id"], "qty": 1}],
                                  template_id=template["id"])
    # DRAFT config under a LOCKED program: only the state gate can fire.
    resp = api.lock_configuration(config["id"], MANAGER)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value, 409)


def test_program_lock_violation_error(api):
    """PRD §3.2: "An `AccountManager` may lock a configuration only when three
    conditions hold: the configuration's `template_id` is non-null, the
    template's program is itself in `LOCKED` status, and every entry of the
    template's `pinned_components` appears in the configuration's
    `component_selections` with the matching `revision`. A violation is
    rejected with `ERR_PROGRAM_LOCK_VIOLATION` (HTTP 422)."

    Design: Corner/errors/program_lock_violation_error
    """
    account = create_account(company_name="ER2")
    program = create_program(account["id"], name="P2")
    chassis = create_chassis(model_code="ERL2")
    component = create_component(sku="ERC2")
    add_allowed_rule(chassis["id"], component["id"])
    template = create_template(program["id"], chassis["id"],
                               [{"component_id": component["id"], "revision": "A01", "qty": 1}],
                               name="T2")
    api.publish_template(template["id"], MANAGER)
    config = create_validated_configuration(
        account, chassis["id"], [{"component_id": component["id"], "qty": 1}],
        template_id=template["id"],
    )
    # VALIDATED config (state gate passes) under an OPEN program.
    resp = api.lock_configuration(config["id"], MANAGER)
    validate_error(resp, ApiErrorId.ERR_PROGRAM_LOCK_VIOLATION.value, 422)
    after = get_success_data(api.get_configuration(config["id"], MANAGER))
    assert after["status"] == "VALIDATED"


def test_unlock_configuration_in_use_rejected(api):
    """PRD §3.2: "It is refused while any order referencing the configuration
    has a build status of `SUBMITTED`, `ALLOCATED`, or `IN_PRODUCTION` — again
    `ERR_CONFIGURATION_IN_USE` — and when it succeeds it resets
    `compatibility_ok` to false, forcing the configuration through validation
    again before reuse."

    Design: Corner/endpoints/unlock_configuration_in_use_rejected
    """
    account = create_account(company_name="EE3")
    program = create_program(account["id"], name="P3")
    chassis = create_chassis(model_code="EEL3")
    component = create_component(sku="EEC3")
    add_allowed_rule(chassis["id"], component["id"])
    template = create_template(program["id"], chassis["id"],
                               [{"component_id": component["id"], "revision": "A01", "qty": 1}],
                               name="T3")
    api.publish_template(template["id"], MANAGER)
    resp = api.lock_program(program["id"], MANAGER)
    assert resp.status_code == 200
    config = create_validated_configuration(
        account, chassis["id"], [{"component_id": component["id"], "qty": 1}],
        template_id=template["id"],
    )
    resp = api.lock_configuration(config["id"], MANAGER)
    locked = validate_success(resp, 200)
    order, lines = create_order_with_lines(
        account,
        [{"configuration_id": config["id"], "qty": 1, "ship_to_mode": "SINGLE_ADDRESS"}],
        po_number="PO-EE3",
    )
    submit_order(account, order, locked["version"])
    resp = api.unlock_configuration(config["id"], MANAGER)
    validate_error(resp, ApiErrorId.ERR_CONFIGURATION_IN_USE.value, 409)
    after = get_success_data(api.get_configuration(config["id"], MANAGER))
    assert after["status"] == "LOCKED"
