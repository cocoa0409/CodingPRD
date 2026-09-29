"""Derived counters, rollups, the credit ledger, serialisers and the compensating cascades."""
from datetime import date, timedelta
from decimal import Decimal

import calc
import db
from core import dec, fmt_date, now_date, now_instant, num, rh


def as_date(value):
    if value is None:
        return None
    if isinstance(value, date):
        return value
    return date(int(value[0:4]), int(value[5:7]), int(value[8:10]))


# --------------------------------------------------------------- derived counters
def occupied_slots(institution_id):
    return sum(1 for a in db.animals.values()
               if a["holding_institution_id"] == institution_id
               and a["location_status"] in calc.OCCUPIED_LOCATIONS)


def reserved_slots(institution_id):
    total = 0
    for a in db.animals.values():
        if a["location_status"] not in calc.RESERVED_LOCATIONS:
            continue
        for ag in db.agreements.values():
            if ag["animal_id"] == a["id"] and ag["status"] == "EXECUTED" \
                    and ag["receiving_institution_id"] == institution_id:
                total += 1
                break
    return total


def population_count(program_id):
    return sum(1 for a in db.animals.values()
               if a["species_program_id"] == program_id and a["location_status"] != "DISPOSED")


def open_recommendations(program):
    return [r for r in db.recommendations.values()
            if r["species_program_id"] == program["id"]
            and r["plan_cycle"] == program["current_plan_cycle"]
            and r["status"] in ("PROPOSED", "ENDORSED")]


def cycle_has_any_recommendation(program):
    return any(r for r in db.recommendations.values()
               if r["species_program_id"] == program["id"]
               and r["plan_cycle"] == program["current_plan_cycle"])


def crate_sessions_for(animal_id):
    return [s for s in db.crate_sessions if s["animal_id"] == animal_id]


def crate_count(animal_id):
    return len(crate_sessions_for(animal_id))


def last_crate_session(animal_id):
    rows = crate_sessions_for(animal_id)
    if not rows:
        return None
    return max(rows, key=lambda s: s["session_date"])["session_date"]


def rollup_program(program):
    """Recompute the open-recommendation set and bubble the plan cycle up or down."""
    if program is None:
        return
    count = len(open_recommendations(program))
    if program["plan_status"] == "PUBLISHED" and count == 0 and cycle_has_any_recommendation(program):
        program["plan_status"] = "CYCLE_CLOSED"
        program["cycle_closed_on"] = now_instant()
        db.touch(program)
    elif program["plan_status"] == "CYCLE_CLOSED" and count > 0:
        program["plan_status"] = "PUBLISHED"
        program["cycle_closed_on"] = None
        db.touch(program)


def rollup_programs(program_ids):
    for pid in sorted(set(program_ids)):
        program = db.programs.get(pid)
        if program is not None:
            rollup_program(program)


# ------------------------------------------------------------------------ ledger
def post_credit(sending, receiving, amount):
    amount = rh(amount, 2)
    sending["transfer_credit_balance"] = rh(dec(sending["transfer_credit_balance"]) + amount, 2)
    receiving["transfer_credit_balance"] = rh(dec(receiving["transfer_credit_balance"]) - amount, 2)


# ------------------------------------------------------------------- serialisers
def institution_out(rec):
    return {
        "id": rec["id"],
        "name": rec["name"],
        "jurisdiction_code": rec["jurisdiction_code"],
        "accreditation_status": rec["accreditation_status"],
        "accreditation_expires_on": rec["accreditation_expires_on"],
        "holding_capacity_slots": rec["holding_capacity_slots"],
        "disposition_policy_on_file": rec["disposition_policy_on_file"],
        "occupied_slots": occupied_slots(rec["id"]),
        "reserved_slots": reserved_slots(rec["id"]),
        "transfer_credit_balance": num(rh(dec(rec["transfer_credit_balance"]), 2)),
        "compliance_points_balance": num(rh(dec(rec["compliance_points_balance"]), 2)),
        "created_at": rec["created_at"],
        "updated_at": rec["updated_at"],
        "version": rec["version"],
    }


def program_out(rec):
    return {
        "id": rec["id"],
        "taxon_name": rec["taxon_name"],
        "program_type": rec["program_type"],
        "target_population_size": rec["target_population_size"],
        "studbook_keeper_name": rec["studbook_keeper_name"],
        "plan_status": rec["plan_status"],
        "current_plan_cycle": rec["current_plan_cycle"],
        "current_population_count": population_count(rec["id"]),
        "open_recommendation_count": len(open_recommendations(rec)),
        "cycle_closed_on": rec["cycle_closed_on"],
        "created_at": rec["created_at"],
        "updated_at": rec["updated_at"],
        "version": rec["version"],
    }


def vet_out(rec):
    return {
        "id": rec["id"],
        "institution_id": rec["institution_id"],
        "full_name": rec["full_name"],
        "license_number": rec["license_number"],
        "license_jurisdiction": rec["license_jurisdiction"],
        "license_status": rec["license_status"],
        "usda_accreditation_category": rec["usda_accreditation_category"],
        "created_at": rec["created_at"],
        "updated_at": rec["updated_at"],
        "version": rec["version"],
    }


def animal_out(rec):
    return {
        "id": rec["id"],
        "species_program_id": rec["species_program_id"],
        "holding_institution_id": rec["holding_institution_id"],
        "owning_institution_id": rec["owning_institution_id"],
        "local_id": rec["local_id"],
        "sex": rec["sex"],
        "birth_date": rec["birth_date"],
        "sire_id": rec["sire_id"],
        "dam_id": rec["dam_id"],
        "founder_representation_pct": num(rec["founder_representation_pct"]),
        "location_status": rec["location_status"],
        "genetic_designation": rec["genetic_designation"],
        "pending_recommendation_id": rec["pending_recommendation_id"],
        "crate_training_sessions_count": crate_count(rec["id"]),
        "last_crate_session_on": last_crate_session(rec["id"]),
        "created_at": rec["created_at"],
        "updated_at": rec["updated_at"],
        "version": rec["version"],
    }


def recommendation_out(rec):
    return {
        "id": rec["id"],
        "species_program_id": rec["species_program_id"],
        "plan_cycle": rec["plan_cycle"],
        "recommendation_type": rec["recommendation_type"],
        "subject_animal_id": rec["subject_animal_id"],
        "paired_animal_id": rec["paired_animal_id"],
        "sending_institution_id": rec["sending_institution_id"],
        "receiving_institution_id": rec["receiving_institution_id"],
        "analysis_mode": rec["analysis_mode"],
        "molecular_similarity_pct": num(rec["molecular_similarity_pct"]),
        "kinship_coefficient": num(rec["kinship_coefficient"]),
        "projected_offspring_inbreeding": num(rec["projected_offspring_inbreeding"]),
        "pairing_verdict": rec["pairing_verdict"],
        "demographic_need_index": num(rec["demographic_need_index"]),
        "genetic_value_score": num(rec["genetic_value_score"]),
        "priority_rank": rec["priority_rank"],
        "expires_on": rec["expires_on"],
        "status": rec["status"],
        "created_at": rec["created_at"],
        "updated_at": rec["updated_at"],
        "version": rec["version"],
    }


def agreement_out(rec):
    return {
        "id": rec["id"],
        "recommendation_id": rec["recommendation_id"],
        "animal_id": rec["animal_id"],
        "sending_institution_id": rec["sending_institution_id"],
        "receiving_institution_id": rec["receiving_institution_id"],
        "ownership_disposition": rec["ownership_disposition"],
        "offspring_disposition_rule": rec["offspring_disposition_rule"],
        "breeding_rights": rec["breeding_rights"],
        "transport_cost_share_pct": num(rec["transport_cost_share_pct"]),
        "transfer_scope": rec["transfer_scope"],
        "round_number": rec["round_number"],
        "last_action_institution_id": rec["last_action_institution_id"],
        "status": rec["status"],
        "provisional_credit_points": num(rec["provisional_credit_points"]),
        "final_credit_points": num(rec["final_credit_points"]),
        "executed_at": rec["executed_at"],
        "termination_reason": rec["termination_reason"],
        "created_at": rec["created_at"],
        "updated_at": rec["updated_at"],
        "version": rec["version"],
    }


def document_out(rec):
    return {
        "id": rec["id"],
        "transfer_agreement_id": rec["transfer_agreement_id"],
        "document_type": rec["document_type"],
        "issuing_veterinarian_id": rec["issuing_veterinarian_id"],
        "issuing_authority_name": rec["issuing_authority_name"],
        "exam_date": rec["exam_date"],
        "document_number": rec["document_number"],
        "valid_from": rec["valid_from"],
        "valid_until": rec["valid_until"],
        "status": rec["status"],
        "decision_note": rec["decision_note"],
        "created_at": rec["created_at"],
        "updated_at": rec["updated_at"],
        "version": rec["version"],
    }


def test_out(rec):
    return {
        "id": rec["id"],
        "transfer_agreement_id": rec["transfer_agreement_id"],
        "animal_id": rec["animal_id"],
        "collecting_veterinarian_id": rec["collecting_veterinarian_id"],
        "test_code": rec["test_code"],
        "collected_on": rec["collected_on"],
        "result": rec["result"],
        "lab_reference": rec["lab_reference"],
        "created_at": rec["created_at"],
    }


def occupancy_out(rec):
    return {
        "id": rec["id"],
        "institution_id": rec["institution_id"],
        "transfer_agreement_id": rec["transfer_agreement_id"],
        "animal_id": rec["animal_id"],
        "clearing_veterinarian_id": rec["clearing_veterinarian_id"],
        "quarantine_room_code": rec["quarantine_room_code"],
        "scheduled_start_date": rec["scheduled_start_date"],
        "scheduled_end_date": rec["scheduled_end_date"],
        "actual_start_date": rec["actual_start_date"],
        "isolation_class": rec["isolation_class"],
        "required_days": rec["required_days"],
        "phase": rec["phase"],
        "cleared_on": rec["cleared_on"],
        "created_at": rec["created_at"],
        "updated_at": rec["updated_at"],
        "version": rec["version"],
    }


def booking_out(rec):
    return {
        "id": rec["id"],
        "transfer_agreement_id": rec["transfer_agreement_id"],
        "carrier_code": rec["carrier_code"],
        "crate_serial": rec["crate_serial"],
        "departure_utc": rec["departure_utc"],
        "arrival_utc": rec["arrival_utc"],
        "temp_min_c": num(rec["temp_min_c"]),
        "temp_max_c": num(rec["temp_max_c"]),
        "temperature_samples": rec["temperature_samples"],
        "thermal_excursion_minutes": rec["thermal_excursion_minutes"],
        "status": rec["status"],
        "departed_at": rec["departed_at"],
        "delivered_at": rec["delivered_at"],
        "created_at": rec["created_at"],
        "updated_at": rec["updated_at"],
        "version": rec["version"],
    }


def protocol_out(rec):
    return {
        "id": rec["id"],
        "transfer_agreement_id": rec["transfer_agreement_id"],
        "animal_id": rec["animal_id"],
        "institution_id": rec["institution_id"],
        "resident_group_code": rec["resident_group_code"],
        "stage": rec["stage"],
        "sessions_at_stage": rec["sessions_at_stage"],
        "aggression_score_total": num(rh(dec(rec["aggression_score_total"]), 2)),
        "regression_count": rec["regression_count"],
        "observation_count": rec["observation_count"],
        "started_on": rec["started_on"],
        "created_at": rec["created_at"],
        "updated_at": rec["updated_at"],
        "version": rec["version"],
    }


def submission_out(rec):
    return {
        "id": rec["id"],
        "species_program_id": rec["species_program_id"],
        "institution_id": rec["institution_id"],
        "transfer_agreement_id": rec["transfer_agreement_id"],
        "submission_type": rec["submission_type"],
        "reporting_period_end": rec["reporting_period_end"],
        "submitted_on": rec["submitted_on"],
        "days_late": rec["days_late"],
        "base_points": num(rec["base_points"]),
        "surcharge_multiplier": num(rec["surcharge_multiplier"]),
        "surcharge_points": num(rec["surcharge_points"]),
        "total_compliance_points": num(rec["total_compliance_points"]),
        "status": rec["status"],
        "review_note": rec["review_note"],
        "created_at": rec["created_at"],
        "updated_at": rec["updated_at"],
        "version": rec["version"],
    }


# --------------------------------------------------------------- lookup helpers
def documents_of(agreement_id):
    return db.sorted_by_seq([d for d in db.documents.values()
                             if d["transfer_agreement_id"] == agreement_id])


def tests_of(agreement_id):
    return db.sorted_by_seq([t for t in db.tests.values()
                            if t["transfer_agreement_id"] == agreement_id])


def bookings_of(agreement_id):
    return db.sorted_by_seq([b for b in db.bookings.values()
                            if b["transfer_agreement_id"] == agreement_id])


def occupancies_of(agreement_id):
    return db.sorted_by_seq([o for o in db.occupancies.values()
                            if o["transfer_agreement_id"] == agreement_id])


def agreements_of_animal(animal_id):
    return db.sorted_by_seq([a for a in db.agreements.values() if a["animal_id"] == animal_id])


# -------------------------------------------------------------------- cascades
def void_documents(agreement_id, note):
    for doc in documents_of(agreement_id):
        if doc["status"] in ("DRAFT", "ISSUED"):
            doc["status"] = "VOIDED"
            doc["decision_note"] = note
            db.touch(doc)


def void_issued_certificates(agreement_id, note):
    for doc in documents_of(agreement_id):
        if doc["document_type"] == "INTERSTATE_CVI" and doc["status"] == "ISSUED":
            doc["status"] = "VOIDED"
            doc["decision_note"] = note
            db.touch(doc)


def abort_live_bookings(agreement_id):
    for bk in bookings_of(agreement_id):
        if bk["status"] in ("RESERVED", "CONFIRMED"):
            bk["status"] = "ABORTED"
            db.touch(bk)


def cancel_scheduled_occupancies(agreement_id):
    for occ in occupancies_of(agreement_id):
        if occ["phase"] == "SCHEDULED":
            occ["phase"] = "CANCELLED"
            db.touch(occ)


def terminate_agreement(agreement, reason, skip_animal_location=False):
    """Apply the status-dependent compensating chain, then stamp the termination."""
    origin = agreement["status"]
    animal = db.animals.get(agreement["animal_id"])
    sending = db.institutions.get(agreement["sending_institution_id"])
    receiving = db.institutions.get(agreement["receiving_institution_id"])

    if origin == "EXECUTED":
        # 1. reverse the ledger at its recorded net value
        net = agreement["final_credit_points"]
        if net is None:
            net = agreement["provisional_credit_points"]
        if net is not None and sending is not None and receiving is not None:
            post_credit(sending, receiving, -dec(net))
        # 2. ownership returns to the sender under an ownership transfer
        if animal is not None and agreement["ownership_disposition"] == "OWNERSHIP_TRANSFER":
            animal["owning_institution_id"] = agreement["sending_institution_id"]
            db.touch(animal)
        # 3. an animal standing at RESERVED returns to HELD
        if animal is not None and animal["location_status"] == "RESERVED":
            animal["location_status"] = "HELD"
            db.touch(animal)
        # 4. the founding recommendation is pulled back into the open set
        rec = db.recommendations.get(agreement["recommendation_id"])
        if rec is not None and rec["status"] == "FULFILLED":
            rec["status"] = "ENDORSED"
            db.touch(rec)
            if animal is not None:
                animal["pending_recommendation_id"] = rec["id"]
                db.touch(animal)
            # 5. the programme reopens when the count rises above zero
            rollup_program(db.programs.get(rec["species_program_id"]))
        # 6/7/8. transport, rooms and paperwork are released
        abort_live_bookings(agreement["id"])
        cancel_scheduled_occupancies(agreement["id"])
        void_documents(agreement["id"], "VOIDED_BY_TERMINATION")
    elif origin == "ACCEPTED":
        void_documents(agreement["id"], "VOIDED_BY_TERMINATION")

    agreement["status"] = "TERMINATED"
    agreement["termination_reason"] = reason
    db.touch(agreement)


def decline_breed_recommendations(animal):
    """Every BREED_WITH recommendation still open that names this animal is declined."""
    touched_programs = []
    for rec in db.sorted_by_seq(list(db.recommendations.values())):
        if rec["recommendation_type"] != "BREED_WITH":
            continue
        if rec["status"] not in ("PROPOSED", "ENDORSED"):
            continue
        if animal["id"] not in (rec["subject_animal_id"], rec["paired_animal_id"]):
            continue
        rec["status"] = "DECLINED"
        db.touch(rec)
        touched_programs.append(rec["species_program_id"])
        if animal.get("pending_recommendation_id") == rec["id"]:
            animal["pending_recommendation_id"] = None
            db.touch(animal)
        subject = db.animals.get(rec["subject_animal_id"])
        if subject is not None and subject is not animal \
                and subject.get("pending_recommendation_id") == rec["id"]:
            subject["pending_recommendation_id"] = None
            db.touch(subject)
    rollup_programs(touched_programs)


def valuation(agreement, on_date):
    """The three-component credit valuation of section 3.6, valued at on_date."""
    rec = db.recommendations.get(agreement["recommendation_id"])
    animal = db.animals.get(agreement["animal_id"])
    score = rec["genetic_value_score"] if rec is not None else Decimal("0.00")
    if score is None:
        score = Decimal("0.00")
    age_years = calc.whole_years(as_date(animal["birth_date"]), on_date) if animal else 0
    return calc.credit_points(score, age_years,
                              agreement["transport_cost_share_pct"],
                              agreement["ownership_disposition"])


def party_check(agreement, actor_id, side=None):
    """Rung 5: strangers and wrong-side actors both hear ERR_NOT_A_PARTY_TO_AGREEMENT."""
    from core import fail
    parties = (agreement["sending_institution_id"], agreement["receiving_institution_id"])
    if actor_id not in parties:
        fail("ERR_NOT_A_PARTY_TO_AGREEMENT")
    if side is not None and actor_id != agreement[side]:
        fail("ERR_NOT_A_PARTY_TO_AGREEMENT")


def as_instant(value):
    """Parse a stored ISO-8601 instant back into an aware datetime."""
    import datetime as _dt

    from core import parse_instant
    if value is None:
        return None
    if isinstance(value, _dt.datetime):
        return value
    return parse_instant(value, "instant")
