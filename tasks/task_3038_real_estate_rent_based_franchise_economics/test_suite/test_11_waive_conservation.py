"""Second coverage test for the repossession waive-conservation invariant."""
import test_helpers as th


def test_repossession_waive_conserves_versions_and_amounts(api, admin_headers, finance_headers):
    """PRD §3.8: "every one of the store's `OPEN` rent charges moves to
    `WAIVED`, every `OPEN` fund assessment moves to `WAIVED`, and every
    `ASSESSED` co-op assessment moves to `WAIVED`; every `PENDING` or
    `SUBMITTED` reinvestment obligation moves to `BREACHED`; and the operator
    moves to `TERMINATED` with `delinquency_balance_cents` recomputed — waived
    charges drop out of the delinquency sum."
    PRD §2.10: "each affected entity has its own `updated_at` refreshed and its
    own `version` incremented."

    Design: Difficulty/compensating_invariant/repossession_waive_conserves_store_charge_total
    """
    ctx = th.setup_open_store()
    charge = th.post_rent_charge(ctx["store"]["id"], ctx["sublease"]["id"])
    selected = charge["selected_rent_cents"]
    operator_mid = th.get_success_data(
        api.get_operator(ctx["operator"]["id"], finance_headers)
    )
    assert operator_mid["delinquency_balance_cents"] == selected

    event = th.declare_store_default(ctx)
    th.validate_success(api.repossess_default(event["id"], admin_headers))

    charge_after = th.get_success_data(api.get_rent_charge(charge["id"], finance_headers))
    assert charge_after["status"] == "WAIVED"
    # The billed amount survives on the waived charge (conserved, not lost).
    assert charge_after["selected_rent_cents"] == selected
    assert charge_after["version"] == charge["version"] + 1
    operator_after = th.get_success_data(
        api.get_operator(ctx["operator"]["id"], finance_headers)
    )
    assert operator_after["delinquency_balance_cents"] == 0
    assert operator_after["status"] == "TERMINATED"
