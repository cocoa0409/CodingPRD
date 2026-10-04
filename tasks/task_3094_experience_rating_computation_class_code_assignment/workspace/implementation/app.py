"""Experience Rating API (NCCI-style) — reference implementation.

In-memory only. No seeding. Logical clock starts at 2026-09-01T00:00:00Z.
Implements PRD.md §1-§5 for task_3094.
"""

import os
import re
import uuid
from datetime import datetime, timedelta, timezone, date
from decimal import Decimal, ROUND_HALF_UP

from flask import Flask, request, jsonify

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

DEFAULT_CLOCK_ISO = "2026-09-01T00:00:00Z"

ROLES = {
    "BureauAdmin",
    "CarrierDataReporter",
    "BureauAnalyst",
    "Inspector",
    "EmployerRepresentative",
    "PoolAdministrator",
    "VoluntaryCarrierRepresentative",
    "Underwriter",
}

# ---------------------------------------------------------------------------
# In-memory store
# ---------------------------------------------------------------------------

db = {
    "bureaus": {},
    "carriers": {},
    "employers": {},
    "class_codes": {},
    "rating_tables": {},
    "policies": {},
    "unit_stat_reports": {},
    "class_assignments": {},
    "inspections": {},
    "class_assignment_disputes": {},
    "experience_mod_sheets": {},
    "mod_appeals": {},
    "ownership_changes": {},
    "combinability_groups": {},
    "assigned_risk_enrollments": {},
    "assigned_risk_take_outs": {},
    "underwriting_reviews": {},
}


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


class ApiError(Exception):
    def __init__(self, error_id, http_status, message):
        super().__init__(message)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message


# ---------------------------------------------------------------------------
# Time helpers
# ---------------------------------------------------------------------------


def parse_iso(value):
    """Parse an ISO 8601 datetime string to an aware UTC datetime."""
    if not isinstance(value, str):
        raise ValueError("not a string")
    s = value.strip()
    if s.endswith(("Z", "z")):
        s = s[:-1] + "+00:00"
    dt = datetime.fromisoformat(s)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def parse_date(value):
    """Parse YYYY-MM-DD to a date object."""
    if not isinstance(value, str):
        raise ValueError("not a string")
    s = value.strip()
    return datetime.strptime(s, "%Y-%m-%d").date()


def parse_clock_value(value):
    m = re.match(r"^(.*?)(?:([+-])(\d+)d)?$", value.strip())
    base = parse_iso(m.group(1))
    if m.group(2) is not None:
        days = int(m.group(3))
        if m.group(2) == "-":
            days = -days
        base = base + timedelta(days=days)
    return base


def logical_clock():
    raw = db.get("_clock", DEFAULT_CLOCK_ISO)
    return parse_clock_value(raw)


def wall_now_iso():
    dt = datetime.now(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def iso_z(dt):
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def new_id():
    return str(uuid.uuid4())


def touch(record):
    record["updated_at"] = wall_now_iso()
    record["version"] = record.get("version", 1) + 1


def new_record(with_version=True):
    now = wall_now_iso()
    rec = {"id": new_id(), "created_at": now}
    if with_version:
        rec["updated_at"] = now
        rec["version"] = 1
    return rec


# ---------------------------------------------------------------------------
# Response envelope
# ---------------------------------------------------------------------------


def meta_base():
    return {
        "api_request_id": "req_" + uuid.uuid4().hex,
        "api_request_timestamp": wall_now_iso(),
    }


def ok_object(data, code=200):
    body = {"meta": meta_base(), "response_type": "object", "data": data}
    return jsonify(body), code


def ok_array(items, code=200, paginate=True):
    meta = meta_base()
    data = items
    if paginate:
        limit_raw = request.args.get("limit", "10")
        offset_raw = request.args.get("offset", "0")
        try:
            limit = int(limit_raw)
            offset = int(offset_raw)
        except (TypeError, ValueError):
            raise ApiError("ERR_INVALID_REQUEST", 400, "invalid pagination parameters")
        if limit < 1 or limit > 100 or offset < 0:
            raise ApiError("ERR_INVALID_REQUEST", 400, "pagination parameters out of range")
        total = len(items)
        data = items[offset : offset + limit]
        meta["limit"] = limit
        meta["offset"] = offset
        meta["total_count"] = total
        meta["has_more"] = offset + limit < total
    body = {"meta": meta, "response_type": "array", "data": data}
    return jsonify(body), code


app = Flask(__name__)


@app.errorhandler(ApiError)
def handle_api_error(err):
    body = {
        "meta": meta_base(),
        "response_type": "error",
        "data": {"error_id": err.error_id, "message": err.message},
    }
    return jsonify(body), err.http_status


@app.errorhandler(404)
def handle_404(_e):
    return handle_api_error(ApiError("ERR_NOT_FOUND", 404, "resource not found"))


@app.errorhandler(405)
def handle_405(_e):
    return handle_api_error(ApiError("ERR_NOT_FOUND", 404, "resource not found"))


@app.errorhandler(Exception)
def handle_unexpected(err):
    if isinstance(err, ApiError):
        return handle_api_error(err)
    return handle_api_error(ApiError("ERR_INVALID_REQUEST", 400, str(err)))


# ---------------------------------------------------------------------------
# Auth / RBAC
# ---------------------------------------------------------------------------


def caller():
    role = request.headers.get("X-User-Role")
    uid = request.headers.get("X-User-ID")
    if role not in ROLES or not uid:
        raise ApiError(
            "ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER",
            400,
            "missing or unknown credentials",
        )
    return {"role": role, "id": uid}


def require_roles(*roles):
    c = caller()
    if c["role"] not in roles:
        raise ApiError(
            "ERR_FORBIDDEN_FOR_ROLE", 403, "role not permitted for this endpoint"
        )
    return c


# ---------------------------------------------------------------------------
# Input validation helpers
# ---------------------------------------------------------------------------


def body():
    return request.get_json(silent=True) or {}


def req_str(data, field, nullable=False):
    v = data.get(field)
    if v is None:
        if nullable:
            return None
        raise ApiError("ERR_INVALID_REQUEST", 400, f"missing required field: {field}")
    if not isinstance(v, str):
        raise ApiError("ERR_INVALID_REQUEST", 400, f"field {field} must be a string")
    return v


def req_int(data, field, nullable=False):
    v = data.get(field)
    if v is None:
        if nullable:
            return None
        raise ApiError("ERR_INVALID_REQUEST", 400, f"missing required field: {field}")
    if isinstance(v, bool) or not isinstance(v, int):
        raise ApiError("ERR_INVALID_REQUEST", 400, f"field {field} must be an integer")
    return v


def req_enum(data, field, allowed, nullable=False):
    v = data.get(field)
    if v is None:
        if nullable:
            return None
        raise ApiError("ERR_INVALID_REQUEST", 400, f"missing required field: {field}")
    if v not in allowed:
        raise ApiError("ERR_INVALID_REQUEST", 400, f"field {field} out of enum")
    return v


def req_date(data, field, nullable=False):
    v = data.get(field)
    if v is None:
        if nullable:
            return None
        raise ApiError("ERR_INVALID_REQUEST", 400, f"missing required field: {field}")
    try:
        parse_date(v)
    except (ValueError, TypeError):
        raise ApiError("ERR_INVALID_REQUEST", 400, f"field {field} must be YYYY-MM-DD")
    return v


def req_array(data, field, nullable=False):
    v = data.get(field)
    if v is None:
        if nullable:
            return None
        raise ApiError("ERR_INVALID_REQUEST", 400, f"missing required field: {field}")
    if not isinstance(v, list):
        raise ApiError("ERR_INVALID_REQUEST", 400, f"field {field} must be an array")
    return v


def get_or_404(collection, rid):
    rec = db[collection].get(rid)
    if rec is None:
        raise ApiError("ERR_NOT_FOUND", 404, f"resource not found: {rid}")
    return rec


def sort_by_created(items):
    return sorted(items, key=lambda r: (r.get("created_at", ""), r["id"]))


def first_bureau():
    """Return the first bureau (tests usually create exactly one)."""
    bureaus = list(db["bureaus"].values())
    return bureaus[0] if bureaus else None


def get_bureau_or_404():
    b = first_bureau()
    if b is None:
        raise ApiError("ERR_NOT_FOUND", 404, "no bureau registered")
    return b


# ---------------------------------------------------------------------------
# Money / decimal helpers
# ---------------------------------------------------------------------------


def dec(v):
    return Decimal(str(v))


def round_half_up_int(v):
    """Round a Decimal to integer cents, half-up."""
    return int(v.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def round_half_up_dec(v, places):
    """Round a Decimal to N decimal places, half-up."""
    q = Decimal(1).scaleb(-places)
    return v.quantize(q, rounding=ROUND_HALF_UP)


# ---------------------------------------------------------------------------
# Serializers
# ---------------------------------------------------------------------------


def ser_bureau(r):
    return {
        "id": r["id"],
        "code": r["code"],
        "name": r["name"],
        "eligibility_threshold_cents": r["eligibility_threshold_cents"],
        "split_point_cents": r["split_point_cents"],
        "credibility_ballast_bp": r["credibility_ballast_bp"],
        "credibility_excess_divisor_bp": r["credibility_excess_divisor_bp"],
        "underwriting_threshold_cents": r["underwriting_threshold_cents"],
        "created_at": r["created_at"],
        "updated_at": r["updated_at"],
        "version": r["version"],
    }


def ser_carrier(r):
    return {
        "id": r["id"],
        "naic_number": r["naic_number"],
        "legal_name": r["legal_name"],
        "assigned_risk_quota_cents": r["assigned_risk_quota_cents"],
        "assigned_risk_current_load_cents": r["assigned_risk_current_load_cents"],
        "status": r["status"],
        "created_at": r["created_at"],
        "updated_at": r["updated_at"],
        "version": r["version"],
    }


def ser_employer(r):
    return {
        "id": r["id"],
        "fein": r["fein"],
        "legal_name": r["legal_name"],
        "state_code": r["state_code"],
        "status": r["status"],
        "created_at": r["created_at"],
        "updated_at": r["updated_at"],
        "version": r["version"],
    }


def ser_class_code(r):
    return {
        "id": r["id"],
        "code": r["code"],
        "description": r["description"],
        "state_code": r["state_code"],
        "status": r["status"],
        "created_at": r["created_at"],
    }


def ser_rating_table(r):
    return {
        "id": r["id"],
        "state_code": r["state_code"],
        "effective_date": r["effective_date"],
        "status": r["status"],
        "values": r["values"],
        "superseded_at": r["superseded_at"],
        "created_at": r["created_at"],
        "updated_at": r["updated_at"],
        "version": r["version"],
    }


def ser_policy(r):
    return {
        "id": r["id"],
        "employer_id": r["employer_id"],
        "carrier_id": r["carrier_id"],
        "policy_number": r["policy_number"],
        "effective_date": r["effective_date"],
        "expiration_date": r["expiration_date"],
        "manual_premium_cents": r["manual_premium_cents"],
        "status": r["status"],
        "class_codes": r["class_codes"],
        "unit_stat_report_id": r["unit_stat_report_id"],
        "created_at": r["created_at"],
        "updated_at": r["updated_at"],
        "version": r["version"],
    }


def ser_unit_stat_report(r):
    return {
        "id": r["id"],
        "policy_id": r["policy_id"],
        "payroll_lines": r["payroll_lines"],
        "claim_lines": r["claim_lines"],
        "status": r["status"],
        "submission_number": r["submission_number"],
        "correction_of_report_id": r["correction_of_report_id"],
        "created_at": r["created_at"],
        "updated_at": r["updated_at"],
        "version": r["version"],
    }


def ser_class_assignment(r):
    return {
        "id": r["id"],
        "employer_id": r["employer_id"],
        "class_code_id": r["class_code_id"],
        "effective_date": r["effective_date"],
        "status": r["status"],
        "inspection_id": r["inspection_id"],
        "dispute_id": r["dispute_id"],
        "created_at": r["created_at"],
        "updated_at": r["updated_at"],
        "version": r["version"],
    }


def ser_inspection(r):
    return {
        "id": r["id"],
        "class_assignment_id": r["class_assignment_id"],
        "inspector_id": r["inspector_id"],
        "scheduled_date": r["scheduled_date"],
        "status": r["status"],
        "findings": r["findings"],
        "created_at": r["created_at"],
        "updated_at": r["updated_at"],
        "version": r["version"],
    }


def ser_class_assignment_dispute(r):
    return {
        "id": r["id"],
        "class_assignment_id": r["class_assignment_id"],
        "employer_id": r["employer_id"],
        "reason": r["reason"],
        "status": r["status"],
        "resolution": r["resolution"],
        "resolved_at": r["resolved_at"],
        "created_at": r["created_at"],
        "updated_at": r["updated_at"],
        "version": r["version"],
    }


def ser_experience_mod_sheet(r):
    return {
        "id": r["id"],
        "employer_id": r["employer_id"],
        "rating_effective_date": r["rating_effective_date"],
        "status": r["status"],
        "mod_factor": r["mod_factor"],
        "expected_losses_cents": r["expected_losses_cents"],
        "actual_primary_cents": r["actual_primary_cents"],
        "actual_excess_cents": r["actual_excess_cents"],
        "ballast_cents": r["ballast_cents"],
        "weight_w": r["weight_w"],
        "expected_primary_cents": r["expected_primary_cents"],
        "expected_excess_cents": r["expected_excess_cents"],
        "provisional_mod_factor": r["provisional_mod_factor"],
        "retroactive_premium_adjustment_cents": r["retroactive_premium_adjustment_cents"],
        "revision_of_sheet_id": r["revision_of_sheet_id"],
        "revision_reason": r["revision_reason"],
        "created_at": r["created_at"],
        "updated_at": r["updated_at"],
        "version": r["version"],
    }


def ser_mod_appeal(r):
    return {
        "id": r["id"],
        "mod_sheet_id": r["mod_sheet_id"],
        "employer_id": r["employer_id"],
        "reason": r["reason"],
        "status": r["status"],
        "filed_at": r["filed_at"],
        "decided_at": r["decided_at"],
        "decision": r["decision"],
        "decision_reason": r["decision_reason"],
        "created_at": r["created_at"],
        "updated_at": r["updated_at"],
        "version": r["version"],
    }


def ser_ownership_change(r):
    return {
        "id": r["id"],
        "employer_id": r["employer_id"],
        "change_type": r["change_type"],
        "effective_date": r["effective_date"],
        "status": r["status"],
        "combinability_group_id": r["combinability_group_id"],
        "created_at": r["created_at"],
        "updated_at": r["updated_at"],
        "version": r["version"],
    }


def ser_combinability_group(r):
    return {
        "id": r["id"],
        "member_employer_ids": r["member_employer_ids"],
        "status": r["status"],
        "created_from_change_id": r["created_from_change_id"],
        "combined_mod_sheet_id": r["combined_mod_sheet_id"],
        "created_at": r["created_at"],
        "updated_at": r["updated_at"],
        "version": r["version"],
    }


def ser_assigned_risk_enrollment(r):
    return {
        "id": r["id"],
        "employer_id": r["employer_id"],
        "state_code": r["state_code"],
        "effective_date": r["effective_date"],
        "expiration_date": r["expiration_date"],
        "estimated_annual_premium_cents": r["estimated_annual_premium_cents"],
        "status": r["status"],
        "assigned_carrier_id": r["assigned_carrier_id"],
        "take_out_credit_cents": r["take_out_credit_cents"],
        "exit_date": r["exit_date"],
        "exit_reason": r["exit_reason"],
        "created_at": r["created_at"],
        "updated_at": r["updated_at"],
        "version": r["version"],
    }


def ser_assigned_risk_take_out(r):
    return {
        "id": r["id"],
        "enrollment_id": r["enrollment_id"],
        "voluntary_carrier_id": r["voluntary_carrier_id"],
        "exit_date": r["exit_date"],
        "status": r["status"],
        "credit_cents": r["credit_cents"],
        "approved_at": r["approved_at"],
        "created_at": r["created_at"],
        "updated_at": r["updated_at"],
        "version": r["version"],
    }


def ser_underwriting_review(r):
    return {
        "id": r["id"],
        "subject_type": r["subject_type"],
        "subject_id": r["subject_id"],
        "status": r["status"],
        "reviewer_id": r["reviewer_id"],
        "decided_at": r["decided_at"],
        "created_at": r["created_at"],
        "updated_at": r["updated_at"],
        "version": r["version"],
    }


# ---------------------------------------------------------------------------
# Lookup helpers
# ---------------------------------------------------------------------------


def promulgated_table_for(state_code, on_date_str):
    """Return the rating table for state_code in force at on_date_str.

    In-force: latest effective_date <= on_date_str among PROMULGATED tables and
    SUPERSEDED tables (a superseded table still governs dates before its
    successor's effective date — lookups resolve against the table in force at
    the relevant date).
    """
    target = parse_date(on_date_str)
    candidates = []
    for rt in db["rating_tables"].values():
        if rt["state_code"] != state_code or rt["status"] not in (
            "PROMULGATED",
            "SUPERSEDED",
        ):
            continue
        try:
            eff = parse_date(rt["effective_date"])
        except (ValueError, TypeError):
            continue
        if eff <= target:
            candidates.append((eff, rt))
    if not candidates:
        return None
    # Latest effective_date wins; among equal dates the most recently
    # promulgated (in force) table wins over one it superseded.
    candidates.sort(
        key=lambda x: (x[0], x[1].get("status") != "PROMULGATED", x[1]["created_at"])
    )
    return candidates[-1][1]


def table_value_for(rating_table, class_code):
    """Look up a class_code's rate row from a RatingTable's values array."""
    if not rating_table:
        return None
    for v in rating_table["values"]:
        if v.get("class_code") == class_code:
            return v
    return None


def employer_reports(employer_id, statuses=None):
    """All UnitStatReports for policies owned by employer_id, optional status filter."""
    out = []
    policy_ids = {
        p["id"] for p in db["policies"].values() if p["employer_id"] == employer_id
    }
    for r in db["unit_stat_reports"].values():
        if r["policy_id"] not in policy_ids:
            continue
        if statuses and r["status"] not in statuses:
            continue
        out.append(r)
    return out


def employer_policies(employer_id):
    return [p for p in db["policies"].values() if p["employer_id"] == employer_id]


def latest_policy_for_employer(employer_id):
    """Most recently created policy for the employer (used for retro adjustment)."""
    ps = employer_policies(employer_id)
    if not ps:
        return None
    ps.sort(key=lambda p: (p["created_at"], p["id"]))
    return ps[-1]


# ---------------------------------------------------------------------------
# Mod sheet computation
# ---------------------------------------------------------------------------


def compute_mod_inputs(employer_id, rating_effective_date, statuses):
    """Aggregate payroll and claim lines across employer's reports with given statuses."""
    bureau = get_bureau_or_404()
    payroll_lines = []
    claim_lines = []
    policy_states = {}
    for r in employer_reports(employer_id, statuses=statuses):
        for pl in r["payroll_lines"]:
            payroll_lines.append((r["policy_id"], pl))
        for cl in r["claim_lines"]:
            claim_lines.append(cl)
        p = db["policies"].get(r["policy_id"])
        if p:
            policy_states[r["policy_id"]] = p
    return bureau, payroll_lines, claim_lines, policy_states


def compute_mod_factors(employer_id, rating_effective_date, statuses):
    """Compute the full mod-factor decomposition. Returns a dict of fields.

    Raises ApiError(ERR_CLASS_CODE_NOT_RATED) when a class code is missing.
    """
    bureau, payroll_lines, claim_lines, policy_states = compute_mod_inputs(
        employer_id, rating_effective_date, statuses
    )

    # Expected losses: sum over payroll lines
    expected_losses_cents = 0
    # d_ratio: take from the rating table (we use the first matching value encountered)
    d_ratio_bp = None
    for policy_id, pl in payroll_lines:
        policy = policy_states.get(policy_id)
        if policy is None:
            continue
        state_code = db["employers"][employer_id]["state_code"]
        rt = promulgated_table_for(state_code, rating_effective_date)
        row = table_value_for(rt, pl.get("class_code"))
        if row is None:
            raise ApiError(
                "ERR_CLASS_CODE_NOT_RATED",
                409,
                f"class code {pl.get('class_code')} not rated in promulgated table",
            )
        elr = row.get("elr_per_100_payroll_cents")
        payroll_dollars = pl.get("payroll_dollars", 0)
        line_cents = round_half_up_int(dec(payroll_dollars) * dec(elr) / dec(100))
        expected_losses_cents += line_cents
        if d_ratio_bp is None:
            d_ratio_bp = row.get("d_ratio_bp")

    # Primary / excess split
    split_point = bureau["split_point_cents"]
    actual_primary_cents = 0
    actual_excess_cents = 0
    for cl in claim_lines:
        incurred = cl.get("incurred_cents", 0)
        primary = min(incurred, split_point)
        actual_primary_cents += primary
        actual_excess_cents += incurred - primary

    # Credibility
    K = dec(bureau["credibility_ballast_bp"]) / dec(10000)
    J = dec(bureau["credibility_excess_divisor_bp"]) / dec(10000)
    E = dec(expected_losses_cents)
    B = round_half_up_int(K * E)
    denom_w = E + J * dec(100000000)
    if denom_w == 0:
        W = Decimal("0")
    else:
        W = round_half_up_dec(E / denom_w, 4)
    if d_ratio_bp is None:
        expected_primary_cents = 0
    else:
        expected_primary_cents = round_half_up_int(
            E * dec(d_ratio_bp) / dec(10000)
        )
    expected_excess_cents = expected_losses_cents - expected_primary_cents
    term_Ae = round_half_up_int(W * dec(actual_excess_cents))
    term_Ee = round_half_up_int((Decimal(1) - W) * dec(expected_excess_cents))
    numerator = dec(actual_primary_cents) + dec(term_Ae) + dec(term_Ee) + dec(B)
    denominator = E + dec(B)
    if denominator == 0:
        mod_factor = Decimal("1.00")
    else:
        mod_factor = round_half_up_dec(numerator / denominator, 2)

    return {
        "expected_losses_cents": expected_losses_cents,
        "actual_primary_cents": actual_primary_cents,
        "actual_excess_cents": actual_excess_cents,
        "ballast_cents": B,
        "weight_w": str(W),
        "expected_primary_cents": expected_primary_cents,
        "expected_excess_cents": expected_excess_cents,
        "mod_factor": str(mod_factor),
    }


def compute_sheet_fields(employer_id, rating_effective_date):
    """Compute final (VALIDATED+LOCKED) and provisional (incl. SUBMITTED) factors."""
    final = compute_mod_factors(
        employer_id, rating_effective_date, {"VALIDATED", "LOCKED"}
    )
    prov = compute_mod_factors(
        employer_id, rating_effective_date, {"VALIDATED", "LOCKED", "SUBMITTED"}
    )
    return final, prov


# ---------------------------------------------------------------------------
# Retroactive premium adjustment
# ---------------------------------------------------------------------------


def recompute_manual_premium_for_policy(policy, on_date_str):
    """Recompute manual_premium_cents for a policy using the in-force table at on_date_str."""
    employer = db["employers"].get(policy["employer_id"])
    if employer is None:
        return policy.get("manual_premium_cents", 0)
    state_code = employer["state_code"]
    rt = promulgated_table_for(state_code, on_date_str)
    if rt is None:
        return policy.get("manual_premium_cents", 0)
    total = 0
    for line in policy["class_codes"]:
        row = table_value_for(rt, line.get("class_code"))
        if row is None:
            raise ApiError(
                "ERR_CLASS_CODE_NOT_RATED",
                409,
                f"class code {line.get('class_code')} not rated",
            )
        rate = row.get("rate_per_100_payroll_cents")
        payroll_dollars = line.get("payroll_dollars", 0)
        total += round_half_up_int(dec(payroll_dollars) * dec(rate) / dec(100))
    return total


def retroactive_premium_adjustment(prior_sheet, new_sheet, employer_id):
    policy = latest_policy_for_employer(employer_id)
    if policy is None:
        return 0
    manual = recompute_manual_premium_for_policy(policy, prior_sheet["rating_effective_date"])
    old_factor = dec(prior_sheet["mod_factor"])
    new_factor = dec(new_sheet["mod_factor"])
    billed_old = round_half_up_int(dec(manual) * old_factor)
    billed_new = round_half_up_int(dec(manual) * new_factor)
    return billed_new - billed_old


# ---------------------------------------------------------------------------
# Cascading: revision of sheets
# ---------------------------------------------------------------------------


def spawn_revision_sheet(prior_sheet, reason):
    """Create a DRAFT revision sheet that supersedes prior_sheet."""
    employer_id = prior_sheet["employer_id"]
    rating_eff = prior_sheet["rating_effective_date"]
    final, prov = compute_sheet_fields(employer_id, rating_eff)
    rec = new_record()
    rec.update(
        {
            "employer_id": employer_id,
            "rating_effective_date": rating_eff,
            "status": "DRAFT",
            "mod_factor": final["mod_factor"],
            "expected_losses_cents": final["expected_losses_cents"],
            "actual_primary_cents": final["actual_primary_cents"],
            "actual_excess_cents": final["actual_excess_cents"],
            "ballast_cents": final["ballast_cents"],
            "weight_w": final["weight_w"],
            "expected_primary_cents": final["expected_primary_cents"],
            "expected_excess_cents": final["expected_excess_cents"],
            "provisional_mod_factor": prov["mod_factor"],
            "retroactive_premium_adjustment_cents": 0,
            "revision_of_sheet_id": prior_sheet["id"],
            "revision_reason": reason,
        }
    )
    # retro adjustment against prior
    rec["retroactive_premium_adjustment_cents"] = retroactive_premium_adjustment(
        prior_sheet, rec, employer_id
    )
    db["experience_mod_sheets"][rec["id"]] = rec
    return rec


def cascade_revise_sheet(sheet, reason):
    """Move sheet PROMULGATED -> REVISED and spawn a new DRAFT revision."""
    if sheet["status"] != "PROMULGATED":
        return None
    sheet["status"] = "REVISED"
    touch(sheet)
    new_sheet = spawn_revision_sheet(sheet, reason)
    return new_sheet


def sheets_consuming_report(report_id):
    """Find PROMULGATED sheets that consumed a given report.

    Heuristic: any PROMULGATED sheet for the same employer whose rating period
    includes this report's policy.
    """
    report = db["unit_stat_reports"].get(report_id)
    if report is None:
        return []
    policy = db["policies"].get(report["policy_id"])
    if policy is None:
        return []
    employer_id = policy["employer_id"]
    out = []
    for s in db["experience_mod_sheets"].values():
        if s["employer_id"] == employer_id and s["status"] == "PROMULGATED":
            out.append(s)
    return out


# ---------------------------------------------------------------------------
# Clock
# ---------------------------------------------------------------------------


@app.route("/_clock/set_current_utc", methods=["POST"])
def set_clock():
    require_roles("BureauAdmin")
    data = body()
    current_utc = req_str(data, "current_utc")
    # Validate it parses
    parse_clock_value(current_utc)
    db["_clock"] = current_utc
    return ok_object({}, code=200)


# ---------------------------------------------------------------------------
# Bureaus
# ---------------------------------------------------------------------------


@app.route("/bureaus", methods=["POST"])
def create_bureau():
    require_roles("BureauAdmin")
    data = body()
    code = req_str(data, "code")
    name = req_str(data, "name")
    eligibility_threshold_cents = req_int(data, "eligibility_threshold_cents")
    split_point_cents = req_int(data, "split_point_cents")
    credibility_ballast_bp = req_int(data, "credibility_ballast_bp")
    credibility_excess_divisor_bp = req_int(data, "credibility_excess_divisor_bp")
    underwriting_threshold_cents = req_int(data, "underwriting_threshold_cents")
    rec = new_record()
    rec.update(
        {
            "code": code,
            "name": name,
            "eligibility_threshold_cents": eligibility_threshold_cents,
            "split_point_cents": split_point_cents,
            "credibility_ballast_bp": credibility_ballast_bp,
            "credibility_excess_divisor_bp": credibility_excess_divisor_bp,
            "underwriting_threshold_cents": underwriting_threshold_cents,
        }
    )
    db["bureaus"][rec["id"]] = rec
    return ok_object(ser_bureau(rec), code=201)


@app.route("/bureaus/<bureauId>", methods=["GET"])
def get_bureau(bureauId):
    require_roles(*ROLES)
    rec = get_or_404("bureaus", bureauId)
    return ok_object(ser_bureau(rec))


# ---------------------------------------------------------------------------
# Carriers
# ---------------------------------------------------------------------------


@app.route("/carriers", methods=["POST"])
def create_carrier():
    require_roles("BureauAdmin")
    data = body()
    naic_number = req_str(data, "naic_number")
    legal_name = req_str(data, "legal_name")
    assigned_risk_quota_cents = req_int(data, "assigned_risk_quota_cents")
    rec = new_record()
    rec.update(
        {
            "naic_number": naic_number,
            "legal_name": legal_name,
            "assigned_risk_quota_cents": assigned_risk_quota_cents,
            "assigned_risk_current_load_cents": 0,
            "status": "ACTIVE",
        }
    )
    db["carriers"][rec["id"]] = rec
    return ok_object(ser_carrier(rec), code=201)


@app.route("/carriers/<carrierId>", methods=["GET"])
def get_carrier(carrierId):
    require_roles(*ROLES)
    rec = get_or_404("carriers", carrierId)
    return ok_object(ser_carrier(rec))


# ---------------------------------------------------------------------------
# Employers
# ---------------------------------------------------------------------------


@app.route("/employers", methods=["POST"])
def create_employer():
    require_roles("BureauAdmin")
    data = body()
    fein = req_str(data, "fein")
    legal_name = req_str(data, "legal_name")
    state_code = req_str(data, "state_code")
    rec = new_record()
    rec.update(
        {
            "fein": fein,
            "legal_name": legal_name,
            "state_code": state_code,
            "status": "ACTIVE",
        }
    )
    db["employers"][rec["id"]] = rec
    return ok_object(ser_employer(rec), code=201)


@app.route("/employers/<employerId>", methods=["GET"])
def get_employer(employerId):
    require_roles(*ROLES)
    rec = get_or_404("employers", employerId)
    return ok_object(ser_employer(rec))


# ---------------------------------------------------------------------------
# ClassCodes
# ---------------------------------------------------------------------------


@app.route("/class-codes", methods=["POST"])
def create_class_code():
    require_roles("BureauAdmin")
    data = body()
    code = req_str(data, "code")
    description = req_str(data, "description")
    state_code = req_str(data, "state_code")
    rec = new_record(with_version=False)
    rec.update(
        {
            "code": code,
            "description": description,
            "state_code": state_code,
            "status": "ACTIVE",
        }
    )
    db["class_codes"][rec["id"]] = rec
    return ok_object(ser_class_code(rec), code=201)


@app.route("/class-codes/<classCodeId>", methods=["GET"])
def get_class_code(classCodeId):
    require_roles(*ROLES)
    rec = get_or_404("class_codes", classCodeId)
    return ok_object(ser_class_code(rec))


# ---------------------------------------------------------------------------
# RatingTables
# ---------------------------------------------------------------------------


@app.route("/rating-tables", methods=["POST"])
def create_rating_table():
    require_roles("BureauAdmin")
    data = body()
    state_code = req_str(data, "state_code")
    effective_date = req_date(data, "effective_date")
    values = req_array(data, "values")
    for v in values:
        if not isinstance(v, dict):
            raise ApiError("ERR_INVALID_REQUEST", 400, "values entries must be objects")
        if "class_code" not in v or "rate_per_100_payroll_cents" not in v or "elr_per_100_payroll_cents" not in v or "d_ratio_bp" not in v:
            raise ApiError(
                "ERR_INVALID_REQUEST",
                400,
                "values entries require class_code, rate_per_100_payroll_cents, elr_per_100_payroll_cents, d_ratio_bp",
            )
    rec = new_record()
    rec.update(
        {
            "state_code": state_code,
            "effective_date": effective_date,
            "status": "DRAFT",
            "values": values,
            "superseded_at": None,
        }
    )
    db["rating_tables"][rec["id"]] = rec
    return ok_object(ser_rating_table(rec), code=201)


@app.route("/rating-tables/<ratingTableId>", methods=["GET"])
def get_rating_table(ratingTableId):
    require_roles(*ROLES)
    rec = get_or_404("rating_tables", ratingTableId)
    return ok_object(ser_rating_table(rec))


@app.route("/rating-tables/<ratingTableId>/promulgate", methods=["POST"])
def promulgate_rating_table(ratingTableId):
    require_roles("BureauAdmin")
    rec = get_or_404("rating_tables", ratingTableId)
    if rec["status"] != "DRAFT":
        raise ApiError(
            "ERR_INVALID_STATE", 409, f"rating table is {rec['status']}, not DRAFT"
        )
    # Supersede any other PROMULGATED tables for same state
    for other in db["rating_tables"].values():
        if (
            other["id"] != rec["id"]
            and other["state_code"] == rec["state_code"]
            and other["status"] == "PROMULGATED"
        ):
            other["status"] = "SUPERSEDED"
            other["superseded_at"] = wall_now_iso()
            touch(other)
    rec["status"] = "PROMULGATED"
    touch(rec)
    # A rating table revision invalidates every promulgated sheet for the state:
    # each moves PROMULGATED -> REVISED and a DRAFT revision sheet is spawned
    # with revision_reason RATE_REVISION (PRD section 3.6).
    affected_employers = set()
    for p in db["policies"].values():
        if p.get("_state_code") == rec["state_code"]:
            affected_employers.add(p["employer_id"])
    sheets_to_revise = [
        s
        for s in db["experience_mod_sheets"].values()
        if s["status"] == "PROMULGATED" and s["employer_id"] in affected_employers
    ]
    for sheet in sheets_to_revise:
        cascade_revise_sheet(sheet, "RATE_REVISION")
    return ok_object(ser_rating_table(rec))


# ---------------------------------------------------------------------------
# Policies
# ---------------------------------------------------------------------------


@app.route("/policies", methods=["POST"])
def create_policy():
    c = require_roles("CarrierDataReporter")
    data = body()
    employer_id = req_str(data, "employer_id")
    carrier_id = req_str(data, "carrier_id")
    policy_number = req_str(data, "policy_number")
    effective_date = req_date(data, "effective_date")
    expiration_date = req_date(data, "expiration_date")
    class_codes = req_array(data, "class_codes")
    # Validation order: existence -> temporal -> referential
    employer = get_or_404("employers", employer_id)
    carrier = get_or_404("carriers", carrier_id)
    # Temporal: effective < expiration
    eff = parse_date(effective_date)
    exp = parse_date(expiration_date)
    if eff >= exp:
        raise ApiError(
            "ERR_TEMPORAL_CONFLICT",
            409,
            "effective_date must be before expiration_date",
        )
    if employer["status"] != "ACTIVE":
        raise ApiError("ERR_EMPLOYER_INACTIVE", 409, "employer is not ACTIVE")
    if carrier["status"] != "ACTIVE":
        raise ApiError("ERR_CARRIER_NOT_ACTIVE", 409, "carrier is not ACTIVE")
    # Compute manual premium via promulgated table at policy effective_date
    rt = promulgated_table_for(employer["state_code"], effective_date)
    if rt is None:
        raise ApiError(
            "ERR_CLASS_CODE_NOT_RATED",
            409,
            "no promulgated rating table for state at effective date",
        )
    manual_premium = 0
    for line in class_codes:
        if not isinstance(line, dict):
            raise ApiError("ERR_INVALID_REQUEST", 400, "class_codes entries must be objects")
        cc = line.get("class_code")
        row = table_value_for(rt, cc)
        if row is None:
            raise ApiError(
                "ERR_CLASS_CODE_NOT_RATED",
                409,
                f"class code {cc} not rated in promulgated table",
            )
        rate = row.get("rate_per_100_payroll_cents")
        payroll_dollars = line.get("payroll_dollars", 0)
        manual_premium += round_half_up_int(dec(payroll_dollars) * dec(rate) / dec(100))
    rec = new_record()
    rec.update(
        {
            "employer_id": employer_id,
            "carrier_id": carrier_id,
            "policy_number": policy_number,
            "effective_date": effective_date,
            "expiration_date": expiration_date,
            "manual_premium_cents": manual_premium,
            "status": "ACTIVE",
            "class_codes": class_codes,
            "unit_stat_report_id": None,
            "_state_code": employer["state_code"],
        }
    )
    db["policies"][rec["id"]] = rec
    return ok_object(ser_policy(rec), code=201)


@app.route("/policies/<policyId>", methods=["GET"])
def get_policy(policyId):
    require_roles(*ROLES)
    rec = get_or_404("policies", policyId)
    return ok_object(ser_policy(rec))


@app.route("/policies", methods=["GET"])
def list_policies():
    require_roles(*ROLES)
    employer_id = request.args.get("employer_id")
    carrier_id = request.args.get("carrier_id")
    status = request.args.get("status")
    unit_stat_report_id = request.args.get("unit_stat_report_id")
    items = list(db["policies"].values())
    if employer_id:
        items = [p for p in items if p["employer_id"] == employer_id]
    if carrier_id:
        items = [p for p in items if p["carrier_id"] == carrier_id]
    if status:
        items = [p for p in items if p["status"] == status]
    if unit_stat_report_id:
        items = [p for p in items if p.get("unit_stat_report_id") == unit_stat_report_id]
    items = sort_by_created(items)
    return ok_array([ser_policy(p) for p in items])


# ---------------------------------------------------------------------------
# UnitStatReports
# ---------------------------------------------------------------------------


@app.route("/unit-stat-reports", methods=["POST"])
def create_unit_stat_report():
    c = require_roles("CarrierDataReporter")
    data = body()
    policy_id = req_str(data, "policy_id")
    payroll_lines = req_array(data, "payroll_lines")
    claim_lines = req_array(data, "claim_lines")
    correction_of_report_id = req_str(data, "correction_of_report_id", nullable=True)
    policy = get_or_404("policies", policy_id)
    # If correction, validate referenced report
    ref = None
    if correction_of_report_id:
        ref = get_or_404("unit_stat_reports", correction_of_report_id)
        if ref["status"] not in ("VALIDATED", "LOCKED"):
            raise ApiError(
                "ERR_INVALID_STATE",
                409,
                "correction_of_report_id must reference a VALIDATED or LOCKED report",
            )
    # Submission number = count of existing reports for policy + 1
    existing = [r for r in db["unit_stat_reports"].values() if r["policy_id"] == policy_id]
    submission_number = len(existing) + 1
    rec = new_record()
    rec.update(
        {
            "policy_id": policy_id,
            "payroll_lines": payroll_lines,
            "claim_lines": claim_lines,
            "status": "SUBMITTED",
            "submission_number": submission_number,
            "correction_of_report_id": correction_of_report_id,
        }
    )
    db["unit_stat_reports"][rec["id"]] = rec
    return ok_object(ser_unit_stat_report(rec), code=201)


@app.route("/unit-stat-reports/<unitStatReportId>", methods=["GET"])
def get_unit_stat_report(unitStatReportId):
    require_roles(*ROLES)
    rec = get_or_404("unit_stat_reports", unitStatReportId)
    return ok_object(ser_unit_stat_report(rec))


@app.route("/unit-stat-reports", methods=["GET"])
def list_unit_stat_reports():
    require_roles(*ROLES)
    policy_id = request.args.get("policy_id")
    status = request.args.get("status")
    correction_of_report_id = request.args.get("correction_of_report_id")
    items = list(db["unit_stat_reports"].values())
    if policy_id:
        items = [r for r in items if r["policy_id"] == policy_id]
    if status:
        items = [r for r in items if r["status"] == status]
    if correction_of_report_id:
        items = [r for r in items if r.get("correction_of_report_id") == correction_of_report_id]
    items = sort_by_created(items)
    return ok_array([ser_unit_stat_report(r) for r in items])


@app.route("/unit-stat-reports/<unitStatReportId>/validate", methods=["POST"])
def validate_unit_stat_report(unitStatReportId):
    require_roles("BureauAnalyst")
    rec = get_or_404("unit_stat_reports", unitStatReportId)
    if rec["status"] != "SUBMITTED":
        raise ApiError(
            "ERR_INVALID_STATE", 409, f"report is {rec['status']}, not SUBMITTED"
        )
    policy = db["policies"].get(rec["policy_id"])
    if policy is None:
        raise ApiError("ERR_NOT_FOUND", 404, "policy not found")
    if policy["status"] != "ACTIVE":
        raise ApiError(
            "ERR_INVALID_STATE", 409, "policy is not ACTIVE"
        )
    if not rec["payroll_lines"] or not rec["claim_lines"]:
        raise ApiError(
            "ERR_INVALID_REQUEST",
            400,
            "report must contain at least one payroll line and one claim line",
        )
    policy_state = policy.get("_state_code")
    for cl in rec["claim_lines"]:
        if cl.get("state_code") != policy_state:
            raise ApiError(
                "ERR_STATE_MISMATCH",
                409,
                "claim state_code does not match policy state",
            )
    # Verify payroll line class codes are ACTIVE
    for pl in rec["payroll_lines"]:
        cc = pl.get("class_code")
        match = None
        for c in db["class_codes"].values():
            if c["code"] == cc and c["state_code"] == policy_state:
                match = c
                break
        if match is None or match["status"] != "ACTIVE":
            raise ApiError(
                "ERR_CLASS_CODE_INACTIVE", 409, f"class code {cc} is not ACTIVE"
            )
    rec["status"] = "VALIDATED"
    touch(rec)
    # Set Policy.unit_stat_report_id = this report
    policy["unit_stat_report_id"] = rec["id"]
    touch(policy)
    # If correction_of_report_id set, referenced report -> CORRECTED; when the
    # referenced report was LOCKED into a promulgated sheet, that sheet moves to
    # REVISED and a DRAFT revision sheet is spawned (PRD section 3.6).
    if rec.get("correction_of_report_id"):
        ref = db["unit_stat_reports"].get(rec["correction_of_report_id"])
        if ref and ref["status"] in ("VALIDATED", "LOCKED"):
            was_locked = ref["status"] == "LOCKED"
            ref["status"] = "CORRECTED"
            touch(ref)
            if was_locked:
                for sheet in sheets_consuming_report(ref["id"]):
                    cascade_revise_sheet(sheet, "CLAIM_VALUE_CHANGE")
    return ok_object(ser_unit_stat_report(rec))


# ---------------------------------------------------------------------------
# ClassAssignments
# ---------------------------------------------------------------------------


@app.route("/class-assignments", methods=["POST"])
def create_class_assignment():
    require_roles("BureauAnalyst")
    data = body()
    employer_id = req_str(data, "employer_id")
    class_code_id = req_str(data, "class_code_id")
    effective_date = req_date(data, "effective_date")
    employer = get_or_404("employers", employer_id)
    class_code = get_or_404("class_codes", class_code_id)
    rec = new_record()
    rec.update(
        {
            "employer_id": employer_id,
            "class_code_id": class_code_id,
            "effective_date": effective_date,
            "status": "PENDING_INSPECTION",
            "inspection_id": None,
            "dispute_id": None,
        }
    )
    db["class_assignments"][rec["id"]] = rec
    return ok_object(ser_class_assignment(rec), code=201)


@app.route("/class-assignments/<classAssignmentId>", methods=["GET"])
def get_class_assignment(classAssignmentId):
    require_roles(*ROLES)
    rec = get_or_404("class_assignments", classAssignmentId)
    return ok_object(ser_class_assignment(rec))


@app.route("/class-assignments", methods=["GET"])
def list_class_assignments():
    require_roles(*ROLES)
    employer_id = request.args.get("employer_id")
    status = request.args.get("status")
    class_code_id = request.args.get("class_code_id")
    inspection_id = request.args.get("inspection_id")
    dispute_id = request.args.get("dispute_id")
    items = list(db["class_assignments"].values())
    if employer_id:
        items = [a for a in items if a["employer_id"] == employer_id]
    if status:
        items = [a for a in items if a["status"] == status]
    if class_code_id:
        items = [a for a in items if a["class_code_id"] == class_code_id]
    if inspection_id:
        items = [a for a in items if a.get("inspection_id") == inspection_id]
    if dispute_id:
        items = [a for a in items if a.get("dispute_id") == dispute_id]
    items = sort_by_created(items)
    return ok_array([ser_class_assignment(a) for a in items])


def employer_has_prior_completed_inspection(employer_id, years=3):
    """Return True if the employer has any COMPLETED inspection within the past N years."""
    cutoff = logical_clock() - timedelta(days=365 * years)
    for a in db["class_assignments"].values():
        if a["employer_id"] != employer_id:
            continue
        for ins in db["inspections"].values():
            if ins["class_assignment_id"] != a["id"]:
                continue
            if ins["status"] == "COMPLETED":
                try:
                    comp_dt = parse_iso(ins["updated_at"])
                except (ValueError, TypeError):
                    continue
                if comp_dt >= cutoff:
                    return True
    return False


@app.route("/class-assignments/<classAssignmentId>/assign", methods=["POST"])
def assign_class_assignment(classAssignmentId):
    require_roles("BureauAnalyst")
    rec = get_or_404("class_assignments", classAssignmentId)
    if rec["status"] != "PENDING_INSPECTION":
        raise ApiError(
            "ERR_INVALID_STATE",
            409,
            f"assignment is {rec['status']}, not PENDING_INSPECTION",
        )
    employer = db["employers"].get(rec["employer_id"])
    if employer is None:
        raise ApiError("ERR_NOT_FOUND", 404, "employer not found")
    if employer["status"] != "ACTIVE":
        raise ApiError("ERR_EMPLOYER_INACTIVE", 409, "employer is not ACTIVE")
    class_code = db["class_codes"].get(rec["class_code_id"])
    if class_code is None:
        raise ApiError("ERR_NOT_FOUND", 404, "class code not found")
    if class_code["status"] != "ACTIVE":
        raise ApiError("ERR_CLASS_CODE_INACTIVE", 409, "class code is not ACTIVE")
    # Overlap check: another ASSIGNED/CONFIRMED for same employer with overlapping effective_date
    target_eff = parse_date(rec["effective_date"])
    for other in db["class_assignments"].values():
        if other["id"] == rec["id"]:
            continue
        if other["employer_id"] != rec["employer_id"]:
            continue
        if other["status"] not in ("ASSIGNED", "CONFIRMED"):
            continue
        try:
            other_eff = parse_date(other["effective_date"])
        except (ValueError, TypeError):
            continue
        if other_eff == target_eff:
            raise ApiError(
                "ERR_CLASS_ASSIGNMENT_OVERLAP",
                409,
                "another ASSIGNED/CONFIRMED assignment exists with overlapping effective_date",
            )
    rec["status"] = "ASSIGNED"
    touch(rec)
    # Side effect: create Inspection if employer has no prior inspection in past 3 years
    if not employer_has_prior_completed_inspection(rec["employer_id"]):
        ins = new_record()
        ins.update(
            {
                "class_assignment_id": rec["id"],
                "inspector_id": None,
                "scheduled_date": wall_now_iso()[:10],
                "status": "SCHEDULED",
                "findings": None,
            }
        )
        db["inspections"][ins["id"]] = ins
        rec["inspection_id"] = ins["id"]
        touch(rec)
    return ok_object(ser_class_assignment(rec))


@app.route("/class-assignments/<classAssignmentId>/confirm", methods=["POST"])
def confirm_class_assignment(classAssignmentId):
    require_roles("BureauAnalyst")
    rec = get_or_404("class_assignments", classAssignmentId)
    if rec["status"] != "ASSIGNED":
        raise ApiError(
            "ERR_INVALID_STATE", 409, f"assignment is {rec['status']}, not ASSIGNED"
        )
    # All inspections for this assignment must be COMPLETED or WAIVED
    for ins in db["inspections"].values():
        if ins["class_assignment_id"] == rec["id"] and ins["status"] not in (
            "COMPLETED",
            "WAIVED",
        ):
            raise ApiError(
                "ERR_INSPECTION_REQUIRED",
                409,
                "inspection for this assignment is not COMPLETED or WAIVED",
            )
    rec["status"] = "CONFIRMED"
    touch(rec)
    return ok_object(ser_class_assignment(rec))


@app.route("/class-assignments/<classAssignmentId>/withdraw", methods=["POST"])
def withdraw_class_assignment(classAssignmentId):
    c = require_roles("EmployerRepresentative")
    rec = get_or_404("class_assignments", classAssignmentId)
    if rec["status"] != "PENDING_INSPECTION":
        raise ApiError(
            "ERR_INVALID_STATE",
            409,
            f"assignment is {rec['status']}, not PENDING_INSPECTION",
        )
    rec["status"] = "WITHDRAWN"
    touch(rec)
    return ok_object(ser_class_assignment(rec))


# ---------------------------------------------------------------------------
# Inspections
# ---------------------------------------------------------------------------


@app.route("/inspections/<inspectionId>", methods=["GET"])
def get_inspection(inspectionId):
    require_roles(*ROLES)
    rec = get_or_404("inspections", inspectionId)
    return ok_object(ser_inspection(rec))


@app.route("/inspections", methods=["GET"])
def list_inspections():
    require_roles(*ROLES)
    class_assignment_id = request.args.get("class_assignment_id")
    status = request.args.get("status")
    items = list(db["inspections"].values())
    if class_assignment_id:
        items = [i for i in items if i["class_assignment_id"] == class_assignment_id]
    if status:
        items = [i for i in items if i["status"] == status]
    items = sort_by_created(items)
    return ok_array([ser_inspection(i) for i in items])


@app.route("/inspections/<inspectionId>/complete", methods=["POST"])
def complete_inspection(inspectionId):
    c = require_roles("Inspector")
    data = body()
    findings = req_str(data, "findings")
    rec = get_or_404("inspections", inspectionId)
    if rec["status"] != "SCHEDULED":
        raise ApiError(
            "ERR_INVALID_STATE", 409, f"inspection is {rec['status']}, not SCHEDULED"
        )
    rec["status"] = "COMPLETED"
    rec["findings"] = findings
    rec["inspector_id"] = c["id"]
    touch(rec)
    return ok_object(ser_inspection(rec))


@app.route("/inspections/<inspectionId>/waive", methods=["POST"])
def waive_inspection(inspectionId):
    require_roles("BureauAnalyst")
    rec = get_or_404("inspections", inspectionId)
    if rec["status"] != "SCHEDULED":
        raise ApiError(
            "ERR_INVALID_STATE", 409, f"inspection is {rec['status']}, not SCHEDULED"
        )
    # Employer must have prior completed inspection in past 3 years
    assignment = db["class_assignments"].get(rec["class_assignment_id"])
    if assignment is None:
        raise ApiError("ERR_NOT_FOUND", 404, "class assignment not found")
    employer_id = assignment["employer_id"]
    if not employer_has_prior_completed_inspection(employer_id):
        raise ApiError(
            "ERR_INSPECTION_WAIVE_NOT_ALLOWED",
            409,
            "no prior completed inspection within the past 3 years",
        )
    rec["status"] = "WAIVED"
    touch(rec)
    return ok_object(ser_inspection(rec))


# ---------------------------------------------------------------------------
# ClassAssignmentDisputes
# ---------------------------------------------------------------------------


@app.route("/class-assignment-disputes", methods=["POST"])
def create_class_assignment_dispute():
    c = require_roles("EmployerRepresentative")
    data = body()
    class_assignment_id = req_str(data, "class_assignment_id")
    reason = req_enum(data, "reason", {"WRONG_CLASS", "PAYROLL_MISMATCH", "OTHER"})
    assignment = get_or_404("class_assignments", class_assignment_id)
    if assignment["status"] not in ("ASSIGNED", "CONFIRMED"):
        raise ApiError(
            "ERR_INVALID_STATE",
            409,
            f"assignment is {assignment['status']}, must be ASSIGNED or CONFIRMED",
        )
    prior_status = assignment["status"]
    rec = new_record()
    rec.update(
        {
            "class_assignment_id": class_assignment_id,
            "employer_id": assignment["employer_id"],
            "reason": reason,
            "status": "OPEN",
            "resolution": None,
            "resolved_at": None,
            "_prior_assignment_status": prior_status,
        }
    )
    db["class_assignment_disputes"][rec["id"]] = rec
    assignment["status"] = "DISPUTED"
    assignment["dispute_id"] = rec["id"]
    touch(assignment)
    return ok_object(ser_class_assignment_dispute(rec), code=201)


@app.route("/class-assignment-disputes/<disputeId>", methods=["GET"])
def get_class_assignment_dispute(disputeId):
    require_roles(*ROLES)
    rec = get_or_404("class_assignment_disputes", disputeId)
    return ok_object(ser_class_assignment_dispute(rec))


@app.route("/class-assignment-disputes", methods=["GET"])
def list_class_assignment_disputes():
    require_roles(*ROLES)
    class_assignment_id = request.args.get("class_assignment_id")
    employer_id = request.args.get("employer_id")
    status = request.args.get("status")
    items = list(db["class_assignment_disputes"].values())
    if class_assignment_id:
        items = [d for d in items if d["class_assignment_id"] == class_assignment_id]
    if employer_id:
        items = [d for d in items if d["employer_id"] == employer_id]
    if status:
        items = [d for d in items if d["status"] == status]
    items = sort_by_created(items)
    return ok_array([ser_class_assignment_dispute(d) for d in items])


@app.route("/class-assignment-disputes/<disputeId>/review", methods=["POST"])
def review_class_assignment_dispute(disputeId):
    require_roles("BureauAnalyst")
    rec = get_or_404("class_assignment_disputes", disputeId)
    if rec["status"] != "OPEN":
        raise ApiError("ERR_INVALID_STATE", 409, f"dispute is {rec['status']}, not OPEN")
    rec["status"] = "IN_REVIEW"
    touch(rec)
    return ok_object(ser_class_assignment_dispute(rec))


@app.route("/class-assignment-disputes/<disputeId>/resolve", methods=["POST"])
def resolve_class_assignment_dispute(disputeId):
    require_roles("BureauAnalyst")
    data = body()
    resolution = req_enum(data, "resolution", {"CONFIRMED", "REASSIGNED"})
    new_class_code_id = req_str(data, "new_class_code_id", nullable=True)
    rec = get_or_404("class_assignment_disputes", disputeId)
    if rec["status"] != "IN_REVIEW":
        raise ApiError(
            "ERR_INVALID_STATE", 409, f"dispute is {rec['status']}, not IN_REVIEW"
        )
    assignment = db["class_assignments"].get(rec["class_assignment_id"])
    if assignment is None:
        raise ApiError("ERR_NOT_FOUND", 404, "class assignment not found")
    if resolution == "REASSIGNED":
        if not new_class_code_id:
            raise ApiError(
                "ERR_INVALID_REQUEST",
                400,
                "new_class_code_id is required when resolution is REASSIGNED",
            )
        new_cc = get_or_404("class_codes", new_class_code_id)
        if new_cc["status"] != "ACTIVE":
            raise ApiError(
                "ERR_CLASS_CODE_INACTIVE", 409, "new class code is not ACTIVE"
            )
    # Resolve dispute
    rec["status"] = "RESOLVED"
    rec["resolution"] = resolution
    rec["resolved_at"] = wall_now_iso()
    touch(rec)
    if resolution == "CONFIRMED":
        assignment["status"] = "CONFIRMED"
        touch(assignment)
    else:
        # REASSIGNED
        assignment["status"] = "REASSIGNED"
        touch(assignment)
        # Spawn a brand-new assignment directly in ASSIGNED
        new_assignment = new_record()
        new_assignment.update(
            {
                "employer_id": assignment["employer_id"],
                "class_code_id": new_class_code_id,
                "effective_date": assignment["effective_date"],
                "status": "ASSIGNED",
                "inspection_id": None,
                "dispute_id": None,
            }
        )
        db["class_assignments"][new_assignment["id"]] = new_assignment
        # A confirmed class code reassignment invalidates the employer's
        # promulgated sheet: it moves PROMULGATED -> REVISED and a DRAFT
        # revision sheet is spawned with revision_reason CLASS_CODE_CHANGE
        # (PRD section 3.6).
        sheets_to_revise = [
            s
            for s in db["experience_mod_sheets"].values()
            if s["status"] == "PROMULGATED"
            and s["employer_id"] == assignment["employer_id"]
        ]
        for sheet in sheets_to_revise:
            cascade_revise_sheet(sheet, "CLASS_CODE_CHANGE")
    return ok_object(ser_class_assignment_dispute(rec))


@app.route("/class-assignment-disputes/<disputeId>/withdraw", methods=["POST"])
def withdraw_class_assignment_dispute(disputeId):
    c = require_roles("EmployerRepresentative")
    rec = get_or_404("class_assignment_disputes", disputeId)
    if rec["status"] != "OPEN":
        raise ApiError("ERR_INVALID_STATE", 409, f"dispute is {rec['status']}, not OPEN")
    rec["status"] = "WITHDRAWN"
    touch(rec)
    # ClassAssignment reverts to its prior status (ASSIGNED or CONFIRMED)
    assignment = db["class_assignments"].get(rec["class_assignment_id"])
    if assignment is not None:
        prior = rec.get("_prior_assignment_status") or "ASSIGNED"
        assignment["status"] = prior
        touch(assignment)
    return ok_object(ser_class_assignment_dispute(rec))


# ---------------------------------------------------------------------------
# ExperienceModSheets
# ---------------------------------------------------------------------------


def active_appeal_for_sheet(sheet_id):
    for a in db["mod_appeals"].values():
        if a["mod_sheet_id"] == sheet_id and a["status"] in ("FILED", "UNDER_REVIEW"):
            return a
    return None


@app.route("/experience-mod-sheets", methods=["POST"])
def create_experience_mod_sheet():
    c = require_roles("BureauAnalyst")
    data = body()
    employer_id = req_str(data, "employer_id")
    rating_effective_date = req_date(data, "rating_effective_date")
    expected_employer_version = data.get("expected_employer_version")
    revision_reason = data.get("revision_reason")
    revision_of_sheet_id = data.get("revision_of_sheet_id")
    employer = get_or_404("employers", employer_id)
    # OCC check
    if expected_employer_version is not None:
        if not isinstance(expected_employer_version, int) or isinstance(
            expected_employer_version, bool
        ):
            raise ApiError(
                "ERR_INVALID_REQUEST", 400, "expected_employer_version must be an integer"
            )
        if expected_employer_version != employer["version"]:
            raise ApiError(
                "ERR_STALE_VERSION",
                412,
                "employer version does not match expected_employer_version",
            )
    final, prov = compute_sheet_fields(employer_id, rating_effective_date)
    rec = new_record()
    rec.update(
        {
            "employer_id": employer_id,
            "rating_effective_date": rating_effective_date,
            "status": "DRAFT",
            "mod_factor": final["mod_factor"],
            "expected_losses_cents": final["expected_losses_cents"],
            "actual_primary_cents": final["actual_primary_cents"],
            "actual_excess_cents": final["actual_excess_cents"],
            "ballast_cents": final["ballast_cents"],
            "weight_w": final["weight_w"],
            "expected_primary_cents": final["expected_primary_cents"],
            "expected_excess_cents": final["expected_excess_cents"],
            "provisional_mod_factor": prov["mod_factor"],
            "retroactive_premium_adjustment_cents": 0,
            "revision_of_sheet_id": revision_of_sheet_id,
            "revision_reason": revision_reason,
            "_created_by": c["id"],
        }
    )
    db["experience_mod_sheets"][rec["id"]] = rec
    # bump employer version
    touch(employer)
    return ok_object(ser_experience_mod_sheet(rec), code=201)


@app.route("/experience-mod-sheets/<modSheetId>", methods=["GET"])
def get_experience_mod_sheet(modSheetId):
    require_roles(*ROLES)
    rec = get_or_404("experience_mod_sheets", modSheetId)
    return ok_object(ser_experience_mod_sheet(rec))


@app.route("/experience-mod-sheets", methods=["GET"])
def list_experience_mod_sheets():
    require_roles(*ROLES)
    employer_id = request.args.get("employer_id")
    status = request.args.get("status")
    rating_effective_date = request.args.get("rating_effective_date")
    revision_of_sheet_id = request.args.get("revision_of_sheet_id")
    items = list(db["experience_mod_sheets"].values())
    if employer_id:
        items = [s for s in items if s["employer_id"] == employer_id]
    if status:
        items = [s for s in items if s["status"] == status]
    if rating_effective_date:
        items = [s for s in items if s["rating_effective_date"] == rating_effective_date]
    if revision_of_sheet_id:
        items = [s for s in items if s.get("revision_of_sheet_id") == revision_of_sheet_id]
    items = sort_by_created(items)
    return ok_array([ser_experience_mod_sheet(s) for s in items])


@app.route("/experience-mod-sheets/<modSheetId>/promulgate", methods=["POST"])
def promulgate_experience_mod_sheet(modSheetId):
    require_roles("BureauAnalyst")
    rec = get_or_404("experience_mod_sheets", modSheetId)
    if rec["status"] != "DRAFT":
        raise ApiError("ERR_INVALID_STATE", 409, f"sheet is {rec['status']}, not DRAFT")
    employer = db["employers"].get(rec["employer_id"])
    if employer is None:
        raise ApiError("ERR_NOT_FOUND", 404, "employer not found")
    if employer["status"] != "ACTIVE":
        raise ApiError("ERR_EMPLOYER_INACTIVE", 409, "employer is not ACTIVE")
    # All UnitStatReports contributing to the sheet must be VALIDATED or LOCKED
    contributing = employer_reports(rec["employer_id"], statuses={"SUBMITTED", "VALIDATED", "LOCKED"})
    has_submitted = any(r["status"] == "SUBMITTED" for r in contributing)
    if has_submitted:
        raise ApiError(
            "ERR_UNVALIDATED_REPORTS",
            409,
            "one or more contributing reports are still SUBMITTED",
        )
    # Eligibility check
    bureau = get_bureau_or_404()
    eligible = rec["expected_losses_cents"] >= bureau["eligibility_threshold_cents"]
    # If a prior promulgated sheet exists for same employer/rating_effective_date,
    # this sheet must carry revision_reason or be a revision of it
    prior_promulgated = None
    for s in db["experience_mod_sheets"].values():
        if (
            s["id"] != rec["id"]
            and s["employer_id"] == rec["employer_id"]
            and s["rating_effective_date"] == rec["rating_effective_date"]
            and s["status"] == "PROMULGATED"
        ):
            prior_promulgated = s
            break
    if prior_promulgated is not None and not rec.get("revision_reason"):
        raise ApiError(
            "ERR_MOD_REVISION_REQUIRED",
            409,
            "prior promulgated sheet exists; revision_reason required",
        )
    # Successful promulgation
    rec["status"] = "PROMULGATED"
    if not eligible:
        # Below the eligibility threshold the factor is fixed at exactly 1.00
        # (unity) and the sheet still promulgates with that value.
        rec["mod_factor"] = "1.00"
    touch(rec)
    # Lock every consumed report (VALIDATED -> LOCKED)
    for r in contributing:
        if r["status"] == "VALIDATED":
            r["status"] = "LOCKED"
            touch(r)
    # If revision_of_sheet_id set, referenced sheet PROMULGATED -> REVISED
    if rec.get("revision_of_sheet_id"):
        ref = db["experience_mod_sheets"].get(rec["revision_of_sheet_id"])
        if ref is not None and ref["status"] == "PROMULGATED":
            ref["status"] = "REVISED"
            touch(ref)
            # Compute retroactive adjustment
            rec["retroactive_premium_adjustment_cents"] = retroactive_premium_adjustment(
                ref, rec, rec["employer_id"]
            )
            touch(rec)
    # If expected losses >= underwriting threshold, create UnderwritingReview
    if rec["expected_losses_cents"] >= bureau["underwriting_threshold_cents"]:
        review = new_record()
        review.update(
            {
                "subject_type": "MOD_SHEET",
                "subject_id": rec["id"],
                "status": "PENDING",
                "reviewer_id": None,
                "decided_at": None,
                "_created_by": rec.get("_created_by"),
            }
        )
        db["underwriting_reviews"][review["id"]] = review
    return ok_object(ser_experience_mod_sheet(rec))


@app.route("/experience-mod-sheets/<modSheetId>/finalize", methods=["POST"])
def finalize_experience_mod_sheet(modSheetId):
    require_roles("BureauAnalyst")
    rec = get_or_404("experience_mod_sheets", modSheetId)
    if rec["status"] not in ("DRAFT", "REVISED"):
        raise ApiError(
            "ERR_INVALID_STATE",
            409,
            f"sheet is {rec['status']}, cannot finalize",
        )
    if active_appeal_for_sheet(rec["id"]) is not None:
        raise ApiError(
            "ERR_APPEAL_ALREADY_ACTIVE",
            409,
            "an active appeal exists for this sheet",
        )
    rec["status"] = "FINAL"
    touch(rec)
    return ok_object(ser_experience_mod_sheet(rec))


# ---------------------------------------------------------------------------
# ModAppeals
# ---------------------------------------------------------------------------


@app.route("/mod-appeals", methods=["POST"])
def create_mod_appeal():
    c = require_roles("EmployerRepresentative")
    data = body()
    mod_sheet_id = data.get("mod_sheet_id")
    if not isinstance(mod_sheet_id, str) or not mod_sheet_id:
        raise ApiError("ERR_INVALID_REQUEST", 400, "mod_sheet_id is required")
    sheet = get_or_404("experience_mod_sheets", mod_sheet_id)
    # Aggregate constraint (duplicate appeal) outranks the sheet state check per
    # the validation precedence in section 2.7.
    if active_appeal_for_sheet(sheet["id"]) is not None:
        raise ApiError(
            "ERR_APPEAL_ALREADY_ACTIVE",
            409,
            "an active appeal already exists for this sheet",
        )
    if sheet["status"] != "PROMULGATED":
        raise ApiError(
            "ERR_INVALID_STATE",
            409,
            f"sheet is {sheet['status']}, must be PROMULGATED",
        )
    reason = req_str(data, "reason")
    rec = new_record()
    rec.update(
        {
            "mod_sheet_id": mod_sheet_id,
            "employer_id": sheet["employer_id"],
            "reason": reason,
            "status": "FILED",
            "filed_at": wall_now_iso(),
            "decided_at": None,
            "decision": None,
            "decision_reason": None,
        }
    )
    db["mod_appeals"][rec["id"]] = rec
    sheet["status"] = "CONTESTED"
    touch(sheet)
    return ok_object(ser_mod_appeal(rec), code=201)


@app.route("/mod-appeals/<appealId>", methods=["GET"])
def get_mod_appeal(appealId):
    require_roles(*ROLES)
    rec = get_or_404("mod_appeals", appealId)
    return ok_object(ser_mod_appeal(rec))


@app.route("/mod-appeals", methods=["GET"])
def list_mod_appeals():
    require_roles(*ROLES)
    mod_sheet_id = request.args.get("mod_sheet_id")
    employer_id = request.args.get("employer_id")
    status = request.args.get("status")
    items = list(db["mod_appeals"].values())
    if mod_sheet_id:
        items = [a for a in items if a["mod_sheet_id"] == mod_sheet_id]
    if employer_id:
        items = [a for a in items if a["employer_id"] == employer_id]
    if status:
        items = [a for a in items if a["status"] == status]
    items = sort_by_created(items)
    return ok_array([ser_mod_appeal(a) for a in items])


@app.route("/mod-appeals/<appealId>/review", methods=["POST"])
def review_mod_appeal(appealId):
    require_roles("BureauAnalyst")
    rec = get_or_404("mod_appeals", appealId)
    if rec["status"] != "FILED":
        raise ApiError("ERR_INVALID_STATE", 409, f"appeal is {rec['status']}, not FILED")
    rec["status"] = "UNDER_REVIEW"
    touch(rec)
    return ok_object(ser_mod_appeal(rec))


@app.route("/mod-appeals/<appealId>/decide", methods=["POST"])
def decide_mod_appeal(appealId):
    require_roles("BureauAnalyst")
    data = body()
    decision = req_enum(data, "decision", {"UPHELD", "REVERSED"})
    decision_reason = req_str(data, "decision_reason")
    rec = get_or_404("mod_appeals", appealId)
    if rec["status"] != "UNDER_REVIEW":
        raise ApiError(
            "ERR_INVALID_STATE", 409, f"appeal is {rec['status']}, not UNDER_REVIEW"
        )
    sheet = db["experience_mod_sheets"].get(rec["mod_sheet_id"])
    if sheet is None:
        raise ApiError("ERR_NOT_FOUND", 404, "sheet not found")
    rec["status"] = decision
    rec["decision"] = decision
    rec["decision_reason"] = decision_reason
    rec["decided_at"] = wall_now_iso()
    touch(rec)
    if decision == "UPHELD":
        sheet["status"] = "FINAL"
        touch(sheet)
    else:
        # REVERSED
        sheet["status"] = "REVISED"
        touch(sheet)
        # Spawn a new DRAFT sheet as a revision
        spawn_revision_sheet(sheet, "CLAIM_VALUE_CHANGE")
    return ok_object(ser_mod_appeal(rec))


@app.route("/mod-appeals/<appealId>/withdraw", methods=["POST"])
def withdraw_mod_appeal(appealId):
    c = require_roles("EmployerRepresentative")
    rec = get_or_404("mod_appeals", appealId)
    if rec["status"] != "FILED":
        raise ApiError("ERR_INVALID_STATE", 409, f"appeal is {rec['status']}, not FILED")
    rec["status"] = "WITHDRAWN"
    touch(rec)
    sheet = db["experience_mod_sheets"].get(rec["mod_sheet_id"])
    if sheet is not None and sheet["status"] == "CONTESTED":
        sheet["status"] = "PROMULGATED"
        touch(sheet)
    return ok_object(ser_mod_appeal(rec))


# ---------------------------------------------------------------------------
# OwnershipChanges
# ---------------------------------------------------------------------------


@app.route("/ownership-changes", methods=["POST"])
def create_ownership_change():
    require_roles("BureauAnalyst")
    data = body()
    employer_id = req_str(data, "employer_id")
    change_type = req_enum(
        data, "change_type", {"SALE", "MERGER", "FORMATION_OF_NEW_ENTITY", "OTHER"}
    )
    effective_date = req_date(data, "effective_date")
    employer = get_or_404("employers", employer_id)
    rec = new_record()
    rec.update(
        {
            "employer_id": employer_id,
            "change_type": change_type,
            "effective_date": effective_date,
            "status": "PENDING",
            "combinability_group_id": None,
        }
    )
    db["ownership_changes"][rec["id"]] = rec
    return ok_object(ser_ownership_change(rec), code=201)


@app.route("/ownership-changes/<changeId>", methods=["GET"])
def get_ownership_change(changeId):
    require_roles(*ROLES)
    rec = get_or_404("ownership_changes", changeId)
    return ok_object(ser_ownership_change(rec))


@app.route("/ownership-changes", methods=["GET"])
def list_ownership_changes():
    require_roles(*ROLES)
    employer_id = request.args.get("employer_id")
    status = request.args.get("status")
    combinability_group_id = request.args.get("combinability_group_id")
    items = list(db["ownership_changes"].values())
    if employer_id:
        items = [c for c in items if c["employer_id"] == employer_id]
    if status:
        items = [c for c in items if c["status"] == status]
    if combinability_group_id:
        items = [c for c in items if c.get("combinability_group_id") == combinability_group_id]
    items = sort_by_created(items)
    return ok_array([ser_ownership_change(c) for c in items])


@app.route("/ownership-changes/<changeId>/combine", methods=["POST"])
def combine_ownership_change(changeId):
    require_roles("BureauAnalyst")
    data = body()
    member_employer_ids = req_array(data, "member_employer_ids")
    rec = get_or_404("ownership_changes", changeId)
    if rec["status"] != "PENDING":
        raise ApiError("ERR_INVALID_STATE", 409, f"change is {rec['status']}, not PENDING")
    # Build full member list (change's employer + supplied related)
    all_members = [rec["employer_id"]] + [e for e in member_employer_ids if e != rec["employer_id"]]
    # All must exist and be ACTIVE
    employers = []
    for eid in all_members:
        e = get_or_404("employers", eid)
        if e["status"] != "ACTIVE":
            raise ApiError("ERR_EMPLOYER_INACTIVE", 409, f"employer {eid} is not ACTIVE")
        employers.append(e)
    # None may already be in another ACTIVE CombinabilityGroup
    for eid in all_members:
        for g in db["combinability_groups"].values():
            if g["status"] != "ACTIVE":
                continue
            if eid in g["member_employer_ids"]:
                raise ApiError(
                    "ERR_ALREADY_COMBINED",
                    409,
                    f"employer {eid} is already in an ACTIVE combinability group",
                )
    # Create group
    group = new_record()
    group.update(
        {
            "member_employer_ids": all_members,
            "status": "ACTIVE",
            "created_from_change_id": rec["id"],
            "combined_mod_sheet_id": None,
        }
    )
    db["combinability_groups"][group["id"]] = group
    rec["status"] = "COMBINED"
    rec["combinability_group_id"] = group["id"]
    touch(rec)
    # Create a combined DRAFT ExperienceModSheet for the group
    # Use the change's employer as the anchor; combine all members' reports.
    anchor_employer_id = rec["employer_id"]
    anchor_employer = db["employers"][anchor_employer_id]
    rating_eff = wall_now_iso()[:10]
    # Compute aggregated inputs across all members
    bureau = get_bureau_or_404()
    expected_losses_cents = 0
    actual_primary_cents = 0
    actual_excess_cents = 0
    d_ratio_bp = None
    for eid in all_members:
        e = db["employers"][eid]
        for r in employer_reports(eid, statuses={"VALIDATED", "LOCKED"}):
            p = db["policies"].get(r["policy_id"])
            if p is None:
                continue
            rt = promulgated_table_for(e["state_code"], rating_eff)
            for pl in r["payroll_lines"]:
                row = table_value_for(rt, pl.get("class_code")) if rt else None
                if row is None:
                    continue
                elr = row.get("elr_per_100_payroll_cents")
                line_cents = round_half_up_int(
                    dec(pl.get("payroll_dollars", 0)) * dec(elr) / dec(100)
                )
                expected_losses_cents += line_cents
                if d_ratio_bp is None:
                    d_ratio_bp = row.get("d_ratio_bp")
            for cl in r["claim_lines"]:
                incurred = cl.get("incurred_cents", 0)
                primary = min(incurred, bureau["split_point_cents"])
                actual_primary_cents += primary
                actual_excess_cents += incurred - primary
    K = dec(bureau["credibility_ballast_bp"]) / dec(10000)
    J = dec(bureau["credibility_excess_divisor_bp"]) / dec(10000)
    E = dec(expected_losses_cents)
    B = round_half_up_int(K * E)
    denom_w = E + J * dec(100000000)
    W = Decimal("0") if denom_w == 0 else round_half_up_dec(E / denom_w, 4)
    expected_primary_cents = (
        0 if d_ratio_bp is None else round_half_up_int(E * dec(d_ratio_bp) / dec(10000))
    )
    expected_excess_cents = expected_losses_cents - expected_primary_cents
    term_Ae = round_half_up_int(W * dec(actual_excess_cents))
    term_Ee = round_half_up_int((Decimal(1) - W) * dec(expected_excess_cents))
    numerator = dec(actual_primary_cents) + dec(term_Ae) + dec(term_Ee) + dec(B)
    denominator = E + dec(B)
    mod_factor = (
        Decimal("1.00") if denominator == 0 else round_half_up_dec(numerator / denominator, 2)
    )
    sheet = new_record()
    sheet.update(
        {
            "employer_id": anchor_employer_id,
            "rating_effective_date": rating_eff,
            "status": "DRAFT",
            "mod_factor": str(mod_factor),
            "expected_losses_cents": expected_losses_cents,
            "actual_primary_cents": actual_primary_cents,
            "actual_excess_cents": actual_excess_cents,
            "ballast_cents": B,
            "weight_w": str(W),
            "expected_primary_cents": expected_primary_cents,
            "expected_excess_cents": expected_excess_cents,
            "provisional_mod_factor": str(mod_factor),
            "retroactive_premium_adjustment_cents": 0,
            "revision_of_sheet_id": None,
            "revision_reason": None,
            "_created_by": None,
        }
    )
    db["experience_mod_sheets"][sheet["id"]] = sheet
    group["combined_mod_sheet_id"] = sheet["id"]
    touch(group)
    return ok_object(ser_ownership_change(rec))


@app.route("/ownership-changes/<changeId>/not_combined", methods=["POST"])
def not_combined_ownership_change(changeId):
    require_roles("BureauAnalyst")
    rec = get_or_404("ownership_changes", changeId)
    if rec["status"] != "PENDING":
        raise ApiError("ERR_INVALID_STATE", 409, f"change is {rec['status']}, not PENDING")
    rec["status"] = "NOT_COMBINED"
    touch(rec)
    return ok_object(ser_ownership_change(rec))


@app.route("/ownership-changes/<changeId>/reverse", methods=["POST"])
def reverse_ownership_change(changeId):
    require_roles("BureauAnalyst")
    rec = get_or_404("ownership_changes", changeId)
    if rec["status"] != "COMBINED":
        raise ApiError(
            "ERR_INVALID_STATE", 409, f"change is {rec['status']}, not COMBINED"
        )
    group = db["combinability_groups"].get(rec.get("combinability_group_id"))
    if group is None or group["status"] != "ACTIVE":
        raise ApiError(
            "ERR_INVALID_STATE", 409, "combinability group is not ACTIVE"
        )
    rec["status"] = "REVERSED"
    touch(rec)
    group["status"] = "DISSOLVED"
    touch(group)
    # Void combined sheet
    sheet_id = group.get("combined_mod_sheet_id")
    if sheet_id:
        sheet = db["experience_mod_sheets"].get(sheet_id)
        if sheet is not None:
            sheet["status"] = "REVISED"
            sheet["revision_reason"] = "CLASS_CODE_CHANGE"
            touch(sheet)
    return ok_object(ser_ownership_change(rec))


# ---------------------------------------------------------------------------
# CombinabilityGroups
# ---------------------------------------------------------------------------


@app.route("/combinability-groups/<groupId>", methods=["GET"])
def get_combinability_group(groupId):
    require_roles(*ROLES)
    rec = get_or_404("combinability_groups", groupId)
    return ok_object(ser_combinability_group(rec))


@app.route("/combinability-groups", methods=["GET"])
def list_combinability_groups():
    require_roles(*ROLES)
    status = request.args.get("status")
    created_from_change_id = request.args.get("created_from_change_id")
    combined_mod_sheet_id = request.args.get("combined_mod_sheet_id")
    items = list(db["combinability_groups"].values())
    if status:
        items = [g for g in items if g["status"] == status]
    if created_from_change_id:
        items = [g for g in items if g.get("created_from_change_id") == created_from_change_id]
    if combined_mod_sheet_id:
        items = [g for g in items if g.get("combined_mod_sheet_id") == combined_mod_sheet_id]
    items = sort_by_created(items)
    return ok_array([ser_combinability_group(g) for g in items])


# ---------------------------------------------------------------------------
# AssignedRiskEnrollments
# ---------------------------------------------------------------------------


@app.route("/assigned-risk-enrollments", methods=["POST"])
def create_assigned_risk_enrollment():
    require_roles("PoolAdministrator")
    data = body()
    employer_id = req_str(data, "employer_id")
    state_code = req_str(data, "state_code")
    effective_date = req_date(data, "effective_date")
    expiration_date = req_date(data, "expiration_date")
    estimated_annual_premium_cents = req_int(data, "estimated_annual_premium_cents")
    employer = get_or_404("employers", employer_id)
    eff = parse_date(effective_date)
    exp = parse_date(expiration_date)
    if eff >= exp:
        raise ApiError(
            "ERR_TEMPORAL_CONFLICT",
            409,
            "effective_date must be before expiration_date",
        )
    rec = new_record()
    rec.update(
        {
            "employer_id": employer_id,
            "state_code": state_code,
            "effective_date": effective_date,
            "expiration_date": expiration_date,
            "estimated_annual_premium_cents": estimated_annual_premium_cents,
            "status": "PENDING",
            "assigned_carrier_id": None,
            "take_out_credit_cents": 0,
            "exit_date": None,
            "exit_reason": None,
        }
    )
    db["assigned_risk_enrollments"][rec["id"]] = rec
    return ok_object(ser_assigned_risk_enrollment(rec), code=201)


@app.route("/assigned-risk-enrollments/<enrollmentId>", methods=["GET"])
def get_assigned_risk_enrollment(enrollmentId):
    require_roles(*ROLES)
    rec = get_or_404("assigned_risk_enrollments", enrollmentId)
    return ok_object(ser_assigned_risk_enrollment(rec))


@app.route("/assigned-risk-enrollments", methods=["GET"])
def list_assigned_risk_enrollments():
    require_roles(*ROLES)
    employer_id = request.args.get("employer_id")
    carrier_id = request.args.get("carrier_id")
    status = request.args.get("status")
    assigned_carrier_id = request.args.get("assigned_carrier_id")
    items = list(db["assigned_risk_enrollments"].values())
    if employer_id:
        items = [e for e in items if e["employer_id"] == employer_id]
    if carrier_id:
        items = [e for e in items if e.get("assigned_carrier_id") == carrier_id]
    if status:
        items = [e for e in items if e["status"] == status]
    if assigned_carrier_id:
        items = [e for e in items if e.get("assigned_carrier_id") == assigned_carrier_id]
    items = sort_by_created(items)
    return ok_array([ser_assigned_risk_enrollment(e) for e in items])


@app.route("/assigned-risk-enrollments/<enrollmentId>/assign", methods=["POST"])
def assign_assigned_risk_enrollment(enrollmentId):
    require_roles("PoolAdministrator")
    data = body()
    carrier_id = req_str(data, "carrier_id")
    rec = get_or_404("assigned_risk_enrollments", enrollmentId)
    if rec["status"] != "PENDING":
        raise ApiError(
            "ERR_INVALID_STATE", 409, f"enrollment is {rec['status']}, not PENDING"
        )
    employer = db["employers"].get(rec["employer_id"])
    if employer is None:
        raise ApiError("ERR_NOT_FOUND", 404, "employer not found")
    if employer["status"] != "ACTIVE":
        raise ApiError("ERR_EMPLOYER_INACTIVE", 409, "employer is not ACTIVE")
    carrier = get_or_404("carriers", carrier_id)
    if carrier["status"] != "ACTIVE":
        raise ApiError("ERR_CARRIER_NOT_ACTIVE", 409, "carrier is not ACTIVE")
    new_load = carrier["assigned_risk_current_load_cents"] + rec["estimated_annual_premium_cents"]
    if new_load > carrier["assigned_risk_quota_cents"]:
        raise ApiError(
            "ERR_ASSIGNED_RISK_QUOTA_EXCEEDED",
            409,
            "carrier assigned-risk quota would be exceeded",
        )
    rec["status"] = "ACTIVE"
    rec["assigned_carrier_id"] = carrier_id
    touch(rec)
    carrier["assigned_risk_current_load_cents"] = new_load
    touch(carrier)
    return ok_object(ser_assigned_risk_enrollment(rec))


@app.route("/assigned-risk-enrollments/<enrollmentId>/cancel", methods=["POST"])
def cancel_assigned_risk_enrollment(enrollmentId):
    require_roles("PoolAdministrator")
    rec = get_or_404("assigned_risk_enrollments", enrollmentId)
    if rec["status"] != "ACTIVE":
        raise ApiError(
            "ERR_INVALID_STATE", 409, f"enrollment is {rec['status']}, not ACTIVE"
        )
    carrier_id = rec.get("assigned_carrier_id")
    if carrier_id:
        carrier = db["carriers"].get(carrier_id)
        if carrier is not None:
            carrier["assigned_risk_current_load_cents"] = max(
                0, carrier["assigned_risk_current_load_cents"] - rec["estimated_annual_premium_cents"]
            )
            touch(carrier)
    rec["status"] = "CANCELLED"
    rec["exit_reason"] = "CANCELLED"
    touch(rec)
    return ok_object(ser_assigned_risk_enrollment(rec))


# ---------------------------------------------------------------------------
# AssignedRiskTakeOuts
# ---------------------------------------------------------------------------


def compute_take_out_credit(enrollment, exit_date_str):
    eff = parse_date(enrollment["effective_date"])
    exp = parse_date(enrollment["expiration_date"])
    exit_d = parse_date(exit_date_str)
    total_days = (exp - eff).days + 1
    earned_days = (exit_d - eff).days
    remaining_days = total_days - earned_days
    if remaining_days < 0:
        remaining_days = 0
    if total_days <= 0:
        return 0
    prem = dec(enrollment["estimated_annual_premium_cents"])
    short_rate_factor = round_half_up_dec(
        dec("0.9") * dec(remaining_days) / dec(total_days), 4
    )
    credit = round_half_up_int(prem * short_rate_factor * dec("0.5"))
    return credit


@app.route("/assigned-risk-take-outs", methods=["POST"])
def create_assigned_risk_take_out():
    c = require_roles("VoluntaryCarrierRepresentative")
    data = body()
    enrollment_id = req_str(data, "enrollment_id")
    voluntary_carrier_id = req_str(data, "voluntary_carrier_id")
    exit_date = req_date(data, "exit_date")
    expected_enrollment_version = data.get("expected_enrollment_version")
    enrollment = get_or_404("assigned_risk_enrollments", enrollment_id)
    voluntary_carrier = get_or_404("carriers", voluntary_carrier_id)
    if enrollment["status"] != "ACTIVE":
        raise ApiError(
            "ERR_INVALID_STATE", 409, f"enrollment is {enrollment['status']}, not ACTIVE"
        )
    if voluntary_carrier["status"] != "ACTIVE":
        raise ApiError("ERR_CARRIER_NOT_ACTIVE", 409, "voluntary carrier is not ACTIVE")
    if expected_enrollment_version is not None:
        if not isinstance(expected_enrollment_version, int) or isinstance(
            expected_enrollment_version, bool
        ):
            raise ApiError(
                "ERR_INVALID_REQUEST",
                400,
                "expected_enrollment_version must be an integer",
            )
        if expected_enrollment_version != enrollment["version"]:
            raise ApiError(
                "ERR_STALE_VERSION",
                412,
                "enrollment version does not match expected_enrollment_version",
            )
    rec = new_record()
    rec.update(
        {
            "enrollment_id": enrollment_id,
            "voluntary_carrier_id": voluntary_carrier_id,
            "exit_date": exit_date,
            "status": "PENDING",
            "credit_cents": 0,
            "approved_at": None,
            "_created_by": c["id"],
        }
    )
    db["assigned_risk_take_outs"][rec["id"]] = rec
    # Place hold on carrier's pool load: subtract estimated premium
    assigned_carrier_id = enrollment.get("assigned_carrier_id")
    if assigned_carrier_id:
        carrier = db["carriers"].get(assigned_carrier_id)
        if carrier is not None:
            carrier["assigned_risk_current_load_cents"] = max(
                0,
                carrier["assigned_risk_current_load_cents"]
                - enrollment["estimated_annual_premium_cents"],
            )
            touch(carrier)
    # Bump enrollment version for OCC
    touch(enrollment)
    return ok_object(ser_assigned_risk_take_out(rec), code=201)


@app.route("/assigned-risk-take-outs/<takeOutId>", methods=["GET"])
def get_assigned_risk_take_out(takeOutId):
    require_roles(*ROLES)
    rec = get_or_404("assigned_risk_take_outs", takeOutId)
    return ok_object(ser_assigned_risk_take_out(rec))


@app.route("/assigned-risk-take-outs", methods=["GET"])
def list_assigned_risk_take_outs():
    require_roles(*ROLES)
    enrollment_id = request.args.get("enrollment_id")
    voluntary_carrier_id = request.args.get("voluntary_carrier_id")
    status = request.args.get("status")
    items = list(db["assigned_risk_take_outs"].values())
    if enrollment_id:
        items = [t for t in items if t["enrollment_id"] == enrollment_id]
    if voluntary_carrier_id:
        items = [t for t in items if t["voluntary_carrier_id"] == voluntary_carrier_id]
    if status:
        items = [t for t in items if t["status"] == status]
    items = sort_by_created(items)
    return ok_array([ser_assigned_risk_take_out(t) for t in items])


@app.route("/assigned-risk-take-outs/<takeOutId>/approve", methods=["POST"])
def approve_assigned_risk_take_out(takeOutId):
    require_roles("PoolAdministrator")
    rec = get_or_404("assigned_risk_take_outs", takeOutId)
    if rec["status"] != "PENDING":
        raise ApiError(
            "ERR_INVALID_STATE", 409, f"take-out is {rec['status']}, not PENDING"
        )
    enrollment = db["assigned_risk_enrollments"].get(rec["enrollment_id"])
    if enrollment is None:
        raise ApiError("ERR_NOT_FOUND", 404, "enrollment not found")
    if enrollment["status"] != "ACTIVE":
        raise ApiError(
            "ERR_INVALID_STATE",
            409,
            f"enrollment is {enrollment['status']}, not ACTIVE",
        )
    bureau = get_bureau_or_404()
    credit = compute_take_out_credit(enrollment, rec["exit_date"])
    # Underwriting review required if credit >= threshold
    if credit >= bureau["underwriting_threshold_cents"]:
        # Look for an APPROVED UnderwritingReview with subject_type TAKE_OUT and subject_id=this take-out
        has_approved = False
        for r in db["underwriting_reviews"].values():
            if (
                r["subject_type"] == "TAKE_OUT"
                and r["subject_id"] == rec["id"]
                and r["status"] == "APPROVED"
            ):
                has_approved = True
                break
        if not has_approved:
            # Auto-create a PENDING review to make the requirement explicit, then fail
            existing_pending = any(
                r["subject_type"] == "TAKE_OUT"
                and r["subject_id"] == rec["id"]
                and r["status"] == "PENDING"
                for r in db["underwriting_reviews"].values()
            )
            if not existing_pending:
                review = new_record()
                review.update(
                    {
                        "subject_type": "TAKE_OUT",
                        "subject_id": rec["id"],
                        "status": "PENDING",
                        "reviewer_id": None,
                        "decided_at": None,
                        "_created_by": rec.get("_created_by"),
                    }
                )
                db["underwriting_reviews"][review["id"]] = review
            raise ApiError(
                "ERR_UNDERWRITING_REVIEW_REQUIRED",
                409,
                "an approved underwriting review is required for this take-out",
            )
    # Approve
    rec["status"] = "APPROVED"
    rec["credit_cents"] = credit
    rec["approved_at"] = wall_now_iso()
    touch(rec)
    enrollment["status"] = "EXITED"
    enrollment["exit_reason"] = "TAKE_OUT"
    enrollment["exit_date"] = rec["exit_date"]
    enrollment["take_out_credit_cents"] = credit
    touch(enrollment)
    return ok_object(ser_assigned_risk_take_out(rec))


@app.route("/assigned-risk-take-outs/<takeOutId>/reject", methods=["POST"])
def reject_assigned_risk_take_out(takeOutId):
    require_roles("PoolAdministrator")
    rec = get_or_404("assigned_risk_take_outs", takeOutId)
    if rec["status"] != "PENDING":
        raise ApiError(
            "ERR_INVALID_STATE", 409, f"take-out is {rec['status']}, not PENDING"
        )
    enrollment = db["assigned_risk_enrollments"].get(rec["enrollment_id"])
    # Release hold: restore carrier load
    if enrollment is not None:
        assigned_carrier_id = enrollment.get("assigned_carrier_id")
        if assigned_carrier_id:
            carrier = db["carriers"].get(assigned_carrier_id)
            if carrier is not None:
                carrier["assigned_risk_current_load_cents"] = (
                    carrier["assigned_risk_current_load_cents"]
                    + enrollment["estimated_annual_premium_cents"]
                )
                touch(carrier)
    rec["status"] = "REJECTED"
    touch(rec)
    return ok_object(ser_assigned_risk_take_out(rec))


# ---------------------------------------------------------------------------
# UnderwritingReviews
# ---------------------------------------------------------------------------


@app.route("/underwriting-reviews/<reviewId>", methods=["GET"])
def get_underwriting_review(reviewId):
    require_roles(*ROLES)
    rec = get_or_404("underwriting_reviews", reviewId)
    return ok_object(ser_underwriting_review(rec))


def _decide_underwriting_review(reviewId, decision):
    c = require_roles("Underwriter")
    rec = get_or_404("underwriting_reviews", reviewId)
    if rec["status"] != "PENDING":
        raise ApiError(
            "ERR_INVALID_STATE", 409, f"review is {rec['status']}, not PENDING"
        )
    # Segregation of duties: reviewer must not be the same user who created the subject
    subject_creator = None
    if rec["subject_type"] == "MOD_SHEET":
        sheet = db["experience_mod_sheets"].get(rec["subject_id"])
        if sheet is not None:
            subject_creator = sheet.get("_created_by")
    elif rec["subject_type"] == "TAKE_OUT":
        to = db["assigned_risk_take_outs"].get(rec["subject_id"])
        if to is not None:
            subject_creator = to.get("_created_by")
    elif rec["subject_type"] == "CLASS_ASSIGNMENT":
        ca = db["class_assignments"].get(rec["subject_id"])
        if ca is not None:
            subject_creator = ca.get("_created_by")
    if subject_creator is not None and subject_creator == c["id"]:
        raise ApiError(
            "ERR_SEGREGATION_OF_DUTIES",
            409,
            "same user cannot create and approve the subject",
        )
    rec["status"] = decision
    rec["reviewer_id"] = c["id"]
    rec["decided_at"] = wall_now_iso()
    touch(rec)
    # Cascade: rejecting a TAKE_OUT review moves the take-out to REJECTED
    if decision == "REJECTED" and rec["subject_type"] == "TAKE_OUT":
        to = db["assigned_risk_take_outs"].get(rec["subject_id"])
        if to is not None and to["status"] == "PENDING":
            enrollment = db["assigned_risk_enrollments"].get(to["enrollment_id"])
            if enrollment is not None:
                assigned_carrier_id = enrollment.get("assigned_carrier_id")
                if assigned_carrier_id:
                    carrier = db["carriers"].get(assigned_carrier_id)
                    if carrier is not None:
                        carrier["assigned_risk_current_load_cents"] = (
                            carrier["assigned_risk_current_load_cents"]
                            + enrollment["estimated_annual_premium_cents"]
                        )
                        touch(carrier)
            to["status"] = "REJECTED"
            touch(to)
    return rec


@app.route("/underwriting-reviews/<reviewId>/approve", methods=["POST"])
def approve_underwriting_review(reviewId):
    rec = _decide_underwriting_review(reviewId, "APPROVED")
    return ok_object(ser_underwriting_review(rec))


@app.route("/underwriting-reviews/<reviewId>/reject", methods=["POST"])
def reject_underwriting_review(reviewId):
    rec = _decide_underwriting_review(reviewId, "REJECTED")
    return ok_object(ser_underwriting_review(rec))


# ---------------------------------------------------------------------------
# Reverse-reachability GETs (FK traversal)
# ---------------------------------------------------------------------------


@app.route("/employers/<employerId>/policies", methods=["GET"])
def list_employer_policies(employerId):
    require_roles(*ROLES)
    get_or_404("employers", employerId)
    items = [p for p in db["policies"].values() if p["employer_id"] == employerId]
    items = sort_by_created(items)
    return ok_array([ser_policy(p) for p in items])


@app.route("/policies/<policyId>/unit-stat-reports", methods=["GET"])
def list_policy_unit_stat_reports(policyId):
    require_roles(*ROLES)
    get_or_404("policies", policyId)
    items = [r for r in db["unit_stat_reports"].values() if r["policy_id"] == policyId]
    items = sort_by_created(items)
    return ok_array([ser_unit_stat_report(r) for r in items])


@app.route("/employers/<employerId>/class-assignments", methods=["GET"])
def list_employer_class_assignments(employerId):
    require_roles(*ROLES)
    get_or_404("employers", employerId)
    items = [a for a in db["class_assignments"].values() if a["employer_id"] == employerId]
    items = sort_by_created(items)
    return ok_array([ser_class_assignment(a) for a in items])


@app.route("/class-assignments/<classAssignmentId>/inspections", methods=["GET"])
def list_assignment_inspections(classAssignmentId):
    require_roles(*ROLES)
    get_or_404("class_assignments", classAssignmentId)
    items = [
        i for i in db["inspections"].values() if i["class_assignment_id"] == classAssignmentId
    ]
    items = sort_by_created(items)
    return ok_array([ser_inspection(i) for i in items])


@app.route("/class-assignments/<classAssignmentId>/disputes", methods=["GET"])
def list_assignment_disputes(classAssignmentId):
    require_roles(*ROLES)
    get_or_404("class_assignments", classAssignmentId)
    items = [
        d
        for d in db["class_assignment_disputes"].values()
        if d["class_assignment_id"] == classAssignmentId
    ]
    items = sort_by_created(items)
    return ok_array([ser_class_assignment_dispute(d) for d in items])


@app.route("/employers/<employerId>/experience-mod-sheets", methods=["GET"])
def list_employer_mod_sheets(employerId):
    require_roles(*ROLES)
    get_or_404("employers", employerId)
    items = [
        s for s in db["experience_mod_sheets"].values() if s["employer_id"] == employerId
    ]
    items = sort_by_created(items)
    return ok_array([ser_experience_mod_sheet(s) for s in items])


@app.route("/experience-mod-sheets/<modSheetId>/appeals", methods=["GET"])
def list_mod_sheet_appeals(modSheetId):
    require_roles(*ROLES)
    get_or_404("experience_mod_sheets", modSheetId)
    items = [a for a in db["mod_appeals"].values() if a["mod_sheet_id"] == modSheetId]
    items = sort_by_created(items)
    return ok_array([ser_mod_appeal(a) for a in items])


@app.route("/employers/<employerId>/ownership-changes", methods=["GET"])
def list_employer_ownership_changes(employerId):
    require_roles(*ROLES)
    get_or_404("employers", employerId)
    items = [c for c in db["ownership_changes"].values() if c["employer_id"] == employerId]
    items = sort_by_created(items)
    return ok_array([ser_ownership_change(c) for c in items])


@app.route("/employers/<employerId>/assigned-risk-enrollments", methods=["GET"])
def list_employer_enrollments(employerId):
    require_roles(*ROLES)
    get_or_404("employers", employerId)
    items = [
        e for e in db["assigned_risk_enrollments"].values() if e["employer_id"] == employerId
    ]
    items = sort_by_created(items)
    return ok_array([ser_assigned_risk_enrollment(e) for e in items])


@app.route("/assigned-risk-enrollments/<enrollmentId>/take-outs", methods=["GET"])
def list_enrollment_take_outs(enrollmentId):
    require_roles(*ROLES)
    get_or_404("assigned_risk_enrollments", enrollmentId)
    items = [
        t for t in db["assigned_risk_take_outs"].values() if t["enrollment_id"] == enrollmentId
    ]
    items = sort_by_created(items)
    return ok_array([ser_assigned_risk_take_out(t) for t in items])


@app.route("/carriers/<carrierId>/assigned-risk-enrollments", methods=["GET"])
def list_carrier_enrollments(carrierId):
    require_roles(*ROLES)
    get_or_404("carriers", carrierId)
    items = [
        e
        for e in db["assigned_risk_enrollments"].values()
        if e.get("assigned_carrier_id") == carrierId
    ]
    items = sort_by_created(items)
    return ok_array([ser_assigned_risk_enrollment(e) for e in items])


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port)
