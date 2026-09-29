"""Existence resolution (PRD section 2.6) and relationship walks."""
import db
from errors import (
    ERR_AUTOSHIP_RUN_NOT_FOUND,
    ERR_CERTIFICATE_NOT_FOUND,
    ERR_ENROLLMENT_NOT_FOUND,
    ERR_FACILITY_NOT_FOUND,
    ERR_KIT_NOT_FOUND,
    ERR_LABEL_NOT_FOUND,
    ERR_LEDGER_ENTRY_NOT_FOUND,
    ERR_NONCONFORMANCE_EVENT_NOT_FOUND,
    ERR_PACKAGING_SPEC_NOT_FOUND,
    ERR_PATIENT_NOT_FOUND,
    ERR_PROGRAM_NOT_FOUND,
    ERR_SHIPMENT_NOT_FOUND,
    ERR_SPONSOR_NOT_FOUND,
    ERR_STATE_RULE_NOT_FOUND,
    fail,
)

_SPECS = (
    ("state_rule", "state_rules", ERR_STATE_RULE_NOT_FOUND),
    ("packaging_spec", "packaging_specs", ERR_PACKAGING_SPEC_NOT_FOUND),
    ("facility", "treatment_facilities", ERR_FACILITY_NOT_FOUND),
    ("sponsor", "sponsors", ERR_SPONSOR_NOT_FOUND),
    ("program", "programs", ERR_PROGRAM_NOT_FOUND),
    ("patient", "patients", ERR_PATIENT_NOT_FOUND),
    ("enrollment", "enrollments", ERR_ENROLLMENT_NOT_FOUND),
    ("kit", "kits", ERR_KIT_NOT_FOUND),
    ("label", "return_labels", ERR_LABEL_NOT_FOUND),
    ("shipment", "shipments", ERR_SHIPMENT_NOT_FOUND),
    ("nonconformance_event", "nonconformance_events", ERR_NONCONFORMANCE_EVENT_NOT_FOUND),
    ("certificate", "certificates", ERR_CERTIFICATE_NOT_FOUND),
    ("ledger_entry", "ledger_entries", ERR_LEDGER_ENTRY_NOT_FOUND),
    ("autoship_run", "autoship_runs", ERR_AUTOSHIP_RUN_NOT_FOUND),
)

COLLECTION_OF = {name: coll for name, coll, _err in _SPECS}
ERROR_OF = {name: err for name, _coll, err in _SPECS}


def find(kind, row_id):
    return db.get(COLLECTION_OF[kind], row_id)


def require(kind, row_id):
    row = find(kind, row_id)
    if row is None:
        fail(ERROR_OF[kind])
    return row


def require_filter(kind, row_id):
    """Existence check for an id supplied as a list filter."""
    if row_id is None:
        return None
    return require(kind, row_id)


# ---- relationship walks -------------------------------------------------

def kit_enrollment(kit):
    return db.get("enrollments", kit["enrollment_id"])


def enrollment_patient(enrollment):
    return db.get("patients", enrollment["patient_id"])


def enrollment_program(enrollment):
    return db.get("programs", enrollment["sponsorship_program_id"])


def program_sponsor(program):
    return db.get("sponsors", program["sponsor_id"])


def patient_state_rule(patient):
    return db.get("state_rules", patient["state_rule_id"])


def kit_patient(kit):
    return enrollment_patient(kit_enrollment(kit))


def kit_program(kit):
    return enrollment_program(kit_enrollment(kit))


def kit_sponsor(kit):
    return program_sponsor(kit_program(kit))


def shipment_kit(shipment):
    return db.get("kits", shipment["kit_id"])


def shipment_label(shipment):
    return db.get("return_labels", shipment["return_label_id"])


def shipment_spec(shipment):
    label = shipment_label(shipment)
    if label is None:
        return None
    return db.get("packaging_specs", label["packaging_spec_id"])


def shipment_facility(shipment):
    return db.get("treatment_facilities", shipment["treatment_facility_id"])


def shipment_patient(shipment):
    kit = shipment_kit(shipment)
    if kit is None:
        return None
    return kit_patient(kit)


def facility_state_rule(facility):
    return db.get("state_rules", facility["state_rule_id"])


def shipment_events(shipment_id):
    return db.ordered("nonconformance_events", lambda e: e["shipment_id"] == shipment_id)


def shipment_certificates(shipment_id):
    return db.ordered("certificates", lambda c: c["shipment_id"] == shipment_id)


def enrollment_kits(enrollment_id):
    return db.ordered("kits", lambda k: k["enrollment_id"] == enrollment_id)


def patient_enrollments(patient_id):
    return db.ordered("enrollments", lambda e: e["patient_id"] == patient_id)


def patient_kits(patient_id):
    kits = []
    for enrollment in patient_enrollments(patient_id):
        kits.extend(enrollment_kits(enrollment["id"]))
    return kits


def kit_labels(kit_id):
    return db.ordered("return_labels", lambda l: l["kit_id"] == kit_id)
