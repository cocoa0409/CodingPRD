"""Row lookup and date helpers shared by calculations, cascades and routes."""

from datetime import date, timedelta

import store
from store import DB


# --- date helpers --------------------------------------------------------

def pd(s):
    return date(int(s[0:4]), int(s[5:7]), int(s[8:10]))


def ds(d):
    return "%04d-%02d-%02d" % (d.year, d.month, d.day)


def shift(s, days):
    return ds(pd(s) + timedelta(days=days))


def day_span(start_s, end_s):
    """Inclusive list of date strings from start to end (empty when reversed)."""
    out = []
    cur = pd(start_s)
    last = pd(end_s)
    while cur <= last:
        out.append(ds(cur))
        cur = cur + timedelta(days=1)
    return out


def stay_nights(arrival_s, nights):
    """Half-open stay: arrival inclusive, departure exclusive."""
    start = pd(arrival_s)
    return [ds(start + timedelta(days=i)) for i in range(nights)]


def clock_date_str():
    return ds(store.clock_date())


def covers(rec, day_s):
    """Closed start_date..end_date range containment."""
    return rec["start_date"] <= day_s <= rec["end_date"]


def stay_covers(res, day_s):
    return res["arrival_date"] <= day_s < res["departure_date"]


# --- table helpers -------------------------------------------------------

def rows(table):
    return store.ordered(list(DB[table].values()))


def get(table, row_id):
    if not isinstance(row_id, str):
        return None
    return DB[table].get(row_id)


def put(table, rec):
    DB[table][rec["id"]] = rec
    return rec


def where(table, **kw):
    out = []
    for rec in rows(table):
        keep = True
        for key, val in kw.items():
            if rec.get(key) != val:
                keep = False
                break
        if keep:
            out.append(rec)
    return out


# --- entity navigation ---------------------------------------------------

def prop_of_room_type(rt):
    return get("properties", rt["property_id"])


def prop_of_channel(ch):
    return get("properties", ch["property_id"])


def prop_of_plan(rp):
    return get("properties", rp["property_id"])


def room_type_of_day(day):
    return get("room_types", day["room_type_id"])


def prop_of_day(day):
    return prop_of_room_type(room_type_of_day(day))


def connection_of_channel(channel_id):
    """The channel's live connection: the non-RETIRED one, else the newest."""
    found = where("connections", channel_id=channel_id)
    if not found:
        return None
    live = [c for c in found if c["connection_state"] != "RETIRED"]
    if live:
        return live[-1]
    return found[-1]


def inventory_day(room_type_id, stay_date):
    for day in rows("inventory_days"):
        if day["room_type_id"] == room_type_id and day["stay_date"] == stay_date:
            return day
    return None


def days_of_room_type(room_type_id):
    return [d for d in rows("inventory_days") if d["room_type_id"] == room_type_id]


def mappings_of_plan(rate_plan_id):
    return where("mappings", rate_plan_id=rate_plan_id)


def verified_mappings_of_plan(rate_plan_id):
    return [m for m in mappings_of_plan(rate_plan_id) if m["mapping_state"] == "VERIFIED"]


def verified_mappings_of_room_type(room_type_id):
    return [m for m in where("mappings", room_type_id=room_type_id)
            if m["mapping_state"] == "VERIFIED"]


def descendants_of_plan(plan_id):
    """Every plan whose parent chain reaches plan_id, parents before children."""
    out = []
    frontier = [plan_id]
    while frontier:
        nxt = []
        for parent_id in frontier:
            for plan in rows("rate_plans"):
                if plan["parent_rate_plan_id"] == parent_id:
                    out.append(plan)
                    nxt.append(plan["id"])
        frontier = nxt
    return out


def plan_family(plan):
    """The plan itself followed by every descendant, parent before child."""
    return [plan] + descendants_of_plan(plan["id"])


def jobs_of_batch(batch_id):
    return where("jobs", batch_id=batch_id)


def jobs_of_mapping(mapping_id):
    return where("jobs", channel_mapping_id=mapping_id)


def confirmed_reservations():
    return [r for r in rows("reservations") if r["reservation_state"] == "CONFIRMED"]
