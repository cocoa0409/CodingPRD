"""Contract routes: origination, funding, cancellation, chargeback and reads."""

from flask import request

import db
import middleware
import response
import serializers
from errors import ApiError
from routes._common import endpoint, q
from services import calculations as calc
from services import factory, queries, workflows
from util import add_days, add_months, fmt_ts, month_label, parse_ts, whole_calendar_days

CONTRACT_READERS = ["Customer", "Dealer", "FundingAnalyst", "ChannelManager",
                    "ComplianceOfficer", "PlatformAdmin"]


def build_contract(dealer_id, source_channel, package_id=None):
    """The shared origination payload (PRD §3.2, §3.4): contract + site + account."""
    body = middleware.body_or_empty(request)
    middleware.required(body, "customer_id", "equipment_config_code", "credit_score",
                        "contract_term_months", "monthly_monitoring_cents",
                        "premises_address_line", "premises_city", "premises_state_code",
                        "premises_postal_code")
    customer = middleware.require_fk("customers", body.get("customer_id"), "customer_id")
    equipment_config_code = middleware.as_enum(body["equipment_config_code"], "equipment_config_code",
                                               {"BASE", "PREMIUM", "ELITE"})
    credit_score = middleware.as_int(body["credit_score"], "credit_score", 300, 850)
    contract_term_months = middleware.as_int(body["contract_term_months"],
                                             "contract_term_months", 12, 84)
    monthly_monitoring_cents = middleware.as_int(body["monthly_monitoring_cents"],
                                                 "monthly_monitoring_cents", 1, None)
    financed_charge = middleware.as_int(body.get("financed_charge_at_apr_cents", 0) or 0,
                                        "financed_charge_at_apr_cents", 0, None)
    address_line = middleware.as_str(body.get("premises_address_line"), "premises_address_line")
    city = middleware.as_str(body.get("premises_city"), "premises_city")
    state_code = middleware.as_str(body.get("premises_state_code"), "premises_state_code", length=2)
    postal_code = middleware.as_str(body.get("premises_postal_code"), "premises_postal_code")

    scheduled_at = None
    if body.get("installation_scheduled_at") is not None:
        scheduled_at = middleware.as_timestamp(body["installation_scheduled_at"],
                                               "installation_scheduled_at")
    duration = middleware.as_int(body.get("installation_duration_minutes", 180) or 180,
                                 "installation_duration_minutes", 1, None)
    engineer_id = body.get("installation_engineer_id")
    if scheduled_at is not None:
        middleware.required(body, "installation_engineer_id")
        engineer_id = middleware.as_str(engineer_id, "installation_engineer_id")

    contract = factory.make_contract(
        customer["id"], source_channel, equipment_config_code, credit_score,
        contract_term_months, monthly_monitoring_cents,
        dealer_id=dealer_id, dealer_package_id=package_id,
        financed_charge_at_apr_cents=financed_charge,
    )
    site = factory.make_site(contract["id"], address_line, city, state_code, postal_code)
    account = factory.make_monitoring_account(contract["id"], site["id"])
    factory.make_contract_owner(contract["id"], customer["id"])
    if scheduled_at is not None:
        if workflows.engineer_overlap(None, engineer_id, scheduled_at, duration):
            raise ApiError("ERR_SERVICE_WINDOW_OVERLAP")
        factory.make_installation(contract["id"], scheduled_at, engineer_id, duration)
    return contract


def register(app):

    @endpoint(app, "POST", "/alarm-funding/contracts",
              ["ChannelManager", "FundingAnalyst", "Customer"])
    def originate_contract(actor):
        contract = build_contract(None, "DIRECT", None)
        return response.envelope_object(serializers.serialize("contract", contract)), 201

    @endpoint(app, "GET", "/alarm-funding/contracts", CONTRACT_READERS)
    def list_contracts(actor):
        rows = db.state.all("contracts")
        for field in ("customer_id", "dealer_id", "dealer_package_id",
                      "source_channel", "contract_status"):
            value = q(field)
            if value is not None:
                rows = [r for r in rows if r.get(field) == value]
        rows = queries.sorted_by_created(rows)
        limit, offset = response.resolve_pagination(request.args)
        page, total = response.paginate(rows, limit, offset)
        return response.envelope_array(serializers.serialize_many("contract", page), limit, offset, total), 200

    @endpoint(app, "GET", "/alarm-funding/contracts/<id>", CONTRACT_READERS)
    def read_contract(actor, id):
        contract = middleware.resolve("contracts", id)
        return response.envelope_object(serializers.serialize("contract", contract)), 200

    @endpoint(app, "POST", "/alarm-funding/contracts/<id>/fund", ["FundingAnalyst"])
    def fund_contract(actor, id):
        contract = middleware.resolve("contracts", id)
        body = middleware.body_or_empty(request)
        expected = body.get("expected_contract_version")
        if expected is not None and int(expected) != contract.get("version"):
            raise ApiError("ERR_STALE_VERSION")
        if contract.get("contract_status") != "PENDING_VALIDATION":
            raise ApiError("ERR_CONTRACT_NOT_PENDING")
        failure = workflows.first_failing_gate(contract)
        if failure is not None:
            workflows.freeze_contract(contract, failure)
            raise ApiError(failure)
        workflows.activate_contract(contract)
        return response.envelope_object(serializers.serialize("contract", contract)), 200

    @endpoint(app, "POST", "/alarm-funding/contracts/<id>/cancel", ["Customer", "FundingAnalyst"])
    def cancel_contract(actor, id):
        contract = middleware.resolve("contracts", id)
        if contract.get("contract_status") not in ("ACTIVE", "DELINQUENT"):
            raise ApiError("ERR_INVALID_STATE")
        if contract.get("contract_status") == "ACTIVE" and contract.get("dealer_id") is not None:
            active = queries.active_contracts_for_dealer(contract["dealer_id"])
            if len(active) >= calc.DEALER_BACKLOG_THRESHOLD:
                raise ApiError("ERR_INVALID_STATE",
                               "The dealer backlog threshold blocks this cancellation.")
        workflows.cancel_contract(contract)
        return response.envelope_object(serializers.serialize("contract", contract)), 200

    @endpoint(app, "POST", "/alarm-funding/contracts/<id>/chargeback", ["FundingAnalyst"])
    def adjudicate_chargeback(actor, id):
        contract = middleware.resolve("contracts", id)
        dealer = db.state.get("dealers", contract.get("dealer_id"))
        if dealer is not None and contract.get("dealer_id") is None:
            raise ApiError("ERR_CHARGEBACK_WINDOW_CLOSED")
        amount, code = calc.chargeback_decision(contract, dealer, apply=False)
        if code != "CHARGEBACK":
            raise ApiError("ERR_CHARGEBACK_WINDOW_CLOSED")
        calc.chargeback_decision(contract, dealer, apply=True)
        if dealer is not None:
            db.bump(dealer)
        return response.envelope_object(serializers.serialize("contract", contract)), 200

    @endpoint(app, "GET", "/alarm-funding/contracts/<id>/chargeback-preview",
              ["FundingAnalyst", "Dealer", "PlatformAdmin"])
    def chargeback_preview(actor, id):
        contract = middleware.resolve("contracts", id)
        dealer = db.state.get("dealers", contract.get("dealer_id"))
        return response.envelope_object(calc.chargeback_preview(contract, dealer)), 200

    @endpoint(app, "POST", "/alarm-funding/contracts/<id>/reactivate-service",
              ["ServiceCoordinator"])
    def reactivate_service(actor, id):
        contract = middleware.resolve("contracts", id)
        if contract.get("contract_status") != "DELINQUENT":
            raise ApiError("ERR_INVALID_STATE")
        action = queries.open_service_required(contract["id"])
        if action is None:
            raise ApiError("ERR_INVALID_STATE",
                           "No open SERVICE_REQUIRED reduction action exists for this account.")
        action["action_status"] = "RESOLVED"
        action["resolved_at"] = fmt_ts(db.now())
        db.bump(action)
        account = queries.account_for_contract(contract["id"])
        if account is not None:
            account["provision_state"] = "PROVISIONED"
            db.bump(account)
        contract["contract_status"] = "ACTIVE"
        db.bump(contract)
        return response.envelope_object(serializers.serialize("contract", contract)), 200

    @endpoint(app, "GET", "/alarm-funding/contracts/<id>/false-alarm-ratio",
              ["MonitoringOperator", "ServiceCoordinator", "PlatformAdmin"])
    def contract_false_alarm_ratio(actor, id):
        contract = middleware.resolve("contracts", id)
        account = queries.account_for_contract(contract["id"])
        if account is None:
            raise ApiError("ERR_MONITORING_ACCOUNT_NOT_FOUND")
        return response.envelope_object(calc.false_alarm_ratio(account)), 200

    @endpoint(app, "GET", "/alarm-funding/contracts/<id>/sites",
              ["Customer", "FundingAnalyst", "ServiceCoordinator", "PlatformAdmin"])
    def contract_sites(actor, id):
        middleware.resolve("contracts", id)
        rows = queries.sorted_by_created(queries.sites_for_contract(id))
        limit, offset = response.resolve_pagination(request.args)
        page, total = response.paginate(rows, limit, offset)
        return response.envelope_array(serializers.serialize_many("site", page), limit, offset, total), 200

    @endpoint(app, "GET", "/alarm-funding/contracts/<id>/attrition-flags",
              ["FundingAnalyst", "ChannelManager", "PlatformAdmin"])
    def contract_attrition_flags(actor, id):
        middleware.resolve("contracts", id)
        rows = [f for f in db.state.attrition_flags.values() if f.get("contract_id") == id]
        rows = queries.sorted_by_created(rows)
        limit, offset = response.resolve_pagination(request.args)
        page, total = response.paginate(rows, limit, offset)
        return response.envelope_array(serializers.serialize_many("attrition_flag", page), limit, offset, total), 200

    @endpoint(app, "GET", "/alarm-funding/contracts/<id>/owners",
              ["Customer", "FundingAnalyst", "ComplianceOfficer", "PlatformAdmin"])
    def contract_owners(actor, id):
        middleware.resolve("contracts", id)
        rows = queries.owners_for_contract(id)
        rows.sort(key=lambda r: r.get("started_at") or "", reverse=True)
        limit, offset = response.resolve_pagination(request.args)
        page, total = response.paginate(rows, limit, offset)
        return response.envelope_array(serializers.serialize_many("contract_owner", page), limit, offset, total), 200

    @endpoint(app, "GET", "/alarm-funding/contracts/<id>/delinquency", CONTRACT_READERS)
    def contract_delinquency(actor, id):
        contract = middleware.resolve("contracts", id)
        days = 0
        if contract.get("contract_status") == "DELINQUENT":
            days = whole_calendar_days(parse_ts(contract.get("attrition_checked_at")), db.now())
        return response.envelope_object({
            "contract_id": contract["id"],
            "delinquency_days": days,
        }), 200