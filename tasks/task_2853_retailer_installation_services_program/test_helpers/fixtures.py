"""Composite state builders.

The harness restarts the API server before every individual test, so every test
starts against an empty database. Nothing here assumes pre-existing rows: each
builder constructs the state it needs from scratch, through the documented
endpoints only, and returns the parsed resources.

Setup calls go through ``get_success_data`` so a broken precondition reports the
API's own error_id rather than a bare status code.
"""

from typing import Any, Dict, List, Optional

from prd_bench_local_runner.testing import get_success_data, validate_paginated

from . import factories as f
from .api_client import ApiClient
from .test_users import (
    NETWORK_MANAGER,
    PROGRAM_ADMIN,
    PROJECT_COORDINATOR,
    SERVICE_MANAGER,
    make_customer_headers,
    make_installer_headers,
)
from .types import (
    AssignmentStatus,
    ChangeOrderDecision,
    DeliveryStatus,
    QualityResult,
)

# ---------------------------------------------------------------------------
# Tier 1 — single-resource creation and the logical clock
# ---------------------------------------------------------------------------
def set_clock(api: ApiClient, current_utc: str) -> Dict[str, Any]:
    """Move the logical clock and return the sweep report."""
    return get_success_data(api.set_clock(current_utc, PROGRAM_ADMIN))


def read_clock(api: ApiClient) -> Dict[str, Any]:
    return get_success_data(api.get_clock(PROGRAM_ADMIN))


def create_category(api: ApiClient, payload: Optional[Dict] = None) -> Dict[str, Any]:
    return get_success_data(
        api.create_service_category(payload or f.service_category_payload(),
                                    PROGRAM_ADMIN)
    )


def create_jurisdiction(api: ApiClient,
                        payload: Optional[Dict] = None) -> Dict[str, Any]:
    return get_success_data(
        api.create_jurisdiction(payload or f.jurisdiction_payload(), PROGRAM_ADMIN)
    )


def create_customer(api: ApiClient, jurisdiction_id: str,
                    payload: Optional[Dict] = None) -> Dict[str, Any]:
    return get_success_data(
        api.create_customer(payload or f.customer_payload(jurisdiction_id),
                            PROGRAM_ADMIN)
    )


def recruit_installer(api: ApiClient,
                      payload: Optional[Dict] = None) -> Dict[str, Any]:
    return get_success_data(
        api.create_installer(payload or f.installer_payload(), NETWORK_MANAGER)
    )


def file_credential(api: ApiClient, installer_id: str, jurisdiction_id: str,
                    payload: Optional[Dict] = None) -> Dict[str, Any]:
    return get_success_data(
        api.create_credential(
            installer_id, payload or f.credential_payload(jurisdiction_id),
            NETWORK_MANAGER,
        )
    )


def verify_credential(api: ApiClient, credential_id: str) -> Dict[str, Any]:
    return get_success_data(
        api.verify_credential(credential_id, f.verify_payload(), NETWORK_MANAGER)
    )


def read_installer(api: ApiClient, installer_id: str) -> Dict[str, Any]:
    return get_success_data(api.get_installer(installer_id, NETWORK_MANAGER))


def read_project(api: ApiClient, project_id: str) -> Dict[str, Any]:
    return get_success_data(api.get_project(project_id, PROJECT_COORDINATOR))


def read_assignment(api: ApiClient, assignment_id: str) -> Dict[str, Any]:
    return get_success_data(api.get_assignment(assignment_id, PROJECT_COORDINATOR))


def read_delivery(api: ApiClient, delivery_id: str) -> Dict[str, Any]:
    return get_success_data(api.get_material_delivery(delivery_id, PROJECT_COORDINATOR))


def read_credential(api: ApiClient, credential_id: str) -> Dict[str, Any]:
    return get_success_data(api.get_credential(credential_id, NETWORK_MANAGER))


def read_scorecard(api: ApiClient, installer_id: str) -> Dict[str, Any]:
    return get_success_data(api.get_scorecard(installer_id, SERVICE_MANAGER))


def project_version(api: ApiClient, project_id: str) -> int:
    return read_project(api, project_id)["version"]


# ---------------------------------------------------------------------------
# Tier 2 — the entity hierarchy
# ---------------------------------------------------------------------------
def program_baseline(api: ApiClient,
                     category_payload: Optional[Dict] = None,
                     jurisdiction_payload: Optional[Dict] = None,
                     customer_payload: Optional[Dict] = None) -> Dict[str, Any]:
    """Catalogue entry, jurisdiction policy row and one purchasing household."""
    category = create_category(api, category_payload)
    jurisdiction = create_jurisdiction(api, jurisdiction_payload)
    customer = create_customer(
        api, jurisdiction["id"],
        customer_payload or f.customer_payload(jurisdiction["id"]),
    )
    return {
        "category": category,
        "jurisdiction": jurisdiction,
        "customer": customer,
    }


def activated_installer(api: ApiClient, jurisdiction_id: str,
                        installer_payload: Optional[Dict] = None,
                        credential_payload: Optional[Dict] = None,
                        background_completed_at: str = "2026-07-15T00:00:00.000Z",
                        ) -> Dict[str, Any]:
    """Recruit, licence, verify, background-check and admit one firm to the network."""
    installer = recruit_installer(api, installer_payload)
    credential = file_credential(
        api, installer["id"], jurisdiction_id, credential_payload
    )
    verify_credential(api, credential["id"])
    get_success_data(
        api.record_background_check(
            installer["id"],
            f.background_check_payload(completed_at=background_completed_at),
            NETWORK_MANAGER,
        )
    )
    activated = get_success_data(
        api.activate_installer(installer["id"], NETWORK_MANAGER)
    )
    return {
        "installer": activated,
        "credential": read_credential(api, credential["id"]),
    }


def sell_project(api: ApiClient, base: Dict[str, Any],
                 estimated_units: float = 420.00,
                 customer: Optional[Dict] = None,
                 jurisdiction: Optional[Dict] = None,
                 **overrides) -> Dict[str, Any]:
    """Sell one project, freezing its provisional quote and deposit requirement."""
    cust = customer or base["customer"]
    jur = jurisdiction or base["jurisdiction"]
    payload = f.project_payload(
        cust["id"], base["category"]["id"], jur["id"],
        estimated_units=estimated_units, **overrides
    )
    return get_success_data(api.create_project(payload, PROJECT_COORDINATOR))


def pay_deposit(api: ApiClient, project: Dict[str, Any], customer_id: str,
                amount_cents: Optional[int] = None) -> Dict[str, Any]:
    """Pay exactly `deposit_required_cents` unless an explicit amount is given."""
    amount = (
        amount_cents if amount_cents is not None
        else project["deposit_required_cents"]
    )
    return get_success_data(
        api.pay_deposit(project["id"], f.deposit_payload(int(amount)),
                        make_customer_headers(customer_id))
    )


def plan_delivery(api: ApiClient, project_id: str,
                 payload: Optional[Dict] = None) -> Dict[str, Any]:
    return get_success_data(
        api.create_material_delivery(project_id, payload or f.delivery_payload(),
                                     PROJECT_COORDINATOR)
    )


def move_delivery(api: ApiClient, delivery_id: str, new_status: str,
                  actual_delivered_at: Optional[str] = None) -> Dict[str, Any]:
    return get_success_data(
        api.update_delivery_status(
            delivery_id,
            f.delivery_status_payload(new_status, actual_delivered_at),
            PROJECT_COORDINATOR,
        )
    )


def hold_assignment(api: ApiClient, project_id: str, installer_id: str,
                    expected_project_version: Optional[int] = None,
                    window_start: str = "2026-08-25T08:00:00.000Z",
                    window_end: str = "2026-08-25T16:00:00.000Z",
                    **overrides) -> Dict[str, Any]:
    version = (
        expected_project_version if expected_project_version is not None
        else project_version(api, project_id)
    )
    payload = f.assignment_payload(
        project_id, installer_id, version,
        window_start=window_start, window_end=window_end, **overrides
    )
    return get_success_data(api.create_assignment(payload, PROJECT_COORDINATOR))


# ---------------------------------------------------------------------------
# Tier 3 — full-lifecycle shortcuts
# ---------------------------------------------------------------------------
def deposited_project(api: ApiClient,
                      category_payload: Optional[Dict] = None,
                      jurisdiction_payload: Optional[Dict] = None,
                      estimated_units: float = 420.00,
                      **project_overrides) -> Dict[str, Any]:
    """Baseline plus one sold project whose deposit has been taken in full."""
    base = program_baseline(api, category_payload, jurisdiction_payload)
    project = sell_project(api, base, estimated_units=estimated_units,
                           **project_overrides)
    project = pay_deposit(api, project, base["customer"]["id"])
    base["project"] = project
    return base


def install_ready(api: ApiClient,
                  category_payload: Optional[Dict] = None,
                  jurisdiction_payload: Optional[Dict] = None,
                  estimated_units: float = 420.00,
                  delivery_payload: Optional[Dict] = None,
                  **project_overrides) -> Dict[str, Any]:
    """Everything needed to hold an install window: an active firm, a deposited
    project and a planned material delivery."""
    ctx = deposited_project(api, category_payload, jurisdiction_payload,
                            estimated_units=estimated_units, **project_overrides)
    network = activated_installer(api, ctx["jurisdiction"]["id"])
    ctx.update(network)
    ctx["delivery"] = plan_delivery(api, ctx["project"]["id"], delivery_payload)
    ctx["project"] = read_project(api, ctx["project"]["id"])
    return ctx


def scheduled_project(api: ApiClient,
                      window_start: str = "2026-08-25T08:00:00.000Z",
                      window_end: str = "2026-08-25T16:00:00.000Z",
                      **kwargs) -> Dict[str, Any]:
    """`install_ready` plus a HELD assignment, so the project sits at SCHEDULED."""
    ctx = install_ready(api, **kwargs)
    ctx["assignment"] = hold_assignment(
        api, ctx["project"]["id"], ctx["installer"]["id"],
        ctx["project"]["version"], window_start=window_start, window_end=window_end,
    )
    ctx["project"] = read_project(api, ctx["project"]["id"])
    return ctx


def confirmed_project(api: ApiClient, **kwargs) -> Dict[str, Any]:
    ctx = scheduled_project(api, **kwargs)
    ctx["assignment"] = get_success_data(
        api.confirm_assignment(ctx["assignment"]["id"], PROJECT_COORDINATOR)
    )
    return ctx


def in_progress_project(api: ApiClient,
                        start_clock: str = "2026-08-25T08:00:00.000Z",
                        **kwargs) -> Dict[str, Any]:
    ctx = confirmed_project(api, **kwargs)
    set_clock(api, start_clock)
    ctx["assignment"] = get_success_data(
        api.start_assignment(ctx["assignment"]["id"],
                             make_installer_headers(ctx["installer"]["id"]))
    )
    ctx["project"] = read_project(api, ctx["project"]["id"])
    return ctx


def installed_project(api: ApiClient,
                      complete_clock: str = "2026-08-25T15:30:00.000Z",
                      **kwargs) -> Dict[str, Any]:
    """Take the work all the way to INSTALL_COMPLETE, which runs the final labour
    variant, the deposit waterfall and the timeliness scorecard event."""
    ctx = in_progress_project(api, **kwargs)
    set_clock(api, complete_clock)
    ctx["assignment"] = get_success_data(
        api.complete_assignment(
            ctx["assignment"]["id"], f.completion_payload(complete_clock),
            make_installer_headers(ctx["installer"]["id"]),
        )
    )
    ctx["project"] = read_project(api, ctx["project"]["id"])
    ctx["installer"] = read_installer(api, ctx["installer"]["id"])
    return ctx


def settled_project(api: ApiClient, **kwargs) -> Dict[str, Any]:
    """`installed_project` with the outstanding balance paid, so the money dimension
    reads SETTLED and the project is closable."""
    ctx = installed_project(api, **kwargs)
    balance = ctx["project"]["balance_due_cents"]
    if balance > 0:
        ctx["project"] = get_success_data(
            api.pay_balance(ctx["project"]["id"], f.balance_payload(int(balance)),
                            make_customer_headers(ctx["customer"]["id"]))
        )
    return ctx


def punch_open_project(api: ApiClient, defects: Optional[List[Dict]] = None,
                       quality_result: str = QualityResult.PASS_WITH_PUNCH,
                       workmanship_score: int = 88,
                       **kwargs) -> Dict[str, Any]:
    """A settled project whose quality inspection reported defects, so the project
    sits at PUNCH_OPEN with one punch item per defect."""
    ctx = settled_project(api, **kwargs)
    items = defects if defects is not None else [
        f.defect("MINOR", "Quarter-round gap at the pantry wall")
    ]
    ctx["project"] = get_success_data(
        api.record_quality_inspection(
            ctx["project"]["id"],
            f.quality_inspection_payload(quality_result, workmanship_score, items),
            PROJECT_COORDINATOR,
        )
    )
    ctx["punch_items"] = list_punch_items(api, ctx["project"]["id"])
    return ctx


def closed_project(api: ApiClient, **kwargs) -> Dict[str, Any]:
    """A settled project recorded as a clean PASS and then closed."""
    ctx = settled_project(api, **kwargs)
    ctx["project"] = get_success_data(
        api.record_quality_inspection(
            ctx["project"]["id"],
            f.quality_inspection_payload(QualityResult.PASS, 95, []),
            PROJECT_COORDINATOR,
        )
    )
    ctx["project"] = get_success_data(
        api.close_project(ctx["project"]["id"], PROJECT_COORDINATOR)
    )
    return ctx


# ---------------------------------------------------------------------------
# Tier 4 — accumulation and threshold targeting
# ---------------------------------------------------------------------------
def file_events(api: ApiClient, installer_id: str,
                events: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """File a list of scorecard-event payloads in order, returning the ledger rows."""
    written = []
    for payload in events:
        written.append(
            get_success_data(
                api.create_scorecard_event(installer_id, payload, SERVICE_MANAGER)
            )
        )
    return written


def installer_with_events(api: ApiClient, events: List[Dict[str, Any]],
                          jurisdiction_payload: Optional[Dict] = None,
                          ) -> Dict[str, Any]:
    """An active firm carrying an explicit ledger, for score arithmetic."""
    jurisdiction = create_jurisdiction(api, jurisdiction_payload)
    network = activated_installer(api, jurisdiction["id"])
    network["jurisdiction"] = jurisdiction
    network["events"] = file_events(api, network["installer"]["id"], events)
    network["installer"] = read_installer(api, network["installer"]["id"])
    return network


def book_measurement(api: ApiClient, project_id: str,
                     scheduled_at: str = "2026-08-05T09:00:00.000Z") -> Dict[str, Any]:
    return get_success_data(
        api.create_measurement(project_id, f.measurement_payload(scheduled_at),
                               PROJECT_COORDINATOR)
    )


def complete_measurement(api: ApiClient, measurement_id: str, measured_units: float,
                         **kwargs) -> Dict[str, Any]:
    return get_success_data(
        api.complete_measurement(
            measurement_id,
            f.measurement_completion_payload(measured_units, **kwargs),
            PROJECT_COORDINATOR,
        )
    )


def measured_project(api: ApiClient, measured_units: float = 420.00,
                     measurement_clock: Optional[str] = None,
                     scheduled_at: str = "2026-08-05T09:00:00.000Z",
                     **kwargs) -> Dict[str, Any]:
    """A deposited project on a measurement-required category whose in-home visit has
    been booked and completed."""
    kwargs.setdefault("category_payload", f.measured_category_payload())
    ctx = deposited_project(api, **kwargs)
    if measurement_clock is not None:
        set_clock(api, measurement_clock)
    ctx["measurement"] = book_measurement(api, ctx["project"]["id"], scheduled_at)
    ctx["measurement"] = complete_measurement(
        api, ctx["measurement"]["id"], measured_units,
        **{k: v for k, v in kwargs.items() if k in ("subfloor_condition",)}
    )
    ctx["project"] = read_project(api, ctx["project"]["id"])
    return ctx


def raise_change_order(api: ApiClient, project_id: str, lines: List[Dict],
                       origin: str = "CUSTOMER_REQUEST",
                       expected_project_version: Optional[int] = None,
                       **overrides) -> Dict[str, Any]:
    version = (
        expected_project_version if expected_project_version is not None
        else project_version(api, project_id)
    )
    return get_success_data(
        api.create_change_order(
            f.change_order_payload(project_id, version, lines, origin, **overrides),
            PROJECT_COORDINATOR,
        )
    )


def accept_change_order(api: ApiClient, change_order_id: str,
                        customer_id: str) -> Dict[str, Any]:
    return get_success_data(
        api.decide_change_order(
            change_order_id, f.decision_payload(ChangeOrderDecision.ACCEPT),
            make_customer_headers(customer_id),
        )
    )


# ---------------------------------------------------------------------------
# Tier 5 — finalisation and terminal states
# ---------------------------------------------------------------------------
def cancel_project(api: ApiClient, project_id: str, headers: Dict[str, str],
                   reason: str = "Customer is moving out of state") -> Dict[str, Any]:
    return get_success_data(
        api.cancel_project(project_id, f.cancel_payload(reason), headers)
    )


def permit_issued_project(api: ApiClient, permit_fee_cents: int = 18500,
                          permit_issued_on: str = "2026-08-01T00:00:00.000Z",
                          reference: str = "PA-2026-0001",
                          **kwargs) -> Dict[str, Any]:
    """A project whose retailer-side permit has been applied for and issued."""
    kwargs.setdefault("category_payload", f.quick_category_payload())
    kwargs.setdefault("jurisdiction_payload", f.jurisdiction_payload(
        inspection_required=True))
    ctx = deposited_project(api, **kwargs)
    ctx["project"] = get_success_data(
        api.apply_permit(ctx["project"]["id"], f.permit_apply_payload(reference),
                         PROJECT_COORDINATOR)
    )
    ctx["project"] = get_success_data(
        api.issue_permit(
            ctx["project"]["id"],
            f.permit_issue_payload(permit_fee_cents, permit_issued_on),
            PROJECT_COORDINATOR,
        )
    )
    return ctx


# ---------------------------------------------------------------------------
# Reverse discovery helpers
# ---------------------------------------------------------------------------
def list_punch_items(api: ApiClient, project_id: str,
                     params: Optional[Dict] = None) -> List[Dict[str, Any]]:
    rows, _ = validate_paginated(
        api.list_project_punch_list_items(project_id, PROJECT_COORDINATOR, params)
    )
    return rows


def list_project_change_orders(api: ApiClient, project_id: str,
                               params: Optional[Dict] = None) -> List[Dict[str, Any]]:
    rows, _ = validate_paginated(
        api.list_project_change_orders(project_id, PROJECT_COORDINATOR, params)
    )
    return rows


def variance_change_order(api: ApiClient, project_id: str) -> Dict[str, Any]:
    """The MEASUREMENT_VARIANCE change order a measurement cascade minted; it appears
    in no response body and is reachable only through a filtered list."""
    rows, _ = validate_paginated(
        api.list_change_orders(
            PROJECT_COORDINATOR,
            {"project_id": project_id, "origin": "MEASUREMENT_VARIANCE"},
        )
    )
    assert rows, "expected a MEASUREMENT_VARIANCE change order to have been raised"
    return rows[0]


def list_installer_events(api: ApiClient, installer_id: str,
                          params: Optional[Dict] = None) -> List[Dict[str, Any]]:
    rows, _ = validate_paginated(
        api.list_installer_scorecard_events(installer_id, SERVICE_MANAGER, params)
    )
    return rows


def list_installer_assignments(api: ApiClient, installer_id: str,
                               params: Optional[Dict] = None) -> List[Dict[str, Any]]:
    query = {"installer_id": installer_id}
    if params:
        query.update(params)
    rows, _ = validate_paginated(
        api.list_assignments(PROJECT_COORDINATOR, query)
    )
    return rows


LIVE_ASSIGNMENT_STATUSES = (
    AssignmentStatus.HELD,
    AssignmentStatus.CONFIRMED,
    AssignmentStatus.IN_PROGRESS,
    AssignmentStatus.COMPLETED,
)

PLANNED_DELIVERY_STATUSES = (
    DeliveryStatus.PLANNED,
    DeliveryStatus.IN_TRANSIT,
    DeliveryStatus.DELIVERED,
)
