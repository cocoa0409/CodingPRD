from flask import Blueprint

import calc
import db
import middleware as mw
import response
import util

bp = Blueprint("maturity", __name__)


@bp.post("/maturity-runs")
def maturity_run():
    user_id, _role = mw.auth("SystemAdmin")
    data = mw.body()
    as_of_date = mw.req_date(data, "as_of_date")

    due = [p for p in db.placements.values()
           if p["funding_status"] == "ACTIVE" and p["maturity_date"] <= as_of_date]
    due.sort(key=lambda p: (p["maturity_date"], p["created_at"], p["_seq"]))

    matured_ids = []
    # --- phase one: mature every due tranche, releasing its principal --------
    for placement in due:
        program = db.programs.get(placement["program_id"])
        institution = db.institutions.get(program["institution_id"])
        days = util.day_diff(placement["maturity_date"], placement["issue_date"])
        interest = calc.accrued_interest(placement["principal_cents"],
                                        placement["rate_bps"], days)
        placement["accrued_interest_cents"] = interest
        placement["early_withdrawal_penalty_cents"] = 0
        placement["net_settlement_cents"] = placement["principal_cents"] + interest
        placement["settlement_date"] = placement["maturity_date"]
        placement["funding_status"] = "MATURED"
        placement["fee_accrual_cents"] = 0
        db.bump(placement)
        program["outstanding_principal_cents"] -= placement["principal_cents"]
        db.touch(program)
        calc.recompute_institution(institution)
        calc.recompute_fees_for_placement(placement)
        matured_ids.append(placement["id"])

    # --- phase two: roll over only what phase one just matured --------------
    created_ids = []
    for placement in due:
        program = db.programs.get(placement["program_id"])
        institution = db.institutions.get(program["institution_id"])
        if not program.get("rollover_enabled"):
            continue
        if program["state"] != "OPEN_FOR_PLACEMENT":
            continue
        if institution["concentration_posture"] == "FROZEN":
            continue
        tenor_days = program["tenor_days"]
        successor = {
            "program_id": program["id"],
            "rolled_from_placement_id": placement["id"],
            "principal_cents": placement["net_settlement_cents"],
            "rate_bps": program["offered_rate_bps"],
            "issue_date": as_of_date,
            "tenor_days": tenor_days,
            "maturity_date": util.add_days(as_of_date, tenor_days),
            "tenor_bucket": calc.tenor_bucket(program["product_type"], tenor_days),
            "funding_status": "PENDING",
            "compliance_status": "UNREVIEWED",
            "accrued_interest_cents": 0,
            "early_withdrawal_penalty_cents": 0,
            "net_settlement_cents": 0,
            "settlement_date": None,
            "fee_accrual_cents": 0,
            "classified_as": None,
            "prepared_by_user_id": user_id,
        }
        db.stamp_new(successor)
        db.placements[successor["id"]] = successor
        placement["funding_status"] = "ROLLED_OVER"
        db.bump(placement)
        created_ids.append(successor["id"])

    return response.ok({
        "as_of_date": as_of_date,
        "matured_count": len(matured_ids),
        "rolled_over_count": len(created_ids),
        "created_placement_count": len(created_ids),
        "matured_placement_ids": matured_ids,
        "created_placement_ids": created_ids,
    })
