"""RateSchedule publication."""
from __future__ import annotations

from authn import ROLE_BENEFIT_ADMINISTRATOR, authenticate, authorize
from calcs import IRMAA_TIER_COUNT
from db import find_one, make_entity, public
from envelope import success_object
from errors import fail
from validate import body_json, req_int, req_list

_BRACKET_FIELDS = ("single_floor_cents", "joint_floor_cents",
                   "part_b_surcharge_cents", "part_d_surcharge_cents")


def _validate_brackets(raw):
    if len(raw) != IRMAA_TIER_COUNT:
        fail("ERR_VALIDATION", "irmaa_brackets must contain exactly 6 entries")
    tiers = set()
    for b in raw:
        if not isinstance(b, dict):
            fail("ERR_VALIDATION", "Each irmaa_brackets entry must be an object")
        tier = b.get("tier")
        if not isinstance(tier, int) or isinstance(tier, bool) \
                or tier < 0 or tier >= IRMAA_TIER_COUNT:
            fail("ERR_VALIDATION", "irmaa_brackets tiers must be 0..5")
        tiers.add(tier)
        for f in _BRACKET_FIELDS:
            v = b.get(f)
            if not isinstance(v, int) or isinstance(v, bool) or v < 0:
                fail("ERR_VALIDATION",
                     f"irmaa_brackets.{f} must be a non-negative integer")
    if tiers != set(range(IRMAA_TIER_COUNT)):
        fail("ERR_VALIDATION", "irmaa_brackets must cover tiers 0..5")
    return raw


def create_rate_schedule():
    role, uid = authenticate()
    authorize(role, [ROLE_BENEFIT_ADMINISTRATOR])
    body = body_json()
    coverage_year = req_int(body, "coverage_year")
    part_b = req_int(body, "part_b_standard_cents", minimum=0)
    part_d = req_int(body, "part_d_national_base_cents", minimum=0)
    brackets = _validate_brackets(req_list(body, "irmaa_brackets"))
    if find_one("rate_schedules",
                lambda r: r["coverage_year"] == coverage_year):
        fail("ERR_DUPLICATE_RATE_SCHEDULE",
             "A RateSchedule for that coverage_year already exists")
    sched = make_entity("rate_schedules", {
        "coverage_year": coverage_year,
        "part_b_standard_cents": part_b,
        "part_d_national_base_cents": part_d,
        "irmaa_brackets": brackets,
    })
    return success_object(public(sched), 201)


def register(app):
    app.add_url_rule("/medicare/rate-schedules", "create_rate_schedule",
                     create_rate_schedule, methods=["POST"])
