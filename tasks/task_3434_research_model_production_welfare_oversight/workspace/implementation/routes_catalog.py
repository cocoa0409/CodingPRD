"""Strain catalog, colonies, cohorts, and diagnostic health screens
(PRD 3.2, 3.3, 3.4, 3.5)."""
from flask import Blueprint

import calc
import domain
import validation as V
from auth import ALL_ROLES, authenticate, require_role
from responses import ApiError, success_object
from store import db, new_id, next_seq, now, touch

bp = Blueprint("catalog", __name__)


def _invalid_state(msg):
    return ApiError("ERR_INVALID_STATE", 409, msg)


def _strain_fields(b):
    """Validate and return the nine strain field values (shared by the strain
    catalog and the contract new_strain_spec)."""
    strain_code = V.v_str(b, "strain_code")
    species = V.v_enum(b, "species", V.SPECIES)
    immune_class = V.v_enum(b, "immune_class", V.IMMUNE_CLASSES)
    breeding_type = V.v_enum(b, "breeding_type", V.BREEDING_TYPES)
    min_barrier = V.v_enum(b, "min_barrier_level", V.BARRIER_LEVELS)
    gestation = V.v_int(b, "gestation_days", minv=1)
    wean = V.v_int(b, "wean_age_days", minv=1)
    litter = V.v_int(b, "typical_litter_size", minv=1)
    price = V.v_int(b, "base_price_cents", minv=0)
    return {
        "strain_code": strain_code,
        "species": species,
        "immune_class": immune_class,
        "breeding_type": breeding_type,
        "min_barrier_level": min_barrier,
        "gestation_days": gestation,
        "wean_age_days": wean,
        "typical_litter_size": litter,
        "base_price_cents": price,
    }


def create_strain_record(fields):
    sid = new_id()
    rec = dict(fields)
    rec.update({"id": sid, "created_at": now(), "_seq": next_seq()})
    db["strains"][sid] = rec
    return rec


# --------------------------------------------------------------------------
# Strains
# --------------------------------------------------------------------------

@bp.post("/api/strains")
def create_strain():
    uid, role = authenticate()
    require_role(role, ["PlatformAdmin"])
    b = V.body()
    fields = _strain_fields(b)
    for s in db["strains"].values():
        if s["strain_code"] == fields["strain_code"]:
            raise ApiError("ERR_DUPLICATE_KEY", 409, "strain_code already exists")
    rec = create_strain_record(fields)
    return success_object(calc.ser_strain(rec), 201)


@bp.get("/api/strains/<sid>")
def get_strain(sid):
    uid, role = authenticate()
    require_role(role, ALL_ROLES)
    return success_object(calc.ser_strain(V.get_or_404("strains", sid)))


@bp.get("/api/strains/<sid>/orders")
def strain_orders(sid):
    uid, role = authenticate()
    require_role(role, ALL_ROLES)
    V.get_or_404("strains", sid)
    items = [o for o in db["orders"].values() if o["strain_id"] == sid]
    return V.paginate(items, calc.ser_order)


@bp.get("/api/strains/<sid>/contracts")
def strain_contracts(sid):
    uid, role = authenticate()
    require_role(role, ALL_ROLES)
    V.get_or_404("strains", sid)
    items = [
        c
        for c in db["contracts"].values()
        if c["source_strain_id"] == sid or c["generated_strain_id"] == sid
    ]
    return V.paginate(items, calc.ser_contract)


# --------------------------------------------------------------------------
# Colonies
# --------------------------------------------------------------------------

@bp.post("/api/colonies")
def create_colony():
    uid, role = authenticate()
    require_role(role, ["FacilityManager"])
    b = V.body()
    # Priority 4: present body foreign keys resolve.
    room = V.get_or_404("rooms", b["room_id"]) if b.get("room_id") is not None else None
    strain = V.get_or_404("strains", b["strain_id"]) if b.get("strain_id") is not None else None
    protocol = V.get_or_404("protocols", b["protocol_id"]) if b.get("protocol_id") is not None else None
    # Priority 6: business safety gates, in ladder order.
    if room is not None and room["status"] != "ACTIVE":
        raise ApiError("ERR_ROOM_QUARANTINED", 409, "Room is not ACTIVE")
    if room is not None:
        fac = db["facilities"].get(room["facility_id"])
        if fac is None or fac["registration_status"] != "REGISTERED":
            raise ApiError("ERR_FACILITY_NOT_REGISTERED", 409, "Facility is not REGISTERED")
    if protocol is not None and protocol["status"] != "APPROVED":
        raise ApiError("ERR_PROTOCOL_NOT_APPROVED", 409, "Protocol is not APPROVED")
    if protocol is not None and V.is_int(b.get("breeding_pair_count")):
        used = calc.protocol_animals_used(protocol["id"])
        if used + 2 * b["breeding_pair_count"] > protocol["approved_animal_quota"]:
            raise ApiError("ERR_PROTOCOL_QUOTA_EXCEEDED", 422, "Protocol animal quota would be exceeded")
    # Priority 8: required fields and types.
    room_id = V.v_str(b, "room_id")
    strain_id = V.v_str(b, "strain_id")
    protocol_id = V.v_str(b, "protocol_id")
    pairs = V.v_int(b, "breeding_pair_count", minv=1)
    generation = V.opt_int(b, "generation_number", 0, minv=0)
    snp_interval = V.opt_int(b, "snp_panel_interval_weeks", 12, minv=1)
    # Priority 8: cage capacity (equality passes).
    if calc.occupied_cages(room_id) + pairs > room["cage_capacity"]:
        raise ApiError("ERR_CAGE_CAPACITY_EXCEEDED", 422, "Room cage capacity would be exceeded")
    # Priority 9: barrier sufficiency.
    if V.BARRIER_RANK[room["barrier_level"]] < V.BARRIER_RANK[strain["min_barrier_level"]]:
        raise ApiError("ERR_BARRIER_LEVEL_INSUFFICIENT", 422, "Room barrier below strain minimum")
    # Priority 9: immunocompromised housing restriction.
    if strain["immune_class"] == "IMMUNOCOMPROMISED":
        if V.BARRIER_RANK[room["barrier_level"]] < V.BARRIER_RANK["VF"]:
            raise ApiError(
                "ERR_IMMUNOCOMPROMISED_MIXING", 422, "IMMUNOCOMPROMISED strains require VF or higher"
            )
        for co in db["colonies"].values():
            if co["room_id"] != room_id or co["lifecycle_status"] == "RETIRED":
                continue
            other = db["strains"].get(co["strain_id"])
            if (
                other is not None
                and other["immune_class"] == "IMMUNOCOMPROMISED"
                and other["id"] != strain_id
            ):
                raise ApiError(
                    "ERR_IMMUNOCOMPROMISED_MIXING",
                    422,
                    "Room already hosts a different IMMUNOCOMPROMISED strain",
                )
    cid = new_id()
    db["colonies"][cid] = {
        "id": cid,
        "room_id": room_id,
        "strain_id": strain_id,
        "protocol_id": protocol_id,
        "breeding_pair_count": pairs,
        "generation_number": generation,
        "lifecycle_status": "FOUNDING",
        "genetic_status": "CLEAR",
        "last_snp_panel_at": now(),
        "snp_panel_interval_weeks": snp_interval,
        "created_at": now(),
        "updated_at": now(),
        "version": 1,
        "_seq": next_seq(),
    }
    return success_object(calc.ser_colony(db["colonies"][cid]), 201)


@bp.get("/api/colonies")
def list_colonies():
    uid, role = authenticate()
    require_role(role, ALL_ROLES)
    args = __import__("flask").request.args
    items = list(db["colonies"].values())
    for key in ("room_id", "strain_id", "protocol_id", "lifecycle_status"):
        val = args.get(key)
        if val is not None:
            items = [c for c in items if str(c.get(key)) == val]
    return V.paginate(items, calc.ser_colony)


@bp.get("/api/colonies/<cid>")
def get_colony(cid):
    uid, role = authenticate()
    require_role(role, ALL_ROLES)
    return success_object(calc.ser_colony(V.get_or_404("colonies", cid)))


@bp.post("/api/colonies/<cid>/transition")
def colony_transition(cid):
    uid, role = authenticate()
    require_role(role, ["FacilityManager"])
    co = V.get_or_404("colonies", cid)
    b = V.body()
    target = V.v_str(b, "target_state")
    cur = co["lifecycle_status"]
    if target == "EXPANDING":
        if cur != "FOUNDING":
            raise _invalid_state("Colony cannot enter EXPANDING from %s" % cur)
        co["lifecycle_status"] = "EXPANDING"
    elif target == "PRODUCTION":
        if cur == "EXPANDING":
            live = any(
                c["colony_id"] == cid and c["status"] in V.LIVE_COHORT_STATUSES
                for c in db["cohorts"].values()
            )
            if not live:
                raise _invalid_state("No live cohort exists for this colony")
            co["lifecycle_status"] = "PRODUCTION"
        elif cur == "PHASING_OUT":
            if co["genetic_status"] == "DRIFT_DETECTED":
                raise _invalid_state("DRIFT_DETECTED colony cannot reactivate")
            co["lifecycle_status"] = "PRODUCTION"
        else:
            raise _invalid_state("Colony cannot enter PRODUCTION from %s" % cur)
    elif target == "PHASING_OUT":
        if cur != "PRODUCTION":
            raise _invalid_state("Colony cannot enter PHASING_OUT from %s" % cur)
        co["lifecycle_status"] = "PHASING_OUT"
    elif target == "RETIRED":
        if cur != "PHASING_OUT":
            raise _invalid_state("Colony cannot retire from %s" % cur)
        for c in db["cohorts"].values():
            if c["colony_id"] != cid:
                continue
            if c["status"] in V.LIVE_COHORT_STATUSES:
                raise _invalid_state("Live cohorts remain")
            for a in db["allocations"].values():
                if a["cohort_id"] == c["id"] and a["status"] == "RESERVED":
                    raise _invalid_state("Reserved allocations remain")
        co["lifecycle_status"] = "RETIRED"
    else:
        raise _invalid_state("Unknown target_state %s" % target)
    touch("colonies", cid)
    return success_object(calc.ser_colony(co))


@bp.post("/api/colonies/<cid>/snp-panel")
def colony_snp_panel(cid):
    uid, role = authenticate()
    require_role(role, ["Veterinarian"])
    co = V.get_or_404("colonies", cid)
    b = V.body()
    result = V.v_enum(b, "result", V.SNP_RESULTS)
    gs = co["genetic_status"]
    if result == "CLEAR":
        if gs != "PANEL_DUE":
            raise _invalid_state("SNP CLEAR result is only valid from PANEL_DUE")
        co["genetic_status"] = "CLEAR"
    else:  # DRIFT_DETECTED
        if gs not in ("CLEAR", "PANEL_DUE"):
            raise _invalid_state("Colony is already DRIFT_DETECTED")
        co["genetic_status"] = "DRIFT_DETECTED"
        if co["lifecycle_status"] in ("EXPANDING", "PRODUCTION"):
            co["lifecycle_status"] = "PHASING_OUT"
    co["last_snp_panel_at"] = now()
    touch("colonies", cid)
    return success_object(calc.ser_colony(co))


@bp.get("/api/colonies/<cid>/cohorts")
def colony_cohorts(cid):
    uid, role = authenticate()
    require_role(role, ALL_ROLES)
    V.get_or_404("colonies", cid)
    items = [c for c in db["cohorts"].values() if c["colony_id"] == cid]
    return V.paginate(items, calc.ser_cohort)


# --------------------------------------------------------------------------
# Cohorts
# --------------------------------------------------------------------------

@bp.post("/api/cohorts")
def create_cohort():
    uid, role = authenticate()
    require_role(role, ["FacilityManager"])
    b = V.body()
    # Priority 4: present body foreign keys resolve.
    colony = V.get_or_404("colonies", b["colony_id"]) if b.get("colony_id") is not None else None
    room = db["rooms"].get(colony["room_id"]) if colony is not None else None
    protocol = db["protocols"].get(colony["protocol_id"]) if colony is not None else None
    # Priority 5: colony lifecycle must admit new cohorts.
    if colony is not None and colony["lifecycle_status"] not in ("EXPANDING", "PRODUCTION"):
        raise _invalid_state("Colony in %s cannot accept new cohorts" % colony["lifecycle_status"])
    # Priority 6: business safety gates.
    if room is not None and room["status"] != "ACTIVE":
        raise ApiError("ERR_ROOM_QUARANTINED", 409, "Room is not ACTIVE")
    if colony is not None and colony["genetic_status"] != "CLEAR":
        raise ApiError("ERR_GENETIC_DRIFT", 409, "Colony genetic_status is not CLEAR")
    if protocol is not None and protocol["status"] != "APPROVED":
        raise ApiError("ERR_PROTOCOL_NOT_APPROVED", 409, "Protocol is not APPROVED")
    if (
        protocol is not None
        and V.is_int(b.get("count_male"))
        and V.is_int(b.get("count_female"))
    ):
        used = calc.protocol_animals_used(protocol["id"])
        if used + b["count_male"] + b["count_female"] > protocol["approved_animal_quota"]:
            raise ApiError("ERR_PROTOCOL_QUOTA_EXCEEDED", 422, "Protocol animal quota would be exceeded")
    # Priority 8: required fields and types.
    colony_id = V.v_str(b, "colony_id")
    birth = V.v_dt(b, "birth_date")
    if birth > now():
        raise V.invalid("birth_date must not lie after the current logical clock")
    count_male = V.v_int(b, "count_male", minv=0)
    count_female = V.v_int(b, "count_female", minv=0)
    w_male = V.v_num(b, "avg_weight_g_male", minv=0, exclusive_min=True)
    w_female = V.v_num(b, "avg_weight_g_female", minv=0, exclusive_min=True)
    # Priority 8: cage capacity (equality passes).
    incoming = -(-(count_male + count_female) // calc.CAGE_DENSITY)
    if calc.occupied_cages(room["id"]) + incoming > room["cage_capacity"]:
        raise ApiError("ERR_CAGE_CAPACITY_EXCEEDED", 422, "Room cage capacity would be exceeded")
    cid = new_id()
    db["cohorts"][cid] = {
        "id": cid,
        "colony_id": colony_id,
        "birth_date": birth,
        "count_male": count_male,
        "count_female": count_female,
        "initial_count_total": count_male + count_female,
        "avg_weight_g_male": w_male,
        "avg_weight_g_female": w_female,
        "health_status": room["barrier_level"],
        "status": "WEANED",
        "created_at": now(),
        "updated_at": now(),
        "version": 1,
        "_seq": next_seq(),
    }
    return success_object(calc.ser_cohort(db["cohorts"][cid]), 201)


@bp.get("/api/cohorts/<cid>")
def get_cohort(cid):
    uid, role = authenticate()
    require_role(role, ALL_ROLES)
    return success_object(calc.ser_cohort(V.get_or_404("cohorts", cid)))


@bp.post("/api/cohorts/<cid>/transition")
def cohort_transition(cid):
    uid, role = authenticate()
    require_role(role, ["FacilityManager", "Veterinarian"])
    cohort = V.get_or_404("cohorts", cid)
    b = V.body()
    target = V.v_str(b, "target_state")
    if target == "HOLD":
        require_role(role, ["FacilityManager"])
        if cohort["status"] != "WEANED":
            raise _invalid_state("Only a WEANED cohort can enter HOLD")
        colony = db["colonies"].get(cohort["colony_id"])
        if colony is None or colony["lifecycle_status"] not in ("EXPANDING", "PRODUCTION"):
            raise _invalid_state("Colony is not EXPANDING or PRODUCTION")
        if colony["genetic_status"] != "CLEAR":
            raise _invalid_state("Colony genetic_status is not CLEAR")
        cohort["status"] = "HOLD"
    elif target == "CULLED":
        require_role(role, ["Veterinarian"])
        if cohort["status"] not in ("WEANED", "HOLD", "PARTIALLY_ALLOCATED"):
            raise _invalid_state("Cohort in %s cannot be culled" % cohort["status"])
        cull_male = V.v_int(b, "cull_male", minv=0)
        cull_female = V.v_int(b, "cull_female", minv=0)
        rm, rf = calc.cohort_reserved(cid)
        avail_m = cohort["count_male"] - rm
        avail_f = cohort["count_female"] - rf
        if cull_male == cohort["count_male"] and cull_female == cohort["count_female"]:
            # Full cull: no RESERVED allocation may exist.
            if calc.cohort_has_reserved(cid):
                raise _invalid_state("Reserved allocations block a full cull")
            cohort["count_male"] = 0
            cohort["count_female"] = 0
            cohort["status"] = "CULLED"
        else:
            # Partial cull: bounded by the available (unreserved) counts and
            # does not change status except the FULLY_ALLOCATED recompute.
            if cull_male > avail_m or cull_female > avail_f:
                raise V.invalid("Cull counts exceed available (unreserved) counts")
            cohort["count_male"] -= cull_male
            cohort["count_female"] -= cull_female
            domain.recompute_cohort(cohort)
    else:
        raise _invalid_state("Unknown target_state %s" % target)
    touch("cohorts", cid)
    return success_object(calc.ser_cohort(cohort))


@bp.get("/api/cohorts/<cid>/allocations")
def cohort_allocations(cid):
    uid, role = authenticate()
    require_role(role, ALL_ROLES)
    V.get_or_404("cohorts", cid)
    items = [a for a in db["allocations"].values() if a["cohort_id"] == cid]
    return V.paginate(items, calc.ser_allocation)


# --------------------------------------------------------------------------
# Health screens
# --------------------------------------------------------------------------

@bp.post("/api/health-screens")
def create_health_screen():
    uid, role = authenticate()
    require_role(role, ["Veterinarian"])
    b = V.body()
    if b.get("room_id") is not None:
        V.get_or_404("rooms", b["room_id"])
    room_id = V.v_str(b, "room_id")
    panel_type = V.v_enum(b, "panel_type", V.PANEL_TYPES)
    scheduled = V.v_dt(b, "scheduled_at")
    hid = new_id()
    db["health_screens"][hid] = {
        "id": hid,
        "room_id": room_id,
        "panel_type": panel_type,
        "scheduled_at": scheduled,
        "status": "SCHEDULED",
        "results": [],
        "resulted_at": None,
        "created_at": now(),
        "_seq": next_seq(),
    }
    return success_object(calc.ser_health_screen(db["health_screens"][hid]), 201)


@bp.post("/api/health-screens/<hid>/result")
def health_screen_result(hid):
    uid, role = authenticate()
    require_role(role, ["Veterinarian"])
    screen = V.get_or_404("health_screens", hid)
    b = V.body()
    if screen["status"] != "SCHEDULED":
        raise _invalid_state("Health screen has already been resulted")
    room = db["rooms"].get(screen["room_id"])
    if room is not None and room["status"] == "DECOMMISSIONED":
        raise _invalid_state("Room is DECOMMISSIONED")
    results = V.req(b, "results")
    if not isinstance(results, list):
        raise V.invalid("results must be an array")
    cleaned = []
    for entry in results:
        if not isinstance(entry, dict):
            raise V.invalid("each result entry must be an object")
        agent = entry.get("agent")
        positive = entry.get("positive")
        if not isinstance(agent, str) or agent == "":
            raise V.invalid("result entry agent must be a non-empty string")
        if not isinstance(positive, bool):
            raise V.invalid("result entry positive must be a boolean")
        cleaned.append({"agent": agent, "positive": positive})
    hit = any(e["positive"] and e["agent"] in (room["excluded_agents"] if room else []) for e in cleaned)
    screen["results"] = cleaned
    screen["resulted_at"] = now()
    screen["status"] = "RESULTED_POSITIVE" if hit else "RESULTED_NEGATIVE"
    if hit and room is not None:
        domain.positive_screen_cascade(room)
    return success_object(calc.ser_health_screen(screen))
