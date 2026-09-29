"""Logical clock, Partner and CertificationRecord endpoints."""
from flask import g

import calc
import serialize
import store
import validate as v
from auth import endpoint
from constants import CERT_CREDIT_WEIGHT, MAX_NAME_LEN, PARTNER_TYPES, TRACKS
from guards import find, find_partner
from response import created, filtered, listing, object_response


def register(app):
    # ------------------------------------------------------------------ clock
    @app.route("/_clock/set_current_utc", methods=["POST"])
    def set_clock():
        # PRD 2.4: the one endpoint that does not require the identity headers.
        body = v.body()
        instant = v.req_instant(body, "current_utc")
        store.set_clock(instant)
        return object_response({})

    # ---------------------------------------------------------------- Partner
    @app.route("/partners", methods=["POST"])
    @endpoint("ChannelOpsAnalyst")
    def create_partner():
        body = v.body()
        company_name = v.req_string(body, "company_name", max_len=MAX_NAME_LEN)
        partner_type = v.req_enum(body, "partner_type", PARTNER_TYPES)
        commitment = v.opt_int(body, "marketing_commitment_cents", minimum=0, default=0)
        row = {
            "company_name": company_name,
            "partner_type": partner_type,
            "tier": "REGISTERED",
            "tier_status": "COMPLIANT",
            "marketing_commitment_cents": commitment,
            "cert_credit_total": 0,
            "trailing_revenue_cents": 0,
            "marketing_qualified_spend_cents": 0,
            "marketing_attainment_pct": calc.marketing_attainment_pct(commitment, 0),
            "portal_entitlement_level": "BASIC",
            "open_conflict_count": 0,
            "standing_reason": None,
        }
        store.insert("partners", row)
        calc.recompute_entitlement(row)
        return created(serialize.partner(row))

    @app.route("/partners", methods=["GET"])
    @endpoint("ChannelOpsAnalyst", "ChannelDirector", "DirectSalesRep")
    def list_partners():
        rows = store.ordered(store.all_rows("partners"))
        rows = filtered(rows, [("tier", "tier"),
                               ("tier_status", "tier_status"),
                               ("partner_type", "partner_type")])
        return listing(rows, serialize.partner)

    @app.route("/partners/<partner_id>", methods=["GET"])
    @endpoint("ChannelOpsAnalyst", "ChannelDirector", "DirectSalesRep", "Partner")
    def read_partner(partner_id):
        partner = find_partner(partner_id)
        return object_response(serialize.partner(partner))

    @app.route("/partners/<partner_id>", methods=["PATCH"])
    @endpoint("ChannelOpsAnalyst")
    def patch_partner(partner_id):
        partner = find_partner(partner_id)
        body = v.body()
        company_name = v.opt_string(body, "company_name", max_len=MAX_NAME_LEN)
        commitment = v.opt_int(body, "marketing_commitment_cents", minimum=0)
        if company_name is not None:
            partner["company_name"] = company_name
        if commitment is not None:
            partner["marketing_commitment_cents"] = commitment
        calc.recompute_marketing(partner)
        calc.recompute_entitlement(partner)
        store.touch(partner)
        return object_response(serialize.partner(partner))

    # ----------------------------------------------------- CertificationRecord
    @app.route("/partners/<partner_id>/certifications", methods=["POST"])
    @endpoint("ChannelOpsAnalyst")
    def create_certification(partner_id):
        partner = find_partner(partner_id)
        body = v.body()
        engineer_name = v.req_string(body, "engineer_name")
        track = v.req_enum(body, "track", TRACKS)
        issued_at = v.req_instant(body, "issued_at")
        expires_at = v.req_instant(body, "expires_at")
        v.interval(issued_at, expires_at, "issued_at", "expires_at")
        row = {
            "partner_id": partner["id"],
            "engineer_name": engineer_name,
            "track": track,
            "credit_weight": CERT_CREDIT_WEIGHT[track],
            "status": "ACTIVE",
            "issued_at": issued_at,
            "expires_at": expires_at,
        }
        store.insert("certifications", row)
        calc.recompute_cert_credits(partner)
        store.touch(partner)
        return created(serialize.certification(row))

    @app.route("/partners/<partner_id>/certifications", methods=["GET"])
    @endpoint("ChannelOpsAnalyst", "ChannelDirector", "Partner")
    def list_partner_certifications(partner_id):
        partner = find_partner(partner_id)
        rows = [r for r in store.ordered(store.all_rows("certifications"))
                if r["partner_id"] == partner["id"]]
        rows = filtered(rows, [("status", "status")])
        return listing(rows, serialize.certification)

    @app.route("/certifications", methods=["GET"])
    @endpoint("ChannelOpsAnalyst", "ChannelDirector")
    def list_certifications():
        rows = store.ordered(store.all_rows("certifications"))
        rows = filtered(rows, [("partner_id", "partner_id"),
                               ("status", "status"),
                               ("track", "track")])
        return listing(rows, serialize.certification)

    @app.route("/certifications/<certification_id>", methods=["GET"])
    @endpoint("ChannelOpsAnalyst", "ChannelDirector", "Partner")
    def read_certification(certification_id):
        row = find("certifications", certification_id)
        return object_response(serialize.certification(row))
