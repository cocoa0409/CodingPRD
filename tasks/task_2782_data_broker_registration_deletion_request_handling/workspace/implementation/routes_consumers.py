"""Consumer records, the collection dimension and the consent dimension
(PRD 3.3)."""
from flask import Blueprint

import audit
import guards
import lookups
from core import bad, db, fail, make, now, ok_list, ok_record, ordered, touch
from guards import (ROLE_BROKER_ADMIN, ROLE_CONSUMER, ROLE_INTAKE_AGENT,
                    ROLE_PLATFORM_ADMIN, ROLE_REGULATOR, authenticate, body,
                    filter_value, get_enum, get_int, get_state_code, get_str,
                    get_str_list, pagination, require_owner)

bp = Blueprint("consumers", __name__)

MAX_DERIVED_PROFILES = 50


@bp.post("/consumers")
def create_consumer():
    caller = authenticate([ROLE_BROKER_ADMIN, ROLE_INTAKE_AGENT])
    data = body()
    broker_id = data.get("broker_id")
    if isinstance(broker_id, str) and broker_id:
        require_owner(caller, broker_id=broker_id)
        broker = lookups.broker_or_404(broker_id)
    else:
        broker = None
    if broker is None:
        bad("broker_id is required")

    identity_hash = get_str(data, "identity_hash", 8, 128)
    state_code = get_state_code(data, "state_code")
    source_label = get_str(data, "source_label", 1, 80)
    sensitive = get_str_list(data, "sensitive_categories",
                             allowed=guards.SENSITIVE_CATEGORY_VALUES,
                             required=False, default=[])
    derived = get_int(data, "derived_profile_count", 0, MAX_DERIVED_PROFILES,
                      required=False, default=0)

    same_hash = ordered([c for c in db.consumers.values()
                         if c["broker_id"] == broker["id"]
                         and c["identity_hash"] == identity_hash])
    for existing in same_hash:
        if existing["collection_status"] != "PURGED":
            fail("ERR_IDENTITY_HASH_DUPLICATE",
                 "identity_hash is already recorded for this broker")
    # PRD 3.7: a purged consumer's hash may be re-used only when no active
    # suppression entry blocks re-collection for the submitted source.
    for existing in same_hash:
        entry = lookups.blocking_suppression(existing["id"], source_label)
        if entry is not None:
            lookups.record_recollection_block(entry, broker, existing["id"],
                                              audit.actor_direct(caller))

    consumer = make(
        "Consumer",
        broker_id=broker["id"],
        identity_hash=identity_hash,
        state_code=state_code,
        sensitive_categories=sensitive,
        derived_profile_count=derived,
        source_label=source_label,
        collection_status="ACTIVE",
        consent_status="CONSENT_PENDING" if sensitive else "NOT_REQUIRED",
        collection_event_count=1,
        opt_out_sale=False,
        opt_out_sharing=False,
        last_purged_at=None,
    )
    db.consumers[consumer["id"]] = consumer
    audit.append(broker, "CONSUMER_RECORDED", "CONSUMER", consumer["id"],
                 audit.actor_direct(caller),
                 "consumer record created from source %s" % source_label)
    return ok_record(consumer, 201)


@bp.get("/consumers")
def list_consumers():
    authenticate([ROLE_BROKER_ADMIN, ROLE_PLATFORM_ADMIN, ROLE_REGULATOR,
                  ROLE_INTAKE_AGENT])
    limit, offset = pagination()
    broker_id = filter_value("broker_id")
    identity_hash = filter_value("identity_hash")
    collection_status = filter_value("collection_status",
                                     guards.COLLECTION_STATUSES)
    consent_status = filter_value("consent_status", guards.CONSENT_STATUSES)
    rows = ordered(list(db.consumers.values()))
    if broker_id is not None:
        rows = [r for r in rows if r["broker_id"] == broker_id]
    if identity_hash is not None:
        rows = [r for r in rows if r["identity_hash"] == identity_hash]
    if collection_status is not None:
        rows = [r for r in rows if r["collection_status"] == collection_status]
    if consent_status is not None:
        rows = [r for r in rows if r["consent_status"] == consent_status]
    return ok_list(rows, limit, offset)


@bp.get("/consumers/<consumer_id>")
def get_consumer(consumer_id):
    caller = authenticate([ROLE_BROKER_ADMIN, ROLE_PLATFORM_ADMIN,
                           ROLE_REGULATOR, ROLE_INTAKE_AGENT, ROLE_CONSUMER])
    require_owner(caller, consumer_id=consumer_id)
    consumer = lookups.consumer_or_404(consumer_id)
    require_owner(caller, broker_id=consumer["broker_id"])
    return ok_record(consumer)


@bp.post("/consumers/<consumer_id>/consent")
def change_consent(consumer_id):
    caller = authenticate([ROLE_BROKER_ADMIN, ROLE_CONSUMER])
    require_owner(caller, consumer_id=consumer_id)
    consumer = lookups.consumer_or_404(consumer_id)
    require_owner(caller, broker_id=consumer["broker_id"])
    broker = db.brokers[consumer["broker_id"]]
    data = body()
    action = get_enum(data, "action", guards.CONSENT_ACTIONS)

    current = consumer["consent_status"]
    if action == "REQUEST":
        if not consumer["sensitive_categories"]:
            fail("ERR_CONSENT_INVALID_TRANSITION",
                 "consent is only meaningful for a consumer carrying "
                 "sensitive categories")
        if current not in ("NOT_REQUIRED", "CONSENT_REVOKED"):
            fail("ERR_CONSENT_INVALID_TRANSITION",
                 "consent cannot be requested from %s" % current)
        target = "CONSENT_PENDING"
    elif action == "GRANT":
        if current != "CONSENT_PENDING":
            fail("ERR_CONSENT_INVALID_TRANSITION",
                 "consent cannot be granted from %s" % current)
        target = "CONSENT_GRANTED"
    else:
        if current != "CONSENT_GRANTED":
            fail("ERR_CONSENT_INVALID_TRANSITION",
                 "consent cannot be revoked from %s" % current)
        target = "CONSENT_REVOKED"

    consumer["consent_status"] = target
    touch(consumer)
    audit.append(broker, "CONSENT_CHANGED", "CONSUMER", consumer["id"],
                 audit.actor_direct(caller),
                 "consent status moved from %s to %s" % (current, target))
    return ok_record(consumer)


@bp.post("/consumers/<consumer_id>/collections")
def record_collection(consumer_id):
    caller = authenticate([ROLE_BROKER_ADMIN, ROLE_INTAKE_AGENT])
    consumer = lookups.consumer_or_404(consumer_id)
    require_owner(caller, broker_id=consumer["broker_id"])
    broker = db.brokers[consumer["broker_id"]]
    data = body()
    source_label = get_str(data, "source_label", 1, 80)
    derived = get_int(data, "derived_profile_count", 0, MAX_DERIVED_PROFILES,
                      required=False, default=None)

    entry = lookups.blocking_suppression(consumer["id"], source_label)
    if entry is not None:
        lookups.record_recollection_block(entry, broker, consumer["id"],
                                          audit.actor_direct(caller))
    if consumer["sensitive_categories"] and consumer["consent_status"] != "CONSENT_GRANTED":
        fail("ERR_SENSITIVE_CONSENT_REQUIRED",
             "a consumer carrying sensitive categories requires granted "
             "consent before a further collection is recorded")
    if lookups.accepted_registration_for(broker["id"],
                                         consumer["state_code"]) is None:
        fail("ERR_NO_ACCEPTED_REGISTRATION",
             "the broker holds no accepted filing covering %s at this instant"
             % consumer["state_code"])

    consumer["collection_event_count"] += 1
    consumer["source_label"] = source_label
    if derived is not None:
        consumer["derived_profile_count"] = derived
    if consumer["collection_status"] == "PURGED":
        consumer["collection_status"] = "REACQUIRED"
    touch(consumer)
    audit.append(broker, "CONSUMER_COLLECTION_RECORDED", "CONSUMER",
                 consumer["id"], audit.actor_direct(caller),
                 "collection event recorded from source %s" % source_label)
    return ok_record(consumer)
