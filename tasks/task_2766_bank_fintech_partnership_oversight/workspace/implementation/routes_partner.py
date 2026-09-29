"""Partner intake, corporate groups, census, launch, and the logical clock."""
from flask import Blueprint, g

import calc
import cascade
import respond
import schema
import serialize
import store
from authz import auth, scope_partner_id, scope_rows
from errors import fail
from util import fmt_iso

bp = Blueprint("partners", __name__)
READ_ROLES = ("ProgramOfficer", "ComplianceOfficer", "RiskCommittee", "InternalAudit",
              "FintechPartner")
BANK_ROLES = ("ProgramOfficer", "ComplianceOfficer", "RiskCommittee", "InternalAudit")


@bp.post("/oversight/partners")
@auth("ProgramOfficer")
def create_partner():
    data = schema.body()
    parent = None
    if data.get("parent_partner_id") is not None:                 # rank 10
        parent = store.must("partners", data["parent_partner_id"])
    legal_name = schema.req_str(data, "legal_name", 1, 120)        # rank 18
    business_model = schema.req_enum(data, "business_model", schema.BUSINESS_MODELS)
    funding_stage = schema.req_enum(data, "funding_stage", schema.FUNDING_STAGES)
    months_runway = schema.req_int(data, "months_runway", 0, 120)
    disclosed = schema.req_decimal(data, "disclosed_complaints_per_10k", 0, 10000)
    account_count = schema.opt_int(data, "end_user_account_count", 0, minimum=0)
    if parent is not None:                                        # rank 20
        seen = set()
        cursor = parent
        while cursor is not None:
            if cursor["id"] in seen:
                fail("ERR_PARTNER_GROUP_CYCLE", "parent chain is cyclic")
            seen.add(cursor["id"])
            cursor = store.get("partners", cursor.get("parent_partner_id"))
    record = cascade.new_partner_record(
        g.user_id, legal_name, parent["id"] if parent else None, business_model,
        funding_stage, months_runway, float(disclosed), account_count)
    store.insert("partners", record)
    cascade.refresh_concentration(record)
    return respond.ok(serialize.partner(record), 201)


@bp.get("/oversight/partners")
@auth(*READ_ROLES)
def list_partners():
    rows = store.rows("partners")
    parent_filter = schema.filter_str("parent_partner_id")
    if parent_filter is not None:
        rows = [r for r in rows if r["parent_partner_id"] == parent_filter]
    status = schema.filter_enum("status", schema.PARTNER_STATUSES)
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    posture = schema.filter_enum("oversight_posture", schema.POSTURES)
    if posture is not None:
        rows = [r for r in rows if r["oversight_posture"] == posture]
    model = schema.filter_enum("business_model", schema.BUSINESS_MODELS)
    if model is not None:
        rows = [r for r in rows if r["business_model"] == model]
    rows = scope_rows(rows, "id")
    return respond.paginate(rows, serialize.partner)


@bp.get("/oversight/partners/<pid>")
@auth(*READ_ROLES)
def read_partner(pid):
    partner = store.must("partners", pid)
    scope_partner_id(partner["id"])
    return respond.ok(serialize.partner(partner))


@bp.get("/oversight/partners/<pid>/oversight-summary")
@auth(*BANK_ROLES)
def oversight_summary(pid):
    partner = store.must("partners", pid)
    numerator, denominator, _members = calc.concentration_parts(partner)
    last_index = None
    for cycle in store.DB["cycles"].values():
        if cycle["status"] == "CLOSED":
            index = int(cycle["cycle_index"])
            if last_index is None or index > last_index:
                last_index = index
    data = {
        "partner_id": partner["id"],
        "oversight_posture": partner["oversight_posture"],
        "capability_tier": partner["capability_tier"],
        "complaint_rate_bps": int(partner["complaint_rate_bps"]),
        "concentration_ratio_pct": calc.concentration_ratio(numerator, denominator),
        "group_root_partner_id": calc.group_root(partner)["id"],
        "group_balance_cents": numerator,
        "bank_total_fbo_balance_cents": denominator,
        "required_reserve_cents": int(partner["required_reserve_cents"]),
        "reserve_shortfall_cents": int(partner["reserve_shortfall_cents"]),
        "consecutive_shortfall_cycles": int(partner["consecutive_shortfall_cycles"]),
        "growth_breach_count": int(partner["growth_breach_count"]),
        "unreconciled_variance_cents": int(partner["unreconciled_variance_cents"]),
        "open_sanctions_alert_count": int(partner["open_sanctions_alert_count"]),
        "systemic_root_cause_code": partner.get("systemic_root_cause_code"),
        "last_closed_cycle_index": last_index,
    }
    return respond.ok(data)


@bp.post("/oversight/partners/<pid>/account-census")
@auth("FintechPartner", "ProgramOfficer")
def account_census(pid):
    partner = store.must("partners", pid)                          # rank 8
    scope_partner_id(partner["id"])                                # rank 12
    data = schema.body()
    count = schema.req_int(data, "end_user_account_count", 0)       # rank 18
    schema.req_dt(data, "as_of_date")
    if partner["status"] in ("DILIGENCE_FAILED", "TERMINATED"):     # rank 32
        fail("ERR_PARTNER_TERMINAL", "partner is terminal")
    partner["end_user_account_count"] = count
    cascade.refresh_complaint_rate(partner)
    cascade.refresh_posture(partner)
    cascade.freeze_custody_if_frozen(partner)
    store.touch(partner)
    return respond.ok(serialize.partner(partner))


@bp.post("/oversight/partners/<pid>/go-live")
@auth("ProgramOfficer")
def go_live(pid):
    partner = store.must("partners", pid)                          # rank 8
    data = schema.body()
    schema.opt_str(data, "attestation_note")                       # rank 18
    if partner["status"] in ("DILIGENCE_FAILED", "TERMINATED"):     # rank 32
        fail("ERR_PARTNER_TERMINAL", "partner is terminal")
    if partner["status"] != "CONTRACTED":                           # rank 39
        fail("ERR_PARTNER_NOT_CONTRACTED", "partner is not CONTRACTED")
    executed = [a for a in store.rows("agreements")
                if a["partner_id"] == partner["id"] and a["status"] == "EXECUTED"]
    accounts = [c for c in store.rows("custody_accounts")
                if c["partner_id"] == partner["id"]]
    active = [c for c in accounts if c["status"] == "ACTIVE"]
    if len(executed) != 1 or len(accounts) != 2 or len(active) != 2:  # rank 40
        fail("ERR_PROGRAM_NOT_READY_FOR_LAUNCH", "program is not ready for launch")
    if int(partner["reserve_shortfall_cents"]) != 0 or \
            partner["oversight_posture"] not in ("OPEN", "HEIGHTENED"):
        fail("ERR_PROGRAM_NOT_READY_FOR_LAUNCH", "reserve or posture blocks launch")
    partner["status"] = "LIVE"
    store.touch(partner)
    return respond.ok(serialize.partner(partner))


@bp.post("/_clock/set_current_utc")
@auth("ProgramOfficer")
def set_clock():
    data = schema.body()
    moment = schema.req_dt(data, "to_iso8601")
    store.set_clock(moment)
    return respond.ok({"current_utc": fmt_iso(moment)})
