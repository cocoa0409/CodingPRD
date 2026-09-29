from flask import Blueprint

import db
import services
from core import (actor, auth, body, fail, get_date, get_enum, get_str, ok, pagination, paginate,
                  q_enum, q_str, sorted_rows)

bp = Blueprint("tests", __name__)

CODES = ("TB", "BRUCELLA", "HERPESVIRUS", "FECAL_PARASITE")
RESULTS = ("NEGATIVE", "POSITIVE", "INCONCLUSIVE")


@bp.post("/pre-shipment-tests")
@auth("Veterinarian")
def create_test():
    b = body()
    agreement_id = get_str(b, "transfer_agreement_id", required=True)
    animal_id = get_str(b, "animal_id", required=True)
    vet_id = get_str(b, "collecting_veterinarian_id", required=True)
    test_code = get_enum(b, "test_code", CODES, required=True)
    collected_on, collected_raw = get_date(b, "collected_on", required=True)
    result = get_enum(b, "result", RESULTS, required=True)
    lab_reference = get_str(b, "lab_reference", required=True)

    agreement = db.get_agreement(agreement_id)
    db.get_animal(animal_id)
    vet = db.get_vet(vet_id)

    if actor() != vet_id:
        fail("ERR_VET_INSTITUTION_MISMATCH")
    parties = (agreement["sending_institution_id"], agreement["receiving_institution_id"])
    if vet["institution_id"] not in parties:
        fail("ERR_NOT_A_PARTY_TO_AGREEMENT")
    if vet["institution_id"] != agreement["sending_institution_id"]:
        fail("ERR_VET_INSTITUTION_MISMATCH")

    if agreement["status"] not in ("ACCEPTED", "EXECUTED"):
        fail("ERR_AGREEMENT_INVALID_STATE")

    if vet["license_status"] != "ACTIVE":
        fail("ERR_VET_LICENSE_INVALID")

    row = db.insert(db.tests, {
        "transfer_agreement_id": agreement_id,
        "animal_id": animal_id,
        "collecting_veterinarian_id": vet_id,
        "test_code": test_code,
        "collected_on": collected_raw,
        "result": result,
        "lab_reference": lab_reference,
    }, common=False)

    if result == "POSITIVE":
        services.void_issued_certificates(agreement_id, "VOIDED_BY_POSITIVE_TEST")
        services.abort_live_bookings(agreement_id)

    return ok(services.test_out(row), 201)


@bp.get("/pre-shipment-tests/<test_id>")
@auth()
def read_test(test_id):
    return ok(services.test_out(db.get_test(test_id)))


@bp.get("/pre-shipment-tests")
@auth()
def list_tests():
    limit, offset = pagination()
    filters = {
        "transfer_agreement_id": q_str("transfer_agreement_id"),
        "animal_id": q_str("animal_id"),
        "collecting_veterinarian_id": q_str("collecting_veterinarian_id"),
        "test_code": q_enum("test_code", CODES),
        "result": q_enum("result", RESULTS),
    }
    rows = list(db.tests.values())
    for field, value in filters.items():
        if value is not None:
            rows = [r for r in rows if r[field] == value]
    return paginate(sorted_rows(rows), limit, offset, services.test_out)
