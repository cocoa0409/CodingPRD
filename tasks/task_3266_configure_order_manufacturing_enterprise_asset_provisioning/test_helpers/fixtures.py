"""Composite setup helpers.

Every helper builds its preconditions from scratch using only PRD-declared
endpoints — the test server is restarted before every test, so each test
starts against an empty database. Helpers use get_success_data() so setup
failures surface as clear "Setup failed" errors.
"""
import itertools
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .factories import (
    create_account_payload,
    create_program_payload,
    create_chassis_model_payload,
    create_component_payload,
    create_compatibility_rule_payload,
    create_template_payload,
    create_configuration_payload,
    create_order_payload,
    add_order_line_payload,
    create_wave_payload,
)
from .test_users import (
    TEST_USERS,
    make_customer_user_headers,
)

ADMIN = TEST_USERS["platform_admin_headers"]
MANAGER = TEST_USERS["account_manager_headers"]
OPS = TEST_USERS["factory_ops_headers"]

_counter = itertools.count(1)


def _u(prefix):
    return f"{prefix}-{next(_counter)}"


def _fail(step, resp):
    raise AssertionError(f"Setup failed at {step}: {resp.status_code} {resp.text}")


# ---------------------------------------------------------------------------
# Tier 1: catalog building blocks
# ---------------------------------------------------------------------------

def create_account(company_name=None, account_tier="STANDARD", credit_limit_cents=10_000_000):
    """Create a customer account. Returns the account dict."""
    resp = api_client.create_account(
        create_account_payload(
            company_name=company_name or _u("Co"),
            account_tier=account_tier,
            credit_limit_cents=credit_limit_cents,
        ),
        ADMIN,
    )
    if resp.status_code != 201:
        _fail("create_account", resp)
    return get_success_data(resp)


def create_chassis(model_code=None, category="LAPTOP", base_price_cents=100_000,
                   build_duration_hours=24):
    """Register a chassis model. Returns the chassis dict."""
    resp = api_client.create_chassis_model(
        create_chassis_model_payload(
            model_code=model_code or _u("M"),
            category=category,
            base_price_cents=base_price_cents,
            build_duration_hours=build_duration_hours,
        ),
        ADMIN,
    )
    if resp.status_code != 201:
        _fail("create_chassis", resp)
    return get_success_data(resp)


def create_component(sku=None, kind="CPU", price_cents=20_000, lead_time_days=3,
                     stock_on_hand=10, revision="A01"):
    """Register a component. Returns the component dict."""
    resp = api_client.create_component(
        create_component_payload(
            sku=sku or _u("SKU"),
            kind=kind,
            price_cents=price_cents,
            lead_time_days=lead_time_days,
            stock_on_hand=stock_on_hand,
            revision=revision,
        ),
        ADMIN,
    )
    if resp.status_code != 201:
        _fail("create_component", resp)
    return get_success_data(resp)


def add_allowed_rule(chassis_id, component_id):
    """ALLOWED membership rule for (chassis, component)."""
    resp = api_client.create_compatibility_rule(
        create_compatibility_rule_payload(chassis_id, component_id, "ALLOWED"), ADMIN,
    )
    if resp.status_code != 201:
        _fail("add_allowed_rule", resp)
    return get_success_data(resp)


def create_program(account_id, name=None, asset_tag_prefix="FE", custom_image_ref="img-std"):
    resp = api_client.create_program(
        account_id,
        create_program_payload(
            name=name or _u("P"),
            asset_tag_prefix=asset_tag_prefix,
            custom_image_ref=custom_image_ref,
        ),
        MANAGER,
    )
    if resp.status_code != 201:
        _fail("create_program", resp)
    return get_success_data(resp)


def create_template(program_id, chassis_id, pinned_components, name=None):
    resp = api_client.create_template(
        program_id,
        create_template_payload(chassis_id, pinned_components, name=name or _u("T")),
        MANAGER,
    )
    if resp.status_code != 201:
        _fail("create_template", resp)
    return get_success_data(resp)


# ---------------------------------------------------------------------------
# Tier 2: configuration helpers
# ---------------------------------------------------------------------------

def create_configuration(account, chassis_id, component_selections, template_id=None,
                         supersedes_configuration_id=None):
    """Create a configuration as the owning customer. Returns the config dict."""
    payload = create_configuration_payload(
        account["id"], chassis_id, component_selections,
    )
    if template_id is not None:
        payload["template_id"] = template_id
    if supersedes_configuration_id is not None:
        payload["supersedes_configuration_id"] = supersedes_configuration_id
    resp = api_client.create_configuration(payload, make_customer_user_headers(account["id"]))
    if resp.status_code != 201:
        _fail("create_configuration", resp)
    return get_success_data(resp)


def create_validated_configuration(account, chassis_id, component_selections, **kwargs):
    """Create + validate. Returns the VALIDATED configuration dict."""
    config = create_configuration(account, chassis_id, component_selections, **kwargs)
    resp = api_client.validate_configuration(config["id"], make_customer_user_headers(account["id"]))
    if resp.status_code != 200:
        _fail("validate_configuration", resp)
    return get_success_data(resp)


def setup_validated_config(company=None, tier="STANDARD", credit=10_000_000,
                           chassis_category="LAPTOP", base_price_cents=100_000,
                           build_duration_hours=24, component_price_cents=20_000,
                           lead_time_days=3, stock_on_hand=10, component_kind="CPU",
                           config_qty=1, revision="A01"):
    """Account + chassis + one component + ALLOWED rule + VALIDATED config.
    Returns dict with account, chassis, component, config."""
    account = create_account(company_name=company or _u("Co"), account_tier=tier,
                             credit_limit_cents=credit)
    chassis = create_chassis(category=chassis_category, base_price_cents=base_price_cents,
                             build_duration_hours=build_duration_hours)
    component = create_component(kind=component_kind, price_cents=component_price_cents,
                                 lead_time_days=lead_time_days, stock_on_hand=stock_on_hand,
                                 revision=revision)
    add_allowed_rule(chassis["id"], component["id"])
    config = create_validated_configuration(
        account, chassis["id"], [{"component_id": component["id"], "qty": config_qty}],
    )
    return {"account": account, "chassis": chassis, "component": component, "config": config}


# ---------------------------------------------------------------------------
# Tier 3: order lifecycle
# ---------------------------------------------------------------------------

def create_order_with_lines(account, lines, po_number=None):
    """Create a draft order and add lines.
    lines: list of dicts {configuration_id, qty, ship_to_mode}.
    Returns (order, [line, ...])."""
    resp = api_client.create_order(
        create_order_payload(account["id"], po_number=po_number or _u("PO")),
        make_customer_user_headers(account["id"]),
    )
    if resp.status_code != 201:
        _fail("create_order", resp)
    order = get_success_data(resp)
    created = []
    for line in lines:
        resp = api_client.add_order_line(
            order["id"], add_order_line_payload(**line),
            make_customer_user_headers(account["id"]),
        )
        if resp.status_code != 201:
            _fail("add_order_line", resp)
        created.append(get_success_data(resp))
    return order, created


def submit_order(account, order, expected_configuration_version):
    """Submit an order. Returns the submitted order dict."""
    resp = api_client.submit_order(
        order["id"],
        {"expected_configuration_version": expected_configuration_version},
        make_customer_user_headers(account["id"]),
    )
    if resp.status_code != 200:
        _fail("submit_order", resp)
    return get_success_data(resp)


def get_order_build_jobs(order_id):
    resp = api_client.list_order_build_jobs(order_id, OPS)
    if resp.status_code != 200:
        _fail("list_order_build_jobs", resp)
    return get_success_data(resp)


def setup_submitted_order(qty=1, credit=10_000_000, tier="STANDARD", stock_on_hand=10,
                          base_price_cents=100_000, component_price_cents=20_000,
                          build_duration_hours=24, lead_time_days=3,
                          ship_to_mode="SINGLE_ADDRESS"):
    """Full chain to a SUBMITTED order with one line.
    Returns dict with account, chassis, component, config, order, line, jobs."""
    env = setup_validated_config(
        tier=tier, credit=credit, stock_on_hand=stock_on_hand,
        base_price_cents=base_price_cents, component_price_cents=component_price_cents,
        build_duration_hours=build_duration_hours, lead_time_days=lead_time_days,
    )
    order, lines = create_order_with_lines(
        env["account"],
        [{"configuration_id": env["config"]["id"], "qty": qty, "ship_to_mode": ship_to_mode}],
    )
    order = submit_order(env["account"], order, env["config"]["version"])
    jobs = get_order_build_jobs(order["id"])
    env.update({"order": order, "line": lines[0], "jobs": jobs})
    return env


def allocate_job(job_id):
    resp = api_client.allocate_build_job(job_id, OPS)
    if resp.status_code != 200:
        _fail("allocate_build_job", resp)
    return get_success_data(resp)


def start_job(job_id):
    resp = api_client.start_build_job(job_id, OPS)
    if resp.status_code != 200:
        _fail("start_build_job", resp)
    return get_success_data(resp)


def complete_job(job_id):
    resp = api_client.complete_build_job(job_id, OPS)
    if resp.status_code != 200:
        _fail("complete_build_job", resp)
    return get_success_data(resp)


def setup_built_order(qty=1, **kwargs):
    """SUBMITTED order, job allocated, started, completed -> order BUILT.
    Returns env dict (see setup_submitted_order) with jobs refreshed."""
    env = setup_submitted_order(qty=qty, **kwargs)
    job = env["jobs"][0]
    allocate_job(job["id"])
    start_job(job["id"])
    complete_job(job["id"])
    env["jobs"] = get_order_build_jobs(env["order"]["id"])
    return env


# ---------------------------------------------------------------------------
# Tier 4: shortage / substitution fixtures
# ---------------------------------------------------------------------------

def setup_shortage_blocked_order(line_qty=1, shorted_stock=0, spare_stock=50,
                                 shorted_price=5_000, spare_price=7_000,
                                 credit=10_000_000):
    """Order whose job went SHORTAGE_BLOCKED during allocation, with an
    auto-created PENDING substitution request and the order ON_HOLD.
    Returns dict with account, chassis, shorted component, spare component,
    config, order, line, job, substitution request."""
    account = create_account(credit_limit_cents=credit)
    chassis = create_chassis()
    shorted = create_component(sku=_u("SHORT"), kind="STORAGE", price_cents=shorted_price,
                               stock_on_hand=shorted_stock)
    spare = create_component(sku=_u("SPARE"), kind="STORAGE", price_cents=spare_price,
                             stock_on_hand=spare_stock)
    add_allowed_rule(chassis["id"], shorted["id"])
    add_allowed_rule(chassis["id"], spare["id"])
    config = create_validated_configuration(
        account, chassis["id"], [{"component_id": shorted["id"], "qty": 1}],
    )
    order, lines = create_order_with_lines(
        account,
        [{"configuration_id": config["id"], "qty": line_qty, "ship_to_mode": "SINGLE_ADDRESS"}],
    )
    order = submit_order(account, order, config["version"])
    jobs = get_order_build_jobs(order["id"])
    job = jobs[0]
    resp = api_client.allocate_build_job(job["id"], OPS)
    if resp.status_code != 200:
        _fail("allocate_build_job (shortage)", resp)
    job = get_success_data(resp)
    resp = api_client.list_job_substitution_requests(job["id"], OPS)
    if resp.status_code != 200:
        _fail("list_job_substitution_requests", resp)
    srs = get_success_data(resp)
    if len(srs) != 1:
        raise AssertionError(f"Setup failed: expected 1 substitution request, got {len(srs)}")
    return {
        "account": account,
        "chassis": chassis,
        "shorted": shorted,
        "spare": spare,
        "config": config,
        "order": order,
        "line": lines[0],
        "job": job,
        "sr": srs[0],
    }


# ---------------------------------------------------------------------------
# Tier 5: delivery + recovery fixtures
# ---------------------------------------------------------------------------

def setup_delivered_asset(qty=1, ship_to="2026-09-02T00:00:00Z", **kwargs):
    """Fully delivered single-unit order. Returns env dict with asset."""
    env = setup_built_order(qty=qty, **kwargs)
    account = env["account"]
    order = env["order"]
    api_client.set_clock(ship_to, ADMIN)
    resp = api_client.create_deployment_wave(
        order["id"],
        create_wave_payload(
            ship_window_start=ship_to,
            ship_window_end="2026-09-20T00:00:00Z",
            destinations=[{"employee_ref": "HQ", "address": "1 Main St", "units": qty}],
        ),
        MANAGER,
    )
    if resp.status_code != 201:
        _fail("create_deployment_wave", resp)
    wave = get_success_data(resp)
    # Release is the AccountManager action; shipment is the FactoryOps action
    # (PRD §4 endpoint table). Call them explicitly: selecting the role by
    # bound-method identity (`fn is api_client.release_wave`) silently picks
    # the wrong role whenever the helpers module is imported under two names.
    resp = api_client.release_wave(wave["id"], MANAGER)
    if resp.status_code != 200:
        _fail("wave release", resp)
    resp = api_client.ship_wave(wave["id"], OPS)
    if resp.status_code != 200:
        _fail("wave ship", resp)
    resp = api_client.receive_wave(wave["id"], make_customer_user_headers(account["id"]))
    if resp.status_code != 200:
        _fail("receive_wave", resp)
    resp = api_client.list_line_assets(env["line"]["id"], make_customer_user_headers(account["id"]))
    if resp.status_code != 200:
        _fail("list_line_assets", resp)
    assets = get_success_data(resp)
    env.update({"wave": wave, "assets": assets})
    return env
