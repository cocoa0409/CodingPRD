"""The term permit lifecycle (PRD 3.3)."""

from flask import Blueprint

import auth
import constants as K
import derive
import envelope
from errors import ApiError
import find
import gates
import services
import store
from validate import date_range, field, json_body, parse_body

bp = Blueprint("permits", __name__)

APPLICATION_FIELDS = [
    field("allotment_id", "str"),
    field("permittee_id", "str"),
    field("base_property_id", "str"),
    field("requested_aums", "int", min=1),
    field("term_start_date", "date"),
    field("term_end_date", "date"),
    field("livestock_kind", "enum", values=K.LIVESTOCK_KIND),
]

RENEW_FIELDS = [
    field("term_start_date", "date"),
    field("term_end_date", "date"),
    field("requested_aums", "int", min=1),
    field("base_property_id", "str"),
]

TRANSFER_FIELDS = [
    field("transferee_permittee_id", "str"),
    field("base_property_id", "str"),
    field("term_start_date", "date"),
    field("term_end_date", "date"),
    field("requested_aums", "int", min=1),
]


def preference_priority(base_property):
    if base_property is not None and base_property["base_property_type"] == "LAND":
        return 1
    return 2


def predecessor_invalid(message):
    raise ApiError("ERR_PREDECESSOR_PERMIT_INVALID", message)


def has_successor(permit_id):
    for row in store.rows("permits"):
        if row["predecessor_permit_id"] == permit_id:
            return True
    return False


def owned_by(base_property, permittee_id):
    """Priority 13."""
    if base_property["permittee_id"] != permittee_id:
        raise ApiError("ERR_BASE_PROPERTY_NOT_OWNED",
                       "the base property belongs to another permittee")


@bp.post("/grazing-permits")
def create_permit():
    body = parse_body(json_body(), APPLICATION_FIELDS)
    date_range(body["term_start_date"], body["term_end_date"], True,
               "term_start_date must be strictly before term_end_date")
    auth.authenticate(["AuthorizedOfficer"])
    allotment = find.need("allotments", body["allotment_id"])
    permittee = find.need("permittees", body["permittee_id"])
    base_property = find.need("base_properties", body["base_property_id"])
    owned_by(base_property, permittee["id"])
    gates.qualified(base_property, body["requested_aums"])
    record = store.insert("permits", {
        "allotment_id": allotment["id"],
        "permittee_id": permittee["id"],
        "base_property_id": base_property["id"],
        "predecessor_permit_id": None,
        "permitted_aums": body["requested_aums"],
        "term_start_date": body["term_start_date"].isoformat(),
        "term_end_date": body["term_end_date"].isoformat(),
        "livestock_kind": body["livestock_kind"],
        "preference_priority": 2,
        "permit_status": "PENDING_REVIEW",
        "account_status": "CURRENT",
        "suspension_reason": None,
        "consecutive_nonuse_years": 0,
    })
    return envelope.created(derive.permit_json(record))


@bp.get("/grazing-permits")
def list_permits():
    envelope.page_params()
    actor = auth.any_operational()
    records = envelope.sort_default(store.rows("permits"))
    records = auth.scope_permittee_rows(actor, records,
                                       lambda row: row["permittee_id"])
    records = find.apply_filters(records, [
        ("allotment_id", "allotment_id", "str"),
        ("permittee_id", "permittee_id", "str"),
        ("base_property_id", "base_property_id", "str"),
        ("predecessor_permit_id", "predecessor_permit_id", "str"),
        ("permit_status", "permit_status", "str"),
        ("account_status", "account_status", "str"),
    ])
    return envelope.paginate(records, derive.permit_json)


@bp.get("/grazing-permits/<permit_id>")
def get_permit(permit_id):
    actor = auth.any_operational()
    permit = find.need("permits", permit_id)
    auth.require_own(actor, permit["permittee_id"])
    return envelope.ok(derive.permit_json(permit))


@bp.post("/grazing-permits/<permit_id>/issue")
def issue_permit(permit_id):
    auth.authenticate(["AuthorizedOfficer"])
    permit = find.need("permits", permit_id)
    if permit["permit_status"] != "PENDING_REVIEW":
        gates.state("ERR_PERMIT_STATE_INVALID",
                    "only a permit in PENDING_REVIEW may be issued")
    allotment = derive.allotment_of_permit(permit)
    base_property = store.get("base_properties", permit["base_property_id"])
    gates.closed(allotment)
    gates.health(allotment)
    gates.qualified(base_property, permit["permitted_aums"])
    gates.debt(permit["permittee_id"])
    gates.capacity(allotment, permit["permitted_aums"])
    permit["permit_status"] = "ISSUED"
    permit["preference_priority"] = preference_priority(base_property)
    store.touch(permit)
    return envelope.ok(derive.permit_json(permit))


@bp.post("/grazing-permits/<permit_id>/renew")
def renew_permit(permit_id):
    body = parse_body(json_body(), RENEW_FIELDS)
    date_range(body["term_start_date"], body["term_end_date"], True,
               "term_start_date must be strictly before term_end_date")
    auth.authenticate(["AuthorizedOfficer"])
    permit = find.need("permits", permit_id)
    supplied_property = find.need("base_properties", body["base_property_id"])
    allotment = derive.allotment_of_permit(permit)
    gates.closed(allotment)
    gates.health(allotment)
    owned_by(supplied_property, permit["permittee_id"])
    if permit["permit_status"] != "ISSUED":
        predecessor_invalid("only an ISSUED permit may be renewed")
    if has_successor(permit["id"]):
        predecessor_invalid("the permit already has a successor")
    if body["term_start_date"].isoformat() < permit["term_end_date"]:
        predecessor_invalid("the successor term must start on or after the "
                            "predecessor's term_end_date")
    gates.qualified(supplied_property, permit["permitted_aums"])
    if services.nonuse_run(permit) >= K.MAX_CONSECUTIVE_NONUSE_YEARS:
        raise ApiError("ERR_NONUSE_LIMIT_EXCEEDED",
                       "the preference has lapsed through consecutive non-use")
    gates.debt(permit["permittee_id"])
    gates.capacity(allotment, permit["permitted_aums"])

    run = services.recompute_consecutive_nonuse_years(permit)
    permit["permit_status"] = "EXPIRED"
    store.touch(permit)
    inherited = store.get("base_properties", permit["base_property_id"])
    successor = store.insert("permits", {
        "allotment_id": permit["allotment_id"],
        "permittee_id": permit["permittee_id"],
        "base_property_id": permit["base_property_id"],
        "predecessor_permit_id": permit["id"],
        "permitted_aums": permit["permitted_aums"],
        "term_start_date": body["term_start_date"].isoformat(),
        "term_end_date": body["term_end_date"].isoformat(),
        "livestock_kind": permit["livestock_kind"],
        "preference_priority": preference_priority(inherited),
        "permit_status": "ISSUED",
        "account_status": "CURRENT",
        "suspension_reason": None,
        "consecutive_nonuse_years": run,
    })
    return envelope.created(derive.permit_json(successor))


@bp.post("/grazing-permits/<permit_id>/transfer")
def transfer_permit(permit_id):
    body = parse_body(json_body(), TRANSFER_FIELDS)
    date_range(body["term_start_date"], body["term_end_date"], True,
               "term_start_date must be strictly before term_end_date")
    auth.authenticate(["AuthorizedOfficer"])
    permit = find.need("permits", permit_id)
    transferee = find.need("permittees", body["transferee_permittee_id"])
    supplied_property = find.need("base_properties", body["base_property_id"])
    allotment = derive.allotment_of_permit(permit)
    # PRD 2.6 priority 8: transfer is declared as the ISSUED -> TRANSFERRED
    # transition, so a source permit in any other state fails transition
    # legality with ERR_PERMIT_STATE_INVALID. That check outranks the priority 15
    # preference-chain code which restates the same fact, because "the checks
    # below are evaluated in ascending order of the numbers given".
    if permit["permit_status"] != "ISSUED":
        gates.state("ERR_PERMIT_STATE_INVALID",
                    "only an ISSUED permit may be transferred")
    gates.closed(allotment)
    gates.health(allotment)
    owned_by(supplied_property, transferee["id"])
    if has_successor(permit["id"]):
        predecessor_invalid("the permit already has a successor")
    gates.qualified(supplied_property, permit["permitted_aums"])
    gates.debt(transferee["id"])
    gates.capacity(allotment, permit["permitted_aums"])

    permit["permit_status"] = "TRANSFERRED"
    permit["suspension_reason"] = None
    store.touch(permit)
    for aoi in store.rows("aois"):
        if aoi["permit_id"] == permit["id"] \
                and aoi["aoi_status"] in ("DRAFT", "ISSUED"):
            services.void_aoi(aoi)
    successor = store.insert("permits", {
        "allotment_id": permit["allotment_id"],
        "permittee_id": transferee["id"],
        "base_property_id": supplied_property["id"],
        "predecessor_permit_id": permit["id"],
        "permitted_aums": permit["permitted_aums"],
        "term_start_date": permit["term_start_date"],
        "term_end_date": permit["term_end_date"],
        "livestock_kind": permit["livestock_kind"],
        "preference_priority": preference_priority(supplied_property),
        "permit_status": "ISSUED",
        "account_status": "CURRENT",
        "suspension_reason": None,
        "consecutive_nonuse_years": 0,
    })
    return envelope.created(derive.permit_json(successor))
