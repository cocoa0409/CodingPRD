"""Program agreements: drafting, risk approval, custody creation and termination."""
from flask import Blueprint, g

import cascade
import respond
import schema
import serialize
import store
from authz import auth, scope_partner_id, scope_rows, sod
from errors import fail

bp = Blueprint("agreements", __name__)
READ_ROLES = ("ProgramOfficer", "ComplianceOfficer", "RiskCommittee", "InternalAudit",
              "FintechPartner")


@bp.post("/oversight/agreements")
@auth("ProgramOfficer")
def create_agreement():
    data = schema.body()
    partner = None
    if data.get("partner_id") is not None:                           # rank 10
        partner = store.must("partners", data["partner_id"])
    schema.req_str(data, "partner_id")                               # rank 18
    kyc = schema.req_enum(data, "kyc_owner", schema.OWNERS)
    dispute = schema.req_enum(data, "dispute_owner", schema.OWNERS)
    marketing = schema.req_enum(data, "marketing_owner", schema.OWNERS)
    rights = schema.req_enum(data, "oversight_rights_level", schema.OVERSIGHT_RIGHTS)
    notice = schema.req_int(data, "audit_access_notice_days", 1, 30)
    triggers = schema.req_enum_array(data, "termination_triggers",
                                     schema.TERMINATION_TRIGGERS, non_empty=True)
    growth_cap = schema.req_decimal(data, "monthly_growth_cap_pct", exclusive_min=0,
                                    maximum="500.00")
    conc_cap = schema.req_decimal(data, "concentration_cap_pct", exclusive_min=0,
                                  maximum="100.00")
    max_balance = schema.req_int(data, "max_end_user_balance_cents", 1)
    reserve_bps = schema.req_int(data, "reserve_requirement_bps", 1, 10000)
    effective_date = schema.req_dt(data, "effective_date")
    expected = schema.req_int(data, "expected_partner_version")
    if expected != int(partner["version"]):                          # rank 28
        fail("ERR_STALE_PARTNER_VERSION", "expected_partner_version is stale")
    if partner["status"] in ("DILIGENCE_FAILED", "TERMINATED"):       # rank 32
        fail("ERR_PARTNER_TERMINAL", "partner is terminal")
    if effective_date < store.clock():                               # rank 67
        fail("ERR_EFFECTIVE_DATE_IN_PAST", "effective_date precedes the logical clock")
    for row in store.rows("agreements"):                             # rank 71
        if row["partner_id"] != partner["id"]:
            continue
        if row["status"] in ("DRAFT", "PENDING_RISK_APPROVAL", "EXECUTED"):
            fail("ERR_AGREEMENT_ALREADY_OPEN", "an open or executed agreement exists")
    record = {
        "partner_id": partner["id"],
        "kyc_owner": kyc,
        "dispute_owner": dispute,
        "marketing_owner": marketing,
        "oversight_rights_level": rights,
        "audit_access_notice_days": notice,
        "termination_triggers": triggers,
        "monthly_growth_cap_pct": float(growth_cap),
        "concentration_cap_pct": float(conc_cap),
        "max_end_user_balance_cents": max_balance,
        "reserve_requirement_bps": reserve_bps,
        "effective_date": effective_date,
        "status": "DRAFT",
        "revision_round": 1,
        "executed_at": None,
        "termination_trigger_fired": None,
        "created_by_user_id": g.user_id,
        "decided_by_user_id": None,
    }
    store.insert("agreements", record)
    store.touch(partner)
    return respond.ok(serialize.agreement(record), 201)


@bp.get("/oversight/agreements")
@auth(*READ_ROLES)
def list_agreements():
    rows = store.rows("agreements")
    partner_id = schema.filter_str("partner_id")
    if partner_id is not None:
        rows = [r for r in rows if r["partner_id"] == partner_id]
    status = schema.filter_enum("status", schema.AGREEMENT_STATUSES)
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    return respond.paginate(scope_rows(rows), serialize.agreement)


@bp.get("/oversight/agreements/<aid>")
@auth(*READ_ROLES)
def read_agreement(aid):
    agreement = store.must("agreements", aid)
    scope_partner_id(agreement["partner_id"])
    return respond.ok(serialize.agreement(agreement))


@bp.post("/oversight/agreements/<aid>/submit-for-approval")
@auth("ProgramOfficer")
def submit_agreement(aid):
    agreement = store.must("agreements", aid)                        # rank 8
    data = schema.body()
    schema.opt_str(data, "submission_note")                          # rank 18
    partner = store.get("partners", agreement["partner_id"])
    if agreement["status"] != "DRAFT":                               # rank 34
        fail("ERR_AGREEMENT_NOT_DRAFT", "agreement is not DRAFT")
    if partner["status"] != "DILIGENCE_PASSED" or \
            partner["capability_tier"] not in ("TIER_1", "TIER_2", "TIER_3"):
        fail("ERR_AGREEMENT_NOT_DRAFT", "partner has no underwritten basis for a contract")
    agreement["status"] = "PENDING_RISK_APPROVAL"
    store.touch(agreement)
    return respond.ok(serialize.agreement(agreement))


@bp.post("/oversight/agreements/<aid>/risk-decision")
@auth("RiskCommittee")
def risk_decision(aid):
    agreement = store.must("agreements", aid)                        # rank 8
    sod(agreement["created_by_user_id"])                             # rank 14
    data = schema.body()
    decision = schema.req_enum(data, "decision", ["EXECUTE", "REJECT"])   # rank 18
    schema.opt_str(data, "decision_note")
    if agreement["status"] != "PENDING_RISK_APPROVAL":               # rank 34
        fail("ERR_AGREEMENT_NOT_PENDING_APPROVAL", "agreement is not pending approval")
    partner = store.get("partners", agreement["partner_id"])
    if decision == "REJECT":
        agreement["status"] = "DRAFT"
        agreement["revision_round"] = int(agreement["revision_round"]) + 1
        agreement["decided_by_user_id"] = g.user_id
        store.touch(agreement)
        return respond.ok(serialize.agreement(agreement))
    if partner["status"] != "DILIGENCE_PASSED":
        fail("ERR_AGREEMENT_NOT_PENDING_APPROVAL", "partner is no longer DILIGENCE_PASSED")
    if agreement["effective_date"] < store.clock():
        fail("ERR_EFFECTIVE_DATE_IN_PAST", "effective_date precedes the logical clock")
    agreement["status"] = "EXECUTED"
    agreement["executed_at"] = store.clock()
    agreement["decided_by_user_id"] = g.user_id
    store.touch(agreement)
    partner["status"] = "CONTRACTED"
    for account_type in ("FBO_END_USER", "RESERVE"):
        store.insert("custody_accounts", {
            "partner_id": partner["id"],
            "account_type": account_type,
            "balance_cents": 0,
            "status": "ACTIVE",
            "frozen_at": None,
        })
    cascade.refresh_reserve(partner)
    cascade.refresh_posture(partner)
    cascade.freeze_custody_if_frozen(partner)
    store.touch(partner)
    return respond.ok(serialize.agreement(agreement))


@bp.post("/oversight/agreements/<aid>/terminate")
@auth("RiskCommittee")
def terminate_agreement(aid):
    agreement = store.must("agreements", aid)                        # rank 8
    data = schema.body()
    trigger = schema.req_enum(data, "termination_trigger",           # rank 18
                              schema.TERMINATION_TRIGGERS)
    schema.req_int(data, "notice_days")
    if agreement["status"] != "EXECUTED":                            # rank 34
        fail("ERR_AGREEMENT_NOT_EXECUTED", "agreement is not EXECUTED")
    if trigger not in (agreement["termination_triggers"] or []):     # rank 59
        fail("ERR_TERMINATION_TRIGGER_NOT_CONTRACTED", "trigger is not contracted")
    partner = store.get("partners", agreement["partner_id"])
    if partner["status"] not in ("CONTRACTED", "LIVE"):
        fail("ERR_PARTNER_NOT_CONTRACTED", "partner is not CONTRACTED or LIVE")
    was_live = partner["status"] == "LIVE"
    agreement["status"] = "TERMINATED"
    agreement["termination_trigger_fired"] = trigger
    store.touch(agreement)
    partner["status"] = "WIND_DOWN"
    store.touch(partner)
    if was_live:
        for review in store.rows("marketing_reviews"):
            if review["partner_id"] == partner["id"] and review["status"] in (
                    "SUBMITTED", "CHANGES_REQUESTED", "APPROVED"):
                review["status"] = "EXPIRED"
                store.touch(review)
    return respond.ok(serialize.agreement(agreement))
