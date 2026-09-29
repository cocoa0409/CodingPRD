"""Every read endpoint (PRD 4, the 25 GET rows)."""
from flask import Blueprint, request

import auth
import derive
import envelope
import store
from helpers import (filter_rows, find, listing, own_establishments, scope_establishment,
                     view_citation, view_establishment, view_practitioner, view_workstation)

reads_bp = Blueprint("reads", __name__)

CREATED_ASC = (lambda r: (r["created_at"], r["_seq"]), False)
CREATED_DESC = (lambda r: (r["created_at"], r["_seq"]), True)
ID_ASC = (lambda r: r["id"], False)

ALL = auth.ROLES


# ---------------------------------------------------------- establishments
@reads_bp.get("/establishments/<eid>")
def get_establishment(eid):
    ctx = auth.authenticate(("BoardAdmin", "Inspector", "HearingOfficer",
                             "EstablishmentOwner", "HealthAuthorityLiaison"))
    est = find("Establishment", eid)
    scope_establishment(ctx, est["id"])
    return envelope.ok(view_establishment(est))


@reads_bp.get("/establishments")
def list_establishments():
    auth.authenticate(("BoardAdmin", "Inspector", "HearingOfficer", "HealthAuthorityLiaison"))
    rows = list(store.establishments.values())
    for e in rows:
        derive.compute_establishment(e)
    rows = filter_rows(rows, request.args, {
        "license_status": ("license_status", "str"),
        "county_code": ("county_code", "str"),
        "compliance_posture": ("compliance_posture", "str"),
        "establishment_type": ("establishment_type", "str"),
    })
    return listing(rows, [CREATED_DESC, ID_ASC], derive.ser_establishment, request.args)


# ----------------------------------------------------------- practitioners
@reads_bp.get("/practitioners/<pid>")
def get_practitioner(pid):
    ctx = auth.authenticate(("BoardAdmin", "Inspector", "HearingOfficer", "SchoolRegistrar",
                             "Practitioner", "EstablishmentOwner"))
    prac = find("Practitioner", pid)
    if ctx.is_registrar and prac["school_id"] != ctx.user_id:
        auth.deny()
    if ctx.is_prac and prac["id"] != ctx.user_id:
        auth.deny()
    if ctx.is_owner and not auth.practitioner_reachable_from_establishment(prac["id"], ctx.user_id):
        auth.deny()
    return envelope.ok(view_practitioner(prac))


@reads_bp.get("/practitioners")
def list_practitioners():
    ctx = auth.authenticate(("BoardAdmin", "Inspector", "HearingOfficer", "SchoolRegistrar"))
    rows = list(store.practitioners.values())
    for p in rows:
        derive.compute_practitioner(p)
    if ctx.is_registrar:
        rows = [p for p in rows if p["school_id"] == ctx.user_id]
    rows = filter_rows(rows, request.args, {
        "school_id": ("school_id", "str"),
        "license_status": ("license_status", "str"),
        "license_type": ("license_type", "str"),
        "exam_eligible": ("exam_eligible", "bool"),
    })
    return listing(rows, [CREATED_DESC, ID_ASC], derive.ser_practitioner, request.args)


# ----------------------------------------------------------------- schools
@reads_bp.get("/schools/<sid>")
def get_school(sid):
    auth.authenticate(("BoardAdmin", "Inspector", "SchoolRegistrar", "Practitioner"))
    return envelope.ok(derive.ser_school(find("School", sid)))


# -------------------------------------------------------- training records
def _training_visible(ctx, t):
    if ctx.is_registrar:
        return t["school_id"] == ctx.user_id
    if ctx.is_prac:
        return t["practitioner_id"] == ctx.user_id or t["sponsor_practitioner_id"] == ctx.user_id
    return True


@reads_bp.get("/training-records/<tid>")
def get_training_record(tid):
    ctx = auth.authenticate(("BoardAdmin", "SchoolRegistrar", "Practitioner"))
    row = find("TrainingRecord", tid)
    if not _training_visible(ctx, row):
        auth.deny()
    return envelope.ok(derive.ser_training_record(row))


@reads_bp.get("/training-records")
def list_training_records():
    ctx = auth.authenticate(("BoardAdmin", "SchoolRegistrar", "Practitioner"))
    rows = [t for t in store.training_records.values() if _training_visible(ctx, t)]
    rows = filter_rows(rows, request.args, {
        "practitioner_id": ("practitioner_id", "str"),
        "school_id": ("school_id", "str"),
        "sponsor_practitioner_id": ("sponsor_practitioner_id", "str"),
        "credit_type": ("credit_type", "str"),
        "discipline": ("discipline", "str"),
    })
    keys = [(lambda r: r["performed_on"], False), CREATED_ASC]
    return listing(rows, keys, derive.ser_training_record, request.args)


# ------------------------------------------------------------ workstations
@reads_bp.get("/workstations/<wid>")
def get_workstation(wid):
    ctx = auth.authenticate(("BoardAdmin", "Inspector", "EstablishmentOwner", "Practitioner"))
    ws = find("Workstation", wid)
    scope_establishment(ctx, ws["establishment_id"])
    if ctx.is_prac and not auth.practitioner_touches_workstation(ctx.user_id, ws):
        auth.deny()
    return envelope.ok(view_workstation(ws))


@reads_bp.get("/workstations")
def list_workstations():
    ctx = auth.authenticate(("BoardAdmin", "Inspector", "EstablishmentOwner"))
    rows = own_establishments(ctx, list(store.workstations.values()))
    for w in rows:
        derive.compute_workstation(w)
    rows = filter_rows(rows, request.args, {
        "establishment_id": ("establishment_id", "str"),
        "posted_practitioner_id": ("posted_practitioner_id", "str"),
        "station_type": ("station_type", "str"),
        "posting_status": ("posting_status", "str"),
    })
    keys = [(lambda r: r["station_number"], False), CREATED_ASC]
    return listing(rows, keys, derive.ser_workstation, request.args)


@reads_bp.get("/workstations/<wid>/sanitation-logs")
def list_sanitation_logs(wid):
    ctx = auth.authenticate(("BoardAdmin", "Inspector", "EstablishmentOwner",
                             "HealthAuthorityLiaison"))
    ws = find("Workstation", wid)
    scope_establishment(ctx, ws["establishment_id"])
    rows = [s for s in store.sanitation_logs.values() if s["workstation_id"] == wid]
    rows = filter_rows(rows, request.args, {"log_type": ("log_type", "str")})
    keys = [(lambda r: r["performed_at"], False), CREATED_ASC]
    return listing(rows, keys, derive.ser_sanitation_log, request.args)


# ----------------------------------------------------------- booth rentals
@reads_bp.get("/booth-rentals/<rid>")
def get_booth_rental(rid):
    ctx = auth.authenticate(("BoardAdmin", "Inspector", "EstablishmentOwner", "Practitioner"))
    rental = find("BoothRental", rid)
    scope_establishment(ctx, auth.est_of_rental(rental))
    if ctx.is_prac and rental["practitioner_id"] != ctx.user_id:
        auth.deny()
    return envelope.ok(derive.ser_booth_rental(rental))


@reads_bp.get("/booth-rentals")
def list_booth_rentals():
    ctx = auth.authenticate(("BoardAdmin", "Inspector", "EstablishmentOwner", "Practitioner"))
    rows = list(store.booth_rentals.values())
    if ctx.is_owner:
        rows = [r for r in rows if auth.est_of_rental(r) == ctx.user_id]
    if ctx.is_prac:
        rows = [r for r in rows if r["practitioner_id"] == ctx.user_id]
    rows = filter_rows(rows, request.args, {
        "workstation_id": ("workstation_id", "str"),
        "practitioner_id": ("practitioner_id", "str"),
        "status": ("status", "str"),
        "rental_type": ("rental_type", "str"),
    })
    keys = [(lambda r: r["term_start_at"], False), CREATED_ASC]
    return listing(rows, keys, derive.ser_booth_rental, request.args)


# ------------------------------------------------------------- inspections
@reads_bp.get("/inspections/<iid>")
def get_inspection(iid):
    ctx = auth.authenticate(("BoardAdmin", "Inspector", "HearingOfficer", "EstablishmentOwner",
                             "HealthAuthorityLiaison"))
    insp = find("Inspection", iid)
    scope_establishment(ctx, insp["establishment_id"])
    return envelope.ok(derive.ser_inspection(insp))


@reads_bp.get("/inspections")
def list_inspections():
    ctx = auth.authenticate(("BoardAdmin", "Inspector", "HearingOfficer", "EstablishmentOwner",
                             "HealthAuthorityLiaison"))
    rows = own_establishments(ctx, list(store.inspections.values()))
    rows = filter_rows(rows, request.args, {
        "establishment_id": ("establishment_id", "str"),
        "reinspection_of_id": ("reinspection_of_id", "str"),
        "status": ("status", "str"),
        "inspection_type": ("inspection_type", "str"),
        "hazard_state": ("hazard_state", "str"),
    })
    keys = [(lambda r: r["window_start_at"], True), CREATED_DESC]
    return listing(rows, keys, derive.ser_inspection, request.args)


# -------------------------------------------- violation codes and findings
@reads_bp.get("/violation-codes/<vid>")
def get_violation_code(vid):
    auth.authenticate(("BoardAdmin", "Inspector", "HearingOfficer", "EstablishmentOwner"))
    return envelope.ok(derive.ser_violation_code(find("ViolationCode", vid)))


@reads_bp.get("/violation-findings/<fid>")
def get_violation_finding(fid):
    ctx = auth.authenticate(("BoardAdmin", "Inspector", "HearingOfficer", "EstablishmentOwner"))
    row = find("ViolationFinding", fid)
    scope_establishment(ctx, auth.est_of_finding(row))
    return envelope.ok(derive.ser_finding(row))


@reads_bp.get("/violation-findings")
def list_violation_findings():
    ctx = auth.authenticate(("BoardAdmin", "Inspector", "HearingOfficer", "EstablishmentOwner"))
    rows = list(store.violation_findings.values())
    if ctx.is_owner:
        rows = [f for f in rows if auth.est_of_finding(f) == ctx.user_id]
    rows = filter_rows(rows, request.args, {
        "inspection_id": ("inspection_id", "str"),
        "violation_code_id": ("violation_code_id", "str"),
        "attributed_practitioner_id": ("attributed_practitioner_id", "str"),
        "workstation_id": ("workstation_id", "str"),
        "declared_hazard": ("declared_hazard", "bool"),
    })
    return listing(rows, [CREATED_ASC], derive.ser_finding, request.args)


# --------------------------------------------------- citations and hearings
def _citation_visible(ctx, cit):
    if ctx.is_owner:
        return auth.est_of_citation(cit) == ctx.user_id
    if ctx.is_prac:
        return cit["subject_practitioner_id"] == ctx.user_id
    return True


@reads_bp.get("/citations/<cid>")
def get_citation(cid):
    ctx = auth.authenticate(("BoardAdmin", "Inspector", "HearingOfficer", "EstablishmentOwner",
                             "Practitioner"))
    cit = find("Citation", cid)
    if not _citation_visible(ctx, cit):
        auth.deny()
    return envelope.ok(view_citation(cit))


@reads_bp.get("/citations")
def list_citations():
    ctx = auth.authenticate(("BoardAdmin", "Inspector", "HearingOfficer", "EstablishmentOwner",
                             "Practitioner"))
    rows = [c for c in store.citations.values() if _citation_visible(ctx, c)]
    for c in rows:
        derive.recompute_citation_outstanding(c)
    rows = filter_rows(rows, request.args, {
        "inspection_id": ("inspection_id", "str"),
        "subject_practitioner_id": ("subject_practitioner_id", "str"),
        "subject_type": ("subject_type", "str"),
        "status": ("status", "str"),
    })
    keys = [(lambda r: r["issued_at"], True), CREATED_DESC]
    return listing(rows, keys, derive.ser_citation, request.args)


@reads_bp.get("/citations/<cid>/hearings")
def list_hearings(cid):
    ctx = auth.authenticate(("BoardAdmin", "HearingOfficer", "EstablishmentOwner", "Practitioner"))
    cit = find("Citation", cid)
    if not _citation_visible(ctx, cit):
        auth.deny()
    rows = [h for h in store.hearings.values() if h["citation_id"] == cid]
    keys = [(lambda r: r["round_index"], False)]
    return listing(rows, keys, derive.ser_hearing, request.args)


@reads_bp.get("/hearings/<hid>")
def get_hearing(hid):
    ctx = auth.authenticate(("BoardAdmin", "HearingOfficer", "EstablishmentOwner", "Practitioner"))
    hearing = find("Hearing", hid)
    cit = store.citations.get(hearing["citation_id"])
    if cit is not None and not _citation_visible(ctx, cit):
        auth.deny()
    return envelope.ok(derive.ser_hearing(hearing))


# ------------------------------------------------------ infection incidents
@reads_bp.get("/infection-incidents/<iid>")
def get_incident(iid):
    ctx = auth.authenticate(("BoardAdmin", "Inspector", "HealthAuthorityLiaison",
                             "EstablishmentOwner"))
    row = find("InfectionIncident", iid)
    scope_establishment(ctx, row["establishment_id"])
    return envelope.ok(derive.ser_incident(row))


@reads_bp.get("/infection-incidents")
def list_incidents():
    auth.authenticate(("BoardAdmin", "Inspector", "HealthAuthorityLiaison"))
    rows = list(store.infection_incidents.values())
    rows = filter_rows(rows, request.args, {
        "establishment_id": ("establishment_id", "str"),
        "suspected_practitioner_id": ("suspected_practitioner_id", "str"),
        "status": ("status", "str"),
    })
    keys = [(lambda r: r["reported_at"], True), CREATED_DESC]
    return listing(rows, keys, derive.ser_incident, request.args)


# ----------------------------------------------------------- ledger entries
@reads_bp.get("/ledger-entries/<lid>")
def get_ledger_entry(lid):
    auth.authenticate(("BoardAdmin", "HearingOfficer"))
    return envelope.ok(derive.ser_ledger_entry(find("LedgerEntry", lid)))


@reads_bp.get("/ledger-entries")
def list_ledger_entries():
    auth.authenticate(("BoardAdmin", "HearingOfficer"))
    rows = list(store.ledger_entries.values())
    rows = filter_rows(rows, request.args, {
        "establishment_id": ("establishment_id", "str"),
        "citation_id": ("citation_id", "str"),
        "practitioner_id": ("practitioner_id", "str"),
        "inspection_id": ("inspection_id", "str"),
        "ledger_type": ("ledger_type", "str"),
        "entry_reason": ("entry_reason", "str"),
    })
    keys = [(lambda r: r["occurred_at"], False), CREATED_ASC]
    return listing(rows, keys, derive.ser_ledger_entry, request.args)
