"""Restoration coverage: endorsement chain, stage caps, pinned evaluation order."""
from test_helpers import (
    TEST_USERS,
    get_policy,
    setup_active_policy,
    validate_success,
)

UW = TEST_USERS["underwriter_headers"]


def _setup_restoration(api, receipts_cents=600_000):
    """Active policy (agreed 4000000, EXCELLENT, RESTORATION use) plus a
    restoration project carrying the given receipts. Returns the ctx dict."""
    ctx = setup_active_policy(
        base_value_cents=3_200_000, proposed=4_000_000, condition_grade="EXCELLENT",
        primary_use="RESTORATION",
    )
    project = validate_success(
        api.create_restoration_project(
            ctx["vehicle"]["id"], {"policy_id": ctx["policy"]["id"]},
            ctx["member_headers"],
        ),
        expected_status=201,
    )
    ctx["project"] = project
    if receipts_cents:
        validate_success(
            api.submit_receipt(
                project["id"],
                {"amount_cents": receipts_cents, "receipt_ref": "rcpt-1"},
                ctx["member_headers"],
            )
        )
    return ctx


def test_restoration_endorsement_pinned_order_mode_c(api):
    """PRD §3.10: "then the stage cap is computed as the floor of the
    policy's `agreed_value_cents` times the stage's cap fraction — ten
    percent at `DISASSEMBLY`, twenty-five percent at `BODYWORK`, forty
    percent at `MECHANICAL`, fifty-five percent at `FINISH`; then the
    project's `endorsement_limit_cents` is the smaller of the receipts total
    and the stage cap while the project is `ACTIVE`, and zero otherwise; that
    limit is pushed onto the policy; the policy's `coverage_limit_cents`
    becomes its agreed value plus the endorsement; and finally the premium is
    recomputed against the new coverage limit."

    Design: Difficulty/combinatorial_formula/restoration_endorsement_pinned_order_mode_c
    """
    ctx = _setup_restoration(api, receipts_cents=600_000)
    project = ctx["project"]
    advanced = validate_success(api.advance_stage(project["id"], UW))
    assert advanced["stage"] == "BODYWORK"
    # min(600000, floor(4000000 * 0.25)) == min(600000, 1000000) == 600000
    assert advanced["endorsement_limit_cents"] == 600_000
    policy = get_policy(ctx["policy"]["id"])
    assert policy["coverage_limit_cents"] == 4_600_000
    # tier1 = round(4600000 * 0.009) = 41400; core = round(41400 * 1.00 * 0.95 * 1.00)
    #       = 39330; fee = round(600000 * 0.01) = 6000; premium = 45330
    assert policy["premium_cents"] == 45_330, (
        f"Premium after endorsement must be 45330, got {policy['premium_cents']}"
    )


def test_restoration_endorsement_pinned_order_coverage_chain(api):
    """PRD §3.10: "The endorsement limit follows a pinned evaluation order
    that makes an otherwise circular-looking dependency explicit: first the
    receipts total is summed; then the stage cap is computed as the floor of
    the policy's `agreed_value_cents` times the stage's cap fraction".

    Design: Difficulty/combinatorial_formula/restoration_endorsement_pinned_order_mode_c
    """
    ctx = _setup_restoration(api, receipts_cents=600_000)
    project = ctx["project"]
    # At DISASSEMBLY (10% cap over agreed 4000000 = 400000): cap binds.
    policy = get_policy(ctx["policy"]["id"])
    assert policy["endorsement_limit_cents"] == 400_000
    assert policy["coverage_limit_cents"] == 4_400_000
    # Advance to BODYWORK (25% cap = 1000000): receipts 600000 bind instead.
    advanced = validate_success(api.advance_stage(project["id"], UW))
    assert advanced["endorsement_limit_cents"] == 600_000
    policy = get_policy(ctx["policy"]["id"])
    assert policy["coverage_limit_cents"] == 4_600_000


def test_restoration_stage_cap_binding(api):
    """PRD §3.10: "then the stage cap is computed as the floor of the
    policy's `agreed_value_cents` times the stage's cap fraction — ten
    percent at `DISASSEMBLY`, twenty-five percent at `BODYWORK`, forty
    percent at `MECHANICAL`, fifty-five percent at `FINISH`; then the
    project's `endorsement_limit_cents` is the smaller of the receipts total
    and the stage cap while the project is `ACTIVE`, and zero otherwise".

    Design: Corner/calculations/restoration_stage_cap_binding
    """
    ctx = _setup_restoration(api, receipts_cents=0)
    project = ctx["project"]
    updated = validate_success(
        api.submit_receipt(
            project["id"], {"amount_cents": 600_000, "receipt_ref": "rcpt-cap"},
            ctx["member_headers"],
        )
    )
    # DISASSEMBLY cap: floor(4000000 * 0.10) = 400000 < receipts 600000 -> cap binds.
    assert updated["endorsement_limit_cents"] == 400_000, (
        f"Stage cap must bind at 400000, got {updated['endorsement_limit_cents']}"
    )
