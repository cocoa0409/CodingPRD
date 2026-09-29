"""Derived-field computation and recomputation for every aggregate."""
from decimal import Decimal

import domain as D
from store import (add_years, clock_date, day_count, db, dec, iso_date, mark,
                   month_of, ordered, pd, q, q1, q2, q4, round_half_up_int,
                   set_field, set_fields)


# --------------------------------------------------------------------- lookups

def referral_ifsps(referral_id):
    return ordered(db.ifsps, [i for i in db.ifsps.values()
                              if i["referral_id"] == referral_id])


def ifsp_lines(ifsp_id):
    return ordered(db.ifsp_services, [s for s in db.ifsp_services.values()
                                      if s["ifsp_id"] == ifsp_id])


def line_authorizations(line_id):
    return ordered(db.authorizations, [a for a in db.authorizations.values()
                                       if a["ifsp_service_id"] == line_id])


def auth_visits(auth_id):
    return ordered(db.visits, [v for v in db.visits.values()
                               if v["provider_authorization_id"] == auth_id])


def line_visits(line_id):
    auth_ids = set(a["id"] for a in line_authorizations(line_id))
    return ordered(db.visits, [v for v in db.visits.values()
                               if v["provider_authorization_id"] in auth_ids])


def line_of_auth(auth):
    return db.ifsp_services.get(auth["ifsp_service_id"])


def auth_of_visit(visit):
    return db.authorizations.get(visit["provider_authorization_id"])


def line_of_visit(visit):
    auth = auth_of_visit(visit)
    return line_of_auth(auth) if auth else None


def ifsp_of_line(line):
    return db.ifsps.get(line["ifsp_id"])


def referral_of_ifsp(ifsp):
    return db.referrals.get(ifsp["referral_id"])


def referral_of_line(line):
    ifsp = ifsp_of_line(line)
    return referral_of_ifsp(ifsp) if ifsp else None


def referral_of_auth(auth):
    line = line_of_auth(auth)
    return referral_of_line(line) if line else None


def referral_of_visit(visit):
    auth = auth_of_visit(visit)
    return referral_of_auth(auth) if auth else None


def active_ifsp(referral):
    plans = [i for i in referral_ifsps(referral["id"]) if i["status"] == "ACTIVE"]
    return plans[-1] if plans else None


def referral_assessments(referral_id):
    return ordered(db.assessments, [a for a in db.assessments.values()
                                    if a["referral_id"] == referral_id])


def referral_contact_logs(referral_id):
    return ordered(db.contact_logs, [c for c in db.contact_logs.values()
                                     if c["referral_id"] == referral_id])


def referral_cost_shares(referral_id):
    return ordered(db.cost_shares, [c for c in db.cost_shares.values()
                                    if c["referral_id"] == referral_id])


def referral_visits(referral_id):
    out = []
    for visit in db.visits.values():
        ref = referral_of_visit(visit)
        if ref is not None and ref["id"] == referral_id:
            out.append(visit)
    return ordered(db.visits, out)


def ifsp_transition_plans(ifsp_id):
    return ordered(db.transition_plans, [t for t in db.transition_plans.values()
                                         if t["ifsp_id"] == ifsp_id])


def child_of(referral):
    return db.children.get(referral["child_id"])


def third_birthday_of(referral):
    child = child_of(referral)
    if child is None:
        return None
    return pd(child["third_birthday_date"])


# -------------------------------------------------------------- child counters

def recompute_child_count(child):
    if child is None:
        return
    count = len([r for r in db.referrals.values()
                 if r["child_id"] == child["id"]
                 and r["status"] not in D.REFERRAL_TERMINAL])
    set_field(child, "active_referral_count", count)


def third_birthday_date(dob):
    return add_years(dob, D.EI_AGE_LIMIT_YEARS)


# ------------------------------------------------------------------ plan counts

def recompute_ifsp_counts(ifsp):
    if ifsp is None:
        return
    lines = [s for s in ifsp_lines(ifsp["id"]) if s["status"] != "DISCONTINUED"]
    set_field(ifsp, "service_line_count", len(lines))
    set_field(ifsp, "non_natural_setting_line_count",
              len([s for s in lines
                   if s["setting_code"] in D.NON_NATURAL_SETTINGS]))


# ----------------------------------------------------- service line unit pool

def recompute_auth_units(auth):
    remaining = (auth["authorized_units"] - auth["units_consumed"]
                 - auth["units_released"])
    set_field(auth, "units_remaining", remaining)


def recompute_line_pool(line):
    """calculation: service_unit_pool."""
    if line is None:
        return
    committed = 0
    for auth in line_authorizations(line["id"]):
        status = auth["status"]
        if status in D.AUTHORIZATION_COMMITTED:
            committed += auth["authorized_units"]
        elif status in ("REVOKED", "EXPIRED"):
            committed += auth["authorized_units"] - auth["units_released"]
    set_field(line, "units_committed", committed)
    set_field(line, "units_pool_remaining", line["planned_units_total"] - committed)
    delivered = sum(v["actual_units"] or 0 for v in line_visits(line["id"])
                    if v["visit_status"] == "DELIVERED")
    set_field(line, "units_delivered", delivered)


def compute_makeup_owed(line):
    """calculation: makeup_obligation."""
    owed = 0
    delivered_makeup = 0
    for visit in line_visits(line["id"]):
        if visit["visit_status"] == "CANCELLED_PROVIDER":
            owed += visit["scheduled_units"] or 0
        elif (visit["visit_status"] == "DELIVERED"
              and visit["makeup_for_visit_id"] is not None):
            delivered_makeup += visit["actual_units"] or 0
    return max(0, owed - delivered_makeup)


def recompute_makeup(line):
    if line is None:
        return
    owed = compute_makeup_owed(line)
    set_field(line, "makeup_owed_units", owed)
    if owed > D.MAKEUP_AT_RISK_THRESHOLD_UNITS:
        if line["status"] in ("AUTHORIZED", "IN_DELIVERY"):
            set_field(line, "status", "AT_RISK")
    else:
        if line["status"] == "AT_RISK":
            set_field(line, "status", "IN_DELIVERY")
    return owed


def recompute_provider_count(provider):
    if provider is None:
        return
    count = len([a for a in db.authorizations.values()
                 if a["provider_id"] == provider["id"]
                 and a["status"] == "ACTIVE"])
    set_field(provider, "active_authorization_count", count)


# ------------------------------------------------------------ case weight points

def live_line_count(referral):
    total = 0
    for ifsp in referral_ifsps(referral["id"]):
        for line in ifsp_lines(ifsp["id"]):
            if line["status"] in D.SERVICE_LIVE_STATUSES:
                total += 1
    return total


def compute_case_weight(referral, status=None):
    """calculation: case_weight_points."""
    status = status or referral["status"]
    if status in D.REFERRAL_TERMINAL:
        return 0.00
    points = Decimal("1.00") if status == "ACTIVE_SERVICES" else Decimal("1.50")
    if referral.get("interpreter_required"):
        points += Decimal("0.50")
    tbd = third_birthday_of(referral)
    if tbd is not None:
        days = day_count(clock_date(), tbd)
        if days <= D.TRANSITION_WINDOW_DAYS:
            points += Decimal("0.75")
    if live_line_count(referral) >= 4:
        points += Decimal("0.50")
    if points < Decimal("1.00"):
        points = Decimal("1.00")
    if points > Decimal("3.00"):
        points = Decimal("3.00")
    return q2(points)


def recompute_case_weight(referral):
    set_field(referral, "case_weight_points", compute_case_weight(referral),
              bump=False)


# -------------------------------------------------------- coordinator aggregates

def coordinator_referrals(coordinator_id):
    return [r for r in db.referrals.values()
            if r["coordinator_id"] == coordinator_id
            and r["status"] not in D.REFERRAL_TERMINAL]


def recompute_coordinator(coordinator):
    """calculation: coordinator_caseload_aggregate."""
    if coordinator is None:
        return
    rows = coordinator_referrals(coordinator["id"])
    weighted = sum(dec(r["case_weight_points"] or 0) for r in rows)
    weighted = q(weighted, 2)
    maximum = dec(coordinator["max_weighted_caseload_points"])
    set_field(coordinator, "active_case_count", len(rows))
    set_field(coordinator, "weighted_caseload_points", float(weighted))
    ratio = q(weighted / maximum, 4) if maximum != 0 else Decimal("0.0000")
    set_field(coordinator, "utilization_ratio", float(ratio))


def caseload_posture(coordinator):
    weighted = dec(coordinator["weighted_caseload_points"] or 0)
    maximum = dec(coordinator["max_weighted_caseload_points"])
    if weighted > maximum:
        return "OVER"
    if weighted == maximum:
        return "AT_CAP"
    if dec(coordinator["utilization_ratio"] or 0) >= Decimal("0.9000"):
        return "NEAR_CAP"
    return "OPEN"


def headroom_points(coordinator):
    weighted = dec(coordinator["weighted_caseload_points"] or 0)
    maximum = dec(coordinator["max_weighted_caseload_points"])
    return q2(maximum - weighted)


# ------------------------------------------------------------------- timeline

def timeline_stop(referral):
    """The statutory clock stop date and whether an INITIAL plan supplied it."""
    candidates = [i for i in referral_ifsps(referral["id"])
                  if i["ifsp_type"] == "INITIAL"
                  and i["status"] in D.IFSP_STOP_CLOCK_STATUSES
                  and i["meeting_date"]]
    if candidates:
        return pd(candidates[-1]["meeting_date"]), True
    return clock_date(), False


def compute_timeline(referral):
    """calculation: initial_timeline_compliance."""
    received = pd(referral["referral_received_date"])
    stop_date, stopped = timeline_stop(referral)
    gross = day_count(received, stop_date)
    excluded = sum(a["family_unavailable_days"] or 0
                   for a in referral_assessments(referral["id"])
                   if a["status"] == "COMPLETED")
    net = max(0, gross - excluded)
    if net <= D.STATUTORY_TIMELINE_DAYS:
        status = "MET" if stopped else "IN_PROGRESS"
    else:
        status = "MISSED"
    return {
        "stop_date": iso_date(stop_date),
        "gross_elapsed_days": gross,
        "excluded_delay_days": excluded,
        "net_elapsed_days": net,
        "initial_timeline_status": status,
    }


def recompute_timeline(referral):
    result = compute_timeline(referral)
    set_fields(referral, {
        "gross_elapsed_days": result["gross_elapsed_days"],
        "excluded_delay_days": result["excluded_delay_days"],
        "net_elapsed_days": result["net_elapsed_days"],
        "initial_timeline_status": result["initial_timeline_status"],
    }, bump=False)
    return result


def recompute_initial_meeting_date(referral):
    candidates = [i for i in referral_ifsps(referral["id"])
                  if i["ifsp_type"] == "INITIAL"
                  and i["status"] in D.IFSP_MEETING_DATE_STATUSES
                  and i["meeting_date"]]
    value = candidates[-1]["meeting_date"] if candidates else None
    set_field(referral, "initial_ifsp_meeting_date", value, bump=False)


# --------------------------------------------------------- monthly contact rule

def recompute_monthly_contact(referral):
    """calculation: monthly_contact_compliance."""
    logs = [c for c in referral_contact_logs(referral["id"])
            if c["qualifies_for_monthly_requirement"]]
    dates = [pd(c["contact_date"]) for c in logs]
    last = max(dates) if dates else None
    set_field(referral, "last_qualifying_contact_date", iso_date(last), bump=False)
    if referral["status"] != "ACTIVE_SERVICES":
        set_field(referral, "monthly_contact_status", "NOT_APPLICABLE", bump=False)
        return
    today = clock_date()
    bucket = "%04d-%02d" % (today.year, today.month)
    in_month = [d for d in dates if d is not None
                and "%04d-%02d" % (d.year, d.month) == bucket]
    if in_month:
        status = "COMPLIANT"
    elif today.day <= 20:
        status = "DUE"
    else:
        status = "DELINQUENT"
    set_field(referral, "monthly_contact_status", status, bump=False)


def recompute_service_gap(referral):
    """service_gap_flag: true while any line on the case remains AT_RISK."""
    flag = False
    for plan in referral_ifsps(referral["id"]):
        for line in ifsp_lines(plan["id"]):
            if line["status"] == "AT_RISK":
                flag = True
    set_field(referral, "service_gap_flag", flag, bump=False)


# ------------------------------------------------------------- child outcomes

def progress_category(entry, exit_rating):
    if entry is None or exit_rating is None:
        return None
    if exit_rating < entry:
        return "a"
    if exit_rating == entry and exit_rating < D.AGE_EXPECTED_RATING:
        return "b"
    if exit_rating > entry and exit_rating < D.AGE_EXPECTED_RATING:
        return "c"
    if exit_rating >= D.AGE_EXPECTED_RATING and entry < D.AGE_EXPECTED_RATING:
        return "d"
    return "e"


def compute_outcomes(referral, exit_date_str):
    """calculation: child_outcome_progress_category."""
    start = pd(referral["services_start_date"])
    end = pd(exit_date_str)
    duration = day_count(start, end) if start and end else None
    if duration is None or duration < D.COMPARABLE_SERVICE_DAYS:
        categories = ("NOT_COMPARABLE", "NOT_COMPARABLE", "NOT_COMPARABLE")
    else:
        categories = (
            progress_category(referral["entry_rating_social"],
                              referral["exit_rating_social"]),
            progress_category(referral["entry_rating_knowledge"],
                              referral["exit_rating_knowledge"]),
            progress_category(referral["entry_rating_needs"],
                              referral["exit_rating_needs"]),
        )
    return duration, categories
