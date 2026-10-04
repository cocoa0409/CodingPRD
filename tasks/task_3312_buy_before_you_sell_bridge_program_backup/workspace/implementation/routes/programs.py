"""Bridge-program routes (PRD 3.3, 3.5, 3.10)."""

from flask import Blueprint

from constants import PROJECTED_CARRY_MONTHS_MAX, PROJECTED_CARRY_MONTHS_MIN, ROLES
from routes import RawPayload, endpoint, json_body, query_params
from services import disclosure as disclosure_service
from services import pricing as pricing_service
from services import program as program_service
from services.lookup import get_bridge_program
from store import db
from validation import body_of, get_int

bp = Blueprint("programs", __name__)

COORDINATOR = ROLES[0]
HOMEOWNER = ROLES[2]
PROGRAM_ADMIN = ROLES[4]


@bp.post("/knock/bridge-programs")
@endpoint([COORDINATOR], status=201)
def create(actor):
    (
        homeowner_id,
        qualification_id,
        new_property_id,
        departing_property_id,
        months,
        fee_bps,
    ) = program_service.parse_create_body(json_body())
    return program_service.create_program(
        homeowner_id, qualification_id, new_property_id, departing_property_id, months, fee_bps
    )


@bp.get("/knock/bridge-programs")
@endpoint([COORDINATOR, PROGRAM_ADMIN])
def list_programs(actor):
    params = query_params()
    records = db.all("bridge_programs")
    for field in ("homeowner_id", "qualification_id", "new_property_id", "departing_property_id"):
        value = params.get(field)
        if value:
            records = [r for r in records if r.get(field) == value]
    return db.sorted_by_created(records), params


@bp.get("/knock/bridge-programs/<program_id>")
@endpoint([COORDINATOR, HOMEOWNER])
def read(actor, program_id):
    return get_bridge_program(program_id)


@bp.post("/knock/bridge-programs/<program_id>/fund")
@endpoint([COORDINATOR])
def fund(actor, program_id):
    return program_service.fund_program(program_id, json_body())


@bp.post("/knock/bridge-programs/<program_id>/occupy-new")
@endpoint([COORDINATOR, HOMEOWNER])
def occupy_new(actor, program_id):
    return program_service.occupy_new(program_id)


@bp.get("/knock/bridge-programs/<program_id>/summary")
@endpoint([COORDINATOR, HOMEOWNER])
def summary(actor, program_id):
    program = get_bridge_program(program_id)
    view = pricing_service.dual_cost_view(program)
    figures = disclosure_service.compute_disclosure(program)
    payload = dict(view)
    payload["total_program_charge_cents"] = figures["total_program_charge_cents"]
    payload["origination_cents"] = figures["origination_cents"]
    payload["coordination_cents"] = figures["coordination_cents"]
    payload["escalator_cents"] = figures["escalator_cents"]
    return RawPayload(payload)


@bp.post("/knock/bridge-programs/<program_id>/disclosures/preview")
@endpoint([COORDINATOR])
def disclosures_preview(actor, program_id):
    program = get_bridge_program(program_id)
    data = body_of(json_body())

    override = get_int(
        data,
        "projected_carry_months",
        required=False,
        default=None,
        minimum=PROJECTED_CARRY_MONTHS_MIN,
        maximum=PROJECTED_CARRY_MONTHS_MAX,
    )

    principal = None
    if override is not None:
        # Model a different carrying horizon without altering the program.
        saved = program.get("projected_carry_months")
        program["projected_carry_months"] = override
        try:
            figures = disclosure_service.compute_disclosure(program)
        finally:
            program["projected_carry_months"] = saved
    else:
        figures = disclosure_service.compute_disclosure(program)

    return RawPayload({
        "total_program_charge_cents": figures["total_program_charge_cents"],
        "origination_cents": figures["origination_cents"],
        "coordination_cents": figures["coordination_cents"],
        "escalator_cents": figures["escalator_cents"],
    })