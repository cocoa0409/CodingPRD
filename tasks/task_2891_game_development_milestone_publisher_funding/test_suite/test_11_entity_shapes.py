"""Entity shapes: what a create returns, what a read echoes, how a filtered list
paginates, and what an unknown id or a missing field answers."""

from test_helpers import factories as f
from test_helpers.assertions import (
    assert_calendar_date,
    assert_common_fields,
    assert_fields_equal,
    assert_instant_format,
    assert_ledger,
    assert_pct_equals,
)
from test_helpers.api_errors import ERR_AGREEMENT_NOT_FOUND, ERR_INVALID_REQUEST
from test_helpers.constants import UNKNOWN_AGREEMENT_ID
from test_helpers.fixtures import (
    DEFAULT_CRITERIA_1,
    add_milestone,
    draft_agreement,
    setup_registry,
)
from prd_bench_local_runner.testing import (
    is_valid_uuid,
    validate_error,
    validate_paginated,
    validate_success,
)

CRITERIA = ["Core loop playable", "Two biomes complete", "Save and load"]


def test_creating_an_agreement_returns_the_whole_initialised_ledger(api):
    """PRD §3.2: "Creation leaves the agreement in `DRAFT` with a `version` of 1 and a
    completely initialised ledger: `funding_posture` is `OPEN`, `recoupment_state` is
    `PRE_RECOUP`, `post_launch_support_state` is `PENDING`, `ip_reversion_state` is
    `NONE` and `sequel_rights_holder` is `PUBLISHER`."

    Design: Corner/entities/corner_create_development_agreement_returns_full_declared_field_set
    """
    reg = setup_registry(api, with_reviewer=False)

    agreement = validate_success(
        api.create_agreement(
            f.agreement_payload(
                reg.studio_id, reg.publisher_id, "Aurora Drift", 12000000, 2500,
                "2027-03-31", 2000, 3000, 500000,
            ),
            reg.finance,
        ),
        201,
    )
    assert_common_fields(agreement, "agreement")
    assert_fields_equal(
        agreement,
        {"status": "DRAFT", "version": 1, "funding_posture": "OPEN",
         "recoupment_state": "PRE_RECOUP", "post_launch_support_state": "PENDING",
         "ip_reversion_state": "NONE", "sequel_rights_holder": "PUBLISHER",
         "live_ops_drawn_cents": 0, "schedule_slip_days": 0,
         "ship_date_current": "2027-03-31", "ship_date_original": "2027-03-31",
         "terminated_at": None},
        "agreement",
    )
    assert_ledger(
        agreement,
        funding_pool_cents=12000000,
        committed_cents=0,
        available_funding_cents=12000000,
        accepted_value_cents=0,
        advance_disbursed_cents=0,
        holdback_reserve_cents=0,
        withheld_payment_cents=0,
        advance_recouped_cents=0,
        unrecouped_advance_cents=0,
        royalties_paid_to_date_cents=0,
        breach_count=0,
    )


def test_reading_a_milestone_echoes_the_stored_row(api):
    """PRD §3.2: "A milestone is born `DEFINED` with `uplift_cents` at 0, `cure_count`
    at 0, `content_threshold_relief_pct` at 0.00, `latest_build_number` at 0,
    `open_condition_indexes` an empty array, and `cure_deadline_at` and `accepted_at`
    both null."

    Design: Corner/entities/corner_get_milestone_returns_the_stored_row
    """
    reg = setup_registry(api, with_reviewer=False)
    agreement = draft_agreement(reg, "Aurora Drift", 3600000,
                                live_ops_quarterly_funding_cents=100000)
    created = add_milestone(reg, agreement["id"], 1, "Alpha", "ALPHA",
                            3600000, 800000, CRITERIA)

    milestone = validate_success(api.get_milestone(created["id"], reg.dev))
    assert_fields_equal(
        milestone,
        {"agreement_id": agreement["id"], "status": "DEFINED", "gate_profile": "ALPHA",
         "sequence_index": 1, "funded_amount_cents": 3600000, "uplift_cents": 0,
         "contractor_budget_cents": 800000, "acceptance_criteria": CRITERIA,
         "cure_count": 0, "latest_build_number": 0, "open_condition_indexes": [],
         "cure_deadline_at": None, "accepted_at": None},
        "milestone",
    )
    assert_pct_equals(milestone["content_threshold_relief_pct"], 0.00, "relief")


def test_the_milestone_list_pages_the_whole_filtered_set(api):
    """PRD §2.3: "A filter value that matches nothing yields an empty array with
    `total_count` of 0, not an error"; filters narrow the set while `total_count`
    describes the filtered set rather than the page.

    Design: Corner/entities/corner_list_milestones_by_agreement_paginates_with_total_count_and_has_more
    """
    reg = setup_registry(api, with_reviewer=False)
    agreement = draft_agreement(reg, "Aurora Drift", 12000000,
                                live_ops_quarterly_funding_cents=500000)
    other = draft_agreement(reg, "Side Project", 1000000, 2000, "2028-01-31",
                            live_ops_quarterly_funding_cents=100000)
    m1 = add_milestone(reg, agreement["id"], 1, "Alpha", "ALPHA", 3600000, 800000,
                       DEFAULT_CRITERIA_1)
    m2 = add_milestone(reg, agreement["id"], 2, "Beta", "BETA", 5400000, 600000,
                       DEFAULT_CRITERIA_1, m1["id"])
    m3 = add_milestone(reg, agreement["id"], 3, "Gold", "GOLD", 3000000, 400000,
                       DEFAULT_CRITERIA_1, m2["id"])

    page1, meta1 = validate_paginated(
        api.list_milestones(reg.finance, {"agreement_id": agreement["id"],
                                          "limit": 2, "offset": 0})
    )
    assert len(page1) == 2
    assert_fields_equal(
        meta1, {"total_count": 3, "has_more": True, "limit": 2, "offset": 0}, "meta"
    )

    page2, meta2 = validate_paginated(
        api.list_milestones(reg.finance, {"agreement_id": agreement["id"],
                                          "limit": 2, "offset": 2})
    )
    assert len(page2) == 1
    assert_fields_equal(
        meta2, {"total_count": 3, "has_more": False, "offset": 2}, "meta"
    )

    seen = [row["id"] for row in page1] + [row["id"] for row in page2]
    assert len(seen) == len(set(seen))
    assert set(seen) == {m1["id"], m2["id"], m3["id"]}

    empty, meta3 = validate_paginated(
        api.list_milestones(reg.finance, {"agreement_id": other["id"]})
    )
    assert empty == []
    assert_fields_equal(meta3, {"total_count": 0, "has_more": False}, "meta")


def test_an_unknown_agreement_id_answers_the_scoped_not_found_code(api):
    """PRD §2.10 rule 10: "An agreement identifier in the path resolves, on the
    agreement read, the agreement's royalty-statement and recoupment-summary reads,
    and on activate, suspend, reinstate, terminate, cure-sweep and live-ops-draw —
    `ERR_AGREEMENT_NOT_FOUND`." PRD §5 maps `ERR_AGREEMENT_NOT_FOUND` to 404.

    Design: Corner/entities/corner_get_development_agreement_with_unknown_id_returns_agreement_not_found
    """
    reg = setup_registry(api, with_reviewer=False)

    response = api.get_agreement(UNKNOWN_AGREEMENT_ID, reg.finance)
    validate_error(response, ERR_AGREEMENT_NOT_FOUND, 404)

    body = response.json()
    assert isinstance(body["data"]["message"], str) and body["data"]["message"].strip()


def test_a_milestone_without_a_gate_profile_is_a_structural_rejection(api):
    """PRD §2.10 rule 6: "The request body is structurally valid, on every endpoint
    that takes a body — `ERR_INVALID_REQUEST`." A milestone needs its `gate_profile`
    to have any gate at all.

    Design: Corner/entities/corner_create_milestone_without_gate_profile_returns_invalid_request
    """
    reg = setup_registry(api, with_reviewer=False)
    agreement = draft_agreement(reg, "Aurora Drift", 3600000,
                                live_ops_quarterly_funding_cents=100000)

    payload = f.milestone_payload(agreement["id"], 1, "Alpha", "ALPHA", 3600000,
                                  800000, DEFAULT_CRITERIA_1)
    payload.pop("gate_profile")
    validate_error(api.create_milestone(payload, reg.dev), ERR_INVALID_REQUEST, 400)

    rows, meta = validate_paginated(
        api.list_milestones(reg.finance, {"agreement_id": agreement["id"]})
    )
    assert rows == [] and meta["total_count"] == 0
    assert_ledger(
        validate_success(api.get_agreement(agreement["id"], reg.finance)),
        committed_cents=0,
        available_funding_cents=3600000,
    )


def test_the_omitted_rate_fields_take_their_contractual_defaults(api):
    """PRD §3.2: "`recoupable_cost_cap_bps` ... accepts 0 through 4000 and defaults to
    2000 ... `platform_fee_bps` ... accepts 0 through 5000 and defaults to 3000 ...
    `live_ops_quarterly_funding_cents` sets the per-quarter live-operations envelope
    that becomes drawable after launch, must not be negative, and defaults to 0".

    Design: Corner/entities/corner_agreement_optional_rate_fields_fall_back_to_declared_defaults
    """
    reg = setup_registry(api, with_reviewer=False)

    payload = f.agreement_payload(
        reg.studio_id, reg.publisher_id, "Bare Bones Deal", 4000000, 1800, "2027-12-31"
    )
    for omitted in ("recoupable_cost_cap_bps", "platform_fee_bps",
                    "live_ops_quarterly_funding_cents"):
        assert omitted not in payload

    agreement = validate_success(api.create_agreement(payload, reg.finance), 201)
    assert_fields_equal(
        agreement,
        {"recoupable_cost_cap_bps": 2000, "platform_fee_bps": 3000,
         "live_ops_quarterly_funding_cents": 0, "royalty_rate_bps": 1800,
         "advance_total_cents": 4000000},
        "agreement",
    )
    assert is_valid_uuid(agreement["id"])
    assert_instant_format(agreement["created_at"], "created_at")
    assert_calendar_date(agreement["ship_date_original"], "ship_date_original")
