"""Logical clock (unprefixed) + StateOffice registry + office-scoped lists."""
from flask import Blueprint

import auth
import db
import envelope
import errors
import serialize
import validate

bp = Blueprint("offices", __name__, url_prefix="/multistate")
bp_clock = Blueprint("clock", __name__)  # mounted OUTSIDE /multistate (PRD §2.4)

APPROPRIATION_RULES = ("PREAPPROPRIATED", "CERTIFICATION_REQUIRED", "GENERAL_FUND_ONLY")


@bp_clock.route("/_clock/set_current_utc", methods=["POST"])
def set_current_utc():
    role, _uid = auth.authenticate()
    auth.require_roles(role, ("CommitteeChair",))
    body = validate.body_json()
    raw = validate.req_str(body, "to_iso8601")
    moment = db.parse_iso(raw)
    if moment is None:
        raise errors.invalid_request("Field 'to_iso8601' must be an ISO 8601 UTC timestamp")
    db.set_clock(moment)
    return envelope.success_object({"current_utc": db.render_ts(db.now())})


@bp.route("/state-offices", methods=["POST"])
def create_office():
    role, _uid = auth.authenticate()
    auth.require_roles(role, ("CommitteeChair",))
    body = validate.body_json()
    state_code = validate.req_str(body, "state_code")
    population = validate.req_int(body, "population")
    harm = validate.req_int(body, "harm_measure_cents")
    rule = validate.req_enum(body, "appropriation_rule", APPROPRIATION_RULES)
    for office in db.offices.values():
        if office["state_code"] == state_code:
            raise errors.invalid_request("state_code is already registered")
    office = db.new_entity(db.offices)
    office.update(
        {
            "state_code": state_code,
            "population": population,
            "harm_measure_cents": harm,
            "appropriation_rule": rule,
        }
    )
    return envelope.success_object(serialize.serialize("office", office), 201)


@bp.route("/state-offices/<office_id>", methods=["GET"])
def get_office(office_id):
    role, _uid = auth.authenticate()
    auth.require_roles(role, auth.ALL_ROLES)
    office = validate.get_office_or_404(office_id)
    return envelope.success_object(serialize.serialize("office", office))


@bp.route("/state-offices/<office_id>", methods=["PATCH"])
def patch_office(office_id):
    role, _uid = auth.authenticate()
    auth.require_roles(role, ("CommitteeChair",))
    body = validate.body_json()
    expected = validate.req_int(body, "expected_state_office_version")
    population = validate.opt_int(body, "population")
    harm = validate.opt_int(body, "harm_measure_cents")
    rule = None
    if body.get("appropriation_rule") is not None:
        rule = validate.req_enum(body, "appropriation_rule", APPROPRIATION_RULES)
    office = validate.get_office_or_404(office_id)
    if expected != office["version"]:
        raise errors.stale_version(
            "expected_state_office_version does not match the office's current version"
        )
    if population is not None:
        office["population"] = population
    if harm is not None:
        office["harm_measure_cents"] = harm
    if rule is not None:
        office["appropriation_rule"] = rule
    db.touch(office)
    return envelope.success_object(serialize.serialize("office", office))


@bp.route("/state-offices/<office_id>/participations", methods=["GET"])
def list_office_participations(office_id):
    role, _uid = auth.authenticate()
    auth.require_roles(role, auth.ALL_ROLES)
    limit, offset = validate.pagination_params()
    validate.get_office_or_404(office_id)
    items = [p for p in db.participations.values() if p["state_office_id"] == office_id]
    page, total = validate.paginate(items, limit, offset)
    return envelope.success_list(
        serialize.serialize_list("participation", page), limit, offset, total
    )


@bp.route("/state-offices/<office_id>/allocation-lines", methods=["GET"])
def list_office_allocation_lines(office_id):
    role, _uid = auth.authenticate()
    auth.require_roles(role, auth.ALL_ROLES)
    limit, offset = validate.pagination_params()
    validate.get_office_or_404(office_id)
    items = [l for l in db.lines.values() if l["state_office_id"] == office_id]
    page, total = validate.paginate(items, limit, offset)
    return envelope.success_list(
        serialize.serialize_list("line", page), limit, offset, total
    )
