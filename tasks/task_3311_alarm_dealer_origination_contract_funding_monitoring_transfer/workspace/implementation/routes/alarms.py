"""Alarm event, dispatch request, reduction action and legal-hold routes."""

from datetime import timedelta

from flask import request

import db
import middleware
import response
import serializers
from errors import ApiError
from routes._common import endpoint, q
from services import calculations as calc
from services import factory, queries, workflows
from util import add_days, coerce_dt, fmt_ts, month_label, parse_ts

ALARM_READERS = ["MonitoringOperator", "ServiceCoordinator", "PlatformAdmin"]


def register(app):

    # --- Alarm events -----------------------------------------------------

    @endpoint(app, "POST", "/alarm-funding/alarm-events", ["MonitoringOperator"])
    def create_alarm(actor):
        body = middleware.body_or_empty(request)
        middleware.required(body, "monitoring_account_id", "signal_source", "occurred_at")
        account = middleware.require_fk("monitoring_accounts", body.get("monitoring_account_id"),
                                        "monitoring_account_id")
        signal_source = middleware.as_str(body["signal_source"], "signal_source")
        occurred_at = middleware.as_timestamp(body["occurred_at"], "occurred_at")
        entered_at = body.get("entered_at_utc")
        if entered_at is not None:
            entered_at = middleware.as_timestamp(entered_at, "entered_at_utc")
        else:
            entered_at = occurred_at
        alarm = factory.make_alarm_event(account["id"], signal_source, occurred_at, entered_at)
        window_start = db.now() - timedelta(days=calc.TRAILING_WINDOW_DAYS)
        if window_start <= occurred_at <= db.now():
            alarm["counted_for_window_total"] = True
        return response.envelope_object(serializers.serialize("alarm_event", alarm)), 201

    @endpoint(app, "GET", "/alarm-funding/alarm-events", ALARM_READERS)
    def list_alarms(actor):
        rows = db.state.all("alarm_events")
        for field in ("monitoring_account_id", "verification_outcome"):
            value = q(field)
            if value is not None:
                rows = [r for r in rows if r.get(field) == value]
        rows = queries.sorted_by_created(rows)
        limit, offset = response.resolve_pagination(request.args)
        page, total = response.paginate(rows, limit, offset)
        return response.envelope_array(serializers.serialize_many("alarm_event", page), limit, offset, total), 200

    @endpoint(app, "GET", "/alarm-funding/alarm-events/<id>", ALARM_READERS)
    def read_alarm(actor, id):
        alarm = middleware.resolve("alarm_events", id)
        return response.envelope_object(serializers.serialize("alarm_event", alarm)), 200

    @endpoint(app, "POST", "/alarm-funding/alarm-events/<id>/verification", ["MonitoringOperator"])
    def record_alarm_verification(actor, id):
        alarm = middleware.resolve("alarm_events", id)
        body = middleware.body_or_empty(request)
        middleware.required(body, "outcome")
        outcome = middleware.as_enum(body["outcome"], "outcome", {"VERIFIED", "FALSE_ALARM"})
        if alarm.get("verification_outcome") != "PENDING":
            raise ApiError("ERR_ALARM_ALREADY_VERIFIED")
        if not workflows.within_verified_window(alarm):
            raise ApiError("ERR_ALARM_OUTSIDE_VERIFIED_WINDOW")
        workflows.record_verification(alarm, outcome)
        account = db.state.get("monitoring_accounts", alarm["monitoring_account_id"])
        workflows.maybe_raise_reduction_action(account)
        return response.envelope_object(serializers.serialize("alarm_event", alarm)), 200

    @endpoint(app, "POST", "/alarm-funding/alarm-events/<id>/legal-hold", ["ComplianceOfficer"])
    def legal_hold(actor, id):
        alarm = middleware.resolve("alarm_events", id)
        if alarm.get("verification_outcome") not in ("VERIFIED", "FALSE_ALARM"):
            raise ApiError("ERR_INVALID_STATE")
        alarm["counted_for_false_alarm"] = False
        alarm["legal_hold"] = True
        db.bump(alarm)
        return response.envelope_object(serializers.serialize("alarm_event", alarm)), 200

    @endpoint(app, "POST", "/alarm-funding/alarm-events/<id>/legal-hold-release",
              ["ComplianceOfficer"])
    def legal_hold_release(actor, id):
        alarm = middleware.resolve("alarm_events", id)
        if alarm.get("verification_outcome") not in ("VERIFIED", "FALSE_ALARM"):
            raise ApiError("ERR_INVALID_STATE")
        if alarm.get("verification_outcome") == "VERIFIED" and alarm.get("counted_for_window_total"):
            alarm["counted_for_false_alarm"] = True
        alarm["legal_hold"] = False
        db.bump(alarm)
        return response.envelope_object(serializers.serialize("alarm_event", alarm)), 200

    # --- Dispatch ---------------------------------------------------------

    @endpoint(app, "POST", "/alarm-funding/dispatch-requests", ["MonitoringOperator"])
    def create_dispatch(actor):
        body = middleware.body_or_empty(request)
        middleware.required(body, "alarm_event_id")
        alarm = middleware.require_fk("alarm_events", body.get("alarm_event_id"), "alarm_event_id")
        account_id = body.get("monitoring_account_id")
        if account_id is not None and account_id != alarm.get("monitoring_account_id"):
            raise ApiError("ERR_ALARM_NOT_FOR_ACCOUNT")
        if alarm.get("verification_outcome") != "PENDING":
            raise ApiError("ERR_ALARM_ALREADY_VERIFIED")
        workflows.record_verification(alarm, "VERIFIED")
        dispatch = factory.make_dispatch_request(alarm["id"])
        return response.envelope_object(serializers.serialize("dispatch_request", dispatch)), 201

    @endpoint(app, "GET", "/alarm-funding/dispatch-requests", ALARM_READERS)
    def list_dispatches(actor):
        rows = db.state.all("dispatch_requests")
        for field in ("alarm_event_id", "dispatch_status"):
            value = q(field)
            if value is not None:
                rows = [r for r in rows if r.get(field) == value]
        rows = queries.sorted_by_created(rows)
        limit, offset = response.resolve_pagination(request.args)
        page, total = response.paginate(rows, limit, offset)
        return response.envelope_array(serializers.serialize_many("dispatch_request", page), limit, offset, total), 200

    @endpoint(app, "GET", "/alarm-funding/dispatch-requests/<id>", ALARM_READERS)
    def read_dispatch(actor, id):
        dispatch = middleware.resolve("dispatch_requests", id)
        return response.envelope_object(serializers.serialize("dispatch_request", dispatch)), 200

    @endpoint(app, "POST", "/alarm-funding/dispatch-requests/<id>/dispatch", ["MonitoringOperator"])
    def release_dispatch(actor, id):
        dispatch = middleware.resolve("dispatch_requests", id)
        if dispatch.get("dispatch_status") != "REQUESTED":
            raise ApiError("ERR_DISPATCH_NOT_REQUESTED")
        alarm = db.state.get("alarm_events", dispatch["alarm_event_id"])
        account = db.state.get("monitoring_accounts", alarm.get("monitoring_account_id")) if alarm else None
        if account is None or account.get("provision_state") != "PROVISIONED":
            raise ApiError("ERR_INVALID_STATE",
                           "The monitoring account must be PROVISIONED to release a dispatch.")
        dispatch["dispatch_status"] = "DISPATCHED"
        dispatch["dispatched_at"] = fmt_ts(db.now())
        db.bump(dispatch)
        return response.envelope_object(serializers.serialize("dispatch_request", dispatch)), 200

    @endpoint(app, "POST", "/alarm-funding/dispatch-requests/<id>/abort", ["MonitoringOperator"])
    def abort_dispatch(actor, id):
        dispatch = middleware.resolve("dispatch_requests", id)
        status = dispatch.get("dispatch_status")
        if status not in ("REQUESTED", "DISPATCHED"):
            raise ApiError("ERR_DISPATCH_NOT_REQUESTED")
        body = middleware.body_or_empty(request)
        reason = body.get("abort_reason", "")
        alarm = db.state.get("alarm_events", dispatch["alarm_event_id"])
        if status == "DISPATCHED":
            if alarm is None or not workflows.within_abort_window(alarm):
                raise ApiError("ERR_ALARM_OUTSIDE_VERIFIED_WINDOW")
        # The mass-cancel guard counts a CLOSED request exactly like an ABORTED dispatch.
        if workflows.mass_cancel_count(alarm) >= calc.MASS_CANCEL_LIMIT:
            raise ApiError("ERR_MASS_CANCEL_BLOCKED")
        dispatch["abort_reason"] = reason if reason is not None else ""
        dispatch["dispatch_status"] = "ABORTED" if status == "DISPATCHED" else "CLOSED"
        db.bump(dispatch)
        return response.envelope_object(serializers.serialize("dispatch_request", dispatch)), 200

    @endpoint(app, "POST", "/alarm-funding/dispatch-requests/<id>/complete", ["MonitoringOperator"])
    def complete_dispatch(actor, id):
        dispatch = middleware.resolve("dispatch_requests", id)
        if dispatch.get("dispatch_status") != "DISPATCHED":
            raise ApiError("ERR_DISPATCH_NOT_REQUESTED")
        dispatch["dispatch_status"] = "COMPLETED"
        db.bump(dispatch)
        return response.envelope_object(serializers.serialize("dispatch_request", dispatch)), 200

    # --- Reduction actions ------------------------------------------------

    @endpoint(app, "POST", "/alarm-funding/alarm-reduction-actions",
              ["ServiceCoordinator", "MonitoringOperator"])
    def create_reduction_action(actor):
        body = middleware.body_or_empty(request)
        middleware.required(body, "monitoring_account_id", "action_type")
        account = middleware.require_fk("monitoring_accounts", body.get("monitoring_account_id"),
                                        "monitoring_account_id")
        action_type = middleware.as_enum(body["action_type"], "action_type",
                                         {"WATCH", "TRAINING_REQUIRED", "SERVICE_REQUIRED"})
        action = factory.make_reduction_action(account["id"], action_type)
        return response.envelope_object(serializers.serialize("alarm_reduction_action", action)), 201

    @endpoint(app, "GET", "/alarm-funding/alarm-reduction-actions", ALARM_READERS)
    def list_reduction_actions(actor):
        rows = db.state.all("alarm_reduction_actions")
        for field in ("monitoring_account_id", "action_type", "action_status"):
            value = q(field)
            if value is not None:
                rows = [r for r in rows if r.get(field) == value]
        rows = queries.sorted_by_created(rows)
        limit, offset = response.resolve_pagination(request.args)
        page, total = response.paginate(rows, limit, offset)
        return response.envelope_array(serializers.serialize_many("alarm_reduction_action", page), limit, offset, total), 200

    @endpoint(app, "GET", "/alarm-funding/alarm-reduction-actions/<id>", ALARM_READERS)
    def read_reduction_action(actor, id):
        action = middleware.resolve("alarm_reduction_actions", id)
        return response.envelope_object(serializers.serialize("alarm_reduction_action", action)), 200