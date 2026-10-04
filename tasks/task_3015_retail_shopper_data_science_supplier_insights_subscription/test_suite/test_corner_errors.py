"""Error-catalog corners: redistribution clauses, modeled-derivation gating,
deliverable review preconditions, and report terminal lockdown."""

from test_helpers import (
    account_with_contract,
    create_cycle,
    create_deliverable,
    create_ready_report,
    create_report,
    get_success_data,
    ingest_category_households,
    read_contract,
    validate_error,
)
from test_helpers import ApiErrorId, factories
from test_helpers.test_users import TEST_USERS

ADMIN = TEST_USERS["retailer_admin_headers"]
MANAGER = TEST_USERS["category_manager_headers"]
SCIENTIST = TEST_USERS["insights_scientist_headers"]


def test_export_blocked_by_redistribution_clause(api):
    """A READY report on a no-redistribution contract stays READY and exports nothing.

    PRD: "A `SupplierAnalyst` may export a report only from `READY` (else `ERR_INVALID_STATE`), only when the contract's `redistribution_allowed` clause is true"
    PRD: "A violation of either clause is rejected with `ERR_REDISTRIBUTION_RESTRICTED`."
    Design: Corner/errors/export_blocked_by_redistribution_clause
    """
    world = account_with_contract(
        api,
        name="Locked Co",
        scope_category="SNACKS",
        scope_brands=["ACME"],
        redistribution_allowed=False,
    )
    ingest_category_households(api, 20, "x")
    report = create_ready_report(api, world["contract"]["id"], world["analyst_headers"])
    resp = api.export_report(report["id"], world["analyst_headers"])
    validate_error(resp, ApiErrorId.REDISTRIBUTION_RESTRICTED.value, 403)
    observed = get_success_data(api.get_insight_report(report["id"], ADMIN))
    assert observed["status"] == "READY"
    from test_helpers import validate_paginated

    _, meta = validate_paginated(api.list_audit_events(ADMIN, params={"subject_id": report["id"]}))
    assert meta["total_count"] == 0


def test_modeled_derivation_forbidden(api):
    """A contract without the modeled-derivation clause cannot create forecasts.

    PRD: "Because a forecast is a modeled, derived data product, creation requires the contract's `modeled_derivation_allowed` clause to be true; otherwise the request fails with `ERR_MODELED_DERIVATION_FORBIDDEN`."
    Design: Corner/errors/modeled_derivation_forbidden
    """
    world = account_with_contract(
        api, name="NoModel Co", tier="TIER_BRAND", modeled_derivation_allowed=False
    )
    resp = api.create_forecast(
        factories.forecast_payload(
            world["contract"]["id"],
            product_ref="NEW-X",
            analogs=[{"analog_ref": "A1", "similarity_score": 1.0, "observed_week4_units": 50}],
            variant="SIMPLE_AVERAGE",
        ),
        SCIENTIST,
    )
    validate_error(resp, ApiErrorId.MODELED_DERIVATION_FORBIDDEN.value, 422)


def test_accept_planned_deliverable_rejected(api):
    """A deliverable that has never been submitted cannot be accepted.

    PRD: "Review of a `SUBMITTED` deliverable belongs to the `CategoryManager` (accept or reject from any other state fails with `ERR_DELIVERABLE_NOT_REVIEWABLE`)."
    Design: Corner/errors/accept_planned_deliverable_rejected
    """
    world = account_with_contract(api, name="Early Co", scope_category="SNACKS", scope_brands=["ACME"])
    report = create_report(api, world["contract"]["id"], world["analyst_headers"])
    cycle = create_cycle(api)
    deliverable = create_deliverable(api, cycle["id"], world["contract"]["id"], report["id"])
    resp = api.accept_deliverable(deliverable["id"], MANAGER)
    validate_error(resp, ApiErrorId.DELIVERABLE_NOT_REVIEWABLE.value, 409)


def test_generate_cancelled_report_rejected(api):
    """A CANCELLED report cannot be regenerated, and its refunded reservation stays refunded.

    PRD: "A `SupplierAnalyst` triggers generation on a report in `REQUESTED` or `SUPPRESSED` — generation from any other state fails with `ERR_REPORT_NOT_GENERATABLE`"
    PRD: "cancellation moves it to `CANCELLED` and refunds the reservation by decreasing the reserved counter by `credit_cost`."
    Design: Corner/errors/generate_cancelled_report_rejected
    """
    world = account_with_contract(api, name="Term Co", scope_category="SNACKS", scope_brands=["ACME"])
    report = create_report(api, world["contract"]["id"], world["analyst_headers"])
    get_success_data(api.cancel_report(report["id"], world["analyst_headers"]))
    resp = api.generate_report(report["id"], world["analyst_headers"])
    validate_error(resp, ApiErrorId.REPORT_NOT_GENERATABLE.value, 409)
    observed = get_success_data(api.get_insight_report(report["id"], ADMIN))
    assert observed["status"] == "CANCELLED"
    contract = read_contract(api, world["contract"]["id"])
    assert contract["report_credits_reserved"] == 0
