"""Endpoint-surface claims: clock default, action visibility, computed reads."""

from test_helpers import (
    ADMIN,
    ANALYST,
    ASSOCIATE,
    LOGICAL_CLOCK_START,
    api_client,
    get_success_data,
    reset_clock,
    setup_approved_customer,
    setup_customer,
    setup_diamond,
    setup_purchase,
    setup_regulation,
    setup_registry_row,
    setup_store,
    validate_error,
    validate_success,
)


def test_clock_default_reads_the_fixed_startup_instant_before_any_set(
        api, sales_associate_headers):
    """PRD §2.16: "Before any call it reads the fixed startup default `2026-09-01T00:00:00Z` and never falls back to real wall-clock time."
    PRD §3.1: "sets `decision_status` to `PENDING`, and sets `expires_at` to the creation instant plus the chain's declared validity period in hours (`DECISION_VALIDITY_HOURS`)"

    Design: Corner/endpoints/clock_default_reads_the_fixed_startup_instant_before_any_set
    """
    store = setup_store()
    setup_regulation()
    setup_registry_row(registry_key="TX", credit_tier="TIER_1", base_limit_cents=400_000,
                       min_down_payment_pct=0.20, min_ticket_cents=200_000)
    customer = setup_customer()

    application = validate_success(api.create_credit_application({
        "customer_id": customer["id"], "store_id": store["id"],
        "requested_limit_cents": 250_000,
        "requested_purchase_amount_cents": 250_000, "down_payment_cents": 50_000,
    }, sales_associate_headers), 201)

    assert application["created_at"] == "2026-09-01T00:00:00.000Z", (
        "no clock call was issued, so the fixed startup default governs"
    )
    assert application["expires_at"] > application["created_at"], (
        "the validity window derives from the default instant, not from today"
    )
    assert application["decision_status"] == "PENDING"


def test_activate_store_side_effect_is_observable_on_read(api, chain_admin_headers):
    """PRD §3.4: "A store in `OPEN` moves to `ACTIVE` on activation, which requires at least one registry row available on its state code or the global fallback."
    PRD §2.14: "Priority 4 is state: the target resource must be in a state from which the requested transition is declared, else `ERR_INVALID_STATE` (409)."

    Design: Corner/endpoints/activate_store_side_effect_is_observable_on_read
    """
    reset_clock(LOGICAL_CLOCK_START)
    store = setup_store(activate=False)
    setup_registry_row(registry_key="TX", credit_tier="TIER_1", base_limit_cents=400_000,
                       min_down_payment_pct=0.20, min_ticket_cents=200_000)

    activated = validate_success(api.activate_store(store["id"], chain_admin_headers), 200)
    assert activated["store_status"] == "ACTIVE"
    assert activated["version"] == 2

    second = api.activate_store(store["id"], chain_admin_headers)
    validate_error(second, "ERR_INVALID_STATE", expected_status=409)
    unchanged = get_success_data(api.get_store(store["id"], chain_admin_headers))
    assert unchanged["version"] == 2, "the refused call advanced nothing"
    assert unchanged["store_status"] == "ACTIVE"


def test_trade_up_preview_reports_derived_figures_without_mutating_state(
        api, sales_associate_headers):
    """PRD §2.8: "an origin ticket of 450,018 gives a credit of 382,515."
    PRD §2.8: "a 900,100 cent ticket against a 450,018 cent origin gives a cap of 900,036, a credit of 383,370 (which is below the cap), a net amount of 516,730"

    Design: Corner/endpoints/trade_up_preview_reports_derived_figures_without_mutating_state
    """
    reset_clock(LOGICAL_CLOCK_START)
    customer, store, origin, new_purchase, _, _ = _trade_up_without_bonus()
    before = get_success_data(api.get_purchase(new_purchase["id"], sales_associate_headers))

    preview = validate_success(
        api.preview_trade_up(new_purchase["id"], sales_associate_headers), 200)
    assert preview["trade_up_credit_cents"] == 382_515, (
        "with no existing credit the two readings coincide"
    )
    assert preview["trade_up_floor_cents"] == 900_036
    assert preview["balance_due_cents"] == 900_100 - 382_515

    after = get_success_data(api.get_purchase(new_purchase["id"], sales_associate_headers))
    assert after["purchase_status"] == "PENDING", "the read mutated nothing"
    assert after["version"] == before["version"]


def test_the_preview_adds_the_protection_fee_to_the_balance_due(api, sales_associate_headers):
    """PRD §2.8: "`protection_fee_cents` is the attached bundle's `lifetime_plan_fee_cents`, or 0 when the purchase carries no bundle; on the trade-up preview the sum of `net_amount_cents` and `protection_fee_cents` is reported as `balance_due_cents`."
    PRD §2.8: "attaching a bundle whose lifetime fee is 19,900 raises the balance due to 536,630."

    Design: Corner/endpoints/trade_up_preview_reports_derived_figures_without_mutating_state
    """
    reset_clock(LOGICAL_CLOCK_START)
    customer, store, origin, new_purchase = _trade_up_with_bonus_credit()
    preview = validate_success(
        api.preview_trade_up(new_purchase["id"], sales_associate_headers), 200)
    assert preview["balance_due_cents"] == 536_630, (
        "the bundle's 19,900 lifetime fee is added to the net amount"
    )


def test_expire_due_sweep_is_idempotent_on_a_second_run(api, credit_analyst_headers,
                                                       sales_associate_headers):
    """PRD §3.1: "A validity sweep, run by a `CreditAnalyst`, retires applications nobody acted on. Every application still `PENDING` and every application `COUNTERED` at an instant strictly after its `expires_at` is set to `EXPIRED`, which is terminal alongside `DECLINED`."
    PRD §3.1: "The sweep reports `expired_count` and `expired_application_ids`."

    Design: Corner/endpoints/expire_due_sweep_is_idempotent_on_a_second_run
    """
    reset_clock(LOGICAL_CLOCK_START)
    store = setup_store()
    setup_regulation()
    setup_registry_row(registry_key="TX", credit_tier="TIER_1", base_limit_cents=400_000,
                       min_down_payment_pct=0.20, min_ticket_cents=200_000)
    customer = setup_customer()
    application = validate_success(api.create_credit_application({
        "customer_id": customer["id"], "store_id": store["id"],
        "requested_limit_cents": 250_000,
        "requested_purchase_amount_cents": 250_000, "down_payment_cents": 50_000,
    }, sales_associate_headers), 201)

    reset_clock("2026-09-15T00:00:00Z")
    first = validate_success(api.expire_credit_applications_due(credit_analyst_headers), 200)
    assert first["expired_count"] == 1
    expired = get_success_data(api.get_credit_application(
        application["id"], credit_analyst_headers))
    assert expired["decision_status"] == "EXPIRED"

    second = validate_success(api.expire_credit_applications_due(credit_analyst_headers), 200)
    assert second["expired_count"] == 0, (
        "EXPIRED is terminal, so the precondition excludes an already-expired row"
    )
    still_no_file = get_success_data(api.get_customer(customer["id"], credit_analyst_headers))
    assert still_no_file["account_status"] == "NO_FILE"


def _trade_up_without_bonus(with_bundle: bool = False):
    """Origin purchase at 450,018 with no stamped credit, plus a 900,100 trade-up."""
    customer, store, _ = setup_approved_customer(
        requested_limit_cents=1_500_000,
        requested_purchase_amount_cents=900_100, down_payment_cents=90_010)
    origin_diamond = setup_diamond(stone_code="ST-0001")
    origin = setup_purchase(customer, store, base_price_cents=450_018, diamond=origin_diamond)
    origin = get_success_data(api_client.complete_purchase(origin["id"], ASSOCIATE))
    payload = {
        "customer_id": customer["id"], "store_id": store["id"],
        "base_price_cents": 900_100, "origin_purchase_id": origin["id"],
    }
    if with_bundle:
        bundle = get_success_data(api_client.create_bundle({
            "bundle_code": "BUNDLE_180_TA", "display_name": "Lifetime Diamond 180",
            "lifetime_plan_fee_cents": 19_900, "stone_limit_labor_cents": 25_000,
            "stone_limit_parts_cents": 60_000, "inspection_interval_days": 180,
            "inspection_cure_days": 30,
        }, ADMIN), 201)
        payload["bundle_id"] = bundle["id"]
    new_purchase = get_success_data(api_client.create_purchase(payload, ASSOCIATE), 201)
    return customer, store, origin, new_purchase, origin_diamond, None

def _trade_up_with_bonus_credit():
    """The PRD §2.8 worked reference: a 450,018 origin already carrying a
    10,050 credit, plus a 900,100 trade-up that takes a 19,900 bundle.
    """
    from test_helpers import setup_trade_up_graph
    customer, store, origin, new_purchase, _, _ = setup_trade_up_graph(
        new_base_price_cents=900_100,
        origin_base_price_cents=450_018,
        additional_credit_cents=10_050,
        with_bundle=True,
    )
    return customer, store, origin, new_purchase


def test_inspection_visit_creation_returns_the_declared_envelope_fields(
        api, store_manager_headers):
    """PRD §3.3: "Logging a visit against a registration whose `version` has moved past what the client observed is rejected with `ERR_STALE_VERSION` (HTTP 412)."
    PRD §3.3: "or as a standing visit record with a `registration_id`, a `store_id`, a `visit_at`, a `result` of `SCHEDULED`, `CLAIMED`, or `NO_SHOW`, an optional `scheduled_for_at`, and the client's last observed `expected_registration_version`."

    Design: Corner/endpoints/inspection_visit_creation_returns_the_declared_envelope_fields
    """
    from test_helpers import setup_pending_registration

    reset_clock(LOGICAL_CLOCK_START)
    customer, store, diamond, bundle, purchase, registration = setup_pending_registration()
    reset_clock("2027-02-20T00:00:00Z")
    validate_success(api.run_inspection_reminders(store_manager_headers), 200)
    current = get_success_data(api.get_registration(registration["id"], store_manager_headers))

    # PRD §3.3 refuses a visit logged earlier than the registration's current
    # `inspection_due_at`, so the standing record is logged at the due instant.
    response = api.create_inspection_visit({
        "registration_id": registration["id"],
        "store_id": store["id"],
        "visit_at": current["inspection_due_at"],
        "result": "SCHEDULED",
        "expected_registration_version": current["version"],
    }, store_manager_headers)
    visit = validate_success(response, 201)
    body = response.json()

    assert body["response_type"] == "object"
    assert visit["inspection_status"] == "SCHEDULED"
    assert visit["claimed_at"] is None
    assert visit["result"] == "SCHEDULED"
    assert visit["visit_at"] == current["inspection_due_at"]
    assert body["meta"]["api_request_id"], "the success envelope carries a request id"
    assert body["meta"]["api_request_timestamp"]
