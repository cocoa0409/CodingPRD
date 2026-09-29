"""Enrolment, activation, cancellation, fulfilment scheduling, surveys and
non-installation evaluations (PRD 3.3, 3.4, 3.5, 3.6, 3.9)."""
from flask import Blueprint

import calc
import clock
import envelope
import guards
import ledger
import services
import validate
import views
from errors import fail
from store import base_record, db, touch

bp = Blueprint("subscriptions", __name__)

BILLING_PARTIES = ("PROPERTY_MANAGER", "RESIDENT")
ENROLLMENT_CHANNELS = ("MOVE_IN_PACKET", "RESIDENT_PORTAL", "PM_BULK_UPLOAD")
SUBSCRIPTION_STATUSES = ("PENDING_SETUP", "ACTIVE", "SUSPENDED", "TRANSFER_PENDING",
                         "CANCELLED", "VOIDED")
POSTURES = ("UNVERIFIED", "COMPLIANT", "NON_INSTALL_SUSPECTED",
            "NON_INSTALL_CONFIRMED", "REMEDIATED")
BENEFIT_CODES = ("AIR_QUALITY_GUARANTEE", "CREDIT_REPORTING", "DAMAGE_WAIVER",
                 "RENTERS_INSURANCE")
ENTITLEMENT_STATES = ("PENDING", "ACTIVE", "SUSPENDED", "FORFEITED", "EXPIRED")
ENTRY_TYPES = ("ENROLLMENT_FEE", "MONTHLY_FEE", "PRORATION_CREDIT",
               "UNRETURNED_SHIPMENT_FEE", "WAIVER_REVERSAL", "CLAIM_PAYOUT",
               "CLAIM_PAYOUT_REVERSAL", "TRANSFER_ADJUSTMENT")
CLAIM_TYPES = ("DAMAGE_WAIVER", "AIR_QUALITY_GUARANTEE")
CLAIM_STATUSES = ("SUBMITTED", "UNDER_REVIEW", "INFO_REQUESTED", "APPROVED",
                  "DENIED", "PAID", "PAYMENT_REVERSED", "WITHDRAWN")
CASE_STATUSES = ("OPEN", "NOTICE_SENT", "REMEDIATED", "ESCALATED_TO_PM",
                 "CLOSED_UNSUBSTANTIATED")
DETECTION_METHODS = ("RUNTIME_ANALYTICS", "RENEWAL_SURVEY")


def new_entitlement(sub, benefit_code):
    rec = base_record()
    rec["subscription_id"] = sub["id"]
    rec["benefit_code"] = benefit_code
    rec["state"] = "PENDING"
    rec["suspended_by_property_event"] = False
    rec["effective_from"] = None
    rec["terminated_at"] = None
    rec["forfeit_reason"] = None
    db.entitlements[rec["id"]] = rec
    return rec


def build_subscription(resident, unit, prop, billing_party, enrollment_channel,
                       lease_start, lease_end, priced, predecessor_id=None,
                       status="PENDING_SETUP"):
    rec = base_record()
    rec["resident_id"] = resident["id"]
    rec["unit_id"] = unit["id"]
    rec["property_id"] = prop["id"]
    rec["assigned_sku_id"] = priced["assigned_sku_id"]
    rec["predecessor_subscription_id"] = predecessor_id
    rec["billing_party"] = billing_party
    rec["enrollment_channel"] = enrollment_channel
    rec["lease_start_date"] = lease_start
    rec["lease_end_date"] = lease_end
    rec["status"] = status
    rec["installation_posture"] = "UNVERIFIED"
    rec["ship_cadence_days"] = priced["ship_cadence_days"]
    rec["filters_per_shipment"] = priced["filters_per_shipment"]
    rec["monthly_fee_cents"] = priced["monthly_fee_cents"]
    rec["entitled_benefit_codes"] = priced["entitled_benefit_codes"]
    rec["next_ship_date"] = None
    rec["shipment_sequence_counter"] = 0
    rec["activated_at"] = None
    rec["cancel_effective_date"] = None
    rec["cancel_reason"] = None
    rec["gross_prorated_credit_cents"] = 0
    rec["waiver_credit_pct"] = 0
    rec["unreturned_fee_gross_cents"] = 0
    rec["unreturned_fee_net_cents"] = 0
    rec["net_settlement_cents"] = 0
    rec["latest_detection_method"] = None
    rec["latest_evidence_score"] = None
    db.subscriptions[rec["id"]] = rec
    return rec


@bp.post("/subscriptions")
def enroll():
    uid, role = guards.auth(["ProgramOperator", "PropertyManager"])
    body = validate.json_body()
    # rung 3: body foreign keys resolve in declaration order
    resident = guards.get_resident(body.get("resident_id"))
    unit = guards.get_unit(body.get("unit_id"))
    guards.own_property(uid, role, unit["property_id"])
    billing_party = validate.req_enum(body, "billing_party", BILLING_PARTIES)
    channel = validate.req_enum(body, "enrollment_channel", ENROLLMENT_CHANNELS)
    lease_start = validate.req_date(body, "lease_start_date")
    lease_end = validate.req_date(body, "lease_end_date")
    if not lease_end > lease_start:
        fail("ERR_INVALID_REQUEST",
             "lease_end_date must be strictly later than lease_start_date")
    prop = db.properties[unit["property_id"]]
    if prop["status"] != "ACTIVE":
        fail("ERR_PROPERTY_NOT_ACTIVE", "the owning property is not ACTIVE")

    priced = calc.derive_pricing(unit, resident, prop, billing_party, "UNVERIFIED")

    for other in calc.subscriptions_of_unit(unit["id"]):
        if (other["resident_id"] == resident["id"]
                and other["status"] in calc.LIVE_SUBSCRIPTION_STATUSES):
            fail("ERR_DUPLICATE_ACTIVE_SUBSCRIPTION",
                 "this resident already holds a live subscription on this unit")
    if calc.occupancy_conflict(unit["id"], lease_start, lease_end):
        fail("ERR_UNIT_OCCUPANCY_CONFLICT",
             "the requested lease interval collides with a live occupancy")

    sub = build_subscription(resident, unit, prop, billing_party, channel,
                             clock.fmt_date(lease_start), clock.fmt_date(lease_end),
                             priced)
    for code in sub["entitled_benefit_codes"]:
        new_entitlement(sub, code)
    return envelope.object_response(views.subscription_view(sub), 201)


@bp.get("/subscriptions/<subscription_id>")
def read_subscription(subscription_id):
    uid, role = guards.auth(["ProgramOperator", "PropertyManager", "Resident"])
    sub = guards.get_subscription(subscription_id)
    guards.own_subscription(uid, role, sub)
    return envelope.object_response(views.subscription_view(sub))


@bp.get("/subscriptions")
def list_subscriptions():
    uid, role = guards.auth(["ProgramOperator", "PropertyManager"])
    limit, offset, filters = guards.pagination(
        {"status": SUBSCRIPTION_STATUSES, "installation_posture": POSTURES},
        ("resident_id", "unit_id", "property_id", "assigned_sku_id",
         "predecessor_subscription_id"))
    rows = [s for s in db.subscriptions.values()
            if all(s[k] == v for k, v in filters.items())]
    if role == "PropertyManager":
        rows = [s for s in rows if s["property_id"] == uid]
    rows = calc.sorted_rows(rows)
    return envelope.list_response([views.subscription_view(r) for r in
                                  guards.page(rows, limit, offset)],
                                 limit, offset, len(rows))


def create_shipment(sub, scheduled_date, quantity, tracking_code):
    sub["shipment_sequence_counter"] = sub["shipment_sequence_counter"] + 1
    rec = base_record()
    rec["subscription_id"] = sub["id"]
    rec["sku_id"] = sub["assigned_sku_id"]
    rec["sequence_number"] = sub["shipment_sequence_counter"]
    rec["scheduled_ship_date"] = clock.fmt_date(scheduled_date)
    rec["quantity"] = quantity
    rec["tracking_code"] = tracking_code
    rec["shipped_at"] = None
    rec["delivered_at"] = None
    rec["returned_at"] = None
    rec["unreturned_fee_cents"] = 0
    rec["status"] = "SCHEDULED"
    db.shipments[rec["id"]] = rec
    return rec


@bp.post("/subscriptions/<subscription_id>/activate")
def activate(subscription_id):
    uid, role = guards.auth(["ProgramOperator", "PropertyManager"])
    sub = guards.get_subscription(subscription_id)
    guards.own_subscription(uid, role, sub)
    prop = db.properties[sub["property_id"]]
    if prop["status"] != "ACTIVE":
        fail("ERR_PROPERTY_NOT_ACTIVE", "the owning property is not ACTIVE")
    if sub["status"] != "PENDING_SETUP":
        fail("ERR_SUBSCRIPTION_STATE_INVALID", "the subscription is not PENDING_SETUP")
    sku = db.skus[sub["assigned_sku_id"]]
    if sku["status"] != "ACTIVE":
        fail("ERR_SKU_DISCONTINUED", "the assigned SKU has been discontinued")

    activation_date = clock.today()
    first_month = calc.first_month_fee_cents(sub["monthly_fee_cents"], activation_date)
    ledger.check_credit_ceiling(prop, sub["billing_party"],
                                calc.ENROLLMENT_FEE_CENTS + first_month)

    sub["status"] = "ACTIVE"
    sub["activated_at"] = clock.now_iso()
    touch(sub)
    services.start_residency(sub["resident_id"])
    services.occupy_unit(sub["unit_id"])
    services.activate_entitlements(sub)
    create_shipment(sub, activation_date, sub["filters_per_shipment"], None)
    ledger.post_one_off(sub, "ENROLLMENT_FEE", calc.ENROLLMENT_FEE_CENTS,
                        "enrollment fee", sub["id"], on_date=activation_date)
    ledger.post(sub, "MONTHLY_FEE", first_month,
                clock.fmt_date(activation_date),
                clock.fmt_date(clock.last_of_month(activation_date)),
                "first month prorated fee", sub["id"])
    return envelope.object_response(views.subscription_view(sub))


@bp.post("/subscriptions/<subscription_id>/cancel")
def cancel(subscription_id):
    uid, role = guards.auth(["ProgramOperator", "PropertyManager", "Resident"])
    sub = guards.get_subscription(subscription_id)
    guards.own_subscription(uid, role, sub)
    body = validate.json_body()
    effective_date = validate.req_date(body, "effective_date")
    reason = validate.req_text(body, "cancel_reason")
    if sub["status"] not in ("PENDING_SETUP", "ACTIVE", "SUSPENDED"):
        fail("ERR_SUBSCRIPTION_STATE_INVALID",
             "the subscription cannot be cancelled from its current status")

    if sub["status"] == "PENDING_SETUP":
        services.void_subscription(sub, effective_date, reason)
        return envelope.object_response(views.subscription_view(sub))

    if effective_date < clock.today():
        fail("ERR_CANCEL_DATE_INVALID",
             "effective_date must be on or after the current logical-clock date")
    if effective_date > clock.parse_date(sub["lease_end_date"]):
        fail("ERR_CANCEL_DATE_INVALID",
             "effective_date must not be later than lease_end_date")
    services.settle_and_cancel_subscription(sub, effective_date, reason)
    return envelope.object_response(views.subscription_view(sub))


@bp.get("/subscriptions/<subscription_id>/settlement")
def settlement_preview(subscription_id):
    uid, role = guards.auth(["ProgramOperator", "PropertyManager"])
    sub = guards.get_subscription(subscription_id)
    guards.own_subscription(uid, role, sub)
    effective_date = validate.query_date("effective_date")
    result = calc.cancellation_settlement(sub, effective_date)
    return envelope.object_response({
        "subscription_id": sub["id"],
        "used_days": result["used_days"],
        "unused_days": result["unused_days"],
        "gross_prorated_credit_cents": result["gross_prorated_credit_cents"],
        "exposed_shipment_count": result["exposed_shipment_count"],
        "unreturned_fee_gross_cents": result["unreturned_fee_gross_cents"],
        "waiver_credit_pct": calc.pct_string(result["waiver_credit_pct"]),
        "unreturned_fee_net_cents": result["unreturned_fee_net_cents"],
        "net_settlement_cents": result["net_settlement_cents"],
    })


@bp.get("/subscriptions/<subscription_id>/benefit-entitlements")
def list_entitlements(subscription_id):
    uid, role = guards.auth(["ProgramOperator", "PropertyManager", "Resident"])
    sub = guards.get_subscription(subscription_id)
    guards.own_subscription(uid, role, sub)
    limit, offset, filters = guards.pagination({"status": ENTITLEMENT_STATES,
                                                "benefit_code": BENEFIT_CODES})
    rows = calc.entitlements_of(sub["id"])
    if "status" in filters:
        rows = [r for r in rows if r["state"] == filters["status"]]
    if "benefit_code" in filters:
        rows = [r for r in rows if r["benefit_code"] == filters["benefit_code"]]
    return envelope.list_response([views.entitlement_view(r) for r in
                                  guards.page(rows, limit, offset)],
                                 limit, offset, len(rows))


@bp.get("/subscriptions/<subscription_id>/ledger-entries")
def list_ledger(subscription_id):
    uid, role = guards.auth(["ProgramOperator", "PropertyManager"])
    sub = guards.get_subscription(subscription_id)
    guards.own_subscription(uid, role, sub)
    limit, offset, filters = guards.pagination({"entry_type": ENTRY_TYPES})
    rows = [r for r in calc.ledger_of(sub["id"])
            if all(r[k] == v for k, v in filters.items())]
    return envelope.list_response([views.ledger_view(r) for r in
                                  guards.page(rows, limit, offset)],
                                 limit, offset, len(rows))


@bp.get("/subscriptions/<subscription_id>/claims")
def list_subscription_claims(subscription_id):
    uid, role = guards.auth(["ProgramOperator", "PropertyManager", "ClaimsAdjuster",
                             "Resident"])
    sub = guards.get_subscription(subscription_id)
    guards.own_subscription(uid, role, sub)
    limit, offset, filters = guards.pagination({"status": CLAIM_STATUSES,
                                                "claim_type": CLAIM_TYPES})
    rows = [c for c in db.claims.values() if c["subscription_id"] == sub["id"]]
    rows = [c for c in rows if all(c[k] == v for k, v in filters.items())]
    rows = calc.sorted_rows(rows)
    return envelope.list_response([views.claim_view(r) for r in
                                  guards.page(rows, limit, offset)],
                                 limit, offset, len(rows))


@bp.get("/subscriptions/<subscription_id>/non-install-cases")
def list_cases(subscription_id):
    uid, role = guards.auth(["ProgramOperator", "PropertyManager"])
    sub = guards.get_subscription(subscription_id)
    guards.own_subscription(uid, role, sub)
    limit, offset, filters = guards.pagination({"status": CASE_STATUSES,
                                                "detection_method": DETECTION_METHODS})
    rows = [c for c in calc.cases_of(sub["id"])
            if all(c[k] == v for k, v in filters.items())]
    return envelope.list_response([views.case_view(r) for r in
                                  guards.page(rows, limit, offset)],
                                 limit, offset, len(rows))


WINDOW_STATUSES = ("SCHEDULED", "SHIPPED", "DELIVERED", "RETURN_REQUESTED",
                   "RETURNED", "UNRETURNED_WRITTEN_OFF")


@bp.post("/subscriptions/<subscription_id>/shipments")
def schedule_shipment(subscription_id):
    guards.auth(["ProgramOperator"])
    sub = guards.get_subscription(subscription_id)
    body = validate.json_body()
    scheduled_date = validate.req_date(body, "scheduled_ship_date")
    quantity = validate.opt_int(body, "quantity")
    tracking_code = validate.opt_string(body, "tracking_code")
    if quantity is not None and quantity != sub["filters_per_shipment"]:
        fail("ERR_INVALID_REQUEST",
             "quantity must equal the subscription's filters_per_shipment")
    if quantity is None:
        quantity = sub["filters_per_shipment"]
    if sub["status"] != "ACTIVE":
        fail("ERR_SUBSCRIPTION_STATE_INVALID", "the subscription is not ACTIVE")
    sku = db.skus[sub["assigned_sku_id"]]
    if sku["status"] != "ACTIVE":
        fail("ERR_SKU_DISCONTINUED", "the assigned SKU has been discontinued")

    live = [s for s in calc.shipments_of(sub["id"])
            if s["status"] in WINDOW_STATUSES]
    if live:
        live.sort(key=lambda s: (s["scheduled_ship_date"], s["created_at"], s["_seq"]))
        latest = live[-1]
        window_start = clock.parse_date(latest["scheduled_ship_date"])
        window_end = clock.plus_days(window_start, sub["ship_cadence_days"])
        if window_start <= scheduled_date < window_end:
            fail("ERR_SHIPMENT_WINDOW_OVERLAP",
                 "the requested date falls inside the previous cadence window")

    rec = create_shipment(sub, scheduled_date, quantity, tracking_code)
    # PRD 3.5 advances the subscription's shipment_sequence_counter, which is a
    # mutation of the subscription row; PRD 2.4 increments version on every one.
    touch(sub)
    return envelope.object_response(views.shipment_view(rec), 201)


@bp.post("/subscriptions/<subscription_id>/renewal-surveys")
def create_survey(subscription_id):
    uid, role = guards.auth(["ProgramOperator", "Resident"])
    sub = guards.get_subscription(subscription_id)
    guards.own_subscription(uid, role, sub)
    body = validate.json_body()
    installed = validate.req_bool(body, "installed_last_shipment")
    on_hand = validate.req_int(body, "filters_on_hand_count", 0, 24)
    change_date = validate.opt_date(body, "self_reported_change_date")
    if sub["status"] not in ("ACTIVE", "SUSPENDED"):
        fail("ERR_SUBSCRIPTION_STATE_INVALID",
             "renewal surveys are only accepted against a live subscription")

    rec = base_record(with_version=False)
    rec["subscription_id"] = sub["id"]
    rec["installed_last_shipment"] = installed
    rec["filters_on_hand_count"] = on_hand
    rec["self_reported_change_date"] = (clock.fmt_date(change_date)
                                        if change_date else None)
    rec["submitted_at"] = clock.now_iso()
    db.surveys[rec["id"]] = rec
    return envelope.object_response(views.survey_view(rec), 201)


@bp.get("/subscriptions/<subscription_id>/renewal-surveys")
def list_surveys(subscription_id):
    uid, role = guards.auth(["ProgramOperator", "PropertyManager"])
    sub = guards.get_subscription(subscription_id)
    guards.own_subscription(uid, role, sub)
    limit, offset, _ = guards.pagination()
    rows = calc.surveys_of(sub["id"])
    return envelope.list_response([views.survey_view(r) for r in
                                  guards.page(rows, limit, offset)],
                                 limit, offset, len(rows))


@bp.post("/subscriptions/<subscription_id>/non-install-evaluations")
def evaluate_non_install(subscription_id):
    guards.auth(["ProgramOperator"])
    sub = guards.get_subscription(subscription_id)
    body = validate.json_body()
    method = validate.req_enum(body, "detection_method", DETECTION_METHODS)
    validate.req_date(body, "evaluated_through_date")
    if sub["status"] not in ("ACTIVE", "SUSPENDED"):
        fail("ERR_SUBSCRIPTION_STATE_INVALID",
             "evaluations only run against a live subscription")
    if sub["installation_posture"] == "NON_INSTALL_CONFIRMED":
        fail("ERR_SUBSCRIPTION_STATE_INVALID",
             "a confirmed non-installation cannot be re-evaluated")

    score = calc.evidence_score(sub, method)
    suspect = calc.SUSPECT_THRESHOLD[method]
    confirm = calc.CONFIRM_THRESHOLD[method]
    posture = sub["installation_posture"]
    if score >= suspect:
        if posture not in ("UNVERIFIED", "COMPLIANT", "NON_INSTALL_SUSPECTED"):
            fail("ERR_SUBSCRIPTION_STATE_INVALID",
                 "the compliance dimension does not permit NON_INSTALL_SUSPECTED")
        case_status = "OPEN"
        target_posture = "NON_INSTALL_SUSPECTED"
    else:
        if posture not in ("UNVERIFIED", "REMEDIATED", "COMPLIANT"):
            fail("ERR_SUBSCRIPTION_STATE_INVALID",
                 "the compliance dimension does not permit COMPLIANT")
        case_status = "CLOSED_UNSUBSTANTIATED"
        target_posture = "COMPLIANT"

    rec = base_record()
    rec["subscription_id"] = sub["id"]
    rec["detection_method"] = method
    rec["evidence_score"] = score
    rec["suspect_threshold"] = suspect
    rec["confirm_threshold"] = confirm
    rec["opened_at"] = clock.now_iso()
    rec["notice_sent_at"] = None
    rec["remediation_deadline"] = None
    rec["remediation_note"] = None
    rec["status"] = case_status
    db.cases[rec["id"]] = rec

    sub["latest_detection_method"] = method
    sub["latest_evidence_score"] = score
    sub["installation_posture"] = target_posture
    touch(sub)
    return envelope.object_response(views.case_view(rec), 201)
