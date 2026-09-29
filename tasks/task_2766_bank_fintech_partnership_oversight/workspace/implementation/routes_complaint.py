"""Consumer complaints and transaction monitoring alerts."""
from flask import Blueprint, g

import calc
import cascade
import respond
import schema
import serialize
import store
from authz import auth, scope_partner_id, scope_rows
from errors import fail

bp = Blueprint("complaint", __name__)
READ_ROLES = ("ProgramOfficer", "ComplianceOfficer", "RiskCommittee", "InternalAudit",
              "FintechPartner")


# --------------------------------------------------------------------------- #
# Complaints
# --------------------------------------------------------------------------- #
@bp.post("/oversight/complaints")
@auth("ProgramOfficer", "ComplianceOfficer", "FintechPartner")
def create_complaint():
    data = schema.body()
    partner = None
    if data.get("partner_id") is not None:                           # rank 10
        partner = store.must("partners", data["partner_id"])
    if partner is not None:                                          # rank 12
        scope_partner_id(partner["id"])
    schema.req_str(data, "partner_id")                               # rank 18
    channel = schema.req_enum(data, "channel", schema.COMPLAINT_CHANNELS)
    category = schema.req_enum(data, "category", schema.COMPLAINT_CATEGORIES)
    severity = schema.req_enum(data, "severity", schema.SEVERITIES)
    received_at = schema.req_dt(data, "received_at")
    narrative = schema.req_str(data, "narrative", 1, 2000)
    is_reg_e = schema.req_bool(data, "is_reg_e_dispute", False)
    if partner["status"] in ("DILIGENCE_FAILED", "TERMINATED"):       # rank 32
        fail("ERR_PARTNER_TERMINAL", "partner is terminal")
    if received_at > store.clock():                                  # rank 66
        fail("ERR_TIMESTAMP_IN_FUTURE", "received_at is later than the logical clock")
    handling_owner = "BANK"
    for agreement in store.rows("agreements"):
        if agreement["partner_id"] == partner["id"] and agreement["status"] == "EXECUTED":
            handling_owner = agreement["dispute_owner"]
            break
    record = {
        "partner_id": partner["id"],
        "channel": channel,
        "category": category,
        "severity": severity,
        "received_at": received_at,
        "narrative": narrative,
        "is_reg_e_dispute": is_reg_e,
        "handling_owner": handling_owner,
        "response_due_at": calc.complaint_response_due_at(channel, received_at),
        "status": "RECEIVED",
        "root_cause_code": None,
        "escalation_count": 0,
        "redress_cents": 0,
        "resolved_at": None,
    }
    store.insert("complaints", record)
    partner["total_complaint_count"] = int(partner["total_complaint_count"]) + 1
    partner["open_complaint_count"] = int(partner["open_complaint_count"]) + 1
    cascade.refresh_complaint_rate(partner)
    cascade.refresh_posture(partner)
    cascade.freeze_custody_if_frozen(partner)
    store.touch(partner)
    return respond.ok(serialize.complaint(record), 201)


@bp.get("/oversight/complaints")
@auth(*READ_ROLES)
def list_complaints():
    rows = store.rows("complaints")
    partner_id = schema.filter_str("partner_id")
    if partner_id is not None:
        rows = [r for r in rows if r["partner_id"] == partner_id]
    channel = schema.filter_enum("channel", schema.COMPLAINT_CHANNELS)
    if channel is not None:
        rows = [r for r in rows if r["channel"] == channel]
    status = schema.filter_enum("status", schema.COMPLAINT_STATUSES)
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    root_cause = schema.filter_enum("root_cause_code", schema.ROOT_CAUSE_CODES)
    if root_cause is not None:
        rows = [r for r in rows if r["root_cause_code"] == root_cause]
    severity = schema.filter_enum("severity", schema.SEVERITIES)
    if severity is not None:
        rows = [r for r in rows if r["severity"] == severity]
    return respond.paginate(scope_rows(rows), serialize.complaint)


@bp.get("/oversight/complaints/<cid>")
@auth(*READ_ROLES)
def read_complaint(cid):
    record = store.must("complaints", cid)
    scope_partner_id(record["partner_id"])
    return respond.ok(serialize.complaint(record))


@bp.post("/oversight/complaints/<cid>/assign-root-cause")
@auth("ComplianceOfficer")
def assign_root_cause(cid):
    record = store.must("complaints", cid)                           # rank 8
    data = schema.body()
    code = schema.req_enum(data, "root_cause_code", schema.ROOT_CAUSE_CODES)  # rank 18
    schema.req_str(data, "investigation_note", 1)
    if record["status"] not in ("RECEIVED", "ESCALATED"):             # rank 34
        fail("ERR_COMPLAINT_NOT_DISPOSABLE", "complaint is not in an assignable state")
    partner = store.get("partners", record["partner_id"])
    source = record["status"]
    record["root_cause_code"] = code
    record["status"] = "ROOT_CAUSE_ASSIGNED"
    store.touch(record)
    if source == "ESCALATED":
        partner["escalated_complaint_count"] = \
            int(partner["escalated_complaint_count"]) - 1
        partner["open_complaint_count"] = int(partner["open_complaint_count"]) + 1
        cascade.refresh_complaint_rate(partner)
        cascade.refresh_posture(partner)
        cascade.freeze_custody_if_frozen(partner)
        store.touch(partner)
    return respond.ok(serialize.complaint(record))


@bp.post("/oversight/complaints/<cid>/disposition")
@auth("ComplianceOfficer")
def disposition_complaint(cid):
    record = store.must("complaints", cid)                           # rank 8
    data = schema.body()
    outcome = schema.req_enum(data, "outcome",                       # rank 18
                              ("RESOLVED", "ESCALATED", "WITHDRAWN"))
    schema.opt_str(data, "resolution_note", None)
    redress = schema.opt_int(data, "redress_cents", 0, 0)
    legal = {"RESOLVED": ("ROOT_CAUSE_ASSIGNED", "ESCALATED"),
             "ESCALATED": ("ROOT_CAUSE_ASSIGNED",),
             "WITHDRAWN": ("RECEIVED",)}[outcome]
    if record["status"] not in legal:                                # rank 34
        fail("ERR_COMPLAINT_NOT_DISPOSABLE", "complaint is not in a disposable state")
    if outcome == "RESOLVED" and record["root_cause_code"] is None:   # rank 58
        fail("ERR_ROOT_CAUSE_REQUIRED", "a root cause must be assigned before resolving")
    partner = store.get("partners", record["partner_id"])
    source = record["status"]
    if outcome == "RESOLVED":
        record["resolved_at"] = store.clock()
        record["redress_cents"] = redress
        record["status"] = "RESOLVED"
        if source == "ROOT_CAUSE_ASSIGNED":
            partner["open_complaint_count"] = int(partner["open_complaint_count"]) - 1
        else:
            partner["escalated_complaint_count"] = \
                int(partner["escalated_complaint_count"]) - 1
        partner["resolved_complaint_count"] = int(partner["resolved_complaint_count"]) + 1
    elif outcome == "ESCALATED":
        record["escalation_count"] = int(record["escalation_count"]) + 1
        record["status"] = "ESCALATED"
        partner["open_complaint_count"] = int(partner["open_complaint_count"]) - 1
        partner["escalated_complaint_count"] = \
            int(partner["escalated_complaint_count"]) + 1
    else:
        record["resolved_at"] = store.clock()
        record["status"] = "WITHDRAWN"
        partner["open_complaint_count"] = int(partner["open_complaint_count"]) - 1
        partner["withdrawn_complaint_count"] = \
            int(partner["withdrawn_complaint_count"]) + 1
    store.touch(record)
    cascade.refresh_complaint_rate(partner)
    cascade.refresh_posture(partner)
    cascade.freeze_custody_if_frozen(partner)
    store.touch(partner)
    return respond.ok(serialize.complaint(record))


# --------------------------------------------------------------------------- #
# Transaction monitoring alerts
# --------------------------------------------------------------------------- #
CLOSING_DISPOSITIONS = ("CLEARED", "SAR_FILED")


@bp.post("/oversight/alerts")
@auth("ComplianceOfficer")
def create_alert():
    data = schema.body()
    partner = None
    if data.get("partner_id") is not None:                           # rank 10
        partner = store.must("partners", data["partner_id"])
    schema.req_str(data, "partner_id")                               # rank 18
    alert_type = schema.req_enum(data, "alert_type", schema.ALERT_TYPES)
    triggered_at = schema.req_dt(data, "triggered_at")
    volume = schema.req_int(data, "transaction_volume_cents", 1)
    note = schema.req_str(data, "detection_note", 1, 1000)
    if partner["status"] in ("DILIGENCE_FAILED", "TERMINATED"):       # rank 32
        fail("ERR_PARTNER_TERMINAL", "partner is terminal")
    if triggered_at > store.clock():                                 # rank 66
        fail("ERR_TIMESTAMP_IN_FUTURE", "triggered_at is later than the logical clock")
    record = {
        "partner_id": partner["id"],
        "alert_type": alert_type,
        "triggered_at": triggered_at,
        "transaction_volume_cents": volume,
        "detection_note": note,
        "sla_due_at": calc.alert_sla_due_at(alert_type, triggered_at),
        "disposition": "OPEN",
        "sla_breach_count": 0,
        "disposed_by_user_id": None,
    }
    store.insert("alerts", record)
    if alert_type == "SANCTIONS_HIT":
        cascade.refresh_open_sanctions(partner)
        cascade.refresh_posture(partner)
        cascade.freeze_custody_if_frozen(partner)
        store.touch(partner)
    return respond.ok(serialize.alert(record), 201)


@bp.get("/oversight/alerts")
@auth(*READ_ROLES)
def list_alerts():
    rows = store.rows("alerts")
    partner_id = schema.filter_str("partner_id")
    if partner_id is not None:
        rows = [r for r in rows if r["partner_id"] == partner_id]
    alert_type = schema.filter_enum("alert_type", schema.ALERT_TYPES)
    if alert_type is not None:
        rows = [r for r in rows if r["alert_type"] == alert_type]
    disposition = schema.filter_enum("disposition", schema.ALERT_DISPOSITIONS)
    if disposition is not None:
        rows = [r for r in rows if r["disposition"] == disposition]
    return respond.paginate(scope_rows(rows), serialize.alert)


@bp.get("/oversight/alerts/<aid>")
@auth(*READ_ROLES)
def read_alert(aid):
    record = store.must("alerts", aid)
    scope_partner_id(record["partner_id"])
    return respond.ok(serialize.alert(record))


@bp.post("/oversight/alerts/<aid>/dispose")
@auth("ComplianceOfficer")
def dispose_alert(aid):
    record = store.must("alerts", aid)                               # rank 8
    data = schema.body()
    disposition = schema.req_enum(data, "disposition",               # rank 18
                                  ("PARTNER_RESPONSE_PENDING",) + CLOSING_DISPOSITIONS)
    min_len = 20 if disposition in CLOSING_DISPOSITIONS else 1
    schema.req_str(data, "disposition_note", min_len)
    legal = ("OPEN",) if disposition == "PARTNER_RESPONSE_PENDING" \
        else ("OPEN", "PARTNER_RESPONSE_PENDING")
    if record["disposition"] not in legal:                           # rank 34
        fail("ERR_ALERT_TERMINAL", "alert is not in a disposable state")
    record["disposition"] = disposition
    record["disposed_by_user_id"] = g.user_id
    store.touch(record)
    if record["alert_type"] == "SANCTIONS_HIT" and disposition in CLOSING_DISPOSITIONS:
        partner = store.get("partners", record["partner_id"])
        cascade.refresh_open_sanctions(partner)
        cascade.refresh_posture(partner)
        store.touch(partner)
    return respond.ok(serialize.alert(record))
