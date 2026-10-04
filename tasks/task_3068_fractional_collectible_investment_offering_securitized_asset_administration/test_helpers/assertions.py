"""Entity assertions and domain invariant checkers.

Each `assert_{entity}` validates a response payload against the fields the PRD
declares for that resource. The five append-mostly child types are checked
*without* `updated_at` and `version`, which the PRD says they do not expose.
"""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp

APPEND_ONLY_ENTITIES = {
    "ArtworkAssetReport", "Appraisal", "OfferingReport", "FeeAccrual", "Distribution",
}


def _assert_identity_block(data: dict):
    """The standard identity block carried by every primary resource."""
    assert is_valid_uuid(data.get("id", "")), "id must be a bare UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), \
        "created_at must be an ISO 8601 timestamp with fractional digits"
    assert is_iso8601_timestamp(data.get("updated_at", "")), \
        "updated_at must be an ISO 8601 timestamp with fractional digits"
    assert isinstance(data.get("version"), int), "version must be an integer"


def assert_append_only_identity(data: dict):
    """Child records carry only id and created_at -- no updated_at, no version."""
    assert is_valid_uuid(data.get("id", "")), "id must be a bare UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), \
        "created_at must be an ISO 8601 timestamp with fractional digits"
    assert "updated_at" not in data, "append-only child must not expose updated_at"
    assert "version" not in data, "append-only child must not expose version"


def assert_money_is_whole_cents(value):
    """Every monetary quantity is an integer count of cents."""
    assert isinstance(value, int) and not isinstance(value, bool), \
        f"monetary value {value!r} must be an integer count of cents"


# ── Artist ───────────────────────────────────────────────────────────────────

def assert_artist(data: dict):
    _assert_identity_block(data)
    assert isinstance(data["legal_name"], str) and data["legal_name"]
    assert data["attribution_status"] in ("CONFIRMED", "DISPUTED", "UNKNOWN")
    assert isinstance(data["nationality_country_code"], str)
    assert isinstance(data["catalogue_raisonne_published"], bool)


# ── Investor ─────────────────────────────────────────────────────────────────

def assert_investor(data: dict):
    _assert_identity_block(data)
    assert isinstance(data["email"], str) and data["email"]
    assert data["suitability_status"] in ("PENDING", "APPROVED", "EXPIRED", "REVOKED")
    assert isinstance(data["is_accredited"], bool)
    assert_money_is_whole_cents(data["lifetime_invested_cents"])
    assert_money_is_whole_cents(data["annual_income_cents"])
    assert_money_is_whole_cents(data["net_worth_cents"])


def assert_investor_invariants(data: dict):
    """Hold after any operation on an investor."""
    assert data["lifetime_invested_cents"] >= 0, \
        "an investor's lifetime invested total never goes negative"
    assert data["suitability_status"] in ("PENDING", "APPROVED", "EXPIRED", "REVOKED")


# ── Artwork ──────────────────────────────────────────────────────────────────

def assert_artwork(data: dict):
    _assert_identity_block(data)
    assert isinstance(data["title"], str) and data["title"]
    assert data["medium"] in ("PAINTING", "SCULPTURE", "WORK_ON_PAPER",
                              "PHOTOGRAPH", "MIXED_MEDIA")
    assert data["status"] in ("APPRAISED", "AUTHENTICATED", "OFFERING_PENDING",
                              "UNDER_OFFERING", "HELD", "SALE_PENDING", "SOLD")
    assert isinstance(data["artifacts_overview"], dict)
    assert_money_is_whole_cents(data["last_appraised_value_cents"])


def assert_artifacts_overview(overview: dict):
    for key in ("is_authenticated", "has_good_provenance", "latest_appraisal_value_cents",
                "latest_appraisal_filed_at", "custody_started_at",
                "holding_period_elapsed_days", "appraisal_due"):
        assert key in overview, f"artifacts_overview must carry {key}"
    assert isinstance(overview["is_authenticated"], bool)
    assert isinstance(overview["has_good_provenance"], bool)


# ── Offering ─────────────────────────────────────────────────────────────────

def assert_offering(data: dict):
    _assert_identity_block(data)
    assert data["status"] in ("DRAFT", "QUALIFICATION_FILED", "ALLOCATED", "HELD",
                              "SALE_PENDING", "CLOSED", "WITHDRAWN", "OFFERING_ABANDONED")
    assert data["exemption_type"] in ("REG_D_506C", "REG_A_TIER2", "EXEMPT_REG_D")
    for f in ("total_shares", "price_per_share_cents", "gross_proceeds_cents",
              "accepted_shares", "unsubscribed_shares", "reserved_shares",
              "cash_ledger_cents", "custody_cost_ledger_cents"):
        assert isinstance(data[f], int), f"{f} must be an integer"
    assert data["gross_proceeds_cents"] == data["total_shares"] * data["price_per_share_cents"], \
        "gross_proceeds_cents is total_shares multiplied by price_per_share_cents"


def assert_offering_invariants(data: dict):
    """Share and cash ledgers a PRD-faithful server must never violate."""
    assert data["accepted_shares"] >= 0
    assert data["reserved_shares"] >= 0
    assert data["unsubscribed_shares"] == (
        data["total_shares"] - data["accepted_shares"] - data["reserved_shares"]
    ), "unsubscribed_shares is the issue size less the accepted and reserved counts together"
    assert data["cash_ledger_cents"] >= 0
    assert data["custody_cost_ledger_cents"] >= 0


# ── Subscription ─────────────────────────────────────────────────────────────

def assert_subscription(data: dict):
    _assert_identity_block(data)
    assert data["status"] in ("RECEIVED", "SUITABILITY_SCREENED", "SUBSCRIBED",
                              "REALLOCATED", "WAITLISTED", "REJECTED", "EXPIRED",
                              "WITHDRAWN")
    assert isinstance(data["accepted_shares"], int)
    assert isinstance(data["requested_shares"], int)
    assert_money_is_whole_cents(data["amount_due_cents"])
    assert_money_is_whole_cents(data["collected_subscription_cents"])
    assert_money_is_whole_cents(data["refunded_cents"])


# ── CustodyRecord ────────────────────────────────────────────────────────────

def assert_custody_record(data: dict):
    _assert_identity_block(data)
    assert data["status"] in ("PENDING", "IN_CUSTODY", "RELEASED")


# ── HoldingDecision ──────────────────────────────────────────────────────────

def assert_holding_decision(data: dict):
    _assert_identity_block(data)
    assert data["decision_type"] in ("HOLD", "SELL")
    assert data["status"] in ("PENDING", "APPROVED", "REJECTED", "EXECUTED", "FAILED")


# ── TransferOrder ────────────────────────────────────────────────────────────

def assert_transfer_order(data: dict):
    _assert_identity_block(data)
    assert data["status"] in ("OPEN", "MATCHED", "EXECUTED", "LAPSED", "CANCELLED")


# ── Lot ──────────────────────────────────────────────────────────────────────

def assert_lot(data: dict):
    _assert_identity_block(data)
    assert isinstance(data["pass_through_allowed"], bool)
    assert isinstance(data["pass_through_amount_cents"], int)
    if not data["pass_through_allowed"]:
        assert data["pass_through_amount_cents"] == 0, \
            "a lot whose gates fail passes through zero"


# ── InsurancePolicy ──────────────────────────────────────────────────────────

def assert_insurance_policy(data: dict):
    _assert_identity_block(data)
    assert data["status"] in ("PENDING", "FORCE", "LAPSED")


# ── Append-only children ─────────────────────────────────────────────────────

def assert_artwork_asset_report(data: dict):
    assert_append_only_identity(data)
    assert data["report_type"] in ("AUTHENTICATION", "PROVENANCE", "CONDITION_SURVEY")
    assert data["outcome"] in ("VERIFIED", "DISPUTED", "REJECTED")


def assert_appraisal(data: dict):
    assert_append_only_identity(data)
    assert data["appraisal_method"] in ("AUCTION_COMPARABLE", "MARKET_INDEX",
                                        "PRIVATE_SALE")
    assert isinstance(data["is_selected"], bool)


def assert_offering_report(data: dict):
    assert_append_only_identity(data)
    assert data["report_kind"] in ("QUARTERLY", "APPRAISAL", "SALE")
    assert isinstance(data["shareholder_count"], int)
    assert data["shareholder_count"] >= 0


def assert_fee_accrual(data: dict):
    assert_append_only_identity(data)
    assert data["accrual_type"] in ("MANAGEMENT", "PROFIT_PARTICIPATION")
    assert_money_is_whole_cents(data["basis_value_cents"])
    assert_money_is_whole_cents(data["amount_cents"])


def assert_distribution(data: dict):
    assert_append_only_identity(data)
    assert data["status"] in ("CALCULATED", "PAID")


# ── PlatformAccount ──────────────────────────────────────────────────────────

def assert_platform_account(data: dict):
    _assert_identity_block(data)
    assert_money_is_whole_cents(data["balance_cents"])
    assert_money_is_whole_cents(data["investor_funds_held_cents"])
    assert_money_is_whole_cents(data["total_paid_out_cents"])


def assert_platform_account_invariants(data: dict):
    """Cash conservation: the account's balance may never go below zero."""
    assert data["balance_cents"] >= 0, "no debit may take balance_cents below zero"
    assert data["investor_funds_held_cents"] >= 0
    assert data["total_paid_out_cents"] >= 0


def assert_cash_conserved(account: dict, expected_segregated_cents: int):
    """The segregated total is the subset of the balance held for subscribers."""
    assert account["investor_funds_held_cents"] == expected_segregated_cents, (
        f"expected investor_funds_held_cents {expected_segregated_cents}, "
        f"got {account['investor_funds_held_cents']}"
    )
    assert account["balance_cents"] >= account["investor_funds_held_cents"], \
        "the balance can never be less than the segregated subset it contains"