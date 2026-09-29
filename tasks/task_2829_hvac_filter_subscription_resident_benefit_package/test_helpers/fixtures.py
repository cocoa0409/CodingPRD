"""
Composite setup builders.

The harness restarts the API against an empty database before every individual
test, so each of these builders drives the public endpoints from scratch. Setup
calls use the lenient ``get_success_data`` validator: a failure here is a broken
precondition, not the behaviour under test.

The recurring shape is the *base environment*: one ACTIVE property with one
AVAILABLE unit, one catalog SKU, one resident and one subscription created at
logical clock 2026-08-05. With the canonical values that environment yields
ship_cadence_days 75, filters_per_shipment 2 and monthly_fee_cents 3546; on
activation it books an ENROLLMENT_FEE of 2500 plus a first-month fee of 3088,
leaving the property's outstanding balance at 5588.
"""

from dataclasses import dataclass, field
from typing import Optional

from prd_bench_local_runner.testing import get_success_data, validate_success

from . import factories as f
from .test_users import (
    ADJUSTER_A,
    ADJUSTER_B,
    OPERATOR,
    make_property_manager_headers,
    make_resident_headers,
)


@dataclass
class BaseEnv:
    """Ids and identities produced by the base environment builder."""

    sku_id: str
    property_id: str
    unit_id: str
    resident_id: str
    subscription_id: str
    pm_headers: dict = field(default_factory=dict)
    resident_headers: dict = field(default_factory=dict)


# ─── Primitive builders ───────────────────────────────────────────────────────

def set_clock(api, to_iso8601: str, headers: dict = OPERATOR) -> dict:
    return get_success_data(api.set_clock(f.clock_payload(to_iso8601), headers))


def create_sku(api, headers: dict = OPERATOR, **overrides) -> dict:
    return get_success_data(api.create_filter_sku(f.filter_sku_payload(**overrides), headers))


def create_property(api, headers: dict = OPERATOR, **overrides) -> dict:
    return get_success_data(api.create_property(f.property_payload(**overrides), headers))


def create_unit(api, property_id: str, headers: dict = OPERATOR, **overrides) -> dict:
    return get_success_data(
        api.create_unit(property_id, f.unit_payload(**overrides), headers)
    )


def activate_property(api, property_id: str, headers: dict = OPERATOR) -> dict:
    return get_success_data(api.activate_property(property_id, headers))


def create_resident(api, headers: dict = OPERATOR, **overrides) -> dict:
    return get_success_data(api.create_resident(f.resident_payload(**overrides), headers))


def create_subscription(api, resident_id: str, unit_id: str, headers: dict = OPERATOR, **overrides) -> dict:
    return get_success_data(
        api.create_subscription(
            f.subscription_payload(resident_id, unit_id, **overrides), headers
        )
    )


def activate_subscription(api, subscription_id: str, headers: dict = OPERATOR) -> dict:
    return get_success_data(api.activate_subscription(subscription_id, headers))


def first_shipment(api, subscription_id: str, headers: dict = OPERATOR) -> dict:
    """The shipment auto-scheduled by subscription activation."""
    data = get_success_data(api.list_shipments(headers, {"subscription_id": subscription_id}))
    assert data, "activation should have scheduled a first shipment"
    return data[0]


# ─── Base environment ─────────────────────────────────────────────────────────

def build_base_env(
    api,
    *,
    activate: bool = True,
    clock_at_enrollment: str = "2026-08-05T00:00:00Z",
    property_overrides: Optional[dict] = None,
    unit_overrides: Optional[dict] = None,
    resident_overrides: Optional[dict] = None,
    sku_overrides: Optional[dict] = None,
    subscription_overrides: Optional[dict] = None,
    set_initial_clock: bool = True,
) -> BaseEnv:
    """
    One SKU, one ACTIVE property with one unit, one resident and one
    subscription — optionally activated.
    """
    if set_initial_clock:
        set_clock(api, "2026-08-01T00:00:00Z")

    sku = create_sku(api, **(sku_overrides or {}))
    prop = create_property(api, **(property_overrides or {}))
    unit = create_unit(api, prop["id"], **(unit_overrides or {}))
    activate_property(api, prop["id"])
    resident = create_resident(api, **(resident_overrides or {}))

    if clock_at_enrollment is not None:
        set_clock(api, clock_at_enrollment)

    subscription = create_subscription(
        api, resident["id"], unit["id"], **(subscription_overrides or {})
    )
    if activate:
        activate_subscription(api, subscription["id"])

    return BaseEnv(
        sku_id=sku["id"],
        property_id=prop["id"],
        unit_id=unit["id"],
        resident_id=resident["id"],
        subscription_id=subscription["id"],
        pm_headers=make_property_manager_headers(prop["id"]),
        resident_headers=make_resident_headers(resident["id"]),
    )


# ─── Fulfilment chains ────────────────────────────────────────────────────────

def deliver_first_shipment(
    api, subscription_id: str, delivered_at: str, tracking_code: str = "TRK-A-0001"
) -> dict:
    """Ship then deliver the auto-scheduled first shipment."""
    shipment = first_shipment(api, subscription_id)
    get_success_data(api.ship_shipment(shipment["id"], f.ship_payload(tracking_code), OPERATOR))
    return get_success_data(
        api.deliver_shipment(shipment["id"], f.deliver_payload(delivered_at), OPERATOR)
    )


def request_return_on(api, shipment_id: str, reason: str = "Resident moved out early") -> dict:
    return get_success_data(
        api.request_shipment_return(shipment_id, f.request_return_payload(reason), OPERATOR)
    )


# ─── Non-installation chains ──────────────────────────────────────────────────

def add_runtime_reading(
    api,
    unit_id: str,
    window_start: str,
    window_end: str,
    runtime_minutes: int,
    static_pressure_delta_pa: int,
    source: str = "SMART_THERMOSTAT",
) -> dict:
    return get_success_data(
        api.create_runtime_reading(
            unit_id,
            f.runtime_reading_payload(
                window_start,
                window_end,
                runtime_minutes,
                static_pressure_delta_pa,
                source,
            ),
            OPERATOR,
        )
    )


def submit_renewal_survey(
    api,
    subscription_id: str,
    installed_last_shipment: bool = False,
    filters_on_hand_count: int = 0,
    self_reported_change_date: Optional[str] = None,
) -> dict:
    return get_success_data(
        api.create_renewal_survey(
            subscription_id,
            f.renewal_survey_payload(
                installed_last_shipment, filters_on_hand_count, self_reported_change_date
            ),
            OPERATOR,
        )
    )


def open_case(api, subscription_id: str, detection_method: str, evaluated_through_date: str) -> dict:
    return get_success_data(
        api.create_non_install_evaluation(
            subscription_id,
            f.non_install_evaluation_payload(detection_method, evaluated_through_date),
            OPERATOR,
        )
    )


def send_notice(api, case_id: str) -> dict:
    return get_success_data(api.send_case_notice(case_id, OPERATOR))


def confirm_case(api, case_id: str) -> dict:
    return get_success_data(api.confirm_case(case_id, OPERATOR))


# ─── Claim chains ─────────────────────────────────────────────────────────────

def file_claim(api, subscription_id: str, **overrides) -> dict:
    return get_success_data(
        api.create_claim(f.claim_payload(subscription_id, **overrides), OPERATOR)
    )


def triage_claim(api, claim_id: str, headers: dict = ADJUSTER_A) -> dict:
    return get_success_data(api.triage_claim(claim_id, headers))


def approve_claim(api, claim_id: str, headers: dict = ADJUSTER_B) -> dict:
    return get_success_data(
        api.decide_claim(claim_id, f.decide_payload("APPROVE"), headers)
    )


def pay_claim(api, claim_id: str) -> dict:
    return get_success_data(api.pay_claim(claim_id, OPERATOR))


# ─── Readers ──────────────────────────────────────────────────────────────────

def read_property(api, property_id: str, headers: dict = OPERATOR) -> dict:
    return validate_success(api.get_property(property_id, headers))


def read_subscription(api, subscription_id: str, headers: dict = OPERATOR) -> dict:
    return validate_success(api.get_subscription(subscription_id, headers))


def read_entitlements(api, subscription_id: str, headers: dict = OPERATOR) -> list:
    return validate_success(
        api.list_benefit_entitlements(subscription_id, headers, {"limit": 100})
    )


def read_ledger(api, subscription_id: str, headers: dict = OPERATOR) -> list:
    return validate_success(
        api.list_ledger_entries(subscription_id, headers, {"limit": 100})
    )
