"""Geo zone effective_ratio compounding and cycle checks (§3.1)."""
from decimal import Decimal
from db import store
from errors import geo_cycle, not_found
from services.common import round6


def compute_effective_ratio(zone: dict) -> Decimal:
    """Recursive with cycle protection. Each step rounds to 6dp half-up."""
    seen = set()
    return _eff(zone, seen)


def _eff(zone: dict, seen: set) -> Decimal:
    zid = zone["id"]
    if zid in seen:
        raise geo_cycle()
    seen.add(zid)
    parent_id = zone.get("parent_zone_id")
    own = Decimal(str(zone["differential_ratio"]))
    if parent_id is None:
        return round6(own)
    parent = store.geo_zones.get(parent_id)
    if parent is None:
        # parent missing — treat as broken reference at create/patch time, but
        # defensively raise not_found here
        raise not_found("parent zone not found")
    parent_eff = _eff(parent, seen)
    return round6(parent_eff * own)


def would_create_cycle(zone_id: str, new_parent_id) -> bool:
    """True if setting zone's parent to new_parent_id closes a chain that revisits zone_id."""
    if new_parent_id is None:
        return False
    if new_parent_id == zone_id:
        return True
    cur = store.geo_zones.get(new_parent_id)
    seen = set()
    while cur is not None:
        cid = cur["id"]
        if cid == zone_id:
            return True
        if cid in seen:
            return True
        seen.add(cid)
        pid = cur.get("parent_zone_id")
        if pid is None:
            return False
        cur = store.geo_zones.get(pid)
    return False


def recompute_subtree(zone_id: str):
    """Recompute effective_ratio for the zone and all descendants, root-to-leaf."""
    zone = store.geo_zones.get(zone_id)
    if zone is None:
        return
    zone["effective_ratio"] = float(compute_effective_ratio(zone))
    for child in list(store.geo_zones.values()):
        if child.get("parent_zone_id") == zone_id:
            recompute_subtree(child["id"])
