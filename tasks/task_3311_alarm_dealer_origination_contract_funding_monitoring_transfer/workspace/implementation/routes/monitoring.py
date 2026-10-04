"""Installation, monitoring-account and monitoring-transfer routes."""

from flask import request

import db
import middleware
import response
import serializers
from errors import ApiError
from routes._common import endpoint, q
from services import calculations as calc
from services import factory, queries, workflows
from util import fmt_ts

INSTALL_READERS = ["ServiceCoordinator", "FundingAnalyst", "PlatformAdmin"]
ACCOUNT_READERS = ["MonitoringOperator", "ServiceCoordinator", "FundingAnalyst", "PlatformAdmin"]


def register(app):

    # --- Installations ----------------------------------------------------

    @endpoint(app, "POST", "/alarm-funding/installations", ["ServiceCoordinator"])
    def create_installation(actor):
        body = middleware.body_or_empty(request)
        middleware.required(body, "contract_id", "scheduled_at", "installation_engineer_id")
        contract = middleware.require_fk("contracts", body.get("contract_id"), "contract_id")
        scheduled_at = middleware.as_timestamp(body["scheduled_at"], "scheduled_at")
        engineer_id = middleware.as_str(body["installation_engineer_id"], "installation_engineer_id")
        duration = middleware.as_int(body.get("duration_minutes", 180) or 180,
                                     "duration_minutes", 1, None)
        if workflows.engineer_overlap(None, engineer_id, scheduled_at, duration):
            raise ApiError("ERR_SERVICE_WINDOW_OVERLAP")
        installation = factory.make_installation(contract["id"], scheduled_at,
                                                 engineer_id, duration)
        return response.envelope_object(serializers.serialize("installation", installation)), 201

    @endpoint(app, "GET", "/alarm-funding/installations", INSTALL_READERS)
    def list_installations(actor):
        rows = db.state.all("installations")
        for field in ("contract_id", "installation_engineer_id", "install_status"):
            value = q(field)
            if value is not None:
                rows = [r for r in rows if r.get(field) == value]
        rows = queries.sorted_by_created(rows)
        limit, offset = response.resolve_pagination(request.args)
        page, total = response.paginate(rows, limit, offset)
        return response.envelope_array(serializers.serialize_many("installation", page), limit, offset, total), 200

    @endpoint(app, "GET", "/alarm-funding/installations/<id>", INSTALL_READERS)
    def read_installation(actor, id):
        installation = middleware.resolve("installations", id)
        return response.envelope_object(serializers.serialize("installation", installation)), 200

    @endpoint(app, "POST", "/alarm-funding/installations/<id>/complete", ["ServiceCoordinator"])
    def complete_installation(actor, id):
        installation = middleware.resolve("installations", id)
        if installation.get("install_status") != "SCHEDULED":
            raise ApiError("ERR_INVALID_STATE")
        contract = middleware.resolve("contracts", installation["contract_id"])
        account = queries.account_for_contract(contract["id"])
        committed = installation.get("activation_committed") or (
            account is not None and account.get("activation_gate_met"))
        if not committed:
            raise ApiError("ERR_INVALID_STATE",
                           "The monitoring transfer must be committed before completion.")
        calc.equipment_financing_split(contract, persist_equipment=True)
        contract["equipment_financing_disclosed"] = False
        installation["install_status"] = "COMPLETED"
        installation["equipment_config_code"] = contract.get("equipment_config_code")
        db.bump(installation)
        db.bump(contract)

        split = calc.equipment_financing_split(contract, persist_equipment=False)
        contract["equipment_financing_disclosed"] = True
        contract["disclosure_financed_payment_cents"] = split["equipment_payment_cents"]
        contract["disclosure_total_of_payments_cents"] = split["total_of_payments_cents"]
        contract["disclosure_equipment_financed_cents"] = contract.get("equipment_financed_cents", 0)
        contract["disclosure_monthly_monitoring_cents"] = contract.get("monthly_monitoring_cents", 0)
        return response.envelope_object(serializers.serialize("installation", installation)), 200

    @endpoint(app, "POST", "/alarm-funding/installations/<id>/mark-failed", ["ServiceCoordinator"])
    def mark_failed(actor, id):
        installation = middleware.resolve("installations", id)
        if installation.get("install_status") != "SCHEDULED":
            raise ApiError("ERR_INVALID_STATE")
        body = middleware.body_or_empty(request)
        installation["reason"] = body.get("reason")
        if installation.get("activation_committed"):
            # Requeue: the status stays SCHEDULED and only the installation version moves.
            db.bump(installation)
            return response.envelope_object(serializers.serialize("installation", installation)), 200
        installation["install_status"] = "FAILED"
        db.bump(installation)
        contract = db.state.get("contracts", installation["contract_id"])
        if contract is not None:
            db.bump(contract)
        return response.envelope_object(serializers.serialize("installation", installation)), 200

    @endpoint(app, "POST", "/alarm-funding/installations/<id>/waiver",
              ["ServiceCoordinator", "ComplianceOfficer"])
    def request_waiver(actor, id):
        installation = middleware.resolve("installations", id)
        if installation.get("install_status") not in ("SCHEDULED", "FAILED", "COMPLETED"):
            raise ApiError("ERR_INVALID_STATE")
        body = middleware.body_or_empty(request)
        middleware.required(body, "requested_by", "onsite_install")
        requested_by = middleware.as_str(body["requested_by"], "requested_by")
        onsite_install = body["onsite_install"]
        if not isinstance(onsite_install, bool):
            raise ApiError("ERR_INVALID_REQUEST", "onsite_install must be a boolean.")
        installation["waiver_requested_by"] = requested_by
        installation["waiver_onsite_install"] = onsite_install
        installation["waiver_approved"] = bool(onsite_install)
        contract = db.state.get("contracts", installation["contract_id"])
        if onsite_install and contract is not None:
            contract["chargeback_exempt"] = True
            db.bump(contract)
        db.bump(installation)
        return response.envelope_object(serializers.serialize("installation", installation)), 200

    # --- Monitoring accounts ---------------------------------------------

    @endpoint(app, "GET", "/alarm-funding/monitoring-accounts", ACCOUNT_READERS)
    def list_accounts(actor):
        rows = db.state.all("monitoring_accounts")
        for field in ("contract_id", "provision_state"):
            value = q(field)
            if value is not None:
                rows = [r for r in rows if r.get(field) == value]
        rows = queries.sorted_by_created(rows)
        limit, offset = response.resolve_pagination(request.args)
        page, total = response.paginate(rows, limit, offset)
        return response.envelope_array(serializers.serialize_many("monitoring_account", page), limit, offset, total), 200

    @endpoint(app, "GET", "/alarm-funding/monitoring-accounts/<id>", ACCOUNT_READERS)
    def read_account(actor, id):
        account = middleware.resolve("monitoring_accounts", id)
        return response.envelope_object(serializers.serialize("monitoring_account", account)), 200

    @endpoint(app, "GET", "/alarm-funding/monitoring-accounts/<id>/false-alarm-ratio",
              ["MonitoringOperator", "ServiceCoordinator", "PlatformAdmin"])
    def account_false_alarm_ratio(actor, id):
        account = middleware.resolve("monitoring_accounts", id)
        return response.envelope_object(calc.false_alarm_ratio(account)), 200

    @endpoint(app, "POST", "/alarm-funding/monitoring-transfers/<id>/trigger",
              ["MonitoringOperator"])
    def trigger_transfer(actor, id):
        account = middleware.resolve("monitoring_accounts", id)
        contract = middleware.resolve("contracts", account["contract_id"])
        site = queries.current_site_for_contract(contract["id"])
        if site is None:
            raise ApiError("ERR_INVALID_STATE",
                           "The monitoring account has no site on file.")
        if account.get("provision_state") != "UNPROVISIONED":
            raise ApiError("ERR_INVALID_STATE")
        account_number = "MA-%06d" % (len(db.state.monitoring_accounts) + 1000)
        for other in db.state.monitoring_accounts.values():
            if other.get("monitoring_account_number") == account_number and other["id"] != account["id"]:
                raise ApiError("ERR_NATURAL_KEY_DUPLICATE")
        account["provision_state"] = "PROVISIONED"
        account["activation_gate_met"] = True
        account["monitoring_account_number"] = account_number
        account["central_station_host"] = "cs-%s.example.net" % (
            (contract.get("contract_number") or contract["id"])[:12])
        db.bump(account)
        # The commit is what makes an installation's completion safe.
        for installation in db.state.installations.values():
            if installation.get("contract_id") == contract["id"] \
                    and installation.get("install_status") == "SCHEDULED":
                installation["activation_committed"] = True
        return response.envelope_object(serializers.serialize("monitoring_account", account)), 200