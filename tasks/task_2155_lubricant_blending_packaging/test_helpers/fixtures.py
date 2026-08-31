"""Composite setup helpers.

Most interesting claims need the plant to be in a state that takes five to
fifteen calls to reach: material booked in, a specification activated, a recipe
formulated and activated, a vessel registered with a declared heel, a batch
created, charged, blended, tested, retained and released. These helpers
encapsulate those preambles so tests can focus on assertions.

Every helper builds its preconditions from scratch through published endpoints
only, and uses the lenient success validator so a broken preamble reports as a
setup failure rather than as a confusing assertion failure.
"""

from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import (
    CLOCK_BASE,
    LOT_RECEIPT_INSTANTS,
    QC_TECH_ID,
    QUALITY_MANAGER_ID,
    RUN_WINDOW_END,
    RUN_WINDOW_START,
    TEST_DEFAULTS,
    WINDOW_A_END,
    WINDOW_A_START,
)
from .factories import (
    charge_payload,
    create_approval_claim_payload,
    create_blend_batch_payload,
    create_blend_recipe_payload,
    create_blend_tank_payload,
    create_component_lot_payload,
    create_customer_payload,
    create_order_line_payload,
    create_order_payload,
    create_package_configuration_payload,
    create_packaging_line_payload,
    create_packaging_run_payload,
    create_product_spec_payload,
    create_spec_change_request_payload,
    create_takeback_collection_payload,
    standard_components,
)
from .test_users import TEST_USERS, make_customer_headers, make_qc_technician_headers, make_quality_manager_headers

ADMIN = TEST_USERS["platform_admin_headers"]
PM = TEST_USERS["product_manager_headers"]
OPERATOR = TEST_USERS["blend_operator_headers"]
QC = TEST_USERS["qc_technician_headers"]
QM = TEST_USERS["quality_manager_headers"]
COMPLIANCE = TEST_USERS["compliance_officer_headers"]
SALES = TEST_USERS["sales_rep_headers"]


# The four canonical material lots. The two base-oil lots deliberately differ in
# both age and landed cost, which is what makes the two costing figures diverge.
STANDARD_LOT_SPECS = [
    (
        "lot_b1",
        {
            "component_type": "BASE_OIL",
            "component_code": "GRP2-150N",
            "received_kg": 400.0,
            "unit_cost_cents_per_kg": 210,
            "kv100_cst": 5.200,
            "density_kg_per_l": 0.855,
            "additive_family": "NONE",
            "coa_viscosity_verified": True,
        },
    ),
    (
        "lot_b2",
        {
            "component_type": "BASE_OIL",
            "component_code": "GRP2-150N",
            "received_kg": 1500.0,
            "unit_cost_cents_per_kg": 250,
            "kv100_cst": 5.200,
            "density_kg_per_l": 0.855,
            "additive_family": "NONE",
            "coa_viscosity_verified": True,
        },
    ),
    (
        "lot_v1",
        {
            "component_type": "VI_IMPROVER",
            "component_code": "OCP-VII",
            "received_kg": 300.0,
            "unit_cost_cents_per_kg": 940,
            "kv100_cst": 850.000,
            "density_kg_per_l": 0.900,
            "additive_family": "NONE",
            "coa_viscosity_verified": True,
        },
    ),
    (
        "lot_a1",
        {
            "component_type": "ADDITIVE_PACKAGE",
            "component_code": "ADD-SN-PLUS",
            "received_kg": 400.0,
            "unit_cost_cents_per_kg": 620,
            "kv100_cst": 105.000,
            "density_kg_per_l": 0.960,
            "additive_family": "ZDDP_PCMO",
            "coa_viscosity_verified": True,
        },
    ),
]


# ==========================================================================
# Tier 0 — primitives
# ==========================================================================
def set_clock(to_iso8601=CLOCK_BASE) -> dict:
    """Point the logical clock at a known instant."""
    return get_success_data(api_client.set_clock(to_iso8601, ADMIN))


def create_customer(**overrides) -> dict:
    return get_success_data(
        api_client.create_customer(create_customer_payload(**overrides), ADMIN)
    )


def create_component_lot(**overrides) -> dict:
    return get_success_data(
        api_client.create_component_lot(create_component_lot_payload(**overrides), ADMIN)
    )


def stock_standard_lots(restore_to=CLOCK_BASE) -> dict:
    """Book in the four canonical material lots, oldest first.

    The bookings are staggered across the logical clock so that the lots
    genuinely differ in age. PRD 3.3 orders draw candidates by `created_at`
    ascending and only falls back to `received_kg` descending on a tie, so the
    small cheap base-oil lot must be booked strictly earlier than the large
    expensive one for a draw to walk both layers. The clock is handed back at
    `restore_to` so everything built on top of the material is stamped there.
    """
    lots = {}
    for (key, payload), instant in zip(STANDARD_LOT_SPECS, LOT_RECEIPT_INSTANTS):
        set_clock(instant)
        lots[key] = create_component_lot(**payload)
    set_clock(restore_to)
    return lots


def create_spec(**overrides) -> dict:
    return get_success_data(
        api_client.create_product_spec(create_product_spec_payload(**overrides), PM)
    )


def create_active_spec(**overrides) -> dict:
    spec = create_spec(**overrides)
    return get_success_data(api_client.activate_product_spec(spec["id"], PM))


def create_recipe(product_spec_id, components=None, **overrides) -> dict:
    return get_success_data(
        api_client.create_blend_recipe(
            create_blend_recipe_payload(product_spec_id, components, **overrides), PM
        )
    )


def create_active_recipe(product_spec_id, components=None, **overrides) -> dict:
    recipe = create_recipe(product_spec_id, components, **overrides)
    return get_success_data(api_client.activate_blend_recipe(recipe["id"], PM))


def create_tank(**overrides) -> dict:
    return get_success_data(
        api_client.create_blend_tank(create_blend_tank_payload(**overrides), ADMIN)
    )


def create_batch(blend_recipe_id, **overrides) -> dict:
    return get_success_data(
        api_client.create_blend_batch(
            create_blend_batch_payload(blend_recipe_id, **overrides), OPERATOR
        )
    )


def create_packaging_line(**overrides) -> dict:
    return get_success_data(
        api_client.create_packaging_line(create_packaging_line_payload(**overrides), ADMIN)
    )


def create_config(product_spec_id, **overrides) -> dict:
    return get_success_data(
        api_client.create_package_configuration(
            create_package_configuration_payload(product_spec_id, **overrides), PM
        )
    )


def create_active_config(product_spec_id, **overrides) -> dict:
    config = create_config(product_spec_id, **overrides)
    return get_success_data(api_client.activate_package_configuration(config["id"], PM))


def create_active_claim(product_spec_id, licence_number="API-1234", **overrides) -> dict:
    """Open a claim, submit it and record an approval, leaving it ACTIVE.

    The specification must already carry an ACTIVE recipe pinned to its current
    revision, otherwise the submission is refused.
    """
    claim = get_success_data(
        api_client.create_approval_claim(
            create_approval_claim_payload(product_spec_id, **overrides), COMPLIANCE
        )
    )
    get_success_data(api_client.submit_approval_claim(claim["id"], COMPLIANCE))
    return get_success_data(
        api_client.decide_approval_claim(
            claim["id"], {"decision": "APPROVE", "licence_number": licence_number}, COMPLIANCE
        )
    )


def read_batch(batch_id) -> dict:
    return get_success_data(api_client.get_blend_batch(batch_id, OPERATOR))


def read_tank(tank_id) -> dict:
    return get_success_data(api_client.get_blend_tank(tank_id, OPERATOR))


def read_lot(lot_id) -> dict:
    return get_success_data(api_client.get_component_lot(lot_id, ADMIN))


def read_spec(spec_id) -> dict:
    return get_success_data(api_client.get_product_spec(spec_id, PM))


def read_recipe(recipe_id) -> dict:
    return get_success_data(api_client.get_blend_recipe(recipe_id, PM))


def read_claim(claim_id) -> dict:
    return get_success_data(api_client.get_approval_claim(claim_id, COMPLIANCE))


def read_config(config_id) -> dict:
    return get_success_data(api_client.get_package_configuration(config_id, PM))


def read_line(line_id) -> dict:
    return get_success_data(api_client.get_packaging_line(line_id, OPERATOR))


def read_run(run_id) -> dict:
    return get_success_data(api_client.get_packaging_run(run_id, OPERATOR))


def read_order(order_id) -> dict:
    return get_success_data(api_client.get_order(order_id, SALES))


def read_customer(customer_id) -> dict:
    return get_success_data(api_client.get_customer(customer_id, SALES))


def read_collection(collection_id) -> dict:
    return get_success_data(api_client.get_takeback_collection(collection_id, SALES))


def read_change_request(request_id) -> dict:
    return get_success_data(api_client.get_spec_change_request(request_id, PM))


def read_retain(retain_id, batch_id) -> dict:
    rows, _ = _paginated(api_client.list_retain_samples(batch_id, QC))
    for row in rows:
        if row["id"] == retain_id:
            return row
    raise AssertionError(f"Setup failed: retain {retain_id} not listed on batch {batch_id}")


def _paginated(response):
    body = response.json()
    if not (200 <= response.status_code < 300):
        raise AssertionError(f"Setup step failed with HTTP {response.status_code}: {response.text}")
    return body["data"], body["meta"]


def list_batch_draws(batch_id) -> list:
    rows, _ = _paginated(api_client.list_batch_component_draws(batch_id, OPERATOR, {"limit": 100}))
    return rows


def list_lot_draws(lot_id) -> list:
    rows, _ = _paginated(api_client.list_component_lot_draws(lot_id, ADMIN, {"limit": 100}))
    return rows


def list_order_lines(order_id) -> list:
    rows, _ = _paginated(api_client.list_order_lines(order_id, SALES, {"limit": 100}))
    return rows


def find_order_line(order_id, line_id) -> dict:
    for row in list_order_lines(order_id):
        if row["id"] == line_id:
            return row
    raise AssertionError(f"Setup failed: line {line_id} not listed on order {order_id}")


# ==========================================================================
# Tier 1 — the formulation world: material, specification and recipe
# ==========================================================================
def setup_active_formulation(
    clock=CLOCK_BASE,
    with_lots=True,
    spec_overrides=None,
    components=None,
    activate_recipe=True,
):
    """Stock the four canonical lots, activate a specification and formulate a
    recipe against it.

    Returns {"lots", "spec", "recipe"}. With activate_recipe False the recipe is
    left in DRAFT so activation-gate tests can drive it themselves.
    """
    if clock is not None:
        set_clock(clock)
    restore_to = clock if clock is not None else CLOCK_BASE
    world = {"lots": stock_standard_lots(restore_to) if with_lots else {}}
    world["spec"] = create_active_spec(**(spec_overrides or {}))
    if activate_recipe:
        world["recipe"] = create_active_recipe(world["spec"]["id"], components)
    else:
        world["recipe"] = create_recipe(world["spec"]["id"], components)
    return world


# ==========================================================================
# Tier 2 — the blend world: a vessel and a planned batch on top of Tier 1
# ==========================================================================
def setup_planned_batch(
    clock=CLOCK_BASE,
    spec_overrides=None,
    components=None,
    tank_overrides=None,
    batch_overrides=None,
    with_lots=True,
    activate_recipe=True,
):
    """Tier 1 plus a registered vessel and a batch sitting in PLANNED / PENDING.

    Returns {"lots", "spec", "recipe", "tank", "batch"}. With activate_recipe
    False the recipe is left in DRAFT, which is legal to create a batch against
    and lets charge-gate tests drive the recipe-activity rung themselves.
    """
    world = setup_active_formulation(
        clock=clock,
        with_lots=with_lots,
        spec_overrides=spec_overrides,
        components=components,
        activate_recipe=activate_recipe,
    )
    world["tank"] = create_tank(**(tank_overrides or {}))
    world["batch"] = create_batch(world["recipe"]["id"], **(batch_overrides or {}))
    return world


def charge(world, tank_id=None, **charge_overrides):
    """Charge the world's batch into the world's vessel and refresh both rows."""
    payload = charge_payload(tank_id or world["tank"]["id"], **charge_overrides)
    world["batch"] = get_success_data(
        api_client.charge_blend_batch(world["batch"]["id"], payload, OPERATOR)
    )
    world["tank"] = read_tank(world["tank"]["id"])
    return world


def setup_charging_batch(charge_overrides=None, **kwargs):
    """A batch in CHARGING with its reserved draws in place."""
    world = setup_planned_batch(**kwargs)
    return charge(world, **(charge_overrides or {}))


def complete_blend(world):
    world["batch"] = get_success_data(api_client.complete_blend(world["batch"]["id"], OPERATOR))
    return world


def setup_blended_batch(charge_overrides=None, **kwargs):
    """A batch in production_status BLENDED with qc_status still PENDING."""
    world = setup_charging_batch(charge_overrides=charge_overrides, **kwargs)
    return complete_blend(world)


def record_qc_results(world, kv100=7.610, tbn=8.9, technician_user_id=QC_TECH_ID):
    """Record the two required laboratory results, driving the quality dimension
    PENDING -> SAMPLED -> PASSED when both pass."""
    headers = make_qc_technician_headers(technician_user_id)
    results = []
    if kv100 is not None:
        results.append(
            get_success_data(
                api_client.create_qc_result(
                    world["batch"]["id"], {"test_type": "KV100", "measured_value": kv100}, headers
                )
            )
        )
    if tbn is not None:
        results.append(
            get_success_data(
                api_client.create_qc_result(
                    world["batch"]["id"], {"test_type": "TBN", "measured_value": tbn}, headers
                )
            )
        )
    world["qc_results"] = results
    world["batch"] = read_batch(world["batch"]["id"])
    return world


def add_retains(world, count=2, technician_user_id=QC_TECH_ID, prefix=None):
    """Book `count` retain jars against the world's batch."""
    headers = make_qc_technician_headers(technician_user_id)
    code_prefix = prefix or f"R-{world['batch']['batch_code']}"
    retains = world.setdefault("retains", [])
    for index in range(count):
        suffix = chr(ord("A") + len(retains))
        retains.append(
            get_success_data(
                api_client.create_retain_sample(
                    world["batch"]["id"],
                    {"retain_code": f"{code_prefix}-{suffix}", "volume_ml": 250.0},
                    headers,
                )
            )
        )
    world["batch"] = read_batch(world["batch"]["id"])
    return world


def release(world, manager_user_id=QUALITY_MANAGER_ID):
    world["batch"] = get_success_data(
        api_client.release_blend_batch(
            world["batch"]["id"], make_quality_manager_headers(manager_user_id)
        )
    )
    world["tank"] = read_tank(world["tank"]["id"])
    return world


def setup_qc_passed_batch(
    kv100=7.610, tbn=8.9, technician_user_id=QC_TECH_ID, retains=2, charge_overrides=None, **kwargs
):
    """A BLENDED batch whose quality dimension is PASSED and which holds the
    required retain jars — one call short of release."""
    world = setup_blended_batch(charge_overrides=charge_overrides, **kwargs)
    record_qc_results(world, kv100=kv100, tbn=tbn, technician_user_id=technician_user_id)
    if retains:
        add_retains(world, count=retains, technician_user_id=technician_user_id)
    return world


def setup_released_batch(manager_user_id=QUALITY_MANAGER_ID, **kwargs):
    """A batch in production_status RELEASED with the vessel handed back and its
    heel rewritten from the batch."""
    world = setup_qc_passed_batch(**kwargs)
    return release(world, manager_user_id=manager_user_id)


# ==========================================================================
# Tier 3 — packaging: a released batch, an active configuration and a line
# ==========================================================================
def setup_released_batch_with_line(
    config_overrides=None, line_overrides=None, **kwargs
):
    """A released batch plus an ACTIVE package configuration carrying no printed
    claim and an AVAILABLE filling line.

    Returns the blend world plus {"config", "line"}.
    """
    world = setup_released_batch(**kwargs)
    world["config"] = create_active_config(world["spec"]["id"], **(config_overrides or {}))
    world["line"] = create_packaging_line(**(line_overrides or {}))
    return world


def schedule_run(world, config_id=None, line_id=None, **run_overrides):
    payload = create_packaging_run_payload(
        world["batch"]["id"],
        config_id or world["config"]["id"],
        line_id or world["line"]["id"],
        **run_overrides,
    )
    run = get_success_data(api_client.create_packaging_run(payload, OPERATOR))
    world.setdefault("runs", []).append(run)
    world["line"] = read_line(world["line"]["id"])
    return run


def setup_scheduled_run(run_overrides=None, **kwargs):
    """A released batch packed onto a line by one SCHEDULED run."""
    world = setup_released_batch_with_line(**kwargs)
    world["run"] = schedule_run(world, **(run_overrides or {}))
    return world


# ==========================================================================
# Tier 4 — the commercial desk: accounts, configurations, orders and credit
# ==========================================================================
def setup_commercial_world(
    clock=CLOCK_BASE,
    customer_overrides=None,
    spec_overrides=None,
    with_drum=True,
):
    """An account, an ACTIVE specification and the pack configurations the
    pricing tests quote against.

    The pail configuration is private label and owned by the account; the drum
    configuration is house brand. Both carry an empty printed claim list.
    Returns {"customer", "spec", "cfg_pail", "cfg_drum"}.
    """
    if clock is not None:
        set_clock(clock)
    customer = create_customer(
        **{
            "name": "Bravo Distribution",
            "customer_type": "PRIVATE_LABEL",
            "contract_tier": "TIER_B",
            "credit_limit_cents": TEST_DEFAULTS["CREDIT_LIMIT_CENTS"],
            "takeback_agreement_status": "ACTIVE",
            **(customer_overrides or {}),
        }
    )
    spec = create_active_spec(**(spec_overrides or {}))
    world = {"customer": customer, "spec": spec}
    world["cfg_pail"] = create_active_config(
        spec["id"],
        package_type="PAIL_20L",
        label_brand="Bravo Blue",
        fill_volume_l=20.0,
        private_label=True,
        customer_id=customer["id"],
        claim_codes=[],
    )
    if with_drum:
        world["cfg_drum"] = create_active_config(
            spec["id"],
            package_type="DRUM_205L",
            label_brand="House Drum",
            fill_volume_l=205.0,
            private_label=False,
            claim_codes=[],
        )
    return world


def open_order(customer_id, **overrides) -> dict:
    return get_success_data(
        api_client.create_order(create_order_payload(customer_id, **overrides), SALES)
    )


def add_order_line(order_id, package_configuration_id, quantity_units) -> dict:
    return get_success_data(
        api_client.create_order_line(
            order_id,
            create_order_line_payload(package_configuration_id, quantity_units),
            SALES,
        )
    )


def confirm_order(order_id) -> dict:
    return get_success_data(api_client.confirm_order(order_id, SALES))


def setup_draft_order_with_lines(
    lines=None, order_overrides=None, world=None, **kwargs
):
    """A DRAFT order carrying the requested lines.

    `lines` is a list of (config key, quantity_units) pairs against the keys of
    setup_commercial_world; it defaults to one 37-pail line.
    Returns the commercial world plus {"order", "lines"}.
    """
    world = world or setup_commercial_world(**kwargs)
    world["order"] = open_order(world["customer"]["id"], **(order_overrides or {}))
    world["lines"] = []
    for config_key, quantity in (lines or [("cfg_pail", 37)]):
        world["lines"].append(
            add_order_line(world["order"]["id"], world[config_key]["id"], quantity)
        )
    world["order"] = read_order(world["order"]["id"])
    return world


def setup_confirmed_order(**kwargs):
    """A CONFIRMED order with the full pricing waterfall applied."""
    world = setup_draft_order_with_lines(**kwargs)
    world["order"] = confirm_order(world["order"]["id"])
    return world


def grant_takeback_credit(
    customer_id, collected_volume_l=60000.0, water_pct=6.5, sediment_pct=3.0, assay=True
):
    """Run one collection through to CREDITED so the account carries a balance.

    With assay False the collection is credited straight out of COLLECTED, which
    is what selects the flat variant regardless of the account's tier.
    """
    collection = get_success_data(
        api_client.create_takeback_collection(
            create_takeback_collection_payload(
                customer_id, scheduled_volume_l=collected_volume_l
            ),
            SALES,
        )
    )
    get_success_data(
        api_client.collect_takeback(
            collection["id"], {"collected_volume_l": collected_volume_l}, SALES
        )
    )
    if assay:
        get_success_data(
            api_client.assay_takeback(
                collection["id"],
                {"water_pct": water_pct, "sediment_pct": sediment_pct},
                QC,
            )
        )
    return get_success_data(api_client.credit_takeback(collection["id"], SALES))


def setup_order_with_credit_balance(
    lines=None,
    collected_volume_l=60000.0,
    water_pct=6.5,
    sediment_pct=3.0,
    assay=True,
    **kwargs
):
    """An account holding a take-back credit balance, with a CONFIRMED
    take-back-linked order ready for a credit draw.

    Returns the commercial world plus {"collection", "order", "lines"}.
    """
    world = setup_commercial_world(**kwargs)
    world["collection"] = grant_takeback_credit(
        world["customer"]["id"],
        collected_volume_l=collected_volume_l,
        water_pct=water_pct,
        sediment_pct=sediment_pct,
        assay=assay,
    )
    world = setup_draft_order_with_lines(
        lines=lines or [("cfg_pail", 37), ("cfg_drum", 6)],
        order_overrides={"takeback_linked": True},
        world=world,
    )
    world["order"] = confirm_order(world["order"]["id"])
    world["customer"] = read_customer(world["customer"]["id"])
    return world


def apply_credit(world, expected_customer_version=None, order_id=None):
    """Draw take-back credit against the world's order at the account's current
    version, refreshing both rows."""
    version = (
        expected_customer_version
        if expected_customer_version is not None
        else read_customer(world["customer"]["id"])["version"]
    )
    target = order_id or world["order"]["id"]
    result = get_success_data(
        api_client.apply_takeback_credit(
            target, {"expected_customer_version": version}, SALES
        )
    )
    if target == world["order"]["id"]:
        world["order"] = result
    world["customer"] = read_customer(world["customer"]["id"])
    return result


# ==========================================================================
# Tier 5 — governed specification change and approval claims
# ==========================================================================
def open_change_request(spec_id, **overrides) -> dict:
    """Open a change request at the specification's current version."""
    version = read_spec(spec_id)["version"]
    return get_success_data(
        api_client.create_spec_change_request(
            spec_id, create_spec_change_request_payload(version, **overrides), PM
        )
    )


def setup_change_request_in_review(spec_id, **overrides):
    """A submitted change request resting at IN_REVIEW with both branches open."""
    request = open_change_request(spec_id, **overrides)
    return get_success_data(api_client.submit_spec_change_request(request["id"], PM))


def clear_both_branches(request_id):
    """Record a CLEAR verdict on both branches, which joins the request to
    CLEARED."""
    get_success_data(
        api_client.viscosity_review(request_id, {"decision": "CLEAR"}, QM)
    )
    return get_success_data(
        api_client.approval_review(request_id, {"decision": "CLEAR"}, COMPLIANCE)
    )


def setup_cleared_change_request(spec_id, **overrides):
    """A change request sitting at CLEARED, ready to be made effective."""
    request = setup_change_request_in_review(spec_id, **overrides)
    clear_both_branches(request["id"])
    return read_change_request(request["id"])


def make_effective(request_id) -> dict:
    return get_success_data(api_client.make_spec_change_effective(request_id, PM))


def setup_spec_advanced_to_revision_two(clock=CLOCK_BASE, components=None, **kwargs):
    """An ACTIVE specification carried through a governed change to revision 2.

    Returns {"spec", "recipe", "request"} where the recipe is the one retired by
    the revision advance.
    """
    world = setup_active_formulation(clock=clock, with_lots=False, components=components, **kwargs)
    request = setup_cleared_change_request(world["spec"]["id"])
    world["request"] = make_effective(request["id"])
    world["spec"] = read_spec(world["spec"]["id"])
    world["recipe"] = read_recipe(world["recipe"]["id"])
    return world


def setup_claim_blocked_configuration(clock=CLOCK_BASE, claim_code="API SP"):
    """An ACTIVE claim whose suspension has blocked the configuration printing
    its code.

    Returns {"spec", "recipe", "claim", "config"}.
    """
    world = setup_active_formulation(clock=clock, with_lots=False)
    world["claim"] = create_active_claim(world["spec"]["id"], claim_code=claim_code)
    world["config"] = create_active_config(
        world["spec"]["id"],
        package_type="PAIL_20L",
        label_brand="House Pail",
        fill_volume_l=20.0,
        private_label=False,
        claim_codes=[claim_code],
    )
    get_success_data(
        api_client.approval_claim_lifecycle(
            world["claim"]["id"],
            {"action": "SUSPEND", "reason": "OEM audit finding"},
            COMPLIANCE,
        )
    )
    world["claim"] = read_claim(world["claim"]["id"])
    world["config"] = read_config(world["config"]["id"])
    return world
