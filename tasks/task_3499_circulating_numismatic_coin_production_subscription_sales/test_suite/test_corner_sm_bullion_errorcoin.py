"""Corner coverage — bullion and error-coin state machines (PRD §3.4, §3.8):
the authorized-purchaser APPROVED/SUSPENDED/TERMINATED machine, the allocation
offer lifecycle (expiry field, eager clock sweep, confirm/settle state gates,
dealer ownership), and error-coin case creation bounds plus certified
destruction under segregation of duties."""

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    make_bullion_dealer_headers,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.assertions import (
    assert_authorized_purchaser,
    assert_bullion_allocation,
    assert_error_coin_case,
)
from test_helpers.factories import (
    create_error_coin_case_payload,
    destroy_payload,
    set_status_payload,
)
from test_helpers.fixtures import (
    create_allocation_offer,
    create_authorized_purchaser,
    create_completed_run,
    destroy_case,
    get_bullion_issue,
    set_ap_status,
    set_clock,
    setup_bullion_issue,
    setup_circulating_base,
    setup_quarantined_case,
)
from test_helpers.test_users import (
    DESTRUCTION_CERTIFIER_1_USER_ID,
    DESTRUCTION_CERTIFIER_2_USER_ID,
    DESTRUCTION_CERTIFIER_3_USER_ID,
    DESTRUCTION_CERTIFIER_4_USER_ID,
    QUALITY_INSPECTOR_USER_ID,
)

MANAGER = TEST_USERS["program_manager_headers"]
DIRECTOR = TEST_USERS["mint_director_headers"]
INSPECTOR = TEST_USERS["quality_inspector_headers"]
FINANCE_ALT = TEST_USERS["finance_officer_alt_headers"]
CERTIFIER = TEST_USERS["destruction_certifier_1_headers"]


def _get_allocation(api, allocation_id):
    return validate_success(api.get_allocation(allocation_id, MANAGER))


def _make_offered_allocation(api, *, quantity=50):
    """Issue (GOLD spot set, clock at 2026-09-10, 48h offer window) + one
    APPROVED purchaser + one OFFERED allocation. Returns (issue, ap, alloc)."""
    issue = setup_bullion_issue(api, clock_ts="2026-09-10T00:00:00Z",
                                name="AGE 2026", total_pool_units=1000,
                                offer_window_hours=48)
    ap = create_authorized_purchaser(api, name="Dealer", tier="T1")
    alloc, issue = create_allocation_offer(api, issue, ap, quantity)
    return issue, ap, alloc


def test_ap_suspend_reinstate_cycle(api):
    """PRD §3.8: "A `PlatformAdmin` registers each authorized purchaser with a
    firm `name` and a `tier` of `T1`, `T2`, or `T3` that drives the premium
    schedule; purchasers begin `APPROVED`. A `MintDirector` manages standing
    through set-status transitions carrying a `to_status`: `APPROVED ↔
    SUSPENDED` in both directions, and `APPROVED` or `SUSPENDED` to
    `TERMINATED`, which is terminal."

    Design: Corner/state_machines/ap_suspend_reinstate_cycle
    """
    ap = create_authorized_purchaser(api, name="Cycle Dealer", tier="T2")
    assert_authorized_purchaser(ap)
    assert ap["status"] == "APPROVED"

    ap = set_ap_status(api, ap["id"], "SUSPENDED")
    assert ap["status"] == "SUSPENDED"
    ap = set_ap_status(api, ap["id"], "APPROVED")
    assert ap["status"] == "APPROVED"


def test_ap_set_status_from_terminated_rejected(api):
    """PRD §3.8: "A `MintDirector` manages standing through set-status
    transitions carrying a `to_status`: `APPROVED ↔ SUSPENDED` in both
    directions, and `APPROVED` or `SUSPENDED` to `TERMINATED`, which is
    terminal. Any requested transition outside that declared set falls back to
    `ERR_INVALID_STATE_TRANSITION` (422)."

    Design: Corner/state_machines/ap_set_status_from_terminated_rejected
    """
    ap = create_authorized_purchaser(api, name="Terminal Dealer", tier="T3")
    ap = set_ap_status(api, ap["id"], "TERMINATED")
    assert ap["status"] == "TERMINATED"

    resp = api.set_authorized_purchaser_status(
        ap["id"], set_status_payload("APPROVED"), DIRECTOR)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE_TRANSITION)


def test_allocation_expiry_fields_and_sweep(api):
    """PRD §3.8: "A created offer decrements the issue's
    `remaining_pool_units` by the offered quantity, increments the issue's
    `version`, records `offered_by_user_id` from the manager's `X-User-ID`,
    fixes `offer_expires_at` as the current logical-clock instant plus the
    issue's `offer_window_hours`, and sits in `OFFERED` with
    `total_price_cents` still null."
    PRD §3.8: "When a clock-set sweep finds the logical clock at or past an
    `OFFERED` allocation's `offer_expires_at`, the allocation becomes
    `EXPIRED` — terminal — its `quantity_units` return to the issue's
    `remaining_pool_units`, an issue that had sold out returns to `ACTIVE`,
    and the issue's `version` increments."

    Design: Corner/state_machines/allocation_expiry_fields_and_sweep
    """
    issue, _, alloc = _make_offered_allocation(api, quantity=50)
    assert issue["remaining_pool_units"] == 950

    alloc = _get_allocation(api, alloc["id"])
    assert_bullion_allocation(alloc)
    assert alloc["status"] == "OFFERED"
    # 2026-09-10T00:00:00Z + 48h, rendered as the clock reads (domain family).
    assert alloc["offer_expires_at"] == "2026-09-12T00:00:00Z"
    assert alloc["total_price_cents"] is None

    # Landing exactly on the expiry instant expires the offer (inclusive).
    set_clock(api, "2026-09-12T00:00:00Z")
    alloc = _get_allocation(api, alloc["id"])
    assert alloc["status"] == "EXPIRED"
    issue = get_bullion_issue(api, issue["id"])
    assert issue["remaining_pool_units"] == 1000, (
        "the expired 50 units return to the pool")


def test_allocation_confirm_after_expiry_rejected(api):
    """PRD §3.8: "A `BullionDealer` confirms an allocation still in `OFFERED`
    — anything else is rejected with `ERR_ALLOCATION_NOT_CONFIRMABLE` (422) —
    with the caller's `X-User-ID` equal to the allocation's
    `authorized_purchaser_id` (`ERR_FORBIDDEN_OWNERSHIP`, 403), with the firm
    still `APPROVED` (`ERR_AP_NOT_APPROVED`, 422), and before
    `offer_expires_at`; because the clock sweep expires offers eagerly, a
    lapsed offer is already `EXPIRED` and fails the state check."

    Design: Corner/state_machines/allocation_confirm_after_expiry_rejected
    """
    _, ap, alloc = _make_offered_allocation(api, quantity=50)
    set_clock(api, "2026-09-13T00:00:00Z")  # past the 2026-09-12 expiry
    assert _get_allocation(api, alloc["id"])["status"] == "EXPIRED"

    resp = api.confirm_allocation(alloc["id"],
                                  make_bullion_dealer_headers(ap["id"]))
    validate_error(resp, ApiErrorId.ERR_ALLOCATION_NOT_CONFIRMABLE)


def test_allocation_settle_before_confirm_rejected(api):
    """PRD §3.8: "A `FinanceOfficer` settles a `CONFIRMED` allocation — any
    other state is rejected with `ERR_ALLOCATION_NOT_SETTLABLE` (422) — and
    segregation of duties forbids the settler's `X-User-ID` from matching the
    allocation's `offered_by_user_id` (`ERR_SEGREGATION_OF_DUTIES`, 422)."

    Design: Corner/state_machines/allocation_settle_before_confirm_rejected
    """
    _, _, alloc = _make_offered_allocation(api, quantity=50)
    assert alloc["status"] == "OFFERED"

    # The settler (fin-9) differs from the offering manager (pm-1), so only
    # the CONFIRMED-state gate can fire.
    resp = api.settle_allocation(alloc["id"], FINANCE_ALT)
    validate_error(resp, ApiErrorId.ERR_ALLOCATION_NOT_SETTLABLE)
    assert _get_allocation(api, alloc["id"])["status"] == "OFFERED"


def test_allocation_confirm_by_other_dealer_forbidden(api):
    """PRD §2.1: "When `X-User-Role` is `BullionDealer`, `X-User-ID` is the
    `id` of the acting `AuthorizedPurchaser`; the dealer may confirm only those
    allocations whose `authorized_purchaser_id` equals `X-User-ID`."
    PRD §2.1: "A violation of either ownership rule is rejected with
    `ERR_FORBIDDEN_OWNERSHIP` (HTTP 403)."

    Design: Corner/state_machines/allocation_confirm_by_other_dealer_forbidden
    """
    issue = setup_bullion_issue(api, clock_ts="2026-09-10T00:00:00Z",
                                name="AGE 2026", total_pool_units=1000,
                                offer_window_hours=48)
    ap1 = create_authorized_purchaser(api, name="Dealer One", tier="T1")
    ap2 = create_authorized_purchaser(api, name="Dealer Two", tier="T2")
    alloc, _ = create_allocation_offer(api, issue, ap1, 50)

    # The offer names ap1; a dealer acting as ap2 fails the ownership rung.
    resp = api.confirm_allocation(alloc["id"],
                                  make_bullion_dealer_headers(ap2["id"]))
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN_OWNERSHIP)
    assert _get_allocation(api, alloc["id"])["status"] == "OFFERED"


def test_ecc_create_exceeding_scrapped_rejected(api):
    """PRD §3.4: "When striking output reveals mint errors, a
    `QualityInspector` opens an error-coin case against the offending
    production run, supplying the `production_run_id`, an `error_pieces` count
    that is strictly positive and no greater than that run's `scrapped_pieces`
    at the moment of creation — a larger count is rejected with
    `ERR_ERRORCOIN_QUANTITY_EXCEEDS` (422) — and an optional `description` such
    as an off-center strike or a doubled die."

    Design: Corner/state_machines/ecc_create_exceeding_scrapped_rejected
    """
    _, _, fed_order = setup_circulating_base(api)
    run = create_completed_run(api, fed_order["id"], good_pieces=9800,
                               planned_quantity=10000)
    assert run["scrapped_pieces"] == 200  # 10000 reserved - 9800 good

    resp = api.create_error_coin_case(
        create_error_coin_case_payload(production_run_id=run["id"],
                                       error_pieces=201,
                                       description="off-center strikes"),
        INSPECTOR)
    validate_error(resp, ApiErrorId.ERR_ERRORCOIN_QUANTITY_EXCEEDS)


def test_ecc_destroy_certifier_is_reporter_rejected(api):
    """PRD §3.4: "A `DestructionCertifier` destroys a quarantined case by
    supplying a `primary_certifier_user_id` and a
    `secondary_certifier_user_id`; the two ids must differ from each other, and
    neither may equal the case's `reported_by_user_id` — any overlap is
    rejected with `ERR_SEGREGATION_OF_DUTIES` (422)."

    Design: Corner/state_machines/ecc_destroy_certifier_is_reporter_rejected
    """
    case, run, _, _, _ = setup_quarantined_case(api)
    assert case["reported_by_user_id"] == QUALITY_INSPECTOR_USER_ID

    resp = api.destroy_error_coin_case(
        case["id"],
        destroy_payload(QUALITY_INSPECTOR_USER_ID,
                        DESTRUCTION_CERTIFIER_2_USER_ID),
        CERTIFIER)
    validate_error(resp, ApiErrorId.ERR_SEGREGATION_OF_DUTIES)

    cases, _ = validate_paginated(api.list_error_coin_cases(run["id"], INSPECTOR))
    assert len(cases) == 1
    assert cases[0]["status"] == "QUARANTINED"


def test_ecc_destroy_duplicate_certifiers_rejected(api):
    """PRD §3.4: "A `DestructionCertifier` destroys a quarantined case by
    supplying a `primary_certifier_user_id` and a
    `secondary_certifier_user_id`; the two ids must differ from each other, and
    neither may equal the case's `reported_by_user_id` — any overlap is
    rejected with `ERR_SEGREGATION_OF_DUTIES` (422)."

    Design: Corner/state_machines/ecc_destroy_duplicate_certifiers_rejected
    """
    case, run, _, _, _ = setup_quarantined_case(api)

    resp = api.destroy_error_coin_case(
        case["id"],
        destroy_payload(DESTRUCTION_CERTIFIER_1_USER_ID,
                        DESTRUCTION_CERTIFIER_1_USER_ID),
        CERTIFIER)
    validate_error(resp, ApiErrorId.ERR_SEGREGATION_OF_DUTIES)

    cases, _ = validate_paginated(api.list_error_coin_cases(run["id"], INSPECTOR))
    assert len(cases) == 1
    assert cases[0]["status"] == "QUARANTINED"


def test_ecc_destroy_success_records_both_certifiers(api):
    """PRD §3.4: "A successful destruction records both ids in
    `destroyed_by_user_ids` and moves the case to its terminal `DESTROYED`
    state."

    Design: Corner/state_machines/ecc_destroy_success_records_both_certifiers
    """
    case, _, _, _, _ = setup_quarantined_case(api)
    assert case["status"] == "QUARANTINED"

    destroyed = destroy_case(api, case["id"], DESTRUCTION_CERTIFIER_1_USER_ID,
                             DESTRUCTION_CERTIFIER_2_USER_ID)
    assert_error_coin_case(destroyed)
    assert destroyed["status"] == "DESTROYED"
    assert destroyed["destroyed_by_user_ids"] == [
        DESTRUCTION_CERTIFIER_1_USER_ID, DESTRUCTION_CERTIFIER_2_USER_ID]


def test_ecc_double_destroy_rejected(api):
    """PRD §3.4: "A successful destruction records both ids in
    `destroyed_by_user_ids` and moves the case to its terminal `DESTROYED`
    state. Attempting destruction on a case already in `DESTROYED` is rejected
    with `ERR_CASE_ALREADY_DESTROYED` (422)."

    Design: Corner/state_machines/ecc_double_destroy_rejected
    """
    case, _, _, _, _ = setup_quarantined_case(api)
    destroy_case(api, case["id"], DESTRUCTION_CERTIFIER_1_USER_ID,
                 DESTRUCTION_CERTIFIER_2_USER_ID)

    resp = api.destroy_error_coin_case(
        case["id"],
        destroy_payload(DESTRUCTION_CERTIFIER_3_USER_ID,
                        DESTRUCTION_CERTIFIER_4_USER_ID),
        CERTIFIER)
    validate_error(resp, ApiErrorId.ERR_CASE_ALREADY_DESTROYED)
