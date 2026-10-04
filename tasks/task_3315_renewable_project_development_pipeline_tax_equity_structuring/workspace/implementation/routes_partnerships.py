"""Tax equity partnership, contributions, distributions, ledger routes."""
from decimal import Decimal

from flask import request

import db
from errors import raise_err
from helpers import (
    require_auth, payload, req_string, req_enum, req_positive_number, req_iso, success_obj,
    success_arr, pagination_args, paginate, now_common, touch, iso_from_epoch,
    dec2, money2,
)
from serializers import partnership_view, ledger_view
from logic import (
    get_project, get_partnership, get_ledger, tcq_for_project, partnership_computed,
    TCQ_ANCHORED_STATES,
)

READ_ROLES = ["TaxCounsel", "InvestorManager", "DeveloperAdmin", "Auditor", "PlatformAdmin"]
LEDGER_TYPES = {
    "CONTRIBUTION", "DISTRIBUTION_INVESTOR", "DISTRIBUTION_DEVELOPER",
    "CREDIT_ALLOCATION_INVESTOR", "CREDIT_ALLOCATION_DEVELOPER",
}


def _new_entry(partnership_id, entry_type, amount, period_iso):
    eid = db.new_id()
    e = {
        "id": eid,
        "partnership_id": partnership_id,
        "entry_type": entry_type,
        "amount_usd": float(amount),
        "period_end_date": period_iso,
        "created_at": iso_from_epoch(db.clock_now()),
    }
    db.partnership_ledger_entries[eid] = e
    return e


def register(app):

    @app.post("/api/projects/<pid>/tax-equity-partnerships")
    def create_partnership(pid):
        require_auth(["TaxCounsel"])
        get_project(pid)
        body = payload()
        investor_name = req_string(body, "investor_name")
        commitment = req_positive_number(body, "commitment_usd")
        target_irr = req_positive_number(body, "target_irr_pct")
        if any(p["project_id"] == pid and p["status"] != "DISSOLVED"
               for p in db.tax_equity_partnerships.values()):
            raise_err("ERR_INVALID_STATE",
                      "A non-DISSOLVED partnership already exists for the project")
        nid = db.new_id()
        p = {
            "id": nid,
            "project_id": pid,
            "investor_name": investor_name,
            "commitment_usd": float(commitment),
            "target_irr_pct": float(target_irr),
            "investor_pre_flip_share_pct": 99.0,
            "investor_post_flip_share_pct": 5.0,
            "flip_date": None,
            "status": "STRUCTURING",
        }
        now_common(p)
        db.tax_equity_partnerships[nid] = p
        return success_obj(partnership_view(p, partnership_computed(p)), 201)

    @app.get("/api/projects/<pid>/tax-equity-partnerships")
    def list_partnerships(pid):
        require_auth(READ_ROLES)
        get_project(pid)
        limit, offset = pagination_args()
        items = sorted(
            [p for p in db.tax_equity_partnerships.values() if p["project_id"] == pid],
            key=lambda p: (p["created_at"], p["id"]),
        )
        page, total = paginate(items, limit, offset)
        return success_arr(
            [partnership_view(p, partnership_computed(p)) for p in page],
            limit, offset, total)

    @app.get("/api/tax-equity-partnerships/<nid>")
    def get_partnership_route(nid):
        require_auth(READ_ROLES)
        p = get_partnership(nid)
        return success_obj(partnership_view(p, partnership_computed(p)))

    @app.post("/api/tax-equity-partnerships/<nid>/transitions")
    def partnership_transition(nid):
        require_auth(["TaxCounsel"])
        p = get_partnership(nid)
        body = payload()
        to = req_enum(body, "to", {"COMMITMENT_EXECUTED", "FLIPPED", "DISSOLVED"})
        cur = p["status"]
        valid = {
            ("STRUCTURING", "COMMITMENT_EXECUTED"),
            ("PRE_FLIP_OPERATING", "FLIPPED"),
            ("FLIPPED", "DISSOLVED"),
        }
        if (cur, to) not in valid:
            raise_err("ERR_INVALID_STATE", f"Cannot move from {cur} to {to}")

        if to == "COMMITMENT_EXECUTED":
            tcq = tcq_for_project(p["project_id"])
            if tcq is None or tcq["status"] not in TCQ_ANCHORED_STATES:
                raise_err("ERR_SAFE_HARBOR_NOT_QUALIFIED",
                          "Tax credit qualification not anchored")
            p["status"] = "COMMITMENT_EXECUTED"
            touch(p)
            return success_obj(partnership_view(p, partnership_computed(p)))

        if to == "FLIPPED":
            epv = body.get("expected_partnership_version")
            if epv is None:
                raise_err("ERR_VALIDATION", "expected_partnership_version is required")
            if isinstance(epv, bool) or not isinstance(epv, int):
                raise_err("ERR_VALIDATION", "expected_partnership_version must be an integer")
            if epv != p["version"]:
                raise_err("ERR_STALE_VERSION", "Partnership version has advanced")
            comp = partnership_computed(p)
            if dec2(comp["investor_irr_pct"]) < dec2(p["target_irr_pct"]):
                raise_err("ERR_TARGET_IRR_NOT_ACHIEVED",
                          "investor_irr_pct below target_irr_pct")
            p["status"] = "FLIPPED"
            p["flip_date"] = iso_from_epoch(db.clock_now())
            touch(p)
            return success_obj(partnership_view(p, partnership_computed(p)))

        # DISSOLVED
        p["status"] = "DISSOLVED"
        touch(p)
        return success_obj(partnership_view(p, partnership_computed(p)))

    @app.post("/api/tax-equity-partnerships/<nid>/contributions")
    def contribute(nid):
        require_auth(["InvestorManager"])
        p = get_partnership(nid)
        body = payload()
        amount = req_positive_number(body, "amount_usd")
        period_iso = iso_from_epoch(req_iso(body, "period_end_date"))
        if p["status"] not in ("COMMITMENT_EXECUTED", "FUNDING"):
            raise_err("ERR_INVALID_STATE",
                      f"Contributions not accepted in {p['status']}")
        comp = partnership_computed(p)
        new_total = dec2(comp["contributed_usd"]) + amount
        if new_total > dec2(p["commitment_usd"]):
            raise_err("ERR_CONTRIBUTION_EXCEEDS_COMMITMENT",
                      "Contribution would exceed commitment")
        e = _new_entry(nid, "CONTRIBUTION", money2(amount), period_iso)
        if p["status"] == "COMMITMENT_EXECUTED":
            p["status"] = "FUNDING"
        if new_total == dec2(p["commitment_usd"]):
            p["status"] = "FULLY_FUNDED"
        touch(p)
        return success_obj(ledger_view(e), 201)

    @app.post("/api/tax-equity-partnerships/<nid>/distributions")
    def distribute(nid):
        require_auth(["TaxCounsel"])
        p = get_partnership(nid)
        body = payload()
        amount = req_positive_number(body, "amount_usd")
        period_iso = iso_from_epoch(req_iso(body, "period_end_date"))
        if p["status"] not in ("PRE_FLIP_OPERATING", "FLIPPED"):
            raise_err("ERR_INVALID_STATE",
                      f"Distributions not permitted in {p['status']}")
        comp = partnership_computed(p)
        if amount > dec2(comp["retained_cash_usd"]):
            raise_err("ERR_DISTRIBUTION_EXCEEDS_CASH",
                      "Distribution exceeds retained cash")
        share = Decimal("99.00") if p["status"] == "PRE_FLIP_OPERATING" else Decimal("5.00")
        cash_inv = money2(amount * share / Decimal("100"))
        cash_dev = money2(amount - dec2(cash_inv))
        entries = []
        entries.append(_new_entry(nid, "DISTRIBUTION_INVESTOR", cash_inv, period_iso))
        entries.append(_new_entry(nid, "DISTRIBUTION_DEVELOPER", cash_dev, period_iso))
        # Credit tier while unallocated credits remain
        project = db.projects.get(p["project_id"])
        total_credits = dec2(project["total_itc_credits_usd"]) if project else Decimal("0")
        allocated = Decimal("0")
        for e in db.partnership_ledger_entries.values():
            if e["partnership_id"] == nid and e["entry_type"] in (
                    "CREDIT_ALLOCATION_INVESTOR", "CREDIT_ALLOCATION_DEVELOPER"):
                allocated += dec2(e["amount_usd"])
        unallocated = total_credits - allocated
        if unallocated > 0:
            cred_inv = money2(unallocated * share / Decimal("100"))
            cred_dev = money2(unallocated - dec2(cred_inv))
            entries.append(_new_entry(nid, "CREDIT_ALLOCATION_INVESTOR", cred_inv, period_iso))
            entries.append(_new_entry(nid, "CREDIT_ALLOCATION_DEVELOPER", cred_dev, period_iso))
        touch(p)
        limit = len(entries)
        return success_arr([ledger_view(e) for e in entries], limit, 0, len(entries), 201)

    @app.get("/api/tax-equity-partnerships/<nid>/ledger-entries")
    def list_ledger(nid):
        require_auth(READ_ROLES)
        get_partnership(nid)
        limit, offset = pagination_args()
        etype = request.args.get("entry_type")
        if etype is not None and etype not in LEDGER_TYPES:
            raise_err("ERR_VALIDATION", "Invalid entry_type filter")
        items = sorted(
            [e for e in db.partnership_ledger_entries.values() if e["partnership_id"] == nid],
            key=lambda e: (e["created_at"], e["id"]),
        )
        if etype:
            items = [e for e in items if e["entry_type"] == etype]
        page, total = paginate(items, limit, offset)
        return success_arr([ledger_view(e) for e in page], limit, offset, total)

    @app.get("/api/partnership-ledger-entries/<eid>")
    def get_ledger_route(eid):
        require_auth(READ_ROLES)
        e = get_ledger(eid)
        return success_obj(ledger_view(e))
