from flask import Blueprint

import calc
import db
import services
from core import (actor, auth, body, fail, get_enum, get_num, get_str, now_date, now_instant, ok,
                  pagination, paginate, q_enum, q_str, sorted_rows)

bp = Blueprint("agreements", __name__)

OWNERSHIP = ("OWNERSHIP_TRANSFER", "BREEDING_LOAN", "LOAN_WITH_RETAINED_OWNERSHIP")
OFFSPRING = ("FIRST_TO_SENDER", "ALTERNATING", "SPLIT_50_50", "ALL_TO_RECEIVER")
RIGHTS = ("FULL", "RESTRICTED_NO_BREED", "CONTRACEPTION_REQUIRED")
SCOPES = ("INTRA_JURISDICTION", "INTERSTATE", "INTERNATIONAL")
STATUSES = ("DRAFT", "OFFERED", "COUNTERED", "ACCEPTED", "EXECUTED", "COMPLETED", "TERMINATED")


def _terms(b, required):
    return (
        get_enum(b, "ownership_disposition", OWNERSHIP, required=required),
        get_enum(b, "offspring_disposition_rule", OFFSPRING, required=required),
        get_enum(b, "breeding_rights", RIGHTS, required=required),
        get_num(b, "transport_cost_share_pct", required=required, minimum=0, maximum=100),
    )


def _turn_check(agreement):
    last = agreement["last_action_institution_id"]
    if last is not None and actor() == last:
        fail("ERR_NOT_COUNTERPARTY_TURN")


@bp.post("/transfer-agreements")
@auth("Registrar")
def create_agreement():
    b = body()
    recommendation_id = get_str(b, "recommendation_id", required=True)
    animal_id = get_str(b, "animal_id", required=True)
    sending_id = get_str(b, "sending_institution_id", required=True)
    receiving_id = get_str(b, "receiving_institution_id", required=True)
    ownership, offspring, rights, share = _terms(b, True)

    rec = db.get_recommendation(recommendation_id)
    animal = db.get_animal(animal_id)
    sending = db.get_institution(sending_id)
    receiving = db.get_institution(receiving_id)

    if actor() != sending_id:
        fail("ERR_ACTOR_SCOPE_VIOLATION")

    if rec["status"] != "ENDORSED":
        fail("ERR_RECOMMENDATION_NOT_ENDORSED")
    if animal["location_status"] != "HELD":
        fail("ERR_ANIMAL_LOCATION_CONFLICT")
    for other in services.agreements_of_animal(animal_id):
        if other["status"] in calc.ACTIVE_AGREEMENT_STATUSES:
            fail("ERR_ANIMAL_HAS_ACTIVE_AGREEMENT")

    for party in (sending, receiving):
        if party["accreditation_status"] not in calc.LIVE_ACCREDITATION:
            fail("ERR_INSTITUTION_NOT_ACCREDITED")

    if animal["holding_institution_id"] != sending_id:
        fail("ERR_ANIMAL_NOT_HELD_BY_SENDER")

    agreement = db.insert(db.agreements, {
        "recommendation_id": recommendation_id,
        "animal_id": animal_id,
        "sending_institution_id": sending_id,
        "receiving_institution_id": receiving_id,
        "ownership_disposition": ownership,
        "offspring_disposition_rule": offspring,
        "breeding_rights": rights,
        "transport_cost_share_pct": share,
        "transfer_scope": calc.transfer_scope(sending["jurisdiction_code"],
                                             receiving["jurisdiction_code"]),
        "round_number": 0,
        "last_action_institution_id": None,
        "status": "DRAFT",
        "provisional_credit_points": None,
        "final_credit_points": None,
        "executed_at": None,
        "termination_reason": None,
    })
    return ok(services.agreement_out(agreement), 201)


def _negotiate(agreement_id, allowed_from, new_status):
    b = body()
    ownership, offspring, rights, share = _terms(b, False)
    agreement = db.get_agreement(agreement_id)

    side = "sending_institution_id" if agreement["status"] == "DRAFT" else None
    services.party_check(agreement, actor(), side)
    _turn_check(agreement)

    if agreement["status"] not in allowed_from:
        fail("ERR_AGREEMENT_INVALID_STATE")
    if agreement["round_number"] >= calc.MAX_NEGOTIATION_ROUNDS:
        fail("ERR_NEGOTIATION_ROUND_LIMIT")

    if ownership is not None:
        agreement["ownership_disposition"] = ownership
    if offspring is not None:
        agreement["offspring_disposition_rule"] = offspring
    if rights is not None:
        agreement["breeding_rights"] = rights
    if share is not None:
        agreement["transport_cost_share_pct"] = share

    agreement["round_number"] += 1
    agreement["last_action_institution_id"] = actor()
    agreement["status"] = new_status
    db.touch(agreement)
    return ok(services.agreement_out(agreement))


@bp.post("/transfer-agreements/<agreement_id>/offer")
@auth("Registrar")
def offer_agreement(agreement_id):
    return _negotiate(agreement_id, ("DRAFT", "COUNTERED"), "OFFERED")


@bp.post("/transfer-agreements/<agreement_id>/counter")
@auth("Registrar")
def counter_agreement(agreement_id):
    return _negotiate(agreement_id, ("OFFERED",), "COUNTERED")


@bp.post("/transfer-agreements/<agreement_id>/accept")
@auth("Registrar")
def accept_agreement(agreement_id):
    b = body()
    get_str(b, "acceptance_note")
    agreement = db.get_agreement(agreement_id)

    services.party_check(agreement, actor())
    _turn_check(agreement)

    if agreement["status"] not in ("OFFERED", "COUNTERED"):
        fail("ERR_AGREEMENT_INVALID_STATE")
    rec = db.recommendations.get(agreement["recommendation_id"])
    if rec is None or rec["status"] != "ENDORSED":
        fail("ERR_RECOMMENDATION_NOT_ENDORSED")

    receiving = db.institutions.get(agreement["receiving_institution_id"])
    if receiving is None or receiving["accreditation_status"] not in calc.LIVE_ACCREDITATION:
        fail("ERR_INSTITUTION_NOT_ACCREDITED")

    agreement["status"] = "ACCEPTED"
    db.touch(agreement)
    return ok(services.agreement_out(agreement))


@bp.post("/transfer-agreements/<agreement_id>/execute")
@auth("Registrar")
def execute_agreement(agreement_id):
    b = body()
    get_str(b, "execution_note")
    agreement = db.get_agreement(agreement_id)

    services.party_check(agreement, actor(), "sending_institution_id")

    if agreement["status"] != "ACCEPTED":
        fail("ERR_AGREEMENT_INVALID_STATE")
    rec = db.recommendations.get(agreement["recommendation_id"])
    if rec is None or rec["status"] != "ENDORSED":
        fail("ERR_RECOMMENDATION_NOT_ENDORSED")
    animal = db.animals.get(agreement["animal_id"])
    if animal is None or animal["location_status"] != "HELD":
        fail("ERR_ANIMAL_LOCATION_CONFLICT")

    sending = db.institutions.get(agreement["sending_institution_id"])
    receiving = db.institutions.get(agreement["receiving_institution_id"])
    if receiving is None or receiving["accreditation_status"] not in calc.LIVE_ACCREDITATION:
        fail("ERR_INSTITUTION_NOT_ACCREDITED")
    if agreement["transfer_scope"] == "INTERNATIONAL" \
            and receiving["accreditation_status"] != "ACCREDITED":
        fail("ERR_INTERNATIONAL_TRANSFER_NOT_PERMITTED")
    if agreement["ownership_disposition"] == "OWNERSHIP_TRANSFER" \
            and not receiving["disposition_policy_on_file"]:
        fail("ERR_DISPOSITION_POLICY_MISSING")

    if animal["holding_institution_id"] != agreement["sending_institution_id"]:
        fail("ERR_ANIMAL_NOT_HELD_BY_SENDER")
    used = services.occupied_slots(receiving["id"]) + services.reserved_slots(receiving["id"])
    if used + 1 > receiving["holding_capacity_slots"]:
        fail("ERR_HOLDING_CAPACITY_EXCEEDED")

    provisional = services.valuation(agreement, now_date())
    agreement["provisional_credit_points"] = provisional
    agreement["status"] = "EXECUTED"
    agreement["executed_at"] = now_instant()
    db.touch(agreement)

    services.post_credit(sending, receiving, provisional)

    animal["location_status"] = "RESERVED"
    if agreement["ownership_disposition"] == "OWNERSHIP_TRANSFER":
        animal["owning_institution_id"] = agreement["receiving_institution_id"]
    animal["pending_recommendation_id"] = None
    db.touch(animal)

    rec["status"] = "FULFILLED"
    db.touch(rec)
    services.rollup_program(db.programs.get(rec["species_program_id"]))
    return ok(services.agreement_out(agreement))


@bp.post("/transfer-agreements/<agreement_id>/terminate")
@auth("Registrar")
def terminate(agreement_id):
    b = body()
    reason = get_str(b, "reason", required=True)
    agreement = db.get_agreement(agreement_id)

    services.party_check(agreement, actor())

    if agreement["status"] not in ("OFFERED", "COUNTERED", "ACCEPTED", "EXECUTED"):
        fail("ERR_AGREEMENT_INVALID_STATE")
    animal = db.animals.get(agreement["animal_id"])
    if animal is None or animal["location_status"] not in ("HELD", "RESERVED"):
        fail("ERR_ANIMAL_LOCATION_CONFLICT")

    services.terminate_agreement(agreement, reason)
    return ok(services.agreement_out(agreement))


@bp.get("/transfer-agreements/<agreement_id>")
@auth()
def read_agreement(agreement_id):
    return ok(services.agreement_out(db.get_agreement(agreement_id)))


@bp.get("/transfer-agreements")
@auth()
def list_agreements():
    limit, offset = pagination()
    filters = {
        "recommendation_id": q_str("recommendation_id"),
        "animal_id": q_str("animal_id"),
        "sending_institution_id": q_str("sending_institution_id"),
        "receiving_institution_id": q_str("receiving_institution_id"),
        "last_action_institution_id": q_str("last_action_institution_id"),
        "transfer_scope": q_enum("transfer_scope", SCOPES),
        "status": q_enum("status", STATUSES),
    }
    rows = list(db.agreements.values())
    for field, value in filters.items():
        if value is not None:
            rows = [r for r in rows if r[field] == value]
    return paginate(sorted_rows(rows), limit, offset, services.agreement_out)
