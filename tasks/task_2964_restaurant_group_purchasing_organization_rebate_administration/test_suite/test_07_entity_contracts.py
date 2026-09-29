"""Entity contract tests: field echo-back, computed and defaulted fields, the
system-owned common fields, the thirteen entity-specific 404 codes, body-shape
rejection and the one immutable row.

Every test builds its whole world through API calls because the database is
empty before each one, and the call under test is always issued through the raw
api_client so its HTTP status is asserted next to its error_id.
"""
from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import constants as C
from test_helpers import factories as F
from test_helpers import fixtures as fx
from test_helpers.api_client import api_client
from test_helpers.api_errors import ApiErrorId
from test_helpers.assertions import (
    assert_compliance_review,
    assert_contracted_item,
    assert_created_at_desc,
    assert_distributor,
    assert_error_meta_is_minimal,
    assert_instants_equal,
    assert_member,
    assert_program_tier,
    assert_purchase_line,
    assert_rate_card,
    round_half_up,
)
from test_helpers.test_users import (
    make_analyst_headers,
    make_distributor_feed_headers,
    make_gpo_admin_headers,
)
from test_helpers.types import (
    AccrualBlockReason,
    ComplianceResult,
    DealStatus,
    ItemStatus,
    MatchStatus,
    MemberEnrollmentStatus,
    RateCardStatus,
    RateType,
    ReconciliationPosture,
)

ADMIN = make_gpo_admin_headers()
ANALYST = make_analyst_headers()

# The design's "belongs to no row of any entity" identifier, and the opaque
# distributor id it uses for a DistributorFeed caller that owns nothing.
UNKNOWN_ID = "00000000-0000-0000-0000-0000000000ff"
UNKNOWN_DISTRIBUTOR_ID = "00000000-0000-0000-0000-0000000000aa"

# ------------------------------------------------------- design literals ----
# instance 1: every knob supplied explicitly, reversal_posture_limit pinned to 1
ELITE_TIER_EXPLICIT_POSTURE_LIMIT = {
    "tier_code": "ELITE",
    "member_share_bps": 7500,
    "gpo_retention_bps": 2500,
    "admin_fee_bps_low": 300,
    "admin_fee_bps_high": 150,
    "compliance_min_ratio_bps": 8000,
    "markup_cap_bps": 700,
    "dispute_window_days": 45,
    "reversal_posture_limit": 1,
}

# instance 6: the CORE tier with reversal_posture_limit OMITTED entirely, which
# is what makes the stored default observable.
CORE_TIER_WITHOUT_POSTURE_LIMIT = {
    "tier_code": "CORE",
    "member_share_bps": 6000,
    "gpo_retention_bps": 4000,
    "admin_fee_bps_low": 400,
    "admin_fee_bps_high": 200,
    "compliance_min_ratio_bps": 6000,
    "markup_cap_bps": 900,
    "dispute_window_days": 30,
}
DEFAULT_REVERSAL_POSTURE_LIMIT = 2

# instance 3: a reported key that no ContractedItem in the world owns
UNOWNED_FRIES_KEY = "FRIES-UNKNOWN-CS30"
FRIES_LINE_CASES = 20

# instance 12: the second distributor the member IS authorized for
SECOND_DISTRIBUTOR_NAME = "Sysco Northeast"
SECOND_DISTRIBUTOR_DBA_CODE = "SYSCO-02"
SECOND_DISTRIBUTOR_MARKUP_BPS = 600

# instance 7: 30 cases at 9140 cents per case
LINE_A_EXTENDED_CENTS = C.LINE_A_CASES * C.INVOICE_UNIT_COST_CENTS  # 274200

# instance 10: the July window, wholly in the past against the epoch clock
REVIEW_WINDOW_START = "2026-07-01"
REVIEW_WINDOW_END = "2026-07-31"
REVIEW_WINDOW_DAYS = 31
REVIEW_PRORATED_COMMITMENT_CENTS = 1_698_630


# ============================================================ module helpers ==

def member_with_open_june_feed() -> dict:
    """An ACTIVE member holding a countersigned PURCHASE_DATA_AND_PRICING letter
    for METRO-01, plus a RECEIVED June feed of that distributor. No deal and no
    contracted item exist, so nothing can ever match."""
    tier = fx.create_tier()
    distributor = fx.create_distributor()
    member = fx.create_member(tier["id"])
    letter = fx.submit_letter(member["id"], distributor["id"])
    fx.countersign_letter(letter["id"], distributor["id"])
    member = fx.activate_member(member["id"])
    batch = fx.create_batch(distributor["id"])
    return {
        "tier": tier,
        "distributor": distributor,
        "member": member,
        "batch": batch,
        "member_id": member["id"],
        "distributor_id": distributor["id"],
        "batch_id": batch["id"],
        "distributor_headers": make_distributor_feed_headers(distributor["id"]),
    }


def member_authorized_for_the_other_distributor() -> dict:
    """Two ACTIVE distributors. The member is ACTIVE through a countersigned
    letter for SYSCO-02 only, while the RECEIVED June feed belongs to
    METRO-01 — so the (member, distributor) pairing is unauthorized."""
    tier = fx.create_tier()
    metro = fx.create_distributor()
    sysco = fx.create_distributor(
        name=SECOND_DISTRIBUTOR_NAME,
        dba_code=SECOND_DISTRIBUTOR_DBA_CODE,
        contracted_markup_bps=SECOND_DISTRIBUTOR_MARKUP_BPS,
    )
    member = fx.create_member(tier["id"])
    letter = fx.submit_letter(member["id"], sysco["id"])
    letter = fx.countersign_letter(letter["id"], sysco["id"])
    member = fx.activate_member(member["id"])
    batch = fx.create_batch(metro["id"])
    return {
        "tier": tier,
        "metro": metro,
        "sysco": sysco,
        "member": member,
        "letter": letter,
        "batch": batch,
        "member_id": member["id"],
        "batch_id": batch["id"],
        "metro_headers": make_distributor_feed_headers(metro["id"]),
    }


def deal_with_one_item() -> tuple:
    """A DRAFT deal carrying the beef contracted item, with the item's own
    version read back for the mandatory OCC token."""
    deal = fx.create_deal()
    item = fx.create_item(deal["id"])
    return deal, item


def june_batch_with_three_lines(ctx: dict) -> dict:
    """Ingest the 30- and 40-case beef lines plus a 20-case fries line whose
    reported key no ContractedItem owns, then normalize the feed."""
    batch = fx.create_batch(ctx["distributor_id"])
    ctx["batch_id"] = batch["id"]
    ctx["line_a"] = fx.create_line(batch["id"], ctx["member_id"], ctx["distributor_id"])
    ctx["line_b"] = fx.create_line_b(
        batch["id"], ctx["member_id"], ctx["distributor_id"]
    )
    ctx["line_c"] = fx.create_line(
        batch["id"],
        ctx["member_id"],
        ctx["distributor_id"],
        payload=F.fries_line_payload(
            batch["id"],
            ctx["member_id"],
            normalized_item_key_reported=UNOWNED_FRIES_KEY,
        ),
    )
    ctx["batch"] = fx.normalize(batch["id"])
    return ctx


# The thirteen path-variable resolutions, one per entity that owns a 404 code.
NOT_FOUND_PROBES = [
    ("GET /program-tiers/{tier_id}",
     lambda: api_client.get_program_tier(UNKNOWN_ID, ADMIN),
     ApiErrorId.ERR_PROGRAM_TIER_NOT_FOUND),
    ("GET /distributors/{distributor_id}",
     lambda: api_client.get_distributor(UNKNOWN_ID, ADMIN),
     ApiErrorId.ERR_DISTRIBUTOR_NOT_FOUND),
    ("GET /members/{member_id}",
     lambda: api_client.get_member(UNKNOWN_ID, ADMIN),
     ApiErrorId.ERR_MEMBER_NOT_FOUND),
    ("GET /authorization-letters/{letter_id}",
     lambda: api_client.get_authorization_letter(UNKNOWN_ID, ADMIN),
     ApiErrorId.ERR_LETTER_NOT_FOUND),
    ("GET /manufacturer-deals/{deal_id}",
     lambda: api_client.get_deal(UNKNOWN_ID, ADMIN),
     ApiErrorId.ERR_DEAL_NOT_FOUND),
    ("GET /contracted-items/{item_id}",
     lambda: api_client.get_contracted_item(UNKNOWN_ID, ADMIN),
     ApiErrorId.ERR_CONTRACTED_ITEM_NOT_FOUND),
    ("GET /rate-cards/{rate_card_id}",
     lambda: api_client.get_rate_card(UNKNOWN_ID, ADMIN),
     ApiErrorId.ERR_RATE_CARD_NOT_FOUND),
    ("GET /purchase-batches/{batch_id}",
     lambda: api_client.get_purchase_batch(UNKNOWN_ID, ADMIN),
     ApiErrorId.ERR_BATCH_NOT_FOUND),
    ("GET /purchase-lines/{line_id}",
     lambda: api_client.get_purchase_line(UNKNOWN_ID, ADMIN),
     ApiErrorId.ERR_PURCHASE_LINE_NOT_FOUND),
    ("GET /accruals/{accrual_id}",
     lambda: api_client.get_accrual(UNKNOWN_ID, ADMIN),
     ApiErrorId.ERR_ACCRUAL_NOT_FOUND),
    ("GET /manufacturer-claims/{claim_id}",
     lambda: api_client.get_claim(UNKNOWN_ID, ADMIN),
     ApiErrorId.ERR_CLAIM_NOT_FOUND),
    ("GET /disputes/{dispute_id}",
     lambda: api_client.get_dispute(UNKNOWN_ID, ADMIN),
     ApiErrorId.ERR_DISPUTE_NOT_FOUND),
    ("GET /compliance-reviews/{review_id}",
     lambda: api_client.get_compliance_review(UNKNOWN_ID, ADMIN),
     ApiErrorId.ERR_COMPLIANCE_REVIEW_NOT_FOUND),
]


# ============================================================================
# ProgramTier — the create echoes every configured field
# ============================================================================

def test_program_tier_create_echoes_every_configured_field():
    """A tier create returns 201 with all eight supplied knobs stored verbatim,
    an explicitly supplied reversal_posture_limit of 1 that the default 2 does
    not overwrite, and the freshly minted common fields.

    PRD: "Unless otherwise noted, operations that create or modify a resource
    will return the created or updated resource object in the data field."
    PRD: "`version` is an integer that starts at 1 when the record is created"

    Design: Corner/entities/program_tier_create_echoes_every_configured_field
    """
    response = api_client.create_program_tier(
        dict(ELITE_TIER_EXPLICIT_POSTURE_LIMIT), ADMIN
    )
    tier = validate_success(response, 201)
    assert response.json()["response_type"] == "object"
    assert_program_tier(tier)

    assert tier["tier_code"] == "ELITE"
    assert tier["member_share_bps"] == 7500
    assert tier["gpo_retention_bps"] == 2500
    assert tier["admin_fee_bps_low"] == 300
    assert tier["admin_fee_bps_high"] == 150
    assert tier["compliance_min_ratio_bps"] == 8000
    assert tier["markup_cap_bps"] == 700
    assert tier["dispute_window_days"] == 45
    assert tier["reversal_posture_limit"] == 1, (
        "the explicitly supplied 1 survives; it is not replaced by the default 2"
    )

    assert tier["version"] == 1
    assert_instants_equal(tier["created_at"], tier["updated_at"])
    assert_instants_equal(tier["created_at"], C.CLOCK_EPOCH)

    rows, meta = validate_paginated(api_client.list_program_tiers(ADMIN))
    assert meta["total_count"] == 1, "exactly one tier row exists"
    assert len(rows) == 1 and rows[0]["id"] == tier["id"]


# ============================================================================
# Member — a retrieval returns the persisted row with its creation defaults
# ============================================================================

def test_member_get_by_id_returns_the_stored_row():
    """Fetching a just-enrolled member returns the persisted row: the three
    supplied inputs, the PENDING/CLEAR/false lifecycle triple and all seven
    counters still at 0.

    PRD: "A new member's `enrollment_status` is `PENDING`, its
    `reconciliation_posture` is `CLEAR`, its `payout_hold` is false, and its
    counters — `active_letter_count`, `accrued_member_share_cents`,
    `attributed_gpo_retention_cents`, `attributed_admin_fee_cents`,
    `ytd_net_snapshot_cents`, `dispute_reversal_count` and
    `recovery_credit_cents` — all start at 0."

    Design: Corner/entities/member_get_by_id_returns_the_stored_row
    """
    tier = fx.create_tier()
    created = fx.create_member(tier["id"])

    response = api_client.get_member(created["id"], ANALYST)
    member = validate_success(response, 200)
    assert_member(member)

    assert member["id"] == created["id"]
    assert member["legal_name"] == C.MEMBER_LEGAL_NAME
    assert member["tier_id"] == tier["id"]
    assert member["committed_annual_spend_cents"] == 20_000_000

    assert member["enrollment_status"] == MemberEnrollmentStatus.PENDING.value
    assert member["reconciliation_posture"] == ReconciliationPosture.CLEAR.value
    assert member["payout_hold"] is False

    for counter in (
        "active_letter_count",
        "accrued_member_share_cents",
        "attributed_gpo_retention_cents",
        "attributed_admin_fee_cents",
        "ytd_net_snapshot_cents",
        "dispute_reversal_count",
        "recovery_credit_cents",
    ):
        assert member[counter] == 0, f"{counter} must start at 0"

    assert member["version"] == 1


# ============================================================================
# PurchaseLine listing — the filter is applied before the page is cut
# ============================================================================

def test_purchase_lines_filter_applies_before_pagination():
    """Two single-row pages of the MATCHED lines report total_count 2 — the
    filtered population, not the batch's three lines — and has_more flips from
    true to false between them while the union covers both beef lines.

    PRD: "`total_count` giving the number of records matching the request's
    filters before pagination, and `has_more` indicating whether any matching
    record remains beyond the current page."

    Design: Corner/entities/purchase_lines_list_paginates_and_filters_together
    """
    ctx = june_batch_with_three_lines(fx.setup_flat_program())
    query = {
        "purchase_batch_id": ctx["batch_id"],
        "match_status": MatchStatus.MATCHED.value,
    }

    first = api_client.list_purchase_lines(ANALYST, dict(query, limit=1, offset=0))
    page_one, meta_one = validate_paginated(first)
    assert first.json()["response_type"] == "array"
    assert len(page_one) == 1
    assert meta_one["limit"] == 1
    assert meta_one["offset"] == 0
    assert meta_one["total_count"] == 2
    assert meta_one["has_more"] is True

    second = api_client.list_purchase_lines(ANALYST, dict(query, limit=1, offset=1))
    page_two, meta_two = validate_paginated(second)
    assert second.json()["response_type"] == "array"
    assert len(page_two) == 1
    assert meta_two["limit"] == 1
    assert meta_two["offset"] == 1
    assert meta_two["total_count"] == 2
    assert meta_two["has_more"] is False

    assert page_one[0]["id"] != page_two[0]["id"], "the two pages must not overlap"
    assert {page_one[0]["id"], page_two[0]["id"]} == {
        ctx["line_a"]["id"],
        ctx["line_b"]["id"],
    }, "the fries line is filtered out by match_status == MATCHED"
    assert_created_at_desc(page_one + page_two)


def test_purchase_lines_match_status_filter_partitions_the_batch():
    """The same batch reports three lines unfiltered, two under MATCHED and the
    single unowned-key fries line under UNMATCHED.

    PRD: "When there are no key candidates at all — an item key nobody has
    contracted — the line stays `UNMATCHED` with `accrual_block_reason` of
    `NONE`, so a later run can pick it up once the item exists."

    Design: Corner/entities/purchase_lines_list_paginates_and_filters_together
    """
    ctx = june_batch_with_three_lines(fx.setup_flat_program())

    all_rows, all_meta = validate_paginated(
        api_client.list_purchase_lines(
            ANALYST, {"purchase_batch_id": ctx["batch_id"], "limit": C.MAX_LIMIT}
        )
    )
    assert all_meta["total_count"] == 3
    assert len(all_rows) == 3
    assert_created_at_desc(all_rows)

    matched, matched_meta = validate_paginated(
        api_client.list_purchase_lines(
            ANALYST,
            {
                "purchase_batch_id": ctx["batch_id"],
                "match_status": MatchStatus.MATCHED.value,
                "limit": C.MAX_LIMIT,
            },
        )
    )
    assert matched_meta["total_count"] == 2
    assert {row["id"] for row in matched} == {
        ctx["line_a"]["id"],
        ctx["line_b"]["id"],
    }

    unmatched, unmatched_meta = validate_paginated(
        api_client.list_purchase_lines(
            ANALYST,
            {
                "purchase_batch_id": ctx["batch_id"],
                "match_status": MatchStatus.UNMATCHED.value,
                "limit": C.MAX_LIMIT,
            },
        )
    )
    assert unmatched_meta["total_count"] == 1
    assert len(unmatched) == 1
    assert unmatched[0]["id"] == ctx["line_c"]["id"]
    assert unmatched[0]["normalized_item_key_reported"] == UNOWNED_FRIES_KEY
    assert unmatched[0]["cases_shipped"] == FRIES_LINE_CASES
    assert unmatched[0]["accrual_block_reason"] == AccrualBlockReason.NONE.value


# ============================================================================
# Path-id resolution — thirteen entity-specific 404 codes
# ============================================================================

def test_unknown_path_ids_return_the_entity_specific_not_found_error():
    """Against an empty database, one unresolvable path id per entity draws that
    entity's own 404 code — thirteen distinct identifiers rather than a single
    generic NOT_FOUND — and every error body carries only error_id and message.

    PRD: "Path variables are resolved first, left to right, and an unresolvable
    one yields HTTP 404 with the not-found code belonging to that resource type"

    Design: Corner/entities/unknown_path_ids_return_the_entity_specific_not_found_error
    """
    seen = []
    for label, probe, expected_error_id in NOT_FOUND_PROBES:
        response = probe()
        assert response.status_code == 404, f"{label} must answer 404"
        assert response.json()["response_type"] == "error", label
        error = validate_error(response, expected_error_id, 404)
        assert set(error.keys()) == {"error_id", "message"}, (
            f"{label}: an error body carries exactly error_id and message"
        )
        assert_error_meta_is_minimal(response)
        seen.append(error["error_id"])

    assert len(set(seen)) == 13, (
        f"each entity must own its own 404 code, got {sorted(set(seen))}"
    )


def test_unknown_letter_id_beats_the_enum_and_scope_failures_on_one_request():
    """A countersign against an unknown letter id, sent by a DistributorFeed
    account that owns nothing and carrying an out-of-enum decision, still
    reports ERR_LETTER_NOT_FOUND: the priority-4 path check runs first.

    PRD: "Requests are validated as an ordered ladder, and the **first** check
    that fails determines the response. No later check runs, so a request that
    would fail three ways reports only the earliest failure."

    Design: Corner/entities/unknown_path_ids_return_the_entity_specific_not_found_error
    """
    response = api_client.countersign_letter(
        UNKNOWN_ID,
        {"decision": "NOT_AN_ENUM_VALUE"},
        make_distributor_feed_headers(UNKNOWN_DISTRIBUTOR_ID),
    )
    assert response.status_code == 404
    assert response.json()["response_type"] == "error"
    error = validate_error(response, ApiErrorId.ERR_LETTER_NOT_FOUND, 404)
    assert set(error.keys()) == {"error_id", "message"}
    assert_error_meta_is_minimal(response)


# ============================================================================
# Required fields — POST /members declares three inputs and defaults none
# ============================================================================

def test_member_create_rejects_a_missing_or_mistyped_commitment():
    """Omitting committed_annual_spend_cents is a 400, and so is sending it as
    a JSON string: the declared integer type is never coerced. Neither attempt
    persists a member.

    PRD: "The request body parses, every required field is present with its
    declared JSON type, every enum-valued field carries a declared member of its
    value set, and no unknown field is supplied — otherwise `ERR_INVALID_REQUEST`."

    Design: Corner/entities/member_create_missing_required_field_returns_invalid_request
    """
    tier = fx.create_tier()

    omitted = api_client.create_member(
        {"legal_name": C.MEMBER_LEGAL_NAME, "tier_id": tier["id"]}, ADMIN
    )
    validate_error(omitted, ApiErrorId.ERR_INVALID_REQUEST, 400)

    stringly = api_client.create_member(
        {
            "legal_name": C.MEMBER_LEGAL_NAME,
            "tier_id": tier["id"],
            "committed_annual_spend_cents": "20000000",
        },
        ADMIN,
    )
    validate_error(stringly, ApiErrorId.ERR_INVALID_REQUEST, 400)

    _, meta = validate_paginated(api_client.list_members(ADMIN))
    assert meta["total_count"] == 0, "neither rejected attempt persisted a member"


def test_member_create_rejects_a_zero_commitment():
    """A commitment of 0 cents fails the declared >= 1 constraint and is
    rejected, so no member can be enrolled with a zero denominator for its
    later compliance ratio.

    PRD: "a `committed_annual_spend_cents` figure of at least 1 cent
    representing the annual contracted-spend commitment the operator signed"

    Design: Corner/entities/member_create_missing_required_field_returns_invalid_request
    """
    tier = fx.create_tier()

    response = api_client.create_member(
        {
            "legal_name": C.MEMBER_LEGAL_NAME,
            "tier_id": tier["id"],
            "committed_annual_spend_cents": 0,
        },
        ADMIN,
    )
    validate_error(response, ApiErrorId.ERR_INVALID_REQUEST, 400)

    _, meta = validate_paginated(api_client.list_members(ADMIN))
    assert meta["total_count"] == 0, "the rejected attempt persisted nothing"


# ============================================================================
# Defaults — reversal_posture_limit is the one optional write-surface input
# ============================================================================

def test_program_tier_reversal_posture_limit_defaults_to_two():
    """A tier created without reversal_posture_limit stores 2, and the stored 2
    is what a later read reports — the default is persisted, not applied
    per-read — while no other supplied field is defaulted away.

    PRD: "`reversal_posture_limit` must be at least 1 and defaults to 2 when the
    field is omitted."

    Design: Corner/entities/program_tier_reversal_posture_limit_defaults_to_two
    """
    response = api_client.create_program_tier(
        dict(CORE_TIER_WITHOUT_POSTURE_LIMIT), ADMIN
    )
    tier = validate_success(response, 201)
    assert_program_tier(tier)
    assert tier["reversal_posture_limit"] == DEFAULT_REVERSAL_POSTURE_LIMIT

    reread = validate_success(api_client.get_program_tier(tier["id"], ADMIN), 200)
    assert reread["reversal_posture_limit"] == DEFAULT_REVERSAL_POSTURE_LIMIT, (
        "the default was persisted onto the row, not recomputed on each read"
    )

    assert reread["tier_code"] == "CORE"
    assert reread["dispute_window_days"] == 30
    assert reread["markup_cap_bps"] == 900
    assert reread["member_share_bps"] == 6000
    assert reread["gpo_retention_bps"] == 4000
    assert reread["admin_fee_bps_low"] == 400
    assert reread["admin_fee_bps_high"] == 200
    assert reread["compliance_min_ratio_bps"] == 6000


# ============================================================================
# Computed fields — invoice_extended_cents is the server's, not the client's
# ============================================================================

def test_purchase_line_rejects_a_client_supplied_invoice_extended_cents():
    """Supplying invoice_extended_cents on a line ingest is an unknown field and
    is rejected with 400 even when the value equals the product the server would
    itself compute, and the rejected attempt moves no batch counter.

    PRD: "The request body parses, every required field is present with its
    declared JSON type, every enum-valued field carries a declared member of its
    value set, and no unknown field is supplied — otherwise `ERR_INVALID_REQUEST`."

    Design: Corner/entities/purchase_line_extended_cost_is_computed_and_client_value_rejected
    """
    ctx = member_with_open_june_feed()
    payload = F.purchase_line_payload(ctx["batch_id"], ctx["member_id"])
    payload["invoice_extended_cents"] = LINE_A_EXTENDED_CENTS
    assert LINE_A_EXTENDED_CENTS == 274_200, "30 cases * 9140 cents is 274200"

    response = api_client.create_purchase_line(payload, ctx["distributor_headers"])
    validate_error(response, ApiErrorId.ERR_INVALID_REQUEST, 400)

    batch = validate_success(
        api_client.get_purchase_batch(ctx["batch_id"], ANALYST), 200
    )
    assert batch["line_count"] == 0
    assert batch["total_cases_ingested"] == 0


def test_purchase_line_computes_invoice_extended_cents_and_its_defaults():
    """A clean ingest returns 201 with invoice_extended_cents computed as cases
    times unit cost, the four ingest-time defaults, and a batch whose line and
    case counters moved by exactly that one line.

    PRD: "`invoice_extended_cents` is `cases_shipped` multiplied by
    `invoice_unit_cost_cents`, and because both operands are integers no
    rounding arises. The line begins with `match_status` of `UNMATCHED`,
    `contracted_item_id` null, `accrual_block_reason` of `NONE` and
    `overbilled_cents` of 0."

    Design: Corner/entities/purchase_line_extended_cost_is_computed_and_client_value_rejected
    """
    ctx = member_with_open_june_feed()

    response = api_client.create_purchase_line(
        F.purchase_line_payload(ctx["batch_id"], ctx["member_id"]),
        ctx["distributor_headers"],
    )
    line = validate_success(response, 201)
    assert_purchase_line(line)

    assert line["invoice_extended_cents"] == LINE_A_EXTENDED_CENTS
    assert line["match_status"] == MatchStatus.UNMATCHED.value
    assert line["contracted_item_id"] is None
    assert line["accrual_block_reason"] == AccrualBlockReason.NONE.value
    assert line["overbilled_cents"] == 0

    batch = validate_success(
        api_client.get_purchase_batch(ctx["batch_id"], ANALYST), 200
    )
    assert batch["line_count"] == 1
    assert batch["total_cases_ingested"] == C.LINE_A_CASES
    assert batch["unmatched_cases"] == C.LINE_A_CASES
    assert batch["matched_cases"] == 0


# ============================================================================
# System fields — id, created_at, updated_at and version are server-owned
# ============================================================================

def test_distributor_create_rejects_a_client_supplied_id_or_version():
    """Neither id nor version is an accepted input on a create: each is an
    unknown field drawing a 400, and neither rejected attempt persists a row.

    PRD: "Every stored record is addressed by an `id` that the server mints as a
    UUID."

    Design: Corner/entities/system_fields_are_server_generated_and_client_supplied_id_rejected
    """
    with_id = api_client.create_distributor(
        F.distributor_payload(id=UNKNOWN_DISTRIBUTOR_ID), ADMIN
    )
    validate_error(with_id, ApiErrorId.ERR_INVALID_REQUEST, 400)

    with_version = api_client.create_distributor(
        F.distributor_payload(version=7), ADMIN
    )
    validate_error(with_version, ApiErrorId.ERR_INVALID_REQUEST, 400)

    _, meta = validate_paginated(api_client.list_distributors(ADMIN))
    assert meta["total_count"] == 0, "neither rejected attempt persisted a row"


def test_distributor_create_mints_its_own_id_and_starts_version_at_one():
    """A clean register returns 201 with a server-generated UUID that is not the
    one a client tried to dictate, version 1, and both instants set.

    PRD: "`version` is an integer that starts at 1 when the record is created
    and increases by exactly 1 on every mutation of that record"

    Design: Corner/entities/system_fields_are_server_generated_and_client_supplied_id_rejected
    """
    response = api_client.create_distributor(F.distributor_payload(), ADMIN)
    distributor = validate_success(response, 201)
    assert_distributor(distributor)

    assert distributor["id"] != UNKNOWN_DISTRIBUTOR_ID, (
        "the id is minted by the server, never taken from a client"
    )
    assert distributor["version"] == 1
    assert_instants_equal(distributor["created_at"], distributor["updated_at"])
    assert distributor["name"] == C.DISTRIBUTOR_NAME
    assert distributor["dba_code"] == C.DISTRIBUTOR_DBA_CODE
    assert distributor["contracted_markup_bps"] == C.DISTRIBUTOR_MARKUP_BPS

    rows, meta = validate_paginated(api_client.list_distributors(ADMIN))
    assert meta["total_count"] == 1
    assert len(rows) == 1 and rows[0]["id"] == distributor["id"]


# ============================================================================
# RateCard — the enum check at priority 7, the shape check at priority 28
# ============================================================================

DESIGN_CARD_FROM = "2026-01-01"
DESIGN_CARD_TO = "2026-12-31"


def rate_card_body(item_id: str, item_version: int, **fields) -> dict:
    """A rate-card proposal body carrying the mandatory OCC token and the
    design's one-year window, plus whatever rate fields the case supplies."""
    body = {
        "contracted_item_id": item_id,
        "expected_contracted_item_version": item_version,
        "effective_from": DESIGN_CARD_FROM,
        "effective_to": DESIGN_CARD_TO,
    }
    body.update(fields)
    return body


def test_rate_card_out_of_enum_rate_type_is_the_body_check_not_the_shape_check():
    """rate_type PER_POUND is outside the declared value set, so the priority-7
    body check fires with a 400 before the priority-28 rate-shape check is ever
    reached — even though a companion PER_CASE rate field was supplied.

    PRD: "every enum-valued field carries a declared member of its value set,
    and no unknown field is supplied — otherwise `ERR_INVALID_REQUEST`."

    Design: Corner/entities/rate_card_shape_and_enum_constraints_are_rejected
    """
    _, item = deal_with_one_item()

    response = api_client.create_rate_card(
        rate_card_body(
            item["id"],
            item["version"],
            rate_type="PER_POUND",
            flat_rate_cents_per_case=150,
        ),
        ADMIN,
    )
    validate_error(response, ApiErrorId.ERR_INVALID_REQUEST, 400)

    _, meta = validate_paginated(api_client.list_rate_cards(ADMIN))
    assert meta["total_count"] == 0, "the rejected proposal persisted no card"


def test_rate_card_rate_fields_must_match_the_declared_rate_type():
    """A well-typed PER_CASE card that carries percent_bps instead of
    flat_rate_cents_per_case is the priority-28 shape rejection with 422: each
    mechanic requires its own field and forbids the other two outright.

    PRD: "A card whose supplied rate fields do not match its declared
    `rate_type`, or whose `tier_breaks` violates any of those structural rules,
    is rejected with `ERR_RATE_CARD_SHAPE_INVALID`."

    Design: Corner/entities/rate_card_shape_and_enum_constraints_are_rejected
    """
    _, item = deal_with_one_item()

    response = api_client.create_rate_card(
        rate_card_body(
            item["id"],
            item["version"],
            rate_type=RateType.PER_CASE.value,
            percent_bps=275,
        ),
        ADMIN,
    )
    validate_error(response, ApiErrorId.ERR_RATE_CARD_SHAPE_INVALID, 422)

    _, meta = validate_paginated(api_client.list_rate_cards(ADMIN))
    assert meta["total_count"] == 0, "the rejected proposal persisted no card"


def test_tiered_volume_ladder_rules_are_each_enforced_independently():
    """All four tier_breaks structural rules reject with 422 on their own — a
    one-entry ladder, a first min_cases that is not 0, a non-increasing
    min_cases and a zero rate — while the well-formed three-entry ladder is
    accepted and is the only call that advances the item's version.

    PRD: "the array must hold at least 2 entries, the first entry's `min_cases`
    must be 0, `min_cases` must strictly increase down the array, and every
    `rate_cents_per_case` must be at least 1."

    Design: Corner/entities/rate_card_shape_and_enum_constraints_are_rejected
    """
    _, item = deal_with_one_item()
    item_version = item["version"]

    malformed_ladders = [
        ("a single-entry ladder is below the 2-entry minimum",
         [{"min_cases": 0, "rate_cents_per_case": 120}]),
        ("the first min_cases must be 0",
         [{"min_cases": 10, "rate_cents_per_case": 120},
          {"min_cases": 50, "rate_cents_per_case": 180}]),
        ("min_cases must strictly increase",
         [{"min_cases": 0, "rate_cents_per_case": 120},
          {"min_cases": 0, "rate_cents_per_case": 180}]),
        ("every rate_cents_per_case must be at least 1",
         [{"min_cases": 0, "rate_cents_per_case": 0},
          {"min_cases": 50, "rate_cents_per_case": 180}]),
    ]
    for reason, tier_breaks in malformed_ladders:
        response = api_client.create_rate_card(
            rate_card_body(
                item["id"],
                item_version,
                rate_type=RateType.TIERED_VOLUME.value,
                tier_breaks=tier_breaks,
            ),
            ADMIN,
        )
        validate_error(response, ApiErrorId.ERR_RATE_CARD_SHAPE_INVALID, 422)
        assert response.status_code == 422, reason

    good_ladder = [dict(entry) for entry in C.TIER_BREAKS]
    accepted = api_client.create_rate_card(
        rate_card_body(
            item["id"],
            item_version,
            rate_type=RateType.TIERED_VOLUME.value,
            tier_breaks=good_ladder,
        ),
        ADMIN,
    )
    card = validate_success(accepted, 201)
    assert_rate_card(card)
    assert card["status"] == RateCardStatus.PROPOSED.value
    assert card["rate_type"] == RateType.TIERED_VOLUME.value
    assert card["tier_breaks"] == good_ladder
    assert card.get("flat_rate_cents_per_case") is None, (
        "TIERED_VOLUME forbids the PER_CASE field"
    )
    assert card.get("percent_bps") is None, (
        "TIERED_VOLUME forbids the PERCENT_OF_SPEND field"
    )

    reread_item = validate_success(
        api_client.get_contracted_item(item["id"], ADMIN), 200
    )
    assert reread_item["version"] == item_version + 1, (
        "only the accepted proposal advances the item version, so the OCC token "
        "stayed valid across every rejected attempt"
    )


# ============================================================================
# ComplianceReview — the one entity with no version and no update endpoint
# ============================================================================

def test_a_second_compliance_review_writes_a_second_immutable_row():
    """Running the same (member, deal, window) review twice creates two distinct
    rows rather than mutating the first; neither carries updated_at or version,
    and both freeze the identical six computed figures.

    PRD: "`ComplianceReview` is the one exception. A review is a point-in-time
    verdict rather than a living record: it carries `id` and `created_at` only.
    It has no `updated_at` and no `version`, there is no endpoint that modifies
    it, and its computed verdict fields are frozen at the moment it is written."

    Design: Corner/entities/compliance_review_row_is_immutable_with_no_version_field
    """
    ctx = fx.setup_flat_program()
    payload = F.compliance_review_payload(
        ctx["member_id"], ctx["deal_id"], REVIEW_WINDOW_START, REVIEW_WINDOW_END
    )

    first = api_client.create_compliance_review(dict(payload), ANALYST)
    review_one = validate_success(first, 201)
    second = api_client.create_compliance_review(dict(payload), ADMIN)
    review_two = validate_success(second, 201)

    assert review_one["id"] != review_two["id"], (
        "the second review is a new row, not an update of the first"
    )

    assert REVIEW_PRORATED_COMMITMENT_CENTS == round_half_up(
        C.MEMBER_COMMITTED_ANNUAL_SPEND_CENTS * REVIEW_WINDOW_DAYS, C.DAYS_PER_YEAR
    ), "20000000 * 31 / 365 rounded half up is 1698630"

    for review in (review_one, review_two):
        assert_compliance_review(review)
        assert "version" not in review, "a compliance review carries no version"
        assert "updated_at" not in review, "a compliance review carries no updated_at"
        assert review["window_days"] == REVIEW_WINDOW_DAYS
        assert review["committed_spend_prorated_cents"] == (
            REVIEW_PRORATED_COMMITMENT_CENTS
        )
        assert review["contracted_spend_cents"] == 0
        assert review["deal_wide_contracted_spend_cents"] == 0
        assert review["purchase_ratio_bps"] == 0
        assert review["result"] == ComplianceResult.BREACH.value
        assert review["triggered_deal_loss"] is False

    rows, meta = validate_paginated(
        api_client.list_compliance_reviews(
            ADMIN, {"member_id": ctx["member_id"], "limit": C.MAX_LIMIT}
        )
    )
    assert meta["total_count"] == 2
    assert {row["id"] for row in rows} == {review_one["id"], review_two["id"]}


def test_the_breach_verdict_suspends_the_member_and_spares_the_deal():
    """The first BREACH review suspends the member and holds its payouts; the
    second changes nothing because the ACTIVE -> SUSPENDED transition cannot
    re-fire, and the deal stays ACTIVE because 31 window days fall short of the
    deal's 60-day required purchase window.

    PRD: "A `BREACH` costs the member its standing: it moves `ACTIVE →
    SUSPENDED`, its `payout_hold` is set to true and its `version` is incremented
    by 1"

    Design: Corner/entities/compliance_review_row_is_immutable_with_no_version_field
    """
    ctx = fx.setup_flat_program()
    payload = F.compliance_review_payload(
        ctx["member_id"], ctx["deal_id"], REVIEW_WINDOW_START, REVIEW_WINDOW_END
    )

    validate_success(api_client.create_compliance_review(dict(payload), ANALYST), 201)
    after_first = validate_success(
        api_client.get_member(ctx["member_id"], ADMIN), 200
    )
    assert after_first["enrollment_status"] == MemberEnrollmentStatus.SUSPENDED.value
    assert after_first["payout_hold"] is True

    validate_success(api_client.create_compliance_review(dict(payload), ADMIN), 201)
    after_second = validate_success(
        api_client.get_member(ctx["member_id"], ADMIN), 200
    )
    assert after_second["enrollment_status"] == MemberEnrollmentStatus.SUSPENDED.value
    assert after_second["payout_hold"] is True
    assert after_second["version"] == after_first["version"], (
        "the member is no longer ACTIVE, so the second review re-fires nothing"
    )

    deal = validate_success(api_client.get_deal(ctx["deal_id"], ADMIN), 200)
    assert deal["status"] == DealStatus.ACTIVE.value, (
        "window_days 31 is below required_purchase_window_days 60, so the "
        "DEAL_LOST branch cannot fire"
    )


# ============================================================================
# ContractedItem — the body foreign key resolves before any state check
# ============================================================================

def test_contracted_item_with_unknown_parent_deal_returns_not_found():
    """An unknown deal_id in the body is the priority-9 foreign-key resolution
    failing with ERR_DEAL_NOT_FOUND (404), and the deal that does exist keeps
    its contracted_item_count at 0.

    PRD: "Foreign keys carried in the request body are resolved later, after the
    body's shape has been checked, and are resolved in the order in which the
    endpoint declares its input fields; the same not-found codes apply."

    Design: Corner/entities/contracted_item_with_unknown_parent_deal_returns_not_found
    """
    deal = fx.create_deal()

    response = api_client.create_contracted_item(
        F.contracted_item_payload(UNKNOWN_ID), ADMIN
    )
    validate_error(response, ApiErrorId.ERR_DEAL_NOT_FOUND, 404)

    reread = validate_success(api_client.get_deal(deal["id"], ADMIN), 200)
    assert reread["contracted_item_count"] == 0, (
        "the failed call recomputed nothing on the deal that does exist"
    )
    _, meta = validate_paginated(api_client.list_contracted_items(ADMIN))
    assert meta["total_count"] == 0


def test_contracted_item_create_recomputes_the_parent_deal_count():
    """A clean item create returns 201 with its own creation defaults and lifts
    the parent deal's contracted_item_count to 1, and the item is reachable back
    from the parent through the deal_id filter.

    PRD: "A new item's `status` is `ACTIVE`, its `approved_rate_card_count` is 0
    and its `version` is 1, and the owning deal's `contracted_item_count` is
    recomputed."

    Design: Corner/entities/contracted_item_with_unknown_parent_deal_returns_not_found
    """
    deal = fx.create_deal()

    response = api_client.create_contracted_item(
        F.contracted_item_payload(deal["id"]), ADMIN
    )
    item = validate_success(response, 201)
    assert_contracted_item(item)

    assert item["deal_id"] == deal["id"]
    assert item["status"] == ItemStatus.ACTIVE.value
    assert item["approved_rate_card_count"] == 0
    assert item["version"] == 1

    reread = validate_success(api_client.get_deal(deal["id"], ADMIN), 200)
    assert reread["contracted_item_count"] == 1

    rows, meta = validate_paginated(
        api_client.list_contracted_items(
            ADMIN, {"deal_id": deal["id"], "limit": C.MAX_LIMIT}
        )
    )
    assert meta["total_count"] == 1
    assert len(rows) == 1 and rows[0]["id"] == item["id"]


# ============================================================================
# PurchaseLine — the two flat foreign keys are validated on separate axes
# ============================================================================

def test_purchase_line_body_foreign_keys_resolve_on_independent_axes():
    """An unknown member_id yields ERR_MEMBER_NOT_FOUND and an unknown
    purchase_batch_id yields ERR_BATCH_NOT_FOUND: each body foreign key is
    resolved on its own, and a batch that does not exist cannot be compared to
    the calling distributor at all.

    PRD: "Path variables therefore always name a single record" and "Foreign
    keys carried in the request body are resolved later, after the body's shape
    has been checked, and are resolved in the order in which the endpoint
    declares its input fields; the same not-found codes apply."

    Design: Corner/entities/purchase_line_resolves_both_flat_foreign_keys_independently
    """
    ctx = member_authorized_for_the_other_distributor()

    unknown_member = api_client.create_purchase_line(
        F.purchase_line_payload(ctx["batch_id"], UNKNOWN_ID), ctx["metro_headers"]
    )
    validate_error(unknown_member, ApiErrorId.ERR_MEMBER_NOT_FOUND, 404)

    unknown_batch = api_client.create_purchase_line(
        F.purchase_line_payload(UNKNOWN_ID, ctx["member_id"]), ctx["metro_headers"]
    )
    validate_error(unknown_batch, ApiErrorId.ERR_BATCH_NOT_FOUND, 404)

    batch = validate_success(
        api_client.get_purchase_batch(ctx["batch_id"], ANALYST), 200
    )
    assert batch["line_count"] == 0
    assert batch["total_cases_ingested"] == 0


def test_purchase_line_requires_a_letter_for_the_batchs_own_distributor():
    """The member exists and is ACTIVE, so the enrollment check passes, but its
    only ACTIVE letter names the other distributor — so the ingest is refused
    with ERR_LOA_NOT_ACTIVE (409) and no line is stored.

    PRD: "the member must hold at least one authorization letter whose `status`
    is `ACTIVE`, whose `distributor_id` is the batch's distributor, and whose
    half-open window contains the current logical-clock instant, and a line
    lacking one is rejected with `ERR_LOA_NOT_ACTIVE`."

    Design: Corner/entities/purchase_line_resolves_both_flat_foreign_keys_independently
    """
    ctx = member_authorized_for_the_other_distributor()
    assert ctx["member"]["enrollment_status"] == MemberEnrollmentStatus.ACTIVE.value

    response = api_client.create_purchase_line(
        F.purchase_line_payload(ctx["batch_id"], ctx["member_id"]),
        ctx["metro_headers"],
    )
    validate_error(response, ApiErrorId.ERR_LOA_NOT_ACTIVE, 409)

    batch = validate_success(
        api_client.get_purchase_batch(ctx["batch_id"], ANALYST), 200
    )
    assert batch["line_count"] == 0
    assert batch["total_cases_ingested"] == 0

    letters, meta = validate_paginated(
        api_client.list_authorization_letters(
            ADMIN,
            {
                "member_id": ctx["member_id"],
                "status": "ACTIVE",
                "limit": C.MAX_LIMIT,
            },
        )
    )
    assert meta["total_count"] == 1
    assert len(letters) == 1
    assert letters[0]["distributor_id"] == ctx["sysco"]["id"], (
        "the member's single ACTIVE letter names SYSCO-02, not the batch's METRO-01"
    )
