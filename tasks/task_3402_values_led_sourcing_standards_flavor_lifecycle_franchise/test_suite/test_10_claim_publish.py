"""Claim publication gates: coverage threshold, cert status, scope (PRD §3.5)."""
from test_helpers import (
    validate_success, validate_error, validate_paginated, get_success_data,
    ApiErrorId, TEST_USERS, api_client,
    create_approved_supplier, make_certification, make_verified_certification,
    verify_certification,
    make_limited_run_flavor, substantiate_claim,
)

FM = TEST_USERS["flavor_manager_headers"]
POC = TEST_USERS["parent_ops_controller_headers"]




def test_claim_coverage_exact_threshold_publishes(api):
    """PRD §3.5: "Publication turns a `SUBSTANTIATED` claim into a public one and applies four gates, evaluated in this order. First, the flavor's lifecycle `status` must be `LIMITED_RUN` or `CORE_LINE`, failing with `ERR_FLAVOR_NOT_PUBLISHABLE` (HTTP 409). Second, `claim_coverage_verified_pct` must meet the threshold for the claim's type — 95 for `FAIR_TRADE_SOURCING`, 100 for `ORGANIC_INGREDIENTS`, 90 for `NON_GMO`, and 100 for `CLIMATE_POSITIVE` — with the boundary inclusive, so coverage exactly equal to the threshold passes; falling short fails with `ERR_CLAIM_COVERAGE_INSUFFICIENT` (HTTP 422). Third, every cited certification must be in `VERIFIED` status, failing with `ERR_CERT_NOT_VERIFIED` (HTTP 422)."

    Design: Difficulty/boundary_precision_check/claim_coverage_exact_threshold_publishes
    """
    supplier = create_approved_supplier(name="Exact Dairy")
    cert = make_verified_certification(supplier["id"], declared=95, verified=95,
                                       certificate_number="FT-B95")
    flavor = make_limited_run_flavor(name="Boundary Batch")
    substantiated = substantiate_claim(flavor["id"], [cert["id"]])
    assert substantiated["claim_coverage_verified_pct"] == 95.0

    published = validate_success(api.publish_claim(flavor["id"], FM))
    assert published["claim_status"] == "PUBLISHED", \
        "coverage == threshold passes; the gate is inclusive"


def test_claim_coverage_just_below_threshold_rejected(api):
    """PRD §3.5: "Publication turns a `SUBSTANTIATED` claim into a public one and applies four gates, evaluated in this order. First, the flavor's lifecycle `status` must be `LIMITED_RUN` or `CORE_LINE`, failing with `ERR_FLAVOR_NOT_PUBLISHABLE` (HTTP 409). Second, `claim_coverage_verified_pct` must meet the threshold for the claim's type — 95 for `FAIR_TRADE_SOURCING`, 100 for `ORGANIC_INGREDIENTS`, 90 for `NON_GMO`, and 100 for `CLIMATE_POSITIVE` — with the boundary inclusive, so coverage exactly equal to the threshold passes; falling short fails with `ERR_CLAIM_COVERAGE_INSUFFICIENT` (HTTP 422). Third, every cited certification must be in `VERIFIED` status, failing with `ERR_CERT_NOT_VERIFIED` (HTTP 422)."

    Design: Difficulty/boundary_precision_check/claim_coverage_exact_threshold_publishes
    """
    supplier = create_approved_supplier(name="Just Under Dairy")
    cert = make_verified_certification(supplier["id"], declared=94, verified=94,
                                       certificate_number="FT-B94")
    flavor = make_limited_run_flavor(name="Just Under Batch")
    substantiated = substantiate_claim(flavor["id"], [cert["id"]])
    assert substantiated["claim_coverage_verified_pct"] == 94.0

    resp = api.publish_claim(flavor["id"], FM)
    validate_error(resp, ApiErrorId.ERR_CLAIM_COVERAGE_INSUFFICIENT)


def test_safety_beats_referential_on_claim_publish(api):
    """PRD §3.5: "Publication turns a `SUBSTANTIATED` claim into a public one and applies four gates, evaluated in this order. First, the flavor's lifecycle `status` must be `LIMITED_RUN` or `CORE_LINE`, failing with `ERR_FLAVOR_NOT_PUBLISHABLE` (HTTP 409). Second, `claim_coverage_verified_pct` must meet the threshold for the claim's type — 95 for `FAIR_TRADE_SOURCING`, 100 for `ORGANIC_INGREDIENTS`, 90 for `NON_GMO`, and 100 for `CLIMATE_POSITIVE` — with the boundary inclusive, so coverage exactly equal to the threshold passes; falling short fails with `ERR_CLAIM_COVERAGE_INSUFFICIENT` (HTTP 422). Third, every cited certification must be in `VERIFIED` status, failing with `ERR_CERT_NOT_VERIFIED` (HTTP 422)."
    PRD §2.6: "the server evaluates them in one fixed precedence ladder, and the earliest failing rung determines the error returned" with business rules applied per endpoint: "each endpoint applying its own ordered list as stated in its subsection (for example, claim publication checks coverage before certification status before scope, and order confirmation checks flavor availability before the credit limit)".

    Design: Difficulty/priority_pair_validation_conflict/safety_beats_referential_on_claim_publish
    """
    supplier = create_approved_supplier(name="Dual Cert Dairy")
    c1 = make_verified_certification(supplier["id"], scheme="FAIR_TRADE",
                                     scope="DAIRY", declared=80, verified=80,
                                     certificate_number="FT-P1")
    c2 = make_verified_certification(supplier["id"], scheme="NON_GMO",
                                     scope="COCOA", declared=90, verified=90,
                                     certificate_number="NG-P2",
                                     valid_until="2026-09-10T00:00:00Z")
    flavor = make_limited_run_flavor(name="Half Verified")
    substantiated = substantiate_claim(flavor["id"], [c1["id"], c2["id"]])
    assert substantiated["claim_coverage_verified_pct"] == 85.0  # mean(80, 90)

    # Expire c2; the claim stays SUBSTANTIATED (only PUBLISHED claims retract).
    validate_success(api.set_clock({"to_iso8601": "2026-09-11T00:00:00Z"}, POC))

    resp = api.publish_claim(flavor["id"], FM)
    err = validate_error(resp, ApiErrorId.ERR_CLAIM_COVERAGE_INSUFFICIENT)
    assert err["error_id"] == "ERR_CLAIM_COVERAGE_INSUFFICIENT", \
        "coverage (priority 10) beats certification status (priority 17)"

    after = get_success_data(api.get_flavor(flavor["id"], FM))
    assert after["claim_coverage_verified_pct"] == 85.0  # below threshold 95
    assert after["claim_status"] == "SUBSTANTIATED"


def test_safety_gate_fires_without_referential_failure(api):
    """PRD §3.5: "Publication turns a `SUBSTANTIATED` claim into a public one and applies four gates, evaluated in this order. First, the flavor's lifecycle `status` must be `LIMITED_RUN` or `CORE_LINE`, failing with `ERR_FLAVOR_NOT_PUBLISHABLE` (HTTP 409). Second, `claim_coverage_verified_pct` must meet the threshold for the claim's type — 95 for `FAIR_TRADE_SOURCING`, 100 for `ORGANIC_INGREDIENTS`, 90 for `NON_GMO`, and 100 for `CLIMATE_POSITIVE` — with the boundary inclusive, so coverage exactly equal to the threshold passes; falling short fails with `ERR_CLAIM_COVERAGE_INSUFFICIENT` (HTTP 422). Third, every cited certification must be in `VERIFIED` status, failing with `ERR_CERT_NOT_VERIFIED` (HTTP 422)."

    Design: Difficulty/priority_pair_validation_conflict/safety_beats_referential_on_claim_publish
    """
    supplier = create_approved_supplier(name="Low Coverage Dairy")
    # Single VERIFIED DAIRY cert at 80: passes scope, all verified, but
    # verified coverage 80 < 95 threshold -> only the safety gate can fail.
    cert = make_verified_certification(supplier["id"], scheme="FAIR_TRADE",
                                       scope="DAIRY", declared=80, verified=80,
                                       certificate_number="FT-LOW")
    flavor = make_limited_run_flavor(name="Low Coverage Batch")
    substantiated = substantiate_claim(flavor["id"], [cert["id"]])
    assert substantiated["claim_coverage_verified_pct"] == 80.0

    resp = api.publish_claim(flavor["id"], FM)
    validate_error(resp, ApiErrorId.ERR_CLAIM_COVERAGE_INSUFFICIENT)
    after = get_success_data(api.get_flavor(flavor["id"], FM))
    assert after["claim_status"] == "SUBSTANTIATED"


def test_claim_publish_unverified_cert_rejected(api):
    """PRD §3.5: "Publication turns a `SUBSTANTIATED` claim into a public one and applies four gates, evaluated in this order. First, the flavor's lifecycle `status` must be `LIMITED_RUN` or `CORE_LINE`, failing with `ERR_FLAVOR_NOT_PUBLISHABLE` (HTTP 409). Second, `claim_coverage_verified_pct` must meet the threshold for the claim's type — 95 for `FAIR_TRADE_SOURCING`, 100 for `ORGANIC_INGREDIENTS`, 90 for `NON_GMO`, and 100 for `CLIMATE_POSITIVE` — with the boundary inclusive, so coverage exactly equal to the threshold passes; falling short fails with `ERR_CLAIM_COVERAGE_INSUFFICIENT` (HTTP 422). Third, every cited certification must be in `VERIFIED` status, failing with `ERR_CERT_NOT_VERIFIED` (HTTP 422)."

    Design: Corner/errors/claim_publish_unverified_cert_rejected
    """
    supplier = create_approved_supplier(name="Mixed Certs")
    c1 = make_verified_certification(supplier["id"], scheme="FAIR_TRADE",
                                     scope="DAIRY", declared=95, verified=95,
                                     certificate_number="FT-UV1")
    c2 = make_certification(supplier["id"], scheme="B_CORP",
                            scope="WHOLE_COMPANY", declared=90,
                            certificate_number="BC-UV2")  # stays PENDING
    flavor = make_limited_run_flavor(name="Pending Partner")
    substantiated = substantiate_claim(flavor["id"], [c1["id"], c2["id"]])
    assert substantiated["claim_coverage_verified_pct"] == 95.0, \
        "only the VERIFIED cert counts, so the safety gate passes"

    resp = api.publish_claim(flavor["id"], FM)
    validate_error(resp, ApiErrorId.ERR_CERT_NOT_VERIFIED)


def test_claim_publish_scope_mismatch_rejected(api):
    """PRD §3.5: "Publication turns a `SUBSTANTIATED` claim into a public one and applies four gates, evaluated in this order. First, the flavor's lifecycle `status` must be `LIMITED_RUN` or `CORE_LINE`, failing with `ERR_FLAVOR_NOT_PUBLISHABLE` (HTTP 409). Second, `claim_coverage_verified_pct` must meet the threshold for the claim's type — 95 for `FAIR_TRADE_SOURCING`, 100 for `ORGANIC_INGREDIENTS`, 90 for `NON_GMO`, and 100 for `CLIMATE_POSITIVE` — with the boundary inclusive, so coverage exactly equal to the threshold passes; falling short fails with `ERR_CLAIM_COVERAGE_INSUFFICIENT` (HTTP 422). Third, every cited certification must be in `VERIFIED` status, failing with `ERR_CERT_NOT_VERIFIED` (HTTP 422)."
    PRD §3.5: "for a `DAIRY` flavor, at least one cited certification must carry an `ingredient_scope` of `DAIRY` or `WHOLE_COMPANY`; for a `NON_DAIRY` flavor, at least one cited certification must carry a scope other than `DAIRY` — and `WHOLE_COMPANY` qualifies here as well. A scope failure is rejected with `ERR_CERT_SCOPE_MISMATCH` (HTTP 422)."

    Design: Corner/errors/claim_publish_scope_mismatch_rejected
    """
    supplier = create_approved_supplier(name="Cocoa Only", category="COCOA",
                                        country_code="GH")
    cert = make_verified_certification(supplier["id"], scheme="FAIR_TRADE",
                                       scope="COCOA", declared=95, verified=95,
                                       certificate_number="FT-SM")
    flavor = make_limited_run_flavor(name="Dairy Needs Dairy")  # DAIRY base
    substantiated = substantiate_claim(flavor["id"], [cert["id"]])
    assert substantiated["claim_coverage_verified_pct"] == 95.0  # gate 2 passes

    resp = api.publish_claim(flavor["id"], FM)
    validate_error(resp, ApiErrorId.ERR_CERT_SCOPE_MISMATCH)
