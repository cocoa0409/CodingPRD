"""The twenty read endpoints of PRD 4."""
from flask import Blueprint

import auth
import calc
import envelope
import resolve
import serialize
import shape
import store

bp = Blueprint("read", __name__)

ALL_READERS = ("Proponent", "WildlifeAgency", "Auditor")
AGENCY_AND_AUDITOR = ("WildlifeAgency", "Auditor")


# ------------------------------------------------------------- species ------


@bp.route("/species/<sid>", methods=["GET"])
def get_species(sid):
    caller = auth.authenticate(ALL_READERS)
    row = resolve.species(sid)
    auth.require_owner(caller, None)
    return envelope.obj(serialize.species(row))


@bp.route("/species/<sid>/critical-habitat-units", methods=["GET"])
def list_habitat_units(sid):
    caller = auth.authenticate(ALL_READERS)
    resolve.species(sid)
    auth.require_owner(caller, None)
    rows = store.where("habitat_units", species_id=sid)
    return envelope.unpaginated([serialize.habitat_unit(r) for r in rows])


@bp.route("/species/<sid>/conservation-banks", methods=["GET"])
def list_species_banks(sid):
    caller = auth.authenticate(ALL_READERS)
    resolve.species(sid)
    auth.require_owner(caller, None)
    rows = store.where("banks", covered_species_id=sid)
    return envelope.unpaginated([serialize.bank(r) for r in rows])


# ----------------------------------------------------------- proponents -----


@bp.route("/proponents/<pid>", methods=["GET"])
def get_proponent(pid):
    caller = auth.authenticate(ALL_READERS)
    row = resolve.proponent(pid)
    auth.require_owner(caller, row["id"])
    # Clock-dependent: re-derived and persisted on every read.
    calc.refresh_compliance(row)
    return envelope.obj(serialize.proponent(row))


# ------------------------------------------------------- project actions ----


@bp.route("/project-actions", methods=["GET"])
def list_actions():
    caller = auth.authenticate(ALL_READERS)
    auth.require_identity(caller)
    limit, offset = shape.paging()
    proponent_id = shape.query_str("proponent_id")
    consultation_id = shape.query_str("active_consultation_id")
    status = shape.query_str("status")
    effect = shape.query_str("effect_determination")

    rows = store.ordered(store.values("actions"))
    if proponent_id is not None:
        rows = [r for r in rows if r["proponent_id"] == proponent_id]
    if consultation_id is not None:
        rows = [r for r in rows if r.get("active_consultation_id") == consultation_id]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    if effect is not None:
        rows = [r for r in rows if r["effect_determination"] == effect]

    total = len(rows)
    window = rows[offset:offset + limit]
    return envelope.paginated(
        [serialize.action(r) for r in window], limit, offset, total
    )


@bp.route("/project-actions/<aid>", methods=["GET"])
def get_action(aid):
    caller = auth.authenticate(ALL_READERS)
    row = resolve.action(aid)
    auth.require_owner(caller, auth.owner_of_action(row))
    return envelope.obj(serialize.action(row))


@bp.route("/project-actions/<aid>/consultations", methods=["GET"])
def list_action_consultations(aid):
    caller = auth.authenticate(ALL_READERS)
    row = resolve.action(aid)
    auth.require_owner(caller, auth.owner_of_action(row))
    rows = store.where("consultations", project_action_id=aid)
    return envelope.unpaginated([serialize.consultation(r) for r in rows])


@bp.route("/project-actions/<aid>/habitat-conservation-plans", methods=["GET"])
def list_action_plans(aid):
    caller = auth.authenticate(ALL_READERS)
    row = resolve.action(aid)
    auth.require_owner(caller, auth.owner_of_action(row))
    rows = store.where("plans", project_action_id=aid)
    return envelope.unpaginated([serialize.plan(r) for r in rows])


# ------------------------------------------- presence determinations --------


@bp.route("/presence-determinations", methods=["GET"])
def list_determinations():
    caller = auth.authenticate(ALL_READERS)
    auth.require_identity(caller)
    limit, offset = shape.paging()
    action_id = shape.query_str("project_action_id")
    species_id = shape.query_str("species_id")
    unit_id = shape.query_str("critical_habitat_unit_id")
    status = shape.query_str("presence_status")
    reevaluation = shape.query_bool("requires_reevaluation")

    rows = store.ordered(store.values("determinations"))
    if action_id is not None:
        rows = [r for r in rows if r["project_action_id"] == action_id]
    if species_id is not None:
        rows = [r for r in rows if r["species_id"] == species_id]
    if unit_id is not None:
        rows = [r for r in rows if r.get("critical_habitat_unit_id") == unit_id]
    if status is not None:
        rows = [r for r in rows if r["presence_status"] == status]
    if reevaluation is not None:
        rows = [r for r in rows if r["requires_reevaluation"] == reevaluation]

    total = len(rows)
    window = rows[offset:offset + limit]
    return envelope.paginated(
        [serialize.determination(r) for r in window], limit, offset, total
    )


@bp.route("/presence-determinations/<did>", methods=["GET"])
def get_determination(did):
    caller = auth.authenticate(ALL_READERS)
    row = resolve.determination(did)
    auth.require_owner(caller, auth.owner_of_determination(row))
    return envelope.obj(serialize.determination(row))


# --------------------------------------------------------- consultations ----


@bp.route("/consultations/<cid>", methods=["GET"])
def get_consultation(cid):
    caller = auth.authenticate(ALL_READERS)
    row = resolve.consultation(cid)
    auth.require_owner(caller, auth.owner_of_consultation(row))
    return envelope.obj(serialize.consultation(row))


@bp.route("/consultations/<cid>/biological-opinions", methods=["GET"])
def list_opinions(cid):
    caller = auth.authenticate(ALL_READERS)
    row = resolve.consultation(cid)
    auth.require_owner(caller, auth.owner_of_consultation(row))
    rows = store.where("opinions", consultation_id=cid)
    return envelope.unpaginated([serialize.opinion(r) for r in rows])


# ----------------------------------------------------- conservation banks ---


@bp.route("/conservation-banks/<bid>", methods=["GET"])
def get_bank(bid):
    caller = auth.authenticate(ALL_READERS)
    row = resolve.bank(bid)
    auth.require_owner(caller, None)
    return envelope.obj(serialize.bank(row))


@bp.route("/conservation-banks/<bid>/mitigation-commitments", methods=["GET"])
def list_bank_commitments(bid):
    auth.authenticate(AGENCY_AND_AUDITOR)
    resolve.bank(bid)
    rows = store.where("commitments", conservation_bank_id=bid)
    return envelope.unpaginated([serialize.commitment(r) for r in rows])


# --------------------------------------------------------------- plans ------


@bp.route("/habitat-conservation-plans/<hid>", methods=["GET"])
def get_plan(hid):
    caller = auth.authenticate(ALL_READERS)
    row = resolve.plan(hid)
    auth.require_owner(caller, auth.owner_of_plan(row))
    return envelope.obj(serialize.plan(row))


@bp.route("/habitat-conservation-plans/<hid>/mitigation-commitments",
          methods=["GET"])
def list_plan_commitments(hid):
    caller = auth.authenticate(ALL_READERS)
    row = resolve.plan(hid)
    auth.require_owner(caller, auth.owner_of_plan(row))
    rows = store.where("commitments", hcp_id=hid)
    return envelope.unpaginated([serialize.commitment(r) for r in rows])


@bp.route("/habitat-conservation-plans/<hid>/incidental-take-permits",
          methods=["GET"])
def list_plan_permits(hid):
    caller = auth.authenticate(ALL_READERS)
    row = resolve.plan(hid)
    auth.require_owner(caller, auth.owner_of_plan(row))
    rows = store.where("permits", hcp_id=hid)
    return envelope.unpaginated([serialize.permit(r) for r in rows])


@bp.route("/habitat-conservation-plans/<hid>/changed-circumstance-events",
          methods=["GET"])
def list_plan_events(hid):
    caller = auth.authenticate(ALL_READERS)
    row = resolve.plan(hid)
    auth.require_owner(caller, auth.owner_of_plan(row))
    rows = store.where("events", hcp_id=hid)
    return envelope.unpaginated([serialize.event(r) for r in rows])


# ------------------------------------------------------------- permits ------


@bp.route("/incidental-take-permits/<pid>", methods=["GET"])
def get_permit(pid):
    caller = auth.authenticate(ALL_READERS)
    row = resolve.permit(pid)
    auth.require_owner(caller, auth.owner_of_permit(row))
    return envelope.obj(serialize.permit(row))


@bp.route("/incidental-take-permits/<pid>/monitoring-reports", methods=["GET"])
def list_permit_reports(pid):
    caller = auth.authenticate(ALL_READERS)
    row = resolve.permit(pid)
    auth.require_owner(caller, auth.owner_of_permit(row))
    rows = store.where("reports", permit_id=pid)
    return envelope.unpaginated([serialize.report(r) for r in rows])
