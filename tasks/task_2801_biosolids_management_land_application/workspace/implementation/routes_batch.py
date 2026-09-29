"""Solids batch endpoints (PRD 3.2 - 3.4)."""

from decimal import Decimal

from flask import Blueprint, g

import store
from auth import roles
from calc import pathogen_class, vsr_mass_balance, vsr_van_kleeck
from derive import (active_limit_for, active_limits, ceiling_rejection_cascade,
                    current_round_results, pfos_advisory_cascade,
                    recompute_batch_balance, refresh_facility_exceedances,
                    refresh_facility_storage, results_of_batch)
from envelope import object_response
from errors import fail
from listing import emit_list
from store import ANALYTES, D, iso, now_iso, public, r2, r3, touch
from validate import (get_body, present, qenum, qint, qstr, resolve_fks, venum, vdt,
                      vint, vnum, vstr)

bp = Blueprint("batches", __name__, url_prefix="/api/v1/solids-batches")

PROCESS_STATUSES = ("THICKENED", "DIGESTED", "DEWATERED")
QUALITY_STATUSES = ("UNTESTED", "PENDING_RESULTS", "QUALIFIED", "REJECTED")
DISPOSITIONS = ("HELD", "PARTIALLY_COMMITTED", "FULLY_COMMITTED")
STABILIZATION = ("ANAEROBIC_DIGESTION", "COMPOSTED", "LIME_STABILIZED")
PATHOGEN_OPTIONS = ("PFRP_ALT1_TIME_TEMP", "PSRP_ALT1_TIME_TEMP",
                    "PSRP_ALT3_FECAL_COLIFORM")
VECTOR_OPTIONS = ("VAR_OPTION_1_VSR", "VAR_OPTION_3_SOUR", "VAR_OPTION_5_AEROBIC",
                  "VAR_OPTION_9_INJECTION", "VAR_OPTION_10_INCORPORATION")
PLANT_SIDE_OPTIONS = ("VAR_OPTION_1_VSR", "VAR_OPTION_3_SOUR", "VAR_OPTION_5_AEROBIC")
BATCH_READ_ROLES = ("FacilityOperator", "ComplianceOfficer", "LabAnalyst", "Agronomist")
NEXT_STAGE = {"THICKENED": "DIGESTED", "DIGESTED": "DEWATERED"}


def get_batch(batch_id):
    batch = store.batches.get(batch_id)
    if batch is None:
        fail("ERR_BATCH_NOT_FOUND", "Batch %s does not exist." % batch_id)
    return batch


def facility_of_batch(batch):
    return store.facilities.get(batch["facility_id"])


def require_not_frozen(facility):
    if facility is not None and facility["posture"] == "FROZEN":
        fail("ERR_FACILITY_FROZEN", "Facility posture is FROZEN.")


@bp.post("")
@roles("FacilityOperator")
def create_batch():
    body = get_body()
    fks = resolve_fks(body, ("facility_id",))
    facility_id = body.get("facility_id")
    if not isinstance(facility_id, str) or not facility_id.strip():
        fail("ERR_INVALID_REQUEST", "Field 'facility_id' is required.")
    facility = fks["facility_id"]
    batch_code = vstr(body, "batch_code", required=True, min_len=1)
    wet_tons = vnum(body, "wet_tons", required=True, gt=0)
    dry_tons_in = vnum(body, "dry_tons_in", required=True, gt=0)
    vs_in = vnum(body, "volatile_solids_in_pct", required=True, gt=0, lt=100)
    percent_solids = vnum(body, "percent_solids", required=True, gt=0, lt=100)
    detention_days = vnum(body, "detention_days", required=False, default=Decimal("0.0"),
                          ge=0)
    digester_temp_c = vnum(body, "digester_temp_c", required=False,
                           default=Decimal("0.0"))
    stabilization = venum(body, "stabilization_process", STABILIZATION, required=False,
                          default="ANAEROBIC_DIGESTION")
    pathogen_option = venum(body, "pathogen_option", PATHOGEN_OPTIONS, required=False,
                            default="PSRP_ALT1_TIME_TEMP")
    vector_option = venum(body, "vector_option", VECTOR_OPTIONS, required=False,
                          default="VAR_OPTION_1_VSR")
    fecal = vnum(body, "fecal_coliform_mpn_per_g", required=False, default=None, ge=0,
                 nullable=True)
    salmonella = vnum(body, "salmonella_mpn_per_4g", required=False, default=None, ge=0,
                      nullable=True)
    sour = vnum(body, "sour_mg_o2_per_g_hr", required=False, default=None, ge=0,
                nullable=True)
    aerobic_days = vnum(body, "aerobic_process_days", required=False,
                        default=Decimal("0.0"), ge=0, nullable=True)
    nh4 = vnum(body, "nh4_n_mg_kg", required=False, default=Decimal("0.0"), ge=0)
    organic_n = vnum(body, "organic_n_mg_kg", required=False, default=Decimal("0.0"),
                     ge=0)
    nitrate_n = vnum(body, "nitrate_n_mg_kg", required=False, default=Decimal("0.0"),
                     ge=0)
    total_p = vnum(body, "total_p_mg_kg", required=False, default=Decimal("0.0"), ge=0)

    require_not_frozen(facility)
    wet_tons = r2(wet_tons)
    if (D(facility["storage_used_wet_tons"]) + wet_tons
            > D(facility["storage_capacity_wet_tons"])):
        fail("ERR_STORAGE_CAPACITY_EXCEEDED",
             "Offered wet tonnage exceeds remaining storage capacity.")
    for existing in store.batches.values():
        if existing["facility_id"] == facility["id"] and existing["batch_code"] == batch_code:
            fail("ERR_DUPLICATE_RESOURCE",
                 "batch_code %s already exists for this facility." % batch_code)

    batch = store.new_record({
        "facility_id": facility["id"],
        "batch_code": batch_code,
        "wet_tons": wet_tons,
        "dry_tons_in": r3(dry_tons_in),
        "volatile_solids_in_pct": r2(vs_in),
        "percent_solids": r2(percent_solids),
        "dry_tons_out": None,
        "volatile_solids_out_pct": None,
        "detention_days": detention_days,
        "digester_temp_c": digester_temp_c,
        "stabilization_process": stabilization,
        "pathogen_option": pathogen_option,
        "vector_option": vector_option,
        "fecal_coliform_mpn_per_g": fecal,
        "salmonella_mpn_per_4g": salmonella,
        "sour_mg_o2_per_g_hr": sour,
        "aerobic_process_days": aerobic_days,
        "nh4_n_mg_kg": nh4,
        "organic_n_mg_kg": organic_n,
        "nitrate_n_mg_kg": nitrate_n,
        "total_p_mg_kg": total_p,
        "dry_tons_produced": r3(0),
        "unallocated_dry_tons": r3(0),
        "vsr_pct_van_kleeck": r2(0),
        "vsr_pct_mass_balance": r2(0),
        "pathogen_class": "NONE",
        "vector_demonstrated_at_batch": False,
        "process_status": "THICKENED",
        "quality_status": "UNTESTED",
        "disposition": "HELD",
        "retest_round": 0,
        "rejection_reason": None,
        "ceiling_exceedance_flag": False,
        "certified_at": None,
        "certified_by_user_id": None,
        "updated_at": now_iso(),
        "version": 1,
    })
    store.batches[batch["id"]] = batch
    refresh_facility_storage(facility)
    return object_response(public(batch), 201)


@bp.get("/<batch_id>")
@roles(*BATCH_READ_ROLES)
def read_batch(batch_id):
    return object_response(public(get_batch(batch_id)))


@bp.get("")
@roles(*BATCH_READ_ROLES)
def list_batches():
    facility_id = qstr("facility_id")
    process_status = qenum("process_status", PROCESS_STATUSES)
    quality_status = qenum("quality_status", QUALITY_STATUSES)
    disposition = qenum("disposition", DISPOSITIONS)
    rows = [b for b in store.batches.values()
            if (facility_id is None or b["facility_id"] == facility_id)
            and (process_status is None or b["process_status"] == process_status)
            and (quality_status is None or b["quality_status"] == quality_status)
            and (disposition is None or b["disposition"] == disposition)]
    return emit_list(rows, ("created_at",))


@bp.post("/<batch_id>/advance-process")
@roles("FacilityOperator")
def advance_process(batch_id):
    batch = get_batch(batch_id)
    body = get_body()
    to_status = body.get("to_status")
    if to_status is None or not isinstance(to_status, str) or not to_status.strip():
        fail("ERR_INVALID_REQUEST", "Field 'to_status' is required.")

    dry_tons_out = None
    vs_out = None
    detention_days = None
    digester_temp_c = None
    percent_solids = None
    if to_status == "DIGESTED":
        dry_tons_out = vnum(body, "dry_tons_out", required=True, gt=0)
        vs_out = vnum(body, "volatile_solids_out_pct", required=True, gt=0)
        detention_days = vnum(body, "detention_days", required=True, ge=0)
        digester_temp_c = vnum(body, "digester_temp_c", required=True)
        if dry_tons_out > D(batch["dry_tons_in"]):
            fail("ERR_INVALID_REQUEST",
                 "Field 'dry_tons_out' must be at most dry_tons_in.")
        if vs_out >= D(batch["volatile_solids_in_pct"]):
            fail("ERR_INVALID_REQUEST",
                 "Field 'volatile_solids_out_pct' must be less than "
                 "volatile_solids_in_pct.")
    elif to_status == "DEWATERED":
        percent_solids = vnum(body, "percent_solids", required=False, default=None, gt=0,
                              lt=100)
        if percent_solids is None and batch.get("percent_solids") is None:
            fail("ERR_INVALID_REQUEST", "Field 'percent_solids' is required.")

    if NEXT_STAGE.get(batch["process_status"]) != to_status:
        fail("ERR_INVALID_PROCESS_TRANSITION",
             "Batch cannot move from %s to %s." % (batch["process_status"], to_status))

    facility = facility_of_batch(batch)
    require_not_frozen(facility)

    if to_status == "DIGESTED":
        batch["dry_tons_out"] = r3(dry_tons_out)
        batch["volatile_solids_out_pct"] = r2(vs_out)
        batch["detention_days"] = detention_days
        batch["digester_temp_c"] = digester_temp_c
        batch["vsr_pct_van_kleeck"] = vsr_van_kleeck(
            batch["volatile_solids_in_pct"], batch["volatile_solids_out_pct"])
        batch["vsr_pct_mass_balance"] = vsr_mass_balance(
            batch["dry_tons_in"], batch["volatile_solids_in_pct"],
            batch["dry_tons_out"], batch["volatile_solids_out_pct"])
        batch["process_status"] = "DIGESTED"
        batch["pathogen_class"] = pathogen_class(batch)
        if (batch["vector_option"] == "VAR_OPTION_1_VSR"
                and D(batch["vsr_pct_van_kleeck"]) < Decimal("38.00")
                and batch["quality_status"] == "UNTESTED"):
            batch["quality_status"] = "REJECTED"
            batch["rejection_reason"] = "VSR_BELOW_MINIMUM"
        touch(batch)
    else:
        if percent_solids is not None:
            batch["percent_solids"] = r2(percent_solids)
        batch["dry_tons_produced"] = r3(batch["dry_tons_out"])
        batch["process_status"] = "DEWATERED"
        if batch["quality_status"] == "UNTESTED":
            batch["quality_status"] = "PENDING_RESULTS"
        recompute_batch_balance(batch)
        touch(batch)
    return object_response(public(batch))


@bp.post("/<batch_id>/certify")
@roles("ComplianceOfficer")
def certify_batch(batch_id):
    batch = get_batch(batch_id)
    get_body()
    if batch["process_status"] != "DEWATERED":
        fail("ERR_INVALID_PROCESS_TRANSITION",
             "Batch must be DEWATERED before certification.")
    if batch["quality_status"] != "PENDING_RESULTS":
        fail("ERR_INVALID_QUALITY_TRANSITION",
             "Batch quality_status must be PENDING_RESULTS to certify.")
    facility = facility_of_batch(batch)
    require_not_frozen(facility)

    batch["pathogen_class"] = pathogen_class(batch)
    if batch["pathogen_class"] not in ("CLASS_B", "CLASS_A"):
        fail("ERR_PATHOGEN_CLASS_INSUFFICIENT",
             "Derived pathogen_class is NONE.")

    option = batch["vector_option"]
    if option == "VAR_OPTION_1_VSR":
        vsr = batch.get("vsr_pct_van_kleeck")
        if vsr is None or D(vsr) < Decimal("38.00"):
            fail("ERR_VSR_BELOW_MINIMUM",
                 "vsr_pct_van_kleeck is below the 38.00 minimum.")
    elif option == "VAR_OPTION_3_SOUR":
        sour = batch.get("sour_mg_o2_per_g_hr")
        if (sour is None or D(sour) > Decimal("1.5")
                or batch.get("digester_temp_c") is None
                or D(batch["digester_temp_c"]) > Decimal("20.0")):
            fail("ERR_VECTOR_OPTION_EVIDENCE_MISSING",
                 "SOUR vector attraction reduction evidence is missing or failing.")
    elif option == "VAR_OPTION_5_AEROBIC":
        aerobic = batch.get("aerobic_process_days")
        if (aerobic is None or D(aerobic) < Decimal("14.0")
                or batch.get("digester_temp_c") is None
                or D(batch["digester_temp_c"]) < Decimal("40.0")):
            fail("ERR_VECTOR_OPTION_EVIDENCE_MISSING",
                 "Aerobic vector attraction reduction evidence is missing or failing.")

    limits = active_limits()
    results = current_round_results(batch)
    by_analyte = {r["analyte"]: r for r in results}
    for analyte in sorted(limits):
        if analyte not in by_analyte:
            fail("ERR_ANALYTE_PANEL_INCOMPLETE",
                 "Analyte %s has no result in the current sampling round." % analyte)
    for analyte in sorted(by_analyte):
        if by_analyte[analyte]["exceeds_ceiling"]:
            fail("ERR_CEILING_EXCEEDED", "Analyte %s exceeds its ceiling." % analyte)
    for analyte in sorted(by_analyte):
        if by_analyte[analyte]["exceeds_monthly_avg"]:
            fail("ERR_MONTHLY_AVG_EXCEEDED",
                 "Analyte %s exceeds its monthly average limit." % analyte)

    batch["quality_status"] = "QUALIFIED"
    batch["certified_at"] = now_iso()
    batch["certified_by_user_id"] = g.user_id
    batch["vector_demonstrated_at_batch"] = option in PLANT_SIDE_OPTIONS
    touch(batch)
    return object_response(public(batch))


@bp.post("/<batch_id>/retest-request")
@roles("ComplianceOfficer")
def retest_request(batch_id):
    batch = get_batch(batch_id)
    get_body()
    if batch["quality_status"] != "REJECTED":
        fail("ERR_INVALID_QUALITY_TRANSITION",
             "Only a REJECTED batch may be reopened for retesting.")
    if not batch["retest_round"] < 2:
        fail("ERR_RETEST_LIMIT_REACHED", "The batch has already been resampled twice.")
    was_ceiling = bool(batch["ceiling_exceedance_flag"])
    batch["retest_round"] = batch["retest_round"] + 1
    batch["quality_status"] = "PENDING_RESULTS"
    batch["rejection_reason"] = None
    batch["ceiling_exceedance_flag"] = False
    touch(batch)
    if was_ceiling:
        facility = facility_of_batch(batch)
        if facility is not None:
            refresh_facility_exceedances(facility)
    return object_response(public(batch))


@bp.post("/<batch_id>/lab-results")
@roles("LabAnalyst")
def file_lab_result(batch_id):
    batch = get_batch(batch_id)
    body = get_body()
    analyte = venum(body, "analyte", ANALYTES, required=True)
    concentration = vnum(body, "concentration_mg_kg", required=True, ge=0)
    sampling_event_index = vint(body, "sampling_event_index", required=True, ge=0)
    analyzed_at = vdt(body, "analyzed_at", required=True)
    method_code = vstr(body, "method_code", required=False, min_len=1, max_len=32,
                       default=None)

    if batch["quality_status"] not in ("PENDING_RESULTS", "QUALIFIED"):
        fail("ERR_INVALID_QUALITY_TRANSITION",
             "Results are accepted only while quality_status is PENDING_RESULTS or "
             "QUALIFIED.")
    for existing in store.lab_results.values():
        if (existing["batch_id"] == batch["id"] and existing["analyte"] == analyte
                and existing["sampling_event_index"] == sampling_event_index):
            fail("ERR_DUPLICATE_RESOURCE",
                 "A result for %s in round %d already exists."
                 % (analyte, sampling_event_index))
    if sampling_event_index != batch["retest_round"]:
        fail("ERR_SAMPLING_ROUND_MISMATCH",
             "sampling_event_index must equal the batch retest_round %d."
             % batch["retest_round"])
    limit = active_limit_for(analyte)
    if limit is None:
        fail("ERR_LIMIT_NOT_FOUND",
             "No ACTIVE pollutant limit row exists for %s." % analyte)

    concentration = r3(concentration)
    exceeds_ceiling = concentration > D(limit["ceiling_mg_kg"])
    monthly = limit.get("monthly_avg_mg_kg")
    exceeds_monthly = monthly is not None and concentration > D(monthly)
    advisory = limit.get("advisory_threshold_mg_kg")
    advisory_exceeded = advisory is not None and concentration > D(advisory)

    result = store.new_record({
        "batch_id": batch["id"],
        "analyte": analyte,
        "concentration_mg_kg": concentration,
        "sampling_event_index": sampling_event_index,
        "analyzed_at": iso(analyzed_at),
        "method_code": method_code,
        "exceeds_ceiling": bool(exceeds_ceiling),
        "exceeds_monthly_avg": bool(exceeds_monthly),
        "advisory_exceeded": bool(advisory_exceeded),
    })
    store.lab_results[result["id"]] = result

    if exceeds_ceiling:
        ceiling_rejection_cascade(batch)
    if analyte == "PFOS" and advisory_exceeded:
        pfos_advisory_cascade(batch)
    return object_response(public(result), 201)


@bp.get("/<batch_id>/lab-results")
@roles("LabAnalyst", "ComplianceOfficer", "FacilityOperator", "Agronomist")
def list_batch_lab_results(batch_id):
    batch = get_batch(batch_id)
    analyte = qenum("analyte", ANALYTES)
    sampling_event_index = qint("sampling_event_index")
    rows = [r for r in results_of_batch(batch["id"])
            if (analyte is None or r["analyte"] == analyte)
            and (sampling_event_index is None
                 or r["sampling_event_index"] == sampling_event_index)]
    return emit_list(rows, ("sampling_event_index", "analyte", "created_at"))
