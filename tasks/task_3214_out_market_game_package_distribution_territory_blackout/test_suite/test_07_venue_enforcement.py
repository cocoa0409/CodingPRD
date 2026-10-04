"""Commercial enforcement: venue fee tiers, occupancy cap, misuse flagging,
and account closure cascades."""
from test_helpers import (
    ApiErrorId,
    create_grant,
    create_venue_license,
    make_support_agent_headers,
    make_venue_manager_headers,
    register_account,
    set_clock,
    setup_week4_game_account_sub,
    validate_error,
    validate_success,
)


def _commercial_account(email, billing_zip="75001"):
    return register_account(
        email=email, full_name="Bar Owner", account_kind="COMMERCIAL",
        billing_zip=billing_zip,
    )


def test_occupancy_100_certifies_t1_and_101_certifies_t2(
    api, compliance_auditor_headers
):
    """PRD §3.8: "Certifying a `PENDING` license derives its `occupancy_tier`
    from the certified occupancy on fixed boundaries: occupancy from 1 through
    100 inclusive is tier `T1`, from 101 through 500 inclusive is `T2`, and
    501 or more is `T3` — so an occupancy of exactly 100 is `T1`, exactly 101
    is `T2`, exactly 500 is `T2`, and exactly 501 is `T3`."

    Design: Difficulty/boundary_precision_check/venue_fee_tier_boundary_100_101
    """
    set_clock("2026-09-01T00:00:00Z")
    create_grant()
    acct_100 = _commercial_account("bar100@x.com")
    acct_101 = _commercial_account("bar101@x.com")
    lic_100 = create_venue_license(acct_100["id"], venue_name="Bar 100",
                                   fire_code_occupancy=100)
    lic_101 = create_venue_license(acct_101["id"], venue_name="Bar 101",
                                   fire_code_occupancy=101)

    certified_100 = validate_success(
        api.certify_venue_license(lic_100["id"], compliance_auditor_headers)
    )
    assert certified_100["occupancy_tier"] == "T1"

    certified_101 = validate_success(
        api.certify_venue_license(lic_101["id"], compliance_auditor_headers)
    )
    assert certified_101["occupancy_tier"] == "T2"


def test_certification_snapshots_fee_with_tier(api, compliance_auditor_headers):
    """PRD §3.8: "The `annual_fee_cents` is derived together with the tier:
    `T1` carries an annual fee of 500000 cents (five thousand dollars), `T2`
    carries 2000000 cents (twenty thousand dollars), and `T3` carries 6000000
    cents (sixty thousand dollars)."

    Design: Difficulty/boundary_precision_check/venue_fee_tier_boundary_100_101
    """
    set_clock("2026-09-01T00:00:00Z")
    create_grant()
    acct_100 = _commercial_account("fee100@x.com")
    acct_101 = _commercial_account("fee101@x.com")
    lic_100 = create_venue_license(acct_100["id"], venue_name="Bar 100",
                                   fire_code_occupancy=100)
    lic_101 = create_venue_license(acct_101["id"], venue_name="Bar 101",
                                   fire_code_occupancy=101)

    certified_100 = validate_success(
        api.certify_venue_license(lic_100["id"], compliance_auditor_headers)
    )
    assert certified_100["annual_fee_cents"] == 500000

    certified_101 = validate_success(
        api.certify_venue_license(lic_101["id"], compliance_auditor_headers)
    )
    assert certified_101["annual_fee_cents"] == 2000000


def test_occupancy_at_cap_admitted_above_cap_rejected(
    api, compliance_auditor_headers
):
    """PRD §3.8: "The occupancy must be greater than zero and may not exceed
    the `max_commercial_occupancy_cap` of the grant that parents the account's
    activity — a violation either way is `ERR_OCCUPANCY_CAP_EXCEEDED` (HTTP
    422), checked again at certify and recertify."

    Design: Corner/cross_cutting_layers/occupancy_cap_and_commercial_flag_enforcement
    """
    set_clock("2026-09-01T00:00:00Z")
    create_grant(max_commercial_occupancy_cap=2000)
    acct = _commercial_account("cap@x.com")

    resp = api.create_venue_license(
        {
            "account_id": acct["id"],
            "venue_name": "Too Big",
            "venue_zip": "75001",
            "fire_code_occupancy": 2001,
        },
        make_venue_manager_headers(acct["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_OCCUPANCY_CAP_EXCEEDED)

    lic_ok = create_venue_license(acct["id"], venue_name="Just Right",
                                  fire_code_occupancy=2000)
    assert lic_ok["status"] == "PENDING"


def test_misuse_flag_suspends_entitlements_without_cancelling_billing(
    api, compliance_auditor_headers, platform_admin_headers
):
    """PRD §3.8: "flagging commercial misuse moves the account `ACTIVE` →
    `SUSPENDED`, recording the request's `reason` as `commercial_flag_reason`,
    and immediately suspends access without touching billing: every `ACTIVE`
    subscription of the account has its `entitlement_state` pushed to
    `SUSPENDED` while its lifecycle `status` is left unchanged."

    Design: Corner/cross_cutting_layers/occupancy_cap_and_commercial_flag_enforcement
    """
    ctx = setup_week4_game_account_sub(email="misuse@x.com", billing_zip="10001",
                                       markets=("DAL", "NYC"))
    flagged = validate_success(
        api.flag_commercial_misuse(
            ctx["account"]["id"], "charging admission",
            compliance_auditor_headers,
        )
    )
    assert flagged["status"] == "SUSPENDED"
    assert flagged["commercial_flag_reason"] == "charging admission"

    sub_now = validate_success(
        api.get_subscription(ctx["subscription"]["id"], platform_admin_headers)
    )
    assert sub_now["status"] == "ACTIVE"
    assert sub_now["entitlement_state"] == "SUSPENDED"

    check = validate_success(
        api.create_territory_check(
            ctx["account"]["id"], ctx["subscription"]["id"],
            ctx["games"][0]["id"], "10001",
            make_support_agent_headers("sa-jane"),
        ),
        expected_status=201,
    )
    assert check["verdict"] == "NO_ENTITLEMENT"


def test_clearing_flag_restores_suspended_entitlements(
    api, compliance_auditor_headers, platform_admin_headers
):
    """PRD §3.8: "Clearing the flag moves `SUSPENDED` → `ACTIVE`, nulls
    `commercial_flag_reason`, and restores every `ACTIVE` subscription whose
    `entitlement_state` is `SUSPENDED` back to `ENABLED` — but does not
    resurrect any `WITHDRAWN` entitlement."

    Design: Corner/cross_cutting_layers/occupancy_cap_and_commercial_flag_enforcement
    """
    ctx = setup_week4_game_account_sub(email="restore@x.com", billing_zip="10001")
    validate_success(
        api.flag_commercial_misuse(
            ctx["account"]["id"], "charging admission",
            compliance_auditor_headers,
        )
    )
    cleared = validate_success(
        api.clear_commercial_flag(ctx["account"]["id"], compliance_auditor_headers)
    )
    assert cleared["status"] == "ACTIVE"
    assert cleared["commercial_flag_reason"] is None

    sub_now = validate_success(
        api.get_subscription(ctx["subscription"]["id"], platform_admin_headers)
    )
    assert sub_now["status"] == "ACTIVE"
    assert sub_now["entitlement_state"] == "ENABLED"
