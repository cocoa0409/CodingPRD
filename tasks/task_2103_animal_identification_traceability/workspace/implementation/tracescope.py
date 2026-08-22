"""Traceback scope projection (PRD 3.7 / calculations.trace_scope_projection).

Residency intervals are half-open [start, end) built from the animal's
non-reversed sightings ordered by observed_at ASC with sequence_no ASC as the
tie-break - deliberately a different ordering from the location projection of
PRD 2.11, which replays in append order.
"""
from datetime import timedelta

from db import store

ENV_WINDOW_DAYS = 14
LOCATION_OPENERS = ("TAG_APPLIED", "ARRIVAL")
LOCATION_CLOSERS = ("DEPARTURE", "HARVEST")


def residencies(animal_id):
    rows = [s for s in store.sightings.values()
            if s["animal_id"] == animal_id and not s["reversed"]]
    rows.sort(key=lambda s: (s["observed_at"], s["sequence_no"]))
    out = []
    for i, row in enumerate(rows):
        if row["sighting_type"] not in LOCATION_OPENERS:
            continue
        end = None
        end_row = None
        for nxt in rows[i + 1:]:
            if nxt["sighting_type"] in LOCATION_CLOSERS:
                end = nxt["observed_at"]
                end_row = nxt
                break
        out.append({
            "premises_id": row["premises_id"],
            "start": row["observed_at"],
            "end": end,
            "start_row": row,
            "end_row": end_row,
        })
    return out


def _overlaps(start_a, end_a, start_b, end_b):
    """Strictly positive overlap of two half-open intervals; None == +infinity."""
    start = max(start_a, start_b)
    if end_a is None and end_b is None:
        return True
    if end_a is None:
        end = end_b
    elif end_b is None:
        end = end_a
    else:
        end = min(end_a, end_b)
    return end > start


def contacts(explored, candidate, variant):
    if variant == "STRICT_INTERVAL":
        return _overlaps(explored["start"], explored["end"],
                         candidate["start"], candidate["end"])
    widened_start = explored["start"] - timedelta(days=ENV_WINDOW_DAYS)
    widened_end = None if explored["end"] is None else explored["end"] + timedelta(days=ENV_WINDOW_DAYS)
    return _overlaps(widened_start, widened_end, candidate["start"], candidate["end"])


def run_projection(trace_request, index_animal):
    """Breadth-first walk over the sighting graph; returns the frozen hit set
    plus the counters that are frozen alongside it."""
    run_at = store.now()
    cutoff = run_at - timedelta(days=trace_request["lookback_days"])
    variant = ("STRICT_INTERVAL" if trace_request["pathogen_class"] == "DIRECT_CONTACT"
               else "PREMISES_WINDOW")
    direction = trace_request["direction"]
    max_hops = trace_request["max_hops"]

    all_res = {a["id"]: residencies(a["id"]) for a in store.animals.values()}
    index_id = index_animal["id"]
    index_res = all_res.get(index_id, [])
    anchor = index_res[0]["start"] if index_res else None

    hits = []
    hit_ids = set()
    traversed = set()
    frontier = [index_id]
    depth = 0
    while depth < max_hops and frontier:
        depth += 1
        next_frontier = []
        for animal_id in frontier:
            for res in all_res.get(animal_id, []):
                if res["end"] is not None and res["end"] <= cutoff:
                    continue
                if anchor is not None:
                    if direction == "BACKWARD" and res["start"] > anchor:
                        continue
                    if direction == "FORWARD" and res["start"] < anchor:
                        continue
                for row in (res["start_row"], res["end_row"]):
                    if row is not None and row["source_movement_id"]:
                        traversed.add(row["source_movement_id"])
                candidates = []
                for other in store.animals.values():
                    if other["id"] == index_id:
                        continue
                    for cand_res in all_res.get(other["id"], []):
                        if cand_res["premises_id"] != res["premises_id"]:
                            continue
                        if not contacts(res, cand_res, variant):
                            continue
                        candidates.append((cand_res["start"], other["created_at"],
                                           other["_seq"], other, cand_res))
                candidates.sort(key=lambda c: (c[0], c[1], c[2]))
                for _start, _created, _seq, other, cand_res in candidates:
                    if other["id"] in hit_ids:
                        continue
                    hit_ids.add(other["id"])
                    hits.append({
                        "animal_id": other["id"],
                        "premises_id": res["premises_id"],
                        "hop_depth": depth,
                        "first_contact_at": max(res["start"], cand_res["start"]),
                        "responded": False,
                        "resolved": False,
                        "_animal_created_at": other["created_at"],
                        "_animal_seq": other["_seq"],
                    })
                    next_frontier.append(other["id"])
        frontier = next_frontier

    hits.sort(key=lambda h: (h["hop_depth"], h["first_contact_at"],
                             h["_animal_created_at"], h["_animal_seq"]))
    premises_touched = {h["premises_id"] for h in hits}
    premises_touched.update(r["premises_id"] for r in index_res)
    return {
        "variant_applied": variant,
        "hits": hits,
        "hit_count": len(hits),
        "premises_touched_count": len(premises_touched),
        "hops_total": len(traversed),
        "traversed_movement_ids": sorted(traversed),
    }
