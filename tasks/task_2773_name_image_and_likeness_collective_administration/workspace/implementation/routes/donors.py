"""Donor members: enrolment onto the dues ladder and the tax profile."""

from flask import Blueprint, request

import auth
import clock
import derive
import envelope
import lookup
import serialize
import shape
import store
from errors import ApiError

bp = Blueprint("donors", __name__)

DONOR_KINDS = ["INDIVIDUAL", "ENTITY"]
DONOR_STATUSES = ["PROSPECT", "ACTIVE", "LAPSED"]


@bp.route("/nil/donor-members", methods=["POST"])
def create_donor():
    auth.authenticate([auth.COLLECTIVE_DIRECTOR])
    body = shape.body()
    collective_id = shape.string_field(body, "collective_id", required=True)
    tier_id = shape.string_field(body, "membership_tier_id", required=True)
    display_name = shape.string_field(body, "display_name", required=True)
    email = shape.string_field(body, "email", required=True)
    donor_kind = shape.enum_field(body, "donor_kind", DONOR_KINDS, default="INDIVIDUAL")
    agi = shape.int_field(body, "annual_agi_cents", default=0, minimum=0)

    collective = lookup.collective(collective_id)
    tier = lookup.membership_tier(tier_id)

    if tier["collective_id"] != collective["id"]:
        raise ApiError("ERR_CROSS_COLLECTIVE_REFERENCE")
    for existing in derive.donors_of_collective(collective["id"]):
        if existing["email"] == email:
            raise ApiError("ERR_DUPLICATE_MEMBER_HANDLE")
    if tier["tier_status"] != "OPEN":
        raise ApiError("ERR_TIER_NOT_OPEN")

    now = clock.now()
    row = {
        "id": store.new_id(),
        "collective_id": collective["id"],
        "membership_tier_id": tier["id"],
        "display_name": display_name,
        "email": email,
        "donor_kind": donor_kind,
        "annual_agi_cents": agi,
        "status": "PROSPECT",
        "lifetime_settled_cents": 0,
        "lifetime_deductible_cents": 0,
        "sequence_no": store.next_seq("donor_member"),
        "created_at": now,
        "updated_at": now,
        "version": 1,
    }
    store.donor_members[row["id"]] = row
    return envelope.object_response(serialize.donor_member(row), 201)


@bp.route("/nil/donor-members/<donor_id>", methods=["GET"])
def read_donor(donor_id):
    auth.authenticate(auth.NON_ATHLETE_ROLES)
    row = lookup.donor_member(donor_id)
    return envelope.object_response(serialize.donor_member(row))


@bp.route("/nil/donor-members", methods=["GET"])
def list_donors():
    auth.authenticate(auth.NON_ATHLETE_ROLES)
    limit, offset = envelope.read_pagination(request.args)
    collective_id = envelope.id_filter(request.args, "collective_id")
    tier_id = envelope.id_filter(request.args, "membership_tier_id")
    status = envelope.enum_filter(request.args, "status", DONOR_STATUSES)
    rows = store.ordered(store.donor_members.values())
    if collective_id is not None:
        rows = [r for r in rows if r["collective_id"] == collective_id]
    if tier_id is not None:
        rows = [r for r in rows if r["membership_tier_id"] == tier_id]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    return envelope.list_response([serialize.donor_member(r) for r in rows], limit, offset)


@bp.route("/nil/donor-members/<donor_id>/tax-profile", methods=["PATCH"])
def update_donor_tax_profile(donor_id):
    auth.authenticate([auth.COLLECTIVE_DIRECTOR])
    body = shape.body()
    donor_kind = shape.enum_field(body, "donor_kind", DONOR_KINDS)
    agi = shape.int_field(body, "annual_agi_cents", minimum=0)
    donor = lookup.donor_member(donor_id)

    if donor_kind is not None:
        donor["donor_kind"] = donor_kind
    if agi is not None:
        donor["annual_agi_cents"] = agi
    # Correcting either figure never rewrites the deductible amounts already
    # stored on that donor's settled contributions.
    derive.bump(donor)
    return envelope.object_response(serialize.donor_member(donor))
