"""Refund-fraud scheme detection tests: preparer velocity over the trailing
7-day window, bank-product routing clusters, and the confirmation cascade
that suspends the preparer and re-holds their passed returns.

PRD section 3.7 (with the suspension filing gate of section 3.4).
"""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    assert_fraud_scheme_alert,
    create_active_config,
    create_preparer,
    create_return_payload,
    create_taxpayer,
    file_preparer_rt_returns,
    file_return,
    get_preparer,
    get_return,
    get_return_hold,
    list_preparer_alerts,
    list_scheme_alerts,
    make_fraud_analyst_headers,
    make_tax_preparer_headers,
    set_clock,
    validate_error,
    validate_success,
)

ADMIN = TEST_USERS["system_admin_headers"]
ANALYST = TEST_USERS["fraud_analyst_headers"]


def test_velocity_alert_fires_at_exactly_ten(api):
    """PRD section 3.7: "When the count reaches at least 10 — a count of
    exactly 10 fires — and no `FLAGGED` alert already exists for that
    preparer, the system creates a `FraudSchemeAlert` with `pattern_type`
    `PREPARER_NETWORK_VELOCITY`."
    PRD section 3.7: "The alert's `evidence` object records `return_ids`
    (the matching returns' ids ordered by `received_at` ascending, ties
    broken by `created_at` ascending), the `window_days` (7), and the
    `match_count`."

    Design: Corner/calculations/velocity_alert_fires_at_exactly_ten
    """
    set_clock("2027-02-01T00:00:00Z")
    create_active_config(model_version="MV-VEL")
    preparer = create_preparer()
    file_preparer_rt_returns(preparer["id"], 9)

    assert list_preparer_alerts(preparer["id"]) == [], (
        "Nine REFUND_TRANSFER filings sit below the velocity threshold"
    )

    tenth_taxpayer = create_taxpayer()
    resp = api.file_tax_return(
        create_return_payload(
            tenth_taxpayer["id"], preparer_id=preparer["id"],
            claimed_refund_cents=1000, bank_product="REFUND_TRANSFER",
            bank_account_fingerprint="fp-v10",
        ),
        make_tax_preparer_headers(preparer["id"]),
    )
    validate_success(resp, 201)

    alerts = list_preparer_alerts(preparer["id"])
    assert len(alerts) == 1
    alert = alerts[0]
    assert_fraud_scheme_alert(alert)
    assert alert["pattern_type"] == "PREPARER_NETWORK_VELOCITY"
    assert alert["status"] == "FLAGGED"
    assert alert["preparer_id"] == preparer["id"]
    assert alert["evidence"]["match_count"] == 10
    assert alert["evidence"]["window_days"] == 7
    assert len(alert["evidence"]["return_ids"]) == 10


def test_routing_cluster_alert_at_three_taxpayers(api):
    """PRD section 3.7: "When that distinct-taxpayer count reaches at least
    3 — exactly 3 fires — and no `FLAGGED` alert already exists carrying that
    fingerprint in its `evidence`, the system creates a `FraudSchemeAlert`
    with `pattern_type` `BANK_PRODUCT_CLUSTER` and a null `preparer_id`,
    since routing clusters span self-filers; its `evidence` lists the
    matching returns under `return_ids` with the same ordering, plus
    `window_days` and `match_count`."

    Design: Corner/calculations/routing_cluster_alert_at_three_taxpayers
    """
    set_clock("2027-02-01T00:00:00Z")
    create_active_config(model_version="MV-CL")
    taxpayers = [create_taxpayer() for _ in range(3)]

    for tp in taxpayers[:2]:
        file_return(
            tp["id"], claimed_refund_cents=1000,
            bank_product="REFUND_TRANSFER",
            bank_account_fingerprint="fp-cluster",
        )
    assert list_scheme_alerts({"pattern_type": "BANK_PRODUCT_CLUSTER"}) == [], (
        "Two taxpayers on one fingerprint sit below the routing threshold"
    )

    file_return(
        taxpayers[2]["id"], claimed_refund_cents=1000,
        bank_product="REFUND_TRANSFER",
        bank_account_fingerprint="fp-cluster",
    )

    alerts = list_scheme_alerts({"pattern_type": "BANK_PRODUCT_CLUSTER"})
    assert len(alerts) == 1
    alert = alerts[0]
    assert_fraud_scheme_alert(alert)
    assert alert["pattern_type"] == "BANK_PRODUCT_CLUSTER"
    assert alert["preparer_id"] is None
    assert alert["status"] == "FLAGGED"
    assert alert["evidence"]["match_count"] == 3
    assert len(alert["evidence"]["return_ids"]) == 3


def test_scheme_confirm_suspends_preparer_and_reholds_returns(api):
    """PRD section 3.7: "Confirmation of a preparer-linked alert carries the
    heaviest cascade in the system: the named preparer moves from `ACTIVE` to
    `SUSPENDED`, terminally, and every one of that preparer's returns
    currently sitting in `FILTER_PASSED` is pulled back to `FILTER_HELD`;
    for each such return that has no hold yet, a `FilterHold` is created in
    zone `FULL` with `reason_codes` exactly `[SCHEME_CONFIRMED]`, its
    `risk_score` and `model_version` copied from the return's own stamped
    values."
    PRD section 3.7: "Confirming an alert — permitted only from `FLAGGED`, as
    is clearing; either action against a decided alert is rejected with
    `ERR_INVALID_STATE` — moves it to `CONFIRMED_SCHEME` and stamps
    `confirmed_by_user_id` with the confirming analyst's `X-User-ID`."
    PRD section 3.4: "A filing that names a `SUSPENDED` preparer is rejected
    with `ERR_PREPARER_SUSPENDED` (HTTP 409)."

    Design: Corner/cross_cutting_complexity_layers/scheme_confirm_suspends_preparer_and_reholds_returns
    """
    set_clock("2027-02-01T00:00:00Z")
    create_active_config(model_version="MV-SCM")
    preparer = create_preparer()
    returns = file_preparer_rt_returns(preparer["id"], 10)

    alerts = list_preparer_alerts(preparer["id"])
    assert len(alerts) == 1
    alert_id = alerts[0]["id"]

    confirmed = validate_success(
        api.confirm_fraud_scheme_alert(
            alert_id, make_fraud_analyst_headers("analyst-9")
        ),
        200,
    )
    assert confirmed["status"] == "CONFIRMED_SCHEME"
    assert confirmed["confirmed_by_user_id"] == "analyst-9"

    assert get_preparer(preparer["id"])["status"] == "SUSPENDED"

    rtn10 = get_return(returns[9]["id"])
    assert rtn10["status"] == "FILTER_HELD"
    hold = get_return_hold(rtn10["id"])
    assert hold["status"] == "OPEN"
    assert hold["zone"] == "FULL"
    assert hold["reason_codes"] == ["SCHEME_CONFIRMED"]
    assert hold["risk_score"] == rtn10["risk_score"]
    assert hold["model_version"] == rtn10["scoring_model_version"]

    late_taxpayer = create_taxpayer()
    resp = api.file_tax_return(
        create_return_payload(
            late_taxpayer["id"], preparer_id=preparer["id"],
            claimed_refund_cents=1000, bank_product="REFUND_TRANSFER",
            bank_account_fingerprint="fp-s11",
        ),
        make_tax_preparer_headers(preparer["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_PREPARER_SUSPENDED)
