"""Settlements: propose, read, counter, revise, agree-terms.

The sign-on campaign, execution, and deposits live in routes_settlement_flow.
"""
from flask import Blueprint

import auth
import calc
import db
import envelope
import errors
import serialize
import services
import validate

bp = Blueprint("settlements", __name__, url_prefix="/multistate")

ALLOCATION_BASES = ("POPULATION", "HARM_MEASURE", "NEGOTIATED")


@bp.route("/investigations/<investigation_id>/settlements", methods=["POST"])
def create_settlement(investigation_id):
    role, uid = auth.authenticate()
    auth.require_roles(role, ("LeadStateAG",))
    body = validate.body_json()
    total = validate.req_int(body, "monetary_total_cents")
    reserve = validate.req_int(body, "restitution_reserve_cents")
    basis = validate.req_enum(body, "allocation_basis", ALLOCATION_BASES)
    terms = validate.req_str_list(body, "injunctive_terms")
    shares = validate.opt_bps_map(body, "negotiated_shares")
    # Rung 3 domain checks (error catalog: ERR_INVALID_REQUEST, 400).
    if reserve < 0 or total <= reserve:
        raise errors.invalid_request(
            "monetary_total_cents must strictly exceed restitution_reserve_cents >= 0"
        )
    if len(terms) < 1:
        raise errors.invalid_request("injunctive_terms must contain at least one entry")
    inv = validate.get_investigation_or_404(investigation_id)
    # Rung 5: lead-gated operation.
    auth.require_lead_active(inv["id"], uid)
    # Rung 6: phase gate, then single-live-settlement gate.
    if inv["phase"] != "NEGOTIATION":
        raise errors.invalid_phase("Settlements may be proposed only in NEGOTIATION phase")
    for existing in db.settlements.values():
        if existing["investigation_id"] == inv["id"] and existing["term_status"] != "COLLAPSED":
            raise errors.invalid_state(
                "A settlement of this investigation is not COLLAPSED; only one live settlement is allowed"
            )
    # Rung 11: NEGOTIATED basis share-map integrity.
    if basis == "NEGOTIATED":
        expected_keys = set()
        for p in services.active_participations_of(inv["id"]):
            office = db.offices.get(p["state_office_id"])
            if office is not None:
                expected_keys.add(office["state_code"])
        if (
            shares is None
            or set(shares.keys()) != expected_keys
            or sum(shares.values()) != calc.TOTAL_WEIGHT_BPS
        ):
            raise errors.ApiError(
                "ERR_NEGOTIATED_SHARES_INVALID",
                422,
                "negotiated_shares keys must equal ACTIVE participants' state codes and sum to 10000",
            )
    st = db.new_entity(db.settlements)
    st.update(
        {
            "investigation_id": inv["id"],
            "monetary_total_cents": total,
            "restitution_reserve_cents": reserve,
            "allocation_basis": basis,
            "negotiated_shares": dict(shares) if shares is not None else None,
            "injunctive_terms": list(terms),
            "term_status": "PROPOSED",
            "fund_status": "UNFUNDED",
            "negotiation_round": 0,
            "counter_total_cents": None,
            "sign_on_opened_at": None,
            "sign_on_deadline": None,
            "executed_at": None,
            "sign_ons": [],
            "provisional_distributable_cents": None,
            "provisional_weight_bps_by_state": None,
            "distributable_cents": None,
            "lead_cost_cents": None,
            "compliance_hold": False,
            "deposited_cents": 0,
            "released_cents": 0,
            "reverted_cents": 0,
            "restitution_reserve_balance_cents": reserve,
            "restitution_computed": False,
            "restitution_remainder_cents": None,
        }
    )
    services.compute_provisional(st)
    inv["active_settlement_id"] = st["id"]
    db.touch(inv)
    return envelope.success_object(serialize.serialize("settlement", st), 201)


@bp.route("/settlements/<settlement_id>", methods=["GET"])
def get_settlement(settlement_id):
    role, _uid = auth.authenticate()
    auth.require_roles(role, auth.ALL_ROLES)
    st = validate.get_settlement_or_404(settlement_id)
    return envelope.success_object(serialize.serialize("settlement", st))


@bp.route("/settlements/<settlement_id>/counter", methods=["POST"])
def counter_settlement(settlement_id):
    role, _uid = auth.authenticate()
    auth.require_roles(role, ("DefendantCounsel",))
    body = validate.body_json()
    expected = validate.req_int(body, "expected_settlement_version")
    counter_total = validate.opt_int(body, "counter_total_cents")
    validate.opt_str(body, "note")
    st = validate.get_settlement_or_404(settlement_id)
    if st["term_status"] != "PROPOSED":
        raise errors.invalid_state("Settlement is not PROPOSED")
    if expected != st["version"]:
        raise errors.stale_version(
            "expected_settlement_version does not match the settlement's current version"
        )
    if st["negotiation_round"] + 1 > calc.MAX_SETTLEMENT_ROUNDS:
        raise errors.ApiError(
            "ERR_NEGOTIATION_EXHAUSTED",
            422,
            "Counter would push negotiation_round beyond MAX_SETTLEMENT_ROUNDS (4)",
        )
    st["negotiation_round"] += 1
    if counter_total is not None:
        st["counter_total_cents"] = counter_total
    st["term_status"] = "COUNTERED"
    db.touch(st)
    inv = db.investigations.get(st["investigation_id"])
    if inv is not None and inv["phase"] == "NEGOTIATION":
        inv["phase"] = "DISCOVERY"
        db.touch(inv)
    return envelope.success_object(serialize.serialize("settlement", st))


@bp.route("/settlements/<settlement_id>/revise", methods=["POST"])
def revise_settlement(settlement_id):
    role, uid = auth.authenticate()
    auth.require_roles(role, ("LeadStateAG",))
    body = validate.body_json()
    expected = validate.req_int(body, "expected_settlement_version")
    revised_total = validate.opt_int(body, "revised_total_cents")
    validate.opt_str(body, "note")
    st = validate.get_settlement_or_404(settlement_id)
    auth.require_lead_active(st["investigation_id"], uid)
    if st["term_status"] != "COUNTERED":
        raise errors.invalid_state("Settlement is not COUNTERED")
    if expected != st["version"]:
        raise errors.stale_version(
            "expected_settlement_version does not match the settlement's current version"
        )
    if revised_total is not None:
        st["monetary_total_cents"] = revised_total
        services.compute_provisional(st)
    st["term_status"] = "PROPOSED"
    db.touch(st)
    inv = db.investigations.get(st["investigation_id"])
    if inv is not None and inv["phase"] == "DISCOVERY":
        inv["phase"] = "NEGOTIATION"
        db.touch(inv)
    return envelope.success_object(serialize.serialize("settlement", st))


@bp.route("/settlements/<settlement_id>/agree-terms", methods=["POST"])
def agree_terms(settlement_id):
    role, _uid = auth.authenticate()
    auth.require_roles(role, ("DefendantCounsel",))
    st = validate.get_settlement_or_404(settlement_id)
    if st["term_status"] != "PROPOSED":
        raise errors.invalid_state("Settlement is not PROPOSED")
    st["term_status"] = "TERMS_AGREED"
    db.touch(st)
    return envelope.success_object(serialize.serialize("settlement", st))
