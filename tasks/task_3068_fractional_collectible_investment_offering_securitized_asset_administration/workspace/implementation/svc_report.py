"""Ongoing investor reporting (§3.2)."""
from collections import OrderedDict

from envelope import ApiError, invalid_request, invalid_state, not_found
from store import DB, parse_dt, to_ms, add_days
from models import make_report, insert_index
from svc_common import body, require, as_int, enum_value
import views


def _offering(offering_id):
    row = DB.offerings.get(offering_id)
    if row is None:
        raise not_found("Offering %s does not exist." % offering_id)
    return row


def _shareholder_count(offering_id, as_of):
    """Distinct investors holding at least one accepted share as of as_of."""
    holders = set()
    for sub in DB.subscriptions.values():
        if sub["offering_id"] != offering_id:
            continue
        if int(sub.get("accepted_shares") or 0) < 1:
            continue
        if as_of is not None and sub.get("created_at") and sub["created_at"] > as_of:
            continue
        holders.add(sub["investor_id"])
    return len(holders)


def _quarter_marker(report):
    """True when the filing falls in a tax year whose quarter-end lies outside
    the window covered by the selected appraisals — i.e. the quarter the filing
    speaks to has closed since the artwork was last appraised."""
    offering = DB.offerings.get(report["offering_id"])
    artwork = DB.artworks.get(offering["artwork_id"]) if offering else None
    if artwork is None:
        return False
    appraisals = [a for a in DB.appraisals.values()
                  if a["artwork_id"] == artwork["id"] and a.get("is_selected")]
    if not appraisals:
        return False
    newest = max(parse_dt(a["filed_at"]) for a in appraisals)
    filed = parse_dt(report["filed_at"])
    if filed is None or newest is None:
        return False
    month = filed.month
    quarter_end_month = ((month - 1) // 3) * 3 + 3
    year = filed.year
    day = 31 if quarter_end_month in (3, 12) else 30
    quarter_end = parse_dt("%04d-%02d-%02dT00:00:00Z" % (year, quarter_end_month, day))
    if quarter_end is None:
        return False
    return quarter_end > newest


def file_report(offering_id):
    offering = _offering(offering_id)
    data = body()
    require(data, ["report_kind", "as_of_date"])
    kind = enum_value(data, "report_kind", "report_kind")
    as_of = data.get("as_of_date")
    as_of_dt = parse_dt(as_of)
    if as_of_dt is None:
        raise invalid_request("as_of_date is not a valid ISO 8601 instant.")
    as_of = to_ms(as_of_dt)
    value = as_int(data, "value_per_share_cents")
    if kind == "QUARTERLY":
        if value is None:
            raise invalid_request("value_per_share_cents is required for a QUARTERLY report.")
    elif value is not None:
        raise invalid_request("value_per_share_cents must be null for this report kind.")

    # window: neither before the offering's latest report nor after the clock
    latest = None
    for r in DB.offering_reports.values():
        if r["offering_id"] == offering_id:
            if latest is None or parse_dt(r["as_of_date"]) > parse_dt(latest["as_of_date"]):
                latest = r
    now = to_ms(DB.now())
    if as_of > now:
        raise ApiError("ERR_REPORT_WINDOW_FORECLOSED",
                       "as_of_date post-dates the current clock.")
    if latest is not None and parse_dt(as_of) < parse_dt(latest["as_of_date"]):
        raise ApiError("ERR_REPORT_WINDOW_FORECLOSED",
                       "as_of_date precedes the offering's most recent report.")

    row = make_report(offering, {**data, "as_of_date": as_of,
                                 "value_per_share_cents": value})
    row["shareholder_count"] = _shareholder_count(offering_id, as_of)
    row["is_quarter_marker"] = _quarter_marker(row)
    return views.report(row), 201


def list_reports(offering_id, query):
    _offering(offering_id)
    rows = DB.ordered("offering_reports", lambda r: r["offering_id"] == offering_id)
    kind = query.get("report_kind")
    if kind:
        rows = [r for r in rows if r["report_kind"] == kind]
    flag = query.get("is_quarter_marker")
    if flag is not None and flag != "":
        want = str(flag).lower() in ("true", "1", "yes")
        rows = [r for r in rows if bool(r.get("is_quarter_marker")) == want]
    return rows