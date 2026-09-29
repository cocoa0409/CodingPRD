"""Routes: networks, affiliate registration / reads / status changes, and the
affiliate application screening workflow (PRD 3.1 and 3.2)."""

import calc
import serializers as S
import services as SV
from common import (
    AFFILIATE_STATUSES, AFFILIATE_TARGET_STATUSES, CURRENCIES, DECISIONS,
    FEE_MODELS, INCREMENTALITY_TIERS, PARTNER_TYPES, PRODUCT_CATEGORIES,
    PROMO_METHODS, ROLE_COMPLIANCE, ROLE_PARTNER, ROLE_PARTNER_MANAGER,
    ROLE_PROGRAM_ADMIN, SCREENING_OUTCOMES, TAX_DOC_STATES, TRAFFIC_SOURCES,
    APPLICATION_STATES, authorize, body, db, fail, fmt_dt, get_bool, get_enum,
    get_enum_list, get_id, get_int, get_instant, get_str, get_str_list, g,
    new_row, opt_raw, ordered, paginate, query_filter, require_owner,
    respond, touch,
)


def register(app):

    # -- Network ------------------------------------------------------------

    @app.post("/networks")
    def create_network():
        authorize([ROLE_PROGRAM_ADMIN])
        payload = body()
        name = get_str(payload, "name", min_len=1, max_len=120)
        fee_model = get_enum(payload, "fee_model", FEE_MODELS)
        fee_bps = get_int(payload, "fee_bps", min_v=0, max_v=3000)
        flat_fee_cents = get_int(payload, "flat_fee_cents", min_v=0, max_v=1000)
        statement_currency = get_enum(payload, "statement_currency", CURRENCIES)
        for row in db.networks.values():
            if row["name"] == name:
                fail("ERR_INVALID_REQUEST", "name is already registered")
        if fee_model == "FLAT_PER_CONVERSION" and fee_bps != 0:
            fail("ERR_INVALID_REQUEST",
                 "fee_bps must be 0 when fee_model is FLAT_PER_CONVERSION")
        if fee_model == "PERCENT_OF_COMMISSION" and flat_fee_cents != 0:
            fail("ERR_INVALID_REQUEST",
                 "flat_fee_cents must be 0 when fee_model is PERCENT_OF_COMMISSION")
        row = new_row(
            name=name, fee_model=fee_model, fee_bps=fee_bps,
            flat_fee_cents=flat_fee_cents, statement_currency=statement_currency,
        )
        db.networks[row["id"]] = row
        return respond(S.network_out(row), 201)

    @app.get("/networks/<nid>")
    def get_network(nid):
        authorize([ROLE_PROGRAM_ADMIN, "FinanceAnalyst", "FinanceController"])
        return respond(S.network_out(SV.find_network(nid)))

    # -- Affiliate ----------------------------------------------------------

    @app.post("/affiliates")
    def create_affiliate():
        authorize(["Anonymous", ROLE_PROGRAM_ADMIN, ROLE_PARTNER_MANAGER],
                  anonymous_route=True)
        payload = body()
        # Rule 3 then rule 11: owner references resolve before body validation.
        parent = None
        parent_raw = opt_raw(payload, "parent_affiliate_id")
        if parent_raw is not None:
            parent = SV.find_affiliate(parent_raw)
        network_raw = opt_raw(payload, "network_id")
        if network_raw is not None:
            SV.find_network(network_raw)
        legal_name = get_str(payload, "legal_name", min_len=1, max_len=160)
        contact_email = get_str(payload, "contact_email", min_len=1)
        if "@" not in contact_email:
            fail("ERR_INVALID_REQUEST", "contact_email must contain @")
        partner_type = get_enum(payload, "partner_type", PARTNER_TYPES)
        network_id = get_id(payload, "network_id")
        payout_currency = get_enum(payload, "payout_currency", CURRENCIES)
        for row in db.affiliates.values():
            if row["contact_email"] == contact_email:
                fail("ERR_INVALID_REQUEST", "contact_email is already registered")
        depth = 0 if parent is None else parent["sub_affiliate_depth"] + 1
        if depth > calc.MAX_SUB_AFFILIATE_DEPTH:
            fail("ERR_SUB_AFFILIATE_DEPTH_EXCEEDED",
                 "sub-affiliate nesting is limited to one level")
        if parent is not None and parent["partner_type"] != "SUB_NETWORK":
            fail("ERR_CIRCULAR_SUB_AFFILIATE",
                 "parent_affiliate_id must name a SUB_NETWORK partner")
        row = new_row(
            legal_name=legal_name, contact_email=contact_email,
            partner_type=partner_type, network_id=network_id,
            parent_affiliate_id=None if parent is None else parent["id"],
            sub_affiliate_depth=depth, payout_currency=payout_currency,
            status="PENDING_APPLICATION", suspension_cause="NONE",
            fraud_risk_score=0, fraud_risk_score_trailing=0.0,
            incrementality_score_bps=0, incrementality_tier="MEDIUM",
            attributed_conversion_count=0, new_customer_attributed_count=0,
            coupon_assisted_conversion_count=0, accrued_balance_cents=0,
            reserved_balance_cents=0, lifetime_paid_cents=0,
            tax_document_status="NONE", open_violation_case_count=0,
            tracking_link_count=0,
        )
        SV.recompute_incrementality(row)
        db.affiliates[row["id"]] = row
        return respond(S.affiliate_out(row), 201)

    @app.get("/affiliates/<aid>")
    def get_affiliate(aid):
        authorize([ROLE_PROGRAM_ADMIN, ROLE_PARTNER_MANAGER, ROLE_COMPLIANCE,
                   "FinanceAnalyst", "FinanceController", ROLE_PARTNER])
        row = SV.find_affiliate(aid)
        require_owner(row["id"])
        return respond(S.affiliate_out(row))

    @app.get("/affiliates")
    def list_affiliates():
        authorize([ROLE_PROGRAM_ADMIN, ROLE_PARTNER_MANAGER, ROLE_COMPLIANCE,
                   "FinanceAnalyst", "FinanceController"])
        rows = ordered(db.affiliates)
        rows = query_filter(rows, "status")
        rows = query_filter(rows, "partner_type")
        rows = query_filter(rows, "network_id")
        rows = query_filter(rows, "parent_affiliate_id")
        rows = query_filter(rows, "incrementality_tier")
        return paginate(rows, S.affiliate_out)

    @app.post("/affiliates/<aid>/status-change")
    def change_affiliate_status(aid):
        role = authorize([ROLE_PROGRAM_ADMIN, ROLE_COMPLIANCE])[1]
        payload = body()
        # Suspension is exclusive to ComplianceAnalyst; reinstatement and
        # termination are exclusive to ProgramAdmin (PRD 2.1 / 3.7).
        requested = payload.get("target_status")
        if requested == "SUSPENDED" and role != ROLE_COMPLIANCE:
            fail("ERR_UNAUTHORIZED", "only a ComplianceAnalyst may suspend")
        if requested in ("ACTIVE", "TERMINATED") and role != ROLE_PROGRAM_ADMIN:
            fail("ERR_UNAUTHORIZED",
                 "only a ProgramAdmin may reinstate or terminate")
        affiliate = SV.find_affiliate(aid)
        target = get_enum(payload, "target_status", AFFILIATE_TARGET_STATUSES)
        get_str(payload, "reason", min_len=1)
        if target == "SUSPENDED":
            if affiliate["status"] not in ("PENDING_APPLICATION", "ACTIVE"):
                fail("ERR_AFFILIATE_SUSPENDED",
                     "only a PENDING_APPLICATION or ACTIVE partner may be suspended")
            SV.suspend_cascade(affiliate, "COMPLIANCE_ACTION")
        elif target == "ACTIVE":
            if affiliate["status"] != "SUSPENDED":
                fail("ERR_AFFILIATE_SUSPENDED",
                     "only a SUSPENDED partner may be reinstated")
            if affiliate["open_violation_case_count"] != 0:
                fail("ERR_OPEN_VIOLATION_CASES",
                     "every violation case must be closed before reinstatement")
            if affiliate["fraud_risk_score_trailing"] >= float(
                    calc.REINSTATEMENT_TRAILING_CEILING):
                fail("ERR_RISK_SCORE_TOO_HIGH",
                     "trailing fraud score is at or above the reinstatement ceiling")
            parent_id = affiliate["parent_affiliate_id"]
            if parent_id is not None:
                parent = db.affiliates.get(parent_id)
                if parent is None or parent["status"] != "ACTIVE":
                    fail("ERR_AFFILIATE_SUSPENDED",
                         "the parent partner must be ACTIVE")
            affiliate["status"] = "ACTIVE"
            affiliate["suspension_cause"] = "NONE"
            touch(affiliate)
        else:
            if affiliate["status"] == "TERMINATED":
                fail("ERR_AFFILIATE_SUSPENDED", "the partner is already terminated")
            SV.terminate_affiliate(affiliate, "AFFILIATE_TERMINATED")
        return respond(S.affiliate_out(affiliate))

    @app.get("/affiliates/<aid>/monitoring-scans")
    def list_affiliate_scans(aid):
        authorize([ROLE_PROGRAM_ADMIN, ROLE_COMPLIANCE])
        affiliate = SV.find_affiliate(aid)
        rows = [r for r in ordered(db.scans)
                if r["affiliate_id"] == affiliate["id"]]
        rows = query_filter(rows, "engine")
        return paginate(rows, S.scan_out)

    @app.get("/affiliates/<aid>/tax-documents")
    def list_affiliate_tax_documents(aid):
        authorize([ROLE_PROGRAM_ADMIN, "FinanceAnalyst", "FinanceController",
                   ROLE_PARTNER])
        affiliate = SV.find_affiliate(aid)
        require_owner(affiliate["id"])
        rows = SV.tax_docs_of(affiliate["id"])
        rows = query_filter(rows, "status")
        return paginate(rows, S.tax_out)

    @app.get("/affiliates/<aid>/tracking-links")
    def list_affiliate_links(aid):
        authorize([ROLE_PROGRAM_ADMIN, ROLE_PARTNER_MANAGER, ROLE_COMPLIANCE,
                   ROLE_PARTNER])
        affiliate = SV.find_affiliate(aid)
        require_owner(affiliate["id"])
        rows = SV.links_of(affiliate["id"])
        rows = query_filter(rows, "status")
        return paginate(rows, S.link_out)
