"""DealRegistration endpoints: draft, submit, review, decision, convert."""
from flask import g

import calc
import cascades
import serialize
import store
import validate as v
from auth import acting_partner_scope, endpoint
from constants import (CERT_CREDIT_MIN_PLATFORM_SUITE, CERT_CREDIT_MIN_TO_REGISTER,
                       MAX_REVISION_ROUNDS, MIN_REGISTRATION_AMOUNT_CENTS,
                       PRODUCT_LINES, REGISTRATION_UPLIFT_IN_WINDOW_PCT)
from errors import ApiError
from guards import (check_no_overdue_audit, check_not_suspended, find_account,
                    find_partner, find_registration, invalid_state)
from response import created, filtered, listing, object_response


def _check_supersede_target(registration, target_id):
    target = store.get("registrations", target_id)
    if (target is None
            or target["partner_id"] != registration["partner_id"]
            or target["account_id"] != registration["account_id"]
            or target["product_line"] != registration["product_line"]
            or target["status"] != "APPROVED"):
        raise ApiError("ERR_SUPERSEDE_TARGET_INVALID",
                       "The superseded registration is not a matching APPROVED predecessor.")
    return target


def _check_certifications(partner, product_line):
    calc.recompute_cert_credits(partner)
    total = partner["cert_credit_total"]
    if total < CERT_CREDIT_MIN_TO_REGISTER:
        raise ApiError("ERR_CERTIFICATION_REQUIREMENT_NOT_MET",
                       "The partner holds too few enablement credits to register a deal.")
    if product_line == "PLATFORM_SUITE":
        if total < CERT_CREDIT_MIN_PLATFORM_SUITE:
            raise ApiError("ERR_CERTIFICATION_REQUIREMENT_NOT_MET",
                           "PLATFORM_SUITE requires at least %d credits."
                           % CERT_CREDIT_MIN_PLATFORM_SUITE)
        expert = False
        for record in store.all_rows("certifications"):
            if (record["partner_id"] == partner["id"]
                    and record["status"] == "ACTIVE"
                    and record["track"] == "TECH_EXPERT"):
                expert = True
                break
        if not expert:
            raise ApiError("ERR_CERTIFICATION_REQUIREMENT_NOT_MET",
                           "PLATFORM_SUITE requires an ACTIVE TECH_EXPERT certification.")


def _check_exclusivity(registration, account):
    if account["coverage_state"] == "DIRECT_LOCKED":
        raise ApiError("ERR_EXCLUSIVITY_CONFLICT",
                       "The account is locked to direct sales.")
    instant = store.now()
    superseded = registration.get("supersedes_registration_id")
    for other in store.ordered(store.all_rows("registrations")):
        if other["id"] == registration["id"]:
            continue
        if other["account_id"] != registration["account_id"]:
            continue
        if other["product_line"] != registration["product_line"]:
            continue
        if other["status"] != "APPROVED":
            continue
        if not calc.window_live(other, instant):
            continue
        if (superseded is not None and other["id"] == superseded
                and other["partner_id"] == registration["partner_id"]):
            continue
        raise ApiError("ERR_EXCLUSIVITY_CONFLICT",
                       "Another approved registration holds a live exclusivity window.")


def _check_duplicate(registration):
    for other in store.ordered(store.all_rows("registrations")):
        if other["id"] == registration["id"]:
            continue
        if other["partner_id"] != registration["partner_id"]:
            continue
        if other["account_id"] != registration["account_id"]:
            continue
        if other["product_line"] != registration["product_line"]:
            continue
        if other["status"] in ("SUBMITTED", "UNDER_REVIEW", "CHANGES_REQUESTED",
                               "CONFLICT_HELD"):
            raise ApiError("ERR_DUPLICATE_REGISTRATION",
                           "This partner already has a registration in flight.")


def _check_mapping_block(registration):
    instant = store.now()
    for mapping in store.ordered(store.all_rows("mappings")):
        if mapping["mapping_status"] != "ACTIVE":
            continue
        if mapping["account_id"] != registration["account_id"]:
            continue
        if mapping["partner_id"] == registration["partner_id"]:
            continue
        if not calc.mapping_covers_product_line(mapping, registration["product_line"]):
            continue
        if mapping["effective_from"] <= instant <= mapping["effective_until"]:
            raise ApiError("ERR_MAPPING_WINDOW_CONFLICT",
                           "Another partner holds a live mapping agreement on this account.")


def register(app):
    @app.route("/deal-registrations", methods=["POST"])
    @endpoint("Partner")
    def create_registration():
        body = v.body()
        # existence (3): body foreign keys in declaration order
        partner_ref = v.fk_candidate(body, "partner_id")
        partner = find_partner(partner_ref) if partner_ref is not None else None
        account_ref = v.fk_candidate(body, "account_id")
        if account_ref is not None:
            find_account(account_ref)
        supersede_ref = v.fk_candidate(body, "supersedes_registration_id")
        if supersede_ref is not None:
            find_registration(supersede_ref)
        # partner scoping (4)
        if partner is not None:
            acting_partner_scope(partner["id"])
        # request shape (5)
        partner_id = v.req_string(body, "partner_id")
        account_id = v.req_string(body, "account_id")
        product_line = v.req_enum(body, "product_line", PRODUCT_LINES)
        expected_amount = v.req_int(body, "expected_amount_cents",
                                   minimum=MIN_REGISTRATION_AMOUNT_CENTS)
        expected_close = v.req_instant(body, "expected_close_date")
        supersedes = v.opt_string(body, "supersedes_registration_id")
        row = {
            "partner_id": partner_id,
            "account_id": account_id,
            "product_line": product_line,
            "expected_amount_cents": expected_amount,
            "expected_close_date": expected_close,
            "supersedes_registration_id": supersedes,
            "status": "DRAFT",
            "submitted_at": None,
            "approved_at": None,
            "exclusivity_start_at": None,
            "exclusivity_end_at": None,
            "protection_days": None,
            "registration_margin_uplift_pct": calc.q4("0"),
            "revision_round": 0,
            "closure_reason": None,
        }
        # supersede target (24)
        if supersedes is not None:
            _check_supersede_target(row, supersedes)
        store.insert("registrations", row)
        return created(serialize.registration(row))

    @app.route("/deal-registrations", methods=["GET"])
    @endpoint("ChannelOpsAnalyst", "ChannelDirector", "DirectSalesRep", "Partner")
    def list_registrations():
        rows = store.ordered(store.all_rows("registrations"))
        rows = filtered(rows, [("partner_id", "partner_id"),
                               ("account_id", "account_id"),
                               ("status", "status"),
                               ("product_line", "product_line"),
                               ("supersedes_registration_id", "supersedes_registration_id")])
        return listing(rows, serialize.registration)

    @app.route("/deal-registrations/<registration_id>", methods=["GET"])
    @endpoint("ChannelOpsAnalyst", "ChannelDirector", "DirectSalesRep", "Partner")
    def read_registration(registration_id):
        row = find_registration(registration_id)
        return object_response(serialize.registration(row))

    @app.route("/deal-registrations/<registration_id>/submit", methods=["POST"])
    @endpoint("Partner")
    def submit_registration(registration_id):
        registration = find_registration(registration_id)
        acting_partner_scope(registration["partner_id"])
        v.body()
        status = registration["status"]
        if status not in ("DRAFT", "CHANGES_REQUESTED"):
            raise invalid_state("A registration in %s cannot be submitted." % status)
        if status == "CHANGES_REQUESTED" and registration["revision_round"] >= MAX_REVISION_ROUNDS:
            raise invalid_state("The revision round limit has been reached.")
        partner = store.get("partners", registration["partner_id"])
        account = store.get("accounts", registration["account_id"])
        _check_duplicate(registration)
        check_not_suspended(partner)
        check_no_overdue_audit(partner)
        _check_certifications(partner, registration["product_line"])
        # the expiry sweep runs before every precondition that inspects a window
        cascades.registration_expiry_sweep(registration["account_id"],
                                          registration["product_line"])
        _check_exclusivity(registration, account)
        _check_mapping_block(registration)
        if status == "CHANGES_REQUESTED":
            registration["revision_round"] = registration["revision_round"] + 1
        registration["status"] = "SUBMITTED"
        registration["submitted_at"] = store.now()
        store.touch(registration)
        return object_response(serialize.registration(registration))

    @app.route("/deal-registrations/<registration_id>/review", methods=["POST"])
    @endpoint("ChannelOpsAnalyst")
    def review_registration(registration_id):
        registration = find_registration(registration_id)
        body = v.body()
        action = v.req_enum(body, "action", ("START_REVIEW", "REQUEST_CHANGES"))
        if action == "START_REVIEW":
            if registration["status"] != "SUBMITTED":
                raise invalid_state("Only a SUBMITTED registration can enter review.")
            registration["status"] = "UNDER_REVIEW"
        else:
            note = v.req_string(body, "reviewer_note")
            if registration["status"] != "UNDER_REVIEW":
                raise invalid_state("Only a registration UNDER_REVIEW can be sent back.")
            registration["status"] = "CHANGES_REQUESTED"
            registration["closure_reason"] = note
        store.touch(registration)
        return object_response(serialize.registration(registration))

    @app.route("/deal-registrations/<registration_id>/decision", methods=["POST"])
    @endpoint("ChannelDirector")
    def decide_registration(registration_id):
        registration = find_registration(registration_id)
        body = v.body()
        decision = v.req_enum(body, "decision", ("APPROVE", "REJECT"))
        reject_reason = None
        if decision == "REJECT":
            reject_reason = v.req_string(body, "reject_reason")
        if registration["status"] != "UNDER_REVIEW":
            raise invalid_state("Only a registration UNDER_REVIEW can be decided.")
        partner = store.get("partners", registration["partner_id"])
        account = store.get("accounts", registration["account_id"])
        if decision == "REJECT":
            registration["status"] = "REJECTED"
            registration["closure_reason"] = reject_reason
            registration["registration_margin_uplift_pct"] = calc.q4("0")
            store.touch(registration)
            return object_response(serialize.registration(registration))
        check_not_suspended(partner)
        _check_exclusivity(registration, account)
        predecessor = None
        if registration["supersedes_registration_id"] is not None:
            predecessor = _check_supersede_target(
                registration, registration["supersedes_registration_id"])
        instant = store.now()
        days = calc.protection_days_for(partner["tier"])
        registration["status"] = "APPROVED"
        registration["approved_at"] = instant
        registration["protection_days"] = days
        registration["exclusivity_start_at"] = instant
        registration["exclusivity_end_at"] = store.plus_days(instant, days)
        registration["registration_margin_uplift_pct"] = calc.q4(
            REGISTRATION_UPLIFT_IN_WINDOW_PCT)
        store.touch(registration)
        cascades.cascade_a(registration, account)
        if predecessor is not None:
            predecessor["status"] = "SUPERSEDED"
            predecessor["closure_reason"] = "SUPERSEDED_BY_RENEWAL"
            store.touch(predecessor)
        return object_response(serialize.registration(registration))

    @app.route("/deal-registrations/<registration_id>/convert", methods=["POST"])
    @endpoint("ChannelOpsAnalyst")
    def convert_registration(registration_id):
        registration = find_registration(registration_id)
        v.body()
        if registration["status"] != "APPROVED":
            raise invalid_state("Only an APPROVED registration can be converted.")
        converted = False
        for order in store.all_rows("orders"):
            if (order["registration_id"] == registration["id"]
                    and order["status"] in ("INVOICED", "CREDITED")):
                converted = True
                break
        if not converted:
            raise invalid_state("No order on this registration has been invoiced.")
        registration["status"] = "CONVERTED"
        registration["closure_reason"] = "CONVERTED"
        store.touch(registration)
        return object_response(serialize.registration(registration))

    @app.route("/deal-registrations/<registration_id>/special-pricing-requests",
               methods=["GET"])
    @endpoint("ChannelOpsAnalyst", "ChannelDirector", "Partner")
    def list_registration_sprs(registration_id):
        registration = find_registration(registration_id)
        rows = [r for r in store.ordered(store.all_rows("sprs"))
                if r["registration_id"] == registration["id"]]
        rows = filtered(rows, [("status", "status")])
        return listing(rows, serialize.spr)

    @app.route("/deal-registrations/<registration_id>/order-invoices", methods=["GET"])
    @endpoint("ChannelOpsAnalyst", "ChannelDirector", "Partner")
    def list_registration_orders(registration_id):
        registration = find_registration(registration_id)
        rows = [r for r in store.ordered(store.all_rows("orders"))
                if r["registration_id"] == registration["id"]]
        rows = filtered(rows, [("status", "status")])
        return listing(rows, serialize.order)
