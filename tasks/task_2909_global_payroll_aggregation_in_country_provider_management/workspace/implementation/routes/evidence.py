"""The one manually recorded global control: the residency attestation."""
from flask import Blueprint, g

import serial
import services
import store
import validate as v
from auth import require
from common import (
    COMPLIANCE_AUDITOR,
    CONTROL_REFS,
    EVIDENCE_TYPES,
    ApiError,
)
from response import created

bp = Blueprint("evidence", __name__)

MANUAL_CONTROL = "CTRL_RESIDENCY_ATTESTATION"


@bp.post("/payroll/audit-evidence")
@require(COMPLIANCE_AUDITOR)
def create_audit_evidence():
    body = v.json_body()
    cycle_id = v.req_id(body, "cycle_id")
    control_ref = v.req_enum(body, "control_ref", CONTROL_REFS)
    evidence_type = v.req_enum(body, "evidence_type", EVIDENCE_TYPES)
    payload_hash = v.req_str(body, "payload_hash", 1, 80)

    cycle = store.get_cycle(cycle_id)
    if cycle["status"] in ("CLOSED", "CANCELLED"):
        raise ApiError(
            "ERR_CYCLE_INVALID_STATE",
            "Evidence may not be recorded against a closed or cancelled cycle.",
        )
    if control_ref != MANUAL_CONTROL:
        raise ApiError(
            "ERR_MANUAL_CONTROL_NOT_ALLOWED",
            "Only the residency attestation may be recorded by hand.",
        )
    for item in store.evidence_of_cycle(cycle["id"]):
        if item["control_ref"] == control_ref:
            raise ApiError(
                "ERR_DUPLICATE_EVIDENCE_CONTROL",
                "This control is already evidenced for the cycle.",
            )

    row = services.record_evidence(
        cycle["id"], control_ref, evidence_type, payload_hash, g.role, g.user_id
    )
    return created(serial.evidence(row))
