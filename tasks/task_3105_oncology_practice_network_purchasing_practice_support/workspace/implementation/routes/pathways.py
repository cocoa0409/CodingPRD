"""Pathway protocols: publish / retire and the adherence recompute."""

import db
from errors import ApiError
from registry import route
from routes._shared import filtered, paginate, serial
from services import helpers
from services.helpers import as_enum, as_list, as_num, as_str

READ_ROLES = [
    "NetworkAdmin",
    "PracticeAdmin",
    "NetworkAnalyst",
    "PlatformAdmin",
]


@route("POST", "/networks/{networkId}/pathway-protocols", roles=["NetworkAdmin"], status=201, write=True)
def create_protocol(ctx):
    network = helpers.network_or_404(ctx.path_id("networkId"))
    data = ctx.body
    protocol = db.create(
        "pathway_protocols",
        {
            "network_id": network["id"],
            "protocol_code": as_str(data, "protocol_code"),
            "indication": as_enum(
                data, "indication", ("NSCLC", "BREAST", "COLORECTAL", "LYMPHOMA"), required_=True
            ),
            "on_pathway_regimen_codes": as_list(data, "on_pathway_regimen_codes", default=[]),
            "declared_regimen_codes": as_list(data, "declared_regimen_codes", default=[]),
            "off_pathway_penalty_score": float(
                as_num(data, "off_pathway_penalty_score", default=0)
            ),
            "version_label": as_str(data, "version_label"),
            "status": "DRAFT",
        },
    )
    return serial(protocol), 201


@route("GET", "/networks/pathway-protocols", roles=READ_ROLES)
def list_protocols(ctx):
    rows = filtered(
        db.all_records("pathway_protocols"),
        ctx,
        {"network_id": "network_id", "indication": "indication", "status": "status"},
    )
    return paginate(ctx, rows)


@route("GET", "/networks/pathway-protocols/{protocolId}", roles=READ_ROLES)
def get_protocol(ctx):
    return serial(helpers.protocol_or_404(ctx.path_id("protocolId")))


@route("PUT", "/networks/pathway-protocols/{protocolId}", roles=["NetworkAdmin"], write=True)
def update_protocol(ctx):
    protocol = helpers.protocol_or_404(ctx.path_id("protocolId"))
    target = ctx.body.get("status")
    if target == "PUBLISHED":
        if protocol["status"] != "DRAFT":
            raise ApiError("ERR_PROTOCOL_NOT_DRAFT")
        if not (protocol.get("on_pathway_regimen_codes") or []):
            raise ApiError("ERR_INVALID_REQUEST", "on_pathway_regimen_codes must be non-empty")
        protocol["status"] = "PUBLISHED"
        # Every practice actively steering has its adherence recomputed against
        # the newly published regimen set.
        for practice in db.where("practices", network_id=protocol["network_id"]):
            if practice["pathway_steering_status"] == "ACTIVE":
                helpers.recompute_adherence(practice)
                db.touch(practice)
    elif target == "RETIRED":
        if protocol["status"] != "PUBLISHED":
            raise ApiError("ERR_PROTOCOL_NOT_PUBLISHED")
        protocol["status"] = "RETIRED"
    else:
        raise ApiError("ERR_INVALID_REQUEST", "status must be PUBLISHED or RETIRED")
    db.touch(protocol)
    return serial(protocol)