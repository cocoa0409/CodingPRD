from flask import Blueprint

import calc
import db
import services
from core import (actor, auth, body, fail, get_date, get_enum, get_int, get_num, get_str,
                  now_date, ok, pagination, paginate, q_enum, q_str, rh, sorted_rows)

bp = Blueprint("recommendations", __name__)

TYPES = ("BREED_WITH", "HOLD", "TRANSFER_OUT", "SURPLUS_DISPOSITION")
MODES = ("PEDIGREE_ONLY", "PEDIGREE_PLUS_MOLECULAR")
VERDICTS = ("RECOMMENDED", "CONDITIONAL", "NOT_RECOMMENDED", "NOT_APPLICABLE")
STATUSES = ("PROPOSED", "ENDORSED", "DECLINED", "SUPERSEDED", "FULFILLED", "EXPIRED")


@bp.post("/population-recommendations")
@auth("ProgramCoordinator")
def create_recommendation():
    b = body()
    program_id = get_str(b, "species_program_id", required=True)
    rec_type = get_enum(b, "recommendation_type", TYPES, required=True)
    subject_id = get_str(b, "subject_animal_id", required=True)
    paired_id = get_str(b, "paired_animal_id")
    sending_id = get_str(b, "sending_institution_id")
    receiving_id = get_str(b, "receiving_institution_id")
    mode = get_enum(b, "analysis_mode", MODES, required=True)
    molecular = get_num(b, "molecular_similarity_pct", minimum=0, maximum=100)
    priority_rank = get_int(b, "priority_rank", required=True, minimum=1)
    expires_on, expires_raw = get_date(b, "expires_on", required=True)
    expected_version = get_int(b, "expected_subject_animal_version", required=True)

    if rec_type in ("BREED_WITH", "TRANSFER_OUT"):
        if sending_id is None:
            fail("ERR_INVALID_REQUEST", "sending_institution_id is required for %s." % rec_type)
        if receiving_id is None:
            fail("ERR_INVALID_REQUEST", "receiving_institution_id is required for %s." % rec_type)
    if mode == "PEDIGREE_PLUS_MOLECULAR" and molecular is None:
        fail("ERR_INVALID_REQUEST",
             "molecular_similarity_pct is required under PEDIGREE_PLUS_MOLECULAR.")

    # existence, in the field order declared on PopulationRecommendation
    program = db.get_program(program_id)
    subject = db.get_animal(subject_id)
    paired = db.get_animal(paired_id) if paired_id is not None else None
    if sending_id is not None:
        db.get_institution(sending_id)
    if receiving_id is not None:
        db.get_institution(receiving_id)

    if actor() != program["id"]:
        fail("ERR_ACTOR_SCOPE_VIOLATION")

    if expected_version != subject["version"]:
        fail("ERR_STALE_ANIMAL_VERSION")

    if program["plan_status"] != "PUBLISHED":
        fail("ERR_PROGRAM_PLAN_NOT_PUBLISHED")

    plan_cycle = program["current_plan_cycle"]
    standing = [r for r in db.sorted_by_seq(list(db.recommendations.values()))
                if r["subject_animal_id"] == subject_id and r["plan_cycle"] == plan_cycle]
    for r in standing:
        if r["status"] in ("ENDORSED", "FULFILLED"):
            fail("ERR_RECOMMENDATION_ALREADY_ENDORSED")

    if rec_type == "BREED_WITH":
        if paired is None:
            fail("ERR_INVALID_PAIRING")
        if paired["id"] == subject["id"]:
            fail("ERR_INVALID_PAIRING")
        if paired["species_program_id"] != subject["species_program_id"]:
            fail("ERR_INVALID_PAIRING")
        if subject["location_status"] == "DISPOSED" or paired["location_status"] == "DISPOSED":
            fail("ERR_INVALID_PAIRING")
        if {subject["sex"], paired["sex"]} != {"MALE", "FEMALE"}:
            fail("ERR_INVALID_PAIRING")
    elif paired is not None:
        fail("ERR_INVALID_PAIRING")

    if rec_type == "BREED_WITH":
        f_pedigree = calc.pedigree_kinship(db.animals, subject, paired)
        kinship = rh(f_pedigree, 4)
        projected = calc.projected_inbreeding(f_pedigree, mode, molecular)
    else:
        kinship = None
        projected = None
    verdict = calc.pairing_verdict(rec_type, projected)

    index, score = calc.demographic_need(
        program["program_type"], program["target_population_size"],
        services.population_count(program["id"]), subject["founder_representation_pct"],
        kinship,
    )

    rec = db.insert(db.recommendations, {
        "species_program_id": program_id,
        "plan_cycle": plan_cycle,
        "recommendation_type": rec_type,
        "subject_animal_id": subject_id,
        "paired_animal_id": paired_id,
        "sending_institution_id": sending_id,
        "receiving_institution_id": receiving_id,
        "analysis_mode": mode,
        "molecular_similarity_pct": molecular,
        "kinship_coefficient": kinship,
        "projected_offspring_inbreeding": projected,
        "pairing_verdict": verdict,
        "demographic_need_index": index,
        "genetic_value_score": score,
        "priority_rank": priority_rank,
        "expires_on": expires_raw,
        "status": "PROPOSED",
    })

    affected = [program_id]
    for r in standing:
        if r["status"] == "PROPOSED":
            r["status"] = "SUPERSEDED"
            db.touch(r)
            affected.append(r["species_program_id"])

    subject["pending_recommendation_id"] = rec["id"]
    db.touch(subject)
    services.rollup_programs(affected)
    return ok(services.recommendation_out(rec), 201)


@bp.post("/population-recommendations/<recommendation_id>/endorse")
@auth("Registrar")
def endorse_recommendation(recommendation_id):
    b = body()
    get_str(b, "endorsement_note")
    rec = db.get_recommendation(recommendation_id)
    subject = db.animals.get(rec["subject_animal_id"])

    if rec["recommendation_type"] in ("BREED_WITH", "TRANSFER_OUT"):
        owner = rec["sending_institution_id"]
    else:
        owner = subject["holding_institution_id"] if subject is not None else None
    if actor() != owner:
        fail("ERR_ACTOR_SCOPE_VIOLATION")

    if rec["status"] != "PROPOSED":
        fail("ERR_RECOMMENDATION_NOT_ENDORSED")

    if now_date() > services.as_date(rec["expires_on"]):
        rec["status"] = "EXPIRED"
        db.touch(rec)
        if subject is not None and subject.get("pending_recommendation_id") == rec["id"]:
            subject["pending_recommendation_id"] = None
            db.touch(subject)
        services.rollup_program(db.programs.get(rec["species_program_id"]))
        fail("ERR_RECOMMENDATION_EXPIRED")

    if rec["recommendation_type"] == "BREED_WITH" and rec["pairing_verdict"] == "NOT_RECOMMENDED":
        fail("ERR_INBREEDING_LIMIT_EXCEEDED")

    rec["status"] = "ENDORSED"
    db.touch(rec)

    if rec["recommendation_type"] == "BREED_WITH":
        paired = db.animals.get(rec["paired_animal_id"])
        for a in (subject, paired):
            if a is not None and a["genetic_designation"] != "BREED_RECOMMENDED":
                a["genetic_designation"] = "BREED_RECOMMENDED"
                db.touch(a)
    elif rec["recommendation_type"] == "HOLD":
        if subject is not None and subject["genetic_designation"] != "HOLD_NO_BREED":
            subject["genetic_designation"] = "HOLD_NO_BREED"
            db.touch(subject)
    elif rec["recommendation_type"] == "SURPLUS_DISPOSITION":
        if subject is not None and subject["genetic_designation"] != "SURPLUS_APPROVED":
            subject["genetic_designation"] = "SURPLUS_APPROVED"
            db.touch(subject)

    services.rollup_program(db.programs.get(rec["species_program_id"]))
    return ok(services.recommendation_out(rec))


@bp.get("/population-recommendations/<recommendation_id>")
@auth()
def read_recommendation(recommendation_id):
    return ok(services.recommendation_out(db.get_recommendation(recommendation_id)))


@bp.get("/population-recommendations")
@auth()
def list_recommendations():
    limit, offset = pagination()
    plan_cycle = None
    raw_cycle = q_str("plan_cycle")
    if raw_cycle is not None:
        try:
            plan_cycle = int(raw_cycle)
        except ValueError:
            fail("ERR_INVALID_REQUEST", "plan_cycle must be an integer.")
    filters = {
        "species_program_id": q_str("species_program_id"),
        "subject_animal_id": q_str("subject_animal_id"),
        "paired_animal_id": q_str("paired_animal_id"),
        "sending_institution_id": q_str("sending_institution_id"),
        "receiving_institution_id": q_str("receiving_institution_id"),
        "recommendation_type": q_enum("recommendation_type", TYPES),
        "pairing_verdict": q_enum("pairing_verdict", VERDICTS),
        "status": q_enum("status", STATUSES),
    }
    rows = list(db.recommendations.values())
    for field, value in filters.items():
        if value is not None:
            rows = [r for r in rows if r[field] == value]
    if plan_cycle is not None:
        rows = [r for r in rows if r["plan_cycle"] == plan_cycle]
    return paginate(sorted_rows(rows), limit, offset, services.recommendation_out)
