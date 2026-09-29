"""The policy tower and the liability claim: setup, reserve, counsel, closure."""

from flask import Blueprint

import calc
import serializers
from auth import require, CLAIM_READ, POLICY_READ
from common import claim_for_crash, filtered, lookup, paginate
from envelope import ok, created
from errors import fail
from shape import MISSING, f, filters, given, present, read_body
from store import base_row, db, ordered, touch

bp = Blueprint("claims", __name__)


# ---------------------------------------------------------------------------
# Policy layers
# ---------------------------------------------------------------------------
LAYER_SPEC = [
    f("program_year", "int", required=True),
    f("layer_index", "int", required=True, minimum=1),
    f("layer_type", "string", required=True, enum=calc.LAYER_TYPES),
    f("attachment_point_cents", "int", required=True, minimum=0),
    f("limit_cents", "int", required=True, minimum=1),
    f("insurer_name", "string", required=True),
]


@bp.post("/policy-layers")
def create_layer():
    require("ClaimsManager", "SafetyAdmin")
    values = read_body(LAYER_SPEC)
    year = values["program_year"]
    index = values["layer_index"]
    for row in db.policy_layers.values():
        if row["program_year"] == year and row["layer_index"] == index:
            fail("ERR_POLICY_LAYER_DUPLICATE",
                 "Layer index %d is already declared for program year %d"
                 % (index, year))
    row = base_row(with_version=False)
    row["program_year"] = year
    row["layer_index"] = index
    row["layer_type"] = values["layer_type"]
    row["attachment_point_cents"] = values["attachment_point_cents"]
    row["limit_cents"] = values["limit_cents"]
    row["insurer_name"] = values["insurer_name"]
    db.policy_layers[row["id"]] = row
    if not calc.tower_well_formed(year):
        del db.policy_layers[row["id"]]
        fail("ERR_POLICY_TOWER_MALFORMED",
             "The declared layer does not form a well-formed tower for %d" % year)
    return created(serializers.policy_layer(row))


@bp.get("/policy-layers/<entity_id>")
def read_layer(entity_id):
    require(*POLICY_READ)
    return ok(serializers.policy_layer(lookup("policy_layers", entity_id)))


@bp.get("/policy-layers")
def list_layers():
    require(*POLICY_READ)
    criteria = filters({"program_year": "int", "layer_type": calc.LAYER_TYPES})
    rows = [r for r in db.policy_layers.values()
            if all(r.get(k) == v for k, v in criteria.items())]
    rows = sorted(rows, key=lambda r: (r["program_year"], r["layer_index"]))
    return paginate(rows, serializers.policy_layer)


# ---------------------------------------------------------------------------
# Claims
# ---------------------------------------------------------------------------
@bp.post("/claims")
def create_claim():
    require("ClaimsAdjuster")
    values = read_body([
        f("crash_id", "string", required=True),
        f("claimant_notice_date", "date", required=True),
        f("adjuster_note", "string"),
    ])
    crash = lookup("crashes", values["crash_id"])
    if claim_for_crash(crash["id"]) is not None:
        fail("ERR_CLAIM_EXISTS", "This crash already carries a claim")
    row = base_row()
    row["crash_id"] = crash["id"]
    row["claimant_notice_date"] = values["claimant_notice_date"]
    row["adjuster_note"] = given(values, "adjuster_note")
    row["handling_status"] = "SETUP"
    row["reserve_status"] = "PROVISIONAL"
    row["counsel_assigned"] = False
    row["counsel_firm_name"] = None
    row["counsel_type"] = "NONE"
    row["counsel_assigned_at"] = None
    row["litigation_flag"] = False
    row["closed_at"] = None
    row["revised_reserve_cents"] = None
    row["indemnity_paid_cents"] = 0
    row["alae_paid_cents"] = 0
    row["reserve_released_cents"] = 0
    row["subrogation_recovered_cents"] = 0
    row["sir_eroded_cents"] = 0
    row["insured_paid_cents"] = 0
    row["layer_allocations"] = []
    row["outstanding_reserve_cents"] = 0
    reserve = calc.compute_reserve(row, "PROVISIONAL_REFRESH")
    row["provisional_reserve_cents"] = reserve
    row["outstanding_reserve_cents"] = reserve
    db.claims[row["id"]] = row
    return created(serializers.claim(row))


@bp.get("/claims/<entity_id>")
def read_claim(entity_id):
    require(*CLAIM_READ)
    return ok(serializers.claim(lookup("claims", entity_id)))


@bp.get("/claims")
def list_claims():
    require(*CLAIM_READ)
    criteria = filters({
        "crash_id": None,
        "handling_status": calc.HANDLING_STATUSES,
        "reserve_status": calc.RESERVE_STATUSES,
        "counsel_required": "bool",
    })
    crash_id = criteria.get("crash_id")
    handling = criteria.get("handling_status")
    reserve = criteria.get("reserve_status")
    counsel = criteria.get("counsel_required")

    def keep(row):
        if crash_id is not None and row["crash_id"] != crash_id:
            return False
        if handling is not None and row["handling_status"] != handling:
            return False
        if reserve is not None and row["reserve_status"] != reserve:
            return False
        if counsel is not None:
            score = calc.litigation_risk_score(row)
            if calc.counsel_required(score) != counsel:
                return False
        return True

    return paginate(filtered("claims", {}, keep), serializers.claim)


@bp.post("/claims/<entity_id>/reserve-revisions")
def revise_reserve(entity_id):
    require("ClaimsAdjuster")
    values = read_body([
        f("expected_claim_version", "int", required=True),
        f("basis", "string", required=True,
          enum=("PROVISIONAL_REFRESH", "DEMAND_BASED")),
        f("revision_note", "string"),
    ])
    claim = lookup("claims", entity_id)
    if claim["handling_status"] == "CLOSED":
        fail("ERR_CLAIM_STATE_INVALID", "A closed claim accepts no revision")
    if values["expected_claim_version"] != claim["version"]:
        fail("ERR_CLAIM_VERSION_STALE",
             "The claim has advanced since it was read")
    basis = values["basis"]
    if basis == "DEMAND_BASED" and not calc.claim_demands(claim["id"]):
        fail("ERR_NO_DEMANDS_TO_WEIGHT",
             "A DEMAND_BASED revision requires at least one demand on the claim")
    revised = calc.compute_reserve(claim, basis)
    claim["revised_reserve_cents"] = revised
    claim["reserve_status"] = "REVISED"
    outstanding = (revised - claim["indemnity_paid_cents"]
                   - claim["alae_paid_cents"])
    claim["outstanding_reserve_cents"] = outstanding if outstanding > 0 else 0
    touch(claim)
    return ok(serializers.claim(claim))


@bp.post("/claims/<entity_id>/counsel-assignment")
def assign_counsel(entity_id):
    require("ClaimsManager")
    values = read_body([
        f("counsel_firm_name", "string", required=True),
        f("counsel_type", "string", required=True, enum=calc.COUNSEL_TYPES),
    ])
    claim = lookup("claims", entity_id)
    if claim["handling_status"] == "CLOSED":
        fail("ERR_CLAIM_STATE_INVALID",
             "A closed claim accepts no counsel assignment")
    score = calc.litigation_risk_score(claim)
    if not calc.counsel_required(score):
        fail("ERR_COUNSEL_NOT_REQUIRED",
             "This claim's litigation risk does not require counsel")
    claim["counsel_assigned"] = True
    claim["counsel_firm_name"] = values["counsel_firm_name"]
    claim["counsel_type"] = values["counsel_type"]
    claim["counsel_assigned_at"] = db.now
    claim["litigation_flag"] = True
    touch(claim)
    return ok(serializers.claim(claim))


@bp.post("/claims/<entity_id>/close")
def close_claim(entity_id):
    require("ClaimsManager")
    read_body([])
    claim = lookup("claims", entity_id)
    if claim["handling_status"] == "CLOSED":
        fail("ERR_CLAIM_STATE_INVALID", "This claim is already closed")
    demands = calc.claim_demands(claim["id"])
    for demand in demands:
        if demand["status"] not in ("SETTLED", "CLOSED_PAID"):
            fail("ERR_OPEN_DEMANDS_REMAIN",
                 "Every demand must be settled before the claim may close")
    for subro in calc.claim_subrogations(claim["id"]):
        if subro["status"] not in ("RECOVERED", "DENIED", "WRITTEN_OFF"):
            fail("ERR_OPEN_SUBROGATION_REMAINS",
                 "Every subrogation demand must be resolved before closure")
    claim["handling_status"] = "CLOSED"
    claim["closed_at"] = db.now
    claim["reserve_status"] = "FINAL"
    residual = claim["outstanding_reserve_cents"]
    claim["reserve_released_cents"] += residual
    claim["outstanding_reserve_cents"] = 0
    touch(claim)
    for demand in demands:
        if demand["status"] == "SETTLED":
            demand["status"] = "CLOSED_PAID"
            touch(demand)
    return ok(serializers.claim(claim))
