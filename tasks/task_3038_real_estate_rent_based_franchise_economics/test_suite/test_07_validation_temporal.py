"""Validation cascade ordering, temporal bounds, and singular-resource rules."""
import test_helpers as th


def test_state_before_fiscal_on_fee_payment(api, admin_headers, finance_headers):
    """PRD §2.8: "Fifth, that the target resource is in the state required by
    the operation (failure yields `ERR_INVALID_STATE`, HTTP 409, unless the
    operation names a more specific state error such as
    `ERR_AGREEMENT_NOT_ACTIVE`)."
    PRD §3.3: "Recording the initial fee payment is a segregated duty performed
    by a `FranchiseFinance` officer, whose `amount_cents` must be at least the
    agreement's `initial_fee_cents` — a shortfall is rejected with
    `ERR_INSUFFICIENT_FEE_PAYMENT` (HTTP 402)."

    Design: Difficulty/priority_pair_validation_conflict/state_before_fiscal_on_fee_payment
    """
    site = th.create_site()
    operator = th.create_strong_approved_operator()
    store = th.create_store_for(operator, site)
    # Agreement stays DRAFT (never submitted): the state check fails.
    agreement = th.get_success_data(
        api.create_agreement(th.create_agreement_payload(store["id"], operator["id"]), admin_headers)
    )
    assert agreement["status"] == "DRAFT"

    # Under-payment on a DRAFT agreement: state pre-empts fiscal shortfall.
    resp = api.record_fee_payment(agreement["id"], {"amount_cents": 1_000}, finance_headers)
    th.validate_error(resp, th.ApiErrorId.ERR_INVALID_STATE, expected_status=409)


def test_underpayment_on_fee_pending_agreement_rejected(api, admin_headers, finance_headers):
    """PRD §3.3: "Recording the initial fee payment is a segregated duty
    performed by a `FranchiseFinance` officer, whose `amount_cents` must be at
    least the agreement's `initial_fee_cents` — a shortfall is rejected with
    `ERR_INSUFFICIENT_FEE_PAYMENT` (HTTP 402)."

    Design: Difficulty/priority_pair_validation_conflict/state_before_fiscal_on_fee_payment
    """
    site = th.create_site()
    operator = th.create_strong_approved_operator()
    store = th.create_store_for(operator, site)
    agreement = th.get_success_data(
        api.create_agreement(th.create_agreement_payload(store["id"], operator["id"]), admin_headers)
    )
    th.get_success_data(api.submit_agreement(agreement["id"], admin_headers))

    # State passes (FEE_PENDING); only the fiscal shortfall remains.
    resp = api.record_fee_payment(agreement["id"], {"amount_cents": 1_000}, finance_headers)
    th.validate_error(resp, th.ApiErrorId.ERR_INSUFFICIENT_FEE_PAYMENT, expected_status=402)


def test_temporal_before_referential_on_sublease_create(api, admin_headers, finance_headers):
    """PRD §2.8: "Seventh and beyond, the domain business rules — portfolio
    limits, temporal bounds on subleases and billing periods, singularity of
    active agreements and subleases, renewal windows, fiscal sufficiency
    checks — and finally the optimistic-concurrency version match, each with
    the specific error identifier defined in §3 and §5."
    PRD §3.3: "For stores on `GROUND_LEASE` sites the `end_date` must not
    extend beyond the site's `ground_lease_expiry`; a sublease reaching past it
    is rejected with `ERR_SUBLEASE_BEYOND_GROUND_LEASE` (HTTP 422), both at
    drafting and again at activation."

    Design: Difficulty/priority_pair_validation_conflict/temporal_before_referential_on_sublease_create
    """
    ctx = th.setup_open_store(
        site_overrides={"acquisition_type": "GROUND_LEASE",
                        "ground_lease_expiry": "2030-01-01T00:00:00Z"},
        sublease_overrides={"end_date": "2029-12-31"},
    )
    # Second sublease: beyond the ground lease AND the store already has an
    # ACTIVE sublease — the temporal error surfaces.
    resp = api.create_sublease(
        th.create_sublease_payload(ctx["store"]["id"], ctx["operator"]["id"],
                                   start_date="2030-01-01", end_date="2035-01-01"),
        admin_headers,
    )
    th.validate_error(resp, th.ApiErrorId.ERR_SUBLEASE_BEYOND_GROUND_LEASE, expected_status=422)


def test_second_sublease_rejected_even_inside_ground_lease(api, admin_headers, finance_headers):
    """PRD §2.8: "Seventh and beyond, the domain business rules — portfolio
    limits, temporal bounds on subleases and billing periods, singularity of
    active agreements and subleases, renewal windows, fiscal sufficiency
    checks — and finally the optimistic-concurrency version match, each with
    the specific error identifier defined in §3 and §5."
    PRD §3.3: "at most one non-terminal sublease may exist per store."

    Design: Difficulty/priority_pair_validation_conflict/temporal_before_referential_on_sublease_create
    """
    ctx = th.setup_open_store(
        site_overrides={"acquisition_type": "GROUND_LEASE",
                        "ground_lease_expiry": "2030-01-01T00:00:00Z"},
        sublease_overrides={"end_date": "2029-12-31"},
    )
    # Second sublease fully inside the ground-lease window; only the
    # singular-active-sublease rule can fire.
    resp = api.create_sublease(
        th.create_sublease_payload(ctx["store"]["id"], ctx["operator"]["id"],
                                   start_date="2026-05-01", end_date="2029-06-30"),
        admin_headers,
    )
    th.validate_error(resp, th.ApiErrorId.ERR_ACTIVE_SUBLEASE_EXISTS, expected_status=409)


def test_sublease_term_must_fit_inside_ground_lease(api, admin_headers, finance_headers):
    """PRD §3.3: "For stores on `GROUND_LEASE` sites the `end_date` must not
    extend beyond the site's `ground_lease_expiry`; a sublease reaching past it
    is rejected with `ERR_SUBLEASE_BEYOND_GROUND_LEASE` (HTTP 422), both at
    drafting and again at activation."

    Design: Difficulty/resource_temporal_overlap/sublease_term_must_fit_inside_ground_lease
    """
    site = th.create_site(acquisition_type="GROUND_LEASE",
                          ground_lease_expiry="2030-01-01T00:00:00Z")
    operator = th.create_strong_approved_operator()
    store = th.create_store_for(operator, site)
    th.activate_agreement(store, operator, term_years=4)

    # End one day past the ground-lease expiry: rejected at drafting.
    resp = api.create_sublease(
        th.create_sublease_payload(store["id"], operator["id"],
                                   start_date="2026-04-01", end_date="2030-01-02"),
        admin_headers,
    )
    th.validate_error(resp, th.ApiErrorId.ERR_SUBLEASE_BEYOND_GROUND_LEASE, expected_status=422)

    # End exactly on the ground-lease expiry: passes the temporal check.
    ok = api.create_sublease(
        th.create_sublease_payload(store["id"], operator["id"],
                                   start_date="2026-04-01", end_date="2030-01-01"),
        admin_headers,
    )
    sub = th.validate_success(ok, expected_status=201)
    th.assert_sublease(sub)
    assert sub["status"] == "PENDING"


def test_sublease_within_ground_lease_activates(api, admin_headers, finance_headers):
    """PRD §3.3: "For stores on `GROUND_LEASE` sites the `end_date` must not
    extend beyond the site's `ground_lease_expiry`; a sublease reaching past it
    is rejected with `ERR_SUBLEASE_BEYOND_GROUND_LEASE` (HTTP 422), both at
    drafting and again at activation."
    PRD §3.3: "Activation by a `FranchisorAdmin` moves the sublease `PENDING →
    ACTIVE` and requires that the store's agreement is `ACTIVE` (else
    `ERR_AGREEMENT_NOT_ACTIVE`) and that the store has no other sublease in
    `ACTIVE`, `DEFAULTED`, or `CURED` status (else
    `ERR_ACTIVE_SUBLEASE_EXISTS`); at most one non-terminal sublease may exist
    per store."

    Design: Difficulty/resource_temporal_overlap/sublease_term_must_fit_inside_ground_lease
    """
    site = th.create_site(acquisition_type="GROUND_LEASE",
                          ground_lease_expiry="2030-01-01T00:00:00Z")
    operator = th.create_strong_approved_operator()
    store = th.create_store_for(operator, site)
    th.activate_agreement(store, operator, term_years=4)

    sub = th.get_success_data(api.create_sublease(
        th.create_sublease_payload(store["id"], operator["id"],
                                   start_date="2026-04-01", end_date="2029-12-31"),
        admin_headers,
    ))
    activated = th.validate_success(api.activate_sublease(sub["id"], admin_headers))
    assert activated["status"] == "ACTIVE"


def test_one_active_sublease_per_store_mutual_exclusion(api, admin_headers, finance_headers):
    """PRD §3.3: "Activation by a `FranchisorAdmin` moves the sublease `PENDING
    → ACTIVE` and requires that the store's agreement is `ACTIVE` (else
    `ERR_AGREEMENT_NOT_ACTIVE`) and that the store has no other sublease in
    `ACTIVE`, `DEFAULTED`, or `CURED` status (else
    `ERR_ACTIVE_SUBLEASE_EXISTS`); at most one non-terminal sublease may exist
    per store."

    Design: Difficulty/resource_temporal_overlap/one_active_sublease_per_store_mutual_exclusion
    """
    ctx = th.setup_open_store()
    # Second sublease whose window starts AFTER the current sublease ends —
    # still collides because the first is ACTIVE.
    resp = api.create_sublease(
        th.create_sublease_payload(ctx["store"]["id"], ctx["operator"]["id"],
                                   base_rent_cents=3_000_000, pct_rent_rate=0.09,
                                   start_date="2031-04-01", end_date="2036-03-31"),
        admin_headers,
    )
    th.validate_error(resp, th.ApiErrorId.ERR_ACTIVE_SUBLEASE_EXISTS, expected_status=409)


def test_second_pending_sublease_also_rejected(api, admin_headers, finance_headers):
    """PRD §3.3: "at most one non-terminal sublease may exist per store."
    PRD §3.3: "Activation by a `FranchisorAdmin` moves the sublease `PENDING →
    ACTIVE` and requires that the store's agreement is `ACTIVE` (else
    `ERR_AGREEMENT_NOT_ACTIVE`) and that the store has no other sublease in
    `ACTIVE`, `DEFAULTED`, or `CURED` status (else
    `ERR_ACTIVE_SUBLEASE_EXISTS`); at most one non-terminal sublease may exist
    per store."

    Design: Difficulty/resource_temporal_overlap/one_active_sublease_per_store_mutual_exclusion
    """
    site = th.create_site()
    operator = th.create_strong_approved_operator()
    store = th.create_store_for(operator, site)
    th.activate_agreement(store, operator)
    # First sublease exists in PENDING (non-terminal).
    first = th.get_success_data(
        api.create_sublease(th.create_sublease_payload(store["id"], operator["id"]), admin_headers)
    )
    assert first["status"] == "PENDING"

    resp = api.create_sublease(
        th.create_sublease_payload(store["id"], operator["id"],
                                   start_date="2031-04-01", end_date="2036-03-31"),
        admin_headers,
    )
    th.validate_error(resp, th.ApiErrorId.ERR_ACTIVE_SUBLEASE_EXISTS, expected_status=409)


def test_missing_user_context_header_rejected(api):
    """PRD §2.1: "A request in which either header is missing or blank is
    rejected with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` (HTTP 400)."
    PRD §2.8: "First, the presence and non-emptiness of the `X-User-ID` and
    `X-User-Role` headers (failure yields
    `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER`)."

    Design: Corner/validations/missing_user_context_header_rejected
    """
    resp = api.create_site(
        th.create_site_payload(site_code="CS10", address="110 Corner St"),
        {"X-User-ID": "test-admin-1", "Content-Type": "application/json"},
    )
    th.validate_error(resp, th.ApiErrorId.ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER, expected_status=400)


def test_existence_before_state_on_nested_action(api, admin_headers):
    """PRD §2.7: "When an endpoint path contains resource identifiers, the
    system validates their existence left to right, rejecting with
    `ERR_RESOURCE_NOT_FOUND` (HTTP 404) at the first identifier that does not
    resolve."
    PRD §2.8: "Third, that path identifiers resolve to existing resources,
    validated left to right (failure yields `ERR_RESOURCE_NOT_FOUND`)."

    Design: Corner/validations/existence_before_state_on_nested_action
    """
    resp = api.approve_operator("8a3e1c0b-2f4d-4a91-9c8b-12e7b6a0f1d2", admin_headers)
    th.validate_error(resp, th.ApiErrorId.ERR_RESOURCE_NOT_FOUND, expected_status=404)


