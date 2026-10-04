"""Temperature excursions, adjudication, slices, appeals and wastage reports."""
from flask import Blueprint

from errors import ApiError
from helpers import h
from middleware import guard
from clockutil import parse_ts, clock, fmt, add_hours, diff_minutes, diff_hours_rounded, earlier
from services import derive as D
from services import calc as C
from routes import common as K

bp = Blueprint("review", __name__)

REVIEW_STATUSES = ["REPORTED", "UNDER_REVIEW", "ADJUDICATED"]
ADJUDICATION_STATUSES = ["PENDING", "USABLE", "NOT_USABLE"]
QUARANTINE_STATUSES = ["OPEN", "LIFTED", "RETAINED", "DESTROYED"]
OUTCOMES = ["USABLE", "NOT_USABLE"]
CLOSURE_STATES = ["OPEN", "IN_REVIEW", "CLOSED"]
SLICE_STATUSES = ["PENDING", "CERTIFIED"]
APPEAL_STATUSES = ["FILED", "ACCEPTED", "DENIED"]
ADJUDICATION_LIFECYCLE = ["DECIDED", "APPEALED", "SUPERSEDED", "WITHDRAWN"]
WASTAGE_CAUSES = ["TEMPERATURE_EXCURSION", "PUNCTURE_EXPIRY", "THAW_WINDOW_BREACH",
                  "REFRIGERATED_EXPIRY", "TRANSFER_REJECTION", "SITE_RETURN"]
WASTAGE_STATUSES = ["OPEN", "RECONCILED"]

APPEAL_WINDOW_HOURS = 72
PUNCTURE_LIMIT_SENTINEL = "puncture"


# ---------------------------------------------------------------------------
# TemperatureExcursion
# ---------------------------------------------------------------------------
@bp.route("/temperature-excursions", methods=["POST"])
def report_excursion():
    guard("POST /vaccine-distribution/temperature-excursions")
    data = K.body()
    carton = K.fetch("cartons", K.required(data, "carton_id"), "Carton")
    site = K.fetch("storage_sites", K.required(data, "storage_site_id"), "Storage site")
    first = K.as_ts(K.required(data, "first_breach_at"), "first_breach_at")
    last = K.as_ts(K.required(data, "last_breach_at"), "last_breach_at")
    min_temp = K.as_num(K.required(data, "min_temperature_c"), "min_temperature_c")
    reported_at = K.as_ts(K.required(data, "reported_at"), "reported_at")

    batch = D.batch_of_carton(carton)
    product = D.product_of_batch(batch)
    minutes = diff_minutes(parse_ts(last), parse_ts(first))
    thaw_window = parse_ts(carton.get("thaw_window_expires_at"))
    remaining = 0.0
    if thaw_window is not None:
        remaining = max(0.0, diff_hours_rounded(thaw_window, parse_ts(last), 4))
    rec = h.create("temperature_excursions", {
        "carton_id": carton["id"],
        "storage_site_id": site["id"],
        "first_breach_at": first,
        "last_breach_at": last,
        "min_temperature_c": min_temp,
        "reported_at": reported_at,
        "review_status": "REPORTED",
        "adjudication_status": "PENDING",
        "adjudicated_at": None,
        "min_duration_minutes": minutes,
        "dosing_hours_remaining_at_breach": remaining,
        "exceeds_cumulative_cap": bool(
            product and minutes > product.get("excursion_max_cumulative_minutes", 0)
        ),
        "dose_impact_category": "NONE",
        "dose_impact_factor": 0.0,
        "quarantine_status": "OPEN",
        "current_resolution_trace_id": None,
        "_ready_at_first_phase": 0,
    })
    D.recompute_site(site)
    h.touch(carton)
    return K.created(rec)


@bp.route("/temperature-excursions", methods=["GET"])
def list_excursions():
    guard("GET /vaccine-distribution/temperature-excursions")
    return K.list_response(h.all("temperature_excursions"), {
        "carton_id": K.eq("carton_id"),
        "storage_site_id": K.eq("storage_site_id"),
        "review_status": K.eq("review_status"),
        "adjudication_status": K.eq("adjudication_status"),
    })


@bp.route("/temperature-excursions/<xid>", methods=["GET"])
def get_excursion(xid):
    guard("GET /vaccine-distribution/temperature-excursions/{id}")
    return K.single(K.fetch("temperature_excursions", xid, "Temperature excursion"))


@bp.route("/temperature-excursions/<xid>/review", methods=["POST"])
def review_excursion(xid):
    guard("POST /vaccine-distribution/temperature-excursions/{id}/review")
    exc = K.fetch("temperature_excursions", xid, "Temperature excursion")
    if exc.get("review_status") != "REPORTED":
        raise ApiError("ERR_INVALID_STATE", "Only a REPORTED excursion may be reviewed.")
    site = h.get("storage_sites", exc.get("storage_site_id"))
    program = h.get("jurisdiction_programs", site.get("jurisdiction_program_id")) if site else None
    if site is None or site.get("inventory_status") == "FROZEN":
        raise ApiError("ERR_SITE_FROZEN")
    sla_hours = program.get("adjudication_sla_hours", 0) if program else 0
    deadline = add_hours(parse_ts(exc.get("reported_at")), sla_hours)
    if clock() > deadline:
        raise ApiError("ERR_ADJUDICATION_SLA_EXCEEDED")

    exc["review_status"] = "UNDER_REVIEW"
    exc["quarantine_status"] = "OPEN"
    exc["_reviewer_user_id"] = _acting_user()
    h.touch(exc)

    carton = h.get("cartons", exc.get("carton_id"))
    if carton:
        for member in D.family_neighbours(site["id"]):
            linked = h.get("storage_sites", member)
            if linked and linked["id"] != site["id"]:
                pass
        carton["temperature_state"] = carton.get("temperature_state")
        h.touch(carton)

    # every dose-affected slice moves to IN_REVIEW
    for slc in h.all("doses_affected_slices"):
        if slc.get("temperature_excursion_id") == exc["id"]:
            slc["closure_state"] = "IN_REVIEW"
            h.touch(slc)

    D.recompute_site(site)
    return K.single(exc)


def _acting_user():
    from flask import request
    return request.headers.get("X-User-ID")


@bp.route("/temperature-excursions/<xid>/readiness", methods=["GET"])
def readiness(xid):
    guard("GET /vaccine-distribution/temperature-excursions/{id}/readiness")
    exc = K.fetch("temperature_excursions", xid, "Temperature excursion")
    return K.single(C.readiness_view(exc))


@bp.route("/temperature-excursions/<xid>/audit", methods=["GET"])
def audit(xid):
    guard("GET /vaccine-distribution/temperature-excursions/{id}/audit")
    exc = K.fetch("temperature_excursions", xid, "Temperature excursion")
    raw = K.q("ordering", "CONSISTENT")
    ordering = str(raw).upper()
    if ordering not in ("WALLCLOCK", "CONSISTENT"):
        raise ApiError("ERR_INVALID_REQUEST", "ordering must be WALLCLOCK or CONSISTENT.")
    return K.single(C.audit_view(exc, ordering))


# ---------------------------------------------------------------------------
# DosesAffectedSlice
# ---------------------------------------------------------------------------
@bp.route("/temperature-excursions/<xid>/doses-affected-slices", methods=["POST"])
def create_slice(xid):
    guard("POST /vaccine-distribution/temperature-excursions/{id}/doses-affected-slices")
    exc = K.fetch("temperature_excursions", xid, "Temperature excursion")
    data = K.body()
    rec = h.create("doses_affected_slices", {
        "temperature_excursion_id": exc["id"],
        "closure_state": K.as_enum(K.required(data, "closure_state"), CLOSURE_STATES,
                                   "closure_state"),
        "time_slice_c": K.as_num(K.required(data, "time_slice_c"), "time_slice_c"),
        "doses_upper_bound": K.as_int(K.required(data, "doses_upper_bound"), "doses_upper_bound"),
        "status": "PENDING",
    })
    return K.created(rec)


@bp.route("/temperature-excursions/<xid>/doses-affected-slices", methods=["GET"])
def list_slices(xid):
    guard("GET /vaccine-distribution/temperature-excursions/{id}/doses-affected-slices")
    K.fetch("temperature_excursions", xid, "Temperature excursion")
    return K.list_response(h.find("doses_affected_slices", temperature_excursion_id=xid),
                           {"status": K.eq("status")})


@bp.route("/doses-affected-slices/<sid>", methods=["GET"])
def get_slice(sid):
    guard("GET /vaccine-distribution/doses-affected-slices/{id}")
    return K.single(K.fetch("doses_affected_slices", sid, "Dose-affected slice"))


@bp.route("/doses-affected-slices/<sid>/close", methods=["POST"])
def close_slice(sid):
    guard("POST /vaccine-distribution/doses-affected-slices/{id}/close")
    slc = K.fetch("doses_affected_slices", sid, "Dose-affected slice")
    if slc.get("closure_state") == "CLOSED":
        raise ApiError("ERR_INVALID_STATE", "This slice is already closed.")
    data = K.body()
    bound = K.as_int(K.required(data, "doses_upper_bound"), "doses_upper_bound")
    if bound < (slc.get("doses_upper_bound") or 0):
        raise ApiError("ERR_INVALID_REQUEST",
                       "doses_upper_bound must be at least the observed doses.")
    slc["closure_state"] = "CLOSED"
    slc["status"] = "CERTIFIED"
    slc["doses_upper_bound"] = bound
    h.touch(slc)
    return K.single(slc)


@bp.route("/doses-affected-slices/<sid>/reopen", methods=["POST"])
def reopen_slice(sid):
    guard("POST /vaccine-distribution/doses-affected-slices/{id}/reopen")
    slc = K.fetch("doses_affected_slices", sid, "Dose-affected slice")
    if slc.get("closure_state") != "CLOSED":
        raise ApiError("ERR_INVALID_STATE", "Only a CLOSED slice may be reopened.")
    exc = h.get("temperature_excursions", slc.get("temperature_excursion_id"))
    carton = h.get("cartons", exc.get("carton_id")) if exc else None
    if carton and carton.get("temperature_state") == "DESTROYED":
        raise ApiError("ERR_CARTON_DESTROYED")
    slc["closure_state"] = "IN_REVIEW"
    slc["status"] = "PENDING"
    h.touch(slc)
    return K.single(slc)


# ---------------------------------------------------------------------------
# ExcursionAdjudication
# ---------------------------------------------------------------------------
@bp.route("/excursion-adjudications", methods=["GET"])
def list_adjudications():
    guard("GET /vaccine-distribution/excursion-adjudications")
    return K.list_response(h.all("excursion_adjudications"), {
        "temperature_excursion_id": K.eq("temperature_excursion_id"),
        "outcome": K.eq("outcome"),
    })


@bp.route("/excursion-adjudications/<aid>", methods=["GET"])
def get_adjudication(aid):
    guard("GET /vaccine-distribution/excursion-adjudications/{id}")
    return K.single(K.fetch("excursion_adjudications", aid, "Excursion adjudication"))


@bp.route("/temperature-excursions/<xid>/adjudicate", methods=["POST"])
def adjudicate(xid):
    guard("POST /vaccine-distribution/temperature-excursions/{id}/adjudicate")
    exc = K.fetch("temperature_excursions", xid, "Temperature excursion")
    if exc.get("review_status") not in ("UNDER_REVIEW",):
        raise ApiError("ERR_INVALID_STATE", "Only an excursion under review may be adjudicated.")
    data = K.body()
    outcome = K.as_enum(K.required(data, "outcome"), OUTCOMES, "outcome")
    rationale = K.as_str(K.required(data, "rationale"), "rationale")
    actor = _acting_user()

    # 1. segregation of duties -- evaluated first
    if actor == exc.get("_reviewer_user_id"):
        raise ApiError("ERR_SEGREGATION_OF_DUTIES")

    carton = h.get("cartons", exc.get("carton_id"))
    site = h.get("storage_sites", exc.get("storage_site_id"))
    batch = D.batch_of_carton(carton) if carton else None
    product = D.product_of_batch(batch)

    # 2. every slice at or below the adjudicated temperature boundary must be closed
    boundary = exc.get("min_temperature_c")
    for slc in h.all("doses_affected_slices"):
        if slc.get("temperature_excursion_id") != exc["id"]:
            continue
        if slc.get("time_slice_c") is not None and boundary is not None and \
                slc["time_slice_c"] <= boundary and slc.get("closure_state") != "CLOSED":
            raise ApiError("ERR_SLICE_NOT_CLOSED")

    # 3. every cited reference must be valid at the adjudication instant
    now = clock()
    for ref in _cited_references(data):
        verification = h.get("site_equipment_verifications", ref)
        if verification is not None:
            exp = parse_ts(verification.get("certificate_expires_at"))
            if exp is not None and exp <= now:
                raise ApiError("ERR_REFERENCE_INVALID_AT_ADJUDICATION")

    band = C.breach_band(exc, product) if product else "SEVERE_COLD"
    certified, interim, pct = C.certificated_losses(exc)
    freeze_total = C.freeze_transitive_doses(exc)
    # A second adjudication performed while an appeal is open supersedes the first:
    # the record that sat APPEALED becomes SUPERSEDED, the new record's prior_outcome
    # is the outcome that was in force immediately before it, and the excursion's
    # current_resolution_trace_id points at the new one (PRD 3.8).
    superseded = [a for a in h.all("excursion_adjudications")
                  if a.get("temperature_excursion_id") == exc["id"]
                  and a.get("status") == "APPEALED"]
    prior_outcome = exc.get("adjudication_status") \
        if exc.get("adjudication_status") != "PENDING" else None
    for old in superseded:
        prior_outcome = old.get("outcome")
        old["status"] = "SUPERSEDED"
        h.touch(old)
    trace = h.create("excursion_adjudications", {
        "temperature_excursion_id": exc["id"],
        "adjudicator_user_id": actor,
        "outcome": outcome,
        "rationale": rationale,
        "effective_from": fmt(now),
        "prior_outcome": prior_outcome,
        "certified_lost_doses": certified,
        "interim_lost_doses": interim,
        "freeze_transitive_doses": freeze_total,
        "status": "DECIDED",
    })

    exc["review_status"] = "ADJUDICATED"
    exc["adjudication_status"] = outcome
    exc["adjudicated_at"] = fmt(now)
    exc["current_resolution_trace_id"] = trace["id"]
    exc["dose_impact_category"] = C.dose_impact_category(band)
    if carton and carton.get("doses_per_carton"):
        from decimal import Decimal, ROUND_HALF_UP
        exc["dose_impact_factor"] = float(
            (Decimal(certified) / Decimal(carton["doses_per_carton"]))
            .quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP)
        )
    h.touch(exc)

    if outcome == "NOT_USABLE":
        wasted = min(carton.get("remaining_doses", 0), certified)
        h.create("dose_ledger_entries", {
            "carton_id": carton["id"],
            "entry_type": "WASTE",
            "quantity_doses": -wasted,
            "occurred_at": fmt(now),
            "site_id": site["id"] if site else None,
            "reverses_entry_id": None,
            "status": "RECORDED",
        })
        carton["temperature_state"] = "DESTROYED"
        exc["quarantine_status"] = "DESTROYED"
        D.recompute_carton(carton)
    else:
        exc["quarantine_status"] = "LIFTED"
        if product is not None and carton is not None and carton.get("thawed_at"):
            effective = parse_ts(carton.get("thawwindow_expires_at") or carton.get(
                "thaw_window_expires_at"))
            carton["current_expires_at"] = fmt(C.beyond_use_for_carton(
                carton, thawed_at=parse_ts(carton.get("thawed_at"))))
            D.recompute_carton(carton)
    h.touch(exc)

    for member in D.family_closure(site["id"]) if site else []:
        linked = h.get("storage_sites", member)
        if linked:
            D.recompute_site(linked)
    return K.single(exc)


def _cited_references(data):
    refs = []
    for key in ("reference_id", "verification_id", "disposition_evidence_reference_id",
                "equipment_verification_id", "evidence_reference_id", "site_equipment_verification_id"):
        if K.has(data, key):
            refs.append(data[key])
    return refs


@bp.route("/excursion-adjudications/<aid>/withdraw", methods=["POST"])
def withdraw_adjudication(aid):
    guard("POST /vaccine-distribution/excursion-adjudications/{id}/withdraw")
    adj = K.fetch("excursion_adjudications", aid, "Excursion adjudication")
    exc = h.get("temperature_excursions", adj.get("temperature_excursion_id"))
    if not exc or exc.get("adjudication_status") != "PENDING":
        raise ApiError("ERR_INVALID_STATE",
                       "Only an adjudication reopened to PENDING may be withdrawn.")
    adj["status"] = "WITHDRAWN"
    h.touch(adj)
    return K.single(adj)


# ---------------------------------------------------------------------------
# AdjudicationAppeal
# ---------------------------------------------------------------------------
@bp.route("/temperature-excursions/<xid>/appeals", methods=["POST"])
def file_appeal(xid):
    guard("POST /vaccine-distribution/temperature-excursions/{id}/appeals")
    exc = K.fetch("temperature_excursions", xid, "Temperature excursion")
    data = K.body()
    filed_by = K.as_str(K.required(data, "filed_by_user_id"), "filed_by_user_id")
    filed_at = K.as_ts(K.required(data, "filed_at"), "filed_at")
    carton = h.get("cartons", exc.get("carton_id"))
    if carton and carton.get("temperature_state") == "DESTROYED":
        raise ApiError("ERR_CARTON_DESTROYED")
    if exc.get("review_status") != "ADJUDICATED":
        raise ApiError("ERR_INVALID_STATE", "Only an adjudicated excursion may be appealed.")
    for existing in h.all("adjudication_appeals"):
        if existing.get("temperature_excursion_id") == exc["id"] and \
                existing.get("status") == "FILED":
            raise ApiError("ERR_APPEAL_ALREADY_OPEN")
    newest = _newest_adjudication(exc["id"])
    rec = h.create("adjudication_appeals", {
        "temperature_excursion_id": exc["id"],
        "filed_by_user_id": filed_by,
        "filed_at": filed_at,
        "status": "FILED",
        "prior_trace_id": newest["id"] if newest else None,
    })
    if newest:
        newest["status"] = "APPEALED"
        h.touch(newest)
    exc["current_resolution_trace_id"] = rec["id"]
    h.touch(exc)
    return K.created(rec)


def _newest_adjudication(excursion_id):
    rows = [a for a in h.all("excursion_adjudications")
            if a.get("temperature_excursion_id") == excursion_id]
    if not rows:
        return None
    rows.sort(key=lambda a: (a.get("effective_from") or "", a.get("created_at", "")))
    return rows[-1]


@bp.route("/temperature-excursions/<xid>/appeals", methods=["GET"])
def list_appeals(xid):
    guard("GET /vaccine-distribution/temperature-excursions/{id}/appeals")
    K.fetch("temperature_excursions", xid, "Temperature excursion")
    return K.list_response(h.find("adjudication_appeals", temperature_excursion_id=xid),
                           {"status": K.eq("status")})


@bp.route("/adjudication-appeals", methods=["GET"])
def list_all_appeals():
    guard("GET /vaccine-distribution/adjudication-appeals")
    return K.list_response(h.all("adjudication_appeals"), {
        "temperature_excursion_id": K.eq("temperature_excursion_id"),
        "status": K.eq("status"),
    })


@bp.route("/adjudication-appeals/<aid>", methods=["GET"])
def get_appeal(aid):
    guard("GET /vaccine-distribution/adjudication-appeals/{id}")
    return K.single(K.fetch("adjudication_appeals", aid, "Adjudication appeal"))


@bp.route("/temperature-excursions/<xid>/appeals/<aid>/accept", methods=["POST"])
def accept_appeal(xid, aid):
    guard("POST /vaccine-distribution/temperature-excursions/{id}/appeals/{appealId}/accept")
    exc = K.fetch("temperature_excursions", xid, "Temperature excursion")
    appeal = K.fetch("adjudication_appeals", aid, "Adjudication appeal")
    if appeal.get("status") != "FILED":
        raise ApiError("ERR_APPEAL_NOT_FILED")
    adjudicated_at = parse_ts(exc.get("adjudicated_at"))
    if adjudicated_at is not None and \
            clock() > add_hours(adjudicated_at, APPEAL_WINDOW_HOURS):
        raise ApiError("ERR_APPEAL_WINDOW_CLOSED")
    appeal["status"] = "ACCEPTED"
    h.touch(appeal)
    exc["review_status"] = "UNDER_REVIEW"
    exc["adjudication_status"] = "PENDING"
    exc["adjudicated_at"] = None
    exc["quarantine_status"] = "OPEN"
    exc["current_resolution_trace_id"] = appeal.get("prior_trace_id")
    h.touch(exc)
    # reverse the not-usable write-off
    carton = h.get("cartons", exc.get("carton_id"))
    if carton:
        for entry in D.entries_of_carton(carton["id"]):
            if entry.get("entry_type") == "WASTE":
                if not any(e.get("entry_type") == "REVERSE" and
                           e.get("reverses_entry_id") == entry["id"]
                           for e in h.all("dose_ledger_entries")):
                    h.create("dose_ledger_entries", {
                        "carton_id": carton["id"],
                        "entry_type": "REVERSE",
                        "quantity_doses": -entry.get("quantity_doses", 0),
                        "occurred_at": h.now_iso(),
                        "site_id": entry.get("site_id"),
                        "reverses_entry_id": entry["id"],
                        "status": "RECORDED",
                    })
                    entry["status"] = "RECONCILED"
                    h.touch(entry)
        if carton.get("temperature_state") == "DESTROYED":
            carton["temperature_state"] = "THAWED"
        D.recompute_carton(carton)
    return K.single(exc)


@bp.route("/temperature-excursions/<xid>/appeals/<aid>/deny", methods=["POST"])
def deny_appeal(xid, aid):
    guard("POST /vaccine-distribution/temperature-excursions/{id}/appeals/{appealId}/deny")
    exc = K.fetch("temperature_excursions", xid, "Temperature excursion")
    appeal = K.fetch("adjudication_appeals", aid, "Adjudication appeal")
    if appeal.get("status") != "FILED":
        raise ApiError("ERR_APPEAL_NOT_FILED")
    newest = _newest_adjudication(exc["id"])
    if newest and _acting_user() == newest.get("adjudicator_user_id"):
        raise ApiError("ERR_SEGREGATION_OF_DUTIES")
    appeal["status"] = "DENIED"
    h.touch(appeal)
    if newest:
        newest["status"] = "DECIDED"
        h.touch(newest)
    exc["review_status"] = "ADJUDICATED"
    h.touch(exc)
    return K.single(exc)


# ---------------------------------------------------------------------------
# WastageReport
# ---------------------------------------------------------------------------
@bp.route("/wastage-reports", methods=["POST"])
def create_wastage():
    guard("POST /vaccine-distribution/wastage-reports")
    data = K.body()
    adj = K.fetch("excursion_adjudications", K.required(data, "excursion_adjudication_id"),
                  "Excursion adjudication")
    doses_reported = K.as_int(K.required(data, "doses_reported"), "doses_reported")
    certified = adj.get("certified_lost_doses", 0)
    exc = h.get("temperature_excursions", adj.get("temperature_excursion_id"))
    carton = h.get("cartons", exc.get("carton_id")) if exc else None
    doses_per_carton = carton.get("doses_per_carton", 0) if carton else 0
    variance = doses_reported - certified
    ppm = 0
    if doses_per_carton:
        from decimal import Decimal, ROUND_FLOOR
        ppm = int((Decimal(variance) / Decimal(doses_per_carton) * Decimal(1000000))
                  .to_integral_value(rounding=ROUND_FLOOR))
    rec = h.create("wastage_reports", {
        "excursion_adjudication_id": adj["id"],
        "accounting_period_start": K.as_ts(K.required(data, "accounting_period_start"),
                                           "accounting_period_start"),
        "accounting_period_end": K.as_ts(K.required(data, "accounting_period_end"),
                                         "accounting_period_end"),
        "reported_at": K.as_ts(K.required(data, "reported_at"), "reported_at"),
        "attributed_cause": K.as_enum(K.required(data, "attributed_cause"), WASTAGE_CAUSES,
                                      "attributed_cause"),
        "doses_reported": doses_reported,
        "dose_accountability_status": "OPEN",
        "diluent_doses": _diluent_doses(carton),
        "certified_doses": certified,
        "reconciliation_variance_doses": variance,
        "site_wastage_rate_ppm": ppm,
    })
    return K.created(rec)


def _diluent_doses(carton):
    if carton is None:
        return 0
    released = carton.get("cumulative_released_doses", 0)
    used = 0
    for entry in D.entries_of_carton(carton["id"]):
        if entry.get("entry_type") in ("THAW", "ADMINISTER"):
            used += abs(entry.get("quantity_doses", 0))
    return max(0, released - used)


@bp.route("/wastage-reports", methods=["GET"])
def list_wastage():
    guard("GET /vaccine-distribution/wastage-reports")
    return K.list_response(h.all("wastage_reports"), {
        "excursion_adjudication_id": K.eq("excursion_adjudication_id"),
        "attributed_cause": K.eq("attributed_cause"),
        "dose_accountability_status": K.eq("dose_accountability_status"),
    })


@bp.route("/wastage-reports/<wid>", methods=["GET"])
def get_wastage(wid):
    guard("GET /vaccine-distribution/wastage-reports/{id}")
    return K.single(K.fetch("wastage_reports", wid, "Wastage report"))


@bp.route("/wastage-reports/<wid>/reconcile", methods=["POST"])
def reconcile_wastage(wid):
    guard("POST /vaccine-distribution/wastage-reports/{id}/reconcile")
    report = K.fetch("wastage_reports", wid, "Wastage report")
    K.ensure_not_terminal(report, "wastage_reports", "dose_accountability_status")
    if report.get("dose_accountability_status") != "OPEN":
        raise ApiError("ERR_INVALID_STATE", "This report is not open for reconciliation.")
    adj = h.get("excursion_adjudications", report.get("excursion_adjudication_id"))
    exc = h.get("temperature_excursions", adj.get("temperature_excursion_id")) if adj else None
    if not adj or exc is None or exc.get("review_status") != "ADJUDICATED":
        raise ApiError("ERR_EXCURSION_NOT_ADJUDICATED")
    certified = adj.get("certified_lost_doses", 0)
    if report.get("doses_reported", 0) < certified:
        raise ApiError("ERR_INVALID_REQUEST",
                       "doses_reported must be at least the certified doses.")
    carton = h.get("cartons", exc.get("carton_id"))
    product = D.product_of_carton(carton) if carton else None
    doses_per_carton = carton.get("doses_per_carton", 0) if carton else 0
    if doses_per_carton and product:
        ratio = abs(report.get("reconciliation_variance_doses", 0)) / float(doses_per_carton)
        if ratio > product.get("wastage_threshold_pct", 0):
            raise ApiError("ERR_WASTAGE_THRESHOLD_EXCEEDED")
    report["dose_accountability_status"] = "RECONCILED"
    h.touch(report)
    for entry in h.all("dose_ledger_entries"):
        if entry.get("carton_id") == (carton["id"] if carton else None) and \
                entry.get("entry_type") in D.LOSS_ENTRY_TYPES:
            entry["status"] = "RECONCILED"
            h.touch(entry)
    for period in h.all("reporting_periods"):
        if period.get("jurisdiction_program_id") == (
                h.get("storage_sites", exc.get("storage_site_id")) or {}).get("jurisdiction_program_id"):
            summary = C.accountability(period, "INTERIM")
            period["unaccounted_doses"] = summary["unaccounted_doses"]
            period["wastage_rate_basis_points"] = summary["wastage_rate_basis_points"]
            h.touch(period)
    return K.single(report)