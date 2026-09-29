"""Overlay corrections and clinical cross-contamination remediation."""

from flask import Blueprint, g

from core import (
    ALL_ROLES, CONTAMINATION_REVIEW_ELEMENT_THRESHOLD, OVERLAY_SNAPSHOT_KEYS,
    authenticate, bad_request, base_entity, created, err, field_date, field_enum,
    field_id, field_int, field_map, field_string, get_body, ok, ok_list, paginate,
    query_filter, store, touch,
)
import domain
import serializers

bp = Blueprint("overlay", __name__)

OVERLAY_TYPES = ["DEMOGRAPHIC_OVERWRITE", "CLINICAL_MISFILE"]


def _overlay_or_404(overlay_id):
    row = store.overlays.get(overlay_id)
    if row is None:
        raise err("ERR_OVERLAY_NOT_FOUND", "No overlay correction with id %s" % overlay_id)
    return row


def _remediation_or_404(remediation_id):
    row = store.remediations.get(remediation_id)
    if row is None:
        raise err("ERR_REMEDIATION_NOT_FOUND",
                  "No contamination remediation with id %s" % remediation_id)
    return row


# --------------------------------------------------------------------------
# Overlay corrections
# --------------------------------------------------------------------------
@bp.post("/mpi/overlay-corrections")
def create_overlay():
    authenticate(["IdentityAnalyst", "IdentityStewardApprover"])
    body = get_body()
    record_id = field_id(body, "record_id", required=True)
    overlay_type = field_enum(body, "overlay_type", OVERLAY_TYPES, required=True)
    snapshot = field_map(body, "corrected_field_snapshot",
                        allowed_keys=OVERLAY_SNAPSHOT_KEYS, required=True)
    element_count = field_int(body, "affected_clinical_element_count",
                             required=True, minimum=0)
    from_date = field_date(body, "encounter_from_date", required=True)
    to_date = field_date(body, "encounter_to_date", required=True)
    if to_date < from_date:
        raise bad_request("encounter_to_date must not be earlier than encounter_from_date")
    expected = field_int(body, "expected_record_version", required=True)

    record = store.records.get(record_id)                                # rank 8
    if record is None:
        raise err("ERR_RECORD_NOT_FOUND", "No patient record with id %s" % record_id)
    if expected != record["version"]:                                    # rank 20
        raise err("ERR_STALE_RECORD_VERSION",
                  "expected_record_version %s does not match the record's current version %s"
                  % (expected, record["version"]))
    if domain.under_fraud_hold(record):                                  # rank 21
        raise err("ERR_RECORD_UNDER_FRAUD_HOLD",
                  "Patient record %s is under a fraud hold" % record_id)
    if record["identity_state"] != "ACTIVE":                             # rank 25
        raise err("ERR_RECORD_NOT_ACTIVE", "Patient record %s is not ACTIVE" % record_id)

    prior = {key: record.get(key) for key in snapshot.keys()}
    row = base_entity()
    row.update({
        "record_id": record_id,
        "overlay_type": overlay_type,
        "corrected_field_snapshot": dict(snapshot),
        "prior_field_snapshot": prior,
        "affected_clinical_element_count": element_count,
        "encounter_from_date": from_date,
        "encounter_to_date": to_date,
        "state": "DETECTED",
        "created_by_user_id": g.user_id,
        "closure_note": None,
    })
    store.overlays[row["id"]] = row
    domain.reconcile_integrity(record)
    return created(serializers.overlay(row))


@bp.get("/mpi/overlay-corrections/<overlay_id>")
def get_overlay(overlay_id):
    authenticate(ALL_ROLES)
    return ok(serializers.overlay(_overlay_or_404(overlay_id)))


@bp.get("/mpi/overlay-corrections")
def list_overlays():
    authenticate(ALL_ROLES)
    rows = sorted(store.overlays.values(), key=lambda o: (o["created_at"], o["_seq"]))
    for key in ("record_id", "state", "overlay_type"):
        rows = query_filter(rows, key)
    window, page = paginate(rows)
    return ok_list([serializers.overlay(o) for o in window], page)


@bp.post("/mpi/overlay-corrections/<overlay_id>/apply")
def apply_overlay(overlay_id):
    authenticate(["IdentityStewardApprover"])
    get_body()
    overlay = _overlay_or_404(overlay_id)                                # rank 11
    record = store.records.get(overlay["record_id"])
    if record is not None and domain.under_fraud_hold(record):           # rank 21
        raise err("ERR_RECORD_UNDER_FRAUD_HOLD",
                  "Patient record %s is under a fraud hold" % record["id"])
    if overlay["state"] != "DETECTED":                                   # rank 28
        raise err("ERR_OVERLAY_INVALID_STATE",
                  "Overlay correction %s is in state %s" % (overlay_id, overlay["state"]))

    overlay["state"] = "UNDER_CORRECTION"
    touch(overlay)

    if record is not None:
        for key, value in overlay["corrected_field_snapshot"].items():
            record[key] = value
        touch(record)

    domain.fan_out("OVERLAY_CORRECTION", overlay_correction_id=overlay_id)

    if overlay["affected_clinical_element_count"] > CONTAMINATION_REVIEW_ELEMENT_THRESHOLD:
        remediation = base_entity()
        remediation.update({
            "source_type": "OVERLAY",
            "merge_operation_id": None,
            "overlay_correction_id": overlay_id,
            "record_id": overlay["record_id"],
            "element_count_subject": overlay["affected_clinical_element_count"],
            "element_count_quarantined": 0,
            "element_count_reassigned": 0,
            "reassigned_to_record_mrn": None,
            "state": "OPEN",
            "closure_note": None,
        })
        store.remediations[remediation["id"]] = remediation

    return ok(serializers.overlay(overlay))


@bp.post("/mpi/overlay-corrections/<overlay_id>/complete")
def complete_overlay(overlay_id):
    authenticate(["IdentityStewardApprover"])
    body = get_body()
    closure_note = field_string(body, "closure_note", required=True)
    overlay = _overlay_or_404(overlay_id)                                # rank 11
    if overlay["state"] != "UNDER_CORRECTION":                           # rank 28
        raise err("ERR_OVERLAY_INVALID_STATE",
                  "Overlay correction %s is in state %s" % (overlay_id, overlay["state"]))
    live = [
        r for r in store.remediations.values()
        if r.get("overlay_correction_id") == overlay_id
        and r["state"] in ("OPEN", "QUARANTINED", "REASSIGNED")
    ]
    if live:
        raise err("ERR_OVERLAY_INVALID_STATE",
                  "A contamination remediation belonging to this correction is still live")

    overlay["state"] = "CORRECTED"
    overlay["closure_note"] = closure_note
    touch(overlay)
    record = store.records.get(overlay["record_id"])
    if record is not None:
        domain.reconcile_integrity(record)
    return ok(serializers.overlay(overlay))


# --------------------------------------------------------------------------
# Contamination remediations
# --------------------------------------------------------------------------
@bp.get("/mpi/contamination-remediations/<remediation_id>")
def get_remediation(remediation_id):
    authenticate(ALL_ROLES)
    return ok(serializers.remediation(_remediation_or_404(remediation_id)))


@bp.get("/mpi/contamination-remediations")
def list_remediations():
    authenticate(ALL_ROLES)
    rows = sorted(store.remediations.values(), key=lambda r: (r["created_at"], r["_seq"]))
    for key in ("merge_operation_id", "overlay_correction_id", "record_id", "state"):
        rows = query_filter(rows, key)
    window, page = paginate(rows)
    return ok_list([serializers.remediation(r) for r in window], page)


@bp.post("/mpi/contamination-remediations/<remediation_id>/quarantine")
def quarantine_remediation(remediation_id):
    authenticate(["IdentityAnalyst", "PrivacyOfficer"])
    body = get_body()
    count = field_int(body, "element_count_quarantined", required=True, minimum=0)
    remediation = _remediation_or_404(remediation_id)                    # rank 12
    if remediation["state"] != "OPEN":                                   # rank 29
        raise err("ERR_REMEDIATION_INVALID_STATE",
                  "Remediation %s is in state %s" % (remediation_id, remediation["state"]))
    if count > remediation["element_count_subject"]:                     # rank 47
        raise err("ERR_REMEDIATION_COUNT_INVALID",
                  "element_count_quarantined may not exceed element_count_subject")
    remediation["element_count_quarantined"] = count
    remediation["state"] = "QUARANTINED"
    touch(remediation)
    return ok(serializers.remediation(remediation))


@bp.post("/mpi/contamination-remediations/<remediation_id>/reassign")
def reassign_remediation(remediation_id):
    authenticate(["PrivacyOfficer"])
    body = get_body()
    target_id = field_id(body, "target_record_id", required=True)
    count = field_int(body, "element_count_reassigned", required=True, minimum=0)

    target = store.records.get(target_id)                                # rank 8
    if target is None:
        raise err("ERR_RECORD_NOT_FOUND", "No patient record with id %s" % target_id)
    remediation = _remediation_or_404(remediation_id)                    # rank 12
    if domain.under_fraud_hold(target):                                  # rank 21
        raise err("ERR_RECORD_UNDER_FRAUD_HOLD",
                  "Patient record %s is under a fraud hold" % target_id)
    if target["identity_state"] != "ACTIVE":                             # rank 25
        raise err("ERR_RECORD_NOT_ACTIVE", "Patient record %s is not ACTIVE" % target_id)
    if remediation["state"] != "QUARANTINED":                            # rank 29
        raise err("ERR_REMEDIATION_INVALID_STATE",
                  "Remediation %s is in state %s" % (remediation_id, remediation["state"]))
    subject = store.records.get(remediation["record_id"])
    if subject is not None and target["enterprise_id"] == subject["enterprise_id"]:  # rank 38
        raise err("ERR_REASSIGN_TARGET_INVALID",
                  "The target record belongs to the same enterprise identity cluster")
    if count > remediation["element_count_quarantined"]:                  # rank 47
        raise err("ERR_REMEDIATION_COUNT_INVALID",
                  "element_count_reassigned may not exceed element_count_quarantined")

    remediation["element_count_reassigned"] = count
    remediation["reassigned_to_record_mrn"] = target["mrn"]
    remediation["state"] = "REASSIGNED"
    touch(remediation)

    target["clinical_element_count"] = target["clinical_element_count"] + count
    touch(target)
    if subject is not None:
        subject["clinical_element_count"] = subject["clinical_element_count"] - count
        touch(subject)
    return ok(serializers.remediation(remediation))


@bp.post("/mpi/contamination-remediations/<remediation_id>/close")
def close_remediation(remediation_id):
    authenticate(["PrivacyOfficer"])
    body = get_body()
    closure_note = field_string(body, "closure_note", required=True)
    remediation = _remediation_or_404(remediation_id)                    # rank 12
    if remediation["state"] not in ("QUARANTINED", "REASSIGNED"):        # rank 29
        raise err("ERR_REMEDIATION_INVALID_STATE",
                  "Remediation %s is in state %s" % (remediation_id, remediation["state"]))
    remediation["state"] = "CLOSED"
    remediation["closure_note"] = closure_note
    touch(remediation)
    record = store.records.get(remediation["record_id"])
    if record is not None:
        domain.reconcile_integrity(record)
    return ok(serializers.remediation(remediation))
