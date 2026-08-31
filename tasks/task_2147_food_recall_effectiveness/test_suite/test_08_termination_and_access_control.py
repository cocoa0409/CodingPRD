"""Closing the case, terminal lockdown, and the acting-identity rules."""
from test_helpers import (
    ApiErrorId,
    MISSING_ROLE_HEADERS,
    NON_EXISTENT_UUID,
    case_in_termination_requested,
    case_with_verified_receipt,
    create_cost_entry_payload,
    create_recall_payload,
    make_coordinator_headers,
    make_firm_officer_headers,
    register_firm,
    terminated_case,
    validate_error,
    validate_paginated,
    validate_success,
)

COORDINATOR = make_coordinator_headers("coord-1")


def test_termination_closes_open_reports_and_frees_the_firms_recall_slot(api):
    """PRD §3.9: "Termination advances `TERMINATION_REQUESTED → TERMINATED`, stamps `terminated_at` from the logical clock, moves every status report of the recall still in `PENDING` or `OVERDUE` to `ACCEPTED`, and decrements the firm's `open_recall_count` by one."
    PRD §3.7: "Finally a `FieldInvestigator` supplies a `decision`: `VERIFY` advances `EXECUTED → VERIFIED`, stamps `witness_user_id`, and moves the `quantity` out of `units_pending_verification` and into `units_disposed_verified`; `REJECT` sends the order back along `EXECUTED → AUTHORIZED`, increments `reject_count`, clears both `certificate_reference` and `executed_at` back to null, and moves the `quantity` out of `units_pending_verification` and back into `units_awaiting_disposition`, so an execute-then-reject pair restores the custody ledger exactly."

    Design: Corner/state_machines/terminate_recall_closes_open_reports_and_decrements_open_recall_count
    """
    case = case_in_termination_requested(
        clock="2026-09-01T00:00:00Z", dispose_units=960
    )

    terminated = case.decide_termination("TERMINATE", coordinator_id="coord-2")
    assert terminated["status"] == "TERMINATED"
    assert terminated["terminated_at"] == "2026-09-01T00:00:00.000Z"
    assert terminated["units_disposed_verified"] == 960
    assert terminated["units_awaiting_disposition"] == 0
    assert terminated["units_pending_verification"] == 0

    firm = validate_success(api.get_firm(case.firm_id, COORDINATOR))
    assert firm["open_recall_count"] == 0

    reports, meta = validate_paginated(
        api.list_status_reports(case.recall_id, COORDINATOR)
    )
    assert meta["total_count"] == 2
    for report in reports:
        assert report["status"] == "ACCEPTED"


def test_no_write_is_accepted_against_a_terminated_recall(api):
    """PRD §3.9: "`TERMINATED` is terminal for the whole case file: no write of any kind is accepted against the recall or any of its sub-resources afterwards."
    PRD §2.6: "The recall's `status` permits the operation, including the total lockdown of a `TERMINATED` recall and the block on terminating while the compliance posture is `DELINQUENT` — otherwise `ERR_INVALID_RECALL_STATE` (409)."

    Design: Corner/state_machines/cost_entry_on_terminated_recall_returns_invalid_recall_state
    """
    case = terminated_case(clock="2026-09-01T00:00:00Z")

    response = api.create_cost_entry(
        case.recall_id,
        create_cost_entry_payload("LEGAL", 50000, description="Late invoice"),
        case.officer,
    )
    validate_error(response, ApiErrorId.ERR_INVALID_RECALL_STATE.value)
    assert response.status_code == 409

    rows, meta = validate_paginated(api.list_cost_entries(case.recall_id, COORDINATOR))
    assert rows == []
    assert meta["total_count"] == 0

    recall = case.read_recall()
    assert recall["total_loaded_cost_cents"] == 0
    assert recall["status"] == "TERMINATED"


def test_denying_termination_cycles_the_recall_back_to_retrieval_accounting(api):
    """PRD §3.9: "A `decision` of `DENY` sends the recall back along `TERMINATION_REQUESTED → RETRIEVAL_ACCOUNTING`, increments `termination_denied_count` by one, raises `compliance_flag` from `COMPLIANT` to `WATCH` while leaving any stronger posture untouched, and mints a fresh status report with `report_kind` `PERIODIC`, `period_index` one above the current maximum, `period_start` at the current logical instant, `period_end` and `due_at` at that instant plus `report_cadence_days` days, and `status` `PENDING`."
    PRD §3.9: "The `FirmRecallOfficer` requests termination from `EFFECTIVENESS_REVIEW`, supplying `root_cause_code` — one of `SUPPLIER_INGREDIENT`, `SANITATION`, `PROCESS_DEVIATION`, `LABELING`, `PACKAGING`, `CROSS_CONTACT` or `UNKNOWN` — and a `capa_summary` narrating the corrective and preventive action taken; both are persisted on the recall and the recall advances `EFFECTIVENESS_REVIEW → TERMINATION_REQUESTED`."

    Design: Corner/state_machines/termination_denial_cycles_recall_back_to_retrieval_accounting
    """
    case = case_in_termination_requested(
        clock="2026-09-01T00:00:00Z", root_cause_code="SANITATION",
        capa_summary="Sanitation SOP revised.",
    )

    denied = case.decide_termination("DENY", coordinator_id="coord-2")
    assert denied["status"] == "RETRIEVAL_ACCOUNTING"
    assert denied["termination_denied_count"] == 1
    assert denied["compliance_flag"] == "WATCH"
    assert denied["report_cadence_days"] == 7
    assert denied["root_cause_code"] == "SANITATION"

    reports, meta = validate_paginated(
        api.list_status_reports(case.recall_id, COORDINATOR)
    )
    assert meta["total_count"] == 3
    newest = [r for r in reports if r["period_index"] == 3][0]
    assert newest["report_kind"] == "PERIODIC"
    assert newest["status"] == "PENDING"
    assert newest["due_at"] == "2026-09-08T00:00:00.000Z"


def test_termination_below_the_effectiveness_floor_is_refused(api):
    """PRD §3.9: "Two conditions guard the request. No disposition order of the recall may be in `PROPOSED`, `AUTHORIZED` or `EXECUTED` — any open order refuses the request with `ERR_OPEN_DISPOSITION_ORDERS` — and the recall's `official_effectiveness_pct` must be at least 90.00, below which the request is refused with `ERR_EFFECTIVENESS_BELOW_TERMINATION_THRESHOLD`."
    PRD §3.4: "`CORRECT` is only available from `DISPUTED`, moves `DISPUTED → CORRECTED`, and requires a `quantity_confirmed` in the body that is present and strictly greater than zero — omit it or send zero and the request is refused with `ERR_INVALID_REQUEST`; the supplied value is stored as `quantity_confirmed` and becomes the line's `effective_quantity`."

    Design: Corner/validations/termination_request_below_ninety_percent_returns_fiscal_error
    """
    case = case_with_verified_receipt(
        agency="USDA", quantity_shipped=1000, quantity_returned=960,
        quantity_unrecoverable=40,
    )
    case.reconcile(case.d1_id, "DISPUTE")
    corrected = case.reconcile(case.d1_id, "CORRECT", quantity_confirmed=1200)
    assert corrected["status"] == "CORRECTED"
    assert corrected["effective_quantity"] == 1200

    response = api.request_termination(
        case.recall_id,
        {"root_cause_code": "LABELING", "capa_summary": "Label artwork control tightened."},
        case.officer,
    )
    validate_error(
        response, ApiErrorId.ERR_EFFECTIVENESS_BELOW_TERMINATION_THRESHOLD.value
    )
    assert response.status_code == 422

    recall = case.read_recall()
    assert recall["total_shipped_units"] == 1200
    assert recall["quantity_effectiveness_pct"] == 80.00
    assert recall["official_effectiveness_pct"] == 80.00
    assert recall["status"] == "EFFECTIVENESS_REVIEW"
    assert recall["root_cause_code"] is None


def test_an_open_disposition_order_blocks_the_termination_request(api):
    """PRD §3.9: "Two conditions guard the request. No disposition order of the recall may be in `PROPOSED`, `AUTHORIZED` or `EXECUTED` — any open order refuses the request with `ERR_OPEN_DISPOSITION_ORDERS` — and the recall's `official_effectiveness_pct` must be at least 90.00, below which the request is refused with `ERR_EFFECTIVENESS_BELOW_TERMINATION_THRESHOLD`."
    PRD §2.6: "Termination may not be requested while any disposition order of the recall is still open — otherwise `ERR_OPEN_DISPOSITION_ORDERS` (409). Applies to `POST /recalls/{id}/request-termination`."

    Design: Corner/errors/termination_request_with_an_open_disposition_order_is_rejected
    """
    case = case_with_verified_receipt(
        agency="USDA", quantity_shipped=1000, quantity_returned=960,
        quantity_unrecoverable=40,
    )
    order = case.propose_disposition(
        100, method="RELABEL", facility_name="Northvale Line 4"
    )

    response = api.request_termination(
        case.recall_id,
        {"root_cause_code": "PACKAGING", "capa_summary": "Seal integrity test added."},
        case.officer,
    )
    error = validate_error(response, ApiErrorId.ERR_OPEN_DISPOSITION_ORDERS.value)
    assert response.status_code == 409
    assert error["error_id"] != (
        ApiErrorId.ERR_EFFECTIVENESS_BELOW_TERMINATION_THRESHOLD.value
    )

    recall = case.read_recall()
    assert recall["status"] == "EFFECTIVENESS_REVIEW"
    assert recall["capa_summary"] is None

    rows, _ = validate_paginated(
        api.list_disposition_orders(case.recall_id, COORDINATOR)
    )
    assert [row for row in rows if row["id"] == order["id"]][0]["status"] == "PROPOSED"


def test_a_recall_officer_of_another_firm_is_out_of_scope(api):
    """PRD §2.1: "Concretely, a recall officer may only touch recalls whose `firm_id` equals their `X-User-ID`, and that scoping applies to reads exactly as it applies to writes; a violation is rejected with `ERR_FIRM_SCOPE_VIOLATION` and HTTP 403."
    PRD §2.6: "Firm tenant scoping: when the acting role is `FirmRecallOfficer`, `X-User-ID` must equal the `firm_id` of the recall the request resolves to — otherwise `ERR_FIRM_SCOPE_VIOLATION` (403)."

    Design: Corner/rbac/firm_officer_of_another_firm_cannot_touch_this_recall
    """
    firm_a = register_firm(name="Northvale Foods", registration_number="FFR-10021")
    firm_b = register_firm(name="Southgate Provisions", registration_number="FFR-20044")
    recall_a = validate_success(
        api.create_recall(
            create_recall_payload(firm_a["id"]), make_firm_officer_headers(firm_a["id"])
        ),
        201,
    )

    response = api.create_cost_entry(
        recall_a["id"],
        create_cost_entry_payload("LOGISTICS", 100000, description="Freight"),
        make_firm_officer_headers(firm_b["id"]),
    )
    error = validate_error(response, ApiErrorId.ERR_FIRM_SCOPE_VIOLATION.value)
    assert response.status_code == 403
    assert error["error_id"] != ApiErrorId.ERR_ROLE_NOT_PERMITTED.value

    rows, meta = validate_paginated(api.list_cost_entries(recall_a["id"], COORDINATOR))
    assert rows == []
    assert meta["total_count"] == 0

    firm_b_after = validate_success(api.get_firm(firm_b["id"], COORDINATOR))
    assert firm_b_after["open_recall_count"] == 0


def test_a_request_without_the_role_header_is_unauthenticated(api):
    """PRD §2.1: "If either header is absent, or if `X-User-Role` carries any string outside those five, the request is rejected with `ERR_MISSING_AUTH_HEADER` and HTTP 401."
    PRD §2.1: "The two rejections are distinct and are not interchangeable: an unrecognised role string is an authentication failure, not an authorization failure."

    Design: Corner/rbac/missing_x_user_role_header_returns_unauthenticated
    """
    response = api.get_recall(NON_EXISTENT_UUID, MISSING_ROLE_HEADERS)
    error = validate_error(response, ApiErrorId.ERR_MISSING_AUTH_HEADER.value)
    assert response.status_code == 401
    assert error["error_id"] != ApiErrorId.ERR_RECALL_NOT_FOUND.value
