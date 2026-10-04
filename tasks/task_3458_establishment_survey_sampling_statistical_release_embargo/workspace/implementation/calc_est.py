"""Estimation pipeline (PRD 3.5): cell estimates with imputation, variance,
response rates, seasonal concurrent snapshot, and suppression resolution."""
from decimal import Decimal

from store import (
    DB, new_entity, touch, now, round0, round6,
    INDUSTRIES, SIZE_CLASSES,
    MIN_CELL_RESPONDENTS, DOMINANCE_THRESHOLD,
)
from validate import month_prev, month_str


def _accepted_reports(cycle_id):
    return {
        r["enrollment_id"]: r
        for r in DB["reports"].values()
        if r["cycle_id"] == cycle_id and r["report_status"] == "ACCEPTED"
    }


def _current_factor_set(program_code, industry_code, size_class, year):
    for fs in DB["factor_sets"].values():
        if (
            fs["program_code"] == program_code
            and fs["industry_code"] == industry_code
            and fs["size_class"] == size_class
            and fs["year"] == year
            and fs["set_status"] != "SUPERSEDED"
        ):
            return fs
    return None


def _stratum_mean(respondents):
    """round_half_up(SUM(w*y)/SUM(w) over respondents, 0); 0 when none."""
    if not respondents:
        return 0
    num = sum(w * y for w, y in respondents)
    den = sum(w for w, _y in respondents)
    if den == 0:
        return 0
    return round0(num / den)


def _compute_cell_values(cell_enrollments, accepted, prev_accepted, variant):
    """Return (estimate, variance, respondent_count, values, dominance_flag).

    values: list of (enrollment, y) with reported-or-imputed employment.
    Rounding order (pinned): imputed values are rounded to whole persons
    BEFORE weighting; the weighted sum is rounded once at the end.
    """
    respondents = []   # (enrollment, y)
    nonrespondents = []
    for enr in cell_enrollments:
        rep = accepted.get(enr["id"])
        if rep is not None:
            respondents.append((enr, rep["employment"]))
        else:
            nonrespondents.append(enr)

    mean_y = _stratum_mean([(e["base_weight"], y) for e, y in respondents])

    # Link relative over matched pairs (enrollments ACCEPTED in both cycles).
    lr = None
    if variant == "LINK_RELATIVE":
        sum_cur = 0
        sum_prev = 0
        for enr, y in respondents:
            prev = prev_accepted.get(enr["id"])
            if prev is not None:
                sum_cur += y
                sum_prev += prev["employment"]
        if sum_prev > 0:
            lr = Decimal(sum_cur) / Decimal(sum_prev)

    values = [(enr, y) for enr, y in respondents]
    for enr in nonrespondents:
        y = None
        if variant == "LINK_RELATIVE" and lr is not None:
            prev = prev_accepted.get(enr["id"])
            if prev is not None:
                y = round0(Decimal(prev["employment"]) * lr)
        if y is None:  # STRATUM_MEAN pass or per-establishment fallback
            y = mean_y
        values.append((enr, y))

    est_sum = Decimal(0)
    var_sum = Decimal(0)
    max_contrib = Decimal(0)
    for enr, y in values:
        w = enr["base_weight"]
        est_sum += w * y
        var_sum += w * (w - 1) * (y ** 2)
        contrib = w * y
        if contrib > max_contrib:
            max_contrib = contrib

    estimate = round0(est_sum)
    variance = round0(var_sum)
    if estimate == 0:
        dominance = False
    else:
        dominance = max_contrib >= DOMINANCE_THRESHOLD * Decimal(estimate)
    return estimate, variance, len(respondents), values, dominance, bool(nonrespondents)


def _suppression_fixed_point(cells):
    """PRIMARY then COMPLEMENTARY fixed point (PRD 3.5). Totals (step 2) are
    computed at bulletin time from the full cell set; suppression never
    changes totals."""
    for c in cells:
        if c["respondent_count"] < MIN_CELL_RESPONDENTS or c["dominance_flag"]:
            c["suppression_status"] = "PRIMARY"
        else:
            c["suppression_status"] = "NONE"

    def suppressed(c):
        return c["suppression_status"] in ("PRIMARY", "COMPLEMENTARY")

    def mark_smallest_publishable(group, tie_key):
        publishable = [c for c in group if c["suppression_status"] == "NONE"]
        if not publishable:
            return False
        target = min(publishable, key=lambda c: (c["employment_estimate"], tie_key(c)))
        target["suppression_status"] = "COMPLEMENTARY"
        touch(target)
        return True

    changed = True
    while changed:
        changed = False
        for ind in INDUSTRIES:  # industry rows first, industry_code ASC
            row = [c for c in cells if c["industry_code"] == ind]
            if len([c for c in row if suppressed(c)]) == 1:
                changed |= mark_smallest_publishable(
                    row, lambda c: SIZE_CLASSES.index(c["size_class"]))
        for size in SIZE_CLASSES:  # then size columns, SMALL < MEDIUM < LARGE
            col = [c for c in cells if c["size_class"] == size]
            if len([c for c in col if suppressed(c)]) == 1:
                changed |= mark_smallest_publishable(
                    col, lambda c: (INDUSTRIES.index(c["industry_code"]),
                                    SIZE_CLASSES.index(c["size_class"])))


def compute_estimates(cycle):
    """Run COMPUTE_ESTIMATES for a cycle in PROCESSING or REVISION_OPEN."""
    program_code = cycle["program_code"]
    revision_pass = cycle["cycle_status"] == "REVISION_OPEN"
    variant = "STRATUM_MEAN" if revision_pass else "LINK_RELATIVE"

    denominator = [
        e for e in DB["enrollments"].values()
        if e["program_code"] == program_code and e["enrollment_status"] == "ENROLLED"
    ]
    accepted = _accepted_reports(cycle["id"])
    prev_key = month_str(month_prev((int(cycle["reference_month"][:4]),
                                     int(cycle["reference_month"][5:7]))))
    prev_cycle = next(
        (c for c in DB["cycles"].values()
         if c["program_code"] == program_code and c["reference_month"] == prev_key),
        None,
    )
    prev_accepted = _accepted_reports(prev_cycle["id"]) if prev_cycle else {}

    # Partition denominator into cells keyed (industry_code, size_class).
    cell_groups = {}
    for enr in denominator:
        cell_groups.setdefault((enr["industry_code"], enr["size_class"]), []).append(enr)

    ref_year = int(cycle["reference_month"][:4])
    ref_month = int(cycle["reference_month"][5:7])

    for (ind, size), members in sorted(cell_groups.items()):
        estimate, variance, resp_count, _values, dominance, had_nonresp = (
            _compute_cell_values(members, accepted, prev_accepted, variant)
        )
        key = (cycle["id"], ind, size)
        cell = next(
            (c for c in DB["cells"].values()
             if (c["cycle_id"], c["industry_code"], c["size_class"]) == key),
            None,
        )
        if cell is not None and cell["estimate_status"] in ("FINAL", "RECONSTRUCTED"):
            continue  # benchmark/reconstruction output is never recomputed
        fs = _current_factor_set(program_code, ind, size, ref_year)
        sac = None
        if fs is not None:
            sac = round0(Decimal(estimate) / Decimal(str(fs["factors"][ref_month - 1])))
        if cell is None:
            cell = new_entity("cells", {
                "cycle_id": cycle["id"],
                "program_code": program_code,
                "industry_code": ind,
                "size_class": size,
                "estimate_status": "PRELIMINARY",
                "revision_no": 1,
                "seasonally_adjusted_revised": None,
                "wedge_factor": None,
            })
        else:
            if revision_pass and cell["estimate_status"] in ("PRELIMINARY", "REVISED"):
                cell["estimate_status"] = "REVISED"
                cell["revision_no"] += 1
        cell["employment_estimate"] = estimate
        cell["variance_estimate"] = variance
        cell["respondent_count"] = resp_count
        cell["enrolled_count"] = len(members)
        cell["dominance_flag"] = dominance
        cell["imputation_variant"] = variant if had_nonresp else None
        cell["seasonally_adjusted_concurrent"] = sac
        touch(cell)

    # Response rates over the denominator set.
    if denominator:
        w_num = sum(e["base_weight"] for e in denominator if e["id"] in accepted)
        w_den = sum(e["base_weight"] for e in denominator)
        cycle["weighted_response_rate"] = round6(w_num / w_den) if w_den != 0 else None
        cycle["unweighted_response_rate"] = round6(
            Decimal(sum(1 for e in denominator if e["id"] in accepted))
            / Decimal(len(denominator))
        )
    else:
        cycle["weighted_response_rate"] = None
        cycle["unweighted_response_rate"] = None

    cycle["estimates_computed_at"] = now()
    touch(cycle)

    cycle_cells = [c for c in DB["cells"].values() if c["cycle_id"] == cycle["id"]]
    _suppression_fixed_point(cycle_cells)
