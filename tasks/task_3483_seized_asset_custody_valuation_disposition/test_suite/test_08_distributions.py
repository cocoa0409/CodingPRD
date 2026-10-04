"""Equitable-share distributions: the forfeiture gate, the amount floor and
pool boundary, segregation of duties, and the approve/rescind conservation
invariant."""

from test_helpers import (
    ApiErrorId,
    FUND_ADMINISTRATOR_USER_ID,
    SECOND_FUND_ADMINISTRATOR_USER_ID,
    TEST_USERS,
    approve_distribution,
    create_case,
    create_case_in_state,
    create_distribution,
    create_distribution_payload,
    create_settled_sale,
    file_forfeiture,
    forfeit_case,
    get_case,
    make_fund_administrator_headers,
    rescind_distribution,
    validate_error,
)


def test_distribution_requires_case_forfeited(api):
    """PRD §3.7: "Creation requires the case to be `FORFEITED`
    (`ERR_CASE_NOT_FORFEITED` otherwise)"
    PRD §3.7: "Manually created distributions are always of
    `distribution_kind` `EQUITABLE_SHARE`"
    PRD §3.7: "A new distribution stands at `PENDING`"

    Design: Difficulty/cross_entity_state_dependency/distribution_requires_case_forfeited
    """
    case = create_case(
        case_number="26-MJ-0014", judicial_district="D. Idaho",
        forfeiture_type="ADMINISTRATIVE", lead_agency_code="USPS",
    )
    file_forfeiture(case["id"])
    early = api.create_distribution(
        create_distribution_payload(
            case["id"], payee_ref="ID-STATE-POLICE", amount_cents=50_000,
            usage_restriction="EQUIPMENT",
        ),
        TEST_USERS["fund_administrator_headers"],
    )
    validate_error(early, ApiErrorId.ERR_CASE_NOT_FORFEITED)
    assert early.status_code == 409, (
        "the case stands at FORFEITURE_PENDING, not FORFEITED"
    )

    forfeit_case(case["id"])
    # Stock the pool: a 100000 sale at a 10000 fee leaves 90000 available.
    create_settled_sale(
        case_id=case["id"], raw_value_cents=100_000, grade="EXCELLENT",
        asset_type="PERSONAL_PROPERTY", description="coin lot",
        winning_bid_cents=100_000, auctioneer_ref="auc-2",
        slot_start="2026-09-06T10:00:00Z", slot_end="2026-09-06T12:00:00Z",
    )
    dist = create_distribution(
        case["id"], amount_cents=50_000, payee_ref="ID-STATE-POLICE",
        usage_restriction="EQUIPMENT",
    )
    assert dist["status"] == "PENDING"
    assert dist["distribution_kind"] == "EQUITABLE_SHARE"
    assert get_case(case["id"])["available_proceeds_cents"] == 90_000, (
        "a pending distribution does not debit the pool"
    )


def test_distribution_rejections_and_exact_pool_boundary(api):
    """PRD §3.7: "the amount to be at least 10,000 cents ($100) — the
    statutory floor, below which creation is rejected with
    `ERR_SHARE_BELOW_MINIMUM` — and the amount to be no more than the case's
    `available_proceeds_cents` (`ERR_INSUFFICIENT_PROCEEDS` otherwise)."
    PRD §3.7: "Approval moves the distribution from `PENDING` to `PAID` ...
    adds the `amount_cents` to the case's `equitable_shares_paid_cents`,
    rederives `available_proceeds_cents` as the net sharing basis minus that
    paid total"

    Design: Corner/errors/distribution_rejections_and_exact_pool_boundary
    """
    case = create_case_in_state(
        "FORFEITED", case_number="26-MJ-1023", judicial_district="D. Idaho",
        forfeiture_type="ADMINISTRATIVE", lead_agency_code="USPS",
    )
    # Pool of exactly 90000 (gross 100000, fee 10000, no liens or costs).
    create_settled_sale(
        case_id=case["id"], raw_value_cents=100_000, grade="EXCELLENT",
        asset_type="PERSONAL_PROPERTY", description="stamp collection",
        winning_bid_cents=100_000, auctioneer_ref="auc-12",
    )

    below = api.create_distribution(
        create_distribution_payload(
            case["id"], payee_ref="ID-STATE-POLICE", amount_cents=9_999,
            usage_restriction="EQUIPMENT",
        ),
        make_fund_administrator_headers(SECOND_FUND_ADMINISTRATOR_USER_ID),
    )
    validate_error(below, ApiErrorId.ERR_SHARE_BELOW_MINIMUM)
    assert below.status_code == 422

    over = api.create_distribution(
        create_distribution_payload(
            case["id"], payee_ref="ID-STATE-POLICE", amount_cents=90_001,
            usage_restriction="EQUIPMENT",
        ),
        make_fund_administrator_headers(SECOND_FUND_ADMINISTRATOR_USER_ID),
    )
    validate_error(over, ApiErrorId.ERR_INSUFFICIENT_PROCEEDS)
    assert over.status_code == 422, "one cent over the 90000 pool"

    dist = create_distribution(
        case["id"], amount_cents=90_000, payee_ref="ID-STATE-POLICE",
        usage_restriction="EQUIPMENT",
        creator_user_id=SECOND_FUND_ADMINISTRATOR_USER_ID,
    )
    assert dist["status"] == "PENDING", "exactly the pool boundary admits"
    approved = approve_distribution(
        dist["id"], approver_user_id=FUND_ADMINISTRATOR_USER_ID
    )
    assert approved["status"] == "PAID"
    assert get_case(case["id"])["available_proceeds_cents"] == 0, (
        "the exact-pool boundary drains to zero without going negative"
    )


def test_distribution_creator_cannot_approve_own_distribution(api):
    """PRD §3.7: "the approving `FundAdministrator`'s `X-User-ID` must differ
    from the recorded `created_by_user_id`, with self-approval rejected as
    `ERR_SOD_VIOLATION`."
    PRD §3.7: "Approval moves the distribution from `PENDING` to `PAID`,
    records the approver as `approved_by_user_id`, adds the `amount_cents` to
    the case's `equitable_shares_paid_cents`"

    Design: Corner/rbac/distribution_creator_cannot_approve_own_distribution
    """
    case = create_case_in_state(
        "FORFEITED", case_number="26-MJ-1033", judicial_district="D. Idaho",
        forfeiture_type="ADMINISTRATIVE", lead_agency_code="USPS",
    )
    create_settled_sale(
        case_id=case["id"], raw_value_cents=100_000, grade="EXCELLENT",
        asset_type="PERSONAL_PROPERTY", description="jewelry lot",
        winning_bid_cents=100_000, auctioneer_ref="auc-15",
    )
    dist = create_distribution(
        case["id"], amount_cents=50_000, payee_ref="ID-STATE-POLICE",
        usage_restriction="OVERTIME",
        creator_user_id=SECOND_FUND_ADMINISTRATOR_USER_ID,
    )

    sod = api.approve_distribution(
        dist["id"],
        make_fund_administrator_headers(SECOND_FUND_ADMINISTRATOR_USER_ID),
    )
    validate_error(sod, ApiErrorId.ERR_SOD_VIOLATION)
    assert sod.status_code == 403, "the creator cannot self-approve"

    paid = approve_distribution(
        dist["id"], approver_user_id=FUND_ADMINISTRATOR_USER_ID
    )
    assert paid["status"] == "PAID"
    assert paid["created_by_user_id"] == SECOND_FUND_ADMINISTRATOR_USER_ID
    assert paid["approved_by_user_id"] == FUND_ADMINISTRATOR_USER_ID

    final_case = get_case(case["id"])
    assert final_case["available_proceeds_cents"] == 40_000
    assert final_case["equitable_shares_paid_cents"] == 50_000


def test_distribution_approve_rescind_pool_invariant(api):
    """PRD §3.7: "Approve and rescind therefore conserve the case's pool
    exactly"
    PRD §3.7: "Rescinding a paid distribution is the compensating half of the
    pair: the `amount_cents` is subtracted back out of the case's
    `equitable_shares_paid_cents`, `available_proceeds_cents` is rederived —
    the pool is credited back — and the case's `version` increments alongside
    the distribution's."

    Design: Difficulty/compensating_invariant/distribution_approve_rescind_pool_invariant
    """
    case = create_case_in_state(
        "FORFEITED", case_number="26-MJ-0018", judicial_district="S.D. Tex.",
        forfeiture_type="CRIMINAL", lead_agency_code="FBI",
    )
    # Net 1830000 minus a 300000 verified lien: available == 1530000.
    create_settled_sale(
        case_id=case["id"], raw_value_cents=2_000_000, grade="EXCELLENT",
        asset_type="VEHICLE", description="suv", winning_bid_cents=2_000_000,
        liens=[{
            "petitioner_ref": "cl-bank", "kind": "LIEN_MORTGAGE",
            "lienholder_name": "Gulf Bank", "amount_cents": 300_000,
            "priority_position": 1,
        }],
        auctioneer_ref="auc-4",
        slot_start="2026-09-07T10:00:00Z", slot_end="2026-09-07T12:00:00Z",
    )
    assert get_case(case["id"])["available_proceeds_cents"] == 1_530_000

    dist = create_distribution(
        case["id"], amount_cents=500_000, payee_ref="TX-DPS",
        usage_restriction="EQUIPMENT",
        creator_user_id=SECOND_FUND_ADMINISTRATOR_USER_ID,
    )
    approve_distribution(dist["id"], approver_user_id=FUND_ADMINISTRATOR_USER_ID)
    after_approve = get_case(case["id"])
    assert after_approve["available_proceeds_cents"] == 1_030_000, (
        "PAID debits the pool: 1530000 - 500000"
    )

    voided = rescind_distribution(
        dist["id"], user_id=FUND_ADMINISTRATOR_USER_ID
    )
    assert voided["status"] == "VOIDED"
    after_rescind = get_case(case["id"])
    assert after_rescind["available_proceeds_cents"] == 1_530_000, (
        "the approve/rescind pair conserves the pool exactly"
    )
    assert after_rescind["equitable_shares_paid_cents"] == 0
