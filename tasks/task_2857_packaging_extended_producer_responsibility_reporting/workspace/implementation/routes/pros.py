"""Producer responsibility organisation and fee schedule endpoints (PRD 3.4)."""
from datetime import timedelta

from flask import Blueprint

import calc
import store
import validation as v
from auth import (OFFICER, PRO_ADMIN, REGULATOR, endpoint, must, new_row,
                  require_pro_owner, touch)
from envelope import ok_entity, ok_list
from errors import fail
from routes.common import enum_filter, listing, str_filter

bp = Blueprint("pros", __name__)


@bp.post("/epr/pros")
@endpoint([REGULATOR])
def create_pro():
    body = v.body()
    name = v.req_str(body, "name")
    contact_email = v.req_str(body, "contact_email")
    for existing in store.values("pros"):
        if existing["name"] == name:
            fail("ERR_INVALID_REQUEST", "A producer responsibility organisation named '%s' already exists." % name)
    row = new_row("pros", {"name": name, "contact_email": contact_email})
    return ok_entity(row, 201)


@bp.get("/epr/pros/<pid>")
@endpoint([REGULATOR, OFFICER, PRO_ADMIN])
def get_pro(pid):
    return ok_entity(must("pros", pid))


@bp.get("/epr/pros")
@endpoint([REGULATOR, OFFICER, PRO_ADMIN])
def list_pros():
    window, limit, offset, total = listing(store.values("pros"))
    return ok_list(window, limit, offset, total)


def parse_rate(raw, label):
    if not isinstance(raw, dict):
        fail("ERR_INVALID_REQUEST", "%s must be a JSON object." % label)
    material = v.req_enum(raw, "material_type", v.MATERIAL_TYPES)
    tier_min = v.req_decimal(raw, "tier_min_kg", 3, minimum=0)
    tier_max = v.opt_decimal(raw, "tier_max_kg", 3, minimum=0)
    rate = v.req_decimal(raw, "rate_cents_per_kg", 4, minimum=0)
    return {
        "material_type": material,
        "tier_min_kg": tier_min,
        "tier_max_kg": tier_max,
        "rate_cents_per_kg": rate,
    }


def check_tier_partition(rates):
    """Half-open contiguous partition per material (PRD 3.4)."""
    by_material = {}
    for row in rates:
        by_material.setdefault(row["material_type"], []).append(row)
    for material, bands in by_material.items():
        ordered = sorted(bands, key=lambda b: b["tier_min_kg"])
        if ordered[0]["tier_min_kg"] != 0:
            fail("ERR_FEE_TIER_DISCONTINUOUS")
        open_ended = [b for b in ordered if b["tier_max_kg"] is None]
        if len(open_ended) != 1 or ordered[-1]["tier_max_kg"] is not None:
            fail("ERR_FEE_TIER_DISCONTINUOUS")
        for index in range(len(ordered) - 1):
            current = ordered[index]
            following = ordered[index + 1]
            if current["tier_max_kg"] is None:
                fail("ERR_FEE_TIER_DISCONTINUOUS")
            if current["tier_max_kg"] != following["tier_min_kg"]:
                fail("ERR_FEE_TIER_DISCONTINUOUS")


def windows_conflict(new_from, new_to, other_from, other_to):
    """Closed windows are inclusive at both ends, so sharing the boundary day is a
    collision (PRD 3.4); a null end is open-ended and blocks every later window.

    Two windows that merely abut - one ending the day before the next begins -
    do not collide: that is exactly the shape publication truncation produces
    when it sets the older row's `effective_to` to the new `effective_from`
    minus one day.
    """
    if other_to is not None and new_from > other_to:
        return False
    if new_to is not None and other_from > new_to:
        return False
    return True


@bp.post("/epr/fee-schedules")
@endpoint([PRO_ADMIN])
def create_fee_schedule():
    body = v.body()
    pro_id = v.req_str(body, "pro_id")
    program_id = v.req_str(body, "state_program_id")
    effective_from = v.req_date(body, "effective_from")
    effective_to = v.opt_date(body, "effective_to")
    membership_fee = v.req_int(body, "membership_fee_cents", minimum=0)
    bps_low = v.req_int(body, "admin_fee_bps_low", minimum=0, maximum=2000)
    bps_high = v.req_int(body, "admin_fee_bps_high", minimum=0, maximum=2000)
    raw_rates = v.req_list(body, "material_rates")
    rates = [parse_rate(raw, "material_rates[%d]" % i) for i, raw in enumerate(raw_rates)]
    must("pros", pro_id)
    must("state_programs", program_id)
    require_pro_owner(pro_id)
    if effective_to is not None and effective_to < effective_from:
        fail("ERR_INVALID_REQUEST", "Field 'effective_to' must not precede 'effective_from'.")
    for existing in store.values("fee_schedules"):
        if existing["pro_id"] != pro_id or existing["state_program_id"] != program_id:
            continue
        if windows_conflict(
            effective_from, effective_to, existing["_effective_from"], existing["_effective_to"]
        ):
            fail("ERR_FEE_SCHEDULE_EFFECTIVE_OVERLAP")
    if rates:
        check_tier_partition(rates)
    row = new_row(
        "fee_schedules",
        {
            "pro_id": pro_id,
            "state_program_id": program_id,
            "effective_from": effective_from.isoformat(),
            "effective_to": None if effective_to is None else effective_to.isoformat(),
            "membership_fee_cents": membership_fee,
            "admin_fee_bps_low": bps_low,
            "admin_fee_bps_high": bps_high,
            "material_rates": rates,
            "status": "DRAFT",
            "_effective_from": effective_from,
            "_effective_to": effective_to,
        },
    )
    return ok_entity(row, 201)


@bp.get("/epr/fee-schedules/<fid>")
@endpoint([REGULATOR, OFFICER, PRO_ADMIN])
def get_fee_schedule(fid):
    return ok_entity(must("fee_schedules", fid))


@bp.get("/epr/fee-schedules")
@endpoint([REGULATOR, OFFICER, PRO_ADMIN])
def list_fee_schedules():
    pro_id = str_filter("pro_id")
    program_id = str_filter("state_program_id")
    status = enum_filter("status", v.FEE_SCHEDULE_STATUSES)
    rows = store.values("fee_schedules")
    if pro_id is not None:
        rows = [r for r in rows if r["pro_id"] == pro_id]
    if program_id is not None:
        rows = [r for r in rows if r["state_program_id"] == program_id]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    window, limit, offset, total = listing(rows)
    return ok_list(window, limit, offset, total)


@bp.post("/epr/fee-schedules/<fid>/publish")
@endpoint([PRO_ADMIN])
def publish_fee_schedule(fid):
    body = v.body()
    expected = v.req_int(body, "expected_pro_version")
    schedule = must("fee_schedules", fid)
    require_pro_owner(schedule["pro_id"])
    if schedule["status"] != "DRAFT":
        fail("ERR_INVALID_STATE", "The fee schedule is not in DRAFT.")
    pro = store.get("pros", schedule["pro_id"])
    if expected != int(pro["version"]):
        fail("ERR_STALE_PRO_VERSION")
    if not schedule["material_rates"]:
        fail("ERR_FEE_SCHEDULE_HAS_NO_RATES")
    schedule["status"] = "PUBLISHED"
    touch(schedule)
    for other in store.by_created(store.values("fee_schedules")):
        if other["id"] == schedule["id"]:
            continue
        if other["pro_id"] != schedule["pro_id"]:
            continue
        if other["state_program_id"] != schedule["state_program_id"]:
            continue
        if other["status"] != "PUBLISHED" or other["_effective_to"] is not None:
            continue
        truncated = schedule["_effective_from"] - timedelta(days=1)
        other["_effective_to"] = truncated
        other["effective_to"] = truncated.isoformat()
        other["status"] = "SUPERSEDED"
        touch(other)
    touch(pro)
    return ok_entity(schedule)
