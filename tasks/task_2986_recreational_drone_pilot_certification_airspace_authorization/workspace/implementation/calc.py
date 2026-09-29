"""Deterministic calculations (PRD 3.1-3.9).

Money is integer cents throughout; every rate multiplication rounds half-up to
whole cents at the point the multiplication occurs (PRD 2.9).
"""

from decimal import Decimal, ROUND_HALF_UP

from clockmod import add_days, add_months, clock
from store import order_key, store

PASS_MARK = {"TRUST_RECREATIONAL": 100, "PART107_COMMERCIAL": 70}
INJURY_RESERVE = {"NONE": 0, "MINOR": 250000, "SERIOUS": 1500000}
ARC_INDEX = {"ARC_A": 0, "ARC_B": 1, "ARC_C": 2, "ARC_D": 3}
COMMERCIAL_MINIMUM_CENTS = 1000000
MAX_APPROVABLE_SAIL = 5
BASE_CEILING_FT = 400
STRUCTURE_RELIEF_CEILING_FT = 600
RISK_SUSPEND_THRESHOLD = 70


def half_up(value):
    """Round a Decimal to a whole number of cents, half away from zero."""
    return int(Decimal(value).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def half_up_1dp(value):
    return float(Decimal(value).quantize(Decimal("0.1"), rounding=ROUND_HALF_UP))


# ---------------------------------------------------------------------------
# 3.1 knowledge tests and certificates
# ---------------------------------------------------------------------------

def test_passed(test_code, raw_score):
    return raw_score >= PASS_MARK[test_code]


def certificate_expiry(issued_at):
    return add_months(issued_at, 24)


# ---------------------------------------------------------------------------
# 3.2 currency
# ---------------------------------------------------------------------------

def active_certification(pilot):
    for cert in store.all("certifications"):
        if cert["pilot_id"] == pilot["id"] and cert["status"] == "ACTIVE":
            return cert
    return None


def default_basis(pilot):
    return "RECREATIONAL_BASIS" if pilot["operator_category"] == "RECREATIONAL" \
        else "COMMERCIAL_BASIS"


def currency_projection(pilot, basis=None):
    """Return (projected_expiry, basis_applied, base_expiry, recency_expiry)."""
    basis_applied = basis or default_basis(pilot)
    cert = active_certification(pilot)
    if cert is None:
        return None, basis_applied, None, None
    base_expiry = cert["expires_at"]
    anchor = pilot.get("last_completed_flight_end") or cert["issued_at"]
    recency_expiry = add_days(anchor, 90)
    if basis_applied == "RECREATIONAL_BASIS":
        projected = base_expiry
    else:
        projected = base_expiry if base_expiry <= recency_expiry else recency_expiry
    return projected, basis_applied, base_expiry, recency_expiry


def write_currency(pilot):
    projected, basis_applied, _, _ = currency_projection(pilot)
    pilot["currency_expires_at"] = projected
    pilot["currency_basis"] = basis_applied
    return projected


def currency_lapsed(pilot):
    projected, _, _, _ = currency_projection(pilot)
    if projected is None:
        return True
    return projected <= clock.now()


def last_completed_flight_end(pilot):
    best = None
    for flight in store.all("flights"):
        if flight["pilot_id"] != pilot["id"] or flight["status"] != "COMPLETED":
            continue
        if flight.get("actual_end") is None:
            continue
        if best is None or flight["actual_end"] > best:
            best = flight["actual_end"]
    return best


# ---------------------------------------------------------------------------
# 3.4 granted ceiling
# ---------------------------------------------------------------------------

def waiver_cap(authorization):
    waiver = store.get("waivers", authorization.get("waiver_id"))
    if waiver is None or waiver["status"] != "APPROVED":
        return BASE_CEILING_FT
    if waiver.get("valid_until") is None:
        return BASE_CEILING_FT
    if waiver["valid_until"] <= authorization["window_end"]:
        return BASE_CEILING_FT
    return waiver["granted_ceiling_ft"]


def category_cap(pilot, zone):
    if pilot["operator_category"] == "RECREATIONAL":
        return BASE_CEILING_FT
    return STRUCTURE_RELIEF_CEILING_FT if zone.get("structure_relief_eligible") \
        else BASE_CEILING_FT


def granted_ceiling(authorization, pilot, aircraft, zone):
    relief = max(waiver_cap(authorization), category_cap(pilot, zone))
    return min(authorization["requested_ceiling_ft"], zone["class_ceiling_ft"],
               aircraft["max_altitude_ft"], relief)


def overlapping_slot_count(zone_id, candidate):
    """Zone capacity: other APPROVED/ACTIVE rows whose half-open window overlaps."""
    count = 0
    for other in store.all("authorizations"):
        if other["zone_id"] != zone_id or other["id"] == candidate["id"]:
            continue
        if other["status"] not in ("APPROVED", "ACTIVE"):
            continue
        if other["window_start"] < candidate["window_end"] \
                and other["window_end"] > candidate["window_start"]:
            count += 1
    return count


# ---------------------------------------------------------------------------
# 3.5 sail level
# ---------------------------------------------------------------------------

def sail_level(ground_risk_class, air_risk_class, waiver_type):
    uplift = 1 if waiver_type == "BVLOS" else 0
    return min(6, ground_risk_class + ARC_INDEX[air_risk_class] + uplift)


# ---------------------------------------------------------------------------
# 3.6 insurance ledger
# ---------------------------------------------------------------------------

def policy_reports(policy):
    return [r for r in store.all("reports") if r.get("policy_id") == policy["id"]]


def recompute_policy_ledger(policy):
    """Ledger identity of PRD 2.10 rebuilt from the reports themselves."""
    open_reserved = 0
    settled = 0
    for report in policy_reports(policy):
        if report["status"] in ("FILED", "INVESTIGATING", "REMEDIATION_REQUIRED"):
            open_reserved += report.get("reserved_cents") or 0
        elif report["status"] == "CLOSED":
            settled += report.get("settlement_cents") or 0
    policy["open_reserved_cents_total"] = open_reserved
    policy["settled_cents_total"] = settled
    policy["remaining_coverage_cents"] = \
        policy["coverage_limit_cents"] - open_reserved - settled


def reserve_for(report, policy):
    if policy is None:
        return 0
    raw = half_up(Decimal(report["reported_property_damage_cents"]) * Decimal("1.25"))
    raw += INJURY_RESERVE[report["injury_level"]]
    return min(policy["remaining_coverage_cents"], raw)


def settlement_for(report, policy, line_items):
    subtotal = 0
    for item in line_items:
        subtotal += half_up(Decimal(int(item["amount_cents"])) * Decimal("0.85"))
    deductible = policy["deductible_cents"] if policy is not None else 0
    net = subtotal - deductible
    if net < 0:
        net = 0
    if net <= 500000:
        surcharge = 0
    elif net <= 2000000:
        surcharge = half_up(Decimal(net) * Decimal("0.02"))
    else:
        surcharge = half_up(Decimal(net) * Decimal("0.05"))
    uncapped = net + surcharge
    if policy is None:
        # No policy means no limit to cap against (PRD 3.8 leaves this unstated).
        return uncapped
    other_settled = 0
    for other in policy_reports(policy):
        if other["id"] == report["id"]:
            continue
        if other["status"] == "CLOSED":
            other_settled += other.get("settlement_cents") or 0
    headroom = policy["coverage_limit_cents"] - other_settled
    return min(uncapped, headroom)


def covering_policy_candidates(pilot_id, window_start, window_end):
    """ACTIVE policies of the pilot whose cover spans the whole window."""
    out = []
    for policy in store.all("policies"):
        if policy["pilot_id"] != pilot_id or policy["coverage_status"] != "ACTIVE":
            continue
        if policy["effective_from"] <= window_start \
                and policy["effective_until"] > window_end:
            out.append(policy)
    return out


def select_covering_policy(candidates):
    best = None
    for policy in candidates:
        if best is None or policy["remaining_coverage_cents"] > best["remaining_coverage_cents"]:
            best = policy
        elif policy["remaining_coverage_cents"] == best["remaining_coverage_cents"] \
                and order_key(policy) < order_key(best):
            best = policy
    return best


# ---------------------------------------------------------------------------
# 3.9 risk score
# ---------------------------------------------------------------------------

def recompute_risk_score(pilot):
    incidents = 0
    exceedances = 0
    clean = 0
    flight_ids = set()
    for flight in store.all("flights"):
        if flight["pilot_id"] != pilot["id"]:
            continue
        flight_ids.add(flight["id"])
        if flight["status"] != "COMPLETED":
            continue
        incident = bool(flight.get("incident_occurred"))
        exceedance = bool(flight.get("altitude_exceedance"))
        if incident:
            incidents += 1
        if exceedance:
            exceedances += 1
        if not incident and not exceedance:
            clean += 1
    open_accidents = 0
    for report in store.all("reports"):
        if report["flight_id"] in flight_ids and \
                report["status"] in ("FILED", "INVESTIGATING", "REMEDIATION_REQUIRED"):
            open_accidents += 1
    lapsed_term = 10 if pilot["status"] == "LAPSED" else 0
    raw = 25 * incidents + 15 * exceedances + 30 * open_accidents + lapsed_term \
        - 5 * clean
    pilot["risk_score"] = max(0, min(100, raw))
    return pilot["risk_score"]


def recompute_open_waiver_count(pilot):
    open_states = ("DRAFT", "SUBMITTED", "UNDER_REVIEW", "REVISION_REQUESTED", "CLEARED",
                   "APPROVED")
    count = 0
    for waiver in store.all("waivers"):
        if waiver["pilot_id"] == pilot["id"] and waiver["status"] in open_states:
            count += 1
    pilot["open_waiver_count"] = count
    return count


def recompute_knowledge_attempt_count(pilot):
    """PRD 3.1: counts only the pilot's tests in PASSED or FAILED."""
    count = 0
    for test in store.all("knowledge_tests"):
        if test["pilot_id"] == pilot["id"] and test["status"] in ("PASSED", "FAILED"):
            count += 1
    pilot["knowledge_attempt_count"] = count
    return count


# ---------------------------------------------------------------------------
# 3.7 flight summary
# ---------------------------------------------------------------------------

def flight_summary(pilot, window_start, window_end):
    rows = []
    for flight in store.all("flights"):
        if flight["pilot_id"] != pilot["id"] or flight["status"] != "COMPLETED":
            continue
        actual_end = flight.get("actual_end")
        if actual_end is None:
            continue
        if window_start <= actual_end < window_end:
            rows.append(flight)
    count = len(rows)
    total_minutes = sum(flight.get("logged_minutes") or 0 for flight in rows)
    max_alt = 0
    incident_count = 0
    exceedance_count = 0
    for flight in rows:
        value = flight.get("max_altitude_reached_ft") or 0
        if value > max_alt:
            max_alt = value
        if flight.get("incident_occurred"):
            incident_count += 1
        if flight.get("altitude_exceedance"):
            exceedance_count += 1
    if count == 0:
        average = 0.0
    else:
        average = half_up_1dp(Decimal(total_minutes) / Decimal(count))
    return {
        "completed_flight_count": count,
        "total_logged_minutes": total_minutes,
        "max_altitude_reached_ft": max_alt,
        "incident_flight_count": incident_count,
        "exceedance_flight_count": exceedance_count,
        "average_duration_minutes": average,
    }
