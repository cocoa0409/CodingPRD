"""Cross-entity cascades and shared write helpers (PRD 2.10).

Covers: factory suspension cascade, workforce re-check cascade (worker and
certification suspension), evidence-document rejection recompute cascade,
claim challenge helper, report creation with supersession, and the lazy
evidence-expiry check applied whenever a document is read or counted.
"""
from state import DB, base_fields, touch, clock_date_str
import calcs


# ---------------------------------------------------------------------------
# Evidence freshness (PRD 2.4): expiry is checked lazily on read / count.
# ---------------------------------------------------------------------------

def doc_live_verified(doc):
    """Apply lazy expiry; return True iff the doc is VERIFIED and unexpired now."""
    if doc["status"] == "VERIFIED" and doc["valid_until"] < clock_date_str():
        doc["status"] = "EXPIRED"
        touch(doc)
    return doc["status"] == "VERIFIED"


def live_verified_claim_docs(claim_id, doc_type):
    """VERIFIED unexpired documents of doc_type attached to the claim."""
    return [
        d for d in DB["docs"].values()
        if d["claim_id"] == claim_id and d["doc_type"] == doc_type
        and doc_live_verified(d)
    ]


# ---------------------------------------------------------------------------
# DomesticContentReport creation with one-live supersession (PRD 3.6).
# Creating a report mutates the run (run.version +1); a CERTIFIED report on a
# DOMESTIC run refreshes model pricing (cost_differential_pricing).
# ---------------------------------------------------------------------------

def find_active_report(run_id, variant):
    for rep in DB["reports"].values():
        if rep["run_id"] == run_id and rep["variant"] == variant and rep["status"] == "ACTIVE":
            return rep
    return None


def create_report_record(run, variant, lot_overrides=frozenset(), labor_disputed=False):
    fields = calcs.compute_report_fields(
        run, variant, lot_overrides=lot_overrides, labor_disputed=labor_disputed
    )
    old = find_active_report(run["id"], variant)
    if old is not None:
        old["status"] = "SUPERSEDED"
        touch(old)
    rep = base_fields()
    rep.update({"run_id": run["id"], "variant": variant, "status": "ACTIVE"})
    rep.update(fields)
    DB["reports"][rep["id"]] = rep
    touch(run)
    if variant == "CERTIFIED":
        calcs.refresh_model_pricing(rep)
    return rep


# ---------------------------------------------------------------------------
# Factory suspension cascade (PRD 3.1)
# ---------------------------------------------------------------------------

def cascade_factory_suspend(factory):
    reverted_run_ids = []
    for run in DB["runs"].values():
        if run["factory_id"] != factory["id"]:
            continue
        if run["status"] == "IN_PRODUCTION":
            # Hop 1: held runs keep their lots and their IN_PRODUCTION orders.
            run["status"] = "QUALITY_HOLD"
            touch(run)
        elif run["status"] == "MATERIAL_RESERVED":
            # Hop 1 + hop 2: revert and re-credit every consumed lot.
            calcs.release_consumption(run)
            run["status"] = "PLANNED"
            touch(run)
            reverted_run_ids.append(run["id"])
    # Hop 2: SCHEDULED orders on the reverted runs fall back to ACCEPTED.
    for order in DB["orders"].values():
        if order["production_status"] == "SCHEDULED" \
                and order["production_run_id"] in reverted_run_ids:
            order["production_status"] = "ACCEPTED"
            order["production_run_id"] = None
            touch(order)


# ---------------------------------------------------------------------------
# Workforce re-check cascade (worker / certification suspension, PRD 3.2)
# ---------------------------------------------------------------------------

def reevaluate_runs_at_factory(factory_id):
    """IN_PRODUCTION runs that lost required coverage go to QUALITY_HOLD."""
    for run in DB["runs"].values():
        if run["factory_id"] == factory_id and run["status"] == "IN_PRODUCTION":
            if calcs.workforce_shortfall(factory_id):
                run["status"] = "QUALITY_HOLD"
                touch(run)


# ---------------------------------------------------------------------------
# Claim challenge (system-driven, PRD 3.8) with hop-3 contract cascade
# ---------------------------------------------------------------------------

def challenge_claim(claim):
    """SUBSTANTIATED/PUBLISHED -> CHALLENGED; pushes IN_FULFILLMENT contracts
    on the claim's model into COMPLIANCE_AUDIT. No-op for other states."""
    if claim["status"] not in ("SUBSTANTIATED", "PUBLISHED"):
        return False
    if claim["status"] == "PUBLISHED":
        claim["published_at"] = None
    claim["status"] = "CHALLENGED"
    touch(claim)
    for contract in DB["contracts"].values():
        if contract["model_id"] == claim["model_id"] and contract["status"] == "IN_FULFILLMENT":
            contract["status"] = "COMPLIANCE_AUDIT"
            touch(contract)
    return True


# ---------------------------------------------------------------------------
# Evidence rejection cascade (VERIFIED -> REJECTED only, PRD 3.8)
# ---------------------------------------------------------------------------

def cascade_doc_rejected_verified(doc):
    recomputed = []  # list of (run, new ACTIVE CERTIFIED report)
    # Hop 1 (origin cert on a lot): recompute every run that consumed the lot
    # and has an ACTIVE CERTIFIED report, with the lot's units forced into the
    # non-domestic bucket.
    if doc["material_lot_id"] and doc["doc_type"] == "SUPPLIER_ORIGIN_CERT":
        lid = doc["material_lot_id"]
        for run in list(DB["runs"].values()):
            if not any(e["lot_id"] == lid for e in run["consumed_lots"]):
                continue
            if find_active_report(run["id"], "CERTIFIED") is None:
                continue
            rep = create_report_record(run, "CERTIFIED", lot_overrides=frozenset([lid]))
            recomputed.append((run, rep))
    # Hop 1 (labor record on a run): recompute with labor and overhead forced
    # into the non-domestic bucket.
    if doc["production_run_id"] and doc["doc_type"] == "ASSEMBLY_LABOR_RECORD":
        run = DB["runs"].get(doc["production_run_id"])
        if run is not None and find_active_report(run["id"], "CERTIFIED") is not None:
            rep = create_report_record(run, "CERTIFIED", labor_disputed=True)
            recomputed.append((run, rep))
    # Hop 2: claims on the model of any recomputed run are re-pointed to the
    # superseding ACTIVE report and re-checked; failures become CHALLENGED.
    for run, rep in recomputed:
        for claim in list(DB["claims"].values()):
            if claim["model_id"] != run["model_id"]:
                continue
            if claim["status"] not in ("SUBSTANTIATED", "PUBLISHED"):
                continue
            claim["report_id"] = rep["id"]
            if not calcs.claim_threshold_pass(
                claim["claim_type"], rep["us_content_pct"], rep["final_assembly_domestic"]
            ):
                challenge_claim(claim)  # bumps version (re-point + challenge)
            else:
                touch(claim)  # re-point alone is still a mutation (PRD 2.5)
    # Hop 2 (direct): a rejected document linked to a claim challenges it outright.
    if doc["claim_id"]:
        claim = DB["claims"].get(doc["claim_id"])
        if claim is not None:
            challenge_claim(claim)
