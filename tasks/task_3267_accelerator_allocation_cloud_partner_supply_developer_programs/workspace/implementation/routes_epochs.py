"""Logical clock, epoch advance/close, checkpoint sweeps and the audit surface."""

from datetime import timedelta
from decimal import Decimal

import calc
import constants as K
from auth import roles
from error import CatalogError, ERR_EPOCH_ALREADY_CLOSED, ERR_RESOURCE_NOT_FOUND
from envelope import ok, page
from rules import resource_or_404
from services import add_penalty, recompute_node, serialize
from store import DB
from util import by_created, paginate, parse_utc, require

GROUP = "epochs"


# ------------------------------------------------------------- the clock ---
def _set_clock(caller):
    from flask import request
    body = request.raw_payload or {}
    value = require(body, "current_utc")
    DB.set_clock(value)
    return ok({"current_utc": DB.now_text()})


def _epoch_view(epoch):
    return serialize(epoch)


def _advance_epoch(caller):
    open_epoch = DB.open_epoch()
    if open_epoch is None:
        raise CatalogError(ERR_EPOCH_ALREADY_CLOSED, "There is no open epoch to advance.")

    open_epoch["epoch_status"] = "CLOSED"
    DB.touch(open_epoch)

    successor = DB.mint({
        "epoch_index": int(open_epoch.get("epoch_index", 0)) + 1,
        "opened_at": DB.now_text(),
        "half_life_next": _predicted_band(),
        "epoch_status": "OPEN",
    })
    DB.epochs[successor["id"]] = successor

    _sweep_nodes()
    _sweep_penalties()
    _sweep_loans()
    _sweep_forecasts()
    _sweep_subscriptions()
    _sweep_grants()
    _sweep_partners()
    return ok(_epoch_view(successor))


def _predicted_band():
    """The band the pools' committed rate would occupy after HALF_LIFE_EPOCHS."""
    if not DB.nodes:
        return "COOL"
    total = Decimal("0")
    for node in DB.nodes.values():
        total += calc.total_committed_rate(DB, node)
    return calc.band_for_rate(total * calc.decay_factor(K.HALF_LIFE_EPOCHS))


def _close_epoch(caller, epoch_id):
    epoch = resource_or_404("epochs", epoch_id, "allocation epoch")
    if epoch.get("epoch_status") == "CLOSED":
        raise CatalogError(ERR_EPOCH_ALREADY_CLOSED)
    epoch["epoch_status"] = "CLOSED"
    DB.touch(epoch)
    return ok(_epoch_view(epoch))


# ---------------------------------------------------------------- sweeps ---
def _sweep_nodes():
    for node in DB.nodes.values():
        recompute_node(node)
        # Release first, on the score the pool already carried into this epoch.
        if node.get("stage") == "FRICTION_HOLD":
            if float(node.get("friction_penalty_score", 0.0)) < K.FRICTION_HOLD_RELEASE_SCORE:
                node["stage"] = "OPEN"
                DB.touch(node)
        elif node.get("stage") == "BINDING":
            node["stage"] = "OPEN"
            node["friction_penalty_score"] = 0.0
            DB.touch(node)
        # A pool that is OPEN with standing holds re-derived above its ceiling
        # enters FRICTION_HOLD with a fresh penalty, exactly as the
        # band-violation path would (PRD 3.3).
        if node.get("stage") == "OPEN" and _apply_band_violations(node):
            node["stage"] = "FRICTION_HOLD"
            recompute_node(node)
            DB.touch(node)
        tier, ceiling, half_life, total = calc.supply_hotness_tier(DB, node)
        node["half_life_next"] = half_life


def _apply_band_violations(node):
    """Flag standing holds that rank above the pool's re-derived ceiling."""
    ceiling = node.get("temp_band_ceiling", "COOL")
    flagged = False
    for hold in list(DB.holds.values()):
        if hold.get("supply_node_id") != node["id"]:
            continue
        if hold.get("state") not in ("REQUESTED", "COMMITTED"):
            continue
        if hold.get("_band_violation"):
            continue
        tier = hold.get("hold_friction_tier", "COOL")
        if K.TIER_INDEX[tier] <= K.TIER_INDEX[ceiling]:
            continue
        score = calc.friction_penalty_score(tier, ceiling)
        add_penalty(node, hold.get("partner_id"), hold["id"], "BAND_VIOLATION", score)
        hold["_band_violation"] = True
        hold["_normal"] = False
        DB.touch(hold)
        flagged = True
    return flagged


def _sweep_penalties():
    factor = Decimal(str(calc.decay_factor(1)))
    for penalty in DB.penalties.values():
        if penalty.get("penalty_state") != "ACTIVE":
            continue
        decayed = Decimal(str(penalty.get("score", 0))) * factor
        new_score = float(calc._r(decayed, 1))
        penalty["score"] = new_score
        if new_score <= 0.0:
            penalty["penalty_state"] = "DECAYED"
        DB.touch(penalty)
    for node in DB.nodes.values():
        node["friction_penalty_score"] = round(sum(
            float(p.get("score", 0))
            for p in DB.penalties.values()
            if p.get("supply_node_id") == node["id"] and p.get("penalty_state") == "ACTIVE"
        ), 1)


def _sweep_loans():
    for loan in DB.loans.values():
        if loan.get("loan_state") != "ACTIVE":
            continue
        due = loan.get("required_return_at")
        if not due:
            continue
        if DB.clock <= parse_utc(due):
            continue
        loan["loan_state"] = "OVERDUE"
        days_late = int((DB.clock - parse_utc(due)).total_seconds()) // K.SECONDS_PER_DAY
        loan["late_fee_units"] = calc.loan_late_fee(days_late)
        DB.touch(loan)
        for milestone in DB.milestones.values():
            if milestone.get("loan_id") != loan["id"]:
                continue
            if milestone.get("milestone_state") == "OPEN":
                milestone["milestone_state"] = "LATE"
                DB.touch(milestone)
        node = _node_for_loan(loan)
        if node is not None:
            add_penalty(node, loan.get("partner_id"), loan["id"], "LATE_CANCEL", K.SCORE_BASE)
            recompute_node(node)


def _node_for_loan(loan):
    if loan.get("supply_node_id"):
        node = DB.nodes.get(loan["supply_node_id"])
        if node is not None:
            return node
    for node in DB.nodes.values():
        if node.get("product_sku_id") == loan.get("product_sku_id"):
            return node
    return None


def _sweep_forecasts():
    for forecast in DB.forecasts.values():
        if forecast.get("tracking_status") != "ACTIVE":
            continue
        partner = DB.partners.get(forecast.get("partner_id"))
        if partner is None:
            continue
        deadline = partner.get("eligibility_deadline_at")
        if not deadline:
            continue
        if DB.clock >= parse_utc(deadline):
            forecast["tracking_status"] = "COMMITTED"
            DB.touch(forecast)


def _sweep_subscriptions():
    for sub in DB.subscriptions.values():
        if sub.get("status") != "ACTIVE":
            continue
        activated = sub.get("activated_at")
        if not activated:
            continue
        anniversary = parse_utc(activated) + timedelta(days=365)
        if DB.clock >= anniversary:
            sub["status"] = "EXPIRED"
            _billable, settled = calc.subscription_fee_final(sub)
            sub["settled_fee_cents"] = settled
            DB.touch(sub)


def _sweep_grants():
    for grant in DB.grants.values():
        if grant.get("grant_status") != "OPEN":
            continue
        expires = grant.get("commitment_expires_at")
        if not expires:
            continue
        if DB.clock > parse_utc(expires):
            grant["grant_status"] = "EXPIRED"
            DB.touch(grant)


def _sweep_partners():
    for partner in DB.partners.values():
        if partner.get("qualification_status") != "QUALIFIED":
            partner["allocation_priority_class"] = "UNQUALIFIED"
            DB.touch(partner)
            continue
        partner["allocation_priority_class"] = calc.partner_priority_class(partner)
        DB.touch(partner)


# --------------------------------------------------------------- epochs ----
def _list_epochs(caller):
    from flask import request
    rows = by_created(list(DB.epochs.values()))
    window, meta = paginate([_epoch_view(row) for row in rows], request.args)
    return page(window, meta)


def _read_epoch(caller, epoch_id):
    return ok(_epoch_view(resource_or_404("epochs", epoch_id, "allocation epoch")))


# ----------------------------------------------------------- audit trail ---
def _list_audits(caller):
    from flask import request
    rows = by_created(list(DB.audits.values()))
    partner_id = request.args.get("partner_id")
    if partner_id:
        rows = [row for row in rows if row.get("partner_id") == partner_id]
    window, meta = paginate([serialize(row) for row in rows], request.args)
    return page(window, meta)


def _read_audit(caller, audit_id):
    entry = DB.audits.get(audit_id)
    if entry is None:
        raise CatalogError(ERR_RESOURCE_NOT_FOUND, "The audit entry does not exist.")
    return ok(serialize(entry))


ROUTES = [
    ("POST", "/accelerators/_clock/set_current_utc", _set_clock, ("PlatformAdmin",)),
    ("POST", "/accelerators/_ops/advance_epoch", _advance_epoch, ("PlatformAdmin",)),
    ("GET", "/accelerators/epochs", _list_epochs, ("PlatformAdmin",)),
    ("GET", "/accelerators/epochs/<epoch_id>", _read_epoch, ("PlatformAdmin",)),
    ("POST", "/accelerators/epochs/<epoch_id>/close", _close_epoch, ("PlatformAdmin",)),
    ("GET", "/accelerators/audit-entries", _list_audits, ("SupplyComplianceOfficer",)),
    ("GET", "/accelerators/audit-entries/<audit_id>", _read_audit, ("SupplyComplianceOfficer",)),
]


def register(app):
    for method, path, handler, allowed in ROUTES:
        endpoint = "%s_%s" % (GROUP, path.replace("/", "_").replace("<", "").replace(">", ""))
        app.add_url_rule(path, endpoint + method, roles(*allowed)(handler), methods=[method])