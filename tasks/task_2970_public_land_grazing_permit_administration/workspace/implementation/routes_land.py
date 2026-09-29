"""Allotments, pastures, permittees and base properties (PRD 3.1 and 3.2)."""

import re
from decimal import Decimal

from flask import Blueprint

import auth
import constants as K
import derive
import envelope
from errors import ApiError
import find
import store
from validate import bad, field, json_body, parse_body

bp = Blueprint("land", __name__)

ADMIN_UNIT_RE = re.compile(r"^[A-Z]{2}-[0-9]{3}$")

ALLOTMENT_FIELDS = [
    field("name", "str", min_len=1, max_len=120),
    field("admin_unit_code", "str"),
    field("acres", "int", min=1),
    field("total_permitted_aums", "int", min=1),
    field("season_start", "mmdd"),
    field("season_end", "mmdd"),
    field("required_pasture_rotation_count", "int", min=1, required=False, default=2),
]


@bp.post("/allotments")
def create_allotment():
    body = parse_body(json_body(), ALLOTMENT_FIELDS)
    if not ADMIN_UNIT_RE.match(body["admin_unit_code"]):
        bad("admin_unit_code must be two uppercase letters, a hyphen and three digits")
    if body["season_end"] <= body["season_start"]:
        bad("season_end must fall strictly after season_start")
    auth.authenticate(["AuthorizedOfficer"])
    record = store.insert("allotments", {
        "name": body["name"],
        "admin_unit_code": body["admin_unit_code"],
        "acres": body["acres"],
        "total_permitted_aums": body["total_permitted_aums"],
        "season_start": body["season_start"],
        "season_end": body["season_end"],
        "required_pasture_rotation_count": body["required_pasture_rotation_count"],
        "stocking_adjustment_pct": Decimal("0.0000"),
        "allotment_status": "OPEN",
        "health_determination": "NOT_ASSESSED",
    })
    return envelope.created(derive.allotment_json(record))


@bp.get("/allotments")
def list_allotments():
    envelope.page_params()
    auth.any_operational()
    records = find.apply_filters(envelope.sort_default(store.rows("allotments")), [
        ("allotment_status", "allotment_status", "str"),
        ("health_determination", "health_determination", "str"),
        ("admin_unit_code", "admin_unit_code", "str"),
    ])
    return envelope.paginate(records, derive.allotment_json)


@bp.get("/allotments/<allotment_id>")
def get_allotment(allotment_id):
    auth.any_operational()
    return envelope.ok(derive.allotment_json(find.need("allotments", allotment_id)))


PASTURE_FIELDS = [
    field("name", "str", min_len=1, max_len=80),
    field("pasture_aum_capacity", "int", min=1),
    field("sequence_order", "int", min=1),
    field("rest_required", "bool", required=False, default=False),
]


@bp.post("/allotments/<allotment_id>/pastures")
def create_pasture(allotment_id):
    body = parse_body(json_body(), PASTURE_FIELDS)
    auth.authenticate(["AuthorizedOfficer"])
    allotment = find.need("allotments", allotment_id)
    siblings = [row for row in store.rows("pastures")
                if row["allotment_id"] == allotment["id"]]
    taken = {row["sequence_order"] for row in siblings}
    wanted = body["sequence_order"]
    if wanted in taken:
        raise_sequence_conflict("sequence_order %d is already taken" % wanted)
    if wanted > 1 and (wanted - 1) not in taken:
        raise_sequence_conflict("the rotation sequence must be dense from 1")
    record = store.insert("pastures", {
        "allotment_id": allotment["id"],
        "name": body["name"],
        "sequence_order": wanted,
        "pasture_aum_capacity": body["pasture_aum_capacity"],
        "rest_required": bool(body["rest_required"]),
    })
    return envelope.created(derive.pasture_json(record))


def raise_sequence_conflict(message):
    raise ApiError("ERR_PASTURE_SEQUENCE_CONFLICT", message)


@bp.get("/allotments/<allotment_id>/pastures")
def list_allotment_pastures(allotment_id):
    envelope.page_params()
    auth.any_operational()
    allotment = find.need("allotments", allotment_id)
    records = [row for row in store.rows("pastures")
               if row["allotment_id"] == allotment["id"]]
    records = sorted(records, key=lambda row: (row["sequence_order"], row["_seq"]))
    return envelope.paginate(records, derive.pasture_json)


@bp.get("/pastures")
def list_pastures():
    envelope.page_params()
    auth.any_operational()
    records = find.apply_filters(envelope.sort_default(store.rows("pastures")), [
        ("allotment_id", "allotment_id", "str"),
        ("rest_required", "rest_required", "bool"),
    ])
    return envelope.paginate(records, derive.pasture_json)


@bp.get("/pastures/<pasture_id>")
def get_pasture(pasture_id):
    auth.any_operational()
    return envelope.ok(derive.pasture_json(find.need("pastures", pasture_id)))


PERMITTEE_FIELDS = [
    field("name", "str", min_len=1, max_len=120),
    field("contact_email", "str", contains="@"),
]


@bp.post("/permittees")
def create_permittee():
    body = parse_body(json_body(), PERMITTEE_FIELDS)
    auth.authenticate(["AuthorizedOfficer"])
    record = store.insert("permittees", {
        "name": body["name"],
        "contact_email": body["contact_email"],
    })
    return envelope.created(derive.permittee_json(record))


@bp.get("/permittees/<permittee_id>")
def get_permittee(permittee_id):
    actor = auth.any_operational()
    record = find.need("permittees", permittee_id)
    auth.require_own(actor, record["id"])
    return envelope.ok(derive.permittee_json(record))


BASE_PROPERTY_FIELDS = [
    field("base_property_type", "enum", values=K.BASE_PROPERTY_TYPE),
    field("legal_description", "str", min_len=1, max_len=200),
    field("carrying_capacity_aums", "int", min=0),
    field("controlled_since_date", "date"),
]


@bp.post("/permittees/<permittee_id>/base-properties")
def create_base_property(permittee_id):
    body = parse_body(json_body(), BASE_PROPERTY_FIELDS)
    auth.authenticate(["AuthorizedOfficer"])
    permittee = find.need("permittees", permittee_id)
    record = store.insert("base_properties", {
        "permittee_id": permittee["id"],
        "base_property_type": body["base_property_type"],
        "legal_description": body["legal_description"],
        "carrying_capacity_aums": body["carrying_capacity_aums"],
        "controlled_since_date": body["controlled_since_date"].isoformat(),
    })
    return envelope.created(derive.base_property_json(record))


@bp.get("/permittees/<permittee_id>/base-properties")
def list_permittee_base_properties(permittee_id):
    envelope.page_params()
    auth.any_operational()
    permittee = find.need("permittees", permittee_id)
    records = [row for row in envelope.sort_default(store.rows("base_properties"))
               if row["permittee_id"] == permittee["id"]]
    records = find.apply_filters(records, [
        ("base_property_type", "base_property_type", "str"),
        ("qualification_basis", "base_property_type", "str"),
    ])
    return envelope.paginate(records, derive.base_property_json)


@bp.get("/base-properties")
def list_base_properties():
    envelope.page_params()
    auth.any_operational()
    records = find.apply_filters(
        envelope.sort_default(store.rows("base_properties")), [
            ("permittee_id", "permittee_id", "str"),
            ("base_property_type", "base_property_type", "str"),
            ("qualification_basis", "base_property_type", "str"),
        ])
    return envelope.paginate(records, derive.base_property_json)


@bp.get("/base-properties/<base_property_id>")
def get_base_property(base_property_id):
    auth.any_operational()
    record = find.need("base_properties", base_property_id)
    return envelope.ok(derive.base_property_json(record))
