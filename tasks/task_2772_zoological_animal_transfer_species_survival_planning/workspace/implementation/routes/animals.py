from decimal import Decimal

from flask import Blueprint

import calc
import db
import services
from core import (actor, auth, body, fail, get_date, get_enum, get_num, get_str, ok,
                  pagination, paginate, q_enum, q_str, sorted_rows)

bp = Blueprint("animals", __name__)

SEXES = ("MALE", "FEMALE", "UNDETERMINED")
LOCATIONS = ("HELD", "RESERVED", "IN_TRANSIT", "IN_QUARANTINE", "AWAITING_INTRODUCTION",
             "INTRODUCING", "DISPOSED")
DESIGNATIONS = ("UNEVALUATED", "BREED_RECOMMENDED", "HOLD_NO_BREED", "SURPLUS_APPROVED")


@bp.post("/animals")
@auth("Registrar")
def create_animal():
    b = body()
    program_id = get_str(b, "species_program_id", required=True)
    holding_id = get_str(b, "holding_institution_id", required=True)
    owning_id = get_str(b, "owning_institution_id", required=True)
    local_id = get_str(b, "local_id", required=True)
    sex = get_enum(b, "sex", SEXES, required=True)
    birth_date, birth_raw = get_date(b, "birth_date", required=True)
    sire_id = get_str(b, "sire_id")
    dam_id = get_str(b, "dam_id")
    founder_pct = get_num(b, "founder_representation_pct", default=Decimal("0.0"),
                          minimum=0, maximum=100)

    # existence: body foreign keys in the order the fields are declared on Animal
    program = db.get_program(program_id)
    db.get_institution(holding_id)
    db.get_institution(owning_id)
    if sire_id is not None:
        db.get_animal(sire_id)
    if dam_id is not None:
        db.get_animal(dam_id)

    if actor() != holding_id:
        fail("ERR_ACTOR_SCOPE_VIOLATION")

    for other in db.animals.values():
        if other["holding_institution_id"] == holding_id and other["local_id"] == local_id:
            fail("ERR_DUPLICATE_ANIMAL_LOCAL_ID")

    rec = db.insert(db.animals, {
        "species_program_id": program_id,
        "holding_institution_id": holding_id,
        "owning_institution_id": owning_id,
        "local_id": local_id,
        "sex": sex,
        "birth_date": birth_raw,
        "sire_id": sire_id,
        "dam_id": dam_id,
        "founder_representation_pct": founder_pct,
        "location_status": "HELD",
        "genetic_designation": "UNEVALUATED",
        "pending_recommendation_id": None,
    })
    return ok(services.animal_out(rec), 201)


@bp.post("/animals/<animal_id>/crate-training-sessions")
@auth("Registrar")
def add_crate_session(animal_id):
    b = body()
    session_date, session_raw = get_date(b, "session_date", required=True)
    trainer = get_str(b, "trainer_name", required=True)
    get_num(b, "duration_minutes", required=True, minimum=0)

    animal = db.get_animal(animal_id)
    if actor() != animal["holding_institution_id"]:
        fail("ERR_ACTOR_SCOPE_VIOLATION")

    db.crate_sessions.append({
        "animal_id": animal["id"],
        "session_date": session_raw,
        "trainer_name": trainer,
        "seq": db.next_seq(),
    })
    db.touch(animal)
    return ok(services.animal_out(animal), 201)


@bp.post("/animals/<animal_id>/disposition")
@auth("Registrar")
def dispose_animal(animal_id):
    b = body()
    get_str(b, "disposition_method", required=True)
    get_str(b, "disposition_note")

    animal = db.get_animal(animal_id)
    if actor() != animal["holding_institution_id"]:
        fail("ERR_ACTOR_SCOPE_VIOLATION")

    if animal["location_status"] != "HELD":
        fail("ERR_ANIMAL_LOCATION_CONFLICT")
    for ag in services.agreements_of_animal(animal["id"]):
        if ag["status"] in calc.ACTIVE_AGREEMENT_STATUSES:
            fail("ERR_ANIMAL_HAS_ACTIVE_AGREEMENT")

    holder = db.institutions.get(animal["holding_institution_id"])
    if holder is None or not holder["disposition_policy_on_file"]:
        fail("ERR_DISPOSITION_POLICY_MISSING")
    if animal["genetic_designation"] != "SURPLUS_APPROVED":
        fail("ERR_ANIMAL_NOT_SURPLUS_APPROVED")

    animal["location_status"] = "DISPOSED"
    db.touch(animal)
    services.rollup_program(db.programs.get(animal["species_program_id"]))
    return ok(services.animal_out(animal))


@bp.get("/animals/<animal_id>")
@auth()
def read_animal(animal_id):
    return ok(services.animal_out(db.get_animal(animal_id)))


@bp.get("/animals")
@auth()
def list_animals():
    limit, offset = pagination()
    filters = {
        "species_program_id": q_str("species_program_id"),
        "holding_institution_id": q_str("holding_institution_id"),
        "owning_institution_id": q_str("owning_institution_id"),
        "sire_id": q_str("sire_id"),
        "dam_id": q_str("dam_id"),
        "pending_recommendation_id": q_str("pending_recommendation_id"),
        "location_status": q_enum("location_status", LOCATIONS),
        "genetic_designation": q_enum("genetic_designation", DESIGNATIONS),
    }
    rows = list(db.animals.values())
    for field, value in filters.items():
        if value is not None:
            rows = [r for r in rows if r[field] == value]
    return paginate(sorted_rows(rows), limit, offset, services.animal_out)
