"""ReferentialIntegration and AlertNotification endpoints (PRD 3.11, 2.12)."""

from flask import Blueprint

from calculations import (
    effective_credit_rate,
    integration_basis_component_cents,
    settlement_account_cents,
)
from constants import (
    INTEGRATION_CREDIT_RATE,
    ROLE_BUDGET_APPROPRIATIONS_COMMITTEE,
    ROLE_REGIONAL_FINANCE_OFFICER,
)
from db import STORE
from domain import (
    get_alert,
    get_integration,
    get_region,
    new_record,
    recompute_region_aggregates,
    store_row,
    touch,
)
from errors import ERR_INVALID_STATE, ERR_REGION_POSTURE_FROZEN, raise_error
from projections import region_view
from routes._common import (
    READERS,
    arg,
    filter_rows,
    list_response,
    optional_field,
    payload,
    principal,
    require_field,
    single_response,
)
from rounding import dec, round_half_up_int

bp = Blueprint("integrations", __name__)


def _credit_contribution(integration):
    """The integration's contribution to the region's credit rollup."""
    rate = INTEGRATION_CREDIT_RATE.get(
        integration.get("risk_sharing_model"), dec(0))
    return round_half_up_int(
        dec(integration.get("cost_reporting_basis_cents") or 0) * rate)


@bp.post("/regions/<region_id>/referential-integrations")
def propose_integration(region_id):
    principal((ROLE_BUDGET_APPROPRIATIONS_COMMITTEE,))
    get_region(region_id)
    body = payload()
    risk_sharing_model = optional_field(body, "risk_sharing_model", "CAPITATED")
    per_diem_days = require_field(body, "per_diem_days")
    per_diem_rate_cents = require_field(body, "per_diem_rate_cents")
    per_diem_cap_cents = require_field(body, "per_diem_cap_cents")
    basis = require_field(body, "cost_reporting_basis_cents")
    interim_claim_count = require_field(body, "interim_claim_count")

    row = new_record(
        region_id=region_id,
        integration_type=require_field(body, "integration_type"),
        risk_sharing_model=risk_sharing_model,
        bound_effective_date=require_field(body, "bound_effective_date"),
        cost_reporting_basis_cents=basis,
        shared_savings_rate=optional_field(body, "shared_savings_rate", 0.0),
        per_diem_days=per_diem_days,
        per_diem_rate_cents=per_diem_rate_cents,
        per_diem_cap_cents=per_diem_cap_cents,
        interim_claim_count=interim_claim_count,
        settlement_account_cents=settlement_account_cents(
            per_diem_days, per_diem_rate_cents, per_diem_cap_cents,
            basis, risk_sharing_model, interim_claim_count),
        settlement_posted_cents=0,
        status="PROPOSED",
    )
    store_row("integrations", row)
    return single_response("integrations", row, 201)


@bp.get("/regions/<region_id>/referential-integrations")
def list_region_integrations(region_id):
    principal((READERS[0],))
    get_region(region_id)
    rows = [i for i in STORE.integrations.values()
            if i.get("region_id") == region_id]
    rows = filter_rows(rows, integration_type=arg("integration_type"),
                       status=arg("status"))
    return list_response("integrations", rows)


@bp.get("/referential-integrations/<integration_id>")
def get_one_integration(integration_id):
    principal((READERS[0],))
    return single_response("integrations", get_integration(integration_id))


@bp.post("/referential-integrations/<integration_id>/bind")
def bind_integration(integration_id):
    principal((ROLE_BUDGET_APPROPRIATIONS_COMMITTEE,))
    integration = get_integration(integration_id)
    if integration.get("status") != "PROPOSED":
        raise_error(ERR_INVALID_STATE)
    region = get_region(integration["region_id"])
    if region_view(region)["posture"] == "FROZEN":
        raise_error(ERR_REGION_POSTURE_FROZEN)

    integration["status"] = "BOUND"
    touch(integration)
    recompute_region_aggregates(integration["region_id"], bump_version=True)
    return single_response("integrations", integration)


@bp.post("/referential-integrations/<integration_id>/enroll")
def enroll_integration(integration_id):
    principal((ROLE_BUDGET_APPROPRIATIONS_COMMITTEE,))
    integration = get_integration(integration_id)
    if integration.get("status") != "BOUND":
        raise_error(ERR_INVALID_STATE)

    region_id = integration["region_id"]
    account = int(integration.get("settlement_account_cents") or 0)
    posted = int(integration.get("settlement_posted_cents") or 0)
    STORE.integration_premium[region_id] = (
        int(STORE.integration_premium.get(region_id, 0) or 0) + posted)
    STORE.integration_outside[region_id] = (
        int(STORE.integration_outside.get(region_id, 0) or 0)
        + (account - posted))

    integration["status"] = "ENROLLED"
    touch(integration)
    recompute_region_aggregates(integration["region_id"], bump_version=True)
    return single_response("integrations", integration)


@bp.post("/referential-integrations/<integration_id>/contract")
def contract_integration(integration_id):
    principal((ROLE_BUDGET_APPROPRIATIONS_COMMITTEE,))
    integration = get_integration(integration_id)
    if integration.get("status") != "ENROLLED":
        raise_error(ERR_INVALID_STATE)

    account = int(integration.get("settlement_account_cents") or 0)
    previously_posted = int(integration.get("settlement_posted_cents") or 0)
    delta = account - previously_posted
    region_id = integration["region_id"]
    STORE.integration_premium[region_id] = (
        int(STORE.integration_premium.get(region_id, 0) or 0) + delta)
    STORE.integration_outside[region_id] = max(
        0, int(STORE.integration_outside.get(region_id, 0) or 0) - delta)

    integration["status"] = "CONTRACTED"
    integration["settlement_posted_cents"] = account
    touch(integration)
    recompute_region_aggregates(integration["region_id"], bump_version=True)
    return single_response("integrations", integration)


@bp.post("/referential-integrations/<integration_id>/terminate")
def terminate_integration(integration_id):
    principal((ROLE_BUDGET_APPROPRIATIONS_COMMITTEE,))
    integration = get_integration(integration_id)
    status = integration.get("status")
    if status not in ("BOUND", "ENROLLED"):
        raise_error(ERR_INVALID_STATE)

    region_id = integration["region_id"]
    if status == "ENROLLED":
        posted = int(integration.get("settlement_posted_cents") or 0)
        account = int(integration.get("settlement_account_cents") or 0)
        STORE.integration_premium[region_id] = max(
            0, int(STORE.integration_premium.get(region_id, 0) or 0) - posted)
        STORE.integration_outside[region_id] = max(
            0, int(STORE.integration_outside.get(region_id, 0) or 0)
            - (account - posted))

    integration["status"] = "TERMINATED"
    touch(integration)
    recompute_region_aggregates(integration["region_id"], bump_version=True)
    return single_response("integrations", integration)


# ------------------------------------------------------------------- Alerts

@bp.get("/regions/<region_id>/alerts")
def list_region_alerts(region_id):
    principal((READERS[0],))
    get_region(region_id)
    rows = [a for a in STORE.alerts.values() if a.get("region_id") == region_id]
    rows = filter_rows(rows, alert_type=arg("alert_type"),
                       severity=arg("severity"), status=arg("status"))
    return list_response("alerts", rows)


@bp.post("/alerts/<alert_id>/acknowledge")
def acknowledge_alert(alert_id):
    principal((ROLE_REGIONAL_FINANCE_OFFICER,))
    alert = get_alert(alert_id)
    alert["status"] = "ACKNOWLEDGED"
    touch(alert)
    recompute_region_aggregates(alert["region_id"], bump_version=True)
    return single_response("alerts", alert)


_ = (effective_credit_rate, integration_basis_component_cents,
     _credit_contribution)