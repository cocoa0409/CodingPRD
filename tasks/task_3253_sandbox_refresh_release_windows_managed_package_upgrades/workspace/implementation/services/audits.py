"""Layered-access audits (PRD §2.10, §3.7).

An audit opens in OPEN with its overreach_count and grade already computed, and
closes with a REVOKE or RETAIN finding.  A REVOKE close sets revoked = true on
every in-scope assignment judged to overreach, permanently removing those layers
from every subsequent computation.
"""

import clock
import db
from errors import ERR_INVALID_STATE, fail
from services import common, permissions


def create_audit(actor, b):
    from validate import optional_list, require_string

    environment_id = require_string(b, "environment_id")
    env = common.get_environment(environment_id)
    scope_ids = optional_list(b, "reviewed_assignment_ids", default=[])

    # Existence: every reviewed id must belong to the audited environment.
    common.require_assignment_trace(env["id"], scope_ids)

    audit = db.create(
        db.access_audits,
        {
            "environment_id": env["id"],
            "reviewed_assignment_ids": list(scope_ids),
            "status": "OPEN",
            "grade": "PASS",
            "overreach_count": 0,
            "finding": None,
            "findings": [],
            "closed_at": None,
        },
    )
    recompute_audit(audit)
    return audit


def recompute_audit(audit):
    scope_ids = audit.get("reviewed_assignment_ids", [])
    audit["overreach_count"] = permissions.audit_overreach_count(
        audit["environment_id"], scope_ids
    )
    audit["grade"] = permissions.audit_grade(audit["overreach_count"])
    return audit


def close_audit(actor, audit_id, b):
    from validate import require_enum

    audit = common.get_access_audit(audit_id)

    if audit["status"] != "OPEN":
        fail(ERR_INVALID_STATE, "The access audit is not OPEN.")

    finding = require_enum(b, "finding", ("REVOKE", "RETAIN"))
    recompute_audit(audit)

    audit["finding"] = finding
    audit["status"] = "CLOSED"
    audit["closed_at"] = clock.default_iso()
    audit["findings"] = permissions.assignment_entries(
        audit["environment_id"], audit.get("reviewed_assignment_ids", [])
    )

    if finding == "REVOKE":
        # PRD §3.7: REVOKE sets revoked = true on every in-scope assignment
        # judged to overreach.  The overreach judgement is made once over the
        # operator's whole layer set (three accumulated layers), so every
        # in-scope grant of an overreaching operator is flipped — not only the
        # grant that happens to sit on the threshold.
        overreaching = {
            assignment["user_id"]
            for assignment_id in audit.get("reviewed_assignment_ids", [])
            for assignment in [db.permission_assignments.get(assignment_id)]
            if assignment is not None
            and permissions.overreaches(audit["environment_id"], assignment["user_id"])
        }
        for assignment_id in audit.get("reviewed_assignment_ids", []):
            assignment = db.permission_assignments.get(assignment_id)
            if assignment is None:
                continue
            if assignment["user_id"] in overreaching:
                assignment["revoked"] = True
                db.touch(assignment)

    env = db.environments.get(audit["environment_id"])
    if env is not None:
        from services import environments as environment_service

        # A REVOKE close removes those layers from every subsequent layer
        # computation, so the environment's rolled-up posture is recomputed
        # (PRD §3.7).
        environment_service.payment_layer_total(env)

    db.touch(audit)
    return audit