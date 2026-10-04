"""Valuation case, entry, segregation-of-duties, and OCC tests."""
from test_helpers import (
    api_client, TEST_USERS,
    validate_success, validate_error, get_success_data,
    ApiErrorId,
    assert_valuation_case, assert_valuation_entry,
    create_assessment_payload, create_capital_item_payload,
    create_target, create_assessment_with_items, submit_assessment,
    accept_assessment, current_target_version,
    open_valuation_case, submit_entry, finalize_case,
    setup_target_in_valuation,
    make_headers,
)


def test_occ_stale_version_on_valuation_case_create(api):
    """PRD §2.7: "**Opening a valuation case.** The request must carry
    `expected_target_version`, the client-side last observed `version` of the
    target. If the target's current `version` has since advanced, the create is
    rejected with `ERR_STALE_VERSION` (HTTP 412)."

    Design: Corner/errors/occ_stale_version_on_valuation_case_create
    """
    target, _, _ = setup_target_in_valuation(state_code="OH", customer_count=5)
    stale_version = current_target_version(target["id"])
    # First open succeeds and bumps the target version by 1.
    open_valuation_case(target["id"])
    resp = api.create_valuation_case(target["id"],
                                     {"expected_target_version": stale_version},
                                     TEST_USERS["analyst_headers"])
    validate_error(resp, ApiErrorId.ERR_STALE_VERSION)


def test_assessment_creator_cannot_accept_own_assessment(api):
    """PRD §2.9: "The `EngineeringReviewer` who accepts or rejects a submitted
    condition assessment must not be the analyst who created it — the request's
    `X-User-ID` must differ from the assessment's `created_by_user_id`, otherwise
    the call is rejected with `ERR_SEGREGATION_OF_DUTY` (HTTP 403)."

    Design: Corner/errors/assessment_creator_cannot_accept_own_assessment
    """
    target = create_target(state_code="OH", customer_count=5)
    shared_headers = make_headers("shared-person-1", "AcquisitionAnalyst")
    resp = api.create_assessment(target["id"], create_assessment_payload(),
                                 shared_headers)
    assessment = get_success_data(resp)
    api.create_capital_item(assessment["id"],
                            create_capital_item_payload(category="GENERAL"),
                            shared_headers)
    api.submit_assessment(assessment["id"], shared_headers)

    reviewer_same_person = make_headers("shared-person-1", "EngineeringReviewer")
    resp = api.accept_assessment(assessment["id"], reviewer_same_person)
    validate_error(resp, ApiErrorId.ERR_SEGREGATION_OF_DUTY)
    fetched = get_success_data(api.get_assessment(assessment["id"], shared_headers))
    assert fetched["status"] == "SUBMITTED"


def test_valuation_finalizer_cannot_be_entry_appraiser(api):
    """PRD §2.9: "the `AcquisitionAnalyst` who finalizes a valuation case must
    not be the appraiser of any `SUBMITTED` entry in that case — `X-User-ID`
    must differ from the `appraiser_user_id` of every submitted entry — and the
    same `ERR_SEGREGATION_OF_DUTY` (HTTP 403) applies."

    Design: Corner/errors/valuation_finalizer_cannot_be_entry_appraiser
    """
    target, _, _ = setup_target_in_valuation(state_code="OH", customer_count=5)
    case = open_valuation_case(target["id"])
    entry = submit_entry(case["id"], appraiser_user_id="dual-hat-1")

    resp = api.finalize_valuation_case(
        case["id"], {"select_entry_id": entry["id"]},
        make_headers("dual-hat-1", "AcquisitionAnalyst"))
    validate_error(resp, ApiErrorId.ERR_SEGREGATION_OF_DUTY)
    fresh = get_success_data(api.get_valuation_case(case["id"], TEST_USERS["analyst_headers"]))
    assert fresh["status"] == "OPEN"


def test_valuation_entry_method_not_permitted(api):
    """PRD §3.3: "State law constrains the menu: an entry whose `method` is not
    among the target's `permitted_valuation_methods` is rejected with
    `ERR_METHOD_NOT_PERMITTED` (HTTP 422)."

    Design: Corner/validations/valuation_entry_method_not_permitted
    """
    target, _, _ = setup_target_in_valuation(
        state_code="OH", customer_count=5,
        permitted_valuation_methods=["FMV_INDEPENDENT", "REPLACEMENT_COST"])
    case = open_valuation_case(target["id"])
    resp = api.create_valuation_entry(
        case["id"],
        {"method": "ORIGINAL_COST_LESS_DEPRECIATION", "value_cents": 4000000,
         "law_citation": "c"},
        make_headers("appraiser-1", "Appraiser"))
    validate_error(resp, ApiErrorId.ERR_METHOD_NOT_PERMITTED)


def test_valuation_entry_terminal_lockdown(api):
    """PRD §3.3: "On finalize, the selected entry moves to `SELECTED` and every
    other `SUBMITTED` entry moves to `NOT_SELECTED`; the case moves to
    `FINALIZED`".

    Design: Corner/state_machines/valuation_entry_terminal_lockdown
    """
    target, _, _ = setup_target_in_valuation(state_code="OH", customer_count=5)
    case = open_valuation_case(target["id"])
    e1 = submit_entry(case["id"], value_cents=5000000, appraiser_user_id="appraiser-1")
    e2 = submit_entry(case["id"], value_cents=6000000, appraiser_user_id="appraiser-2")
    finalize_case(case["id"], e2["id"])

    e1_now = get_success_data(
        api.list_valuation_entries(case["id"], TEST_USERS["analyst_headers"]))
    statuses = {e["id"]: e["status"] for e in e1_now}
    assert statuses[e1["id"]] == "NOT_SELECTED"
    assert statuses[e2["id"]] == "SELECTED"

    # The finalized case accepts no new entries.
    resp = api.create_valuation_entry(
        case["id"], {"method": "FMV_INDEPENDENT", "value_cents": 7000000,
                     "law_citation": "c"},
        make_headers("appraiser-3", "Appraiser"))
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
