"""HostPatronizationRecord services: support-the-host receipts and verification."""

import random
import string

import calculations as calc
import errors
import recompute
import serializers
import store
import validation as v
from envelope import created_object, ok_array, ok_object

PURCHASE_KINDS = ("TASTING", "MERCHANDISE", "TICKET", "MEAL")
VERIFICATION_ACTIONS = ("VERIFY", "REJECT")
_CODE_ALPHABET = string.ascii_uppercase + string.digits


def load_record(record_id):
    record = store.get(store.RECORDS, record_id)
    if record is None:
        errors.fail("ERR_RESOURCE_NOT_FOUND", "No patronization record with that id.")
    return record


def _mint_code():
    return "VC-" + "".join(random.choice(_CODE_ALPHABET) for _ in range(12))


def create_record(actor, body):
    v.authorize(actor, ("HostOperator", "Member"))
    # priority 4: required payload members.
    v.require_fields(
        body,
        [
            "host_id",
            "member_id",
            "stay_request_id",
            "receipt_cents",
            "purchase_kind",
            "expected_request_version",
        ],
    )
    host_id = v.text_field(body, "host_id")
    member_id = v.text_field(body, "member_id")
    stay_request_id = v.text_field(body, "stay_request_id")
    receipt_cents = v.int_field(body, "receipt_cents", required=True)
    purchase_kind = v.enum_field(body, "purchase_kind", PURCHASE_KINDS, required=True)
    expected_request_version = v.int_field(body, "expected_request_version", required=True)
    if receipt_cents <= 0:
        errors.fail("ERR_INVALID_REQUEST", "receipt_cents must be positive.")

    # priority 2: the acting host operator owns the host; a member its own record.
    v.require_host_scope(actor, host_id)
    v.require_member_scope(actor, member_id)

    # priority 3: every referenced id resolves, outer first.
    host_row = store.get(store.HOSTS, host_id)
    if host_row is None:
        errors.fail("ERR_RESOURCE_NOT_FOUND", "No host business with that id.")
    if store.get(store.MEMBERS, member_id) is None:
        errors.fail("ERR_RESOURCE_NOT_FOUND", "No member with that id.")
    stay = store.get(store.STAYS, stay_request_id)
    if stay is None:
        errors.fail("ERR_RESOURCE_NOT_FOUND", "No stay request with that id.")
    # ...and the request must be addressed to that host and that member.
    if stay.get("host_id") != host_id:
        errors.fail("ERR_RESOURCE_NOT_FOUND", "That stay does not belong to this host.")
    if stay.get("member_id") != member_id:
        errors.fail("ERR_RESOURCE_NOT_FOUND", "That stay does not belong to this member.")

    # priority 25: the stay version precondition.
    if expected_request_version != stay.get("version"):
        errors.fail("ERR_STALE_REQUEST_VERSION")

    record = {
        "id": store.new_id(),
        "host_id": host_id,
        "member_id": member_id,
        "stay_request_id": stay_request_id,
        "receipt_cents": receipt_cents,
        "purchase_kind": purchase_kind,
        "verification_code": _mint_code(),
        "verification_status": "PENDING",
        "host_credit_cents": 0,
    }
    record.update(store.create_common())
    store.add(store.RECORDS, record)
    # Recording the purchase advances the stay's version by one.
    store.stamp(stay)
    return created_object(serializers.record_row(record))


def list_records(actor):
    v.authorize(actor, ("Member", "HostOperator", "PlatformAdmin"))
    limit, offset = v.pagination()
    keys = ("host_id", "member_id", "stay_request_id", "verification_status")
    filters = {key: v.query(key) for key in keys}
    rows = []
    for record in store.all_of(store.RECORDS):
        if any(
            filters[key] is not None and record.get(key) != filters[key] for key in keys
        ):
            continue
        rows.append(serializers.record_row(record))
    window, total = v.page(rows, limit, offset)
    return ok_array(window, limit, offset, total)


def get_record(actor, record_id):
    v.authorize(actor, ("Member", "HostOperator", "PlatformAdmin"))
    record = load_record(record_id)
    return ok_object(serializers.record_row(record))


def verify_record(actor, record_id, body):
    v.authorize(actor, ("HostOperator", "PlatformAdmin"))
    record = load_record(record_id)
    v.require_fields(body, ["action"])
    action = v.enum_field(body, "action", VERIFICATION_ACTIONS, required=True)
    code = v.text_field(body, "verification_code")

    v.require_host_scope(actor, record.get("host_id"))

    # priority 7: the record must still be PENDING.
    if record.get("verification_status") != "PENDING":
        errors.fail("ERR_INVALID_STATE")

    if action == "REJECT":
        record["verification_status"] = "REJECTED"
        record["host_credit_cents"] = 0
        store.stamp(record)
        return ok_object(serializers.record_row(record))

    # priority 4: the code is a required member of a VERIFY request.
    if code is None:
        errors.fail("ERR_INVALID_REQUEST", "Missing required field: verification_code.")
    if code != record.get("verification_code"):
        errors.fail("ERR_PATRONIZATION_CODE_INVALID")

    record["verification_status"] = "VERIFIED"
    record["host_credit_cents"] = calc.host_patronization_credit_cents(
        record.get("receipt_cents")
    )
    store.stamp(record)
    host = store.get(store.HOSTS, record.get("host_id"))
    if host is not None:
        host["patronization_credit_cents"] = recompute.patronization_credit_cents(host["id"])
        store.stamp(host)
    return ok_object(serializers.record_row(record))