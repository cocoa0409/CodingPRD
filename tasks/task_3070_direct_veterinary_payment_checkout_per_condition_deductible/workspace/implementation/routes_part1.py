"""Route handlers, part 1: clock, filings, hospitals, policies, records."""
from flask import Blueprint, request

import core
from core import (
    store, fail, ok, body, req_field, req_str, req_int, opt_version,
    require_roles, paginate, sort_items, public, new_entity, touch,
    parse_dt, parse_date, midnight, to_decimal, now_iso,
)
import logic

bp = Blueprint("part1", __name__)

FILING_FIELDS = [
    "id", "territory_code", "state_code", "species", "base_monthly_premium_cents",
    "age_band_multipliers", "filing_effective_date", "regulator_reference", "status",
    "filed_at", "effective_at", "created_at", "updated_at", "version",
]
HOSPITAL_FIELDS = [
    "id", "legal_name", "territory_code", "bank_account_ref", "checkout_software_version",
    "training_completed_at", "status", "running_ledger_balance_cents",
    "created_at", "updated_at", "version",
]
POLICY_FIELDS = [
    "id", "owner_name", "pet_name", "species", "breed", "pet_date_of_birth",
    "territory_code", "coverage_start", "per_condition_deductible_cents",
    "reimbursement_rate", "enrollment_status", "lifecycle_status",
    "current_monthly_premium_cents", "filed_base_cents", "applied_filing_id",
    "next_birthday", "injury_waiting_end", "illness_waiting_end",
    "created_at", "updated_at", "version",
]
RECORD_FIELDS = [
    "id", "policy_id", "hospital_id", "record_type", "recorded_at",
    "diagnosis_code", "notes", "appeal_id", "created_at",
]
REPORT_FIELDS = [
    "id", "hospital_id", "period_start", "period_end",
    "expected_cents", "actual_cents", "discrepancy_cents", "status", "created_at",
]


def filing_view(f):
    logic.sweep_filing(f)
    return public(f, FILING_FIELDS)


def hospital_view(h):
    return public(h, HOSPITAL_FIELDS)


def policy_view(p):
    logic.sweep_policy(p)
    return public(p, POLICY_FIELDS)


def get_filing_or_404(fid):
    f = store.filings.get(fid)
    if f is None:
        fail("ERR_FILING_NOT_FOUND", 404, "Rate filing not found")
    return f


def get_hospital_or_404(hid):
    h = store.hospitals.get(hid)
    if h is None:
        fail("ERR_HOSPITAL_NOT_FOUND", 404, "Hospital not found")
    return h


def get_policy_or_404(pid):
    p = store.policies.get(pid)
    if p is None:
        fail("ERR_POLICY_NOT_FOUND", 404, "Policy not found")
    return p


def get_record_or_404(rid):
    r = store.records.get(rid)
    if r is None:
        fail("ERR_RECORD_NOT_FOUND", 404, "Medical record not found")
    return r


def get_report_or_404(rid):
    r = store.reports.get(rid)
    if r is None:
        fail("ERR_REPORT_NOT_FOUND", 404, "Reconciliation report not found")
    return r


# ---------------------------------------------------------------------------
# Clock
# ---------------------------------------------------------------------------


@bp.post("/_clock/set_current_utc")
def set_clock():
    require_roles("PlatformAdmin")
    data = body()
    dt = parse_dt(req_field(data, "to_iso8601"))
    if dt is None:
        fail(core.ERR_INVALID_REQUEST, 400, "to_iso8601 must be an ISO 8601 timestamp")
    store.clock = dt
    logic.run_clock_sweep()
    return ok({"current_utc": now_iso()})


# ---------------------------------------------------------------------------
# Rate filings
# ---------------------------------------------------------------------------


@bp.post("/rate-filings")
def create_filing():
    require_roles("RateFilingAdmin")
    data = body()
    f = new_entity()
    species = req_str(data, "species")
    if species not in ("DOG", "CAT"):
        fail(core.ERR_INVALID_REQUEST, 400, "species must be DOG or CAT")
    eff = parse_date(req_field(data, "filing_effective_date"))
    if eff is None:
        fail(core.ERR_INVALID_REQUEST, 400, "filing_effective_date must be an ISO date")
    mults = req_field(data, "age_band_multipliers")
    if not isinstance(mults, dict):
        fail(core.ERR_INVALID_REQUEST, 400, "age_band_multipliers must be an object")
    f.update({
        "territory_code": req_str(data, "territory_code"),
        "state_code": req_str(data, "state_code"),
        "species": species,
        "base_monthly_premium_cents": req_int(data, "base_monthly_premium_cents", 0),
        "age_band_multipliers": mults,
        "filing_effective_date": eff.isoformat(),
        "regulator_reference": req_str(data, "regulator_reference"),
        "status": "DRAFT",
        "filed_at": None,
        "effective_at": None,
        "_eff_date": eff,
    })
    store.filings[f["id"]] = f
    return ok(filing_view(f), 201)


@bp.get("/rate-filings")
def list_filings():
    require_roles("PlatformAdmin", "RateFilingAdmin", "ClaimsAdjuster")
    items = list(store.filings.values())
    for f in items:
        logic.sweep_filing(f)
    tc = request.args.get("territory_code")
    sp = request.args.get("species")
    st = request.args.get("status")
    if tc is not None:
        items = [f for f in items if f["territory_code"] == tc]
    if sp is not None:
        items = [f for f in items if f["species"] == sp]
    if st is not None:
        items = [f for f in items if f["status"] == st]
    items = sort_items(items)
    page, meta = paginate(items)
    return ok([public(f, FILING_FIELDS) for f in page], 200, meta)


@bp.get("/rate-filings/<filingId>")
def get_filing(filingId):
    require_roles("PlatformAdmin", "RateFilingAdmin", "ClaimsAdjuster")
    return ok(filing_view(get_filing_or_404(filingId)))


@bp.post("/rate-filings/<filingId>/file")
def file_filing(filingId):
    require_roles("RateFilingAdmin")
    f = get_filing_or_404(filingId)
    logic.sweep_filing(f)
    if f["status"] != "DRAFT":
        fail("ERR_FILING_NOT_FILABLE", 409, "Only a DRAFT filing can be filed")
    if f["_eff_date"] < store.clock.date():
        fail("ERR_FILING_RETROACTIVE", 422, "filing_effective_date is in the past")
    f["status"] = "FILED"
    f["filed_at"] = now_iso()
    touch(f)
    return ok(filing_view(f))


# ---------------------------------------------------------------------------
# Hospitals
# ---------------------------------------------------------------------------


@bp.post("/hospitals")
def create_hospital():
    require_roles("PlatformAdmin")
    data = body()
    h = new_entity()
    h.update({
        "legal_name": req_str(data, "legal_name"),
        "territory_code": req_str(data, "territory_code"),
        "bank_account_ref": req_str(data, "bank_account_ref"),
        "checkout_software_version": req_str(data, "checkout_software_version"),
        "training_completed_at": None,
        "status": "APPLIED",
        "running_ledger_balance_cents": 0,
    })
    store.hospitals[h["id"]] = h
    return ok(hospital_view(h), 201)


@bp.get("/hospitals")
def list_hospitals():
    require_roles("PlatformAdmin", "ClaimsAdjuster", "HospitalStaff")
    items = list(store.hospitals.values())
    st = request.args.get("status")
    tc = request.args.get("territory_code")
    if st is not None:
        items = [h for h in items if h["status"] == st]
    if tc is not None:
        items = [h for h in items if h["territory_code"] == tc]
    items = sort_items(items)
    page, meta = paginate(items)
    return ok([hospital_view(h) for h in page], 200, meta)


@bp.get("/hospitals/<hospitalId>")
def get_hospital(hospitalId):
    require_roles("PlatformAdmin", "ClaimsAdjuster", "HospitalStaff")
    return ok(hospital_view(get_hospital_or_404(hospitalId)))


@bp.post("/hospitals/<hospitalId>/approve")
def approve_hospital(hospitalId):
    require_roles("PlatformAdmin")
    h = get_hospital_or_404(hospitalId)
    data = body()
    expected = opt_version(data, "expected_hospital_version")
    if expected != h["version"]:
        fail("ERR_STALE_HOSPITAL_VERSION", 412, "Stale hospital version")
    if h["status"] != "APPLIED":
        fail("ERR_HOSPITAL_NOT_APPROVABLE", 409, "Hospital is not in APPLIED status")
    h["status"] = "APPROVED"
    touch(h)
    return ok(hospital_view(h))


@bp.post("/hospitals/<hospitalId>/training-complete")
def training_complete(hospitalId):
    uid, _ = require_roles("HospitalStaff")
    h = get_hospital_or_404(hospitalId)
    if h["status"] != "APPROVED":
        fail(core.ERR_INVALID_STATE, 409, "Hospital is not in APPROVED status")
    if uid != h["id"]:
        fail(core.ERR_UNAUTHORIZED, 403, "Staff may only act for their own hospital")
    h["status"] = "ACTIVE"
    h["training_completed_at"] = now_iso()
    touch(h)
    return ok(hospital_view(h))


@bp.post("/hospitals/<hospitalId>/suspend")
def suspend_hospital(hospitalId):
    require_roles("PlatformAdmin")
    h = get_hospital_or_404(hospitalId)
    if h["status"] != "ACTIVE":
        fail(core.ERR_INVALID_STATE, 409, "Hospital is not in ACTIVE status")
    logic.suspend_cascade(h)
    h["status"] = "SUSPENDED"
    touch(h)
    return ok(hospital_view(h))


@bp.post("/hospitals/<hospitalId>/reinstate")
def reinstate_hospital(hospitalId):
    require_roles("PlatformAdmin")
    h = get_hospital_or_404(hospitalId)
    if h["status"] != "SUSPENDED":
        fail(core.ERR_INVALID_STATE, 409, "Hospital is not in SUSPENDED status")
    h["status"] = "ACTIVE"
    touch(h)
    return ok(hospital_view(h))


# ---------------------------------------------------------------------------
# Policies
# ---------------------------------------------------------------------------


@bp.post("/policies")
def create_policy():
    require_roles("PetOwner", "PlatformAdmin")
    data = body()
    species = req_str(data, "species")
    if species not in ("DOG", "CAT"):
        fail(core.ERR_INVALID_REQUEST, 400, "species must be DOG or CAT")
    dob = parse_date(req_field(data, "pet_date_of_birth"))
    if dob is None:
        fail(core.ERR_INVALID_REQUEST, 400, "pet_date_of_birth must be an ISO date")
    cs = parse_date(req_field(data, "coverage_start"))
    if cs is None:
        fail(core.ERR_INVALID_REQUEST, 400, "coverage_start must be an ISO date")
    rate_raw = req_field(data, "reimbursement_rate")
    if isinstance(rate_raw, bool) or not isinstance(rate_raw, (int, float)):
        fail(core.ERR_INVALID_REQUEST, 400, "reimbursement_rate must be a number")
    rate = to_decimal(rate_raw)
    if rate is None or rate <= 0 or rate > 1:
        fail(core.ERR_INVALID_REQUEST, 400, "reimbursement_rate must be in (0, 1]")
    territory = req_str(data, "territory_code")
    filing = logic.select_filing(territory, species, cs)
    if filing is None:
        fail("ERR_RATE_NOT_FILED", 422,
             "No EFFECTIVE rate filing for this territory and species at coverage_start")
    p = new_entity()
    base = filing["base_monthly_premium_cents"]
    nb = logic.compute_next_birthday(dob, cs)
    cs_mid = midnight(cs)
    from datetime import timedelta
    p.update({
        "owner_name": req_str(data, "owner_name"),
        "pet_name": req_str(data, "pet_name"),
        "species": species,
        "breed": req_str(data, "breed"),
        "pet_date_of_birth": dob.isoformat(),
        "territory_code": territory,
        "coverage_start": cs.isoformat(),
        "per_condition_deductible_cents": req_int(data, "per_condition_deductible_cents", 0),
        "reimbursement_rate": rate_raw,
        "enrollment_status": "INJURY_WAITING",
        "lifecycle_status": "ACTIVE",
        "filed_base_cents": base,
        "applied_filing_id": filing["id"],
        "current_monthly_premium_cents": logic.compute_premium(filing, dob, cs),
        "next_birthday": nb.isoformat(),
        "injury_waiting_end": core.fmt_ts(cs_mid + timedelta(days=logic.INJURY_WAITING_DAYS)),
        "illness_waiting_end": core.fmt_ts(cs_mid + timedelta(days=logic.ILLNESS_WAITING_DAYS)),
        "_dob": dob,
        "_coverage_start": cs,
        "_next_bday": nb,
        "_inj_end": cs_mid + timedelta(days=logic.INJURY_WAITING_DAYS),
        "_ill_end": cs_mid + timedelta(days=logic.ILLNESS_WAITING_DAYS),
    })
    p["injury_waiting_end"] = core.fmt_ts(p["_inj_end"])
    p["illness_waiting_end"] = core.fmt_ts(p["_ill_end"])
    store.policies[p["id"]] = p
    logic.sweep_policy(p)
    return ok(policy_view(p), 201)


@bp.get("/policies")
def list_policies():
    require_roles("PlatformAdmin", "ClaimsAdjuster", "PetOwner")
    items = list(store.policies.values())
    for p in items:
        logic.sweep_policy(p)
    tc = request.args.get("territory_code")
    sp = request.args.get("species")
    ls = request.args.get("lifecycle_status")
    es = request.args.get("enrollment_status")
    af = request.args.get("applied_filing_id")
    if tc is not None:
        items = [p for p in items if p["territory_code"] == tc]
    if sp is not None:
        items = [p for p in items if p["species"] == sp]
    if ls is not None:
        items = [p for p in items if p["lifecycle_status"] == ls]
    if es is not None:
        items = [p for p in items if p["enrollment_status"] == es]
    if af is not None:
        items = [p for p in items if p["applied_filing_id"] == af]
    items = sort_items(items)
    page, meta = paginate(items)
    return ok([public(p, POLICY_FIELDS) for p in page], 200, meta)


@bp.get("/policies/<policyId>")
def get_policy(policyId):
    require_roles("PlatformAdmin", "ClaimsAdjuster", "PetOwner", "HospitalStaff")
    return ok(policy_view(get_policy_or_404(policyId)))


@bp.post("/policies/<policyId>/cancel")
def cancel_policy(policyId):
    uid, _ = require_roles("PetOwner")
    p = get_policy_or_404(policyId)
    logic.sweep_policy(p)
    if p["lifecycle_status"] != "ACTIVE":
        fail(core.ERR_INVALID_STATE, 409, "Policy is not ACTIVE")
    if uid != p["id"]:
        fail(core.ERR_UNAUTHORIZED, 403, "Owner may cancel only their own policy")
    p["lifecycle_status"] = "CANCELLED"
    touch(p)
    return ok(policy_view(p))


@bp.post("/policies/<policyId>/mark-lapsed")
def lapse_policy(policyId):
    require_roles("PlatformAdmin")
    p = get_policy_or_404(policyId)
    logic.sweep_policy(p)
    if p["lifecycle_status"] != "ACTIVE":
        fail(core.ERR_INVALID_STATE, 409, "Policy is not ACTIVE")
    p["lifecycle_status"] = "LAPSED"
    touch(p)
    return ok(policy_view(p))


@bp.post("/policies/<policyId>/recalculate-premium")
def recalc_premium(policyId):
    require_roles("PlatformAdmin")
    p = get_policy_or_404(policyId)
    logic.sweep_policy(p)
    if p["lifecycle_status"] != "ACTIVE":
        fail(core.ERR_INVALID_STATE, 409, "Policy is not ACTIVE")
    if store.clock.date() < p["_next_bday"]:
        fail(core.ERR_INVALID_STATE, 409, "Current date is before next_birthday")
    logic.do_premium_recalc(p)
    return ok(policy_view(p))


# ---------------------------------------------------------------------------
# Medical records
# ---------------------------------------------------------------------------


@bp.post("/policies/<policyId>/medical-records")
def upload_record(policyId):
    require_roles("HospitalStaff")
    p = get_policy_or_404(policyId)
    data = body()
    hid = req_str(data, "hospital_id")
    get_hospital_or_404(hid)
    rtype = req_str(data, "record_type")
    if rtype not in ("EXAM", "LAB", "IMAGING", "PROCEDURE", "PRESCRIPTION"):
        fail(core.ERR_INVALID_REQUEST, 400, "Invalid record_type")
    rdt = parse_dt(req_field(data, "recorded_at"))
    if rdt is None:
        fail(core.ERR_INVALID_REQUEST, 400, "recorded_at must be an ISO 8601 timestamp")
    r = {
        "id": core.new_id(),
        "created_at": now_iso(),
        "_seq": core.tick(),
        "policy_id": p["id"],
        "hospital_id": hid,
        "record_type": rtype,
        "recorded_at": core.fmt_ts(rdt),
        "diagnosis_code": req_str(data, "diagnosis_code"),
        "notes": data.get("notes") if isinstance(data.get("notes"), str) else ("" if data.get("notes") is None else None),
        "appeal_id": None,
        "_recorded_dt": rdt,
    }
    if r["notes"] is None:
        fail(core.ERR_INVALID_REQUEST, 400, "notes must be a string")
    store.records[r["id"]] = r
    return ok(public(r, RECORD_FIELDS), 201)


@bp.get("/policies/<policyId>/medical-records")
def list_policy_records(policyId):
    require_roles("PlatformAdmin", "ClaimsAdjuster", "HospitalStaff")
    p = get_policy_or_404(policyId)
    items = [r for r in store.records.values() if r["policy_id"] == p["id"]]
    cc = request.args.get("condition_code")
    if cc is not None:
        items = [r for r in items if r["diagnosis_code"] == cc]
    items = sort_items(items)
    page, meta = paginate(items)
    return ok([public(r, RECORD_FIELDS) for r in page], 200, meta)


@bp.get("/medical-records/<recordId>")
def get_record(recordId):
    require_roles("PlatformAdmin", "ClaimsAdjuster", "HospitalStaff")
    return ok(public(get_record_or_404(recordId), RECORD_FIELDS))


@bp.get("/medical-records")
def list_records():
    require_roles("PlatformAdmin", "ClaimsAdjuster", "HospitalStaff")
    items = list(store.records.values())
    pid = request.args.get("policy_id")
    hid = request.args.get("hospital_id")
    aid = request.args.get("appeal_id")
    if pid is not None:
        items = [r for r in items if r["policy_id"] == pid]
    if hid is not None:
        items = [r for r in items if r["hospital_id"] == hid]
    if aid is not None:
        items = [r for r in items if r["appeal_id"] == aid]
    items = sort_items(items)
    page, meta = paginate(items)
    return ok([public(r, RECORD_FIELDS) for r in page], 200, meta)


@bp.get("/hospitals/<hospitalId>/medical-records")
def list_hospital_records(hospitalId):
    require_roles("PlatformAdmin", "ClaimsAdjuster", "HospitalStaff")
    h = get_hospital_or_404(hospitalId)
    items = [r for r in store.records.values() if r["hospital_id"] == h["id"]]
    items = sort_items(items)
    page, meta = paginate(items)
    return ok([public(r, RECORD_FIELDS) for r in page], 200, meta)
