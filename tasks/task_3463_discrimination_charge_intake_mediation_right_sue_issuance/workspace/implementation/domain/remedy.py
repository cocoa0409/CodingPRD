"""Remedy valuation (calculations.remedy_valuation; PRD section 3.7).

Pinned evaluation order: interest is computed per wage component and rounded
half-up BEFORE any summation; the non-pecuniary components are summed and
capped together at the statutory tier for band_used; the total is a plain sum
of already-whole cents.

PROVISIONAL: band from the employer's current size_band; interest accrues to
the conciliation-initiation date.
FINAL: band from the charge's immutable employee_count_at_incident snapshot;
interest accrues to the accept date; never recomputes again.
"""

from datetime import datetime
from decimal import Decimal, ROUND_HALF_UP

import constants
from store import db


def _as_date(value):
    if isinstance(value, datetime):
        return value.date()
    return value


def _interest_cents(component_cents, interest_days):
    rate = Decimal(constants.ANNUAL_INTEREST_RATE)
    raw = (
        Decimal(component_cents)
        * rate
        * interest_days
        / constants.INTEREST_DIVISOR_DAYS
    )
    return int(raw.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def compute_remedy(package, band, projection_date):
    """Fill in the derived fields of a RemedyPackage for the given band and
    projection date. Mutates the package row (caller bumps the version)."""
    harm_start = _as_date(package["harm_start_date"])
    projection = _as_date(projection_date)
    interest_days = (projection - harm_start).days

    back_interest = _interest_cents(package["back_pay_cents"], interest_days)
    front_interest = _interest_cents(package["front_pay_cents"], interest_days)

    nonpecuniary = (
        package["compensatory_damages_cents"] + package["punitive_damages_cents"]
    )
    # UNDER_15 has no cap tier (such an employer never lawfully reaches
    # conciliation); treat a missing tier as a zero cap rather than crash.
    cap = constants.CAP_TIER_CENTS.get(band, 0)
    capped_nonpecuniary = min(nonpecuniary, cap)

    package["band_used"] = band
    package["projection_date"] = projection
    package["interest_days"] = interest_days
    package["back_pay_interest_cents"] = back_interest
    package["front_pay_interest_cents"] = front_interest
    package["capped_nonpecuniary_cents"] = capped_nonpecuniary
    package["total_cents"] = (
        package["back_pay_cents"]
        + package["front_pay_cents"]
        + back_interest
        + front_interest
        + capped_nonpecuniary
    )


def package_for_conciliation(conciliation):
    for package in db.remedy_packages.values():
        if package["conciliation_process_id"] == conciliation["id"]:
            return package
    return None


def conciliation_for_charge(charge):
    for conciliation in db.conciliation_processes.values():
        if conciliation["charge_id"] == charge["id"]:
            return conciliation
    return None


def revalue_provisional_packages_for_employer(employer):
    """Employer PATCH cascade: re-band every PROVISIONAL RemedyPackage on
    this employer's non-terminal conciliations, keeping each package's
    original projection_date (only the cap tier moves)."""
    from helpers import bump

    for charge in db.charges.values():
        if charge["employer_id"] != employer["id"]:
            continue
        conciliation = conciliation_for_charge(charge)
        if conciliation is None:
            continue
        if conciliation["status"] not in constants.CONCILIATION_OPEN_STATES:
            continue
        package = package_for_conciliation(conciliation)
        if package is None:
            continue
        if package["valuation_variant"] != constants.VALUATION_PROVISIONAL:
            continue
        compute_remedy(
            package,
            employer["size_band"],
            package["projection_date"],
        )
        bump(package)
