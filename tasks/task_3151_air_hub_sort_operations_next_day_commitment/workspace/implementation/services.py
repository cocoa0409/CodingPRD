"""Shared business helpers: postures, cascades, failure emission."""

from decimal import Decimal

import calculations as calc


# =============================================================================
# Posture helpers
# =============================================================================

def handling_posture(handling_status):
    if handling_status == "ROUTED_TO_IRREGULAR":
        return "IRREGULAR_LANE"
    if handling_status == "ROUTED_TO_HAZMAT":
        return "HAZMAT_LANE"
    return "STANDARD"


def commitment_posture(commitment_status):
    if commitment_status in ("REROUTED", "UPGRADED_HELD"):
        return "REROUTE_PENDING"
    if commitment_status == "DOWNGRADED":
        return "DOWNGRADE_PENDING"
    return "COMMITTED_OK"


def refresh_package_postures(package):
    package["handling_posture"] = handling_posture(package.get("handling_status"))
    package["commitment_posture"] = commitment_posture(package.get("commitment_status"))
    return package


# =============================================================================
# Recompute fan-out
# =============================================================================

def hub_mutated(store, hub):
    """Volume + posture + every shift on the hub, then bump the hub version."""
    calc.recompute_hub(store, hub)
    store.touch("hubs", hub)
    return hub


def hub_and_shifts(store, hub):
    calc.recompute_hub(store, hub)
    store.touch("hubs", hub)
    for shift in store.all("shifts"):
        if shift.get("hub_id") == hub["id"]:
            calc.recompute_shift(store, hub, shift)
    return hub


def hub_touched(store, hub):
    """Volume + posture recompute with an ordinary mutation bump."""
    calc.recompute_hub(store, hub)
    store.touch("hubs", hub)
    return hub


# =============================================================================
# Failure emission
# =============================================================================

def new_failure(store, hub, package, cause_code, *, status="OPEN",
                attributed_role=None, refund_amount_cents=None):
    role = attributed_role or calc.ATTRIBUTION[cause_code]
    failure = store.create("failures", {
        "hub_id": hub["id"],
        "package_id": package["id"] if package else None,
        "cause_code": cause_code,
        "attributed_role": role,
        "failure_minutes": store.minute(),
        "refund_eligible": role == "CARRIER",
        "refund_amount_cents": 0,
        "status": status,
    })
    if refund_amount_cents is None:
        failure["refund_amount_cents"] = calc.money_back_refund(store, failure)
    else:
        failure["refund_amount_cents"] = refund_amount_cents
    return failure


def new_failure_batch(store, hub, package, count, pricing, cause_code,
                      attributed_role):
    """Create `count` failures, each priced independently then summed.

    `pricing` is (gross_cents, provisional) and is applied per failure so the
    batch total rounds each one before summing (pinned evaluation order).
    """
    out = []
    gross, provisional = pricing
    value = (calc.round_half_up(Decimal(gross) * calc.MBG_PROVISIONAL_PCT)
             if provisional else gross)
    for _ in range(count):
        out.append(new_failure(store, hub, package, cause_code,
                               attributed_role=attributed_role,
                               refund_amount_cents=value))
    return out


def service_failure_status(store, failure, claim_sequence):
    """Re-derive the failure status from its last claim in the pinned order."""
    claims = [c for c in store.all("claims")
              if c.get("service_failure_id") == failure["id"]
              and int(c.get("claim_index") or 0) <= int(claim_sequence or 0)]
    if not claims:
        return None
    claims.sort(key=lambda c: (int(c.get("claim_index") or 0),
                               c.get("created_at") or "",
                               c.get("id") or ""))
    return claims[-1]["outcome"]


def refresh_failure(store, failure):
    failure["refund_amount_cents"] = calc.money_back_refund(store, failure)
    return failure


def package_failures(store, package_id):
    return [f for f in store.all("failures") if f.get("package_id") == package_id]


def has_finalized_failure(store, package_id):
    return any(f.get("status") == "FINALIZED" for f in package_failures(store, package_id))


# =============================================================================
# Package commitment cascades
# =============================================================================

def cascade_downgrade(package):
    """COMMITTED -> DOWNGRADED with the +360 assurance extension."""
    package["commitment_status"] = "DOWNGRADED"
    package["service_level"] = "SECOND_DAY_AIR"
    package["final_commitment_minutes"] = (
        int(package["commitment_cutoff_minutes"]) + calc.REROUTE_ASSURANCE_BUFFER_MINUTES)
    return refresh_package_postures(package)


def cascade_reroute(package):
    """(COMMITTED|DOWNGRADED) -> REROUTED with the +240 normal extension."""
    package["commitment_status"] = "REROUTED"
    package["handling_status"] = "DIVERTED"
    package["final_commitment_minutes"] = (
        int(package["commitment_cutoff_minutes"]) + calc.NORMAL_REROUTE_BUFFER_MINUTES)
    return refresh_package_postures(package)


def cascade_upgrade_hold(package, extension=calc.REROUTE_ASSURANCE_BUFFER_MINUTES):
    """-> UPGRADED_HELD parked at the hub with a cutoff-based extension."""
    package["commitment_status"] = "UPGRADED_HELD"
    package["handling_status"] = "HOLD_AT_HUB"
    package["final_commitment_minutes"] = (
        int(package["commitment_cutoff_minutes"]) + extension)
    return refresh_package_postures(package)


def cascade_commit(package):
    """Restore a stranded package to COMMITTED/NORMAL with no extension."""
    package["commitment_status"] = "COMMITTED"
    package["handling_status"] = "NORMAL"
    package["final_commitment_minutes"] = None
    return refresh_package_postures(package)