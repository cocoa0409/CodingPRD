"""Ops endpoints: the monthly holding-cost accrual sweep (mounted under
/custody) and the test-driving logical clock endpoint (mounted at app root,
outside the /custody prefix, per PRD §1 and the endpoint table).
"""

from flask import Blueprint

import clock
import store
from constants import MONTHLY_CARRYING_COST_CENTS, EXPENSE_TYPE_STORAGE_ACCRUAL
from middleware import require_roles
from response import ok_object
from util import get_body, req_dt

bp = Blueprint("ops", __name__)

# monthly_holding_accrual input-set filters (SCAFFOLD §1.3).
_SWEEP_LEGAL_STATES = ("SEIZED", "VALUATION_PENDING", "VALUED", "DISPOSITION_REVIEW")
_SWEEP_CUSTODY_STATES = ("SECURED", "IN_STORAGE", "IN_MAINTENANCE")


@bp.route("/custody/run-holding-review", methods=["POST"])
def run_holding_review():
    require_roles("FundAdministrator")
    get_body()
    now = clock.now()
    assets_reviewed = 0
    accruals_posted = 0
    assets = sorted(store.ASSETS.values(), key=lambda a: (a["created_at"], a["_seq"]))
    for asset in assets:
        if asset["legal_state"] not in _SWEEP_LEGAL_STATES:
            continue
        if asset["custody_state"] not in _SWEEP_CUSTODY_STATES:
            continue
        assets_reviewed += 1
        # Idempotent per (asset, calendar month): skip when a SYSTEM_ACCRUAL
        # entry already exists inside the clock's current calendar month.
        already = any(
            entry["source"] == "SYSTEM_ACCRUAL"
            and entry["incurred_on"].year == now.year
            and entry["incurred_on"].month == now.month
            for entry in store.expenses_of_asset(asset["id"])
        )
        if already:
            continue
        entry = store.new_entity(
            {
                "asset_id": asset["id"],
                "entry_kind": "COST",
                "expense_type": EXPENSE_TYPE_STORAGE_ACCRUAL,
                "amount_cents": MONTHLY_CARRYING_COST_CENTS[asset["asset_type"]],
                "incurred_on": now,
                "source": "SYSTEM_ACCRUAL",
                "posted_by_user_id": "system",
            }
        )
        store.EXPENSES[entry["id"]] = entry
        asset["accumulated_net_holding_cost_cents"] += entry["amount_cents"]
        store.touch(asset)
        accruals_posted += 1
    return ok_object(
        {"assets_reviewed": assets_reviewed, "accruals_posted": accruals_posted}
    )


def register_clock_route(app):
    """Register POST /_clock/set_current_utc at the app root (UNPREFIXED)."""

    @app.route("/_clock/set_current_utc", methods=["POST"])
    def set_current_utc():
        require_roles("SystemOperator")
        data = get_body()
        to_iso8601 = req_dt(data, "to_iso8601")
        clock.set_now(to_iso8601)
        return ok_object({})
