"""Development document endpoints (PRD 3.5)."""
from flask import Blueprint

import cascades
import serialize
from calc import DOC_REVISION_LIMIT
from envelope import success
from errors import ApiError
from guards import (ROLE_MENTOR, ROLE_OFFICER, ROLE_POSTDOC, authenticate, json_body,
                    lookup, need_enum, need_string, opt_bool, opt_string)
from store import store, touch

bp = Blueprint("documents", __name__)

REVIEW_DECISIONS = ("APPROVE", "RETURN")
SUBMITTABLE_APPOINTMENT_STATUSES = ("OFFER_ISSUED", "OFFER_ACCEPTED", "ACTIVE")


@bp.post("/development-documents/<record_id>/submit")
def submit_document(record_id):
    user_id, _ = authenticate((ROLE_MENTOR,))
    document = lookup("development_document", record_id)
    appointment = store.appointments.get(document["appointment_id"])
    # rule 4: ownership against the governing appointment's mentor.
    if appointment is None or user_id != appointment["mentor_id"]:
        raise ApiError("ERR_NOT_RESOURCE_OWNER",
                       "Only the appointment's mentor may submit this document.")
    body = json_body()
    content_summary = need_string(body, "content_summary")
    acknowledged = None
    if "postdoc_acknowledged" in body and body.get("postdoc_acknowledged") is not None:
        acknowledged = opt_bool(body, "postdoc_acknowledged", False)
    # rule 6: state precondition on the document and on the appointment.
    if document["status"] not in ("DRAFT", "RETURNED_FOR_REVISION"):
        raise ApiError("ERR_INVALID_STATE_TRANSITION",
                       "A document in %s may not be submitted." % document["status"])
    if appointment["appointment_status"] not in SUBMITTABLE_APPOINTMENT_STATUSES:
        raise ApiError("ERR_INVALID_STATE_TRANSITION",
                       "The appointment is not in a state that accepts a submission.")
    # rule 19: revision rounds bound the re-submission loop too.
    if document["status"] == "RETURNED_FOR_REVISION" \
            and document["revision_round"] >= DOC_REVISION_LIMIT:
        raise ApiError("ERR_REVISION_LIMIT_REACHED",
                       "The document has exhausted its revision rounds.")

    document["content_summary"] = content_summary
    if acknowledged is not None:
        document["postdoc_acknowledged"] = acknowledged
    document["submitted_by_user_id"] = user_id
    document["status"] = "SUBMITTED"
    touch(document)
    return success(serialize.development_document_out(document))


@bp.post("/development-documents/<record_id>/acknowledge")
def acknowledge_document(record_id):
    authenticate((ROLE_POSTDOC,))
    document = lookup("development_document", record_id)
    json_body()
    document["postdoc_acknowledged"] = True
    touch(document)
    return success(serialize.development_document_out(document))


@bp.post("/development-documents/<record_id>/review")
def review_document(record_id):
    authenticate((ROLE_OFFICER,))
    document = lookup("development_document", record_id)
    body = json_body()
    decision = need_enum(body, "decision", REVIEW_DECISIONS)
    opt_string(body, "reviewer_note")
    if document["status"] != "SUBMITTED":
        raise ApiError("ERR_INVALID_STATE_TRANSITION",
                       "A document in %s may not be reviewed." % document["status"])
    if decision == "RETURN":
        # rule 19: document revision rounds.
        if document["revision_round"] >= DOC_REVISION_LIMIT:
            raise ApiError("ERR_REVISION_LIMIT_REACHED",
                           "The document has exhausted its revision rounds.")
        document["revision_round"] = document["revision_round"] + 1
        document["status"] = "RETURNED_FOR_REVISION"
        touch(document)
        return success(serialize.development_document_out(document))

    # rule 21: the scholar's co-signature gates IDP approval only.
    if document["doc_type"] == "IDP" and not document["postdoc_acknowledged"]:
        raise ApiError("ERR_IDP_NOT_ACKNOWLEDGED",
                       "An IDP may only be approved once the scholar has acknowledged it.")
    document["status"] = "APPROVED"
    document["approved_at"] = store.now()
    touch(document)
    return success(serialize.development_document_out(document))
