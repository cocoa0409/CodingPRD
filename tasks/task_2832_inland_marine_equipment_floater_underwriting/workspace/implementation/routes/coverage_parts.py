import datetime

from flask import Blueprint, g, request

import cascades
import rating
import store
import views
from common import (API_PREFIX, body, clock_date, clock_now, envelope_list,
                    envelope_object, fail, get_bool, get_date, get_enum,
                    get_instant, get_int, get_str, own_policy, paginate,
                    parse_pagination, require)

bp = Blueprint("coverage_parts", __name__)

PART_FIELD = "/coverage-parts/<part_id>"


def _part(part_id):
    return store.find(store.coverage_parts, part_id, "ERR_COVERAGE_PART_NOT_FOUND")


def _guard_part_and_policy(part):
    """Rung 11 (target state) then rung 12 (ancestor state)."""
    if part["status"] == "VOID":
        fail("ERR_PART_VOID", "Coverage part is VOID")
    policy = store.policies[part["policy_id"]]
    if policy["status"] not in rating.MUTABLE_POLICY_STATUSES:
        fail("ERR_POLICY_NOT_MUTABLE", "Policy is %s" % policy["status"])
    return policy


@bp.get(API_PREFIX + PART_FIELD)
def get_part(part_id):
    require("Underwriter", "UnderwritingManager", "ClaimsAdjuster", "Policyholder")
    part = _part(part_id)
    return envelope_object(views.part_view(part), 200)


@bp.patch(API_PREFIX + PART_FIELD)
def endorse_part(part_id):
    require("Underwriter")
    part = _part(part_id)
    b = body()
    updates = {}
    rating_basis = get_enum(b, "rating_basis", ("SCHEDULED", "BLANKET"), required=False)
    if rating_basis is not None:
        updates["rating_basis"] = rating_basis
    valuation_basis = get_enum(b, "valuation_basis", rating.VALUATION_BASES,
                               required=False)
    if valuation_basis is not None:
        updates["valuation_basis"] = valuation_basis
    for field in ("deductible_cents", "blanket_limit_cents", "per_item_limit_cents",
                  "loss_of_use_daily_limit_cents", "transit_owned_limit_cents",
                  "transit_hired_limit_cents", "catastrophe_limit_cents",
                  "reporting_annual_rate_bp", "reporting_limit_cents"):
        value = get_int(b, field, required=False, minimum=0)
        if value is not None:
            updates[field] = value
    coins = get_int(b, "coinsurance_pct_bp", required=False, minimum=5000,
                    maximum=10000)
    if coins is not None:
        updates["coinsurance_pct_bp"] = coins
    max_days = get_int(b, "loss_of_use_max_days", required=False, minimum=1)
    if max_days is not None:
        updates["loss_of_use_max_days"] = max_days
    _guard_part_and_policy(part)
    part.update(updates)
    # Switching a basis does not restate the charged premium; the next quote
    # picks up the other variant.  Raising a limit never restores consumed
    # aggregate capacity.
    store.bump(part)
    return envelope_object(views.part_view(part), 200)


@bp.get(API_PREFIX + PART_FIELD + "/equipment-items")
def list_part_items(part_id):
    require("Underwriter", "UnderwritingManager", "ClaimsAdjuster", "Policyholder")
    _part(part_id)
    limit, offset = parse_pagination()
    status = request.args.get("status")
    rows = store.items_of_part(part_id)
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    page, total = paginate(rows, limit, offset)
    return envelope_list([views.item_view(r) for r in page], limit, offset, total)


@bp.get(API_PREFIX + PART_FIELD + "/value-reports")
def list_part_reports(part_id):
    require("Underwriter", "UnderwritingManager", "ClaimsAdjuster", "Policyholder")
    _part(part_id)
    limit, offset = parse_pagination()
    status = request.args.get("status")
    rows = store.reports_of_part(part_id)
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    page, total = paginate(rows, limit, offset)
    return envelope_list([views.report_view(r) for r in page], limit, offset, total)


def _body_jobsite(b, field):
    """Rung 8: a jobsite_id supplied in the body must resolve."""
    if field not in b or b[field] is None:
        return None
    raw = b[field]
    jobsite = store.jobsites.get(raw) if isinstance(raw, str) else None
    if jobsite is None:
        fail("ERR_JOBSITE_NOT_FOUND", "Jobsite %s does not exist" % (raw,))
    return jobsite


@bp.post(API_PREFIX + PART_FIELD + "/equipment-items")
def schedule_item(part_id):
    require("Underwriter")
    part = _part(part_id)
    b = body()
    jobsite = _body_jobsite(b, "assigned_jobsite_id")
    description = get_str(b, "description", max_len=160)
    equipment_type = get_enum(b, "equipment_type", rating.EQUIPMENT_TYPES)
    model_year = get_int(b, "model_year", minimum=1950, maximum=2100)
    original_cost_cents = get_int(b, "original_cost_cents", minimum=1)
    ownership = get_enum(b, "ownership", ("OWNED", "RENTED", "LEASED"),
                         required=False, default="OWNED")
    expected_policy_version = get_int(b, "expected_policy_version", minimum=0)
    geo_tracker_installed = get_bool(b, "geo_tracker_installed", required=False,
                                     default=False)
    valuation_basis = get_enum(b, "valuation_basis", rating.VALUATION_BASES,
                               required=False)
    effective_basis = valuation_basis or part["valuation_basis"]
    stated_required = effective_basis in ("AGREED_VALUE", "STATED_AMOUNT")
    stated_value_cents = get_int(b, "stated_value_cents", required=stated_required,
                                 minimum=0)
    policy = _guard_part_and_policy(part)
    if expected_policy_version != policy["version"]:
        fail("ERR_STALE_POLICY_VERSION",
             "Policy version is %s, not %s" % (policy["version"],
                                               expected_policy_version))
    candidate = {
        "equipment_type": equipment_type,
        "model_year": model_year,
        "geo_tracker_installed": geo_tracker_installed,
        "assigned_jobsite_id": jobsite["id"] if jobsite else None,
        "valuation_basis": effective_basis,
        "original_cost_cents": original_cost_cents,
        "stated_value_cents": stated_value_cents,
    }
    if jobsite is not None:
        cascades.check_geo_tracking(candidate, policy, jobsite)
    if part["part_type"] not in rating.EQUIPMENT_PART_TYPES:
        fail("ERR_PART_TYPE_MISMATCH",
             "Equipment cannot be scheduled on a %s part" % part["part_type"])
    outcome = rating.rate_equipment_item(candidate, policy)
    per_item = part.get("per_item_limit_cents")
    if per_item is not None and outcome["insured_value_cents"] > per_item:
        fail("ERR_ITEM_VALUE_EXCEEDS_PER_ITEM_LIMIT",
             "Insured value %s exceeds the part's per-item limit %s"
             % (outcome["insured_value_cents"], per_item))
    row = store.make({
        "coverage_part_id": part_id,
        "assigned_jobsite_id": jobsite["id"] if jobsite else None,
        "applied_rate_rule_id": outcome["applied_rate_rule_id"],
        "description": description,
        "equipment_type": equipment_type,
        "model_year": model_year,
        "original_cost_cents": original_cost_cents,
        "stated_value_cents": stated_value_cents,
        "ownership": ownership,
        "geo_tracker_installed": geo_tracker_installed,
        "valuation_basis": effective_basis,
        "age_years_at_rating": outcome["age_years_at_rating"],
        "insured_value_cents": outcome["insured_value_cents"],
        "applied_base_rate_bp": outcome["applied_base_rate_bp"],
        "applied_credit_bp": outcome["applied_credit_bp"],
        "rated_premium_cents": outcome["rated_premium_cents"],
        "status": "RATED",
        "removed_at": None,
    })
    store.equipment_items[row["id"]] = row
    rating.recompute_part(part)
    rating.reroll_policy(policy)
    cascades.prorated_entry(policy, row["rated_premium_cents"],
                            "Endorsement: scheduled equipment item %s" % row["id"])
    store.bump(policy)
    return envelope_object(views.item_view(row), 201)


@bp.post(API_PREFIX + PART_FIELD + "/installation-floaters")
def open_floater(part_id):
    require("Underwriter")
    part = _part(part_id)
    b = body()
    jobsite = _body_jobsite(b, "jobsite_id")
    if jobsite is None:
        fail("ERR_INVALID_REQUEST", "jobsite_id is required")
    project_name = get_str(b, "project_name", max_len=120)
    installed_value_limit_cents = get_int(b, "installed_value_limit_cents", minimum=1)
    coverage_start_date = get_date(b, "coverage_start_date")
    coverage_end_date = get_date(b, "coverage_end_date")
    if coverage_end_date <= coverage_start_date:
        fail("ERR_INVALID_REQUEST",
             "coverage_end_date must be strictly after coverage_start_date")
    policy = _guard_part_and_policy(part)
    if (coverage_start_date < policy["effective_date"]
            or coverage_end_date > policy["expiration_date"]):
        fail("ERR_FLOATER_OUTSIDE_POLICY_TERM",
             "The closed coverage interval must sit inside the policy term")
    if part["part_type"] != "INSTALLATION_FLOATER":
        fail("ERR_PART_TYPE_MISMATCH",
             "An installation floater cannot be opened on a %s part"
             % part["part_type"])
    for other in store.order(list(store.installation_floaters.values())):
        if other["jobsite_id"] != jobsite["id"]:
            continue
        if other["status"] not in ("PENDING", "ACTIVE"):
            continue
        if (coverage_start_date <= other["coverage_end_date"]
                and other["coverage_start_date"] <= coverage_end_date):
            fail("ERR_JOBSITE_FLOATER_OVERLAP",
                 "Jobsite %s already carries a live floater over that interval"
                 % jobsite["id"])
    term_days = rating.floater_term_days(coverage_start_date, coverage_end_date)
    premium = rating.installation_floater_premium(
        installed_value_limit_cents, jobsite["security_tier"], term_days)
    row = store.make({
        "coverage_part_id": part_id,
        "jobsite_id": jobsite["id"],
        "project_name": project_name,
        "installed_value_limit_cents": installed_value_limit_cents,
        "coverage_start_date": coverage_start_date,
        "coverage_end_date": coverage_end_date,
        "term_days": term_days,
        "rated_premium_cents": premium,
        "earned_premium_cents": 0,
        "unearned_return_cents": 0,
        "termination_trigger": None,
        "termination_date": None,
        "status": "PENDING",
    })
    store.installation_floaters[row["id"]] = row
    # Creation reserves the site: active_floater_count is derived from the live
    # set, so the increment happens by construction.  The jobsite row is still
    # touched because one of its derived fields moved.
    store.touch(jobsite)
    return envelope_object(views.floater_view(row), 201)


@bp.post(API_PREFIX + PART_FIELD + "/transit-shipments")
def plan_shipment(part_id):
    require("Underwriter")
    part = _part(part_id)
    b = body()
    raw_vehicle = b.get("vehicle_id")
    vehicle = store.vehicles.get(raw_vehicle) if isinstance(raw_vehicle, str) else None
    if vehicle is None:
        fail("ERR_VEHICLE_NOT_FOUND", "Vehicle %s does not exist" % (raw_vehicle,))
    origin = get_enum(b, "origin_territory_code", rating.TERRITORIES)
    destination = get_enum(b, "destination_territory_code", rating.TERRITORIES)
    departure_at = get_instant(b, "departure_at")
    arrival_at = get_instant(b, "arrival_at")
    if arrival_at <= departure_at:
        fail("ERR_INVALID_REQUEST", "arrival_at must be strictly after departure_at")
    declared_value_cents = get_int(b, "declared_value_cents", minimum=1)
    _guard_part_and_policy(part)
    if part["part_type"] != "TRANSIT":
        fail("ERR_PART_TYPE_MISMATCH",
             "A transit shipment cannot be planned on a %s part" % part["part_type"])
    buffer_delta = datetime.timedelta(hours=rating.TRANSIT_TURNAROUND_HOURS)
    new_free_at = arrival_at + buffer_delta
    for other in store.order(list(store.transit_shipments.values())):
        if other["vehicle_id"] != vehicle["id"]:
            continue
        if other["status"] not in ("PLANNED", "IN_TRANSIT"):
            continue
        other_free_at = other["arrival_at"] + buffer_delta
        if departure_at < other_free_at and other["departure_at"] < new_free_at:
            fail("ERR_VEHICLE_WINDOW_CONFLICT",
                 "Conveyance %s is occupied over that window" % vehicle["id"])
    same_day = declared_value_cents
    for other in store.order(list(store.transit_shipments.values())):
        if other["vehicle_id"] != vehicle["id"]:
            continue
        if other["status"] not in ("PLANNED", "IN_TRANSIT"):
            continue
        if other["departure_at"].date() == departure_at.date():
            same_day += other["declared_value_cents"]
    if same_day > vehicle["per_conveyance_limit_cents"]:
        fail("ERR_VEHICLE_CAPACITY_EXCEEDED",
             "Declared value on %s exceeds the conveyance's daily capacity"
             % departure_at.date().isoformat())
    catastrophe_zone, applicable_limit = rating.transit_applicable_limit(
        part, vehicle, origin, destination)
    if applicable_limit is None:
        applicable_limit = 0
    if declared_value_cents > applicable_limit:
        fail("ERR_TRANSIT_VALUE_EXCEEDS_LIMIT",
             "declared_value_cents exceeds the applicable limit %s" % applicable_limit)
    row = store.make({
        "coverage_part_id": part_id,
        "vehicle_id": vehicle["id"],
        "origin_territory_code": origin,
        "destination_territory_code": destination,
        "departure_at": departure_at,
        "arrival_at": arrival_at,
        "declared_value_cents": declared_value_cents,
        "catastrophe_zone": catastrophe_zone,
        "applicable_limit_cents": applicable_limit,
        "status": "PLANNED",
        "departed_at": None,
        "delivered_at": None,
    })
    store.transit_shipments[row["id"]] = row
    return envelope_object(views.shipment_view(row), 201)


@bp.post(API_PREFIX + PART_FIELD + "/value-reports")
def file_value_report(part_id):
    require("Underwriter", "Policyholder")
    pending = store.maybe(store.coverage_parts, part_id)
    own_policy(pending["policy_id"] if pending else None)
    part = _part(part_id)
    b = body()
    period_start_date = get_date(b, "period_start_date")
    period_end_date = get_date(b, "period_end_date")
    if period_end_date <= period_start_date:
        fail("ERR_INVALID_REQUEST",
             "period_end_date must be strictly after period_start_date")
    reported_value_cents = get_int(b, "reported_value_cents", minimum=0)
    expected_version = get_int(b, "expected_coverage_part_version", minimum=0)
    policy = _guard_part_and_policy(part)
    if expected_version != part["version"]:
        fail("ERR_STALE_COVERAGE_PART_VERSION",
             "Coverage part version is %s, not %s" % (part["version"],
                                                      expected_version))
    if (period_start_date < policy["effective_date"]
            or period_end_date > policy["expiration_date"]):
        fail("ERR_REPORT_PERIOD_OUTSIDE_TERM",
             "The reporting period must sit inside the policy term")
    frontier = views.latest_report_period_end_date(part)
    restatement = any(r["period_start_date"] == period_start_date
                      and r["period_end_date"] == period_end_date
                      for r in store.reports_of_part(part_id))
    if not restatement and frontier is not None and period_start_date <= frontier:
        fail("ERR_REPORT_PERIOD_MISALIGNED",
             "A new period must start strictly after %s" % frontier.isoformat())
    if part["part_type"] != "REPORTING_FORM":
        fail("ERR_PART_TYPE_MISMATCH",
             "A value report cannot be filed on a %s part" % part["part_type"])
    limit = part.get("reporting_limit_cents")
    if limit is not None and reported_value_cents > limit:
        fail("ERR_REPORTED_VALUE_EXCEEDS_LIMIT",
             "reported_value_cents exceeds the reporting limit %s" % limit)
    row = store.make({
        "coverage_part_id": part_id,
        "superseded_by_report_id": None,
        "period_start_date": period_start_date,
        "period_end_date": period_end_date,
        "period_days": rating.reporting_period_days(period_start_date,
                                                    period_end_date),
        "reported_value_cents": reported_value_cents,
        "submitted_at": clock_now(),
        "due_date": rating.reporting_due_date(period_end_date),
        "period_earned_premium_cents": 0,
        "late_penalty_cents": 0,
        "status": "SUBMITTED",
    })
    store.value_reports[row["id"]] = row
    cured_candidate = False
    for prior in store.reports_of_part(part_id):
        if prior["id"] == row["id"]:
            continue
        if prior["status"] == "SUPERSEDED":
            continue
        if (prior["period_start_date"] != period_start_date
                or prior["period_end_date"] != period_end_date):
            continue
        was = prior["status"]
        prior["status"] = "SUPERSEDED"
        prior["superseded_by_report_id"] = row["id"]
        store.touch(prior)
        if was in ("ACCEPTED", "PENALIZED"):
            backed_out = prior["period_earned_premium_cents"] or 0
            if backed_out:
                store.append_entry(
                    policy["id"], "REPORTING_ADJUSTMENT", -backed_out,
                    "Backing out superseded value report %s" % prior["id"])
        if was == "DELINQUENT":
            cured_candidate = True
    if cured_candidate:
        cascades.cure_delinquency(policy)
    store.bump(part)
    return envelope_object(views.report_view(row), 201)


@bp.post(API_PREFIX + PART_FIELD + "/reporting-sweep")
def reporting_sweep(part_id):
    require("Underwriter")
    part = _part(part_id)
    policy = store.policies[part["policy_id"]]
    if policy["status"] != "IN_FORCE":
        fail("ERR_POLICY_NOT_IN_FORCE", "Policy is %s" % policy["status"])
    if part["part_type"] != "REPORTING_FORM":
        fail("ERR_PART_TYPE_MISMATCH",
             "The delinquency sweep does not apply to a %s part" % part["part_type"])
    today = clock_date()
    minted = []
    for start, end in rating.reporting_periods(policy, part["reporting_frequency"]):
        due = rating.reporting_due_date(end)
        if not due < today:
            continue
        covered = any(r["period_start_date"] == start
                      and r["period_end_date"] == end
                      and r["status"] in ("SUBMITTED", "ACCEPTED", "PENALIZED")
                      for r in store.reports_of_part(part_id))
        if covered:
            continue
        row = store.make({
            "coverage_part_id": part_id,
            "superseded_by_report_id": None,
            "period_start_date": start,
            "period_end_date": end,
            "period_days": rating.reporting_period_days(start, end),
            "reported_value_cents": 0,
            "submitted_at": clock_now(),
            "due_date": due,
            "period_earned_premium_cents": 0,
            "late_penalty_cents": 0,
            "status": "DELINQUENT",
        })
        store.value_reports[row["id"]] = row
        minted.append(row)
    if minted and policy["status"] == "IN_FORCE":
        policy["status"] = "SUSPENDED"
        store.touch(policy)
    store.bump(part)
    return envelope_object({
        "swept_period_count": len(minted),
        "delinquent_report_ids": [r["id"] for r in minted],
        "policy_status": policy["status"],
        "part_id": part_id,
    }, 200)
