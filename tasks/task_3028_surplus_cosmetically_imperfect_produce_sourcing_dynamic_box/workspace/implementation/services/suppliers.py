"""§3.1 Supplier standing: computed, never set by hand."""

import rules
import store


def empty_supplier(region=None):
    return {"region": region}


def recompute_supplier(supplier):
    """Recompute the four lifetime counters, the score and the tier."""
    if supplier is None:
        return
    lots = [l for l in store.SUPPLY_LOTS.values()
            if l["supplier_id"] == supplier["id"]]
    awarded = [l for l in lots if l["_status_awarded"]]
    accepted = [l for l in awarded if l["_accepted"]]
    on_time = [l for l in awarded if l["_on_time"]]
    claims = [c for c in store.QUALITY_CLAIMS.values()
              if c["_supplier_id"] == supplier["id"] and c["_upheld"]]

    supplier["lots_awarded_total"] = len(awarded)
    supplier["lots_accepted_total"] = len(accepted)
    supplier["lots_on_time_total"] = len(on_time)
    supplier["claims_upheld_total"] = len(claims)

    score = rules.reliability_score_bp(supplier)
    supplier["reliability_score_bp"] = score
    supplier["relationship_status"] = rules.relationship_status_for(score)
    store.touch(supplier)


def recompute_for_lot(lot):
    recompute_supplier(store.SUPPLIERS.get(lot["supplier_id"]))


def recompute_for_claim(claim):
    recompute_supplier(store.SUPPLIERS.get(claim["_supplier_id"]))