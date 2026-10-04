"""Composite setup helpers for the accelerator allocation test suite.

Each helper walks the multi-step PRD-declared sequences needed to bring the
system into a testable state, using ``get_success_data`` so setup failures
surface as clear "Setup failed" errors. Ownership-gated calls use
``make_partner_ops_headers(partner_id)`` with the live entity id.
"""
import datetime

from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client as api
from .constants import STARTUP_CLOCK, TEST_DEFAULTS as D
from .test_users import TEST_USERS, make_partner_ops_headers

ADMIN = TEST_USERS["platform_admin_headers"]
PLANNER = TEST_USERS["supply_planner_headers"]
PROGRAM = TEST_USERS["partner_program_manager_headers"]
SUPPORT = TEST_USERS["support_account_manager_headers"]
SUPPORT_SECOND = TEST_USERS["support_account_manager_2_headers"]
COMPLIANCE = TEST_USERS["supply_compliance_officer_headers"]
LIFECYCLE = TEST_USERS["lifecycle_program_manager_headers"]
# PRD 4: POST /accelerators/partners is authorized for PartnerOps only. The
# created account's id is server-minted, so the shared opaque fallback identity
# is correct here (there is no prior entity to own).
PARTNER_OPS = TEST_USERS["partner_ops_headers"]


# --------------------------------------------------------------------------
# Clock / logical time
# --------------------------------------------------------------------------

def set_clock(instant: str = STARTUP_CLOCK):
    """Set the logical clock. Every fixture and test starts here."""
    return get_success_data(api.set_clock({"current_utc": instant}, ADMIN))


def startup_clock():
    return set_clock(STARTUP_CLOCK)


# --------------------------------------------------------------------------
# Tier 1: individual entity creation
# --------------------------------------------------------------------------

def create_partner(legal_name=D["PARTNER_LEGAL_NAME"], partner_type=D["PARTNER_TYPE"],
                   destination_country=D["PARTNER_DESTINATION"],
                   export_restriction_tier="LICENSE_EXCEPTION",
                   origin_epoch_index=D["PARTNER_ORIGIN_EPOCH_INDEX"]) -> dict:
    resp = api.create_partner({
        "legal_name": legal_name,
        "partner_type": partner_type,
        "destination_country": destination_country,
        "export_restriction_tier": export_restriction_tier,
        "origin_epoch_index": origin_epoch_index,
    }, PARTNER_OPS)
    return get_success_data(resp, 201)


def get_partner(partner_id: str) -> dict:
    return get_success_data(api.get_partner(partner_id, make_partner_ops_headers(partner_id)))


def create_blueprint(**overrides) -> dict:
    payload = {
        "blueprint_code": overrides.pop("blueprint_code", D["BLUEPRINT_CODE"]),
        "blueprint_type": overrides.pop("blueprint_type", D["BLUEPRINT_TYPE"]),
        "target_tdp_watts": overrides.pop("target_tdp_watts",
                                          D["BLUEPRINT_TARGET_TDP_WATTS"]),
        "required_validation_minutes": overrides.pop(
            "required_validation_minutes", D["BLUEPRINT_REQUIRED_VALIDATION_MINUTES"]),
        "evaluation_deadline_days": overrides.pop(
            "evaluation_deadline_days", D["BLUEPRINT_EVALUATION_DEADLINE_DAYS"]),
    }
    payload.update(overrides)
    return get_success_data(api.create_blueprint(payload, PLANNER), 201)


def create_certified_blueprint(**overrides) -> dict:
    blueprint = create_blueprint(**overrides)
    get_success_data(api.certify_blueprint(blueprint["id"], PLANNER))
    return blueprint


def create_product(sku_code=D["SKU_CODE"], tdp_watts=D["TDP_WATTS"],
                   supply_ceiling_units=D["SUPPLY_CEILING_UNITS"],
                   long_term_availability_through=D["LONG_TERM_AVAILABILITY_THROUGH"],
                   **overrides) -> dict:
    payload = {
        "sku_code": sku_code,
        "product_family": overrides.pop("product_family", "DATACENTER"),
        "form_factor": overrides.pop("form_factor", "PCLE"),
        "hbm_capacity_gb": overrides.pop("hbm_capacity_gb", 80),
        "tdp_watts": tdp_watts,
        "supply_ceiling_units": supply_ceiling_units,
        "long_term_availability_through": long_term_availability_through,
    }
    payload.update(overrides)
    return get_success_data(api.create_product(payload, ADMIN), 201)


def advance_product_lifecycle(product_id: str) -> dict:
    return get_success_data(api.advance_product_lifecycle(product_id, ADMIN))


def get_product(product_id: str) -> dict:
    return get_success_data(api.get_product(product_id, ADMIN))


def create_open_epoch_product(sku_code=D["SKU_CODE"], **overrides) -> dict:
    """Create a SKU and open its evaluation ring fence (GENERAL_AVAILABILITY)."""
    product = create_product(sku_code=sku_code, **overrides)
    product = advance_product_lifecycle(product["id"])
    return product


def create_supply_node(product_sku_id: str, node_code="POOL-AMER-1",
                       capacity_units=D["NODE_CAPACITY_UNITS"],
                       requested_hotness_tier="COOL",
                       node_region=D["NODE_REGION"]) -> dict:
    resp = api.create_supply_node({
        "node_code": node_code,
        "product_sku_id": product_sku_id,
        "node_region": node_region,
        "capacity_units": capacity_units,
        "requested_hotness_tier": requested_hotness_tier,
    }, PLANNER)
    return get_success_data(resp, 201)


def get_supply_node(node_id: str) -> dict:
    return get_success_data(api.get_supply_node(node_id, PLANNER))


def create_stack_license(product_sku_id: str, license_code="SL-TRAIN-1",
                         entitlement_units=D["STACK_ENTITLEMENT_UNITS"],
                         preview_stack_flag=False, release=True, **overrides) -> dict:
    payload = {
        "license_code": license_code,
        "product_sku_id": product_sku_id,
        "stack_name": overrides.pop("stack_name", "Training Suite"),
        "entitlement_units": entitlement_units,
        "min_package_version": overrides.pop("min_package_version",
                                             D["STACK_MIN_PACKAGE_VERSION"]),
        "preview_stack_flag": preview_stack_flag,
    }
    payload.update(overrides)
    stack = get_success_data(api.create_stack_license(payload, PLANNER), 201)
    if release:
        stack = get_success_data(api.release_stack_license(stack["id"], PLANNER))
    return stack


def create_deployment(product_sku_id: str, partner_id: str, stack_manifest=None,
                      destination_country_code=D["DEPLOYMENT_DESTINATION"]) -> dict:
    """Register a deployment operated by ``partner_id``.

    ``partner_id`` is a PRD-declared input field on ``HardwareDeployment`` ("the
    partner operating the deployment"); the activation qualification gate and
    the suspension/termination cascades all read it.
    """
    resp = api.create_deployment({
        "product_sku_id": product_sku_id,
        "partner_id": partner_id,
        "destination_country_code": destination_country_code,
        "stack_manifest": stack_manifest if stack_manifest is not None else [],
    }, SUPPORT)
    return get_success_data(resp, 201)


def activate_deployment(deployment_id: str) -> dict:
    return get_success_data(api.activate_deployment(deployment_id, SUPPORT))


def get_deployment(deployment_id: str) -> dict:
    return get_success_data(api.get_deployment(deployment_id, SUPPORT))


def get_membership(membership_id: str) -> dict:
    return get_success_data(api.get_membership(membership_id, PROGRAM))


def get_preview_grant(grant_id: str) -> dict:
    return get_success_data(api.get_preview_grant(grant_id, PROGRAM))


def get_confidentiality_ack(ack_id: str) -> dict:
    return get_success_data(api.get_confidentiality_ack(ack_id, COMPLIANCE))


def get_blueprint(blueprint_id: str) -> dict:
    return get_success_data(api.get_blueprint(blueprint_id, PLANNER))


def get_lifecycle_commitment(commitment_id: str) -> dict:
    return get_success_data(api.get_lifecycle_commitment(commitment_id, LIFECYCLE))


def get_evaluation_loan(loan_id: str, partner_id: str) -> dict:
    return get_success_data(api.get_evaluation_loan(
        loan_id, make_partner_ops_headers(partner_id)))


def get_allocation_hold(hold_id: str, partner_id: str) -> dict:
    return get_success_data(api.get_allocation_hold(
        hold_id, make_partner_ops_headers(partner_id)))


def get_supply_contract(contract_id: str) -> dict:
    return get_success_data(api.get_supply_contract(contract_id, LIFECYCLE))


def create_subscription(deployment_id: str, stack_license_id=None,
                        support_tier=D["SUBSCRIPTION_SUPPORT_TIER"],
                        seat_count=D["SUBSCRIPTION_SEAT_COUNT"],
                        licence_group=None, trial_flag=True) -> dict:
    if licence_group is None:
        licence_group = [{"license_id": stack_license_id}] if stack_license_id else []
    resp = api.create_subscription({
        "deployment_id": deployment_id,
        "support_tier": support_tier,
        "seat_count": seat_count,
        "licence_group": licence_group,
        "trial_flag": trial_flag,
    }, SUPPORT)
    return get_success_data(resp, 201)


def activate_subscription(subscription_id: str) -> dict:
    return get_success_data(api.activate_subscription(subscription_id, SUPPORT))


def get_subscription(subscription_id: str) -> dict:
    return get_success_data(api.get_subscription(subscription_id, SUPPORT))


def create_validation(partner_id: str, blueprint_id: str,
                      validation_minutes=D["VALIDATION_MINUTES"],
                      test_count=D["VALIDATION_TEST_COUNT"]) -> dict:
    resp = api.create_validation(partner_id, {
        "validation_minutes": validation_minutes,
        "test_count": test_count,
        "blueprint_id": blueprint_id,
    }, PROGRAM)
    return get_success_data(resp, 201)


def create_lifecycle_commitment(product_sku_id: str, embedded_partner_id: str,
                                availability_through="2029-05-29T00:00:00Z",
                                covered_units=500) -> dict:
    resp = api.create_lifecycle_commitment({
        "product_sku_id": product_sku_id,
        "embedded_partner_id": embedded_partner_id,
        "availability_through": availability_through,
        "covered_units": covered_units,
    }, LIFECYCLE)
    return get_success_data(resp, 201)


def create_supply_contract(product_sku_id: str, partner_id: str, start_month="2026-01",
                           end_month="2026-03", contracted_units=500) -> dict:
    """Record a monthly supply contract. PRD 3.9 names the ``partner_id`` that
    holds the contract alongside the SKU, months and contracted units, so the
    holder is part of the request body."""
    resp = api.create_supply_contract({
        "product_sku_id": product_sku_id,
        "partner_id": partner_id,
        "start_month": start_month,
        "end_month": end_month,
        "contracted_units": contracted_units,
    }, LIFECYCLE)
    return get_success_data(resp, 201)


def create_membership(partner_id: str, requested_tier="ELITE") -> dict:
    resp = api.create_membership({"requested_tier": requested_tier},
                                 make_partner_ops_headers(partner_id))
    return get_success_data(resp, 201)


def create_confidentiality_ack(membership_id: str, stack_license_id: str,
                               acknowledged_at="2026-09-01T00:00:00Z") -> dict:
    resp = api.create_confidentiality_ack({
        "membership_id": membership_id,
        "stack_license_id": stack_license_id,
        "acknowledged_at": acknowledged_at,
    }, COMPLIANCE)
    return get_success_data(resp, 201)


def create_preview_grant(stack_license_id: str, confidentiality_ack_id: str,
                         device_serial="EVAL-0001",
                         commitment_boundary_at="2026-09-01T00:00:00Z",
                         commitment_expires_at="2026-09-30T00:00:00Z") -> dict:
    resp = api.create_preview_grant({
        "stack_license_id": stack_license_id,
        "device_serial": device_serial,
        "commitment_boundary_at": commitment_boundary_at,
        "commitment_expires_at": commitment_expires_at,
        "confidentiality_ack_id": confidentiality_ack_id,
    }, PROGRAM)
    return get_success_data(resp, 201)


def create_export_license(product_sku_id: str, destination_country_code="FR",
                          granted_units=1000) -> dict:
    resp = api.create_export_license({
        "product_sku_id": product_sku_id,
        "destination_country_code": destination_country_code,
        "granted_units": granted_units,
    }, COMPLIANCE)
    return get_success_data(resp, 201)


def create_evaluation_loan(product_sku_id: str, blueprint_id: str,
                           partner_id: str, loan_units=50) -> dict:
    resp = api.create_evaluation_loan({
        "product_sku_id": product_sku_id,
        "blueprint_id": blueprint_id,
        "loan_units": loan_units,
    }, make_partner_ops_headers(partner_id))
    return get_success_data(resp, 201)


def create_and_activate_subscription(deployment_id: str, stack_license_id=None,
                                     **overrides) -> dict:
    subscription = create_subscription(deployment_id, stack_license_id=stack_license_id,
                                       **overrides)
    return activate_subscription(subscription["id"])


def create_allocation_hold(product_sku_id, supply_node_id, quantity_units,
                           partner_id, forecast_id=None, hold_friction_tier="COOL",
                           preempt_lower_tier=None) -> dict:
    """Create a REQUESTED hold for ``partner_id``, reading live OCC tokens first."""
    partner = get_partner(partner_id)
    product = get_product(product_sku_id)
    payload = {
        "product_sku_id": product_sku_id,
        "supply_node_id": supply_node_id,
        "quantity_units": quantity_units,
        "hold_friction_tier": hold_friction_tier,
        "expected_partner_version": partner["version"],
        "expected_allocated_units": product["allocated_units"],
    }
    if forecast_id is not None:
        payload["forecast_id"] = forecast_id
    if preempt_lower_tier is not None:
        payload["preempt_lower_tier"] = preempt_lower_tier
    resp = api.create_allocation_hold(payload, make_partner_ops_headers(partner_id))
    return get_success_data(resp, 201)


def commit_allocation_hold(hold_id, partner_id, consume_reservation=False) -> dict:
    return get_success_data(api.commit_allocation_hold(
        hold_id, make_partner_ops_headers(partner_id),
        {"consume_reservation": consume_reservation}))


def create_and_commit_allocation_hold(product_sku_id, supply_node_id, quantity_units,
                                      partner_id, forecast_id=None, **overrides) -> dict:
    hold = create_allocation_hold(product_sku_id, supply_node_id, quantity_units,
                                  partner_id, forecast_id=forecast_id, **overrides)
    commit_allocation_hold(hold["id"], partner_id)
    return hold


def create_validated_partner(legal_name=D["PARTNER_LEGAL_NAME"], blueprint_id=None,
                             qualified=True, **overrides) -> dict:
    """Partner that has filed accepted evidence and (optionally) been qualified.

    Filing a validation pack requires the ``blueprint_id`` of a reference
    architecture (PRD 3.2), so a certified blueprint is minted when the caller
    does not supply one. When ``qualified`` is false the partner is left in
    ``APPLIED`` — the state the qualification pipeline starts from — so callers
    can drive their own validation/rejection rounds.
    """
    partner = create_partner(legal_name=legal_name, **overrides)
    if not qualified:
        return partner
    if blueprint_id is None:
        blueprint_id = create_certified_blueprint()["id"]
    evidence = get_success_data(api.create_validation(
        partner["id"],
        {"validation_minutes": D["VALIDATION_MINUTES"],
         "test_count": D["VALIDATION_TEST_COUNT"],
         "blueprint_id": blueprint_id},
        PROGRAM), 201)
    get_success_data(api.accept_validation(evidence["id"], PROGRAM))
    partner = get_success_data(api.qualify_partner(partner["id"], PROGRAM))
    return partner


def create_allocation_forecast(product_sku_id, partner_id, requested_quantity_units=1000,
                               committed_quantity_units=None, acknowledge_only=False,
                               committed_only=True) -> dict:
    """Create a forecast for ``partner_id`` and drive it to ACTIVE (or
    FORECAST_SUBMITTED when ``acknowledge_only``)."""
    partner = get_partner(partner_id)
    forecast = get_success_data(api.create_demand_forecast({
        "product_sku_id": product_sku_id,
        "requested_quantity_units": requested_quantity_units,
        "expected_partner_version": partner["version"],
    }, make_partner_ops_headers(partner_id)), 201)
    forecast = get_success_data(api.acknowledge_demand_forecast(forecast["id"], PROGRAM))
    if acknowledge_only:
        return forecast
    committed = committed_quantity_units if committed_quantity_units is not None \
        else requested_quantity_units
    forecast = get_success_data(api.commit_demand_forecast(
        forecast["id"], {"committed_quantity_units": committed},
        make_partner_ops_headers(partner_id)))
    return forecast


# --------------------------------------------------------------------------
# Tier 2: hierarchy helpers
# --------------------------------------------------------------------------

def setup_partner_with_product(**overrides) -> dict:
    """Qualified partner plus a SKU, a COOL pool and a released stack."""
    blueprint = create_certified_blueprint()
    partner = create_validated_partner(blueprint_id=blueprint["id"])
    product = create_product(**overrides)
    node = create_supply_node(product["id"])
    stack = create_stack_license(product["id"])
    return {"partner": partner, "product": product, "node": node, "stack": stack,
            "blueprint": blueprint}


def setup_partner_with_committed_allocation(quantity_units=400, **overrides) -> dict:
    """Qualified partner + SKU + pool + one COMMITTED hold of ``quantity_units``."""
    ctx = setup_partner_with_product(**overrides)
    hold = create_and_commit_allocation_hold(ctx["product"]["id"], ctx["node"]["id"],
                                             quantity_units, ctx["partner"]["id"])
    return {"partner": ctx["partner"], "product": ctx["product"], "node": ctx["node"],
            "stack": ctx["stack"], "blueprint": ctx["blueprint"], "hold": hold}


def setup_deployment_stack(holder_quantity_units=400, entitlement_units=250,
                           seats=D["SUBSCRIPTION_SEAT_COUNT"], support_tier="BUSINESS",
                           activate_subscription=True) -> dict:
    """Partner + SKU with a committed hold + activated deployment + subscription."""
    ctx = setup_partner_with_committed_allocation(quantity_units=holder_quantity_units)
    stack = create_stack_license(ctx["product"]["id"], entitlement_units=entitlement_units)
    deployment = create_deployment(ctx["product"]["id"],
                                   stack_manifest=[{"license_id": stack["id"],
                                                    "entitlement_units": entitlement_units}])
    deployment = activate_deployment(deployment["id"])
    subscription = create_subscription(deployment["id"], stack_license_id=stack["id"],
                                       seat_count=seats, support_tier=support_tier)
    if activate_subscription:
        subscription = activate_subscription(subscription["id"])
    ctx.update({"stack": stack, "deployment": deployment, "subscription": subscription})
    return ctx


def setup_general_availability_product(supply_ceiling_units=10000, **overrides) -> dict:
    """SKU promoted to GENERAL_AVAILABILITY so its evaluation ring fence is set
    to 10 percent of the supply ceiling, rounded up."""
    product = create_product(supply_ceiling_units=supply_ceiling_units, **overrides)
    product = advance_product_lifecycle(product["id"])
    return product


def setup_qualified_embedding_partner(partner_type="EMBEDDED_VENDOR",
                                      destination_country="SG",
                                      export_restriction_tier="LICENSE_REQUIRED") -> dict:
    blueprint = create_certified_blueprint()
    partner = create_validated_partner(partner_type=partner_type,
                                       destination_country=destination_country,
                                       export_restriction_tier=export_restriction_tier,
                                       blueprint_id=blueprint["id"])
    return {"partner": partner, "blueprint": blueprint}


# --------------------------------------------------------------------------
# Tier 3: lifecycle shortcuts
# --------------------------------------------------------------------------

def setup_activated_membership(requested_tier="ELITE", advance_days=30) -> dict:
    """Partner + membership driven REQUESTED -> UNDER_EVALUATION -> ACTIVE with
    `stored_tier` lifted one step."""
    blueprint = create_certified_blueprint()
    partner = create_validated_partner(blueprint_id=blueprint["id"])
    membership = get_success_data(api.create_membership(
        {"requested_tier": requested_tier}, make_partner_ops_headers(partner["id"])), 201)
    membership = get_success_data(api.evaluate_membership(membership["id"], PROGRAM))
    deadline = membership.get("evaluation_deadline_at")
    if deadline:
        advance_clock_past(deadline, days=advance_days)
    membership = get_success_data(api.renew_membership(membership["id"], PROGRAM))
    return {"partner": partner, "membership": membership, "blueprint": blueprint}


def advance_clock_past(iso_instant: str, days: int = 1):
    """Move the logical clock to ``iso_instant`` + ``days`` whole days."""
    base = datetime.datetime.fromisoformat(iso_instant.replace("Z", "+00:00"))
    target = base + datetime.timedelta(days=days)
    return set_clock(target.strftime("%Y-%m-%dT%H:%M:%SZ"))


def create_and_return_loan(product_sku_id, blueprint_id, partner_id, loan_units=50) -> dict:
    product = get_product(product_sku_id)
    loan = get_success_data(api.create_evaluation_loan({
        "product_sku_id": product_sku_id,
        "blueprint_id": blueprint_id,
        "loan_units": loan_units,
    }, make_partner_ops_headers(partner_id)), 201)
    product = get_product(product_sku_id)
    loan = get_success_data(api.approve_evaluation_loan(
        loan["id"], {"expected_product_version": product["version"]}, PROGRAM))
    loan = get_success_data(api.start_evaluation_loan(loan["id"], PROGRAM))
    loan = get_success_data(api.return_evaluation_loan(loan["id"], PROGRAM))
    return loan


# --------------------------------------------------------------------------
# Tier 4: accumulation / threshold targeting
# --------------------------------------------------------------------------

def setup_pool_rate(node_id: str, partner_id: str, product_sku_id: str,
                    total_rate_target: float) -> list:
    """Create repeated 1-unit COOL holds on ``node_id`` until its committed rate
    reaches ``total_rate_target``. Returns the created holds."""
    holds = []
    while True:
        node = get_supply_node(node_id)
        if node["total_committed_rate"] >= total_rate_target - 1e-9:
            break
        holds.append(create_allocation_hold(product_sku_id, node_id, 1, partner_id))
    return holds


def accumulate_partner_attempts(partner_id: str, blueprint_id: str, rejections: int):
    """Drive ``rejections`` full validation+rejection rounds so the partner's
    qualification_attempt_count reaches that value."""
    for _ in range(rejections):
        get_success_data(api.create_validation(
            partner_id,
            {"validation_minutes": D["VALIDATION_MINUTES"],
             "test_count": D["VALIDATION_TEST_COUNT"],
             "blueprint_id": blueprint_id},
            PROGRAM), 201)
        get_success_data(api.reject_partner(partner_id, PROGRAM))
    return get_partner(partner_id)


# --------------------------------------------------------------------------
# Tier 5: finalization / terminal state
# --------------------------------------------------------------------------

def setup_suspended_partner_with_subscription(entitlement_units=250) -> dict:
    """Activated deployment + subscription, then partner suspended so the
    subscription is SUSPENDED and the deployment TERMINATED."""
    ctx = setup_deployment_stack(entitlement_units=entitlement_units)
    # The deployment activator must differ from a later terminator (PRD 3.7),
    # so the handover records a different SupportAccountManager identity.
    get_success_data(api.handover_deployment(ctx["deployment"]["id"],
                                             {"handover_reason": "operator rotation"},
                                             SUPPORT_SECOND))
    ctx["partner"] = get_success_data(api.suspend_partner(ctx["partner"]["id"], PROGRAM))
    ctx["subscription"] = get_subscription(ctx["subscription"]["id"])
    ctx["deployment"] = get_deployment(ctx["deployment"]["id"])
    return ctx


def terminate_deployment(deployment_id: str) -> dict:
    return get_success_data(api.terminate_deployment(deployment_id, SUPPORT))


def setup_terminated_deployment_with_no_covering_subscription() -> dict:
    """A deployment that is ACTIVATED but has no subscription covering it."""
    ctx = setup_partner_with_committed_allocation(quantity_units=400)
    stack = create_stack_license(ctx["product"]["id"])
    deployment = create_deployment(ctx["product"]["id"],
                                   stack_manifest=[{"license_id": stack["id"],
                                                    "entitlement_units": 250}])
    deployment = activate_deployment(deployment["id"])
    ctx.update({"stack": stack, "deployment": deployment})
    return ctx