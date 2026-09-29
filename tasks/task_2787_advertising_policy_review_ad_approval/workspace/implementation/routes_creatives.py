"""Ad creative authoring and its two independent state axes.

The review axis (PRD 3.3, 3.4, 3.7) and the destination axis (PRD 3.8) advance
on different triggers from different roles and are read together by the serving
eligibility gate of PRD 2.11.
"""

from decimal import Decimal

from flask import Blueprint, request

import calc
import services as svc
from core import (D, EVIDENCE_COMMON, MUTABLE_COMMON, ROLE_ADMIN, ROLE_ADVERTISER,
                  ROLE_ANALYST, authenticate, bool_arg, db, fail, new_row, now, ok,
                  ok_list, oldest_first, pagination, paginate, q2, touch)
from validate import (bad, body_or_empty, read_body, v_array, v_bool, v_int, v_id,
                      v_enum, v_string, v_url, el_country, v_decimal2)

bp = Blueprint("creatives", __name__)

CREATIVE_FIELDS = ("headline", "body_text", "declared_category_codes",
                   "target_country_codes", "landing_page_url", "display_url",
                   "political_flag", "disclaimer_text")


def _el_category_code(value, key):
    if not isinstance(value, str) or len(value) < 1 or len(value) > 40:
        bad("%s elements must be policy codes of 1..40 characters." % key)


def _scope_creative(user_id, role, creative_id):
    """Priority 3 scope check: resolved leniently so that an unresolvable id
    still reports its own 404 at priority 6."""
    creative = db.ad_creatives.get(creative_id)
    if creative is not None and role == ROLE_ADVERTISER \
            and creative["advertiser_id"] != user_id:
        fail("ERR_ADVERTISER_SCOPE_VIOLATION", 403)
    return creative


def _resolve_declared_codes(codes):
    """PRD 2.5: every element of declared_category_codes must match the code of
    an existing policy rule."""
    for code in codes:
        if calc.rule_by_code(code) is None:
            fail("ERR_POLICY_RULE_NOT_FOUND", 404)


# ==========================================================================
# authoring, revision, submission and withdrawal
# ==========================================================================
@bp.route("/ad-creatives", methods=["POST"])
def create_ad_creative():
    user_id, role = authenticate(ROLE_ADVERTISER)
    pre = body_or_empty()
    if isinstance(pre.get("advertiser_id"), str) and pre["advertiser_id"] != user_id:
        fail("ERR_ADVERTISER_SCOPE_VIOLATION", 403)
    data = read_body(("advertiser_id",) + CREATIVE_FIELDS,
                     ("advertiser_id", "headline", "body_text",
                      "declared_category_codes", "target_country_codes",
                      "landing_page_url", "display_url"))
    advertiser_id = v_id(data, "advertiser_id")
    headline = v_string(data, "headline", 1, 200)
    body_text = v_string(data, "body_text", 1, 2000)
    codes = v_array(data, "declared_category_codes", no_duplicates=False,
                    element=_el_category_code)
    countries = v_array(data, "target_country_codes", element=el_country)
    landing_page_url = v_url(data, "landing_page_url")
    display_url = v_url(data, "display_url")
    political_flag = v_bool(data, "political_flag", False)
    disclaimer_text = v_string(data, "disclaimer_text", 1, 300,
                               required=False, nullable=True)
    advertiser = svc.get_advertiser(advertiser_id)
    _resolve_declared_codes(codes)
    # priority 12 then priority 27
    if advertiser["account_status"] == "SUSPENDED":
        fail("ERR_ADVERTISER_SUSPENDED", 409)
    if advertiser["account_status"] == "RESTRICTED":
        if political_flag:
            fail("ERR_ADVERTISER_RESTRICTED_CATEGORY", 409)
        for code in codes:
            rule = calc.rule_by_code(code)
            if rule["category_class"] in ("PROHIBITED", "RESTRICTED"):
                fail("ERR_ADVERTISER_RESTRICTED_CATEGORY", 409)
    row = new_row(MUTABLE_COMMON)
    row.update({
        "advertiser_id": advertiser["id"],
        "headline": headline,
        "body_text": body_text,
        "declared_category_codes": list(codes),
        "target_country_codes": list(countries),
        "landing_page_url": landing_page_url,
        "display_url": display_url,
        "political_flag": political_flag,
        "disclaimer_text": disclaimer_text,
        "review_status": "DRAFT",
        "destination_status": "NOT_CHECKED",
        "risk_score_provisional": Decimal("0.00"),
        "risk_score_final": Decimal("0.00"),
        "serving_eligible": False,
        "blocking_reason_codes": [],
        "limited_country_codes": [],
        "approved_under_certification_id": None,
        "screening_run_count": 0,
    })
    db.ad_creatives[row["id"]] = row
    svc.recompute_gate(row, advertiser, bump=False)
    return ok(svc.s_ad_creative(row), 201)


@bp.route("/ad-creatives", methods=["GET"])
def list_ad_creatives():
    authenticate()
    limit, offset = pagination()
    rows = list(db.ad_creatives.values())
    for key in ("advertiser_id", "review_status", "destination_status",
                "approved_under_certification_id"):
        value = request.args.get(key)
        if value is not None:
            rows = [r for r in rows if r[key] == value]
    political = bool_arg("political_flag")
    if political is not None:
        rows = [r for r in rows if r["political_flag"] == political]
    page, total = paginate(oldest_first(rows), limit, offset)
    return ok_list([svc.s_ad_creative(r) for r in page], limit, offset, total)


@bp.route("/ad-creatives/<creative_id>", methods=["GET"])
def read_ad_creative(creative_id):
    authenticate()
    return ok(svc.s_ad_creative(svc.get_creative(creative_id)))


@bp.route("/ad-creatives/<creative_id>", methods=["PATCH"])
def revise_ad_creative(creative_id):
    user_id, role = authenticate(ROLE_ADVERTISER)
    _scope_creative(user_id, role, creative_id)
    data = read_body(CREATIVE_FIELDS)
    headline = v_string(data, "headline", 1, 200, required=False)
    body_text = v_string(data, "body_text", 1, 2000, required=False)
    codes = v_array(data, "declared_category_codes", required=False,
                    no_duplicates=False, element=_el_category_code)
    countries = v_array(data, "target_country_codes", required=False,
                        element=el_country)
    landing_page_url = v_url(data, "landing_page_url", required=False)
    display_url = v_url(data, "display_url", required=False)
    political_flag = v_bool(data, "political_flag")
    disclaimer_given = "disclaimer_text" in data
    disclaimer_text = v_string(data, "disclaimer_text", 1, 300,
                               required=False, nullable=True)
    creative = svc.get_creative(creative_id)
    if codes is not None:
        _resolve_declared_codes(codes)
    if creative["review_status"] not in ("DRAFT", "DISAPPROVED"):
        fail("ERR_INVALID_CREATIVE_STATE", 409)
    advertiser = svc.get_advertiser(creative["advertiser_id"])
    if advertiser["account_status"] == "SUSPENDED":
        fail("ERR_ADVERTISER_SUSPENDED", 409)
    if headline is not None:
        creative["headline"] = headline
    if body_text is not None:
        creative["body_text"] = body_text
    if codes is not None:
        creative["declared_category_codes"] = list(codes)
    if countries is not None:
        creative["target_country_codes"] = list(countries)
    if landing_page_url is not None:
        creative["landing_page_url"] = landing_page_url
    if display_url is not None:
        creative["display_url"] = display_url
    if political_flag is not None:
        creative["political_flag"] = political_flag
    if disclaimer_given:
        creative["disclaimer_text"] = disclaimer_text
    # a revision from DISAPPROVED returns the creative to DRAFT
    creative["review_status"] = "DRAFT"
    creative["destination_status"] = "NOT_CHECKED"
    creative["risk_score_provisional"] = Decimal("0.00")
    creative["risk_score_final"] = Decimal("0.00")
    creative["limited_country_codes"] = []
    creative["approved_under_certification_id"] = None
    svc.expire_queued_tasks(creative)
    svc.recompute_gate(creative, advertiser, bump=False)
    touch(creative)
    return ok(svc.s_ad_creative(creative))


@bp.route("/ad-creatives/<creative_id>/submit", methods=["POST"])
def submit_ad_creative(creative_id):
    user_id, role = authenticate(ROLE_ADVERTISER)
    _scope_creative(user_id, role, creative_id)
    read_body(())
    creative = svc.get_creative(creative_id)
    _resolve_declared_codes(creative["declared_category_codes"])
    if creative["review_status"] != "DRAFT":
        fail("ERR_INVALID_CREATIVE_STATE", 409)
    advertiser = svc.get_advertiser(creative["advertiser_id"])
    if advertiser["account_status"] == "SUSPENDED":
        fail("ERR_ADVERTISER_SUSPENDED", 409)
    creative["review_status"] = "SCREENING"
    if creative["destination_status"] == "NOT_CHECKED":
        creative["destination_status"] = "DESTINATION_PENDING"
    svc.recompute_gate(creative, advertiser, bump=False)
    touch(creative)
    return ok(svc.s_ad_creative(creative))


@bp.route("/ad-creatives/<creative_id>/withdraw", methods=["POST"])
def withdraw_ad_creative(creative_id):
    user_id, role = authenticate(ROLE_ADVERTISER)
    _scope_creative(user_id, role, creative_id)
    read_body(())
    creative = svc.get_creative(creative_id)
    if creative["review_status"] == "WITHDRAWN":
        fail("ERR_INVALID_CREATIVE_STATE", 409)
    svc.expire_open_tasks(creative)
    creative["review_status"] = "WITHDRAWN"
    svc.recompute_gate(creative, svc.owner_of(creative), bump=False)
    touch(creative)
    return ok(svc.s_ad_creative(creative))


# ==========================================================================
# automated pre-approval screening (PRD 3.4)
# ==========================================================================
DECISION_KEYS = ("policy_rule_id", "confidence", "matched_snippet")


def _el_decision(value, key):
    if not isinstance(value, dict):
        bad("%s elements must be objects." % key)
    for name in value.keys():
        if name not in DECISION_KEYS:
            bad("Unknown field in %s element: %s" % (key, name))
    for name in DECISION_KEYS:
        if name not in value or value[name] is None:
            bad("Missing required field in %s element: %s" % (key, name))
    v_id(value, "policy_rule_id")
    v_string(value, "matched_snippet", 1, 300)
    v_decimal2(value, "confidence", "0.01", "1.00")


@bp.route("/ad-creatives/<creative_id>/screening-runs", methods=["POST"])
def ingest_screening_run(creative_id):
    authenticate(ROLE_ADMIN)
    data = read_body(("ad_creative_id", "classifier_version", "decisions",
                      "expected_ad_creative_version"),
                     ("classifier_version", "decisions", "expected_ad_creative_version"))
    classifier_version = v_string(data, "classifier_version", 1, 40)
    decisions = v_array(data, "decisions", no_duplicates=False, element=_el_decision)
    expected = v_int(data, "expected_ad_creative_version", 0, None)
    if expected is None:
        bad("expected_ad_creative_version is required.")
    body_creative_id = v_id(data, "ad_creative_id", required=False)
    creative = svc.get_creative(creative_id)
    if body_creative_id is not None and body_creative_id not in db.ad_creatives:
        fail("ERR_AD_CREATIVE_NOT_FOUND", 404)
    # PRD 2.5: decision rules resolve in submitted order; the first miss
    # rejects the whole run, leaving no run and no decisions behind
    rules = []
    for element in decisions:
        rule = db.policy_rules.get(element["policy_rule_id"])
        if rule is None:
            fail("ERR_POLICY_RULE_NOT_FOUND", 404)
        rules.append(rule)
    if creative["review_status"] != "SCREENING":
        fail("ERR_INVALID_CREATIVE_STATE", 409)
    if expected != creative["version"]:
        fail("ERR_STALE_CREATIVE_VERSION", 412)
    advertiser = svc.get_advertiser(creative["advertiser_id"])
    highest = 0
    for existing in calc.runs_for(creative):
        if existing["sequence_index"] > highest:
            highest = existing["sequence_index"]
    run = new_row(EVIDENCE_COMMON)
    run.update({
        "ad_creative_id": creative["id"],
        "classifier_version": classifier_version,
        "sequence_index": highest + 1,
        "outcome": None,
        "decision_count": 0,
        "max_confidence": Decimal("0.00"),
        "provisional_risk_score": Decimal("0.00"),
        "creative_version_at_run": creative["version"],
    })
    db.screening_runs[run["id"]] = run
    decision_rows = []
    top_confidence = Decimal("0.00")
    for element, rule in zip(decisions, rules):
        confidence = q2(D(str(element["confidence"])))
        multiplier = calc.country_multiplier(rule, creative)
        row = new_row(EVIDENCE_COMMON)
        row.update({
            "screening_run_id": run["id"],
            "policy_rule_id": rule["id"],
            "confidence": confidence,
            "matched_snippet": element["matched_snippet"],
            "disposition": calc.decision_disposition(rule, confidence),
            "country_multiplier_applied": multiplier,
            "assessed_points": q2(rule["base_severity_weight"] * multiplier * confidence),
        })
        db.classifier_decisions[row["id"]] = row
        decision_rows.append(row)
        if confidence > top_confidence:
            top_confidence = confidence
    run["decision_count"] = len(decision_rows)
    run["max_confidence"] = top_confidence
    creative["screening_run_count"] += 1
    creative["risk_score_provisional"] = calc.provisional_risk_score(creative)
    run["provisional_risk_score"] = creative["risk_score_provisional"]
    outcome = calc.screening_outcome(creative, advertiser, decision_rows)
    run["outcome"] = outcome
    if outcome == "AUTO_APPROVED":
        creative["review_status"] = "AUTO_APPROVED"
    elif outcome == "ROUTED_MANUAL":
        creative["review_status"] = "PENDING_MANUAL_REVIEW"
        queue, primary_rule_id = calc.screening_route(creative, decision_rows)
        svc.create_review_task(creative, queue, primary_rule_id, 0)
    else:
        creative["review_status"] = "DISAPPROVED"
        svc.write_risk_final(creative)
        svc.issue_notice(creative, ["AUTO_SCREENING"], None)
    svc.write_risk_final(creative)
    svc.recompute_gate(creative, advertiser, bump=False)
    touch(creative)
    return ok(svc.s_screening_run(run), 201)


@bp.route("/ad-creatives/<creative_id>/screening-runs", methods=["GET"])
def list_creative_screening_runs(creative_id):
    authenticate()
    limit, offset = pagination()
    creative = svc.get_creative(creative_id)
    rows = calc.runs_for(creative)
    rows.sort(key=lambda r: r["sequence_index"])
    page, total = paginate(rows, limit, offset)
    return ok_list([svc.s_screening_run(r) for r in page], limit, offset, total)


@bp.route("/screening-runs/<run_id>", methods=["GET"])
def read_screening_run(run_id):
    authenticate()
    return ok(svc.s_screening_run(svc.get_screening_run(run_id)))


@bp.route("/screening-runs/<run_id>/classifier-decisions", methods=["GET"])
def list_run_classifier_decisions(run_id):
    authenticate()
    limit, offset = pagination()
    run = svc.get_screening_run(run_id)
    rows = [d for d in db.classifier_decisions.values()
            if d["screening_run_id"] == run["id"]]
    page, total = paginate(oldest_first(rows), limit, offset)
    return ok_list([svc.s_classifier_decision(r) for r in page], limit, offset, total)


# ==========================================================================
# destination and landing-page integrity (PRD 3.8)
# ==========================================================================
@bp.route("/ad-creatives/<creative_id>/destination-checks", methods=["POST"])
def create_destination_check(creative_id):
    authenticate(ROLE_ANALYST)
    data = read_body(("ad_creative_id", "check_type", "user_agent_variant",
                      "fetched_final_url", "fetched_content_category", "http_status"),
                     ("check_type", "user_agent_variant", "fetched_final_url",
                      "fetched_content_category", "http_status"))
    check_type = v_enum(data, "check_type", ("INITIAL", "RECHECK"))
    variant = v_enum(data, "user_agent_variant", ("CRAWLER", "USER"))
    final_url = v_url(data, "fetched_final_url")
    category = v_string(data, "fetched_content_category", 1, 40)
    http_status = v_int(data, "http_status", 100, 599)
    if http_status is None:
        bad("http_status is required.")
    body_creative_id = v_id(data, "ad_creative_id", required=False)
    creative = svc.get_creative(creative_id)
    if body_creative_id is not None and body_creative_id not in db.ad_creatives:
        fail("ERR_AD_CREATIVE_NOT_FOUND", 404)
    if creative["review_status"] in ("DRAFT", "WITHDRAWN"):
        fail("ERR_INVALID_CREATIVE_STATE", 409)
    if category != "GENERAL" and calc.rule_by_code(category) is None:
        fail("ERR_UNKNOWN_POLICY_CATEGORY", 422)
    # the reference crawler check is an *earlier* check, so derive before insert
    result, detail = calc.destination_check_result(
        creative, check_type, variant, final_url, category, http_status)
    row = new_row(EVIDENCE_COMMON)
    row.update({
        "ad_creative_id": creative["id"],
        "check_type": check_type,
        "user_agent_variant": variant,
        "fetched_final_url": final_url,
        "fetched_content_category": category,
        "http_status": http_status,
        "result": result,
        "mismatch_detail": detail,
    })
    db.destination_checks[row["id"]] = row
    previous_review = creative["review_status"]
    if result == "CLEARED":
        creative["destination_status"] = "DESTINATION_CLEARED"
    elif result == "MISMATCH":
        creative["destination_status"] = "MISMATCH_FLAGGED"
    else:
        creative["destination_status"] = "CLOAKING_CONFIRMED"
    if result == "MISMATCH" and previous_review in ("AUTO_APPROVED", "APPROVED_LIMITED"):
        creative["review_status"] = "PENDING_MANUAL_REVIEW"
        svc.create_review_task(creative, "STANDARD", None, 0)
    elif result == "CLOAKING" and previous_review in (
            "AUTO_APPROVED", "APPROVED_LIMITED", "PENDING_MANUAL_REVIEW"):
        creative["review_status"] = "DISAPPROVED"
        svc.expire_open_tasks(creative)
        svc.write_risk_final(creative)
        svc.issue_notice(creative, ["CLOAKING"], None)
    svc.write_risk_final(creative)
    svc.recompute_gate(creative, svc.owner_of(creative), bump=False)
    touch(creative)
    return ok(svc.s_destination_check(row), 201)


@bp.route("/ad-creatives/<creative_id>/destination-checks", methods=["GET"])
def list_destination_checks(creative_id):
    authenticate()
    limit, offset = pagination()
    creative = svc.get_creative(creative_id)
    rows = [c for c in db.destination_checks.values()
            if c["ad_creative_id"] == creative["id"]]
    page, total = paginate(oldest_first(rows), limit, offset)
    return ok_list([svc.s_destination_check(r) for r in page], limit, offset, total)


@bp.route("/ad-creatives/<creative_id>/political-archive-entries", methods=["GET"])
def list_creative_archive_entries(creative_id):
    authenticate()
    limit, offset = pagination()
    creative = svc.get_creative(creative_id)
    rows = [e for e in db.political_archive_entries.values()
            if e["ad_creative_id"] == creative["id"]]
    rows.sort(key=lambda e: (e["archived_at"], e["_seq"]))
    page, total = paginate(rows, limit, offset)
    return ok_list([svc.s_political_archive_entry(r) for r in page], limit, offset, total)
