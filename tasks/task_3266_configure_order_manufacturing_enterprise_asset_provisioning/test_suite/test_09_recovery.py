"""End-of-life recovery: estimated vs final credit variants, grade-keyed
finals, recoverability gate, and terminal-state lockdown."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    setup_delivered_asset,
    setup_built_order,
    make_customer_user_headers,
    get_success_data,
    validate_error,
    validate_success,
)

ADMIN = TEST_USERS["platform_admin_headers"]
MANAGER = TEST_USERS["account_manager_headers"]
OPS = TEST_USERS["factory_ops_headers"]


def test_recovery_credit_estimated_vs_final_on_asset(api):
    """PRD §3.9: "The estimated credit is a flat provisional figure: 30 percent
    of the asset's order-line unit price at order time, rounded half up to
    whole cents. Receiving the returned unit — permitted only while the asset
    is `RECOVERY_REQUESTED` — moves the request from `LABEL_ISSUED` to
    `RECEIVED`, records the intake `grade`, and computes the
    `final_credit_cents` from the graded condition: 10 percent of the original
    unit price for a unit graded poor, 25 percent for fair, 45 percent for
    good, each rounded half up to whole cents."

    Design: Difficulty/dual_variant_calc/recovery_credit_estimated_vs_final_on_asset
    """
    env = setup_delivered_asset()
    account = env["account"]
    asset = env["assets"][0]
    resp = api.create_recovery_request(
        {"account_id": account["id"], "asset_id": asset["id"], "program_kind": "RESALE_CREDIT"},
        make_customer_user_headers(account["id"]),
    )
    rr = validate_success(resp, 201)
    resp = api.issue_recovery_label(rr["id"], ADMIN)
    rr = validate_success(resp, 200)
    assert rr["estimated_credit_cents"] == 36_000  # 0.30 x 120000
    resp = api.receive_recovery(rr["id"], {"grade": "good"}, ADMIN)
    rr = validate_success(resp, 200)
    assert rr["final_credit_cents"] == 54_000  # 0.45 x 120000
    assert rr["estimated_credit_cents"] != rr["final_credit_cents"]


def test_recovery_estimated_credit_flat_thirty_percent(api):
    """PRD §3.9: "The estimated credit is a flat provisional figure: 30 percent
    of the asset's order-line unit price at order time, rounded half up to
    whole cents."

    Design: Difficulty/dual_variant_calc/recovery_credit_estimated_vs_final_on_asset
    """
    env = setup_delivered_asset()
    account = env["account"]
    asset = env["assets"][0]
    rr = get_success_data(api.create_recovery_request(
        {"account_id": account["id"], "asset_id": asset["id"], "program_kind": "RECYCLE"},
        make_customer_user_headers(account["id"]),
    ))
    rr = get_success_data(api.issue_recovery_label(rr["id"], ADMIN))
    assert rr["estimated_credit_cents"] == 36_000
    asset_after = get_success_data(api.get_asset(asset["id"], ADMIN))
    assert asset_after["status"] == "RECOVERY_REQUESTED"


def test_recovery_grade_poor_final_credit(api):
    """PRD §3.9: "Receiving the returned unit — permitted only while the asset
    is `RECOVERY_REQUESTED` — moves the request from `LABEL_ISSUED` to
    `RECEIVED`, records the intake `grade`, and computes the
    `final_credit_cents` from the graded condition: 10 percent of the original
    unit price for a unit graded poor, 25 percent for fair, 45 percent for
    good, each rounded half up to whole cents."
    PRD §3.9: "For `RESALE_CREDIT`, posting the credit moves the request from
    `RECEIVED` to `CREDITED`, adds the `final_credit_cents` to the account's
    `recovery_credit_cents`, leaves `outstanding_cents` untouched, and moves
    the asset to `RECOVERED`."

    Design: Corner/calculations/recovery_grade_poor_final_credit
    """
    env = setup_delivered_asset()
    account = env["account"]
    asset = env["assets"][0]
    rr = get_success_data(api.create_recovery_request(
        {"account_id": account["id"], "asset_id": asset["id"], "program_kind": "RESALE_CREDIT"},
        make_customer_user_headers(account["id"]),
    ))
    api.issue_recovery_label(rr["id"], ADMIN)
    resp = api.receive_recovery(rr["id"], {"grade": "poor"}, ADMIN)
    rr = validate_success(resp, 200)
    assert rr["final_credit_cents"] == 12_000  # 0.10 x 120000
    resp = api.credit_recovery(rr["id"], ADMIN)
    rr = validate_success(resp, 200)
    assert rr["status"] == "CREDITED"
    account_after = get_success_data(api.get_account(account["id"], ADMIN))
    assert account_after["recovery_credit_cents"] == 12_000


def test_recovery_for_non_delivered_asset_rejected(api):
    """PRD §3.9: "The asset must currently be in `DELIVERED` status; a recovery
    request against any other asset status is rejected with
    `ERR_ASSET_NOT_RECOVERABLE` (HTTP 422)."

    Design: Corner/validations/recovery_for_non_delivered_asset_rejected
    """
    env = setup_built_order()
    account = env["account"]
    # Asset minted STAGED but never shipped.
    assets = get_success_data(api.list_line_assets(
        env["line"]["id"], make_customer_user_headers(account["id"])))
    asset = assets[0]
    assert asset["status"] == "STAGED"
    resp = api.create_recovery_request(
        {"account_id": account["id"], "asset_id": asset["id"], "program_kind": "RECYCLE"},
        make_customer_user_headers(account["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_ASSET_NOT_RECOVERABLE.value, 422)


def test_recycle_recovery_request_is_terminal_for_credit(api):
    """PRD §3.9: "For `RECYCLE`, recycling moves the request from `RECEIVED` to
    `RECYCLED` and likewise moves the asset to `RECOVERED`, with no credit
    posted. `CREDITED`, `RECYCLED`, and `CANCELLED` are the request's terminal
    states; the asset's own terminal resting place after any completed recovery
    is `RECOVERED`, and its full lifecycle runs `STAGED` to `IN_TRANSIT` to
    `DELIVERED` to `RECOVERY_REQUESTED` to `RECOVERED`."
    PRD §2.9: "then state-machine legality (the target resource is not in a
    state from which the requested transition is defined, `ERR_INVALID_STATE`)."

    Design: Corner/state_machines/recycle_recovery_request_is_terminal_for_credit
    """
    env = setup_delivered_asset()
    account = env["account"]
    asset = env["assets"][0]
    rr = get_success_data(api.create_recovery_request(
        {"account_id": account["id"], "asset_id": asset["id"], "program_kind": "RECYCLE"},
        make_customer_user_headers(account["id"]),
    ))
    api.issue_recovery_label(rr["id"], ADMIN)
    api.receive_recovery(rr["id"], {"grade": "poor"}, ADMIN)
    resp = api.recycle_recovery(rr["id"], ADMIN)
    rr = validate_success(resp, 200)
    assert rr["status"] == "RECYCLED"
    resp = api.credit_recovery(rr["id"], ADMIN)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value, 409)
    account_after = get_success_data(api.get_account(account["id"], ADMIN))
    assert account_after["recovery_credit_cents"] == 0
