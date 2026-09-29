"""Routes: affiliate applications (filing, screening, decision, resubmission)
and tax documents (PRD 3.2 and 3.8)."""

import calc
import serializers as S
import services as SV
from common import (
    DECISIONS, FORM_TYPES, PRODUCT_CATEGORIES, PROMO_METHODS, ROLE_COMPLIANCE,
    ROLE_PARTNER, ROLE_PARTNER_MANAGER, ROLE_PROGRAM_ADMIN, TRAFFIC_SOURCES,
    VERIFICATION_OUTCOMES, authorize, body, check_sod, db, fail, fmt_dt, g,
    get_enum, get_enum_list, get_int, get_instant, get_str, get_str_list,
    new_row, now_dt, ordered, paginate, parse_instant, query_filter,
    require_owner, respond, touch,
)

TERMINAL_APPLICATION_STATES = ("APPROVED", "APPROVED_WITH_CONDITIONS", "REJECTED")


def register(app):

    @app.post("/affiliates/<aid>/applications")
    def file_application(aid):
        authorize([ROLE_PROGRAM_ADMIN, ROLE_PARTNER_MANAGER, ROLE_PARTNER])
        affiliate = SV.find_affiliate(aid)
        require_owner(affiliate["id"])
        payload = body()
        site_url = get_str(payload, "site_url", min_len=1, prefix="https://")
        source = get_enum(payload, "primary_traffic_source", TRAFFIC_SOURCES)
        traffic = get_int(payload, "monthly_traffic_estimate", min_v=0)
        methods = get_enum_list(payload, "declared_promo_methods", PROMO_METHODS)
        categories = get_enum_list(payload, "product_categories",
                                   PRODUCT_CATEGORIES)
        if affiliate["status"] in ("SUSPENDED", "TERMINATED"):
            fail("ERR_AFFILIATE_SUSPENDED",
                 "a suspended or terminated partner may not file an application")
        for row in SV.applications_of(affiliate["id"]):
            if row["review_state"] not in TERMINAL_APPLICATION_STATES:
                fail("ERR_DUPLICATE_APPLICATION",
                     "an application is already in review for this partner")
        row = new_row(
            affiliate_id=affiliate["id"], site_url=site_url,
            primary_traffic_source=source, monthly_traffic_estimate=traffic,
            declared_promo_methods=methods, product_categories=categories,
            review_state="SUBMITTED", site_quality_score=None,
            brand_suitability_score=None, screening_outcome="NOT_SCREENED",
            screened_by_user_id=None, decided_by_user_id=None,
            revision_round_count=0, decision_notes=None,
            conditional_requirements=[],
        )
        db.applications[row["id"]] = row
        return respond(S.application_out(row), 201)

    @app.get("/affiliate-applications/<app_id>")
    def get_application(app_id):
        authorize([ROLE_PROGRAM_ADMIN, ROLE_PARTNER_MANAGER, ROLE_COMPLIANCE,
                   ROLE_PARTNER])
        return respond(S.application_out(SV.find_application(app_id)))

    @app.get("/affiliate-applications")
    def list_applications():
        authorize([ROLE_PROGRAM_ADMIN, ROLE_PARTNER_MANAGER, ROLE_COMPLIANCE])
        rows = ordered(db.applications)
        rows = query_filter(rows, "affiliate_id")
        rows = query_filter(rows, "review_state")
        rows = query_filter(rows, "screening_outcome")
        return paginate(rows, S.application_out)

    @app.post("/affiliate-applications/<app_id>/screen")
    def screen_application(app_id):
        authorize([ROLE_COMPLIANCE])
        application = SV.find_application(app_id)
        payload = body()
        domain_authority = get_int(payload, "domain_authority", min_v=0, max_v=100)
        originality = get_int(payload, "content_originality_pct", min_v=0,
                              max_v=100)
        broken = get_int(payload, "broken_link_ratio_bps", min_v=0, max_v=10000)
        flags = get_int(payload, "brand_safety_flag_count", min_v=0, max_v=20)
        overlap = get_int(payload, "restricted_vertical_overlap_bps", min_v=0,
                          max_v=10000)
        if application["review_state"] in TERMINAL_APPLICATION_STATES:
            fail("ERR_APPLICATION_TERMINAL",
                 "the application has already reached a terminal state")
        if application["review_state"] != "SUBMITTED":
            fail("ERR_APPLICATION_NOT_SCREENED",
                 "only a SUBMITTED application may be screened")
        affiliate = db.affiliates[application["affiliate_id"]]
        if affiliate["status"] != "PENDING_APPLICATION":
            fail("ERR_AFFILIATE_NOT_ELIGIBLE",
                 "the applicant partner is no longer pending application")
        application["site_quality_score"] = calc.site_quality_score(
            domain_authority, originality, broken, flags,
            application["primary_traffic_source"],
            application["declared_promo_methods"])
        application["brand_suitability_score"] = calc.brand_suitability_score(
            overlap, flags)
        application["screening_outcome"] = calc.screening_outcome(
            application["site_quality_score"],
            application["brand_suitability_score"])
        application["screened_by_user_id"] = g.user_id
        application["review_state"] = "SCREENED"
        touch(application)
        return respond(S.application_out(application))

    @app.post("/affiliate-applications/<app_id>/decide")
    def decide_application(app_id):
        authorize([ROLE_PARTNER_MANAGER])
        application = SV.find_application(app_id)
        payload = body()
        decision = get_enum(payload, "decision", DECISIONS)
        get_str(payload, "decision_notes", min_len=1)
        expected = get_int(payload, "expected_affiliate_version")
        conditions = get_str_list(payload, "conditional_requirements",
                                  required=False, non_empty=False, default=None)
        check_sod(application["screened_by_user_id"],
                  "the screening analyst may not decide the application")
        if application["review_state"] in TERMINAL_APPLICATION_STATES:
            fail("ERR_APPLICATION_TERMINAL",
                 "the application has already reached a terminal state")
        if application["review_state"] != "SCREENED":
            fail("ERR_APPLICATION_NOT_SCREENED",
                 "only a SCREENED application may be decided")
        affiliate = db.affiliates[application["affiliate_id"]]
        if affiliate["status"] != "PENDING_APPLICATION":
            fail("ERR_AFFILIATE_NOT_ELIGIBLE",
                 "the applicant partner is no longer pending application")
        for case in SV.cases_of(affiliate["id"]):
            if case["state"] == "UPHELD":
                fail("ERR_AFFILIATE_NOT_ELIGIBLE",
                     "an upheld violation case blocks any decision")
        if expected != affiliate["version"]:
            fail("ERR_STALE_AFFILIATE_VERSION",
                 "expected_affiliate_version does not match the partner version")
        if decision in ("APPROVE", "APPROVE_WITH_CONDITIONS"):
            score = application["brand_suitability_score"]
            if score is None or score < float(calc.BRAND_SUITABILITY_FLOOR):
                fail("ERR_BRAND_SUITABILITY_VIOLATION",
                     "brand suitability is below the approval floor")
        if decision == "REQUEST_CHANGES":
            if application["revision_round_count"] >= calc.MAX_REVISION_ROUNDS:
                fail("ERR_REVISION_LIMIT_REACHED",
                     "the revision limit has already been reached")
        if decision == "APPROVE":
            if application["screening_outcome"] != "PASS":
                fail("ERR_SCREENING_NOT_PASSED",
                     "an outright approval requires a PASS screening outcome")
        if decision == "APPROVE_WITH_CONDITIONS":
            if application["screening_outcome"] not in ("PASS", "CONDITIONAL"):
                fail("ERR_SCREENING_NOT_PASSED",
                     "a conditional approval requires PASS or CONDITIONAL")
            if not conditions:
                fail("ERR_SCREENING_NOT_PASSED",
                     "conditional_requirements must be a non-empty array")

        application["decision_notes"] = payload["decision_notes"]
        application["decided_by_user_id"] = g.user_id
        if decision == "APPROVE":
            application["review_state"] = "APPROVED"
            _activate_partner(affiliate)
        elif decision == "APPROVE_WITH_CONDITIONS":
            application["review_state"] = "APPROVED_WITH_CONDITIONS"
            application["conditional_requirements"] = conditions
            _activate_partner(affiliate)
        elif decision == "REQUEST_CHANGES":
            application["review_state"] = "CHANGES_REQUESTED"
        else:
            application["review_state"] = "REJECTED"
            SV.terminate_affiliate(affiliate, "APPLICATION_REJECTED")
        touch(application)
        return respond(S.application_out(application))

    @app.post("/affiliate-applications/<app_id>/resubmit")
    def resubmit_application(app_id):
        authorize([ROLE_PARTNER, ROLE_PROGRAM_ADMIN])
        application = SV.find_application(app_id)
        require_owner(application["affiliate_id"])
        payload = body()
        site_url = get_str(payload, "site_url", min_len=1, prefix="https://")
        source = get_enum(payload, "primary_traffic_source", TRAFFIC_SOURCES)
        methods = get_enum_list(payload, "declared_promo_methods", PROMO_METHODS)
        affiliate = db.affiliates[application["affiliate_id"]]
        if affiliate["status"] in ("SUSPENDED", "TERMINATED"):
            fail("ERR_AFFILIATE_SUSPENDED",
                 "a suspended or terminated partner may not resubmit")
        if application["review_state"] in TERMINAL_APPLICATION_STATES:
            fail("ERR_APPLICATION_TERMINAL",
                 "the application has already reached a terminal state")
        if application["review_state"] != "CHANGES_REQUESTED":
            fail("ERR_APPLICATION_NOT_SCREENED",
                 "only an application with changes requested may be resubmitted")
        if application["revision_round_count"] >= calc.MAX_REVISION_ROUNDS:
            fail("ERR_REVISION_LIMIT_REACHED",
                 "the revision limit has already been reached")
        application["site_url"] = site_url
        application["primary_traffic_source"] = source
        application["declared_promo_methods"] = methods
        application["revision_round_count"] += 1
        application["site_quality_score"] = None
        application["brand_suitability_score"] = None
        application["screened_by_user_id"] = None
        application["screening_outcome"] = "NOT_SCREENED"
        application["review_state"] = "SUBMITTED"
        touch(application)
        return respond(S.application_out(application))

    # -- Tax documents ------------------------------------------------------

    @app.post("/affiliates/<aid>/tax-documents")
    def file_tax_document(aid):
        authorize([ROLE_PROGRAM_ADMIN, "FinanceController", ROLE_PARTNER])
        affiliate = SV.find_affiliate(aid)
        require_owner(affiliate["id"])
        payload = body()
        form_type = get_enum(payload, "form_type", FORM_TYPES)
        last4 = get_str(payload, "tax_id_last4", exact_len=4)
        treaty = get_int(payload, "treaty_withholding_bps", min_v=0, max_v=3000)
        expires_on = get_instant(payload, "expires_on")
        if form_type == "W9" and treaty != 0:
            fail("ERR_INVALID_REQUEST",
                 "a W9 must declare treaty_withholding_bps of 0")
        row = new_row(
            affiliate_id=affiliate["id"], form_type=form_type,
            tax_id_last4=last4, treaty_withholding_bps=treaty,
            expires_on=fmt_dt(expires_on), status="PENDING",
            verified_by_user_id=None,
        )
        db.tax_documents[row["id"]] = row
        SV.mirror_tax_status(row)
        return respond(S.tax_out(row), 201)

    @app.post("/tax-documents/<doc_id>/verify")
    def verify_tax_document(doc_id):
        authorize(["FinanceController"])
        document = SV.find_tax_document(doc_id)
        payload = body()
        outcome = get_enum(payload, "verification_outcome",
                           VERIFICATION_OUTCOMES)
        if document["status"] != "PENDING":
            fail("ERR_TAX_DOCUMENT_INVALID",
                 "only a PENDING document may be verified")
        if outcome == "VALID":
            expires = parse_instant(document["expires_on"])
            if expires is None or expires <= now_dt():
                fail("ERR_TAX_DOCUMENT_INVALID",
                     "the document expires at or before the current time")
            document["status"] = "VALID"
        else:
            document["status"] = "REJECTED"
        document["verified_by_user_id"] = g.user_id
        touch(document)
        SV.mirror_tax_status(document)
        return respond(S.tax_out(document))


def _activate_partner(affiliate):
    affiliate["status"] = "ACTIVE"
    SV.recompute_incrementality(affiliate)
    touch(affiliate)
