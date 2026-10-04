"""Envelope routes: assembly, lifecycle, fees and the audit certificate."""

from flask import Blueprint, request

from db import db, now_clock
from errors import (
    ApiError,
    ERR_ENVELOPE_NOT_FOUND,
    ERR_INVALID_ENVELOPE_STATE,
    ERR_INVALID_REQUEST,
    ERR_SOD_VIOLATION,
)
from middleware import authenticate, owned_by_account, ROLE_ACCOUNT, ROLE_PLATFORM_ADMIN
from response import ok, ok_array, paginate, read_pagination
from services.calculations import (
    audit_certificate_view,
    envelope_fee_quote,
    envelope_page_fee,
    total_pages,
)
from services.common import serialize, serialize_list
from services.envelope import (
    add_document,
    add_field,
    add_recipient,
    build_envelope,
    feed_envelope,
    load_envelope,
    send_envelope,
)
from services.lifecycle import (
    expire_cascade,
    guard_envelope_from_set,
    guard_envelope_terminal,
    guard_expected_version,
    guard_not_frozen,
    void_cascade,
)
from services.signing import (
    complete_envelope,
    purge_envelope,
    segregation_of_duties_violation,
    send_reminders,
    set_legal_hold,
)
from timeutil import parse_iso

bp = Blueprint("envelopes", __name__)


@bp.route("/esign/envelopes", methods=["POST"])
def post_envelope():
    actor = authenticate([ROLE_ACCOUNT])
    body = request.get_json(silent=True) or {}
    owned_by_account(actor, body.get("sender_account_id"))
    envelope = build_envelope(body)
    return ok(serialize(envelope), 201)


@bp.route("/esign/envelopes", methods=["GET"])
def list_envelopes():
    authenticate([ROLE_ACCOUNT, ROLE_PLATFORM_ADMIN])
    limit, offset = read_pagination(request.args)
    sender_account_id = request.args.get("sender_account_id")
    retention_policy_id = request.args.get("retention_policy_id")
    status = request.args.get("status")
    envelopes = list(db.envelopes.values())
    if sender_account_id:
        envelopes = [
            e for e in envelopes if e["sender_account_id"] == sender_account_id
        ]
    if retention_policy_id:
        envelopes = [
            e
            for e in envelopes
            if e["retention_policy_id"] == retention_policy_id
        ]
    if status:
        envelopes = [e for e in envelopes if e["status"] == status]
    envelopes.sort(key=lambda e: e.get("_ord", 0))
    window, limit, offset, total = paginate(envelopes, limit, offset)
    return ok_array(serialize_list(window), limit, offset, total, 200)


@bp.route("/esign/envelopes/<envelope_id>", methods=["GET"])
def get_envelope(envelope_id):
    actor = authenticate([ROLE_ACCOUNT, ROLE_PLATFORM_ADMIN])
    envelope = load_envelope(envelope_id)
    owned_by_account(actor, envelope["sender_account_id"])
    return ok(serialize(envelope), 200)


@bp.route("/esign/envelopes/<envelope_id>/documents", methods=["POST"])
def post_document(envelope_id):
    actor = authenticate([ROLE_ACCOUNT])
    envelope = load_envelope(envelope_id)
    owned_by_account(actor, envelope["sender_account_id"])
    guard_envelope_terminal(envelope)
    guard_not_frozen(envelope)
    guard_envelope_from_set(envelope, ("CREATED",))
    body = request.get_json(silent=True) or {}
    document = add_document(envelope, body)
    return ok(serialize(document), 201)


@bp.route("/esign/envelopes/<envelope_id>/documents", methods=["GET"])
def list_documents(envelope_id):
    actor = authenticate([ROLE_ACCOUNT, ROLE_PLATFORM_ADMIN])
    envelope = load_envelope(envelope_id)
    owned_by_account(actor, envelope["sender_account_id"])
    documents = db.documents_of(envelope_id)
    documents.sort(key=lambda d: d.get("_ord", 0))
    limit, offset = read_pagination(request.args)
    window, limit, offset, total = paginate(documents, limit, offset)
    return ok_array(serialize_list(window), limit, offset, total, 200)


@bp.route("/esign/envelopes/<envelope_id>/recipients", methods=["POST"])
def post_recipient(envelope_id):
    actor = authenticate([ROLE_ACCOUNT])
    envelope = load_envelope(envelope_id)
    owned_by_account(actor, envelope["sender_account_id"])
    guard_envelope_terminal(envelope)
    guard_not_frozen(envelope)
    guard_envelope_from_set(envelope, ("CREATED",))
    body = request.get_json(silent=True) or {}
    recipient = add_recipient(envelope, body)
    return ok(serialize(recipient), 201)


@bp.route("/esign/envelopes/<envelope_id>/fields", methods=["POST"])
def post_field(envelope_id):
    actor = authenticate([ROLE_ACCOUNT])
    envelope = load_envelope(envelope_id)
    owned_by_account(actor, envelope["sender_account_id"])
    guard_envelope_terminal(envelope)
    guard_not_frozen(envelope)
    guard_envelope_from_set(envelope, ("CREATED",))
    body = request.get_json(silent=True) or {}
    field = add_field(envelope, body)
    return ok(serialize(field), 201)


@bp.route("/esign/envelopes/<envelope_id>/send", methods=["POST"])
def post_send(envelope_id):
    actor = authenticate([ROLE_ACCOUNT])
    envelope = load_envelope(envelope_id)
    owned_by_account(actor, envelope["sender_account_id"])
    envelope = send_envelope(envelope)
    return ok(serialize(envelope), 200)


@bp.route("/esign/envelopes/<envelope_id>/feed", methods=["POST"])
def post_feed(envelope_id):
    actor = authenticate([ROLE_ACCOUNT, ROLE_PLATFORM_ADMIN])
    envelope = load_envelope(envelope_id)
    owned_by_account(actor, envelope["sender_account_id"])
    body = request.get_json(silent=True) or {}
    feed_event = body.get("feed_event")
    if feed_event is None:
        raise ApiError(
            ERR_INVALID_REQUEST[0], "required field 'feed_event' is missing",
            ERR_INVALID_REQUEST[1],
        )
    envelope = feed_envelope(envelope, feed_event)
    return ok(serialize(envelope), 200)


@bp.route("/esign/envelopes/<envelope_id>/void", methods=["POST"])
def post_void(envelope_id):
    actor = authenticate([ROLE_ACCOUNT])
    envelope = load_envelope(envelope_id)
    owned_by_account(actor, envelope["sender_account_id"])
    body = request.get_json(silent=True) or {}

    guard_envelope_terminal(envelope)                      # 11
    guard_not_frozen(envelope)                             # 12
    guard_envelope_from_set(envelope, ("SENT", "DELIVERED"))  # 13
    guard_expected_version(envelope, body.get("expected_envelope_version"))  # 33

    envelope = void_cascade(
        envelope,
        body.get("void_reason"),
        refund_credit=bool(body.get("refund_credit", False)),
    )
    return ok(serialize(envelope), 200)


@bp.route("/esign/envelopes/<envelope_id>/complete", methods=["POST"])
def post_complete(envelope_id):
    actor = authenticate([ROLE_ACCOUNT])
    envelope = load_envelope(envelope_id)
    # priority 4 (segregation of duties) precedes the ownership gate, so a
    # sealing identity that also acted as a recipient of this envelope surfaces
    # ERR_SOD_VIOLATION rather than ERR_FORBIDDEN.
    if segregation_of_duties_violation(actor, envelope):
        raise ApiError(
            ERR_SOD_VIOLATION[0],
            "the sealing identity also acted as a recipient of this envelope",
            ERR_SOD_VIOLATION[1],
        )
    owned_by_account(actor, envelope["sender_account_id"])
    body = request.get_json(silent=True) or {}
    envelope = complete_envelope(
        envelope, actor, body.get("expected_envelope_version")
    )
    return ok(serialize(envelope), 200)


@bp.route("/esign/envelopes/<envelope_id>/expire", methods=["POST"])
def post_expire(envelope_id):
    actor = authenticate([ROLE_ACCOUNT, ROLE_PLATFORM_ADMIN])
    envelope = load_envelope(envelope_id)
    owned_by_account(actor, envelope["sender_account_id"])
    body = request.get_json(silent=True) or {}

    guard_envelope_terminal(envelope)                          # 11
    guard_not_frozen(envelope)                                 # 12
    guard_envelope_from_set(envelope, ("SENT", "DELIVERED"))   # 13
    expires_at = parse_iso(envelope.get("expires_at"))
    if expires_at is None or now_clock() < expires_at:
        raise ApiError(
            ERR_INVALID_ENVELOPE_STATE[0],
            "the logical clock has not reached the envelope's expires_at",
            ERR_INVALID_ENVELOPE_STATE[1],
        )
    guard_expected_version(envelope, body.get("expected_envelope_version"))  # 33

    envelope = expire_cascade(envelope)
    return ok(serialize(envelope), 200)


@bp.route("/esign/envelopes/<envelope_id>/purge", methods=["POST"])
def post_purge(envelope_id):
    authenticate([ROLE_PLATFORM_ADMIN])
    envelope = load_envelope(envelope_id)
    body = request.get_json(silent=True) or {}
    envelope = purge_envelope(envelope, body.get("expected_envelope_version"))
    return ok(serialize(envelope), 200)


@bp.route("/esign/envelopes/<envelope_id>/legal-hold", methods=["POST"])
def post_legal_hold(envelope_id):
    authenticate([ROLE_PLATFORM_ADMIN])
    envelope = load_envelope(envelope_id)
    body = request.get_json(silent=True) or {}
    if "legal_hold" not in body or body["legal_hold"] is None:
        raise ApiError(
            ERR_INVALID_REQUEST[0], "required field 'legal_hold' is missing",
            ERR_INVALID_REQUEST[1],
        )
    envelope = set_legal_hold(
        envelope, bool(body["legal_hold"]), body.get("hold_until")
    )
    return ok(serialize(envelope), 200)


@bp.route("/esign/envelopes/<envelope_id>/reminders", methods=["POST"])
def post_reminders(envelope_id):
    actor = authenticate([ROLE_ACCOUNT])
    envelope = load_envelope(envelope_id)
    owned_by_account(actor, envelope["sender_account_id"])
    envelope = send_reminders(envelope)
    return ok(serialize(envelope), 200)


@bp.route("/esign/envelopes/<envelope_id>/quote", methods=["GET"])
def get_quote(envelope_id):
    actor = authenticate([ROLE_ACCOUNT])
    envelope = load_envelope(envelope_id)
    owned_by_account(actor, envelope["sender_account_id"])
    return ok(envelope_fee_quote(envelope), 200)


@bp.route("/esign/envelopes/<envelope_id>/fee-breakdown", methods=["GET"])
def get_fee_breakdown(envelope_id):
    actor = authenticate([ROLE_ACCOUNT])
    envelope = load_envelope(envelope_id)
    owned_by_account(actor, envelope["sender_account_id"])
    fee, rows = envelope_page_fee(envelope)
    return ok(
        {
            "per_document_fee": rows,
            "total_page_fee": float(fee),
            "total_pages": total_pages(envelope_id),
        },
        200,
    )


@bp.route("/esign/envelopes/<envelope_id>/audit-certificate", methods=["GET"])
def get_audit_certificate(envelope_id):
    actor = authenticate([ROLE_ACCOUNT, ROLE_PLATFORM_ADMIN])
    envelope = load_envelope(envelope_id)
    owned_by_account(actor, envelope["sender_account_id"])
    payload, tampered = audit_certificate_view(envelope)
    if tampered:
        raise ApiError(
            ERR_INVALID_ENVELOPE_STATE[0],
            "the stored audit event chain disagrees with its recomputation",
            ERR_INVALID_ENVELOPE_STATE[1],
        )
    return ok(payload, 200)