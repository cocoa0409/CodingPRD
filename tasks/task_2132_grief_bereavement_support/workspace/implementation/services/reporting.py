"""Grant report roll-up (§3.9).

Rounding order is pinned: each line's indirect amount is rounded to whole cents
first, and the rounded per-line figures are then summed.
"""

from core import calc
from core.store import store


def effective_date(alloc):
    if alloc["status"] == "SETTLED" and alloc.get("settled_at"):
        return alloc["settled_at"][:10]
    return alloc["created_at"][:10]


def select_lines(report):
    lines = []
    for alloc in store.find("FundingAllocation", grant_award_id=report["grant_award_id"]):
        if alloc["status"] not in ("COMMITTED", "SETTLED"):
            continue
        eff = effective_date(alloc)
        if report["period_start"] <= eff <= report["period_end"]:
            lines.append((eff, alloc))
    lines.sort(key=lambda pair: (pair[0], pair[1]["created_at"], pair[1]["_seq"]))
    return [alloc for _, alloc in lines]


def reportable_amount(alloc):
    if alloc["status"] == "SETTLED":
        return alloc["settled_cents"] or 0
    return alloc["provisional_cents"] or 0


def compute_totals(report):
    award = store.get("GrantAward", report["grant_award_id"])
    bps = award["indirect_rate_bps"] if award else 0
    lines = select_lines(report)
    direct_total = 0
    indirect_total = 0
    for alloc in lines:
        amount = reportable_amount(alloc)
        direct_total += amount
        indirect_total += calc.money(calc.dec(amount) * calc.dec(bps) / calc.dec(10000))

    funded_cohort_ids = set()
    for alloc in lines:
        if alloc.get("cohort_id"):
            funded_cohort_ids.add(alloc["cohort_id"])
    served = set()
    for enr in store.all("Enrollment"):
        if enr["cohort_id"] in funded_cohort_ids and enr["status"] in ("CONFIRMED", "ATTENDING", "COMPLETED"):
            served.add(enr["participant_id"])

    report["line_count"] = len(lines)
    report["direct_total_cents"] = direct_total
    report["indirect_total_cents"] = indirect_total
    report["reported_total_cents"] = direct_total + indirect_total
    report["participants_served"] = len(served)
