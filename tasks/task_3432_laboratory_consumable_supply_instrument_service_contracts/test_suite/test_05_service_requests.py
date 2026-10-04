"""Service requests: the PM contract/spacing gates, the PM quota boundary,
the billing-split partition invariant, and the dispatch selector policy
(eligibility, capacity, tie-breaks, and resolve ownership).
"""

from test_helpers import (
    ACCOUNT_MANAGER,
    CLOCK_START_UTC,
    DISPATCHER,
    ApiErrorId,
    api_client,
    assert_billing_split_invariant,
    create_account,
    create_and_resolve_request,
    create_engineer,
    create_engineers_staggered,
    create_installed_instrument,
    create_instrument,
    create_pm_request,
    create_service_request,
    dispatch_request,
    ensure_engineer,
    get_account,
    get_service_contract,
    get_service_request,
    install_instrument,
    make_field_engineer_headers,
    make_lab_procurement_headers,
    plus_days,
    resolve_payload,
    resolve_request,
    service_request_payload,
    setup_instrument_with_contract,
    setup_pm_quota_scenario,
    validate_error,
    validate_success,
    LABOR_RATE_CENTS_PER_HOUR,
)

_PM_BASE_DATE = plus_days(CLOCK_START_UTC, 30)  # 2026-10-01T00:00:00Z


def test_pm_without_contract_rejected(api):
    """PRD section 3.5: "Preventive maintenance carries two further gates: the
    instrument must have a contract reading `ACTIVE` or `RENEWAL_DUE` —
    otherwise `ERR_CONTRACT_REQUIRED`".

    Design: Corner/validations/pm_without_contract_rejected
    """
    account = create_account(name="No Contract Lab", segment="CLINICAL")
    instrument = create_installed_instrument(account)
    response = api_client.create_service_request(
        service_request_payload(
            instrument["id"],
            request_type="PREVENTIVE_MAINTENANCE",
            scheduled_for=_PM_BASE_DATE,
        ),
        headers=ACCOUNT_MANAGER,
    )
    validate_error(response, ApiErrorId.ERR_CONTRACT_REQUIRED)

    ok = api_client.create_service_request(
        service_request_payload(instrument["id"], request_type="BREAK_FIX"),
        headers=ACCOUNT_MANAGER,
    )
    validate_success(ok, 201)


def test_pm_gap_nineteen_days_rejected(api):
    """PRD section 3.5: "a preventive request whose `scheduled_for` falls less
    than 30 days after the `scheduled_for` of another `OPEN` or `DISPATCHED`
    preventive request on the same instrument is rejected with
    `ERR_PM_GAP_VIOLATION`, while a gap of exactly 30 days is permitted."

    Design: Difficulty/resource_temporal_overlap/pm_min_gap_thirty_days
    """
    account, instrument, contract = setup_instrument_with_contract(tier="GOLD")
    create_pm_request(instrument, account, _PM_BASE_DATE)
    response = api_client.create_service_request(
        service_request_payload(
            instrument["id"],
            request_type="PREVENTIVE_MAINTENANCE",
            scheduled_for=plus_days(_PM_BASE_DATE, 19),
        ),
        headers=make_lab_procurement_headers(account["id"]),
    )
    validate_error(response, ApiErrorId.ERR_PM_GAP_VIOLATION)


def test_pm_gap_exactly_thirty_days_allowed(api):
    """PRD section 3.5: "a preventive request whose `scheduled_for` falls less
    than 30 days after the `scheduled_for` of another `OPEN` or `DISPATCHED`
    preventive request on the same instrument is rejected with
    `ERR_PM_GAP_VIOLATION`, while a gap of exactly 30 days is permitted."

    Design: Difficulty/resource_temporal_overlap/pm_min_gap_thirty_days
    """
    account, instrument, contract = setup_instrument_with_contract(tier="GOLD")
    create_pm_request(instrument, account, _PM_BASE_DATE)
    response = api_client.create_service_request(
        service_request_payload(
            instrument["id"],
            request_type="PREVENTIVE_MAINTENANCE",
            scheduled_for=plus_days(_PM_BASE_DATE, 30),
        ),
        headers=make_lab_procurement_headers(account["id"]),
    )
    created = validate_success(response, 201)
    assert created["status"] == "OPEN", (
        "a gap of exactly 30 days is permitted (comparison is >= 30 days)"
    )


def test_pm_quota_fourth_visit_fully_covered(api):
    """PRD section 3.5: "A within-quota preventive visit — one resolved while
    the contract's `used_pm_visits` is still below its `pm_visits_per_year` —
    bills the customer nothing, covers labor plus parts in full, and
    increments `used_pm_visits` by 1."  On a GOLD contract the fourth visit
    resolves while used_pm_visits is 3, still below the quota of 4.

    Design: Difficulty/boundary_precision_check/pm_quota_fourth_free_fifth_billed
    """
    scene = setup_pm_quota_scenario(tier="GOLD", resolved_visits=5,
                                    hours_on_site=2)
    fourth = scene["resolved_requests"][3]
    labor = LABOR_RATE_CENTS_PER_HOUR * 2
    assert fourth["billable_cents"] == 0, "the 4th visit is still within quota"
    assert fourth["covered_cents"] == labor, "labor 2 x 18500 covered in full"
    after = get_service_contract(scene["contract"])
    assert after["used_pm_visits"] == 4, "the within-quota 4th visit consumed the last slot"


def test_pm_quota_fifth_visit_fully_billed(api):
    """PRD section 3.5: "A preventive visit beyond the quota bills labor plus
    parts to the customer and covers nothing."  On a GOLD contract
    (pm_visits_per_year 4) the fifth visit resolves while used_pm_visits is
    already 4 — the within-quota comparison is used < quota, so
    exactly-at-quota is already over.

    Design: Difficulty/boundary_precision_check/pm_quota_fourth_free_fifth_billed
    """
    scene = setup_pm_quota_scenario(tier="GOLD", resolved_visits=5,
                                    hours_on_site=2)
    fifth = scene["resolved_requests"][4]
    labor = LABOR_RATE_CENTS_PER_HOUR * 2
    assert fifth["billable_cents"] == labor, (
        "the 5th visit is over quota: labor plus parts bills in full"
    )
    assert fifth["covered_cents"] == 0
    after = get_service_contract(scene["contract"])
    assert after["used_pm_visits"] == 4, (
        "over-quota visits do not consume quota: counter stays at 4"
    )


def test_billing_split_partitions_labor_and_parts(api):
    """PRD section 3.5: "Any other request type covers labor entirely plus the
    tier's `parts_coverage_pct` share of `parts_cost_cents` — that share
    rounded half-up to the nearest cent — and bills the customer only the
    uncovered remainder of parts."  GOLD covers 90 percent of parts.

    Design: Difficulty/compensating_invariant/billing_split_conserves_total_cost
    """
    account, instrument, contract = setup_instrument_with_contract(tier="GOLD")
    ensure_engineer(account, ["BREAK_FIX"], name="Fixer")
    resolved = create_and_resolve_request(
        instrument, account, hours_on_site=2, parts_cost_cents=100000,
        request_type="BREAK_FIX", severity="MEDIUM",
    )
    assert resolved["billable_cents"] == 10000, (
        "customer bills the uncovered 10 percent of 100000 parts"
    )
    assert resolved["covered_cents"] == 127000, (
        "labor 2 x 18500 = 37000 fully covered plus 90000 covered parts"
    )
    assert_billing_split_invariant(
        resolved, hours_on_site=2, labor_rate_cents=LABOR_RATE_CENTS_PER_HOUR
    )


def test_billing_split_invoice_and_no_breach_memo(api):
    """PRD section 3.5: "Whenever a live contract pays, the billable and
    covered portions sum exactly to labor plus parts." and "a
    `credit_memo_cents` equal to 10 percent of `billable_cents` rounded
    half-up to the nearest cent when the SLA was breached, and 0 otherwise"
    and "The invoice posted to the account's `outstanding_balance_cents` is
    `billable_cents` minus `credit_memo_cents`".

    Design: Difficulty/compensating_invariant/billing_split_conserves_total_cost
    """
    account, instrument, contract = setup_instrument_with_contract(tier="GOLD")
    ensure_engineer(account, ["BREAK_FIX"], name="Fixer")
    resolved = create_and_resolve_request(
        instrument, account, hours_on_site=2, parts_cost_cents=100000,
        request_type="BREAK_FIX", severity="MEDIUM",
    )
    assert resolved["sla_breached"] is False, (
        "resolved at the open instant, inside the GOLD 24-hour window"
    )
    assert resolved["credit_memo_cents"] == 0
    fresh = get_account(account)
    assert fresh["outstanding_balance_cents"] == 10000, (
        "the posted invoice is billable_cents minus credit_memo_cents"
    )


def _two_engineers_and_instrument(account):
    """Two engineers one logical second apart (first INSTALL+BREAK_FIX, second
    BREAK_FIX only) plus an installed instrument; returns (e1, e2, instrument)."""
    engineers = create_engineers_staggered(
        2,
        per_engineer=[
            {"name": "Zed First", "skills": ["INSTALL", "BREAK_FIX"]},
            {"name": "Ann Second", "skills": ["BREAK_FIX"]},
        ],
    )
    instrument = install_instrument(create_instrument(account, model="SEQ-5000"))
    return engineers[0], engineers[1], instrument


def test_dispatch_selector_tie_break_created_at(api):
    """PRD section 3.5: "Otherwise the selector ranks eligible engineers by
    `open_ticket_count` ascending, breaks ties by the engineer's `created_at`
    ascending, and breaks any remaining tie by `name` ascending".

    Design: Corner/cross_cutting_layers/dispatch_selector_tie_break_created_at
    """
    account = create_account(name="Selector Lab")
    first, second, instrument = _two_engineers_and_instrument(account)
    r1 = create_service_request(instrument, account, severity="LOW")
    r2 = create_service_request(instrument, account, severity="LOW")

    pick1 = dispatch_request(r1)
    assert pick1["engineer_id"] == first["id"], (
        "0-0 open-ticket tie breaks to the first-created engineer"
    )
    pick2 = dispatch_request(r2)
    assert pick2["engineer_id"] == second["id"], (
        "0 open tickets beats 1 open ticket on the second dispatch"
    )


def test_dispatch_five_tickets_capacity_rejected(api):
    """PRD section 3.5: "a non-empty set in which every eligible engineer
    already holds 4 dispatched tickets on the current UTC calendar day fails
    with `ERR_ENGINEER_CAPACITY_EXCEEDED`."

    Design: Corner/cross_cutting_layers/dispatch_five_tickets_capacity_rejected
    """
    account = create_account(name="Capacity Lab")
    create_engineer(name="Solo Fixer", skills=["INSTALL", "BREAK_FIX"])
    instrument = install_instrument(create_instrument(account, model="SEQ-5000"))
    requests = [
        create_service_request(instrument, account, severity="MEDIUM")
        for _ in range(5)
    ]
    for request in requests[:4]:
        dispatch_request(request)

    response = api_client.dispatch_service_request(requests[4]["id"], headers=DISPATCHER)
    validate_error(response, ApiErrorId.ERR_ENGINEER_CAPACITY_EXCEEDED)
    fifth = get_service_request(requests[4])
    assert fifth["status"] == "OPEN"
    assert fifth["engineer_id"] is None


def test_dispatch_no_eligible_engineer_rejected(api):
    """PRD section 3.5: "An empty eligible set fails the dispatch with
    `ERR_NO_ELIGIBLE_ENGINEER`" — the territory has an INSTALL engineer (the
    install succeeded) but nobody holding the BREAK_FIX skill.

    Design: Corner/cross_cutting_layers/dispatch_no_eligible_engineer_rejected
    """
    account = create_account(name="No Eng Lab", segment="INDUSTRIAL",
                             territory_code="TX-SOUTH")
    create_engineer(name="Installer Only", territory_code="TX-SOUTH",
                    skills=["INSTALL"])
    instrument = install_instrument(create_instrument(account, model="SEQ-5000"))
    request = create_service_request(instrument, account, severity="LOW")
    response = api_client.dispatch_service_request(request["id"], headers=DISPATCHER)
    validate_error(response, ApiErrorId.ERR_NO_ELIGIBLE_ENGINEER)
    fresh = get_service_request(request)
    assert fresh["status"] == "OPEN"


def test_resolve_by_unassigned_engineer_forbidden(api):
    """PRD section 2.1: "a FieldEngineer may resolve only those service
    requests whose `engineer_id` equals `X-User-ID`, and attempting to resolve
    a request assigned to a different engineer is rejected with
    `ERR_FORBIDDEN`."

    Design: Corner/rbac/resolve_by_unassigned_engineer_forbidden
    """
    account = create_account(name="Ownership Lab")
    first, second, instrument = _two_engineers_and_instrument(account)
    request = create_service_request(instrument, account, severity="LOW")
    dispatched = dispatch_request(request)
    assert dispatched["engineer_id"] == first["id"], (
        "both engineers tie at 0 open tickets; created_at picks the first"
    )

    response = api_client.resolve_service_request(
        request["id"],
        resolve_payload(1, parts_cost_cents=0),
        headers=make_field_engineer_headers(second["id"]),
    )
    validate_error(response, ApiErrorId.ERR_FORBIDDEN)
    fresh = get_service_request(request)
    assert fresh["status"] == "DISPATCHED"


def test_engineer_cannot_dispatch_forbidden(api):
    """PRD section 3.5: "Only a `ServiceDispatcher` or `PlatformAdmin`
    dispatches, and only from `OPEN` (`ERR_INVALID_STATE` otherwise)." and
    PRD section 2.1: "A request whose role is not among an endpoint's
    authorized roles, or that violates an ownership rule, is rejected with
    `ERR_FORBIDDEN` (HTTP 403)."

    Design: Corner/rbac/engineer_cannot_dispatch_forbidden
    """
    account = create_account(name="Dispatch RBAC Lab")
    engineer = create_engineer(name="Fixer", skills=["INSTALL", "BREAK_FIX"])
    instrument = install_instrument(create_instrument(account, model="SEQ-5000"))
    request = create_service_request(instrument, account, severity="LOW")

    response = api_client.dispatch_service_request(
        request["id"], headers=make_field_engineer_headers(engineer["id"])
    )
    validate_error(response, ApiErrorId.ERR_FORBIDDEN)
    fresh = get_service_request(request)
    assert fresh["status"] == "OPEN"
    assert fresh["engineer_id"] is None
