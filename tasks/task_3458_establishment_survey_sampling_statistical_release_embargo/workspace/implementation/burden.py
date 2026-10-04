"""Burden ledger (PRD 3.4): per-establishment annual reporting burden.

burden_minutes_ytd accumulates 15 minutes per report submission event plus the
minutes of every non-voided follow-up contact; burden_year records which
calendar year the accumulator covers (null until the first burden event). When
the first burden event of a new calendar year lands, the accumulator resets to
0 and burden_year advances to that year BEFORE the new event's minutes apply.
The budget check on contact recording applies against the post-rollover figure.
"""
from store import now, touch


def _rollover_view(enrollment):
    """Return (ytd, year) after applying the calendar-year rollover rule,
    without mutating the enrollment."""
    year = now().year
    ytd = enrollment["burden_minutes_ytd"]
    byear = enrollment["burden_year"]
    if byear is None or byear < year:
        return 0, year
    return ytd, byear


def burden_would_fit(enrollment, program, add_minutes) -> bool:
    ytd, _year = _rollover_view(enrollment)
    return ytd + add_minutes <= program["annual_burden_budget_minutes"]


def burden_apply(enrollment, delta_minutes) -> None:
    """Apply a signed burden event (+submission/contact, -void) with rollover."""
    ytd, year = _rollover_view(enrollment)
    enrollment["burden_minutes_ytd"] = ytd + delta_minutes
    enrollment["burden_year"] = year
    touch(enrollment)
