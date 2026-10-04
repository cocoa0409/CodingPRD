"""Custody records, insurance policies, cost lots, quotes (§3.6)."""
from envelope import ApiError, invalid_request, invalid_state, not_found, stale
from catalog import (COVERAGE_MAX_PCT, CADENCE_DUE_DAYS, CADENCE_REQUIRED_DAYS,
                     HOLD_LAPSE_DAYS)
from store import DB, parse_dt, to_ms, add_days
from models import (make_custody_record, make_policy, make_lot, refresh_overview,
                    newest_appraisal, insert_index)
from svc_common import (body, require, as_int, enum_value, policy_in_force,
                        evaluate_lot, recompute_custody_cost_ledger,
                        recompute_lots)
from calc import day_gap, cadence_flag, bps_floor
import views


def _offering(offering_id):
    row = DB.offerings.get(offering_id)
    if row is None:
        raise not_found("Offering %s does not exist." % offering_id)
    return row


def _occ(data, offering):
    expected = as_int(data, "expected_offering_version")
    if expected is not None and int(expected) != int(offering["version"]):
        raise stale("expected_offering_version does not match the offering's version.")


def _artwork(offering):
    return DB.artworks.get(offering["artwork_id"])


def _other_in_custody(offering_id, exclude_id=None):
    for rec in DB.custody_records.values():
        if rec["offering_id"] == offering_id and rec["id"] != exclude_id \
                and rec["status"] == "IN_CUSTODY":
            return True
    return False


# ---------------------------------------------------------------------------
# CustodyRecord
# ---------------------------------------------------------------------------

def open_custody_record(offering_id):
    offering = _offering(offering_id)
    data = body()
    require(data, ["custodian_name", "facility_code", "is_freeport"])
    row = make_custody_record(offering, data)
    return views.custody_record(row), 201


def get_custody_record(record_id):
    row = DB.custody_records.get(record_id)
    if row is None:
        raise not_found("CustodyRecord %s does not exist." % record_id)
    return views.custody_record(row)


def list_custody_records(offering_id, query):
    _offering(offering_id)
    rows = [r for r in DB.ordered("custody_records") if r["offering_id"] == offering_id]
    status = query.get("status")
    if status:
        rows = [r for r in rows if r["status"] == status]
    return rows


def receive_custody(record_id):
    record = DB.custody_records.get(record_id)
    if record is None:
        raise not_found("CustodyRecord %s does not exist." % record_id)
    data = body()
    offering = _offering(record["offering_id"])
    artwork = _artwork(offering)
    state = record["status"]

    if state == "PENDING":
        if offering["status"] not in ("ALLOCATED", "HELD"):
            raise invalid_state("The offering is not ALLOCATED or HELD.")
    elif state == "RELEASED":
        if offering["status"] != "ALLOCATED":
            raise invalid_state("Re-receipt requires an ALLOCATED offering.")
        _occ(data, offering)
        ended = record.get("custody_ended_at")
        selected = newest_appraisal(artwork["id"])
        if selected is None or ended is None or selected["filed_at"] <= ended:
            raise ApiError("ERR_APPRAISAL_STALE",
                           "No selected appraisal was filed after the record's "
                           "custody_ended_at.")
    else:
        raise invalid_state("The custody record is already IN_CUSTODY.")

    if _other_in_custody(offering["id"], record["id"]):
        raise ApiError("ERR_CUSTODY_INTERVAL_OVERLAP",
                       "Another custody record of this offering is already IN_CUSTODY.")

    now = to_ms(DB.now())
    record["status"] = "IN_CUSTODY"
    record["custody_started_at"] = now
    record["custody_ended_at"] = None
    record["updated_at"] = now
    record["version"] = int(record.get("version") or 1) + 1
    if offering.get("holding_clock_started_at") is None or state == "RELEASED":
        offering["holding_clock_started_at"] = now
        offering["holding_period_end_at"] = add_days(now, int(offering["hold_period_days"]))
    offering["status"] = "HELD"
    offering["updated_at"] = now
    offering["version"] = int(offering["version"]) + 1
    artwork["status"] = "HELD"
    refresh_overview(artwork, bump=True)
    recompute_lots(offering)
    return views.custody_record(record)


def release_custody(record_id):
    record = DB.custody_records.get(record_id)
    if record is None:
        raise not_found("CustodyRecord %s does not exist." % record_id)
    data = body()
    offering = _offering(record["offering_id"])
    if record["status"] != "IN_CUSTODY":
        raise invalid_state("Only a record IN_CUSTODY may be released.")
    if offering["status"] != "HELD":
        raise invalid_state("Release requires the offering to be HELD.")
    _occ(data, offering)
    now = to_ms(DB.now())
    record["status"] = "RELEASED"
    record["custody_ended_at"] = now
    record["updated_at"] = now
    record["version"] = int(record.get("version") or 1) + 1
    offering["holding_clock_started_at"] = None
    offering["holding_period_end_at"] = None
    offering["status"] = "ALLOCATED"
    offering["updated_at"] = now
    offering["version"] = int(offering["version"]) + 1
    artwork = _artwork(offering)
    refresh_overview(artwork, bump=True)
    recompute_lots(offering)
    return views.custody_record(record)


# ---------------------------------------------------------------------------
# InsurancePolicy
# ---------------------------------------------------------------------------

def create_policy(offering_id):
    offering = _offering(offering_id)
    data = body()
    require(data, ["carrier_name", "coverage_cents", "annual_premium_cents"])
    as_int(data, "coverage_cents", minimum=0)
    row = make_policy(offering, data)
    return views.policy(row), 201


def get_policy(policy_id):
    row = DB.insurance_policies.get(policy_id)
    if row is None:
        raise not_found("InsurancePolicy %s does not exist." % policy_id)
    return views.policy(row)


def list_policies(offering_id, query):
    _offering(offering_id)
    rows = [r for r in DB.ordered("insurance_policies") if r["offering_id"] == offering_id]
    status = query.get("status")
    if status:
        rows = [r for r in rows if r["status"] == status]
    return rows


def bind_policy(policy_id):
    policy = DB.insurance_policies.get(policy_id)
    if policy is None:
        raise not_found("InsurancePolicy %s does not exist." % policy_id)
    offering = _offering(policy["offering_id"])
    if policy["status"] != "PENDING":
        raise invalid_state("Only a PENDING policy may be bound.")
    artwork = _artwork(offering)
    value = int(artwork.get("last_appraised_value_cents") or 0)
    if value <= 0:
        raise ApiError("ERR_APPRAISAL_MISSING",
                       "The artwork carries no selected appraised value.")
    coverage = int(policy["coverage_cents"])
    if coverage < value:
        raise ApiError("ERR_INSUFFICIENT_COVERAGE",
                       "coverage_cents is below the artwork's appraised value.")
    if coverage > (value * COVERAGE_MAX_PCT) // 100:
        raise ApiError("ERR_COVERAGE_EXCEEDS_VALUE",
                       "coverage_cents exceeds 120 percent of the appraised value.")
    if policy_in_force(offering["id"]):
        raise ApiError("ERR_POLICY_INTERVAL_OVERLAP",
                       "Another policy of this offering is already in force.")
    now = to_ms(DB.now())
    policy["status"] = "FORCE"
    policy["updated_at"] = now
    policy["version"] = int(policy.get("version") or 1) + 1
    offering["updated_at"] = now
    offering["version"] = int(offering["version"]) + 1
    recompute_lots(offering)
    return views.policy(policy)


def lapse_policy(policy_id):
    policy = DB.insurance_policies.get(policy_id)
    if policy is None:
        raise not_found("InsurancePolicy %s does not exist." % policy_id)
    offering = _offering(policy["offering_id"])
    if policy["status"] != "FORCE":
        raise invalid_state("Only a policy in FORCE may be lapsed.")
    replacement = any(p["id"] != policy["id"] and p["offering_id"] == offering["id"]
                      and p["status"] in ("FORCE", "PENDING")
                      for p in DB.insurance_policies.values())
    if not replacement:
        raise ApiError("ERR_SOLE_POLICY_CANNOT_LAPSE",
                       "The policy is the sole policy of the offering.")
    now = to_ms(DB.now())
    policy["status"] = "LAPSED"
    policy["updated_at"] = now
    policy["version"] = int(policy.get("version") or 1) + 1
    for lot in DB.lots.values():
        if lot["offering_id"] == offering["id"]:
            lot["pass_through_allowed"] = False
            lot["pass_through_amount_cents"] = 0
            lot["updated_at"] = now
            lot["version"] = int(lot.get("version") or 1) + 1
    offering["custody_cost_ledger_cents"] = 0
    offering["updated_at"] = now
    offering["version"] = int(offering["version"]) + 1
    recompute_custody_cost_ledger(offering)
    return views.policy(policy)


# ---------------------------------------------------------------------------
# Lot
# ---------------------------------------------------------------------------

def create_lot(offering_id):
    offering = _offering(offering_id)
    data = body()
    require(data, ["lot_type", "cost_amount_cents", "incurred_on"])
    as_int(data, "cost_amount_cents", minimum=0)
    lot_type = data.get("lot_type")
    if lot_type not in ("STORAGE", "INSURANCE", "CONSERVATION"):
        raise ApiError("ERR_VALUE_REJECTED",
                       "lot_type carries an undeclared value.")
    from svc_common import body_datetime
    body_datetime(data, "incurred_on")
    artwork = _artwork(offering)
    row = make_lot(offering, data)
    evaluate_lot(offering, artwork, row)
    offering["custody_cost_ledger_cents"] = (
        int(offering.get("custody_cost_ledger_cents") or 0)
        + int(row["pass_through_amount_cents"]))
    offering["updated_at"] = row["created_at"]
    offering["version"] = int(offering["version"]) + 1
    return views.lot(row), 201


def list_lots(offering_id, query):
    _offering(offering_id)
    rows = [r for r in DB.ordered("lots") if r["offering_id"] == offering_id]
    lot_type = query.get("lot_type")
    if lot_type:
        rows = [r for r in rows if r["lot_type"] == lot_type]
    flag = query.get("pass_through_allowed")
    if flag is not None and flag != "":
        want = str(flag).lower() in ("true", "1", "yes")
        rows = [r for r in rows if bool(r.get("pass_through_allowed")) == want]
    return rows


def insurer_quote(offering_id):
    offering = _offering(offering_id)
    data = body()
    require(data, ["carrier_name", "quoted_annual_premium_cents"])
    as_int(data, "quoted_annual_premium_cents", minimum=0)
    quote_id = DB.new_id()
    DB.quotes[quote_id] = {
        "offering_id": offering["id"],
        "carrier_name": data.get("carrier_name"),
        "quoted_annual_premium_cents": int(data.get("quoted_annual_premium_cents")),
        "created_at": to_ms(DB.now()),
    }
    return {"quote_reference": quote_id}, 201