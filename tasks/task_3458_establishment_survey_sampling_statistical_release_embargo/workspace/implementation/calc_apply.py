"""Benchmark wedge realignment (PRD 3.7) and methodology reconstruction (3.8),
plus the shared 'published release re-flag' cascade."""
from decimal import Decimal

from errors import (
    raise_err, ERR_CYCLE_NOT_CERTIFIED, ERR_BENCHMARK_CELL_MISSING,
    ERR_BENCHMARK_UNDEFINED_WEDGE,
)
from store import DB, now, touch, round0, round6, PPM_BASELINE


def flag_published_release(cycle_id):
    """When estimates under an already-published release change: set
    revision_notice_required and auto-revert disclosure APPROVED -> PENDING."""
    for rel in DB["releases"].values():
        if rel["cycle_id"] == cycle_id and rel["pub_status"] == "PUBLISHED":
            changed = False
            if not rel["revision_notice_required"]:
                rel["revision_notice_required"] = True
                changed = True
            if rel["disclosure_status"] == "APPROVED":
                rel["disclosure_status"] = "PENDING"
                changed = True
            if changed:
                touch(rel)


def _find_cycle(program_code, reference_month):
    return next(
        (c for c in DB["cycles"].values()
         if c["program_code"] == program_code and c["reference_month"] == reference_month),
        None,
    )


def _find_cell(cycle_id, industry_code, size_class):
    return next(
        (c for c in DB["cells"].values()
         if c["cycle_id"] == cycle_id
         and c["industry_code"] == industry_code
         and c["size_class"] == size_class),
        None,
    )


def apply_benchmark(run):
    """Apply a DRAFT benchmark run (caller has checked run_status)."""
    program_code = run["program_code"]
    bench_month = run["benchmark_month"]
    bench_year = int(bench_month[:4])
    bench_mon = int(bench_month[5:7])

    bench_cycle = _find_cycle(program_code, bench_month)
    if bench_cycle is None or bench_cycle["cycle_status"] not in ("CERTIFIED", "PUBLISHED"):
        raise_err(ERR_CYCLE_NOT_CERTIFIED,
                  "benchmark-month cycle must exist and be CERTIFIED or PUBLISHED")

    # Preconditions: every admin cell must match a PRELIMINARY/REVISED cell at
    # the benchmark month; a zero estimate with a positive admin count is an
    # undefined wedge.
    wedges = {}
    for entry in run["admin_cell_counts"]:
        key = (entry["industry_code"], entry["size_class"])
        cell = _find_cell(bench_cycle["id"], *key)
        if cell is None or cell["estimate_status"] not in ("PRELIMINARY", "REVISED"):
            raise_err(ERR_BENCHMARK_CELL_MISSING,
                      f"no PRELIMINARY/REVISED cell estimate for {key[0]}/{key[1]} "
                      f"at the benchmark month")
        base_est = cell["employment_estimate"]
        if base_est == 0:
            if entry["admin_employment"] > 0:
                raise_err(ERR_BENCHMARK_UNDEFINED_WEDGE,
                          f"benchmark cell {key[0]}/{key[1]} has zero estimate with "
                          f"positive administrative count")
            wedges[key] = (cell, Decimal("1.000000"))
        else:
            wedges[key] = (
                cell,
                round6(Decimal(entry["admin_employment"]) / Decimal(base_est)),
            )

    affected_cycle_ids = {bench_cycle["id"]}
    for entry in run["admin_cell_counts"]:
        key = (entry["industry_code"], entry["size_class"])
        base_cell, wedge = wedges[key]
        # Benchmark-month cell: anchored outright.
        base_cell["employment_estimate"] = entry["admin_employment"]
        base_cell["estimate_status"] = "FINAL"
        base_cell["wedge_factor"] = wedge
        base_cell["revision_no"] += 1
        touch(base_cell)
        # Earlier-month cells of the same program+series in the same calendar
        # year, still PRELIMINARY/REVISED: scaled by the wedge. Each month is
        # rounded independently; no annual reconciliation pass.
        for cell in DB["cells"].values():
            if cell["id"] == base_cell["id"]:
                continue
            if cell["program_code"] != program_code:
                continue
            if (cell["industry_code"], cell["size_class"]) != key:
                continue
            if cell["estimate_status"] not in ("PRELIMINARY", "REVISED"):
                continue
            other = _cycle_of(cell)
            if other is None:
                continue
            oy, om = int(other["reference_month"][:4]), int(other["reference_month"][5:7])
            if oy == bench_year and om < bench_mon:
                cell["employment_estimate"] = round0(
                    Decimal(cell["employment_estimate"]) * wedge)
                cell["estimate_status"] = "FINAL"
                cell["wedge_factor"] = wedge
                cell["revision_no"] += 1
                touch(cell)
                affected_cycle_ids.add(cell["cycle_id"])

    for cid in affected_cycle_ids:
        flag_published_release(cid)

    run["run_status"] = "APPLIED"
    run["applied_at"] = now()
    touch(run)


def _cycle_of(cell):
    return DB["cycles"].get(cell["cycle_id"])


def activate_notice(notice):
    """Run the ACTIVATE cascade (caller has checked status + effectiveness)."""
    program_code = notice["program_code"]
    if notice["scope"] == "ALL_SERIES":
        in_scope = None
    else:
        in_scope = {(s["industry_code"], s["size_class"]) for s in notice.get("series") or []}

    def covered(ind, size):
        return in_scope is None or (ind, size) in in_scope

    ppm = notice["reconstruction_factor_ppm"]
    affected_cycle_ids = set()
    for cell in DB["cells"].values():
        if cell["program_code"] != program_code:
            continue
        if cell["estimate_status"] != "FINAL":
            continue
        if not covered(cell["industry_code"], cell["size_class"]):
            continue
        cell["employment_estimate"] = round0(
            Decimal(cell["employment_estimate"]) * Decimal(ppm) / Decimal(PPM_BASELINE))
        cell["estimate_status"] = "RECONSTRUCTED"
        cell["revision_no"] += 1
        touch(cell)
        affected_cycle_ids.add(cell["cycle_id"])

    for fs in DB["factor_sets"].values():
        if fs["program_code"] != program_code:
            continue
        if fs["set_status"] != "FINAL":
            continue
        if not covered(fs["industry_code"], fs["size_class"]):
            continue
        fs["set_status"] = "SUPERSEDED"
        touch(fs)

    for cid in affected_cycle_ids:
        flag_published_release(cid)

    notice["notice_status"] = "EFFECTIVE"
    notice["activated_at"] = now()
    touch(notice)
