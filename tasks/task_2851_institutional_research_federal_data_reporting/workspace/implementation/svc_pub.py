"""DashboardPublication materiality, window geometry and restatement helpers."""
from db import MATERIALITY_PCT, stamp_new, store, touch
from svc_common import publications_of, restatements_of
from util import D, num1, num2, parse_instant


def materiality(baseline, proposed):
    """calculations.restatement_materiality — 2 decimal places, inclusive >= 2.00."""
    if proposed is None:
        return None, False
    if baseline is None or D(baseline) == 0:
        return None, D(proposed) != 0
    delta = abs(D(proposed) - D(baseline)) / abs(D(baseline)) * D(100)
    delta_pct = num2(delta)
    return delta_pct, D(delta_pct) >= D(MATERIALITY_PCT)


def window_overlaps(component_id, metric_key, new_from, new_to):
    """calculations.publication_window_overlap — HALF-OPEN, adjacency allowed."""
    start = parse_instant(new_from)
    end = parse_instant(new_to) if new_to else None
    for peer in publications_of(component_id):
        if peer["metric_key"] != metric_key:
            continue
        if peer["publication_status"] == "WITHDRAWN":
            continue
        peer_start = parse_instant(peer["effective_from"])
        peer_end = parse_instant(peer["effective_to"]) if peer["effective_to"] else None
        left = end is None or peer_start < end
        right = peer_end is None or start < peer_end
        if left and right:
            return True
    return False


def supersede_submitted(publication, exclude_id=None):
    for req in restatements_of(publication["id"]):
        if req["id"] == exclude_id:
            continue
        if req["status"] == "SUBMITTED":
            req["status"] = "SUPERSEDED"
            touch(req)


def void_submitted(publication):
    for req in restatements_of(publication["id"]):
        if req["status"] == "SUBMITTED":
            req["status"] = "VOIDED"
            touch(req)


def create_restatement(publication, proposed_value, justification, requester, origin):
    delta_pct, notice = materiality(publication["published_value"], proposed_value)
    row = {
        "publication_id": publication["id"],
        "proposed_value": proposed_value,
        "baseline_value": publication["published_value"],
        "delta_pct": delta_pct,
        "public_notice_required": notice,
        "justification": justification,
        "requested_by_user_id": requester,
        "approved_by_user_id": None,
        "public_notice_reference": None,
        "rejection_reason": None,
        "status": "SUBMITTED",
        "origin": origin,
    }
    stamp_new(row)
    store.restatements[row["id"]] = row
    return row


def apply_restatement(publication, request):
    """PRD 3.7 ledger: net_applied_delta accumulates at 1 dp; published_value := proposed."""
    delta = num1(D(request["proposed_value"]) - D(request["baseline_value"]))
    publication["published_value"] = request["proposed_value"]
    publication["net_applied_delta"] = num1(
        D(publication.get("net_applied_delta") or 0) + D(delta))
    publication["restatement_count"] = (publication.get("restatement_count") or 0) + 1
    publication["publication_status"] = "RESTATED"
    touch(publication)


def publication_sort_key(row):
    parsed = parse_instant(row.get("effective_from"))
    return (parsed if parsed is not None else parse_instant("0001-01-01"),
            row.get("created_at") or "", row.get("_seq") or 0)
