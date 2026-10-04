"""State machines, cascades and shared business gates (SCAFFOLD §1.2, PRD §3)."""

from datetime import timedelta

from db import db, iso_now
from errors import (
    ApiError,
    ERR_AREA_ALREADY_ASSIGNED,
    ERR_ASSIGNMENT_NOT_FOUND,
    ERR_BRANDING_NONCOMPLIANT,
    ERR_CHARGEBACK_OUTSTANDING,
    ERR_DEDUCTION_CAP_EXCEEDED,
    ERR_DRIVER_NOT_QUALIFIED,
    ERR_INSURANCE_INSUFFICIENT,
    ERR_INVALID_REQUEST,
    ERR_INVALID_STATE,
    ERR_NEGOTIATION_ROUND_LIMIT,
    ERR_PEAK_CAPACITY_EXCEEDED,
    ERR_PROVIDER_NOT_FOUND,
    ERR_SERVICE_AREA_NOT_FOUND,
    ERR_SETTLEMENT_PERIOD_NOT_FOUND,
    ERR_STOP_CAPACITY_EXCEEDED,
    ERR_TEMPORAL_OVERLAP,
    ERR_VEHICLE_INELIGIBLE,
)
import calculations as calc

# --- terminal states (PRD §2.9) ---
TERMINAL_STATES = {
    "TRANSFERRED", "TERMINATED", "EXPIRED", "RELEASED", "REJECTED",
    "SETTLED", "ENDED", "CANCELED", "SUSPENDED", "WITHDRAWN", "RESOLVED",
}

ROUTE_ASSIGNMENT_TERMINAL = ["TRANSFERRED", "TERMINATED"]
AGREEMENT_TERMINAL = ["EXPIRED", "TERMINATED"]
PERIOD_TERMINAL = ["RELEASED"]
CLAIM_TERMINAL = ["REJECTED", "SETTLED"]
DISPUTE_TERMINAL = ["RESOLVED", "WITHDRAWN"]
DECLARATION_TERMINAL = ["ENDED", "CANCELED"]
PROVIDER_TERMINAL = ["SUSPENDED"]

# Statuses in which a title no longer reserves the territory it once ran.
OCCUPANCY_RELEASED_STATUSES = {"TERMINATED", "TRANSFERRED"}

# PRD §3.3: the round budget counts the renegotiate action and the provider's
# resubmission against the same allowance, since "an agreement may consume at
# most three renegotiation rounds in total". Six increments therefore exhaust a
# full three-round negotiation, and the next attempt is refused.
RENEGOTIATION_ROUND_BUDGET = 6
# PRD §3.11: a dispute may consume at most two counter-offers.
DISPUTE_COUNTER_BUDGET = 2
MAX_AUTHORIZED_VEHICLES = 25


# ---------------------------------------------------------------------------
# Shared compliance gates
# ---------------------------------------------------------------------------

def auto_liability_policies(provider_id):
    return [
        p
        for p in db.all("InsurancePolicy")
        if p["provider_id"] == provider_id and p["policy_type"] == "AUTO_LIABILITY"
    ]


def insurance_clear(provider_id, floor, allow_submitted):
    """PRD §2.6 / §3.5. `floor` is the governing agreement's coverage floor."""
    policies = auto_liability_policies(provider_id)
    allowed_status = {"SUBMITTED", "VERIFIED"} if allow_submitted else {"VERIFIED"}
    for policy in policies:
        if policy["status"] not in allowed_status:
            return False
        if int(policy["coverage_cents"]) < int(floor):
            return False
        if policy["expires_at_dt"] <= db.clock:
            return False
    return True


def require_insurance(provider_id, floor, allow_submitted):
    if not insurance_clear(provider_id, floor, allow_submitted):
        raise ApiError(ERR_INSURANCE_INSUFFICIENT)


def agreement_floor_for_area(provider_id, service_area_id):
    """The insurance floor of the governing agreement; 0 when none governs yet."""
    matches = [
        a for a in db.all("Agreement")
        if a["service_area_id"] == service_area_id and a["provider_id"] == provider_id
    ]
    if not matches:
        return 0
    matches.sort(key=lambda a: (a["created_at"], a["id"]))
    return int(matches[-1]["insurance_coverage_cents"])


def non_temporary_vehicles_on_area(service_area_id):
    return [
        v for v in db.all("Vehicle")
        if v["service_area_id"] == service_area_id and not v.get("is_temporary")
    ]


def require_branding(service_area_id):
    """Priority 22: every non-temporary vehicle on the area must pass branding."""
    for vehicle in non_temporary_vehicles_on_area(service_area_id):
        if vehicle["branding_compliance"] != "PASSED":
            raise ApiError(ERR_BRANDING_NONCOMPLIANT)


def active_assignments_on_area(service_area_id, exclude_id=None, statuses=("ACTIVE", "PENDING_TRANSFER")):
    return [
        a for a in db.all("RouteAssignment")
        if a["service_area_id"] == service_area_id
        and a["status"] in statuses
        and a["id"] != exclude_id
    ]


def require_area_free(service_area_id, exclude_id=None):
    """Priority 17: no other title on the area is ACTIVE or PENDING_TRANSFER."""
    if active_assignments_on_area(service_area_id, exclude_id):
        raise ApiError(ERR_AREA_ALREADY_ASSIGNED)


def occupancy_interval(assignment):
    """The occupancy span a title recorded.

    PRD §2.5: "a candidate interval begins at its `effective_date`, and the
    interval is half-open, running up to `occupancy_ends_at` when that instant is
    recorded and to positive infinity otherwise." The recorded span is what the
    overlap test reads, so a title that has since ended still contributes the
    interval it held — which is what makes an abutting candidate legal while one
    that starts inside the span is refused.
    """
    end = assignment.get("occupancy_ends_at_dt")
    if end is not None and end < assignment["effective_date_dt"]:
        # A recorded end that precedes the start leaves no span to occupy.
        return None, None
    return assignment["effective_date_dt"], end


def require_no_overlap(service_area_id, effective_date, exclude_id=None):
    """Priority 18: the candidate interval [effective_date, +inf) must not
    intersect another title's occupancy interval on the same area. Intervals are
    half-open [start, end) when `occupancy_ends_at` is recorded and [start, +inf)
    otherwise, so abutting endpoints (gap 0 days) are permitted."""
    for other in db.all("RouteAssignment"):
        if other["service_area_id"] != service_area_id or other["id"] == exclude_id:
            continue
        other_start, other_end = occupancy_interval(other)
        if other_start is None:
            continue
        # No recorded end means the title still holds the territory to infinity.
        if other_end is None:
            raise ApiError(ERR_TEMPORAL_OVERLAP)
        # A candidate that starts at or after the recorded end never intersects.
        if effective_date >= other_end:
            continue
        raise ApiError(ERR_TEMPORAL_OVERLAP)


def assert_provider_exists(provider_id):
    provider = db.get("ServiceProvider", provider_id)
    if provider is None:
        raise ApiError(ERR_PROVIDER_NOT_FOUND)
    return provider


def assert_area_exists(service_area_id):
    area = db.get("ServiceArea", service_area_id)
    if area is None:
        raise ApiError(ERR_SERVICE_AREA_NOT_FOUND)
    return area


def assert_assignment_exists(assignment_id):
    assignment = db.get("RouteAssignment", assignment_id)
    if assignment is None:
        raise ApiError(ERR_ASSIGNMENT_NOT_FOUND)
    return assignment


# ---------------------------------------------------------------------------
# Vehicle eligibility and peak season capacity
# ---------------------------------------------------------------------------

def require_vehicle_eligible(vehicle_class, service_area):
    """STEP_VAN is refused above the stop ceiling; BOX_TRUCK and TRACTOR_TRAILER
    clear every area (PRD §2.7)."""
    if vehicle_class == "STEP_VAN" and int(service_area["stop_capacity_weekly"]) > calc.STEP_VAN_STOP_CEILING:
        raise ApiError(ERR_VEHICLE_INELIGIBLE)


def covering_declaration(service_area_id, instant):
    found = []
    for decl in db.all("PeakSeasonDeclaration"):
        if decl["status"] != "ACTIVE":
            continue
        if decl["service_area_id"] != service_area_id:
            continue
        if decl["starts_on_dt"] <= instant < decl["ends_on_dt"]:
            found.append(decl)
    found.sort(key=lambda d: (d["created_at"], d["id"]))
    return found[-1] if found else None


def require_temporary_capacity(service_area_id, asset):
    """PRD §2.7 / §3.6: a temporary asset needs a covering ACTIVE declaration
    with room inside its authorized count."""
    decl = covering_declaration(service_area_id, db.clock)
    if decl is None:
        raise ApiError(ERR_PEAK_CAPACITY_EXCEEDED)
    if asset == "vehicle":
        used = len([v for v in db.all("Vehicle")
                    if v["service_area_id"] == service_area_id and v.get("is_temporary")
                    and v["status"] != "DECOMMISSIONED"])
        if used + 1 > int(decl["authorized_vehicles"]):
            raise ApiError(ERR_PEAK_CAPACITY_EXCEEDED)
    else:
        used = len([d for d in db.all("Driver")
                    if d["service_area_id"] == service_area_id and d.get("is_temporary")
                    and d["status"] != "TERMINATED"])
        if used + 1 > int(decl["authorized_drivers"]):
            raise ApiError(ERR_PEAK_CAPACITY_EXCEEDED)


# ---------------------------------------------------------------------------
# ServiceProvider transitions
# ---------------------------------------------------------------------------

def provider_approve(provider):
    """Approval gates on every AUTO_LIABILITY policy being VERIFIED and unexpired,
    and on every non-temporary vehicle passing branding."""
    for policy in auto_liability_policies(provider["id"]):
        if policy["status"] != "VERIFIED":
            raise ApiError(ERR_INSURANCE_INSUFFICIENT)
        if policy["expires_at_dt"] <= db.clock:
            raise ApiError(ERR_INSURANCE_INSUFFICIENT)
    for vehicle in db.all("Vehicle"):
        if vehicle["provider_id"] == provider["id"] and not vehicle.get("is_temporary"):
            if vehicle["branding_compliance"] != "PASSED":
                raise ApiError(ERR_BRANDING_NONCOMPLIANT)

    provider["status"] = "APPROVED"
    for vehicle in db.all("Vehicle"):
        if (vehicle["provider_id"] == provider["id"] and not vehicle.get("is_temporary")
                and vehicle["status"] == "PENDING"):
            vehicle["status"] = "ACTIVE"
            db.touch("Vehicle", vehicle)
    for driver in db.all("Driver"):
        if (driver["provider_id"] == provider["id"] and not driver.get("is_temporary")
                and driver["status"] == "PENDING" and driver["qualification_status"] == "QUALIFIED"):
            driver["status"] = "ACTIVE"
            db.touch("Driver", driver)
    # active_fleet_denominator variant: brand_compliance_pct over the ACTIVE fleet.
    provider["brand_compliance_pct"] = calc.brand_compliance_pct(provider["id"])
    db.touch("ServiceProvider", provider)
    return provider


def provider_suspend(provider):
    provider["status"] = "SUSPENDED"
    for assignment in db.all("RouteAssignment"):
        if assignment["provider_id"] == provider["id"] and assignment["status"] in (
            "DRAFT", "ACTIVE", "PENDING_TRANSFER"
        ):
            assignment["status"] = "TERMINATED"
            assignment["occupancy_ends_at"] = iso_now(db.clock)
            assignment["occupancy_ends_at_dt"] = db.clock
            db.touch("RouteAssignment", assignment)
    for area in db.all("ServiceArea"):
        if area.get("assigned_provider_id") == provider["id"]:
            area["status"] = "UNASSIGNED"
            area["assigned_provider_id"] = None
            db.touch("ServiceArea", area)
    for agreement in db.all("Agreement"):
        if agreement["provider_id"] == provider["id"] and agreement["status"] in (
            "DRAFT", "PENDING_REVIEW", "RE_NEGOTIATION", "ACTIVE"
        ):
            agreement["status"] = "TERMINATED"
            db.touch("Agreement", agreement)
    db.touch("ServiceProvider", provider)
    return provider


# ---------------------------------------------------------------------------
# RouteAssignment transitions
# ---------------------------------------------------------------------------

def assignment_activate(assignment):
    area = assert_area_exists(assignment["service_area_id"])
    agreement = calc.governing_agreement_for_area(assignment["service_area_id"])
    if agreement is None or agreement["status"] != "ACTIVE":
        raise ApiError(ERR_INVALID_STATE,
                       "the governing agreement for this area is not ACTIVE")
    if area["status"] != "UNASSIGNED":
        raise ApiError(ERR_AREA_ALREADY_ASSIGNED)
    require_area_free(area["id"], exclude_id=assignment["id"])
    require_no_overlap(area["id"], assignment["effective_date_dt"], exclude_id=assignment["id"])
    provider = assert_provider_exists(assignment["provider_id"])
    if provider["status"] not in ("UNDER_REVIEW", "APPROVED"):
        raise ApiError(ERR_INVALID_STATE, "a suspended provider may not take a title")
    require_branding(area["id"])

    assignment["status"] = "ACTIVE"
    area["status"] = "ASSIGNED"
    area["assigned_provider_id"] = assignment["provider_id"]
    db.touch("ServiceArea", area)
    # active_only variant: qualification_pct over the ACTIVE non-temporary roster.
    calc.recompute_brand_compliance(assignment["provider_id"])
    calc.recompute_qualification_pct(assignment["provider_id"], include_suspended=False)
    db.touch("RouteAssignment", assignment)
    return assignment


def assignment_terminate(assignment):
    area = assert_area_exists(assignment["service_area_id"])
    for period in db.all("SettlementPeriod"):
        if period["service_area_id"] == area["id"] and period["status"] == "DISPUTED":
            raise ApiError(ERR_INVALID_STATE, "a settlement week on this area is still in dispute")
    assignment["status"] = "TERMINATED"
    assignment["occupancy_ends_at"] = iso_now(db.clock)
    assignment["occupancy_ends_at_dt"] = db.clock
    area["status"] = "UNASSIGNED"
    area["assigned_provider_id"] = None
    db.touch("ServiceArea", area)
    for agreement in db.all("Agreement"):
        if agreement["service_area_id"] == area["id"]:
            agreement["status"] = "TERMINATED"
            db.touch("Agreement", agreement)
    calc.recompute_brand_compliance(assignment["provider_id"])
    db.touch("RouteAssignment", assignment)
    return assignment


def assignment_request_transfer(assignment, acquiring_provider, transfer_price_cents):
    provider = assert_provider_exists(assignment["provider_id"])
    if int(provider.get("chargeback_outstanding_cents") or 0) != 0:
        raise ApiError(ERR_CHARGEBACK_OUTSTANDING)
    floor = agreement_floor_for_area(provider["id"], assignment["service_area_id"])
    require_insurance(provider["id"], floor, allow_submitted=True)
    if acquiring_provider["status"] != "APPROVED":
        raise ApiError(ERR_INVALID_STATE, "the acquiring provider is not APPROVED")

    assignment["status"] = "PENDING_TRANSFER"
    assignment["acquiring_provider_id"] = acquiring_provider["id"]
    if transfer_price_cents is not None:
        assignment["transfer_price_cents"] = int(transfer_price_cents)
    for agreement in db.all("Agreement"):
        if agreement["service_area_id"] == assignment["service_area_id"]:
            agreement["status"] = "RE_NEGOTIATION"
            db.touch("Agreement", agreement)
    db.touch("RouteAssignment", assignment)
    return assignment


def assignment_approve_transfer(assignment):
    area = assert_area_exists(assignment["service_area_id"])
    acquiring = assert_provider_exists(assignment["acquiring_provider_id"])
    if acquiring["status"] != "APPROVED":
        raise ApiError(ERR_INVALID_STATE, "the acquiring provider is not APPROVED")
    require_area_free(area["id"], exclude_id=assignment["id"])
    provider = assert_provider_exists(assignment["provider_id"])
    if int(provider.get("chargeback_outstanding_cents") or 0) != 0:
        raise ApiError(ERR_CHARGEBACK_OUTSTANDING)

    assignment["status"] = "TRANSFERRED"
    assignment["occupancy_ends_at"] = iso_now(db.clock)
    assignment["occupancy_ends_at_dt"] = db.clock
    # The transferring title's version advances exactly once for the approval
    # cascade; it is refreshed again below only to carry the back-pointer.
    db.touch("RouteAssignment", assignment)

    area["assigned_provider_id"] = acquiring["id"]
    db.touch("ServiceArea", area)

    successor = {
        "service_area_id": assignment["service_area_id"],
        "provider_id": acquiring["id"],
        "acquiring_provider_id": None,
        "superseded_by_assignment_id": None,
        "effective_date": iso_now(assignment["effective_date_dt"] + timedelta(days=1)),
        "effective_date_dt": assignment["effective_date_dt"] + timedelta(days=1),
        "transfer_price_cents": int(assignment.get("transfer_price_cents") or 0),
        "occupancy_ends_at": None,
        "occupancy_ends_at_dt": None,
        "compliance_failures_count": 0,
        "status": "DRAFT",
    }
    db.insert("RouteAssignment", successor)
    successor["__type"] = "RouteAssignment"
    assignment["superseded_by_assignment_id"] = successor["id"]

    acquiring["provider_type"] = "SUCCESSOR"
    # all_owned_denominator variant: the denominator widens to include PENDING
    # non-temporary vehicles on transfer approval.
    acquiring["brand_compliance_pct"] = calc.brand_compliance_pct(acquiring["id"], include_pending=True)
    db.touch("ServiceProvider", acquiring)
    return assignment


def assignment_withdraw_transfer(assignment):
    assignment["status"] = "ACTIVE"
    for agreement in db.all("Agreement"):
        if agreement["service_area_id"] == assignment["service_area_id"]:
            agreement["status"] = "ACTIVE"
            db.touch("Agreement", agreement)
    db.touch("RouteAssignment", assignment)
    return assignment


def assignment_reaffirm(assignment):
    area = assert_area_exists(assignment["service_area_id"])
    agreement = calc.governing_agreement_for_area(area["id"])
    if agreement is None or agreement["status"] != "ACTIVE":
        raise ApiError(ERR_INVALID_STATE, "the governing agreement is not ACTIVE")
    require_branding(area["id"])
    require_non_temporary_drivers_qualified(area["id"])
    # tolerated_roster variant: the transition proceeds and records the failures.
    _, failures = calc.driver_qualification_compliance(area["id"])
    assignment["compliance_failures_count"] = failures
    db.touch("RouteAssignment", assignment)
    return assignment


def require_non_temporary_drivers_qualified(service_area_id):
    """Priority 20: every driver on the signing area must be QUALIFIED and hold
    CLASS_B or CLASS_A."""
    for driver in calc.driver_roster(service_area_id):
        if driver["qualification_status"] != "QUALIFIED" or driver["license_class"] == "CLASS_C":
            raise ApiError(ERR_DRIVER_NOT_QUALIFIED)


# ---------------------------------------------------------------------------
# Agreement transitions
# ---------------------------------------------------------------------------

def agreement_submit(agreement):
    if agreement["status"] == "DRAFT":
        if int(agreement["base_rate_cents_per_stop"]) < 1:
            raise ApiError(ERR_INVALID_REQUEST, "base_rate_cents_per_stop must be at least 1")
        if int(agreement["package_rate_cents"]) < 1:
            raise ApiError(ERR_INVALID_REQUEST, "package_rate_cents must be at least 1")
        if int(agreement["insurance_coverage_cents"]) < 500000:
            raise ApiError(ERR_INVALID_REQUEST, "insurance_coverage_cents must be at least 500000")
    else:
        if int(agreement["base_rate_cents_per_stop"]) < 1:
            raise ApiError(ERR_NEGOTIATION_ROUND_LIMIT,
                           "the per-stop base rate fell below the floor on resubmission")
    require_round_budget(agreement)
    agreement["rounds_used"] = int(agreement.get("rounds_used") or 0) + 1
    agreement["status"] = "PENDING_REVIEW"
    db.touch("Agreement", agreement)
    return agreement


def agreement_sign(agreement, signer_id):
    require_non_temporary_drivers_qualified(agreement["service_area_id"])
    require_insurance(agreement["provider_id"], agreement["insurance_coverage_cents"], allow_submitted=False)
    agreement["status"] = "ACTIVE"
    agreement["negotiated_by"] = signer_id
    activated = db.clock
    agreement["activated_at"] = iso_now(activated)
    agreement["renewal_due_at_dt"] = activated + timedelta(days=365)
    agreement["renewal_due_at"] = iso_now(agreement["renewal_due_at_dt"])
    agreement["rounds_used"] = 0
    db.touch("Agreement", agreement)
    return agreement


def agreement_renegotiate(agreement):
    if agreement["status"] == "ACTIVE":
        due = agreement.get("renewal_due_at_dt")
        if due is None or (due - db.clock).total_seconds() > 30 * 86400:
            raise ApiError(ERR_NEGOTIATION_ROUND_LIMIT,
                           "more than 30 days remain before renewal_due_at")
    require_round_budget(agreement)
    if agreement["status"] == "ACTIVE":
        agreement["rounds_used"] = int(agreement.get("rounds_used") or 0) + 1
    agreement["status"] = "RE_NEGOTIATION"
    db.touch("Agreement", agreement)
    return agreement


def require_round_budget(agreement):
    if int(agreement.get("rounds_used") or 0) >= RENEGOTIATION_ROUND_BUDGET:
        raise ApiError(ERR_NEGOTIATION_ROUND_LIMIT, "the renegotiation round budget is exhausted")


def agreement_amend(agreement):
    due = agreement.get("renewal_due_at_dt")
    if due is None or (due - db.clock).total_seconds() <= 30 * 86400:
        raise ApiError(ERR_NEGOTIATION_ROUND_LIMIT,
                       "30 days or fewer remain before renewal_due_at; amend is not available")
    agreement["status"] = "PENDING_REVIEW"
    db.touch("Agreement", agreement)
    return agreement


def agreement_expire(agreement):
    due = agreement.get("renewal_due_at_dt")
    if due is None or db.clock < due:
        raise ApiError(ERR_INVALID_STATE, "the logical clock has not reached renewal_due_at")
    agreement["status"] = "EXPIRED"
    area = db.get("ServiceArea", agreement["service_area_id"])
    for assignment in db.all("RouteAssignment"):
        if assignment["service_area_id"] == agreement["service_area_id"] and assignment["status"] == "ACTIVE":
            assignment["status"] = "TERMINATED"
            assignment["occupancy_ends_at"] = iso_now(db.clock)
            assignment["occupancy_ends_at_dt"] = db.clock
            db.touch("RouteAssignment", assignment)
    if area is not None:
        area["status"] = "UNASSIGNED"
        area["assigned_provider_id"] = None
        db.touch("ServiceArea", area)
    calc.renewal_recommendation(agreement)
    db.touch("Agreement", agreement)
    return agreement


def agreement_terminate(agreement):
    agreement["status"] = "TERMINATED"
    for assignment in db.all("RouteAssignment"):
        if assignment["service_area_id"] == agreement["service_area_id"] and assignment["status"] == "DRAFT":
            assignment["status"] = "TERMINATED"
            db.touch("RouteAssignment", assignment)
    db.touch("Agreement", agreement)
    return agreement


# ---------------------------------------------------------------------------
# PeakSeasonDeclaration transitions
# ---------------------------------------------------------------------------

def declaration_activate(declaration):
    if not (declaration["starts_on_dt"] <= db.clock < declaration["ends_on_dt"]):
        raise ApiError(ERR_INVALID_STATE, "the logical clock is outside the declared window")
    if int(declaration["authorized_vehicles"]) > MAX_AUTHORIZED_VEHICLES:
        raise ApiError(ERR_INVALID_STATE, "authorized_vehicles may not exceed 25")
    area = assert_area_exists(declaration["service_area_id"])
    state_code = area["state_code"]
    same_state = {
        a["id"] for a in db.all("ServiceArea")
        if a["state_code"] == state_code and a["status"] in ("UNASSIGNED", "ASSIGNED")
    }
    for other in db.all("PeakSeasonDeclaration"):
        if other["id"] == declaration["id"] or other["status"] != "ACTIVE":
            continue
        if other["service_area_id"] not in same_state:
            continue
        if declaration["starts_on_dt"] < other["ends_on_dt"] and other["starts_on_dt"] < declaration["ends_on_dt"]:
            raise ApiError(ERR_INVALID_STATE, "another ACTIVE declaration in this state overlaps the window")
    declaration["status"] = "ACTIVE"
    db.touch("PeakSeasonDeclaration", declaration)
    return declaration


def declaration_end(declaration):
    if db.clock < declaration["ends_on_dt"]:
        raise ApiError(ERR_INVALID_STATE, "the logical clock has not reached ends_on")
    declaration["status"] = "ENDED"
    area_id = declaration["service_area_id"]
    for vehicle in db.all("Vehicle"):
        if vehicle["service_area_id"] == area_id and vehicle.get("is_temporary") and vehicle["status"] != "DECOMMISSIONED":
            vehicle["status"] = "DECOMMISSIONED"
            db.touch("Vehicle", vehicle)
    for driver in db.all("Driver"):
        if driver["service_area_id"] == area_id and driver.get("is_temporary") and driver["status"] != "TERMINATED":
            driver["status"] = "TERMINATED"
            driver["qualification_status"] = "UNQUALIFIED"
            db.touch("Driver", driver)
    provider_ids = {
        v["provider_id"] for v in db.all("Vehicle")
        if v["service_area_id"] == area_id and v.get("is_temporary")
    } | {
        d["provider_id"] for d in db.all("Driver")
        if d["service_area_id"] == area_id and d.get("is_temporary")
    }
    # rostered_all variant: the denominator counts every non-terminal driver.
    for provider_id in provider_ids:
        calc.recompute_qualification_pct(provider_id, include_suspended=True)
    db.touch("PeakSeasonDeclaration", declaration)
    return declaration


# ---------------------------------------------------------------------------
# SettlementPeriod transitions
# ---------------------------------------------------------------------------

def period_close_accrual(period):
    area = assert_area_exists(period["service_area_id"])
    if period["status"] == "OPEN":
        end = calc.week_end(period)
        if not db.clock > end:
            raise ApiError(ERR_INVALID_STATE, "the logical clock has not moved past the accrual window")
        rows = calc.window_observations(period)
        total_stops = sum(int(o["stops_count"]) for o in rows)
        if total_stops > int(area["stop_capacity_weekly"]):
            raise ApiError(ERR_STOP_CAPACITY_EXCEEDED)
        period["status"] = "ACCRUAL_CLOSED"
    # Second and later occurrence: refresh the totals without reopening the window.
    calc.compute_gross_settlement(period, resolve=False)
    db.touch("SettlementPeriod", period)
    return period


def period_reconcile(period, allow_over_cap=False, deduction_order=None):
    if period["status"] != "ACCRUAL_CLOSED":
        raise ApiError(ERR_INVALID_STATE, "only an ACCRUAL_CLOSED week may be reconciled")

    if deduction_order not in (None, "forward", "reversed", "MAINTENANCE_FIRST",
                              "ACCESSORIAL_FIRST"):
        raise ApiError(ERR_INVALID_REQUEST,
                       "deduction_order must name one of the two pinned segment orders")

    # Refold the week's arithmetic over the CURRENT deduction rows before testing
    # the balance identity, so the identity reflects the segments as posted. The
    # segment cap is applied by the waterfall below and is never folded here, so
    # deductions posted above the cap still reconcile straight into the cap test.
    calc.compute_gross_settlement(period, resolve=False)
    total_non_chargeback = calc.sum_amounts(calc.period_deductions(
        period, ["FUEL", "MAINTENANCE", "ACCESSORIAL"]))
    if int(period.get("base_gross_cents") or 0) - int(period.get("net_amount_cents") or 0) != total_non_chargeback:
        raise ApiError(ERR_INVALID_STATE, "the week's gross and net do not balance against its deductions")

    eligible_total = calc.sum_amounts(calc.period_deductions(
        period, ["MAINTENANCE", "ACCESSORIAL"], eligible_only=True))
    if not allow_over_cap and eligible_total > calc.DEDUCTION_CAP:
        raise ApiError(ERR_DEDUCTION_CAP_EXCEEDED)

    period["deduction_order"] = deduction_order

    calc.recompute_period_chargebacks(period)
    calc.apply_deduction_segment_cap(period, allow_over_cap=allow_over_cap, deduction_order=deduction_order)

    # The metrics-driven multiplier is resolved here and rewritten on the week.
    multiplier = calc.resolve_multiplier(period)
    period["performance_multiplier"] = float(multiplier)

    use_observed = calc.has_late_accrual(period)
    calc.compute_gross_settlement(period, use_observed_date=use_observed)

    period["status"] = "RECONCILED"
    calc.recompute_chargeback_outstanding(period["provider_id"])
    calc.recompute_brand_compliance(period["provider_id"])
    db.touch("SettlementPeriod", period)
    return period


def period_release(period):
    if period["status"] not in ("RECONCILED", "DISPUTED"):
        raise ApiError(ERR_INVALID_STATE, "only a RECONCILED or DISPUTED week may be released")
    disputes = [d for d in db.all("Dispute") if d["settlement_period_id"] == period["id"]]
    if period["status"] == "RECONCILED":
        if any(d["status"] in ("OPEN", "EVIDENCE_SUBMITTED", "COUNTERED", "ESCALATED") for d in disputes):
            raise ApiError(ERR_INVALID_STATE, "the week carries an unresolved dispute")
    else:
        if any(d["status"] not in ("RESOLVED", "WITHDRAWN") for d in disputes):
            raise ApiError(ERR_INVALID_STATE, "not every dispute on the week is resolved or withdrawn")
        if not db.clock < calc.week_end(period) + timedelta(days=90):
            raise ApiError(ERR_INVALID_STATE, "the dispute window for this week has expired")

    provider = assert_provider_exists(period["provider_id"])
    provider["lifetime_paid_cents"] = int(provider.get("lifetime_paid_cents") or 0) + int(period["net_amount_cents"])
    chargebacks = calc.sum_amounts(calc.period_deductions(period, "CHARGEBACK"))
    provider["chargeback_outstanding_cents"] = max(0, int(provider.get("chargeback_outstanding_cents") or 0) - chargebacks)
    db.touch("ServiceProvider", provider)
    period["status"] = "RELEASED"
    db.touch("SettlementPeriod", period)
    return period


# ---------------------------------------------------------------------------
# ChargebackClaim transitions
# ---------------------------------------------------------------------------

def claim_approve(claim):
    period = db.get("SettlementPeriod", claim["settlement_period_id"])
    if period is None:
        raise ApiError(ERR_SETTLEMENT_PERIOD_NOT_FOUND)
    if period["status"] not in ("OPEN", "ACCRUAL_CLOSED", "RECONCILED"):
        raise ApiError(ERR_INVALID_STATE, "the settlement week does not accept a charge-back")
    if claim["claim_type"] == "EQUIPMENT":
        vehicle = db.get("Vehicle", claim.get("vehicle_id"))
        if vehicle is None or vehicle["service_area_id"] != period["service_area_id"]:
            raise ApiError(ERR_INVALID_STATE, "the named vehicle does not run this territory")
    if claim["claim_type"] in ("MISSED_PICKUP", "EQUIPMENT"):
        end = calc.week_end(period)
        for obs in calc.observations(period):
            if obs["observed_date_dt"] <= end and not obs.get("recorded_at"):
                raise ApiError(ERR_INVALID_STATE,
                               "an observation on this week has no recorded_at")

    calc.compute_net_recovery(claim)
    claim["status"] = "APPROVED"
    _ded = {
        "settlement_period_id": claim["settlement_period_id"],
        "deduction_type": "CHARGEBACK",
        "amount_cents": int(claim["net_of_recovery_cents"]),
        "chargeback_category": claim["claim_type"],
        "performance_factor_eligible": False,
    }
    db.insert("SettlementDeduction", _ded)
    _ded["__type"] = "SettlementDeduction"
    claim["status"] = "SETTLED"
    provider = assert_provider_exists(claim["provider_id"])
    provider["chargeback_outstanding_cents"] = int(provider.get("chargeback_outstanding_cents") or 0) + int(claim["net_of_recovery_cents"])
    calc.recompute_brand_compliance(claim["provider_id"])
    db.touch("ChargebackClaim", claim)
    return claim


def claim_settle(claim):
    if claim.get("net_of_recovery_cents") is None:
        raise ApiError(ERR_INVALID_STATE, "net_of_recovery_cents is not set")
    claim["status"] = "SETTLED"
    db.touch("ChargebackClaim", claim)
    return claim


def claim_reject(claim):
    claim["status"] = "REJECTED"
    db.touch("ChargebackClaim", claim)
    return claim


# ---------------------------------------------------------------------------
# Dispute transitions
# ---------------------------------------------------------------------------

def dispute_counter(dispute, counter_amount_cents):
    # PRD §3.11: "A counter may only be placed while `rounds_used` is at most 1",
    # so a counter is accepted at rounds_used 0 and 1 and refused from 2 on. The
    # `rounds_used` write below is what makes a second counter-of-record
    # impossible, so no separate budget test is needed here.
    if int(dispute.get("rounds_used") or 0) > DISPUTE_COUNTER_BUDGET - 1:
        raise ApiError(ERR_NEGOTIATION_ROUND_LIMIT, "the dispute round budget is exhausted")
    if dispute["status"] != "EVIDENCE_SUBMITTED":
        raise ApiError(ERR_INVALID_STATE)
    dispute["status"] = "COUNTERED"
    dispute["rounds_used"] = int(dispute.get("rounds_used") or 0) + 1
    if counter_amount_cents is not None:
        dispute["counter_amount_cents"] = int(counter_amount_cents)
    db.touch("Dispute", dispute)
    return dispute


def dispute_resubmit(dispute):
    # The back-edge is legal from COUNTERED and leaves the counter count alone.
    dispute["status"] = "EVIDENCE_SUBMITTED"
    db.touch("Dispute", dispute)
    return dispute


def dispute_withdraw(dispute):
    if dispute.get("filed_by_role") != "ServiceProvider":
        raise ApiError(ERR_INVALID_STATE, "only a provider-filed dispute may be withdrawn")
    dispute["status"] = "WITHDRAWN"
    db.touch("Dispute", dispute)
    return dispute