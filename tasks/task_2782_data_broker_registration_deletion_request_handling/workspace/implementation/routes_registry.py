"""Broker onboarding and state registration filings (PRD 3.1, 3.2)."""
from decimal import Decimal

from flask import Blueprint

import audit
import guards
import lookups
import scoring
import standing
from core import (D, bad, db, fail, make, now, ok, ok_list, ok_record, ordered,
                  touch, whole_days)
from guards import (ROLE_BROKER_ADMIN, ROLE_PLATFORM_ADMIN, ROLE_REGULATOR,
                    authenticate, body, filter_value, get_bool, get_enum,
                    get_int, get_state_code, get_str, get_str_list, get_ts,
                    pagination, require_owner)

bp = Blueprint("registry", __name__)

MAX_OPERATING_STATES = 12
MIN_BUSINESS_DESCRIPTION = 60
FEE_DEPOSIT_MAX_CENTS = 10000000


def _payload_broker(data, caller, own=True):
    """Rule 4 then rule 5: ownership is compared against the supplied
    broker_id before the broker is resolved."""
    broker_id = data.get("broker_id")
    if not isinstance(broker_id, str) or not broker_id:
        return None
    if own:
        require_owner(caller, broker_id=broker_id)
    return lookups.broker_or_404(broker_id)


# ------------------------------------------------------------------ brokers
@bp.post("/brokers")
def create_broker():
    caller = authenticate([ROLE_PLATFORM_ADMIN])
    data = body()
    legal_name = get_str(data, "legal_name", 1, 160)
    email = get_str(data, "primary_contact_email", 5, 160)
    if "@" not in email:
        bad("primary_contact_email must contain @")
    home_state_code = get_state_code(data, "home_state_code")

    def _state(key, item):
        if len(item) != 2 or not item.isalpha() or item != item.upper():
            bad("%s entries must be exactly two uppercase letters" % key)

    operating = get_str_list(data, "operating_state_codes", minitems=1,
                             maxitems=MAX_OPERATING_STATES, distinct=True,
                             validator=_state)
    description = get_str(data, "business_description",
                          minlen=MIN_BUSINESS_DESCRIPTION)

    broker = make(
        "DataBroker",
        legal_name=legal_name,
        primary_contact_email=email,
        home_state_code=home_state_code,
        operating_state_codes=operating,
        business_description=description,
        registry_standing="DELINQUENT",
        delinquent_since=None,
        fee_deposited_cents=0,
        fee_paid_cents=0,
        fee_credit_cents=0,
        open_breach_count=0,
        request_intake_total=0,
        request_open_count=0,
        request_completed_count=0,
        request_terminated_count=0,
        audit_sequence_high_water=0,
    )
    # PRD 3.1: delinquent_since is the enrolment instant, which is created_at.
    broker["delinquent_since"] = broker["created_at"]
    db.brokers[broker["id"]] = broker
    audit.append(broker, "BROKER_REGISTERED", "BROKER", broker["id"],
                 audit.actor_direct(caller),
                 "broker enrolled in the state registry")
    return ok_record(broker, 201)


@bp.get("/brokers/<broker_id>")
def get_broker(broker_id):
    caller = authenticate([ROLE_BROKER_ADMIN, ROLE_PLATFORM_ADMIN,
                           ROLE_REGULATOR])
    require_owner(caller, broker_id=broker_id)
    return ok_record(lookups.broker_or_404(broker_id))


@bp.post("/brokers/<broker_id>/fee-deposits")
def create_fee_deposit(broker_id):
    caller = authenticate([ROLE_BROKER_ADMIN, ROLE_PLATFORM_ADMIN])
    require_owner(caller, broker_id=broker_id)
    broker = lookups.broker_or_404(broker_id)
    data = body()
    # Rule 15 covers the *_cents shape; rule 71 the positive-and-capped range.
    amount = get_int(data, "amount_cents", lo=0)
    if amount <= 0 or amount > FEE_DEPOSIT_MAX_CENTS:
        fail("ERR_FEE_DEPOSIT_INVALID",
             "amount_cents must be a positive integer no greater than %d"
             % FEE_DEPOSIT_MAX_CENTS)
    broker["fee_deposited_cents"] += amount
    broker["fee_credit_cents"] += amount
    touch(broker)
    audit.append(broker, "FEE_DEPOSITED", "BROKER", broker["id"],
                 audit.actor_direct(caller),
                 "fee deposit of %d cents recorded" % amount)
    return ok_record(broker)


@bp.get("/brokers/<broker_id>/audit-events")
def list_audit_events(broker_id):
    caller = authenticate([ROLE_BROKER_ADMIN, ROLE_REGULATOR,
                           ROLE_PLATFORM_ADMIN])
    require_owner(caller, broker_id=broker_id)
    lookups.broker_or_404(broker_id)
    limit, offset = pagination()
    event_type = filter_value("event_type", guards.EVENT_TYPES)
    subject_kind = filter_value("subject_kind", guards.SUBJECT_KINDS)
    subject_id = filter_value("subject_id")
    rows = audit.trail(broker_id)
    if event_type is not None:
        rows = [r for r in rows if r["event_type"] == event_type]
    if subject_kind is not None:
        rows = [r for r in rows if r["subject_kind"] == subject_kind]
    if subject_id is not None:
        rows = [r for r in rows if r["subject_id"] == subject_id]
    return ok_list(rows, limit, offset)


# ------------------------------------------------------------ registrations
@bp.post("/registrations")
def create_registration():
    caller = authenticate([ROLE_BROKER_ADMIN])
    data = body()
    broker = _payload_broker(data, caller)
    if broker is None:
        bad("broker_id is required")
    state_code = get_state_code(data, "state_code")
    if state_code not in (broker["operating_state_codes"] or []):
        bad("state_code must appear in the broker's operating_state_codes")
    start = get_ts(data, "coverage_period_start")
    end = get_ts(data, "coverage_period_end")
    description = get_str(data, "business_description",
                          minlen=MIN_BUSINESS_DESCRIPTION)
    expected = get_int(data, "expected_broker_version", lo=0)

    if expected != broker["version"]:
        fail("ERR_STALE_BROKER_VERSION",
             "expected_broker_version %s does not match %s"
             % (expected, broker["version"]))
    if lookups.overlapping_registration(broker["id"], state_code, start, end):
        fail("ERR_COVERAGE_PERIOD_OVERLAP",
             "another submitted or accepted filing covers this interval")
    if not start < end:
        fail("ERR_COVERAGE_PERIOD_INVALID",
             "coverage_period_start must be strictly before coverage_period_end")

    reg = make(
        "Registration",
        broker_id=broker["id"],
        state_code=state_code,
        status="DRAFT",
        coverage_period_start=start,
        coverage_period_end=end,
        coverage_days=whole_days(start, end),
        business_description=description,
        disclosure_completeness_score=D("0.00"),
        provisional_filing_fee_cents=0,
        final_filing_fee_cents=None,
        charged_fee_cents=0,
        submitted_at=None,
        accepted_at=None,
        rejection_reason_code=None,
        revision_count=0,
        superseded_registration_id=None,
    )
    db.registrations[reg["id"]] = reg
    touch(broker)
    audit.append(broker, "REGISTRATION_CREATED", "REGISTRATION", reg["id"],
                 audit.actor_direct(caller),
                 "state registration filing opened as a draft")

    # A pre-existing draft for the same broker and state is superseded rather
    # than blocked. No money moves because a draft has never been charged.
    for other in ordered([r for r in db.registrations.values()
                          if r["broker_id"] == broker["id"]
                          and r["state_code"] == state_code
                          and r["id"] != reg["id"]
                          and r["status"] == "DRAFT"]):
        other["status"] = "WITHDRAWN"
        touch(other)
        reg["superseded_registration_id"] = other["id"]
        audit.append(broker, "REGISTRATION_WITHDRAWN", "REGISTRATION",
                     other["id"], audit.actor_system(caller),
                     "draft filing withdrawn because a newer filing "
                     "superseded it")
    return ok_record(reg, 201)


@bp.get("/registrations")
def list_registrations():
    authenticate([ROLE_BROKER_ADMIN, ROLE_PLATFORM_ADMIN, ROLE_REGULATOR])
    limit, offset = pagination()
    broker_id = filter_value("broker_id")
    state_code = filter_value("state_code")
    status = filter_value("status", guards.REGISTRATION_STATUSES)
    superseded = filter_value("superseded_registration_id")
    rows = ordered(list(db.registrations.values()))
    if broker_id is not None:
        rows = [r for r in rows if r["broker_id"] == broker_id]
    if state_code is not None:
        rows = [r for r in rows if r["state_code"] == state_code]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    if superseded is not None:
        rows = [r for r in rows if r["superseded_registration_id"] == superseded]
    return ok_list(rows, limit, offset)


@bp.get("/registrations/<registration_id>")
def get_registration(registration_id):
    caller = authenticate([ROLE_BROKER_ADMIN, ROLE_PLATFORM_ADMIN,
                           ROLE_REGULATOR])
    reg = lookups.registration_or_404(registration_id)
    require_owner(caller, broker_id=reg["broker_id"])
    return ok_record(reg)


@bp.post("/registrations/<registration_id>/disclosures")
def add_disclosure(registration_id):
    caller = authenticate([ROLE_BROKER_ADMIN])
    reg = lookups.registration_or_404(registration_id)
    require_owner(caller, broker_id=reg["broker_id"])
    broker = db.brokers[reg["broker_id"]]
    data = body()
    category = get_enum(data, "category", guards.DISCLOSURE_CATEGORIES)
    content = get_str(data, "content", 1, 2000)
    covers = get_bool(data, "covers_sensitive_categories", default=False)

    existing = lookups.disclosures_of(reg["id"])
    if any(d["category"] == category for d in existing):
        fail("ERR_DUPLICATE_DISCLOSURE_CATEGORY",
             "this filing already carries a %s disclosure" % category)
    if reg["status"] not in ("DRAFT", "REJECTED"):
        fail("ERR_REGISTRATION_INVALID_STATE",
             "disclosures may only be added to a DRAFT or REJECTED filing")

    item = make(
        "DisclosureItem",
        registration_id=reg["id"],
        category=category,
        content=content,
        content_length=len(content),
        covers_sensitive_categories=covers,
        weight_credit=scoring.weight_credit(category, len(content)),
        surcharge_cents=scoring.item_surcharge_cents(category, covers),
    )
    db.disclosures[item["id"]] = item

    if reg["status"] == "REJECTED":
        reg["status"] = "DRAFT"
        reg["revision_count"] += 1
        reg["rejection_reason_code"] = None
    reg["disclosure_completeness_score"] = scoring.completeness_score(
        lookups.disclosures_of(reg["id"]))
    touch(reg)
    audit.append(broker, "DISCLOSURE_ADDED", "DISCLOSURE", item["id"],
                 audit.actor_direct(caller),
                 "%s disclosure recorded on the filing" % category)
    return ok_record(item, 201)


@bp.get("/registrations/<registration_id>/disclosures")
def list_disclosures(registration_id):
    caller = authenticate([ROLE_BROKER_ADMIN, ROLE_PLATFORM_ADMIN,
                           ROLE_REGULATOR])
    reg = lookups.registration_or_404(registration_id)
    require_owner(caller, broker_id=reg["broker_id"])
    limit, offset = pagination()
    category = filter_value("category", guards.DISCLOSURE_CATEGORIES)
    rows = lookups.disclosures_of(reg["id"])
    if category is not None:
        rows = [r for r in rows if r["category"] == category]
    return ok_list(rows, limit, offset)


def _sensitive_disclosure_required(broker_id):
    """PRD 3.2: a SENSITIVE_CATEGORIES item is additionally mandatory when any
    consumer of this broker carries a non-empty sensitive_categories list."""
    for consumer in db.consumers.values():
        if consumer["broker_id"] == broker_id and consumer["sensitive_categories"]:
            return True
    return False


@bp.post("/registrations/<registration_id>/submit")
def submit_registration(registration_id):
    caller = authenticate([ROLE_BROKER_ADMIN])
    reg = lookups.registration_or_404(registration_id)
    require_owner(caller, broker_id=reg["broker_id"])
    broker = db.brokers[reg["broker_id"]]

    if reg["status"] != "DRAFT":
        fail("ERR_REGISTRATION_INVALID_STATE",
             "only a DRAFT filing may be submitted")

    items = lookups.disclosures_of(reg["id"])
    present = set(d["category"] for d in items)
    required = list(scoring.MANDATORY_CATEGORIES)
    if _sensitive_disclosure_required(broker["id"]):
        required.append("SENSITIVE_CATEGORIES")
    missing = [c for c in required if c not in present]
    if missing:
        fail("ERR_REQUIRED_DISCLOSURE_MISSING",
             "missing mandatory disclosure categories: %s" % ", ".join(missing))

    score = scoring.completeness_score(items)
    reg["disclosure_completeness_score"] = score
    if score < scoring.COMPLETENESS_SUBMIT_MINIMUM:
        fail("ERR_DISCLOSURE_INCOMPLETE",
             "disclosure completeness %s is below the required minimum" % score)

    if lookups.overlapping_registration(broker["id"], reg["state_code"],
                                        reg["coverage_period_start"],
                                        reg["coverage_period_end"],
                                        exclude_id=reg["id"]):
        fail("ERR_COVERAGE_PERIOD_OVERLAP",
             "another submitted or accepted filing covers this interval")

    fee = scoring.provisional_filing_fee_cents(items)
    if broker["fee_credit_cents"] < fee:
        fail("ERR_FILING_FEE_UNPAID",
             "fee credit of %d cents does not cover the provisional filing fee "
             "of %d cents" % (broker["fee_credit_cents"], fee))

    reg["provisional_filing_fee_cents"] = fee
    reg["charged_fee_cents"] = fee
    broker["fee_credit_cents"] -= fee
    broker["fee_paid_cents"] += fee
    reg["submitted_at"] = now()
    reg["status"] = "SUBMITTED"
    touch(reg)
    touch(broker)
    audit.append(broker, "REGISTRATION_SUBMITTED", "REGISTRATION", reg["id"],
                 audit.actor_direct(caller),
                 "filing submitted and the provisional filing fee consumed")
    return ok_record(reg)


@bp.post("/registrations/<registration_id>/accept")
def accept_registration(registration_id):
    caller = authenticate([ROLE_PLATFORM_ADMIN])
    reg = lookups.registration_or_404(registration_id)
    broker = db.brokers[reg["broker_id"]]
    if reg["status"] != "SUBMITTED":
        fail("ERR_REGISTRATION_INVALID_STATE",
             "only a SUBMITTED filing may be accepted")

    items = lookups.disclosures_of(reg["id"])
    coverage_days = whole_days(reg["coverage_period_start"],
                               reg["coverage_period_end"])
    reg["coverage_days"] = coverage_days
    final = scoring.final_filing_fee_cents(items, coverage_days)
    provisional = reg["provisional_filing_fee_cents"] or 0
    delta = final - provisional
    if delta > 0 and broker["fee_credit_cents"] < delta:
        fail("ERR_FILING_FEE_UNPAID",
             "fee credit does not cover the %d cent acceptance shortfall"
             % delta)

    reg["final_filing_fee_cents"] = final
    reg["charged_fee_cents"] = final
    standing.settle_fee_delta(broker, delta)
    reg["accepted_at"] = now()
    reg["status"] = "ACCEPTED"
    touch(reg)
    standing.derive_standing(broker, audit.actor_system(caller))
    audit.append(broker, "REGISTRATION_ACCEPTED", "REGISTRATION", reg["id"],
                 audit.actor_direct(caller),
                 "filing accepted and the final filing fee settled")
    return ok_record(reg)


@bp.post("/registrations/<registration_id>/reject")
def reject_registration(registration_id):
    caller = authenticate([ROLE_PLATFORM_ADMIN])
    reg = lookups.registration_or_404(registration_id)
    broker = db.brokers[reg["broker_id"]]
    data = body()
    reason = get_enum(data, "rejection_reason_code",
                      guards.REJECTION_REASON_CODES)
    if reg["status"] != "SUBMITTED":
        fail("ERR_REGISTRATION_INVALID_STATE",
             "only a SUBMITTED filing may be rejected")

    reg["status"] = "REJECTED"
    reg["rejection_reason_code"] = reason
    reg["final_filing_fee_cents"] = None
    standing.refund_charged_fee(broker, reg)
    touch(reg)
    standing.derive_standing(broker, audit.actor_system(caller),
                             delinquency_cascade=True)
    audit.append(broker, "REGISTRATION_REJECTED", "REGISTRATION", reg["id"],
                 audit.actor_direct(caller),
                 "filing rejected for %s and the charged fee refunded" % reason)
    return ok_record(reg)


@bp.post("/registrations/<registration_id>/withdraw")
def withdraw_registration(registration_id):
    caller = authenticate([ROLE_BROKER_ADMIN])
    reg = lookups.registration_or_404(registration_id)
    require_owner(caller, broker_id=reg["broker_id"])
    broker = db.brokers[reg["broker_id"]]
    if reg["status"] not in ("DRAFT", "SUBMITTED", "ACCEPTED"):
        fail("ERR_REGISTRATION_INVALID_STATE",
             "only a DRAFT, SUBMITTED or ACCEPTED filing may be withdrawn")

    reg["status"] = "WITHDRAWN"
    standing.refund_charged_fee(broker, reg)
    touch(reg)
    standing.derive_standing(broker, audit.actor_system(caller),
                            delinquency_cascade=True)
    audit.append(broker, "REGISTRATION_WITHDRAWN", "REGISTRATION", reg["id"],
                 audit.actor_direct(caller),
                 "filing withdrawn by the broker and the charged fee refunded")
    return ok_record(reg)
