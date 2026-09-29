"""Composite setup helpers.

Every helper builds its preconditions from scratch through PRD-declared
endpoints only, because each test starts against an empty database. Setup calls
use the lenient `get_success_data()` validator so a broken precondition reports
itself as a setup failure rather than as a confusing assertion failure.

The helpers thread a single mutable `env` dict through the lifecycle. Keys are
added as the chain progresses: customer, model, line, engineer, trial, order,
component, slot, fat, sat, machine, kit, contract, visit, claim, claim_lines,
recommendation.
"""

from typing import Any, Dict, List, Optional

from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .factories import (
    create_acceptance_test_payload,
    create_build_slot_payload,
    create_customer_payload,
    create_field_engineer_payload,
    create_format_kit_payload,
    create_installed_machine_payload,
    create_long_lead_component_payload,
    create_machine_model_payload,
    create_machine_order_payload,
    create_pm_visit_payload,
    create_product_trial_payload,
    create_production_line_payload,
    create_service_contract_payload,
    create_stocking_recommendation_payload,
    create_warranty_claim_line_payload,
    create_warranty_claim_payload,
    finalize_acceptance_test_payload,
    record_trial_result_payload,
    start_acceptance_test_payload,
)
from .test_users import TEST_USERS, make_customer_contact_headers

ADMIN = TEST_USERS["platform_admin_headers"]
APP_ENGINEER = TEST_USERS["application_engineer_headers"]
PLANNER = TEST_USERS["production_planner_headers"]
INSPECTOR = TEST_USERS["quality_inspector_headers"]
SERVICE_MANAGER = TEST_USERS["service_manager_headers"]


# --- Single-row seeds ----------------------------------------------------


def seed_customer(**overrides) -> Dict[str, Any]:
    return get_success_data(api_client.create_customer(create_customer_payload(**overrides), ADMIN))


def seed_machine_model(**overrides) -> Dict[str, Any]:
    return get_success_data(
        api_client.create_machine_model(create_machine_model_payload(**overrides), ADMIN)
    )


def seed_production_line(**overrides) -> Dict[str, Any]:
    return get_success_data(
        api_client.create_production_line(create_production_line_payload(**overrides), ADMIN)
    )


def seed_field_engineer(**overrides) -> Dict[str, Any]:
    return get_success_data(
        api_client.create_field_engineer(create_field_engineer_payload(**overrides), ADMIN)
    )


def move_clock(to_iso8601: str) -> Dict[str, Any]:
    """Move the server's logical clock; this mutates no entity row (PRD §2.5)."""
    return get_success_data(api_client.set_clock(to_iso8601, ADMIN))


def read_order(order_id: str) -> Dict[str, Any]:
    return get_success_data(api_client.get_machine_order(order_id, PLANNER))


def read_line(line_id: str) -> Dict[str, Any]:
    return get_success_data(api_client.get_production_line(line_id, PLANNER))


def read_slot(slot_id: str) -> Dict[str, Any]:
    return get_success_data(api_client.get_build_slot(slot_id, PLANNER))


def read_trial(trial_id: str) -> Dict[str, Any]:
    return get_success_data(api_client.get_product_trial(trial_id, APP_ENGINEER))


def read_test(test_id: str) -> Dict[str, Any]:
    return get_success_data(api_client.get_acceptance_test(test_id, INSPECTOR))


def read_machine(machine_id: str) -> Dict[str, Any]:
    return get_success_data(api_client.get_installed_machine(machine_id, SERVICE_MANAGER))


def read_contract(contract_id: str) -> Dict[str, Any]:
    return get_success_data(api_client.get_service_contract(contract_id, SERVICE_MANAGER))


def read_visit(visit_id: str) -> Dict[str, Any]:
    return get_success_data(api_client.get_pm_visit(visit_id, SERVICE_MANAGER))


def read_claim(claim_id: str) -> Dict[str, Any]:
    return get_success_data(api_client.get_warranty_claim(claim_id, SERVICE_MANAGER))


def read_claim_line(line_id: str) -> Dict[str, Any]:
    return get_success_data(api_client.get_warranty_claim_line(line_id, SERVICE_MANAGER))


def read_customer(customer_id: str) -> Dict[str, Any]:
    return get_success_data(api_client.get_customer(customer_id, ADMIN))


def read_model(model_id: str) -> Dict[str, Any]:
    return get_success_data(api_client.get_machine_model(model_id, ADMIN))


def read_kit(kit_id: str) -> Dict[str, Any]:
    return get_success_data(api_client.get_format_kit(kit_id, SERVICE_MANAGER))


def read_recommendation(recommendation_id: str) -> Dict[str, Any]:
    return get_success_data(
        api_client.get_stocking_recommendation(recommendation_id, SERVICE_MANAGER)
    )


# --- Tier 1/2: reference data and a passed trial -------------------------


def setup_reference_data(
    customer: Optional[dict] = None,
    model: Optional[dict] = None,
    line: Optional[dict] = None,
    engineer: Optional[dict] = None,
) -> Dict[str, Any]:
    """A customer plant, a catalog model, and optionally a production line and a
    field engineer. Pass a dict of field overrides for each row you want, or
    None to skip the line / engineer."""
    env: Dict[str, Any] = {}
    env["customer"] = seed_customer(**(customer or {}))
    env["model"] = seed_machine_model(**(model or {}))
    if line is not None:
        env["line"] = seed_production_line(**line)
    if engineer is not None:
        env["engineer"] = seed_field_engineer(**engineer)
    return env


def setup_submitted_trial(env: Optional[Dict[str, Any]] = None, **trial_overrides) -> Dict[str, Any]:
    """Reference data plus one SUBMITTED product trial."""
    env = env if env is not None else setup_reference_data()
    env["trial"] = get_success_data(
        api_client.create_product_trial(
            create_product_trial_payload(
                env["customer"]["id"], env["model"]["id"], **trial_overrides
            ),
            APP_ENGINEER,
        )
    )
    return env


def setup_passed_trial(
    env: Optional[Dict[str, Any]] = None,
    measured_rate_cpm: int = 570,
    **trial_overrides,
) -> Dict[str, Any]:
    """Trial driven SUBMITTED -> TESTING -> PASSED with a passing rig result."""
    env = setup_submitted_trial(env, **trial_overrides)
    get_success_data(api_client.start_testing_product_trial(env["trial"]["id"], APP_ENGINEER))
    env["trial"] = get_success_data(
        api_client.record_result_product_trial(
            env["trial"]["id"],
            record_trial_result_payload(measured_rate_cpm=measured_rate_cpm, outcome="PASS"),
            APP_ENGINEER,
        )
    )
    return env


# --- Tier 2/3: the machine-order fulfillment chain -----------------------


def setup_draft_order(env: Optional[Dict[str, Any]] = None, **order_overrides) -> Dict[str, Any]:
    """Reference data, a PASSED trial and a DRAFT / QUOTED machine order."""
    env = env if env is not None else setup_passed_trial(setup_reference_data(line={}))
    if "trial" not in env:
        env = setup_passed_trial(env)
    env["order"] = get_success_data(
        api_client.create_machine_order(
            create_machine_order_payload(
                env["customer"]["id"],
                env["model"]["id"],
                env["trial"]["id"],
                **order_overrides,
            ),
            APP_ENGINEER,
        )
    )
    return env


def setup_engineered_order(env: Optional[Dict[str, Any]] = None, **order_overrides) -> Dict[str, Any]:
    """Order carried to ENGINEERED so a build slot can be reserved."""
    env = setup_draft_order(env, **order_overrides)
    env["order"] = get_success_data(
        api_client.engineer_machine_order(env["order"]["id"], APP_ENGINEER)
    )
    return env


def advance_commercial(env: Dict[str, Any], target_status: str = "PO_RECEIVED") -> Dict[str, Any]:
    """Walk the commercial dimension forward one rung; the fulfillment dimension
    is untouched."""
    env["order"] = get_success_data(
        api_client.commercial_advance_machine_order(env["order"]["id"], target_status, ADMIN)
    )
    return env


def seed_component(env: Dict[str, Any], **overrides) -> Dict[str, Any]:
    """Add a long-lead procurement line to the order in env."""
    env["component"] = get_success_data(
        api_client.create_long_lead_component(
            create_long_lead_component_payload(env["order"]["id"], **overrides), PLANNER
        )
    )
    return env


def reserve_slot(
    env: Dict[str, Any],
    line: Optional[Dict[str, Any]] = None,
    expected_machine_order_version: Optional[int] = None,
    **slot_overrides,
) -> Dict[str, Any]:
    """Reserve a build slot, pinning the order's current version read back from
    the order itself (§2.7). Pass `line` to occupy a line other than env['line'],
    or `expected_machine_order_version` to pin a version deliberately."""
    target_line = line if line is not None else env["line"]
    version = (
        expected_machine_order_version
        if expected_machine_order_version is not None
        else read_order(env["order"]["id"])["version"]
    )
    env["slot"] = get_success_data(
        api_client.create_build_slot(
            create_build_slot_payload(
                env["order"]["id"], target_line["id"], version, **slot_overrides
            ),
            PLANNER,
        )
    )
    return env


def setup_order_with_reserved_slot(
    env: Optional[Dict[str, Any]] = None,
    commercial_status: Optional[str] = "PO_RECEIVED",
    order_overrides: Optional[dict] = None,
    **slot_overrides,
) -> Dict[str, Any]:
    """ENGINEERED order with one RESERVED slot on the line. By default the
    commercial dimension is already at PO_RECEIVED so the slot can be confirmed;
    pass commercial_status=None to leave the money track at QUOTED."""
    env = setup_engineered_order(env, **(order_overrides or {}))
    if commercial_status is not None:
        advance_commercial(env, commercial_status)
    return reserve_slot(env, **slot_overrides)


def setup_confirmed_slot(env: Optional[Dict[str, Any]] = None, **kwargs) -> Dict[str, Any]:
    """Slot CONFIRMED, which bubbles the order's fulfillment to SLOTTED."""
    env = setup_order_with_reserved_slot(env, **kwargs)
    env["slot"] = get_success_data(api_client.confirm_build_slot(env["slot"]["id"], PLANNER))
    env["order"] = read_order(env["order"]["id"])
    return env


def setup_order_in_build(env: Optional[Dict[str, Any]] = None, **kwargs) -> Dict[str, Any]:
    """Slot IN_BUILD and order fulfillment IN_BUILD — the state a factory test
    can be booked from."""
    env = setup_confirmed_slot(env, **kwargs)
    env["slot"] = get_success_data(api_client.start_build_build_slot(env["slot"]["id"], PLANNER))
    env["order"] = read_order(env["order"]["id"])
    return env


# --- Tier 3: acceptance testing, shipment and installation ---------------


def book_test(env: Dict[str, Any], kind: str = "FAT", **overrides) -> Dict[str, Any]:
    """Book an acceptance test of the given kind against the order in env."""
    data = get_success_data(
        api_client.create_acceptance_test(
            create_acceptance_test_payload(env["order"]["id"], kind=kind, **overrides), INSPECTOR
        )
    )
    env["fat" if kind == "FAT" else "sat"] = data
    return env


def start_test(
    env: Dict[str, Any],
    kind: str = "FAT",
    customer_product_supplied: bool = True,
    containers_supplied_count: Optional[int] = None,
) -> Dict[str, Any]:
    """Start the booked run with the customer's product and containers on the
    floor; the default supplied count clears the minimum for the kind."""
    key = "fat" if kind == "FAT" else "sat"
    count = containers_supplied_count if containers_supplied_count is not None else (
        500 if kind == "FAT" else 200
    )
    env[key] = get_success_data(
        api_client.start_acceptance_test(
            env[key]["id"],
            start_acceptance_test_payload(customer_product_supplied, count),
            INSPECTOR,
        )
    )
    return env


def finalize_test(
    env: Dict[str, Any],
    kind: str = "FAT",
    measured_rate_cpm: int = 570,
    measured_efficiency_pct: float = 96.00,
    operators_trained_count: Optional[int] = None,
) -> Dict[str, Any]:
    key = "fat" if kind == "FAT" else "sat"
    env[key] = get_success_data(
        api_client.finalize_acceptance_test(
            env[key]["id"],
            finalize_acceptance_test_payload(
                measured_rate_cpm, measured_efficiency_pct, operators_trained_count
            ),
            INSPECTOR,
        )
    )
    env["order"] = read_order(env["order"]["id"])
    return env


def setup_fat_in_progress(env: Optional[Dict[str, Any]] = None, **kwargs) -> Dict[str, Any]:
    """Factory run IN_PROGRESS, ready to be finalized with any run data."""
    env = setup_order_in_build(env, **kwargs)
    env = book_test(env, "FAT")
    return start_test(env, "FAT")


def setup_fat_passed(
    env: Optional[Dict[str, Any]] = None,
    measured_rate_cpm: int = 570,
    measured_efficiency_pct: float = 96.00,
    **kwargs,
) -> Dict[str, Any]:
    """Factory run PASSED: order FAT_PASSED and its slot COMPLETED."""
    env = setup_fat_in_progress(env, **kwargs)
    env = finalize_test(env, "FAT", measured_rate_cpm, measured_efficiency_pct)
    env["slot"] = read_slot(env["slot"]["id"])
    return env


def setup_shipped_order(env: Optional[Dict[str, Any]] = None, **kwargs) -> Dict[str, Any]:
    env = setup_fat_passed(env, **kwargs)
    env["order"] = get_success_data(api_client.ship_machine_order(env["order"]["id"], PLANNER))
    return env


def setup_installed_machine(
    env: Optional[Dict[str, Any]] = None, machine_overrides: Optional[dict] = None, **kwargs
) -> Dict[str, Any]:
    """Asset recorded INSTALLED, which cascades the order to INSTALLED."""
    env = setup_shipped_order(env, **kwargs)
    env["machine"] = get_success_data(
        api_client.create_installed_machine(
            create_installed_machine_payload(
                env["order"]["id"], env["customer"]["id"], **(machine_overrides or {})
            ),
            SERVICE_MANAGER,
        )
    )
    env["order"] = read_order(env["order"]["id"])
    return env


def setup_accepted_machine(
    env: Optional[Dict[str, Any]] = None,
    required_operators_trained: int = 2,
    operators_trained_count: int = 2,
    sat_measured_rate_cpm: int = 570,
    sat_measured_efficiency_pct: float = 96.00,
    **kwargs,
) -> Dict[str, Any]:
    """Site run PASSED: order ACCEPTED and the asset ACCEPTED, which is the gate
    every aftermarket activity waits on."""
    env = setup_installed_machine(env, **kwargs)
    env = book_test(env, "SAT", required_operators_trained=required_operators_trained)
    env = start_test(env, "SAT")
    env = finalize_test(
        env,
        "SAT",
        sat_measured_rate_cpm,
        sat_measured_efficiency_pct,
        operators_trained_count=operators_trained_count,
    )
    env["machine"] = read_machine(env["machine"]["id"])
    return env


# --- Tier 3/4: aftermarket kits and spare-parts stocking -----------------


def draft_kit(env: Dict[str, Any], components: Optional[List[dict]] = None, **overrides) -> Dict[str, Any]:
    env["kit"] = get_success_data(
        api_client.create_format_kit(
            create_format_kit_payload(env["machine"]["id"], components, **overrides),
            SERVICE_MANAGER,
        )
    )
    return env


def setup_quoted_kit(
    env: Optional[Dict[str, Any]] = None,
    components: Optional[List[dict]] = None,
    kit_overrides: Optional[dict] = None,
    **kwargs,
) -> Dict[str, Any]:
    """Accepted machine with one QUOTED format kit."""
    env = env if env is not None and "machine" in env else setup_accepted_machine(env, **kwargs)
    env = draft_kit(env, components, **(kit_overrides or {}))
    env["kit"] = get_success_data(api_client.quote_format_kit(env["kit"]["id"], SERVICE_MANAGER))
    return env


def setup_ordered_kit(env: Optional[Dict[str, Any]] = None, **kwargs) -> Dict[str, Any]:
    """Kit accepted by the owning customer contact, so it sits in ORDERED."""
    env = setup_quoted_kit(env, **kwargs)
    env["kit"] = get_success_data(
        api_client.order_format_kit(
            env["kit"]["id"], make_customer_contact_headers(env["customer"]["id"])
        )
    )
    return env


def publish_recommendation(env: Dict[str, Any], **overrides) -> Dict[str, Any]:
    """Publish a stocking recommendation pinning the asset's freshly read
    version (§2.7)."""
    version = read_machine(env["machine"]["id"])["version"]
    env["recommendation"] = get_success_data(
        api_client.create_stocking_recommendation(
            create_stocking_recommendation_payload(env["machine"]["id"], version, **overrides),
            SERVICE_MANAGER,
        )
    )
    return env


def setup_active_recommendation(env: Optional[Dict[str, Any]] = None, **overrides) -> Dict[str, Any]:
    env = env if env is not None and "machine" in env else setup_accepted_machine(env)
    return publish_recommendation(env, **overrides)


# --- Tier 4/5: service contracts, visits and warranty claims ------------


def draft_contract(env: Dict[str, Any], **overrides) -> Dict[str, Any]:
    env["contract"] = get_success_data(
        api_client.create_service_contract(
            create_service_contract_payload(env["machine"]["id"], **overrides), SERVICE_MANAGER
        )
    )
    return env


def setup_active_contract(
    env: Optional[Dict[str, Any]] = None,
    contract_overrides: Optional[dict] = None,
    **kwargs,
) -> Dict[str, Any]:
    """Accepted machine plus an ACTIVE contract whose goodwill pot is funded."""
    env = env if env is not None and "machine" in env else setup_accepted_machine(env, **kwargs)
    env = draft_contract(env, **(contract_overrides or {}))
    env["contract"] = get_success_data(
        api_client.activate_service_contract(env["contract"]["id"], SERVICE_MANAGER)
    )
    return env


def book_visit(env: Dict[str, Any], **overrides) -> Dict[str, Any]:
    """Book a visit on the contract in env. An engineer is attached by default
    when env carries one, because on-site work requires a named engineer."""
    payload_overrides = dict(overrides)
    if "field_engineer_id" not in payload_overrides and "engineer" in env:
        if payload_overrides.get("visit_type", "PM") != "REMOTE_DIAGNOSTIC":
            payload_overrides["field_engineer_id"] = env["engineer"]["id"]
    env["visit"] = get_success_data(
        api_client.create_pm_visit(
            create_pm_visit_payload(env["contract"]["id"], **payload_overrides), SERVICE_MANAGER
        )
    )
    return env


def setup_scheduled_visit(
    env: Optional[Dict[str, Any]] = None,
    engineer_overrides: Optional[dict] = None,
    visit_overrides: Optional[dict] = None,
    **kwargs,
) -> Dict[str, Any]:
    """ACTIVE contract with one SCHEDULED preventive visit and the engineer who
    will attend it."""
    env = env if env is not None and "contract" in env else setup_active_contract(env, **kwargs)
    if "engineer" not in env:
        env["engineer"] = seed_field_engineer(**(engineer_overrides or {}))
    return book_visit(env, **(visit_overrides or {}))


def open_claim(env: Dict[str, Any], **overrides) -> Dict[str, Any]:
    env["claim"] = get_success_data(
        api_client.create_warranty_claim(
            create_warranty_claim_payload(
                env["machine"]["id"], env["contract"]["id"], **overrides
            ),
            SERVICE_MANAGER,
        )
    )
    return env


def add_claim_line(env: Dict[str, Any], **overrides) -> Dict[str, Any]:
    """Append an immutable cost line and record it in env['claim_lines']."""
    line = get_success_data(
        api_client.create_warranty_claim_line(
            create_warranty_claim_line_payload(env["claim"]["id"], **overrides), SERVICE_MANAGER
        )
    )
    env.setdefault("claim_lines", []).append(line)
    env["claim"] = read_claim(env["claim"]["id"])
    return env


def setup_claim_with_lines(
    env: Optional[Dict[str, Any]] = None,
    lines: Optional[List[dict]] = None,
    claim_overrides: Optional[dict] = None,
    **kwargs,
) -> Dict[str, Any]:
    """SUBMITTED claim carrying its cost lines. `lines` is a list of override
    dicts, applied in the order given so the pinned per-line walk order is the
    order supplied."""
    env = env if env is not None and "contract" in env else setup_active_contract(env, **kwargs)
    env = open_claim(env, **(claim_overrides or {}))
    for line_overrides in lines if lines is not None else [{}]:
        add_claim_line(env, **line_overrides)
    return env


def sign_both_reviews(env: Dict[str, Any], variation_first: bool = True) -> Dict[str, Any]:
    """Sign off both fork branches; the branch signed off first owns the claim's
    status field."""
    if variation_first:
        get_success_data(
            api_client.review_product_variation_warranty_claim(env["claim"]["id"], SERVICE_MANAGER)
        )
        get_success_data(api_client.review_defect_warranty_claim(env["claim"]["id"], INSPECTOR))
    else:
        get_success_data(api_client.review_defect_warranty_claim(env["claim"]["id"], INSPECTOR))
        get_success_data(
            api_client.review_product_variation_warranty_claim(env["claim"]["id"], SERVICE_MANAGER)
        )
    env["claim"] = read_claim(env["claim"]["id"])
    return env


def setup_claim_ready_for_adjudication(
    env: Optional[Dict[str, Any]] = None, variation_first: bool = True, **kwargs
) -> Dict[str, Any]:
    """Claim with both reviews signed off, so the join may be adjudicated."""
    env = setup_claim_with_lines(env, **kwargs)
    return sign_both_reviews(env, variation_first=variation_first)


def setup_adjudicated_claim(
    env: Optional[Dict[str, Any]] = None, resolution: str = "APPROVE", **kwargs
) -> Dict[str, Any]:
    """Claim adjudicated, so the goodwill pot has moved and the coverage posture
    has been re-derived."""
    env = setup_claim_ready_for_adjudication(env, **kwargs)
    env["claim"] = get_success_data(
        api_client.adjudicate_warranty_claim(env["claim"]["id"], resolution, SERVICE_MANAGER)
    )
    env["contract"] = read_contract(env["contract"]["id"])
    return env


def refresh(env: Dict[str, Any]) -> Dict[str, Any]:
    """Re-read every row the env chain currently holds, so assertions see the
    state after the cascades of the last request."""
    if "customer" in env:
        env["customer"] = read_customer(env["customer"]["id"])
    if "model" in env:
        env["model"] = read_model(env["model"]["id"])
    if "line" in env:
        env["line"] = read_line(env["line"]["id"])
    if "order" in env:
        env["order"] = read_order(env["order"]["id"])
    if "slot" in env:
        env["slot"] = read_slot(env["slot"]["id"])
    if "trial" in env:
        env["trial"] = read_trial(env["trial"]["id"])
    if "fat" in env:
        env["fat"] = read_test(env["fat"]["id"])
    if "sat" in env:
        env["sat"] = read_test(env["sat"]["id"])
    if "machine" in env:
        env["machine"] = read_machine(env["machine"]["id"])
    if "kit" in env:
        env["kit"] = read_kit(env["kit"]["id"])
    if "contract" in env:
        env["contract"] = read_contract(env["contract"]["id"])
    if "visit" in env:
        env["visit"] = read_visit(env["visit"]["id"])
    if "claim" in env:
        env["claim"] = read_claim(env["claim"]["id"])
    if "claim_lines" in env:
        env["claim_lines"] = [read_claim_line(line["id"]) for line in env["claim_lines"]]
    if "recommendation" in env:
        env["recommendation"] = read_recommendation(env["recommendation"]["id"])
    return env
