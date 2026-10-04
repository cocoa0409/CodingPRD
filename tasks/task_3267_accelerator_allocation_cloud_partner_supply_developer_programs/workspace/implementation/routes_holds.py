"""Allocation holds: request, commit, cancel, reclaim, expire and preemption."""

import calc
import constants as K
from auth import require_self, roles
from error import (
    CatalogError,
    ERR_ALLOCATED_UNITS_CHANGED,
    ERR_FORECAST_NOT_COMMITTED,
    ERR_HOLD_TIER_EXCEEDS_BAND,
    ERR_INVALID_REQUEST,
    ERR_INVALID_STATE,
    ERR_NO_ALLOCATION_CANDIDATE,
    ERR_NO_OPEN_EPOCH,
    ERR_NODE_NOT_OPEN_FOR_ALLOCATION,
    ERR_PARTNER_NOT_FOUND,
    ERR_QUALIFICATION_NOT_MET,
    ERR_STALE_PARTNER_VERSION,
    ERR_SUPPLY_CEILING_EXCEEDED,
)
from envelope import created, ok, page
from rules import check_qualified, resolve, resource_or_404
from services import (
    add_penalty,
    append_audit,
    derive_product_allocated,
    move_capacity_ledger,
    recompute_node,
    serialize,
)
from store import DB
from util import by_created, optional, paginate, parse_utc, require, require_enum

GROUP = "holds"

# POST /allocation-holds binds its payload to this key order, not to names
# (PRD 3.4 / scaffold description).
POSITIONAL_KEYS = [
    "product_sku_id",
    "supply_node_id",
    "quantity_units",
    "hold_friction_tier",
    "forecast_id",
    "preempt_lower_tier",
    "expected_partner_version",
    "expected_allocated_units",
]


def _partition(body):
    """Accept both a keyed payload and a positional list."""
    if isinstance(body, list):
        return dict(zip(POSITIONAL_KEYS, body))
    return body if isinstance(body, dict) else {}


# --------------------------------------------------------------- creation --
def _create(caller):
    from flask import request
    body = _partition(request.raw_payload)
    hold = _build_hold(caller, body, use_positional=True)
    return created(serialize(hold))


def _bulk_create(caller):
    from flask import request
    body = _partition(request.raw_payload)
    partner = _caller_partner(caller)
    members = body.get("members")
    if not isinstance(members, list) or not members:
        raise CatalogError(ERR_INVALID_REQUEST, "'members' must be a non-empty array.")
    product = resource_or_404("products", body.get("product_sku_id"), "accelerator product")
    node = resource_or_404("nodes", body.get("supply_node_id"), "supply node")
    _check_allocated_units(product, body.get("expected_allocated_units"))
    _check_partner_version(partner, body.get("expected_partner_version"))
    tier = body.get("hold_friction_tier") or "COOL"
    require_enum(tier, K.HOTNESS_TIERS, "hold_friction_tier")

    holds = []
    for member in members:
        if isinstance(member, dict):
            quantity = member.get("quantity_units")
            if quantity is None:
                # A licence-member entry names a code rather than a quantity; one
                # reservation per member is the unit the bulk form promises.
                quantity = 1
            quantity = int(quantity)
        else:
            quantity = int(member)
        rows = _reserve(
            partner=partner,
            product=product,
            node=node,
            quantity_units=quantity,
            tier=tier,
            preempt=False,
            bump_partner=False,
        )
        holds.extend(rows)
    DB.bump(partner)
    recompute_node(node)
    derive_product_allocated(product)
    return ok([serialize(row) for row in holds])


def _caller_partner(caller):
    partner = resolve("partners", caller.user_id)
    if partner is None:
        raise CatalogError(ERR_PARTNER_NOT_FOUND, "X-User-ID does not name a partner account.")
    return partner


def _build_hold(caller, body, use_positional):
    partner = _caller_partner(caller)
    product = resolve("products", body.get("product_sku_id"))
    if product is None:
        raise CatalogError(ERR_INVALID_REQUEST, "'product_sku_id' does not resolve.")
    node = resolve("nodes", body.get("supply_node_id"))
    if node is None:
        raise CatalogError(ERR_INVALID_REQUEST, "'supply_node_id' does not resolve.")

    # Priority 11: posture gate.
    if DB.open_epoch() is None:
        raise CatalogError(ERR_NO_OPEN_EPOCH)
    # Priority 10: the pool must accept allocations.
    if node.get("stage") in ("DRAINING", "BINDING"):
        raise CatalogError(ERR_NODE_NOT_OPEN_FOR_ALLOCATION)

    # The tier is read now but its band behaviour is applied in _reserve: the
    # single-hold path lets an over-temperature hold commit into FRICTION_HOLD
    # (PRD 3.3 and the SupplyNode state machine).
    tier = optional(body, "hold_friction_tier", "COOL")
    if tier is not None and tier not in K.HOTNESS_TIERS:
        raise CatalogError(ERR_INVALID_REQUEST, "'hold_friction_tier' has an unknown member.")

    quantity = body.get("quantity_units")
    shape_ok = isinstance(quantity, int) and not isinstance(quantity, bool) and quantity > 0
    effective_quantity = quantity if shape_ok else 0

    # Priority 9: the friction tier must rank at or below the pool's ceiling.
    # The over-temperature hold normally takes the friction path (commits into
    # FRICTION_HOLD rather than being refused), but when the pool cannot supply
    # it from unheld capacity the ceiling is a hard constraint and the request
    # is refused outright (PRD 3.4).
    insufficient_capacity = (
        int(node.get("held_units", 0)) + effective_quantity
    ) > int(node.get("capacity_units", 0))
    tier_over_ceiling = K.TIER_INDEX[tier] > K.TIER_INDEX[node.get("temp_band_ceiling", "COOL")]
    if tier_over_ceiling and insufficient_capacity:
        raise CatalogError(ERR_HOLD_TIER_EXCEEDS_BAND)

    # Priority 13: a named forecast must support the hold.
    forecast = None
    forecast_id = body.get("forecast_id")
    if forecast_id:
        forecast = DB.forecasts.get(forecast_id)
        if forecast is None:
            raise CatalogError(ERR_FORECAST_NOT_COMMITTED)
        if forecast.get("tracking_status") not in ("ACTIVE", "COMMITTED"):
            raise CatalogError(ERR_FORECAST_NOT_COMMITTED)
        if forecast.get("partner_id") != partner["id"]:
            raise CatalogError(ERR_FORECAST_NOT_COMMITTED)
        if forecast.get("product_sku_id") != product["id"]:
            raise CatalogError(ERR_FORECAST_NOT_COMMITTED)

    # Priority 22: the committed-volume ceiling, strict comparison.
    ceiling = int(partner.get("entitlement_units_held", 0) or 0) + K.SUPPLY_CEILING_HEADROOM_UNITS
    if effective_quantity > ceiling:
        raise CatalogError(ERR_SUPPLY_CEILING_EXCEEDED)

    preempt = bool(body.get("preempt_lower_tier"))
    # Priority 25: a displacing request needs a non-empty candidate set, and
    # that check precedes any capacity comparison.
    if preempt and (int(node.get("held_units", 0)) + effective_quantity) > int(node.get("capacity_units", 0)):
        if not _candidates(node):
            raise CatalogError(ERR_NO_ALLOCATION_CANDIDATE)

    # Priorities 26 and 27.
    _check_allocated_units(product, body.get("expected_allocated_units"))
    _check_partner_version(partner, body.get("expected_partner_version"))
    # Priority 29: request shape.
    if not shape_ok:
        raise CatalogError(ERR_INVALID_REQUEST, "'quantity_units' must be strictly positive.")
    # Priority 30: certification.
    check_qualified(partner)

    rows = _reserve(
        partner=partner,
        product=product,
        node=node,
        quantity_units=quantity,
        tier=tier,
        forecast=forecast,
        preempt=preempt,
        bump_partner=True,
    )
    return rows[0]


def _check_allocated_units(product, expected):
    if expected is None:
        raise CatalogError(ERR_INVALID_REQUEST, "'expected_allocated_units' is required.")
    try:
        observed = int(expected)
    except (TypeError, ValueError):
        raise CatalogError(ERR_INVALID_REQUEST, "'expected_allocated_units' must be an integer.")
    if observed != int(product.get("allocated_units", 0) or 0):
        raise CatalogError(ERR_ALLOCATED_UNITS_CHANGED)


def _check_partner_version(partner, expected):
    if expected is None:
        raise CatalogError(ERR_INVALID_REQUEST, "'expected_partner_version' is required.")
    try:
        observed = int(expected)
    except (TypeError, ValueError):
        raise CatalogError(ERR_INVALID_REQUEST, "'expected_partner_version' must be an integer.")
    if observed != int(partner.get("version", 1)):
        raise CatalogError(ERR_STALE_PARTNER_VERSION)


def _reserve(partner, product, node, quantity_units, tier, forecast=None, preempt=False, bump_partner=False):
    """Create one REQUESTED hold plus its preemption and friction side effects."""
    if quantity_units <= 0:
        raise CatalogError(ERR_INVALID_REQUEST, "'quantity_units' must be strictly positive.")

    insufficient = (int(node.get("held_units", 0)) + quantity_units) > int(node.get("capacity_units", 0))
    displaced = []
    if insufficient and preempt:
        candidates = _candidates(node, exclude_partner_hold=None)
        if not candidates:
            raise CatalogError(ERR_NO_ALLOCATION_CANDIDATE)
        ordered = calc.allocation_priority_ranking(DB, candidates)
        accumulated = 0
        # Displacement consumes the ranking from the LOWEST score upward, so the
        # descending ranking is walked in reverse (PRD 2.7).
        for hold in reversed(ordered):
            displaced.append(hold)
            accumulated += int(hold.get("quantity_units", 0))
            if accumulated >= quantity_units:
                break

    rate, _fee = calc.committed_rate_v2(partner, quantity_units)
    estimate = calc.allocation_value_estimate(partner, quantity_units, DB.clock)
    confirm = calc.allocation_value_confirm(partner, quantity_units, DB.clock)
    band_violation = K.TIER_INDEX[tier] > K.TIER_INDEX[node.get("temp_band_ceiling", "COOL")]
    # Per the scaffold's SupplyNode transition, a band-violating hold is
    # COMMITTED on creation and its quantity is never counted toward the
    # pool's held units.  A displacing request also lands COMMITTED once it has
    # displaced its prefix (PRD 2.7): it steps into the capacity it freed.
    # The marker is server-private bookkeeping.
    band_flag = "_band_violation" if band_violation else "_normal"
    commits_on_create = band_violation or bool(displaced)

    hold = DB.mint({
        "partner_id": partner["id"],
        "product_sku_id": product["id"],
        "supply_node_id": node["id"],
        "hold_friction_tier": tier,
        "quantity_units": quantity_units,
        "committed_rate_v2": float(rate),
        "cancellation_forfeit_units": 0,
        "economic_tag": "HIGH_VALUE" if confirm > estimate else "LOW_VALUE",
        "state": "COMMITTED" if commits_on_create else "REQUESTED",
        "expected_partner_version": partner.get("version"),
        "forecast_id": forecast["id"] if forecast is not None else None,
        "forecast_horizon_band": forecast.get("horizon_band") if forecast is not None else None,
        "value_estimate": estimate,
        "value_confirm": confirm,
        band_flag: True,
    })
    DB.holds[hold["id"]] = hold

    # Preemption order is pinned: the displaced set is frozen before the
    # incoming quantity reaches the partner's committed volume.
    for victim in displaced:
        victim["state"] = "RECLAIMED"
        DB.touch(victim)
        move_capacity_ledger(DB.partners.get(victim.get("partner_id")), -int(victim.get("quantity_units", 0)))

    if commits_on_create and not band_violation:
        move_capacity_ledger(partner, int(quantity_units))

    if bump_partner:
        DB.bump(partner)

    if band_violation:
        score = calc.friction_penalty_score(tier, node.get("temp_band_ceiling", "COOL"))
        add_penalty(node, partner["id"], hold["id"], "BAND_VIOLATION", score)
        if node.get("stage") == "OPEN":
            node["stage"] = "FRICTION_HOLD"
    recompute_node(node)
    derive_product_allocated(product)
    return [hold]


def _candidates(node, exclude_partner_hold=None):
    ceiling = node.get("temp_band_ceiling", "COOL")
    rows = []
    for hold in DB.holds.values():
        if hold.get("product_sku_id") != node.get("product_sku_id"):
            continue
        if hold.get("state") != "REQUESTED":
            continue
        if hold.get("supply_node_id") != node["id"]:
            continue
        if K.TIER_INDEX[hold.get("hold_friction_tier", "COOL")] > K.TIER_INDEX[ceiling]:
            continue
        rows.append((hold, node))
    return rows


# ----------------------------------------------------------------- reads ---
def _list(caller):
    from flask import request
    rows = by_created(list(DB.holds.values()))
    for field in ("partner_id", "state", "product_sku_id", "supply_node_id", "forecast_id"):
        value = request.args.get(field)
        if value:
            rows = [row for row in rows if row.get(field) == value]
    window, meta = paginate([serialize(row) for row in rows], request.args)
    return page(window, meta)


def _read(caller, hold_id):
    return ok(serialize(resource_or_404("holds", hold_id, "allocation hold")))


# ------------------------------------------------------------- transitions --
def _commit(caller, hold_id):
    from flask import request
    hold = resource_or_404("holds", hold_id, "allocation hold")
    body = request.raw_payload if isinstance(request.raw_payload, dict) else {}
    if hold.get("state") != "REQUESTED":
        raise CatalogError(ERR_INVALID_STATE, "Only a REQUESTED hold may be committed.")
    node = resource_or_404("nodes", hold.get("supply_node_id"), "supply node")
    if node.get("stage") in ("DRAINING", "BINDING"):
        raise CatalogError(ERR_NODE_NOT_OPEN_FOR_ALLOCATION)
    hold["state"] = "COMMITTED"
    DB.touch(hold)
    partner = DB.partners.get(hold.get("partner_id"))
    move_capacity_ledger(partner, int(hold.get("quantity_units", 0)))
    if bool(body.get("consume_reservation")):
        move_capacity_ledger(partner, -int(hold.get("quantity_units", 0)))
    derive_product_allocated(DB.products.get(hold.get("product_sku_id")))
    recompute_node(node)
    return ok(serialize(hold))


def _cancel(caller, hold_id):
    from flask import request
    hold = resource_or_404("holds", hold_id, "allocation hold")
    body = request.raw_payload if isinstance(request.raw_payload, dict) else {}
    state = hold.get("state")
    if state not in ("REQUESTED", "COMMITTED"):
        raise CatalogError(ERR_INVALID_STATE, "Only a REQUESTED or COMMITTED hold may be cancelled.")
    node = resource_or_404("nodes", hold.get("supply_node_id"), "supply node")
    hold["state"] = "CANCELLED"
    DB.touch(hold)
    move_capacity_ledger(DB.partners.get(hold.get("partner_id")), -int(hold.get("quantity_units", 0)))
    if state == "COMMITTED":
        _apply_forfeit(hold)
        derive_product_allocated(DB.products.get(hold.get("product_sku_id")))
    recompute_node(node)
    actor = body.get("as_user_id")
    if actor:
        _audit_as(hold.get("partner_id"), "HOLD_CANCELLED", "AllocationHold", hold["id"], actor, caller.role)
    else:
        append_audit(hold.get("partner_id"), "HOLD_CANCELLED", "AllocationHold", hold["id"], caller)
    return ok(serialize(hold))


def _audit_as(partner_id, action_code, entity, subject_id, user_id, role):
    from services import _digest  # local import keeps the helper private-ish

    payload = "%s:%s:%s:%s" % (action_code, entity, subject_id, DB.now_text())
    entry = DB.mint({
        "partner_id": partner_id,
        "action_code": action_code,
        "subject_entity": entity,
        "subject_id": subject_id,
        "actor_user_id": user_id,
        "actor_role": role,
        "recorded_at": DB.now_text(),
        "entry_digest": _digest(partner_id, payload),
    })
    DB.audits[entry["id"]] = entry
    return entry


def _apply_forfeit(hold):
    forecast = DB.forecasts.get(hold.get("forecast_id"))
    if forecast is None:
        return
    acknowledged = forecast.get("acknowledged_at")
    if not acknowledged:
        return
    notice = int(forecast.get("cancellation_notice_days", 0) or 0)
    from datetime import timedelta

    deadline = parse_utc(acknowledged) + timedelta(days=notice)
    if DB.clock > deadline:
        rate = float(forecast.get("forfeit_rate", 0.0) or 0.0)
        hold["cancellation_forfeit_units"] = round(
            rate * int(hold.get("quantity_units", 0)), 1
        )


def _reclaim(caller, hold_id):
    hold = resource_or_404("holds", hold_id, "allocation hold")
    if hold.get("state") != "COMMITTED":
        raise CatalogError(ERR_INVALID_STATE, "Only a COMMITTED hold may be reclaimed.")
    node = resource_or_404("nodes", hold.get("supply_node_id"), "supply node")
    hold["state"] = "RECLAIMED"
    DB.touch(hold)
    move_capacity_ledger(DB.partners.get(hold.get("partner_id")), -int(hold.get("quantity_units", 0)))
    derive_product_allocated(DB.products.get(hold.get("product_sku_id")))
    recompute_node(node)
    return ok(serialize(hold))


def _expire(caller, hold_id):
    hold = resource_or_404("holds", hold_id, "allocation hold")
    if hold.get("state") != "COMMITTED":
        raise CatalogError(ERR_INVALID_STATE, "Only a COMMITTED hold may be expired.")
    node = resource_or_404("nodes", hold.get("supply_node_id"), "supply node")
    hold["state"] = "EXPIRED"
    DB.touch(hold)
    # The signed capacity ledger is deliberately untouched by expiry (PRD 2.8).
    derive_product_allocated(DB.products.get(hold.get("product_sku_id")))
    recompute_node(node)
    return ok(serialize(hold))


ROUTES = [
    ("POST", "/accelerators/allocation-holds", _create, ("PartnerOps",)),
    ("GET", "/accelerators/allocation-holds", _list, ("PartnerOps",)),
    ("GET", "/accelerators/allocation-holds/<hold_id>", _read, ("PartnerOps",)),
    ("POST", "/accelerators/allocation-holds/bulk", _bulk_create, ("PartnerOps",)),
    ("POST", "/accelerators/allocation-holds/<hold_id>/commit", _commit, ("PartnerOps",)),
    ("POST", "/accelerators/allocation-holds/<hold_id>/cancel", _cancel, ("PartnerOps",)),
    ("POST", "/accelerators/allocation-holds/<hold_id>/reclaim", _reclaim, ("PlatformAdmin",)),
    ("POST", "/accelerators/allocation-holds/<hold_id>/expire", _expire, ("PlatformAdmin",)),
]


def register(app):
    for method, path, handler, allowed in ROUTES:
        endpoint = "%s_%s" % (GROUP, path.replace("/", "_").replace("<", "").replace(">", ""))
        app.add_url_rule(path, endpoint + method, roles(*allowed)(handler), methods=[method])