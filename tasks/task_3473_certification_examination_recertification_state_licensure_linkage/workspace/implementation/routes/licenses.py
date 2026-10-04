"""State licensure (PRD §3.8): policy snapshot pinned at creation, NREMT /
STATE_EXAM path resolution, OCC on the certification, per-line fee rounding,
the MORE_INFO_REQUIRED cycle, and credential-mediated cascade denials."""

from datetime import datetime, time

from flask import Blueprint, request

from db import (STORE, base_entity, disciplinary_hold, now_dt, serialize,
                touch)
from envelope import ok_list, ok_object, list_page
from errors import raise_err
from middleware import (ALL_AUTHENTICATED_ROLES, authn, body, opt_bool,
                        opt_int, opt_str, req_enum, req_str)
from util import UTC, add_months, share_cents

bp = Blueprint("licenses", __name__)


@bp.post("/registry/license-applications")
def create_license_application():
    uid, _ = authn(["Candidate"])
    b = body()
    state_code = req_str(b, "state_code")
    level_id = req_str(b, "level_id")
    certification_id = opt_str(b, "certification_id", None)
    state_exam_record_id = opt_str(b, "state_exam_record_id", None)
    jurisprudence_completed = opt_bool(b, "jurisprudence_completed", False)
    expected_version = opt_int(b, "expected_certification_version", None)

    level = STORE.levels.get(level_id)
    if not level:
        raise_err("ERR_NOT_FOUND", "LevelDefinition %s does not exist" % level_id)
    policy = next((p for p in STORE.policies.values() if p["state_code"] == state_code), None)
    if not policy:
        raise_err("ERR_NOT_FOUND", "No StateAdoptionPolicy for state %s" % state_code)

    # Path resolution from the pinned adoption mode; a missing path-required
    # reference is a shape error. This shape check needs the resolved policy,
    # so it sits immediately after the policy's existence check and ahead of
    # the remaining (body-referenced) existence checks.
    mode = policy["adoption_mode"]
    if mode == "NREMT_ACCEPTED":
        path = "NREMT"
        if certification_id is None:
            raise_err("ERR_INVALID_REQUEST",
                      "certification_id is required for a NREMT_ACCEPTED state")
    elif mode == "STATE_EXAM":
        path = "STATE_EXAM"
        if state_exam_record_id is None:
            raise_err("ERR_INVALID_REQUEST",
                      "state_exam_record_id is required for a STATE_EXAM state")
    else:  # HYBRID — validate the national path first when a certification is cited
        if certification_id is not None:
            path = "NREMT"
        elif state_exam_record_id is not None:
            path = "STATE_EXAM"
        else:
            raise_err("ERR_INVALID_REQUEST",
                      "HYBRID states require certification_id or state_exam_record_id")

    candidate = STORE.candidates.get(uid)
    if not candidate:
        raise_err("ERR_NOT_FOUND", "Candidate %s does not exist" % uid)
    cert = None
    if certification_id is not None:
        cert = STORE.certifications.get(certification_id)
        if not cert:
            raise_err("ERR_NOT_FOUND", "Certification %s does not exist" % certification_id)
    ser = None
    if state_exam_record_id is not None:
        ser = STORE.state_exams.get(state_exam_record_id)
        if not ser:
            raise_err("ERR_NOT_FOUND", "StateExamRecord %s does not exist" % state_exam_record_id)

    if path == "NREMT":
        if expected_version is None:
            raise_err("ERR_INVALID_REQUEST",
                      "expected_certification_version is required on the NREMT path")
        if expected_version != cert["version"]:
            raise_err("ERR_STALE_VERSION",
                      "expected_certification_version %s does not match current version %s"
                      % (expected_version, cert["version"]))
        if cert["status"] != "ACTIVE":
            raise_err("ERR_CERTIFICATION_NOT_ACTIVE",
                      "Certification is %s, not ACTIVE" % cert["status"])

    if candidate["status"] == "BARRED":
        raise_err("ERR_PERMANENTLY_BARRED", "Candidate is BARRED")
    if disciplinary_hold(uid):
        raise_err("ERR_DISCIPLINARY_HOLD",
                  "Candidate is under a HOLD_NEW_APPLICATIONS interim action")

    if path == "NREMT":
        if cert["candidate_id"] != uid or cert["level_id"] != level_id:
            raise_err("ERR_CROSS_REFERENCE_MISMATCH",
                      "Certification belongs to a different candidate or level")
        accepted = policy.get("accepted_level_codes") or []
        if level["code"] not in accepted:
            raise_err("ERR_LEVEL_NOT_ACCEPTED_IN_STATE",
                      "Level %s is not accepted by %s on the national path"
                      % (level["code"], state_code))
    else:
        if (ser["candidate_id"] != uid or ser["state_code"] != state_code
                or ser["level_id"] != level_id):
            raise_err("ERR_CROSS_REFERENCE_MISMATCH",
                      "State exam record does not match the target state, level, and candidate")
        if not ser["passed"] or ser["status"] != "VALID":
            raise_err("ERR_STATE_EXAM_NOT_PASSING",
                      "State exam record is not passing or not VALID")
        exam_dt = datetime.combine(ser["exam_date"], time.min, tzinfo=UTC)
        if now_dt() > add_months(exam_dt, 24):
            raise_err("ERR_CREDENTIAL_STALE",
                      "The state examination is more than 24 months old")

    if policy["jurisprudence_exam_required"] and not jurisprudence_completed:
        raise_err("ERR_JURISPRUDENCE_REQUIRED",
                  "This state requires a jurisprudence exam attestation")

    e = base_entity()
    e.update({
        "candidate_id": uid,
        "state_code": state_code,
        "level_id": level_id,
        "policy_id": policy["id"],
        "adoption_mode_snapshot": policy["adoption_mode"],
        "registry_share_bps_snapshot": policy["registry_share_bps"],
        "fee_lines_snapshot": {
            "base_license_fee_cents": policy["base_license_fee_cents"],
            "national_verification_surcharge_cents": policy["national_verification_surcharge_cents"],
            "state_exam_fee_cents": policy["state_exam_fee_cents"],
        },
        "path": path,
        "certification_id": certification_id if path == "NREMT" else None,
        "certification_version_at_submission": cert["version"] if path == "NREMT" else None,
        "state_exam_record_id": state_exam_record_id if path == "STATE_EXAM" else None,
        "jurisprudence_completed": jurisprudence_completed,
        "assessed_fee_cents": None,
        "registry_share_cents": None,
        "status": "UNDER_REVIEW",
        "decision_reason": None,
        "more_info_note": None,
        "granted_on": None,
    })
    STORE.licenses[e["id"]] = e
    if path == "NREMT":
        # Creating the application pins and advances the certification version.
        touch(cert)
    return ok_object(serialize(e), 201)


@bp.get("/registry/license-applications")
def list_license_applications():
    authn(ALL_AUTHENTICATED_ROLES)
    filters = {
        "candidate_id": request.args.get("candidate_id"),
        "state_code": request.args.get("state_code"),
        "level_id": request.args.get("level_id"),
        "certification_id": request.args.get("certification_id"),
        "state_exam_record_id": request.args.get("state_exam_record_id"),
        "policy_id": request.args.get("policy_id"),
        "status": request.args.get("status"),
    }
    items = []
    for a in STORE.licenses.values():
        if any(v is not None and a.get(k) != v for k, v in filters.items()):
            continue
        items.append(a)
    page, total, limit, offset = list_page(items)
    return ok_list([serialize(a) for a in page], total, limit, offset)


@bp.get("/registry/license-applications/<lid>")
def get_license_application(lid):
    authn(ALL_AUTHENTICATED_ROLES)
    a = STORE.licenses.get(lid)
    if not a:
        raise_err("ERR_NOT_FOUND", "LicenseApplication %s does not exist" % lid)
    return ok_object(serialize(a), 200)


@bp.post("/registry/license-applications/<lid>/decision")
def decide_license_application(lid):
    authn(["StateOfficial"])
    b = body()
    outcome = req_enum(b, "outcome", ["GRANTED", "DENIED", "MORE_INFO_REQUIRED"])
    reason = opt_str(b, "reason", None)
    app = STORE.licenses.get(lid)
    if not app:
        raise_err("ERR_NOT_FOUND", "LicenseApplication %s does not exist" % lid)
    if app["status"] != "UNDER_REVIEW":
        raise_err("ERR_LICENSE_NOT_ACTIONABLE",
                  "License application is %s, not UNDER_REVIEW" % app["status"])

    if outcome == "DENIED":
        app["status"] = "DENIED"
        app["decision_reason"] = reason
        touch(app)
        return ok_object(serialize(app), 200)

    if outcome == "MORE_INFO_REQUIRED":
        app["status"] = "MORE_INFO_REQUIRED"
        app["more_info_note"] = reason
        touch(app)
        return ok_object(serialize(app), 200)

    # GRANTED
    if app["path"] == "NREMT":
        cert = STORE.certifications.get(app["certification_id"])
        if not cert or cert["status"] != "ACTIVE":
            raise_err("ERR_CERTIFICATION_NOT_ACTIVE",
                      "The cited certification must still be ACTIVE at grant time")
    lines = app["fee_lines_snapshot"]
    applicable = [lines["base_license_fee_cents"]]
    if app["path"] == "NREMT":
        applicable.append(lines["national_verification_surcharge_cents"])
    else:
        applicable.append(lines["state_exam_fee_cents"])
    app["assessed_fee_cents"] = sum(applicable)
    # Pinned rounding order: round EACH line first, then sum the rounded shares.
    app["registry_share_cents"] = sum(
        share_cents(line, app["registry_share_bps_snapshot"]) for line in applicable)
    app["granted_on"] = now_dt()
    app["status"] = "GRANTED"
    touch(app)
    return ok_object(serialize(app), 200)


@bp.post("/registry/license-applications/<lid>/respond")
def respond_license_application(lid):
    uid, _ = authn(["Candidate"])
    b = body()
    note = b.get("response_note")
    if note is not None and not isinstance(note, str):
        raise_err("ERR_INVALID_REQUEST", "Field 'response_note' must be a string")
    app = STORE.licenses.get(lid)
    if not app:
        raise_err("ERR_NOT_FOUND", "LicenseApplication %s does not exist" % lid)
    if app["candidate_id"] != uid:
        raise_err("ERR_FORBIDDEN_ROLE", "Only the owning candidate may respond")
    if app["status"] != "MORE_INFO_REQUIRED":
        raise_err("ERR_LICENSE_NOT_AWAITING_RESPONSE",
                  "License application is %s, not MORE_INFO_REQUIRED" % app["status"])
    app["status"] = "UNDER_REVIEW"
    touch(app)
    return ok_object(serialize(app), 200)
