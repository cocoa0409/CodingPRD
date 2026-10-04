"""Lead referrals: submit, assign via selector, decline."""
from datetime import date
from flask import Blueprint, request, g

import db as dbmod
from errors import (raise_err, ERR_INVALID_STATE, ERR_NO_ELIGIBLE_CONTRACTOR,
                    ERR_NOT_ASSIGNEE, ERR_UNAUTHORIZED)
from middleware import require_roles
from services import calcs
from services.lookup import get_path, get_body_ref
from util import body, ok_object, ok_list, req_str, new_resource, touch, logical_now_iso

bp = Blueprint("leads", __name__)


@bp.post("/decking/lead-referrals")
@require_roles("Dealer", "ProgramAdmin")
def create_lead():
    data = body()
    dealer = get_body_ref("dealers", data.get("submitted_by_dealer_id"), "submitted_by_dealer_id")
    if g.role == "Dealer" and g.user_id != dealer["id"]:
        raise_err(ERR_UNAUTHORIZED, "dealer may only submit leads under own id")
    name = req_str(data, "homeowner_name")
    zipc = req_str(data, "zip_code")
    lead = new_resource({
        "homeowner_name": name,
        "zip_code": zipc,
        "submitted_by_dealer_id": dealer["id"],
        "assigned_contractor_id": None,
        "declined_by": [],
        "assigned_at": None,
        "status": "OPEN",
    })
    dbmod.db.lead_referrals[lead["id"]] = lead
    return ok_object(dict(lead), status=201)


@bp.get("/decking/lead-referrals/<lid>")
@require_roles("ProgramAdmin", "Dealer", "Contractor")
def get_lead(lid):
    return ok_object(dict(get_path("lead_referrals", lid)))


@bp.get("/decking/lead-referrals")
@require_roles("ProgramAdmin", "Dealer", "Contractor")
def list_leads():
    items = list(dbmod.db.lead_referrals.values())
    for f in ("submitted_by_dealer_id", "assigned_contractor_id", "status"):
        v = request.args.get(f)
        if v:
            items = [l for l in items if str(l.get(f)) == v]
    return ok_list([dict(l) for l in items])


def _assigned_count_90d(contractor_id):
    ref = dbmod.clock_date()
    n = 0
    for l in dbmod.db.lead_referrals.values():
        if l["status"] == "ASSIGNED" and l.get("assigned_contractor_id") == contractor_id:
            ad = date.fromisoformat((l.get("assigned_at") or l["updated_at"])[:10])
            if 0 <= (ref - ad).days <= 90:
                n += 1
    return n


def _run_selector(exclude_ids):
    candidates = [c for c in dbmod.db.contractors.values()
                  if c["status"] == "CERTIFIED" and c["id"] not in exclude_ids]
    if not candidates:
        raise_err(ERR_NO_ELIGIBLE_CONTRACTOR, "lead selector found an empty candidate pool")

    def key(c):
        return (-calcs.TIER_RANK[c["tier"]],
                _assigned_count_90d(c["id"]),
                c.get("certified_at") or "",
                c["created_at"],
                c["id"])
    candidates.sort(key=key)
    return candidates[0]


@bp.post("/decking/lead-referrals/<lid>/assign")
@require_roles("ProgramAdmin")
def assign_lead(lid):
    lead = get_path("lead_referrals", lid)
    if lead["status"] == "OPEN":
        exclude = set()
    elif lead["status"] == "DECLINED":
        exclude = set(lead.get("declined_by") or [])
    else:
        raise_err(ERR_INVALID_STATE, f"lead is {lead['status']}")
    winner = _run_selector(exclude)
    lead["assigned_contractor_id"] = winner["id"]
    lead["assigned_at"] = logical_now_iso()
    lead["status"] = "ASSIGNED"
    touch(lead)
    return ok_object(dict(lead))


@bp.post("/decking/lead-referrals/<lid>/decline")
@require_roles("Contractor")
def decline_lead(lid):
    lead = get_path("lead_referrals", lid)
    if lead["status"] != "ASSIGNED":
        raise_err(ERR_INVALID_STATE, f"lead is {lead['status']}")
    if g.user_id != lead.get("assigned_contractor_id"):
        raise_err(ERR_NOT_ASSIGNEE, "lead decline by a non-assignee")
    lead.setdefault("declined_by", [])
    if g.user_id not in lead["declined_by"]:
        lead["declined_by"].append(g.user_id)
    lead["status"] = "DECLINED"
    lead["assigned_contractor_id"] = None
    touch(lead)
    return ok_object(dict(lead))
