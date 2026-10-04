from flask import Blueprint, request

from db import store, new_entity, touch, parse_date, parse_iso8601, set_clock
from errors import bad_request, not_found, invalid_state
from middleware import (auth, body, need, need_str, need_int, need_date, is_int,
                        paginate)
from response import ok
from serialize import site_json, school_json, application_json, member_json
import services as svc

bp = Blueprint("sites", __name__)

FUNDING_TYPES = {"DISTRICT": "district_received_cents",
                 "PHILANTHROPY": "philanthropy_received_cents",
                 "FEDERAL": "federal_received_cents"}


@bp.route("/corps/_clock/set_current_utc", methods=["POST"])
def set_current_utc():
    auth(["SiteDirector"])
    data = body()
    to_iso8601 = need(data, "to_iso8601")
    try:
        parse_iso8601(to_iso8601)
    except (ValueError, TypeError):
        bad_request("to_iso8601 must be a valid ISO8601 instant")
    set_clock(to_iso8601)
    return ok({"current_utc": store.clock_iso}, 200)


@bp.route("/corps/sites", methods=["POST"])
def create_site():
    auth(["SiteDirector"])
    data = body()
    name = need_str(data, "name")
    city = need_str(data, "city")
    sy_start = need_date(data, "service_year_start")
    sy_end = need_date(data, "service_year_end")
    stipend = need_int(data, "annual_stipend_cents")
    if stipend <= 0:
        bad_request("annual_stipend_cents must be > 0")
    if parse_date(sy_end) <= parse_date(sy_start):
        bad_request("service_year_end must be after service_year_start")
    committed = {}
    for f in ("district_committed_cents", "philanthropy_committed_cents",
              "federal_committed_cents"):
        v = data.get(f, 0)
        if not is_int(v) or v < 0:
            bad_request("%s must be a non-negative integer" % f)
        committed[f] = v
    s = new_entity({
        "name": name,
        "city": city,
        "service_year_start": sy_start,
        "service_year_end": sy_end,
        "annual_stipend_cents": stipend,
        "district_committed_cents": committed["district_committed_cents"],
        "philanthropy_committed_cents": committed["philanthropy_committed_cents"],
        "federal_committed_cents": committed["federal_committed_cents"],
        "district_received_cents": 0,
        "philanthropy_received_cents": 0,
        "federal_received_cents": 0,
        "status": "SETUP",
    })
    store.sites[s["id"]] = s
    return ok(site_json(s), 201)


def get_site_or_404(site_id):
    s = store.sites.get(site_id)
    if s is None:
        not_found("Site not found")
    return s


@bp.route("/corps/sites/<site_id>", methods=["GET"])
def get_site(site_id):
    auth(["SiteDirector", "ProgramManager", "StipendAdministrator"])
    return ok(site_json(get_site_or_404(site_id)), 200)


@bp.route("/corps/sites/<site_id>/state", methods=["POST"])
def site_state(site_id):
    auth(["SiteDirector"])
    data = body()
    to_status = need(data, "to_status")
    if to_status not in ("SETUP", "ACTIVE", "CLOSED"):
        bad_request("to_status must be a valid Site status")
    s = get_site_or_404(site_id)
    if to_status == "ACTIVE" and s["status"] == "SETUP":
        s["status"] = "ACTIVE"
    elif to_status == "CLOSED" and s["status"] == "ACTIVE":
        live = [m for m in svc.members_of_site(s["id"])
                if m["service_status"] in ("ENROLLED", "ACTIVE", "SUSPENDED")]
        if live:
            invalid_state("Site has corps members still serving")
        school_ids = {sc["id"] for sc in svc.schools_of_site(s["id"])}
        live_teams = [t for t in store.teams.values()
                      if t["school_id"] in school_ids
                      and t["status"] in ("FORMING", "DEPLOYED", "UNDERSTAFFED")]
        if live_teams:
            invalid_state("Site has teams still running")
        s["status"] = "CLOSED"
    else:
        invalid_state("Site status %s cannot transition to %s"
                      % (s["status"], to_status))
    touch(s)
    return ok(site_json(s), 200)


@bp.route("/corps/sites/<site_id>/funding/receive", methods=["POST"])
def funding_receive(site_id):
    auth(["SiteDirector"])
    data = body()
    funding_type = need(data, "funding_type")
    if funding_type not in FUNDING_TYPES:
        bad_request("funding_type must be DISTRICT, PHILANTHROPY or FEDERAL")
    amount = need(data, "amount_cents")
    if not is_int(amount) or amount < 0:
        bad_request("amount_cents must be a non-negative integer")
    s = get_site_or_404(site_id)
    s[FUNDING_TYPES[funding_type]] += amount
    touch(s)
    return ok(site_json(s), 200)


# ---- site-scoped list endpoints -------------------------------------------

@bp.route("/corps/sites/<site_id>/schools", methods=["GET"])
def list_site_schools(site_id):
    auth(["SiteDirector", "ProgramManager", "SchoolLiaison"])
    s = get_site_or_404(site_id)
    items = svc.schools_of_site(s["id"])
    flt = request.args.get("agreement_status")
    if flt is not None:
        items = [x for x in items if x["agreement_status"] == flt]
    page, pg = paginate(items)
    return ok([school_json(x) for x in page], 200, is_array=True, pagination=pg)


@bp.route("/corps/sites/<site_id>/applications", methods=["GET"])
def list_site_applications(site_id):
    auth(["SiteDirector", "ProgramManager"])
    s = get_site_or_404(site_id)
    items = [a for a in store.applications.values() if a["site_id"] == s["id"]]
    flt = request.args.get("status")
    if flt is not None:
        items = [x for x in items if x["status"] == flt]
    page, pg = paginate(items)
    return ok([application_json(x) for x in page], 200, is_array=True, pagination=pg)


@bp.route("/corps/sites/<site_id>/members", methods=["GET"])
def list_site_members(site_id):
    auth(["SiteDirector", "ProgramManager", "StipendAdministrator"])
    s = get_site_or_404(site_id)
    items = svc.members_of_site(s["id"])
    if request.args.get("service_status") is not None:
        items = [x for x in items
                 if x["service_status"] == request.args.get("service_status")]
    if request.args.get("stipend_status") is not None:
        items = [x for x in items
                 if x["stipend_status"] == request.args.get("stipend_status")]
    page, pg = paginate(items)
    return ok([member_json(x) for x in page], 200, is_array=True, pagination=pg)
