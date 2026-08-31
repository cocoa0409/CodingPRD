"""Practice roles, authentication and the fixed order of rejection."""

from test_helpers import (
    NO_AUTH_HEADERS,
    UNKNOWN_UUIDS,
    ApiErrorId,
    TEST_USERS,
    assert_money,
    assert_ratio,
    create_activity_record,
    create_group,
    make_controller_headers,
    make_headers,
    read_filing,
    read_group,
    read_registration,
    setup_bare_registration,
    setup_computed_filing,
    setup_filing_in_review,
    validate_error,
    validate_paginated,
    validate_success,
)

TM = TEST_USERS["tax_manager_headers"]
SA = TEST_USERS["state_analyst_headers"]
CTRL = TEST_USERS["controller_headers"]
AUD = TEST_USERS["auditor_headers"]


# ─── The return's state outranks the fiscal prepayment floor ──────────────────

def test_extension_on_a_draft_return_reports_the_state_rule_not_the_fiscal_one(api):
    """PRD 2.11: "An extension requested on a `DRAFT` return whose prepayment is also insufficient fails at band 7 with `ERR_INVALID_FILING_STATE`, not at band 39."
    PRD 3.6: "A `StateAnalyst` or `TaxManager` requests one on a return that has reached `FACTORS_LOCKED`, `IN_REVIEW` or `APPROVED`, supplying `estimated_tax_paid` — the amount the taxpayer represents as already remitted toward this return, which may not be negative."

    Design: Difficulty/priority_pair_validation_conflict/filing_state_beats_extension_prepayment_fiscal
    """
    ctx = setup_computed_filing(variant="JOYCE")
    assert read_filing(ctx["filing_id"])["preparation_status"] == "DRAFT"
    assert_money(read_filing(ctx["filing_id"])["tax_before_credits"], 88411.96,
                 "tax_before_credits, so the required prepayment is 79570.76")

    response = api.create_extension(ctx["filing_id"], {"estimated_tax_paid": 0.00}, SA)

    error = validate_error(response, ApiErrorId.ERR_INVALID_FILING_STATE.value)
    assert response.status_code == 409
    assert error["error_id"] != ApiErrorId.ERR_EXTENSION_PREPAYMENT_INSUFFICIENT.value


def test_extension_rejected_on_state_grounds_writes_no_request_row(api):
    """PRD 2.11: "An extension requested on a `DRAFT` return whose prepayment is also insufficient fails at band 7 with `ERR_INVALID_FILING_STATE`, not at band 39."
    PRD 3.6: "On the `GRANTED` branch, the request moves `REQUESTED → GRANTED`, its `new_due_date` is set to the return's `original_due_date` advanced by the registration's `extension_months` months, **and** the return's `extended_due_date` is set to that same instant — which is what actually buys the filing deadline more room."

    Design: Difficulty/priority_pair_validation_conflict/filing_state_beats_extension_prepayment_fiscal
    """
    ctx = setup_computed_filing(variant="JOYCE")

    validate_error(
        api.create_extension(ctx["filing_id"], {"estimated_tax_paid": 0.00}, SA),
        ApiErrorId.ERR_INVALID_FILING_STATE.value,
    )

    rows, meta = validate_paginated(
        api.list_filing_extensions(ctx["filing_id"], AUD, {"limit": 10, "offset": 0})
    )
    assert rows == [], "No ExtensionRequest row may be created by a rejected request"
    assert meta["total_count"] == 0
    assert read_filing(ctx["filing_id"])["extended_due_date"] is None


# ─── Role authorization ───────────────────────────────────────────────────────

def test_auditor_may_not_create_a_taxpayer_group(api):
    """PRD 2.1: "An `Auditor` is a read-only reviewer. The role may read every resource in the system and may perform no write of any kind."
    PRD 2.1: "If both headers are well-formed but the named role is not authorized for the target operation, the request is rejected with `ERR_ROLE_NOT_PERMITTED` (HTTP 403)."

    Design: Corner/rbac/auditor_cannot_create_a_taxpayer_group
    """
    validate_success(api.set_clock({"to_iso8601": "2026-08-01T00:00:00Z"}, TM))

    response = api.create_group({
        "name": "Forbidden Group", "base_state_code": "DE", "everywhere_sales": 1,
        "everywhere_property": 1, "everywhere_payroll": 1,
    }, AUD)

    validate_error(response, ApiErrorId.ERR_ROLE_NOT_PERMITTED.value)
    assert response.status_code == 403
    _, meta = validate_paginated(api.list_groups(AUD, {"limit": 10, "offset": 0}))
    assert meta["total_count"] == 0, "A forbidden create must persist nothing"


def test_state_analyst_may_not_approve_a_return(api):
    """PRD 2.1: "A `StateAnalyst` is the return preparer. The role writes activity records, opens returns, runs the factor computation, adds modification lines and credit claims, requests extensions, freezes the computed return and submits it for review. A `StateAnalyst` may not approve, may not transmit a return to the state, and may not move money."
    PRD 2.11: "2. Authorization — the acting role is listed for the target operation (`ERR_ROLE_NOT_PERMITTED`)."
    PRD 2.11: "18. Segregation of duties on approval (`ERR_SEGREGATION_OF_DUTIES`)."

    Design: Corner/rbac/state_analyst_cannot_approve_a_filing
    """
    ctx = setup_filing_in_review(preparer_user_id="analyst-01")

    response = api.approve_filing(
        ctx["filing_id"], {"approval_note": "analyst self approval"},
        make_headers("analyst-02", "StateAnalyst"),
    )

    error = validate_error(response, ApiErrorId.ERR_ROLE_NOT_PERMITTED.value)
    assert response.status_code == 403
    assert error["error_id"] != ApiErrorId.ERR_SEGREGATION_OF_DUTIES.value, (
        "Authorization is evaluated well before segregation of duties"
    )
    filing = read_filing(ctx["filing_id"])
    assert filing["preparation_status"] == "IN_REVIEW"
    assert filing["approver_user_id"] is None


def test_controller_may_not_run_a_nexus_evaluation(api):
    """PRD 2.1: "A `TaxManager` is the practice lead. The role owns groups, member entities, state registrations, nexus determinations, filing elections, the filing calendar, the acknowledgement of extension requests, the state's side of correspondence (information requests, appellate outcomes, closure) and every stage of a voluntary disclosure agreement."
    PRD 2.1: "If both headers are well-formed but the named role is not authorized for the target operation, the request is rejected with `ERR_ROLE_NOT_PERMITTED` (HTTP 403)."

    Design: Corner/rbac/controller_cannot_run_nexus_evaluation
    """
    ctx = setup_bare_registration(
        group_overrides={"name": "Role Nexus Group"},
        registration_overrides={
            "state_code": "CA", "factor_formula": "SINGLE_SALES_FACTOR",
            "tax_rate": 0.0884, "throwback_rule": "NONE",
            "service_sourcing_rule": "MARKET_BASED",
        },
        include_member=True,
    )
    create_activity_record(ctx["registration_id"], {
        "legal_entity_id": ctx["le_a_id"], "tax_year": 2026,
        "destination_sales": 900000, "protected_solicitation_only": False,
    })

    response = api.evaluate_nexus(
        ctx["registration_id"], {"as_of_tax_year": 2026},
        make_controller_headers("controller-01"),
    )

    validate_error(response, ApiErrorId.ERR_ROLE_NOT_PERMITTED.value)
    registration = read_registration(ctx["registration_id"])
    assert registration["nexus_status"] == "NONE"
    assert registration["registration_status"] == "NOT_REQUIRED"
    assert read_group(ctx["group_id"])["open_registration_obligations"] == 0


def test_request_without_practice_headers_is_unauthenticated(api):
    """PRD 2.1: "Every request to the API — reads included — must carry two headers: `X-User-ID`, identifying the acting operator, and `X-User-Role`, naming that operator's role in the SALT practice. If either header is absent, or if `X-User-Role` is not one of the four role names below, the request is rejected with `ERR_UNAUTHENTICATED` (HTTP 401)."

    Design: Corner/rbac/missing_role_header_returns_unauthenticated
    """
    validate_success(api.set_clock({"to_iso8601": "2026-08-01T00:00:00Z"}, TM))
    group = create_group(name="Auth Group")

    response = api.get_group(group["id"], NO_AUTH_HEADERS)

    validate_error(response, ApiErrorId.ERR_UNAUTHENTICATED.value)
    assert response.status_code == 401
    assert response.json()["response_type"] == "error"


def test_auditor_can_read_a_return_and_its_factor_rows(api):
    """PRD 2.1: "An `Auditor` is a read-only reviewer. The role may read every resource in the system and may perform no write of any kind."
    PRD 3.4: "Each run of the computation creates or replaces exactly three `ApportionmentFactor` rows for the return — one with `factor_type` `SALES`, one `PROPERTY`, one `PAYROLL` — each carrying its own `filing_id`, `numerator`, `denominator`, `ratio`, `weight`, `included`, `throwback_added` and `throwout_removed`."

    Design: Corner/rbac/auditor_can_read_every_resource
    """
    ctx = setup_computed_filing(variant="JOYCE")

    filing_response = api.get_filing(ctx["filing_id"], AUD)
    filing = validate_success(filing_response)
    assert filing_response.status_code == 200
    assert_ratio(filing["apportionment_percentage"], 0.200000, "apportionment_percentage")
    assert_money(filing["tax_before_credits"], 88411.96, "tax_before_credits")

    factors_response = api.list_filing_factors(
        ctx["filing_id"], AUD, {"limit": 10, "offset": 0}
    )
    rows, _ = validate_paginated(factors_response)
    assert factors_response.status_code == 200
    assert len(rows) == 3, f"Expected exactly three factor rows, got {len(rows)}"


# ─── Typed not-found codes and duplicate guards ───────────────────────────────

def test_each_collection_answers_its_own_typed_not_found_code(api):
    """PRD 2.7: "Each entity has its own not-found code: `ERR_GROUP_NOT_FOUND` for a taxpayer group, `ERR_LEGAL_ENTITY_NOT_FOUND` for a member entity, `ERR_REGISTRATION_NOT_FOUND` for a state registration, `ERR_ACTIVITY_RECORD_NOT_FOUND` for an activity record, `ERR_ELECTION_NOT_FOUND` for a filing election, `ERR_FILING_NOT_FOUND` for a state return, `ERR_CREDIT_CLAIM_NOT_FOUND` for a credit claim, `ERR_PAYMENT_NOT_FOUND` for an estimated payment, `ERR_EXTENSION_NOT_FOUND` for an extension request, `ERR_NOTICE_NOT_FOUND` for a notice, and `ERR_VDA_NOT_FOUND` for a voluntary disclosure agreement. All eleven return HTTP 404."

    Design: Corner/endpoints/unknown_ids_across_collections_return_typed_not_found
    """
    validate_success(api.set_clock({"to_iso8601": "2026-08-01T00:00:00Z"}, TM))

    probes = [
        (api.get_registration(UNKNOWN_UUIDS["registration"], AUD),
         ApiErrorId.ERR_REGISTRATION_NOT_FOUND.value),
        (api.get_election(UNKNOWN_UUIDS["election"], AUD),
         ApiErrorId.ERR_ELECTION_NOT_FOUND.value),
        (api.get_notice(UNKNOWN_UUIDS["notice"], AUD),
         ApiErrorId.ERR_NOTICE_NOT_FOUND.value),
        (api.get_vda_agreement(UNKNOWN_UUIDS["vda"], AUD),
         ApiErrorId.ERR_VDA_NOT_FOUND.value),
        (api.get_payment(UNKNOWN_UUIDS["payment"], AUD),
         ApiErrorId.ERR_PAYMENT_NOT_FOUND.value),
        (api.get_credit_claim(UNKNOWN_UUIDS["credit_claim"], AUD),
         ApiErrorId.ERR_CREDIT_CLAIM_NOT_FOUND.value),
        (api.get_activity_record(UNKNOWN_UUIDS["activity_record"], AUD),
         ApiErrorId.ERR_ACTIVITY_RECORD_NOT_FOUND.value),
    ]

    for response, expected_error_id in probes:
        assert response.status_code == 404, (
            f"Expected 404 for {expected_error_id}, got {response.status_code}"
        )
        assert response.json()["response_type"] == "error"
        validate_error(response, expected_error_id)


def test_second_registration_for_the_same_state_is_refused(api):
    """PRD 3.1: "A group may hold at most one registration per state: a second registration carrying a `state_code` the group already has is rejected with `ERR_DUPLICATE_REGISTRATION`."

    Design: Corner/validations/duplicate_state_registration_returns_conflict
    """
    ctx = setup_bare_registration(group_overrides={"name": "Duplicate Reg Group"})

    response = api.create_registration(ctx["group_id"], {
        "state_code": "CA", "factor_formula": "SINGLE_SALES_FACTOR", "tax_rate": 0.05,
        "throwback_rule": "NONE", "service_sourcing_rule": "MARKET_BASED",
    }, TM)

    validate_error(response, ApiErrorId.ERR_DUPLICATE_REGISTRATION.value)
    assert response.status_code == 409
    rows, meta = validate_paginated(api.list_group_registrations(
        ctx["group_id"], AUD, {"limit": 10, "offset": 0}
    ))
    assert meta["total_count"] == 1 and len(rows) == 1


def test_activity_record_before_the_year_2000_is_refused(api):
    """PRD 3.1: "A record's `legal_entity_id` must name a member of the very same group that owns the registration in the path, or the write is rejected with `ERR_ENTITY_NOT_IN_GROUP`; and its `tax_year` must be no earlier than 2000, or the write is rejected with `ERR_ACTIVITY_YEAR_MISMATCH`."

    Design: Corner/endpoints/activity_record_before_year_2000_returns_year_mismatch
    """
    ctx = setup_bare_registration(
        group_overrides={"name": "Year Mismatch Group"}, include_member=True,
    )

    response = api.create_activity_record(ctx["registration_id"], {
        "legal_entity_id": ctx["le_a_id"], "tax_year": 1999,
        "destination_sales": 100000,
    }, SA)

    validate_error(response, ApiErrorId.ERR_ACTIVITY_YEAR_MISMATCH.value)
    assert response.status_code == 422
    rows, _ = validate_paginated(api.list_activity_records(AUD, {
        "registration_id": ctx["registration_id"], "limit": 10, "offset": 0,
    }))
    assert rows == [], "A rejected activity write must persist nothing"
