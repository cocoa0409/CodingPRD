"""IACUC protocols, welfare inspections, service contracts, and the logical
clock control (PRD 2.5, 3.9, 3.10)."""
from flask import Blueprint

import calc
import domain
import validation as V
from auth import authenticate, require_role, require_ownership
from responses import ApiError, success_object
from store import db, new_id, next_seq, now, set_now, touch

bp = Blueprint("oversight", __name__)


def _invalid_state(msg):
    return ApiError("ERR_INVALID_STATE", 409, msg)


def _ip_terms_error(msg):
    return ApiError("ERR_IP_TERMS_INVALID", 422, msg)


STRAIN_SPEC_FIELDS = (
    "strain_code",
    "species",
    "immune_class",
    "breeding_type",
    "min_barrier_level",
    "gestation_days",
    "wean_age_days",
    "typical_litter_size",
    "base_price_cents",
)


def validate_contract_terms(contract_type, ip_ownership, new_strain_spec, straw_count,
                            exclusivity_fee, royalty_rate, customer):
    """The IP/type payload rules of PRD 3.10, enforced at creation and again
    at execution. Raises ERR_IP_TERMS_INVALID."""
    if contract_type == "CUSTOM_GENERATION":
        if straw_count is not None:
            raise _ip_terms_error("CUSTOM_GENERATION forbids straw_count")
        if not isinstance(new_strain_spec, dict):
            raise _ip_terms_error("CUSTOM_GENERATION requires new_strain_spec")
        for f in STRAIN_SPEC_FIELDS:
            if f not in new_strain_spec or new_strain_spec[f] is None:
                raise _ip_terms_error("new_strain_spec is missing field %s" % f)
    elif contract_type == "CRYOPRESERVATION":
        if new_strain_spec is not None:
            raise _ip_terms_error("CRYOPRESERVATION forbids new_strain_spec")
        if not V.is_int(straw_count) or straw_count < 1:
            raise _ip_terms_error("CRYOPRESERVATION requires straw_count >= 1")
    if ip_ownership == "CUSTOMER_EXCLUSIVE":
        if customer is None or not customer.get("is_commercial"):
            raise _ip_terms_error("CUSTOMER_EXCLUSIVE requires a commercial customer")
        if not V.is_int(exclusivity_fee) or exclusivity_fee < 1:
            raise _ip_terms_error("CUSTOMER_EXCLUSIVE requires exclusivity_fee_cents >= 1")
        if royalty_rate is not None and royalty_rate != 0:
            raise _ip_terms_error("CUSTOMER_EXCLUSIVE forbids royalty_rate_pct")
    else:  # SHARED or VENDOR_RETAINED
        if not V.is_num(royalty_rate) or not (0 < royalty_rate <= 100):
            raise _ip_terms_error("royalty_rate_pct must lie in (0, 100]")


# --------------------------------------------------------------------------
# IACUC protocols
# --------------------------------------------------------------------------

@bp.post("/api/protocols")
def create_protocol():
    uid, role = authenticate()
    require_role(role, ["FacilityManager"])
    b = V.body()
    if b.get("facility_id") is not None:
        V.get_or_404("facilities", b["facility_id"])
    facility_id = V.v_str(b, "facility_id")
    number = V.v_str(b, "protocol_number")
    pi = V.v_str(b, "pi_name")
    species = V.v_enum(b, "species", V.SPECIES)
    quota = V.v_int(b, "approved_animal_quota", minv=1)
    effective = V.v_dt(b, "effective_date")
    expiration = V.v_dt(b, "expiration_date")
    for p in db["protocols"].values():
        if p["protocol_number"] == number:
            raise ApiError("ERR_DUPLICATE_KEY", 409, "protocol_number already exists")
    pid = new_id()
    db["protocols"][pid] = {
        "id": pid,
        "facility_id": facility_id,
        "protocol_number": number,
        "pi_name": pi,
        "species": species,
        "approved_animal_quota": quota,
        "effective_date": effective,
        "expiration_date": expiration,
        "submitted_by_user_id": None,
        "status": "DRAFT",
        "created_at": now(),
        "updated_at": now(),
        "version": 1,
        "_seq": next_seq(),
    }
    return success_object(calc.ser_protocol(db["protocols"][pid]), 201)


_PROTOCOL_TRANSITIONS = {
    ("DRAFT", "SUBMITTED"): ["FacilityManager"],
    ("REVISION_REQUESTED", "SUBMITTED"): ["FacilityManager"],
    ("SUBMITTED", "UNDER_REVIEW"): ["IACUCReviewer"],
    ("UNDER_REVIEW", "APPROVED"): ["IACUCReviewer"],
    ("UNDER_REVIEW", "REJECTED"): ["IACUCReviewer"],
    ("UNDER_REVIEW", "REVISION_REQUESTED"): ["IACUCReviewer"],
    ("APPROVED", "SUSPENDED"): ["PlatformAdmin"],
    ("SUSPENDED", "APPROVED"): ["PlatformAdmin"],
    ("DRAFT", "WITHDRAWN"): ["FacilityManager"],
    ("SUBMITTED", "WITHDRAWN"): ["FacilityManager"],
}


@bp.post("/api/protocols/<pid>/transition")
def protocol_transition(pid):
    uid, role = authenticate()
    require_role(role, ["FacilityManager", "IACUCReviewer", "PlatformAdmin"])
    p = V.get_or_404("protocols", pid)
    b = V.body()
    target = V.v_str(b, "target_state")
    allowed = _PROTOCOL_TRANSITIONS.get((p["status"], target))
    if allowed is None:
        raise _invalid_state(
            "Protocol cannot transition %s -> %s" % (p["status"], target)
        )
    require_role(role, allowed)
    # Priority 6: segregation of duties on decide transitions.
    if p["status"] == "UNDER_REVIEW" and target in ("APPROVED", "REJECTED"):
        if uid == p["submitted_by_user_id"]:
            raise ApiError(
                "ERR_SEGREGATION_OF_DUTIES",
                403,
                "The submitting operator may not decide this protocol",
            )
    p["status"] = target
    if target == "SUBMITTED":
        p["submitted_by_user_id"] = uid
    touch("protocols", pid)
    return success_object(calc.ser_protocol(p))


# --------------------------------------------------------------------------
# Welfare inspections
# --------------------------------------------------------------------------

@bp.post("/api/inspections")
def create_inspection():
    uid, role = authenticate()
    require_role(role, ["WelfareInspector"])
    b = V.body()
    fid = b.get("facility_id")
    cid = b.get("customer_id")
    # Priority 4: present foreign keys resolve.
    if fid is not None:
        V.get_or_404("facilities", fid)
    if cid is not None:
        V.get_or_404("customers", cid)
    # Priority 7: one open inspection per site per UTC calendar day.
    scheduled = None
    if b.get("scheduled_date") is not None:
        try:
            scheduled = V.parse_dt(b["scheduled_date"])
        except (ValueError, TypeError):
            scheduled = None
    if scheduled is not None and ((fid is None) != (cid is None)):
        day = scheduled.date()
        for insp in db["inspections"].values():
            if insp["status"] not in ("SCHEDULED", "CORRECTIVE_ACTION"):
                continue
            same_site = (fid is not None and insp["facility_id"] == fid) or (
                cid is not None and insp["customer_id"] == cid
            )
            if same_site and insp["scheduled_date"].date() == day:
                raise ApiError(
                    "ERR_INSPECTION_DAY_CONFLICT",
                    409,
                    "An open inspection already occupies this site day",
                )
    # Priority 8: exactly one site, fields, enums.
    if (fid is None) == (cid is None):
        raise V.invalid("Exactly one of facility_id / customer_id must be set")
    itype = V.v_enum(b, "inspection_type", V.INSPECTION_TYPES)
    scheduled = V.v_dt(b, "scheduled_date")
    iid = new_id()
    db["inspections"][iid] = {
        "id": iid,
        "facility_id": fid,
        "customer_id": cid,
        "inspection_type": itype,
        "scheduled_date": scheduled,
        "findings": [],
        "corrective_deadline": None,
        "reported_by_user_id": None,
        "status": "SCHEDULED",
        "created_at": now(),
        "_seq": next_seq(),
    }
    return success_object(calc.ser_inspection(db["inspections"][iid]), 201)


@bp.post("/api/inspections/<iid>/report")
def inspection_report(iid):
    uid, role = authenticate()
    require_role(role, ["WelfareInspector"])
    insp = V.get_or_404("inspections", iid)
    b = V.body()
    if insp["status"] != "SCHEDULED":
        raise _invalid_state("Inspection is not SCHEDULED")
    findings = V.req(b, "findings")
    if not isinstance(findings, list):
        raise V.invalid("findings must be an array")
    cleaned = []
    for entry in findings:
        if not isinstance(entry, dict):
            raise V.invalid("each finding must be an object")
        deficiency = entry.get("deficiency")
        severity = entry.get("severity")
        if not isinstance(deficiency, str) or deficiency == "":
            raise V.invalid("finding deficiency must be a non-empty string")
        if not isinstance(severity, str):
            raise V.invalid("finding severity must be a string")
        if severity not in V.SEVERITIES:
            raise ApiError("ERR_INVALID_ENUM", 400, "severity must be MINOR or SIGNIFICANT")
        cleaned.append({"deficiency": deficiency, "severity": severity})
    any_significant = any(f["severity"] == "SIGNIFICANT" for f in cleaned)
    deadline_raw = b.get("corrective_deadline")
    if any_significant and deadline_raw is None:
        raise V.invalid("corrective_deadline is required when a finding is SIGNIFICANT")
    deadline = None
    if deadline_raw is not None:
        try:
            deadline = V.parse_dt(deadline_raw)
        except (ValueError, TypeError):
            raise V.invalid("corrective_deadline must be an ISO-8601 timestamp")
    insp["findings"] = cleaned
    insp["corrective_deadline"] = deadline
    insp["reported_by_user_id"] = uid
    insp["status"] = "CORRECTIVE_ACTION" if cleaned else "CLOSED_VERIFIED"
    return success_object(calc.ser_inspection(insp))


@bp.post("/api/inspections/<iid>/verify")
def inspection_verify(iid):
    uid, role = authenticate()
    require_role(role, ["WelfareInspector"])
    insp = V.get_or_404("inspections", iid)
    b = V.body()
    if insp["status"] != "CORRECTIVE_ACTION":
        raise _invalid_state("Inspection is not in CORRECTIVE_ACTION")
    # Priority 6: segregation of duties.
    if uid == insp["reported_by_user_id"]:
        raise ApiError(
            "ERR_SEGREGATION_OF_DUTIES",
            403,
            "The reporting inspector may not verify corrective closure",
        )
    outcome = V.v_enum(b, "outcome", V.VERIFY_OUTCOMES)
    if outcome == "VERIFIED_OK":
        insp["status"] = "CLOSED_VERIFIED"
    else:
        domain.escalate_inspection(insp)
    return success_object(calc.ser_inspection(insp))


# --------------------------------------------------------------------------
# Service contracts
# --------------------------------------------------------------------------

@bp.post("/api/contracts")
def create_contract():
    uid, role = authenticate()
    require_role(role, ["PlatformAdmin"])
    b = V.body()
    # Priority 4: present foreign keys resolve.
    customer = V.get_or_404("customers", b["customer_id"]) if b.get("customer_id") is not None else None
    if b.get("source_strain_id") is not None:
        V.get_or_404("strains", b["source_strain_id"])
    # Priority 8: fields and enums.
    customer_id = V.v_str(b, "customer_id")
    contract_type = V.v_enum(b, "contract_type", V.CONTRACT_TYPES)
    source_strain_id = V.v_str(b, "source_strain_id")
    ip_ownership = V.v_enum(b, "ip_ownership", V.IP_OWNERSHIP)
    # Priority 8: type-specific and IP terms.
    validate_contract_terms(
        contract_type,
        ip_ownership,
        b.get("new_strain_spec"),
        b.get("straw_count"),
        b.get("exclusivity_fee_cents"),
        b.get("royalty_rate_pct"),
        customer,
    )
    cid = new_id()
    db["contracts"][cid] = {
        "id": cid,
        "customer_id": customer_id,
        "contract_type": contract_type,
        "source_strain_id": source_strain_id,
        "new_strain_spec": b.get("new_strain_spec"),
        "ip_ownership": ip_ownership,
        "exclusivity_fee_cents": b.get("exclusivity_fee_cents"),
        "straw_count": b.get("straw_count"),
        "royalty_rate_pct": b.get("royalty_rate_pct"),
        "viability_pct": None,
        "generated_strain_id": None,
        "milestone_status": "DRAFT",
        "created_at": now(),
        "updated_at": now(),
        "version": 1,
        "_seq": next_seq(),
    }
    return success_object(calc.ser_contract(db["contracts"][cid]), 201)


_CONTRACT_TRANSITIONS = {
    ("DRAFT", "EXECUTED"),
    ("EXECUTED", "IN_PROGRESS"),
    ("IN_PROGRESS", "VALIDATION"),
    ("VALIDATION", "COMPLETED"),
    ("VALIDATION_FAILED", "IN_PROGRESS"),
    ("COMPLETED", "CLOSED"),
    ("DRAFT", "CANCELLED"),
    ("EXECUTED", "CANCELLED"),
}


@bp.post("/api/contracts/<cid>/transition")
def contract_transition(cid):
    uid, role = authenticate()
    require_role(role, ["PlatformAdmin", "Customer"])
    c = V.get_or_404("contracts", cid)
    b = V.body()
    target = V.v_str(b, "target_state")
    if (c["milestone_status"], target) not in _CONTRACT_TRANSITIONS:
        raise _invalid_state(
            "Contract cannot transition %s -> %s" % (c["milestone_status"], target)
        )
    # Per-target authorization and ownership.
    if target == "EXECUTED":
        require_role(role, ["Customer"])
        require_ownership(uid, c["customer_id"])
    elif target == "CANCELLED":
        require_role(role, ["Customer", "PlatformAdmin"])
        if role == "Customer":
            require_ownership(uid, c["customer_id"])
    else:
        require_role(role, ["PlatformAdmin"])

    if target == "EXECUTED":
        customer = db["customers"].get(c["customer_id"])
        validate_contract_terms(
            c["contract_type"],
            c["ip_ownership"],
            c["new_strain_spec"],
            c["straw_count"],
            c["exclusivity_fee_cents"],
            c["royalty_rate_pct"],
            customer,
        )
        c["milestone_status"] = "EXECUTED"
    elif target == "COMPLETED":
        if c["contract_type"] == "CUSTOM_GENERATION":
            spec = c["new_strain_spec"]
            if not isinstance(spec, dict):
                raise V.invalid("new_strain_spec is missing")
            fields = {}
            from routes_catalog import _strain_fields

            fields = _strain_fields(spec)
            for s in db["strains"].values():
                if s["strain_code"] == fields["strain_code"]:
                    raise ApiError("ERR_DUPLICATE_KEY", 409, "strain_code already exists")
            from routes_catalog import create_strain_record

            rec = create_strain_record(fields)
            c["generated_strain_id"] = rec["id"]
            c["milestone_status"] = "COMPLETED"
        else:  # CRYOPRESERVATION
            raw = b.get("viability_pct")
            if raw is None:
                raise V.invalid("viability_pct is required to complete a CRYOPRESERVATION contract")
            if not V.is_num(raw) or raw < 0 or raw > 100:
                raise _ip_terms_error("viability_pct must lie in [0, 100]")
            c["viability_pct"] = raw
            c["milestone_status"] = "COMPLETED" if raw >= calc.VIABILITY_FLOOR else "VALIDATION_FAILED"
    else:
        c["milestone_status"] = target
    touch("contracts", cid)
    return success_object(calc.ser_contract(c))


# --------------------------------------------------------------------------
# Logical clock (the one endpoint outside /api)
# --------------------------------------------------------------------------

@bp.post("/_clock/set_current_utc")
def set_clock():
    uid, role = authenticate()
    require_role(role, ["PlatformAdmin"])
    b = V.body()
    target = V.v_dt(b, "to_iso8601")
    set_now(target)
    domain.clock_sweep()
    return success_object({})
