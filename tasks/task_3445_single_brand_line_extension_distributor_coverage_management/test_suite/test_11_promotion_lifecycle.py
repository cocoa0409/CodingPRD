"""Promotion lifecycle: submission/approval roles and segregation, the clock
sweep (LIVE/ENDED), and the posture-driven SUSPENDED round trip."""
from test_helpers import (
    ApiErrorId, TEST_USERS, api_client, make_marketing_manager_headers,
    validate_error, validate_success,
)
from test_helpers import fixtures as fx

CA = TEST_USERS["compliance_auditor_headers"]
CM = TEST_USERS["channel_manager_headers"]
MM = TEST_USERS["marketing_manager_headers"]
TSO = TEST_USERS["trade_secret_officer_headers"]


def test_promo_approve_state_error_trumps_depth_fiscal_error():
    """PRD §2.6: "Every request is evaluated against an ordered validation pipeline, and the first failing check determines the error returned — later checks are never reached once an earlier one fails."
    PRD §2.6: "8. **State-machine admissibility.** The target resource's own state machine must admit the requested transition (`ERR_INVALID_STATE_TRANSITION`, 409; with the dedicated wrong-from-state errors `ERR_RENEWAL_WINDOW_NOT_OPEN`, `ERR_REGISTRATION_EXPIRED`, `ERR_DISTRIBUTOR_NOT_APPROVED` and `ERR_PROMO_WINDOW_CLOSED` where §3 assigns them)."
    PRD §2.6: "13. **Fiscal gates, evaluated last.** The equity budget, the core-identity floor, the promotion depth cap, price-list presence and the advertised-price floor at approval, promotion frequency then gap, and the redemption budget (`ERR_EQUITY_BUDGET_EXCEEDED`, `ERR_CORE_IDENTITY_DILUTION`, `ERR_PROMO_DEPTH_EXCEEDS_CAP`, `ERR_BELOW_MAP_PRICE`, `ERR_PROMO_TOO_FREQUENT`, `ERR_PROMO_GAP_VIOLATION`, `ERR_PROMO_BUDGET_EXCEEDED`)."
    PRD §3.8: "the promotion starts in `DRAFT` with `accrued_funding_cents` and `redemptions_count` at 0, `unit_funding_provisional_cents` null, and `approved_by_user_id` unset."

    Design: Difficulty/priority_pair_validation_conflict/promo_approve_state_error_trumps_depth_fiscal_error
    """
    sc = fx.setup_launched_line()
    promo = fx.create_promotion_record(
        sc["line"]["id"], discount_pct=30.00, starts_on="2026-10-01",
        ends_on="2026-10-31", funding_budget_cents=100000)  # stays DRAFT

    resp = api_client.approve_promotion(promo["id"], MM)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE_TRANSITION)

    after = validate_success(api_client.get_promotion(promo["id"], MM))
    assert after["status"] == "DRAFT"
    assert after["unit_funding_provisional_cents"] is None


def test_promotion_sweep_live_then_ended():
    """PRD §2.4: "Promotions move `APPROVED` → `LIVE` when the current date reaches `starts_on` while not past `ends_on`, and `APPROVED` or `LIVE` → `ENDED` once the current date passes `ends_on`. The sweep never ends a `SUSPENDED` promotion."

    Design: Corner/state_machines/promotion_sweep_live_then_ended
    """
    sc = fx.setup_approved_promotion()  # window 2026-10-01..2026-10-31, future
    assert sc["promotion"]["status"] == "APPROVED"
    promo_id = sc["promotion"]["id"]

    fx.advance_clock("2026-10-05T00:00:00Z")
    live = validate_success(api_client.get_promotion(promo_id, MM))
    assert live["status"] == "LIVE"

    fx.advance_clock("2026-11-01T00:00:00Z")
    ended = validate_success(api_client.get_promotion(promo_id, MM))
    assert ended["status"] == "ENDED", \
        "2026-10-31 was the last live day; the sweep ended it"


def test_suspended_promotion_survives_sweep_and_resume_after_window_closed():
    """PRD §2.4: "The sweep never ends a `SUSPENDED` promotion."
    PRD §3.8: "Resuming is a `MarketingManager` act requiring the posture no longer `CRITICAL` (`ERR_POSTURE_CRITICAL`), the brand `OPERATING` (`ERR_BRAND_IN_LOCKDOWN`), and the current date not past `ends_on` (`ERR_PROMO_WINDOW_CLOSED`, HTTP 409)."
    PRD §3.1: "The posture is `CRITICAL` when at least two such breaches exist, or any single open case has `severity` 5, or the open-case severities sum to at least 10."

    Design: Corner/state_machines/suspended_promotion_survives_sweep_and_resume_after_window_closed
    """
    sc = fx.setup_live_promotion(promo_overrides={"ends_on": "2026-10-31"})
    promo_id = sc["promotion"]["id"]
    assert sc["promotion"]["status"] == "LIVE"
    market = fx.create_market()

    case = fx.create_counterfeit_case_record(sc["brand"]["id"], market["id"],
                                             severity=5)
    suspended = validate_success(api_client.get_promotion(promo_id, MM))
    assert suspended["status"] == "SUSPENDED", "the CRITICAL cascade fired"

    fx.advance_clock("2026-12-01T00:00:00Z")
    still = validate_success(api_client.get_promotion(promo_id, MM))
    assert still["status"] == "SUSPENDED", \
        "the sweep never ends a SUSPENDED promotion"

    validate_success(api_client.close_counterfeit_case(case["id"], CA))
    resp = api_client.resume_promotion(promo_id, MM)
    validate_error(resp, ApiErrorId.ERR_PROMO_WINDOW_CLOSED)


def test_promo_suspend_resume_conserves_funding_headroom():
    """PRD §3.8: "The protection cascade of §3.1 and §3.9 can instead flip `LIVE` → `SUSPENDED` the moment the brand's posture becomes `CRITICAL`; `accrued_funding_cents` and `funding_budget_cents` are deliberately left untouched by that flip, and the sweep never ends a `SUSPENDED` promotion — one that outlives its window while suspended can only leave by resuming and then expiring."
    PRD §3.9: "Closing — from either `REPORTED` or `ACTION_TAKEN` — lands in `CLOSED` and recomputes the posture, but never auto-resumes suspended promotions: bringing them back is an explicit resume decision under §3.8."
    PRD §3.8: "On success `accrued_funding_cents` grows by the total and `redemptions_count` increments by one."

    Design: Difficulty/compensating_invariant/promo_suspend_resume_conserves_funding_headroom
    """
    sc = fx.setup_launched_line(price_overrides={"list_price_cents": 3000})
    sc = fx.setup_live_promotion(
        scenario=sc,
        promo_overrides={"discount_pct": 15.00, "funding_budget_cents": 10000})
    promo = sc["promotion"]
    assert promo["status"] == "LIVE"
    market = fx.create_market()

    redemption = validate_success(api_client.create_redemption(
        promo["id"], sc["pack"]["id"], 10, CM))
    assert redemption["unit_funding_cents"] == 450, \
        "round_half_up(3000 * 15.00 / 100)"
    assert redemption["accrued_funding_cents"] == 4500
    assert redemption["remaining_budget_cents"] == 5500

    case = fx.create_counterfeit_case_record(sc["brand"]["id"], market["id"],
                                             severity=5, units_seized=40)
    brand = validate_success(api_client.get_brand(sc["brand"]["id"], CA))
    assert brand["protection_posture"] == "CRITICAL"
    suspended = validate_success(api_client.get_promotion(promo["id"], MM))
    assert suspended["status"] == "SUSPENDED"
    assert suspended["accrued_funding_cents"] == 4500, \
        "the suspension left accrued funding untouched"
    assert suspended["funding_budget_cents"] == 10000

    validate_success(api_client.take_action_counterfeit_case(case["id"], 40, CA))
    validate_success(api_client.close_counterfeit_case(case["id"], CA))
    restored = validate_success(api_client.get_brand(sc["brand"]["id"], CA))
    assert restored["protection_posture"] == "NORMAL"
    not_resumed = validate_success(api_client.get_promotion(promo["id"], MM))
    assert not_resumed["status"] == "SUSPENDED", \
        "closing the case does not auto-resume the promotion"

    resumed = validate_success(api_client.resume_promotion(promo["id"], MM))
    assert resumed["status"] == "LIVE"
    assert resumed["accrued_funding_cents"] == 4500
    assert resumed["funding_budget_cents"] == 10000, \
        "headroom is exactly 5500, as before the incident"
    assert resumed["redemptions_count"] == 1, \
        "the suspend/resume round trip created no phantom redemptions"


def test_promotion_approver_must_differ_from_creator():
    """PRD §3.8: "Approval is a `MarketingManager` act and is deliberately segregated: the approver's `X-User-ID` must differ from `created_by_user_id` (`ERR_SEGREGATION_OF_DUTIES`, HTTP 403)."
    PRD §2.1: "`X-User-ID` is opaque but is recorded on each promotion as `created_by_user_id`."

    Design: Corner/validations/promotion_approver_must_differ_from_creator
    """
    sc = fx.setup_submitted_promotion()  # created by pa-1
    promo_id = sc["promotion"]["id"]
    assert sc["promotion"]["created_by_user_id"] == "pa-1"

    conflict = api_client.approve_promotion(
        promo_id, make_marketing_manager_headers("pa-1"))
    validate_error(conflict, ApiErrorId.ERR_SEGREGATION_OF_DUTIES)

    approved = api_client.approve_promotion(promo_id, MM)
    assert validate_success(approved)["status"] == "APPROVED", \
        "starts_on 2026-10-01 is in the future, so the promotion waits for the sweep"


def test_trade_secret_officer_cannot_approve_promotion():
    """PRD §2.1: "When the headers are valid but the caller's role is not among the roles authorized for the target endpoint, the request is rejected with `ERR_FORBIDDEN_FOR_ROLE` (HTTP 403)."
    PRD §2.1: "`MarketingManager` — approves and resumes promotions (segregated from their creator) and moderates consumer use cases (review, publish, retract)."

    Design: Corner/rbac/trade_secret_officer_cannot_approve_promotion
    """
    sc = fx.setup_submitted_promotion()
    promo_id = sc["promotion"]["id"]

    resp = api_client.approve_promotion(promo_id, TSO)
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN_FOR_ROLE)

    after = validate_success(api_client.get_promotion(promo_id, MM))
    assert after["status"] == "PENDING_APPROVAL"
