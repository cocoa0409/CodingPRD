"""SpecialPricingRequest endpoints."""
from decimal import Decimal

from flask import g

import calc
import serialize
import store
import validate as v
from auth import acting_partner_scope, endpoint
from constants import (BASE_MARGIN_PCT, REGISTRATION_UPLIFT_IN_WINDOW_PCT,
                       SPR_MAX_REQUESTED_EXTRA_MARGIN_PCT, SPR_VALIDITY_DAYS,
                       TIER_MARGIN_CEILING_PCT)
from errors import ApiError
from guards import check_not_suspended, find, find_registration, invalid_state
from response import created, filtered, listing, object_response


def register(app):
    @app.route("/special-pricing-requests", methods=["POST"])
    @endpoint("Partner")
    def create_spr():
        body = v.body()
        # existence (3)
        registration_ref = v.fk_candidate(body, "registration_id")
        registration = (find_registration(registration_ref)
                        if registration_ref is not None else None)
        # partner scoping (4)
        if registration is not None:
            acting_partner_scope(registration["partner_id"])
        # request shape (5)
        registration_id = v.req_string(body, "registration_id")
        requested = v.req_fraction(body, "requested_extra_margin_pct",
                                   low=Decimal("0"), low_exclusive=True,
                                   high=SPR_MAX_REQUESTED_EXTRA_MARGIN_PCT)
        justification = v.req_string(body, "justification")
        expected_version = v.req_int(body, "expected_registration_version", minimum=0)
        # registration stale-version guard (7)
        if registration["version"] != expected_version:
            raise ApiError("ERR_STALE_REGISTRATION_VERSION",
                           "The registration has been modified since it was read.")
        partner = store.get("partners", registration["partner_id"])
        # program standing (13)
        check_not_suspended(partner)
        # registration approved and live (25)
        instant = store.now()
        if registration["status"] != "APPROVED" or not calc.window_live(registration, instant):
            raise ApiError("ERR_REGISTRATION_NOT_APPROVED",
                           "The registration is not APPROVED with a live exclusivity window.")
        horizon = store.plus_days(instant, SPR_VALIDITY_DAYS)
        window_end = registration["exclusivity_end_at"]
        expires_at = window_end if window_end < horizon else horizon
        # a create supersedes every still-pending request on the same registration
        for other in store.ordered(store.all_rows("sprs")):
            if other["registration_id"] != registration["id"]:
                continue
            if other["status"] != "SUBMITTED":
                continue
            other["status"] = "SUPERSEDED"
            other["approved_extra_margin_pct"] = calc.q4("0")
            store.touch(other)
        row = {
            "registration_id": registration_id,
            "requested_extra_margin_pct": calc.q4(requested),
            "justification": justification,
            "status": "SUBMITTED",
            "approved_extra_margin_pct": None,
            "expires_at": expires_at,
            "decided_by_user_id": None,
        }
        store.insert("sprs", row)
        store.touch(registration)
        return created(serialize.spr(row))

    @app.route("/special-pricing-requests", methods=["GET"])
    @endpoint("ChannelOpsAnalyst", "ChannelDirector", "Partner")
    def list_sprs():
        rows = store.ordered(store.all_rows("sprs"))
        rows = filtered(rows, [("registration_id", "registration_id"),
                               ("status", "status")])
        return listing(rows, serialize.spr)

    @app.route("/special-pricing-requests/<spr_id>", methods=["GET"])
    @endpoint("ChannelOpsAnalyst", "ChannelDirector", "Partner")
    def read_spr(spr_id):
        row = find("sprs", spr_id)
        return object_response(serialize.spr(row))

    @app.route("/special-pricing-requests/<spr_id>/decision", methods=["POST"])
    @endpoint("ChannelDirector")
    def decide_spr(spr_id):
        spr = find("sprs", spr_id)
        body = v.body()
        decision = v.req_enum(body, "decision", ("APPROVE", "PARTIAL", "DENY"))
        requested = calc.dec(spr["requested_extra_margin_pct"])
        partial_value = None
        if decision == "PARTIAL":
            partial_value = v.req_fraction(body, "approved_extra_margin_pct",
                                           low=Decimal("0"), low_exclusive=True,
                                           high=requested, high_exclusive=True)
        # state precondition (9)
        if spr["status"] != "SUBMITTED":
            raise invalid_state("Only a SUBMITTED request can be decided.")
        registration = store.get("registrations", spr["registration_id"])
        partner = store.get("partners", registration["partner_id"]) if registration else None
        instant = store.now()
        if decision in ("APPROVE", "PARTIAL"):
            # special-pricing validity window (19)
            if not (instant < spr["expires_at"]):
                raise ApiError("ERR_EXCLUSIVITY_WINDOW_EXPIRED",
                               "The request's validity window has elapsed.")
            granted = requested if decision == "APPROVE" else partial_value
            # margin ceiling (20)
            tier = partner["tier"]
            resolved = (BASE_MARGIN_PCT[tier] + REGISTRATION_UPLIFT_IN_WINDOW_PCT
                        + granted)
            if resolved > TIER_MARGIN_CEILING_PCT[tier]:
                raise ApiError("ERR_MARGIN_CEILING_EXCEEDED",
                               "The grant would breach the tier's margin ceiling.")
            spr["status"] = "APPROVED" if decision == "APPROVE" else "PARTIALLY_APPROVED"
            spr["approved_extra_margin_pct"] = calc.q4(granted)
        else:
            spr["status"] = "DENIED"
            spr["approved_extra_margin_pct"] = calc.q4("0")
        spr["decided_by_user_id"] = g.user_id
        store.touch(spr)
        return object_response(serialize.spr(spr))
