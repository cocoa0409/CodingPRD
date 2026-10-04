"""PlanElection: AEP (last-in-wins supersede) / OEP_MA (single-use),
OCC-guarded on Beneficiary.version."""
from __future__ import annotations

from authn import (ROLE_BENEFICIARY, ROLE_FIELD_OFFICER, authenticate,
                   authorize, body_beneficiary_ownership, check_ownership)
from clock import add_months, clock_month, month_str, now
from db import find, find_one, get, make_entity, public, sort_entities, touch
from envelope import success_list, success_object
from errors import fail
from validate import (body_json, pagination_args, paginate, req_enum, req_int,
                      req_str)

ELECTION_WINDOWS = ("AEP", "OEP_MA")
COVERAGE_KINDS = ("ORIGINAL", "MA")


def _aep_open() -> bool:
    """Oct 15 00:00:00 UTC through Dec 7 23:59:59 UTC of the clock year."""
    n = now()
    return ((n.month == 10 and n.day >= 15)
            or n.month == 11
            or (n.month == 12 and n.day <= 7))


def _oep_open() -> bool:
    """January 1 through March 31 of the clock year."""
    return now().month in (1, 2, 3)


def create_election():
    role, uid = authenticate()
    authorize(role, [ROLE_BENEFICIARY])
    body = body_json()
    body_beneficiary_ownership(role, uid, body)
    bid = req_str(body, "beneficiary_id")
    window = req_enum(body, "election_window", ELECTION_WINDOWS)
    target = req_enum(body, "target_coverage", COVERAGE_KINDS)
    expected_version = req_int(body, "expected_beneficiary_version")
    benef = get("beneficiaries", bid)
    if not benef:
        fail("ERR_BENEFICIARY_NOT_FOUND", "No beneficiary with that id")
    # Pinned order: OCC -> window -> OEP constraints -> target check
    if expected_version != benef["version"]:
        fail("ERR_STALE_BENEFICIARY_VERSION",
             "expected_beneficiary_version does not match Beneficiary.version")
    year = now().year
    if window == "AEP":
        if not _aep_open():
            fail("ERR_ELECTION_WINDOW_CLOSED",
                 "Clock is outside the AEP window (Oct 15 - Dec 7)")
        season_key = f"AEP-{year:04d}"
        effective_ym = (year + 1, 1)
    else:  # OEP_MA
        if not _oep_open():
            fail("ERR_ELECTION_WINDOW_CLOSED",
                 "Clock is outside the OEP_MA window (Jan 1 - Mar 31)")
        has_part_c = find_one("enrollments",
                              lambda e: e["beneficiary_id"] == bid
                              and e["part"] == "PART_C"
                              and e["enrollment_status"] == "ACTIVE")
        if not has_part_c:
            fail("ERR_OEP_REQUIRES_MA",
                 "OEP_MA election requires an ACTIVE PART_C enrollment")
        season_key = f"OEP-{year:04d}"
        used = find_one("elections",
                        lambda e: e["beneficiary_id"] == bid
                        and e["season_key"] == season_key)
        if used:
            fail("ERR_OEP_ELECTION_ALREADY_USED",
                 "An election already exists for this OEP season")
        effective_ym = add_months(clock_month(), 1)
    current = "MA" if find_one(
        "enrollments",
        lambda e: e["beneficiary_id"] == bid
        and e["part"] == "PART_C"
        and e["enrollment_status"] in ("PENDING", "ACTIVE")) else "ORIGINAL"
    if target == current:
        fail("ERR_ELECTION_TARGET_UNCHANGED",
             "target_coverage equals current_coverage")
    if window == "AEP":
        # last-in-wins: supersede the prior GOVERNING election of the season
        prior = find_one("elections",
                         lambda e: e["beneficiary_id"] == bid
                         and e["season_key"] == season_key
                         and e["status"] == "GOVERNING")
        if prior:
            prior["status"] = "SUPERSEDED"
            touch(prior)
    election = make_entity("elections", {
        "beneficiary_id": bid,
        "election_window": window,
        "season_key": season_key,
        "current_coverage": current,
        "target_coverage": target,
        "effective_month": month_str(effective_ym),
        "status": "GOVERNING",
    })
    # A successful election creation advances the Beneficiary OCC version
    benef["version"] = int(benef["version"]) + 1
    benef["updated_at"] = election["created_at"]
    return success_object(public(election), 201)


def list_elections(beneficiary_id):
    role, uid = authenticate()
    authorize(role, [ROLE_BENEFICIARY, ROLE_FIELD_OFFICER])
    check_ownership(role, uid, beneficiary_id)
    if not get("beneficiaries", beneficiary_id):
        fail("ERR_BENEFICIARY_NOT_FOUND", "No beneficiary with that id")
    limit, offset = pagination_args()
    rows = sort_entities(find("elections",
                              lambda e: e["beneficiary_id"] == beneficiary_id))
    page, total = paginate(rows, limit, offset)
    return success_list([public(e) for e in page], limit, offset, total)


def register(app):
    app.add_url_rule("/medicare/elections", "create_election",
                     create_election, methods=["POST"])
    app.add_url_rule("/medicare/beneficiaries/<beneficiary_id>/elections",
                     "list_elections", list_elections, methods=["GET"])
