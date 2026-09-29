"""Disclosure avoidance: small-cell suppression and controlled rounding."""
from db import ROUNDING_BASE, touch
from svc_common import cells_of
from util import D, rhu


def cell_sort_key(row):
    return (row.get("dimension_group") or "", row.get("dimension_key") or "")


def ordered_cells(request_id):
    rows = cells_of(request_id)
    rows.sort(key=cell_sort_key)
    return rows


def screen(request):
    """calculations.disclosure_avoidance.

    States are decided in memory first so that a cell selected for complementary
    suppression still advances its version exactly once for the whole screening run.
    """
    cells = ordered_cells(request["id"])
    plan = {}
    residual = False

    if request["avoidance_method"] == "CONTROLLED_ROUNDING":
        for cell in cells:
            rounded = int(rhu(D(cell["raw_count"]) / D(ROUNDING_BASE), 0)) * ROUNDING_BASE
            plan[cell["id"]] = ("RELEASED", rounded)
    else:
        minimum = request["min_cell_size"]
        for cell in cells:
            raw = cell["raw_count"]
            if 0 < raw < minimum:
                plan[cell["id"]] = ("PRIMARY_SUPPRESSED", None)
            else:
                plan[cell["id"]] = ("RELEASED", raw)
        groups = sorted({c["dimension_group"] for c in cells})
        for group in groups:
            members = [c for c in cells if c["dimension_group"] == group]
            primaries = [c for c in members
                         if plan[c["id"]][0] == "PRIMARY_SUPPRESSED"]
            candidates = [c for c in members
                          if plan[c["id"]][0] == "RELEASED" and c["raw_count"] > 0]
            if len(primaries) != 1:
                continue
            if not candidates:
                residual = True
                continue
            victim = sorted(candidates,
                            key=lambda c: (c["raw_count"], c["dimension_key"]))[0]
            plan[victim["id"]] = ("COMPLEMENTARY_SUPPRESSED", None)

    for cell in cells:
        state, released = plan[cell["id"]]
        cell["suppression_state"] = state
        cell["released_count"] = released
        touch(cell)

    request["released_cell_count"] = len(
        [c for c in cells if c["suppression_state"] == "RELEASED"])
    request["suppressed_cell_count"] = len(
        [c for c in cells if c["suppression_state"] in
         ("PRIMARY_SUPPRESSED", "COMPLEMENTARY_SUPPRESSED")])
    request["residual_disclosure_risk"] = residual


def aggregate_raw_count(request):
    return sum(c["raw_count"] for c in cells_of(request["id"]))
