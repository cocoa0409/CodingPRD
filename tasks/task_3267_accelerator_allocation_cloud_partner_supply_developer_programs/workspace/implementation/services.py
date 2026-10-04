"""Serialization, ledger movements, pool re-derivation and the audit chain."""

import hashlib

import calc
import constants as K
from error import CatalogError, ERR_INVALID_STATE, ERR_SAME_ACTOR_DEPLOYMENT_CHAIN
from store import DB

# ------------------------------------------------------------ serializers --
_INT_FIELDS = {
    "hbm_capacity_gb", "tdp_watts", "export_performance_density", "supply_ceiling_units",
    "reserved_evaluation_units", "allocated_units", "available_units",
    "lifecycle_min_remaining_days", "capacity_units", "held_units",
    "friction_penalty_score", "committed_fee_cents", "target_tdp_watts",
    "required_validation_minutes", "era_index", "evaluation_deadline_days",
    "quantity_units", "qualification_attempt_count", "entitlement_units_held",
    "capacity_ledger_net", "committed_volume_units", "seat_count",
    "annual_fee_cents", "support_credit_units", "billed_fee_cents",
    "settled_fee_cents", "entitlement_units", "bound_deployment_count",
    "preview_kit_units", "support_incidents_included", "requested_quantity_units",
    "committed_quantity_units", "cancellation_notice_days", "loan_units",
    "commitment_floor_days", "covered_units", "granted_units", "contracted_units",
    "epoch_index", "validation_minutes", "test_count", "termination_effect_units",
    "expected_partner_version", "expected_product_version", "expected_allocated_units",
    "expected_subscription_version",
}
_FLOAT_FIELDS = {
    "cancellation_forfeit_rate", "committed_rate_v2", "total_committed_rate",
    "forfeit_rate", "late_fee_units", "score", "value_estimate", "value_confirm",
    "on_time_ratio",
}
_BOOL_FIELDS = {"preview_stack_flag", "trial_flag", "service_ready", "group_satisfied"}


def serialize(row, extra=None):
    """Copy with stable JSON-friendly scalars.

    Keys beginning with an underscore are server-private bookkeeping (mint
    order, internal gate flags) and never appear on the wire.
    """
    out = {}
    for key, value in row.items():
        if key.startswith("_"):
            continue
        if isinstance(value, float):
            out[key] = round(value, 6)
        else:
            out[key] = value
    if extra:
        out.update(extra)
    return out


# --------------------------------------------------------------- ledgers ---
def move_capacity_ledger(partner, delta):
    if partner is None or delta == 0:
        return
    partner["capacity_ledger_net"] = int(partner.get("capacity_ledger_net", 0) or 0) + int(delta)
    DB.touch(partner)


def move_entitlement_ledger(partner, delta):
    if partner is None or delta == 0:
        return
    partner["entitlement_units_held"] = int(partner.get("entitlement_units_held", 0) or 0) + int(delta)
    DB.touch(partner)


# ------------------------------------------------------------ pool state ---
def recompute_node(node, settle=False):
    """Re-derive temperature, ceiling, held units, fee and friction score."""
    tier, ceiling, half_life, total = calc.supply_hotness_tier(DB, node)
    node["hotness_tier"] = tier
    node["temp_band_ceiling"] = ceiling
    node["total_committed_rate"] = round(float(total), 4)
    node["held_units"] = sum(
        int(h.get("quantity_units", 0))
        for h in DB.holds.values()
        if h.get("supply_node_id") == node["id"]
        and h.get("state") in ("REQUESTED", "COMMITTED")
        and not h.get("_band_violation")
    )
    node["committed_fee_cents"] = calc.allocation_commitment_fee(DB, node)
    node["friction_penalty_score"] = round(sum(
        float(p.get("score", 0))
        for p in DB.penalties.values()
        if p.get("supply_node_id") == node["id"] and p.get("penalty_state") == "ACTIVE"
    ), 1)
    if settle:
        for penalty in DB.penalties.values():
            if penalty.get("supply_node_id") != node["id"]:
                continue
            if penalty.get("penalty_state") == "ACTIVE":
                penalty["penalty_state"] = "SETTLED"
                penalty["updated_at"] = DB.now_text()
    DB.touch(node)
    node["half_life_next"] = half_life
    return node


def declared_node_state(node):
    """Applied at creation so a ceiling exists before any hold (PRD 3.3)."""
    tier = node.get("requested_hotness_tier", "COOL")
    node["hotness_tier"] = tier
    node["temp_band_ceiling"] = K.BAND_CEILING[tier]
    node["total_committed_rate"] = 0.0
    node["friction_penalty_score"] = 0.0
    node["held_units"] = 0
    node["committed_fee_cents"] = 0
    return node


def add_penalty(node, partner_id, hold_id, reason, score):
    pen = DB.mint({
        "supply_node_id": node["id"],
        "partner_id": partner_id,
        "hold_id": hold_id,
        "score": round(float(score), 1),
        "penalty_reason": reason,
        "penalty_state": "ACTIVE",
        "node_id": node["id"],
    })
    DB.penalties[pen["id"]] = pen
    return pen


# ------------------------------------------------------------ audit chain --
def _digest(partner_id, payload):
    chain = [entry.get("entry_digest", "") for entry in DB.audits.values()
             if entry.get("partner_id") == partner_id]
    chain.sort()
    material = "|".join(chain[-1:]) + "|" + payload
    return hashlib.sha256(material.encode("utf-8")).hexdigest()[:32]


def append_audit(partner_id, action_code, subject_entity, subject_id, caller=None):
    payload = "%s:%s:%s:%s" % (action_code, subject_entity, subject_id, DB.now_text())
    entry = DB.mint({
        "partner_id": partner_id,
        "action_code": action_code,
        "subject_entity": subject_entity,
        "subject_id": subject_id,
        "actor_user_id": caller.user_id if caller is not None else None,
        "actor_role": caller.role if caller is not None else None,
        "recorded_at": DB.now_text(),
        "entry_digest": _digest(partner_id, payload),
    })
    DB.audits[entry["id"]] = entry
    return entry


def activation_actor(deployment_id):
    """The X-User-ID recorded on the deployment's activation entry (PRD 3.7)."""
    entries = [
        entry for entry in DB.audits.values()
        if entry.get("subject_id") == deployment_id
        and entry.get("action_code") in ("DEPLOYMENT_ACTIVATED", "DEPLOYMENT_HANDOVER")
    ]
    if not entries:
        return None
    entries.sort(key=lambda row: row.get("recorded_at", ""))
    return entries[-1].get("actor_user_id")


def check_separation_of_duties(deployment, caller):
    """The terminating user must differ from the deployment's activation actor.

    The authoritative value is the deployment's activation_actor_user_id, which
    POST /deployments/{id}/handover replaces; the audit chain is the fallback
    when no field was recorded (PRD 3.7).
    """
    recorded = deployment.get("activation_actor_user_id")
    if recorded is None:
        recorded = activation_actor(deployment["id"])
    if recorded is not None and caller is not None and recorded == caller.user_id:
        raise CatalogError(
            ERR_SAME_ACTOR_DEPLOYMENT_CHAIN,
            "The terminating user activated this deployment.",
        )


# --------------------------------------------------------- product helpers --
def derive_available(product):
    available = (
        int(product.get("supply_ceiling_units", 0) or 0)
        - int(product.get("allocated_units", 0) or 0)
        - int(product.get("reserved_evaluation_units", 0) or 0)
    )
    product["available_units"] = max(0, available)
    return product["available_units"]


def derive_product_allocated(product):
    total = 0
    for hold in DB.holds.values():
        if hold.get("product_sku_id") != product["id"]:
            continue
        if hold.get("state") == "COMMITTED" and not hold.get("_band_violation"):
            total += int(hold.get("quantity_units", 0))
    product["allocated_units"] = total
    return total


def refresh_density(product, declared=False):
    if declared:
        density, band = calc.declared_density_band(product.get("tdp_watts", 0))
        product["export_performance_density_band"] = band
        return
    density, band = calc.computed_density_band(product.get("tdp_watts", 0))
    product["export_performance_density"] = density
    product["export_performance_density_band"] = band


# --------------------------------------------------------- subscription ----
def deployment_service_ready(deployment):
    for sub in DB.subscriptions.values():
        if sub.get("deployment_id") != deployment["id"]:
            continue
        if sub.get("status") == "ACTIVE":
            return True
    return False


def recompute_service_ready(deployment, caller=None):
    ready = deployment_service_ready(deployment)
    deployment["service_ready"] = ready
    DB.touch(deployment)
    return ready


def bound_stack_ids_for(deployment):
    """The manifest stack ids that cleared the NDA gate (PRD 3.7).

    A manifest stack carrying the preview flag must have a BOUND confidentiality
    acknowledgement for the deployment's partner; entries without one are
    dropped from the bound set rather than rejecting the whole request.
    """
    partner_id = deployment.get("partner_id")
    bound = []
    for entry in deployment.get("stack_manifest", []) or []:
        license_id = entry.get("license_id")
        license_row = DB.stack_licenses.get(license_id)
        if license_row is None:
            continue
        if license_row.get("preview_stack_flag"):
            if _internal_ack_bound(partner_id, license_id) is None:
                continue
        bound.append(license_id)
    return sorted(set(bound))


def _internal_ack_bound(partner_id, stack_license_id):
    for ack in DB.acks.values():
        if ack.get("partner_id") != partner_id:
            continue
        if ack.get("stack_license_id") != stack_license_id:
            continue
        if ack.get("ack_status") == "BOUND":
            return ack
    return None


def released_entitlement_for(deployment):
    """Step 1 of entitlement_pool_release (PRD 3.7)."""
    total = 0
    for sub in DB.subscriptions.values():
        if sub.get("deployment_id") != deployment["id"]:
            continue
        if sub.get("status") not in ("ACTIVE", "SUSPENDED"):
            continue
        for license_id in sub.get("bound_stack_ids", []) or []:
            license_row = DB.stack_licenses.get(license_id)
            if license_row is not None:
                total += int(license_row.get("entitlement_units", 0))
                break
    return total


def recompute_bound_deployment_count():
    for license_row in DB.stack_licenses.values():
        count = 0
        for deployment in DB.deployments.values():
            if deployment.get("activation_state") != "ACTIVATED":
                continue
            if license_row["id"] in (deployment.get("bound_stack_ids") or []):
                count += 1
        license_row["bound_deployment_count"] = count