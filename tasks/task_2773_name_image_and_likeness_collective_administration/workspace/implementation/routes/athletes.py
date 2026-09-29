"""The athlete roster: eligibility, portal movement and taxpayer documentation."""

from flask import Blueprint, request

import auth
import calc
import clock
import derive
import envelope
import lookup
import serialize
import shape
import store
from errors import ApiError

bp = Blueprint("athletes", __name__)

SPORTS = ["FOOTBALL", "MENS_BASKETBALL", "WOMENS_BASKETBALL", "BASEBALL", "SOFTBALL"]
TAX_PERSON_KINDS = ["US_PERSON", "NONRESIDENT_ALIEN"]
TAXPAYER_DOCS = ["NONE", "W9", "W8BEN"]
ELIGIBILITY_STATUSES = ["ENROLLED", "PORTAL_ENTERED", "TRANSFERRED_OUT", "INELIGIBLE"]
TAX_FORMS = ["NONE", "FORM_1099_NEC", "FORM_1042_S"]
CHANGES = ["ENTER_PORTAL", "WITHDRAW_FROM_PORTAL", "COMPLETE_TRANSFER",
           "DECLARE_INELIGIBLE", "REINSTATE"]


@bp.route("/nil/athletes", methods=["POST"])
def create_athlete():
    auth.authenticate([auth.COLLECTIVE_DIRECTOR, auth.COMPLIANCE_OFFICER])
    body = shape.body()
    collective_id = shape.string_field(body, "collective_id", required=True)
    full_name = shape.string_field(body, "full_name", required=True)
    portal_user_id = shape.string_field(body, "portal_user_id", required=True)
    sport = shape.enum_field(body, "sport", SPORTS, required=True)
    class_year = shape.int_field(body, "class_year", required=True, minimum=2026, maximum=2031)
    roster_weight = shape.int_field(body, "roster_weight", default=1, minimum=1, maximum=10)
    tax_person_kind = shape.enum_field(body, "tax_person_kind", TAX_PERSON_KINDS,
                                       default="US_PERSON")

    collective = lookup.collective(collective_id)

    for existing in derive.athletes_of_collective(collective["id"]):
        if existing["portal_user_id"] == portal_user_id:
            raise ApiError("ERR_DUPLICATE_MEMBER_HANDLE")

    now = clock.now()
    row = {
        "id": store.new_id(),
        "collective_id": collective["id"],
        "full_name": full_name,
        "portal_user_id": portal_user_id,
        "sport": sport,
        "class_year": class_year,
        "roster_weight": roster_weight,
        "tax_person_kind": tax_person_kind,
        "taxpayer_doc_on_file": "NONE",
        "treaty_exempt_claimed": False,
        "eligibility_status": "ENROLLED",
        "sequence_no": store.next_seq("athlete"),
        "created_at": now,
        "updated_at": now,
        "version": 1,
    }
    store.athletes[row["id"]] = row
    return envelope.object_response(serialize.athlete(row), 201)


@bp.route("/nil/athletes/<athlete_id>", methods=["GET"])
def read_athlete(athlete_id):
    auth.authenticate(auth.ALL_ROLES)
    row = lookup.athlete(athlete_id)
    return envelope.object_response(serialize.athlete(row))


@bp.route("/nil/athletes", methods=["GET"])
def list_athletes():
    auth.authenticate(auth.NON_ATHLETE_ROLES)
    limit, offset = envelope.read_pagination(request.args)
    collective_id = envelope.id_filter(request.args, "collective_id")
    sport = envelope.enum_filter(request.args, "sport", SPORTS)
    status = envelope.enum_filter(request.args, "eligibility_status", ELIGIBILITY_STATUSES)
    tax_form = envelope.enum_filter(request.args, "tax_form_required", TAX_FORMS)
    rows = store.ordered(store.athletes.values())
    if collective_id is not None:
        rows = [r for r in rows if r["collective_id"] == collective_id]
    if sport is not None:
        rows = [r for r in rows if r["sport"] == sport]
    if status is not None:
        rows = [r for r in rows if r["eligibility_status"] == status]
    if tax_form is not None:
        rows = [r for r in rows if derive.athlete_tax_form_required(r) == tax_form]
    return envelope.list_response([serialize.athlete(r) for r in rows], limit, offset)


@bp.route("/nil/athletes/<athlete_id>/eligibility-changes", methods=["POST"])
def eligibility_change(athlete_id):
    auth.authenticate([auth.COMPLIANCE_OFFICER])
    body = shape.body()
    change = shape.enum_field(body, "change", CHANGES, required=True)
    athlete = lookup.athlete(athlete_id)

    required_from = {
        "ENTER_PORTAL": "ENROLLED",
        "WITHDRAW_FROM_PORTAL": "PORTAL_ENTERED",
        "COMPLETE_TRANSFER": "PORTAL_ENTERED",
        "DECLARE_INELIGIBLE": "ENROLLED",
        "REINSTATE": "INELIGIBLE",
    }[change]
    if athlete["eligibility_status"] != required_from:
        raise ApiError("ERR_ATHLETE_STATE_INVALID")

    collective = store.collectives.get(athlete["collective_id"])

    if change == "ENTER_PORTAL":
        athlete["eligibility_status"] = "PORTAL_ENTERED"
        derive.touch(athlete)
    elif change == "WITHDRAW_FROM_PORTAL":
        athlete["eligibility_status"] = "ENROLLED"
        derive.touch(athlete)
        # Release the held money, in ascending payment-release sequence_no.
        for release in derive.releases_of_athlete(athlete["id"]):
            if release["status"] != "QUEUED":
                continue
            contract = store.deal_contracts.get(release["deal_contract_id"])
            if contract is None or contract["lifecycle_status"] != "ACTIVE":
                continue
            derive.release_payment(release, contract, collective)
    elif change in ("COMPLETE_TRANSFER", "DECLARE_INELIGIBLE"):
        athlete["eligibility_status"] = ("TRANSFERRED_OUT" if change == "COMPLETE_TRANSFER"
                                        else "INELIGIBLE")
        derive.touch(athlete)
        reason = "TRANSFER_OUT" if change == "COMPLETE_TRANSFER" else "INELIGIBILITY"
        for contract in derive.contracts_of_athlete(athlete["id"]):
            if contract["lifecycle_status"] in ("DRAFT", "ACTIVE"):
                derive.terminate_contract(contract, reason)
    else:
        athlete["eligibility_status"] = "ENROLLED"
        derive.touch(athlete)

    return envelope.object_response(serialize.athlete(athlete))


@bp.route("/nil/athletes/<athlete_id>/tax-profile", methods=["PATCH"])
def update_tax_profile(athlete_id):
    auth.authenticate([auth.COMPLIANCE_OFFICER, auth.TREASURY_OFFICER])
    body = shape.body()
    doc = shape.enum_field(body, "taxpayer_doc_on_file", TAXPAYER_DOCS, required=True)
    treaty = shape.bool_field(body, "treaty_exempt_claimed", default=False)
    if treaty and doc != "W8BEN":
        raise ApiError("ERR_INVALID_REQUEST",
                       "treaty_exempt_claimed may only be true alongside a W8BEN.")
    athlete = lookup.athlete(athlete_id)

    athlete["taxpayer_doc_on_file"] = doc
    athlete["treaty_exempt_claimed"] = treaty
    derive.bump(athlete)
    return envelope.object_response(serialize.athlete(athlete))
