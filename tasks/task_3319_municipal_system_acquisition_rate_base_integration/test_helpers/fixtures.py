"""Composite setup helpers: multi-step state builders shared by tests.

Every fixture builds preconditions from scratch via public endpoints only.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .factories import (
    create_target_payload,
    create_assessment_payload,
    create_capital_item_payload,
    create_valuation_case_payload,
    create_valuation_entry_payload,
    create_council_event_payload,
    create_regulatory_application_payload,
    create_customer_account_payload,
    create_employee_transition_payload,
    create_tariff_case_payload,
)
from .test_users import TEST_USERS, make_headers

HEARING_START = "2026-09-02T00:00:00Z"
HEARING_END = "2026-09-02T02:00:00Z"
VOTE_DAY = "2026-09-10T00:00:00Z"
VOTE_START = "2026-09-10T03:00:00Z"
VOTE_END = "2026-09-10T04:00:00Z"

TRANSITION_ITEM_ORDER = ["BILLING_RECORDS", "DEPOSITS", "SERVICE_AGREEMENTS", "METER_READS"]


def create_target(**overrides):
    """Create an acquisition target. Returns the target dict."""
    resp = api_client.create_target(create_target_payload(**overrides),
                                    TEST_USERS["analyst_headers"])
    return get_success_data(resp)


def create_assessment_with_items(target_id, item_payloads, notes="survey",
                                 creator_user_id="analyst-1"):
    """Create a DRAFT assessment with the given capital items.
    Returns (assessment, [items])."""
    headers = make_headers(creator_user_id, "AcquisitionAnalyst")
    resp = api_client.create_assessment(target_id, create_assessment_payload(notes=notes),
                                        headers)
    assessment = get_success_data(resp)
    items = []
    for p in item_payloads:
        r = api_client.create_capital_item(assessment["id"], p, headers)
        items.append(get_success_data(r))
    return assessment, items


def submit_assessment(assessment_id, user_id="analyst-1"):
    headers = make_headers(user_id, "AcquisitionAnalyst")
    resp = api_client.submit_assessment(assessment_id, headers)
    return get_success_data(resp)


def accept_assessment(assessment_id, user_id="reviewer-1"):
    headers = make_headers(user_id, "EngineeringReviewer")
    resp = api_client.accept_assessment(assessment_id, headers)
    return get_success_data(resp)


def setup_target_in_valuation(item_payloads=None, **target_overrides):
    """Target advanced SCREENING -> VALUATION via an ACCEPTED assessment.
    Returns (target, assessment, items)."""
    if item_payloads is None:
        item_payloads = [create_capital_item_payload()]
    target = create_target(**target_overrides)
    assessment, items = create_assessment_with_items(target["id"], item_payloads)
    submit_assessment(assessment["id"])
    accept_assessment(assessment["id"])
    return target, assessment, items


def current_target_version(target_id):
    resp = api_client.get_target(target_id, TEST_USERS["analyst_headers"])
    return get_success_data(resp)["version"]


def open_valuation_case(target_id, analyst_user_id="analyst-1"):
    """Open a valuation case with a fresh OCC version. Returns the case."""
    version = current_target_version(target_id)
    headers = make_headers(analyst_user_id, "AcquisitionAnalyst")
    resp = api_client.create_valuation_case(
        target_id, create_valuation_case_payload(version), headers)
    return get_success_data(resp)


def submit_entry(case_id, value_cents=5000000, method="FMV_INDEPENDENT",
                 law_citation="66 Pa.C.S. 1329", appraiser_user_id="appraiser-1"):
    headers = make_headers(appraiser_user_id, "Appraiser")
    resp = api_client.create_valuation_entry(
        case_id,
        create_valuation_entry_payload(method=method, value_cents=value_cents,
                                       law_citation=law_citation),
        headers)
    return get_success_data(resp)


def finalize_case(case_id, select_entry_id, analyst_user_id="analyst-1"):
    headers = make_headers(analyst_user_id, "AcquisitionAnalyst")
    resp = api_client.finalize_valuation_case(case_id, {"select_entry_id": select_entry_id},
                                              headers)
    return get_success_data(resp)


def setup_target_in_municipal_review(entry_value_cents=5000000, **target_overrides):
    """Target in MUNICIPAL_REVIEW with a FINALIZED valuation case.
    Returns dict with target, assessment, items, case, entry."""
    target, assessment, items = setup_target_in_valuation(**target_overrides)
    case = open_valuation_case(target["id"])
    entry = submit_entry(case["id"], value_cents=entry_value_cents)
    finalize_case(case["id"], entry["id"])
    return {"target": target, "assessment": assessment, "items": items,
            "case": case, "entry": entry}


def schedule_event(target_id, kind, start, end, clerk_user_id="clerk-1"):
    headers = make_headers(clerk_user_id, "MunicipalClerk")
    resp = api_client.create_council_event(
        target_id, create_council_event_payload(kind=kind, scheduled_start=start,
                                                scheduled_end=end), headers)
    return get_success_data(resp)


def record_outcome(event_id, payload=None, clerk_user_id="clerk-1"):
    headers = make_headers(clerk_user_id, "MunicipalClerk")
    resp = api_client.record_council_outcome(event_id, payload or {}, headers)
    return resp


def set_clock(to_iso8601):
    resp = api_client.set_clock(to_iso8601, TEST_USERS["sysadmin_headers"])
    return get_success_data(resp)


def setup_hearing_held(target_id, start=HEARING_START, end=HEARING_END):
    """Schedule a PUBLIC_HEARING and record it HELD. Returns the event."""
    hearing = schedule_event(target_id, "PUBLIC_HEARING", start, end)
    get_success_data(record_outcome(hearing["id"]))
    return hearing


def pass_council_vote(target_id, yes=3, no=2, vote_start=VOTE_START, vote_end=VOTE_END,
                      advance_clock_to=VOTE_DAY):
    """Advance the clock past the hearing-notice window and record a passing vote."""
    set_clock(advance_clock_to)
    vote = schedule_event(target_id, "COUNCIL_VOTE", vote_start, vote_end)
    resp = record_outcome(vote["id"], {"yes_votes": yes, "no_votes": no})
    return get_success_data(resp)


def file_application(target_id, purchase_price_cents=5000000, rate_base_method="AS_PAID",
                     ocld_cents=None, officer_user_id="regofficer-1"):
    headers = make_headers(officer_user_id, "RegulatoryOfficer")
    payload = create_regulatory_application_payload(
        purchase_price_cents=purchase_price_cents, rate_base_method=rate_base_method)
    if ocld_cents is not None:
        payload["original_cost_less_depreciation_cents"] = ocld_cents
    resp = api_client.create_regulatory_application(target_id, payload, headers)
    return get_success_data(resp)


def decide_application(application_id, outcome, commissioner_user_id="commissioner-1"):
    headers = make_headers(commissioner_user_id, "Commissioner")
    resp = api_client.decide_regulatory_application(application_id, {"outcome": outcome},
                                                    headers)
    return get_success_data(resp)


def setup_target_in_regulatory_review(purchase_price_cents=5000000,
                                      rate_base_method="AS_PAID",
                                      ocld_cents=None,
                                      entry_value_cents=5000000,
                                      **target_overrides):
    """Target in REGULATORY_REVIEW with a FILED application.
    Returns dict with target, assessment, items, case, entry, vote, application."""
    ctx = setup_target_in_municipal_review(entry_value_cents=entry_value_cents,
                                           **target_overrides)
    target_id = ctx["target"]["id"]
    ctx["hearing"] = setup_hearing_held(target_id)
    ctx["vote"] = pass_council_vote(target_id)
    ctx["application"] = file_application(target_id, purchase_price_cents,
                                          rate_base_method, ocld_cents)
    return ctx


def setup_target_in_closing(purchase_price_cents=5000000,
                            rate_base_method="AS_PAID",
                            ocld_cents=None,
                            entry_value_cents=5000000,
                            **target_overrides):
    """Target in CLOSING with an APPROVED application.
    Returns the full context dict."""
    ctx = setup_target_in_regulatory_review(purchase_price_cents, rate_base_method,
                                            ocld_cents, entry_value_cents,
                                            **target_overrides)
    ctx["application"] = decide_application(ctx["application"]["id"], "APPROVED")
    return ctx


def list_transition_items(target_id):
    resp = api_client.list_transition_items(target_id, TEST_USERS["transition_mgr_headers"])
    return get_success_data(resp)


def transition_item_ids_by_category(target_id):
    """Return {category: id} using the fixed creation order."""
    items = list_transition_items(target_id)
    return {item["category"]: item["id"] for item in items}


def resolve_transition_item(item_id, note=None, tm_user_id="tm-1"):
    headers = make_headers(tm_user_id, "TransitionManager")
    payload = {} if note is None else {"resolution_note": note}
    resp = api_client.resolve_transition_item(item_id, payload, headers)
    return resp


def register_account(target_id, account_ref="ACCT-1", deposit_cents=0, ar_balance_cents=0,
                     tm_user_id="tm-1"):
    headers = make_headers(tm_user_id, "TransitionManager")
    resp = api_client.create_customer_account(
        target_id, create_customer_account_payload(account_ref=account_ref,
                                                   deposit_cents=deposit_cents,
                                                   ar_balance_cents=ar_balance_cents),
        headers)
    return get_success_data(resp)


def register_employee(target_id, employee_ref="EMP-1", years_of_service=3,
                      weekly_salary_cents=100000, union_covered=False,
                      hr_user_id="hr-1"):
    headers = make_headers(hr_user_id, "HRDirector")
    resp = api_client.create_employee_transition(
        target_id, create_employee_transition_payload(employee_ref=employee_ref,
                                                      years_of_service=years_of_service,
                                                      weekly_salary_cents=weekly_salary_cents,
                                                      union_covered=union_covered),
        headers)
    return get_success_data(resp)


def create_tariff_case(target_id, mode="STAND_ALONE", representative_old_bill_cents=5000,
                       consolidated_monthly_bill_cents=5000, officer_user_id="regofficer-1"):
    headers = make_headers(officer_user_id, "RegulatoryOfficer")
    resp = api_client.create_tariff_case(
        target_id, create_tariff_case_payload(
            mode=mode, representative_old_bill_cents=representative_old_bill_cents,
            consolidated_monthly_bill_cents=consolidated_monthly_bill_cents),
        headers)
    return get_success_data(resp)


def adopt_tariff_case(case_id, officer_user_id="regofficer-1"):
    headers = make_headers(officer_user_id, "RegulatoryOfficer")
    resp = api_client.adopt_tariff_case(case_id, headers)
    return resp
