"""Rating distribution reporting and the logical district clock."""
from decimal import Decimal

import calc
import services as svc
from auth import authenticate
from errors import err
from response import ok
from store import S, num, parse_dt
from validation import body, query_str, v_str

BANDS = (
    ("INEFFECTIVE", "ineffective"),
    ("DEVELOPING", "developing"),
    ("EFFECTIVE", "effective"),
    ("HIGHLY_EFFECTIVE", "highly_effective"),
)


def register(app):
    @app.get("/reports/rating-distribution")
    def rating_distribution():
        authenticate(("HrAdmin", "UnionRep"))
        school_year = query_str("school_year")
        if school_year is None:
            raise err("ERR_INVALID_REQUEST", "school_year is required.")
        school_id = query_str("school_id")
        population = []
        for cycle in S.cycles.values():
            if cycle["status"] not in ("FINALIZED", "CLOSED"):
                continue
            if cycle["school_year"] != school_year:
                continue
            if school_id is not None:
                educator = S.educators.get(cycle["educator_id"])
                if educator is None or educator["school_id"] != school_id:
                    continue
            population.append(cycle)
        total = len(population)
        data = {"school_year": school_year, "school_id": school_id, "total_count": total}
        highly_pct = Decimal("0.00")
        for band_value, prefix in BANDS:
            count = len([c for c in population if c["composite_rating"] == band_value])
            percentage = calc.pct(count, total)
            data["%s_count" % prefix] = count
            data["%s_pct" % prefix] = num(percentage)
            if band_value == "HIGHLY_EFFECTIVE":
                highly_pct = percentage
        data["outlier_flag"] = bool(total > 0 and highly_pct > calc.DISTRIBUTION_OUTLIER_PCT)
        return ok(data)

    @app.post("/_clock/set_current_utc")
    def set_clock():
        authenticate(("HrAdmin",))
        data = body()
        raw = v_str(data, "to_iso8601")
        parsed = parse_dt(raw)
        if parsed is None:
            raise err("ERR_INVALID_REQUEST", "to_iso8601 must be an ISO 8601 UTC instant.")
        S.clock = parsed
        return ok({})
