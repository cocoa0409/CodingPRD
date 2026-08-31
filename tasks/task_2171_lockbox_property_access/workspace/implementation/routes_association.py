"""Association, recovery summary, compliance checkpoint and the logical clock."""
from flask import Blueprint, request

import calc
import serialize
from cascades import create_charge, suspend_active_credentials
from core import (
    ADMIN, AUDITOR, READ_ROLES, authenticate, body, db, end_of_day, fail, iso,
    is_int, is_num, is_str, lookup, new_common, now, num2, ok, ordered,
    parse_date, parse_dt, present, touch,
)

bp = Blueprint("association", __name__)

POLICY_INT_FIELDS = {
    "temp_code_daily_limit": (3, 0),
    "temp_code_overage_fee_cents": (500, 0),
    "removal_grace_days": (3, 0),
    "late_removal_daily_fee_cents": (1500, 0),
    "late_removal_cap_cents": (15000, 0),
    "credential_cap_per_member": (2, 0),
    "grant_buffer_minutes": (15, 0),
}


@bp.post("/associations")
def create_association():
    authenticate([ADMIN])
    payload = body()
    for field in ("name", "jurisdiction_code"):
        if not present(payload, field) or not is_str(payload[field]) or not payload[field].strip():
            fail("ERR_INVALID_REQUEST", "%s is required." % field)
    rec = new_common()
    rec["name"] = payload["name"]
    rec["jurisdiction_code"] = payload["jurisdiction_code"]
    for field, (default, minimum) in POLICY_INT_FIELDS.items():
        if present(payload, field):
            value = payload[field]
            if not is_int(value) or value < minimum:
                fail("ERR_INVALID_REQUEST", "%s must be an integer >= %d." % (field, minimum))
            rec[field] = value
        else:
            rec[field] = default
    if present(payload, "recovery_target_pct"):
        value = payload["recovery_target_pct"]
        if not is_num(value):
            fail("ERR_INVALID_REQUEST", "recovery_target_pct must be a number.")
        rec["recovery_target_pct"] = num2(value)
    else:
        rec["recovery_target_pct"] = 95.00
    rec["recovery_rate_pct"] = 0.00
    db.associations[rec["id"]] = rec
    return ok(serialize.association(rec), 201)


@bp.get("/associations/<association_id>")
def read_association(association_id):
    authenticate(READ_ROLES)
    rec = lookup("associations", association_id)
    return ok(serialize.association(rec))


@bp.get("/associations/<association_id>/recovery-summary")
def recovery_summary(association_id):
    authenticate([ADMIN, AUDITOR])
    rec = lookup("associations", association_id)

    variant = request.args.get("variant")
    if variant is None or variant == "":
        variant = "closing_cohort"
    if variant not in ("closing_cohort", "removal_activity"):
        fail("ERR_INVALID_REQUEST", "variant must be closing_cohort or removal_activity.")

    default_start, default_end = calc.recovery_window_defaults()
    raw_start = request.args.get("window_start")
    raw_end = request.args.get("window_end")
    if raw_start:
        window_start = parse_dt(raw_start)
        if window_start is None:
            fail("ERR_INVALID_REQUEST", "window_start must be an ISO 8601 instant.")
    else:
        window_start = default_start
    if raw_end:
        window_end = parse_dt(raw_end)
        if window_end is None:
            fail("ERR_INVALID_REQUEST", "window_end must be an ISO 8601 instant.")
    else:
        window_end = default_end

    denominator, numerator, rate = calc.lockbox_recovery_rate(
        association_id, variant, window_start, window_end
    )
    return ok({
        "variant": variant,
        "window_start": iso(window_start),
        "window_end": iso(window_end),
        "denominator_count": denominator,
        "numerator_count": numerator,
        "recovery_rate_pct": rate,
        "recovery_target_pct": rec["recovery_target_pct"],
        "posture": calc.association_posture(association_id),
    })


@bp.post("/associations/<association_id>/compliance-runs")
def compliance_run(association_id):
    authenticate([ADMIN])
    association = lookup("associations", association_id)
    run_at = now()
    aid = association_id

    # Step 1 — expire grants.
    expired_grant_count = 0
    for grant in ordered(db.grants):
        if grant["status"] not in ("REQUESTED", "APPROVED"):
            continue
        listing = db.listings.get(grant["listing_id"])
        if listing is None or listing["association_id"] != aid:
            continue
        window_end = parse_dt(grant["window_end"])
        if window_end is not None and window_end <= run_at:
            grant["status"] = "EXPIRED"
            touch(grant)
            expired_grant_count += 1

    # Step 2 — expire credentials.
    expired_credential_count = 0
    for cred in ordered(db.credentials):
        if cred["status"] not in ("ACTIVE", "SUSPENDED"):
            continue
        member = db.members.get(cred["member_id"])
        if member is None or member["association_id"] != aid:
            continue
        expires_at = parse_dt(cred["expires_at"])
        if expires_at is not None and expires_at <= run_at:
            cred["status"] = "EXPIRED"
            touch(cred)
            expired_credential_count += 1

    # Step 3 — expire memberships (credentials already expired above).
    expired_member_count = 0
    for member in ordered(db.members):
        if member["association_id"] != aid:
            continue
        if member["membership_status"] not in ("ACTIVE", "PROBATION"):
            continue
        paid_through = parse_date(member.get("dues_paid_through"))
        if paid_through is None:
            continue
        if end_of_day(paid_through) < run_at:
            member["membership_status"] = "EXPIRED"
            suspend_active_credentials(member["id"])
            touch(member)
            expired_member_count += 1

    # Step 4 — accrue delinquencies.
    delinquent_placement_count = 0
    accrued_charge_count = 0
    for placement in ordered(db.placements):
        if placement["placement_status"] != "REMOVAL_DUE":
            continue
        lockbox = db.lockboxes.get(placement["lockbox_id"])
        if lockbox is None or lockbox["association_id"] != aid:
            continue
        deadline = parse_dt(placement.get("removal_deadline"))
        if deadline is None or not (deadline < run_at):
            continue
        late_days, amount, basis = calc.late_removal_penalty(association, deadline)
        placement["placement_status"] = "DELINQUENT"
        placement["late_days"] = late_days
        if placement["billing_status"] == "NONE":
            placement["billing_status"] = "ACCRUED"
        touch(placement)
        delinquent_placement_count += 1
        create_charge(
            member_id=placement.get("placed_by_member_id"),
            charge_type="LATE_REMOVAL",
            amount_cents=amount,
            variant_applied="NOT_APPLICABLE",
            basis=basis,
            lockbox_id=placement["lockbox_id"],
            placement_id=placement["id"],
        )
        accrued_charge_count += 1

    # Step 5 — recompute the association.
    rate = calc.recompute_recovery_rate(association)

    return ok({
        "run_at": iso(run_at),
        "expired_grant_count": expired_grant_count,
        "expired_credential_count": expired_credential_count,
        "expired_member_count": expired_member_count,
        "delinquent_placement_count": delinquent_placement_count,
        "accrued_charge_count": accrued_charge_count,
        "recovery_rate_pct": rate,
        "posture": calc.association_posture(aid),
    })


@bp.post("/_clock/set_current_utc")
def set_clock():
    authenticate([ADMIN])
    payload = body()
    if not present(payload, "to_iso8601"):
        fail("ERR_INVALID_REQUEST", "to_iso8601 is required.")
    moment = parse_dt(payload["to_iso8601"])
    if moment is None:
        fail("ERR_INVALID_REQUEST", "to_iso8601 must be an ISO 8601 instant.")
    db.clock = moment
    return ok({"current_utc": iso(db.clock)})
