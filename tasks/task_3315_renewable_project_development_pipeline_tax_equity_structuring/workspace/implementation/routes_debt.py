"""Debt facility routes."""
from decimal import Decimal

import db
from errors import raise_err
from helpers import (
    require_auth, payload, req_enum, req_positive_number, opt_number,
    success_obj, success_arr, pagination_args, paginate, now_common, touch,
    dec2, money2,
)
from serializers import df_view
from logic import (
    get_project, get_df, project_eligible_basis, MIN_DSCR, MAX_ADVANCE_RATE,
)

READ_ROLES = ["LenderAgent", "DeveloperAdmin", "TaxCounsel", "Auditor", "PlatformAdmin"]


def register(app):

    @app.post("/api/projects/<pid>/debt-facilities")
    def create_df(pid):
        require_auth(["LenderAgent"])
        get_project(pid)
        body = payload()
        commitment = req_positive_number(body, "commitment_usd")
        rate = req_positive_number(body, "interest_rate_pct")
        cfads = req_positive_number(body, "projected_cfads_usd")
        if any(f["project_id"] == pid and f["status"] != "RETIRED"
               for f in db.debt_facilities.values()):
            raise_err("ERR_INVALID_STATE",
                      "A non-RETIRED debt facility already exists for the project")
        fid = db.new_id()
        f = {
            "id": fid,
            "project_id": pid,
            "commitment_usd": float(commitment),
            "drawn_usd": 0.0,
            "interest_rate_pct": float(rate),
            "projected_cfads_usd": float(cfads),
            "min_dscr": 1.30,
            "term_debt_usd": 0.0,
            "status": "COMMITMENT",
        }
        now_common(f)
        db.debt_facilities[fid] = f
        return success_obj(df_view(f), 201)

    @app.get("/api/projects/<pid>/debt-facilities")
    def list_df(pid):
        require_auth(READ_ROLES)
        get_project(pid)
        limit, offset = pagination_args()
        items = sorted(
            [f for f in db.debt_facilities.values() if f["project_id"] == pid],
            key=lambda f: (f["created_at"], f["id"]),
        )
        page, total = paginate(items, limit, offset)
        return success_arr([df_view(f) for f in page], limit, offset, total)

    @app.get("/api/debt-facilities/<fid>")
    def get_df_route(fid):
        require_auth(READ_ROLES)
        f = get_df(fid)
        return success_obj(df_view(f))

    @app.post("/api/debt-facilities/<fid>/transitions")
    def df_transition(fid):
        require_auth(["LenderAgent"])
        f = get_df(fid)
        body = payload()
        to = req_enum(body, "to", {
            "CONSTRUCTION_DRAWING", "CONVERSION_PENDING", "TERM_REPAYMENT",
            "RETIRED", "DEFAULTED",
        })
        cur = f["status"]
        valid = {
            ("COMMITMENT", "CONSTRUCTION_DRAWING"),
            ("CONSTRUCTION_DRAWING", "CONSTRUCTION_DRAWING"),
            ("CONVERSION_PENDING", "TERM_REPAYMENT"),
            ("TERM_REPAYMENT", "RETIRED"),
            ("CONSTRUCTION_DRAWING", "DEFAULTED"),
            ("TERM_REPAYMENT", "DEFAULTED"),
        }
        if (cur, to) not in valid:
            raise_err("ERR_INVALID_STATE", f"Cannot move from {cur} to {to}")

        if to == "CONSTRUCTION_DRAWING":
            amount = opt_number(body, "draw_amount_usd", None)
            if amount is None or amount <= 0:
                raise_err("ERR_VALIDATION", "draw_amount_usd must be present and > 0")
            if dec2(f["drawn_usd"]) + amount > dec2(f["commitment_usd"]):
                raise_err("ERR_DRAW_EXCEEDS_COMMITMENT",
                          "Draw would exceed commitment")
            f["drawn_usd"] = float(dec2(f["drawn_usd"]) + amount)
            f["status"] = "CONSTRUCTION_DRAWING"
            touch(f)
            return success_obj(df_view(f))

        if to == "TERM_REPAYMENT":
            if dec2(f["drawn_usd"]) <= 0:
                raise_err("ERR_VALIDATION", "drawn_usd must be > 0")
            annual_service = dec2(f["drawn_usd"]) * dec2(f["interest_rate_pct"]) / Decimal("100")
            dscr = dec2(f["projected_cfads_usd"]) / annual_service
            if dscr < MIN_DSCR:
                raise_err("ERR_DSCR_BELOW_MINIMUM", "DSCR below 1.30")
            eligible_cost = project_eligible_basis(f["project_id"])
            sized = money2(MAX_ADVANCE_RATE * eligible_cost)
            f["term_debt_usd"] = min(
                dec2(f["commitment_usd"]), dec2(f["drawn_usd"]), dec2(sized))
            f["term_debt_usd"] = float(f["term_debt_usd"])
            f["status"] = "TERM_REPAYMENT"
            touch(f)
            return success_obj(df_view(f))

        f["status"] = to
        touch(f)
        return success_obj(df_view(f))
