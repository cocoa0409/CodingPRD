"""Publication snapshot, the appeal loop and reprint licence arithmetic."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    api_client,
    create_analyst,
    create_document,
    create_inclusion,
    create_vendor,
    finalize_inclusion,
    get_document,
    get_success_data,
    make_vendor_rep_headers,
    publish_document,
    record_peer_verdict,
    respond_fact_check,
    decide_fact_check,
    set_clock,
    setup_document_with_inclusion,
    setup_published_document,
    submit_for_review,
    validate_error,
)


def test_reprint_bracket_is_selected_from_the_pre_discount_total():
    """PRD §2.9: "The volume discount is selected from that pre-discount total, which
    already contains the overage component: 15 percent when the pre-discount total is
    at least 1,000,000 cents, otherwise 10 percent when it is at least 500,000 cents,
    otherwise no discount."
    PRD §2.9: "Selecting the discount bracket after discounting instead of before is
    expressly rejected, because it can drop an order into a lower bracket; the bracket
    is always chosen from the pre-discount total."

    Design: Difficulty/combinatorial_formula/reprint_fee_bracket_selected_from_pre_discount_total
    """
    set_clock("2026-09-01T00:00:00Z")
    lead = create_analyst()
    vendor = create_vendor()
    document = create_document(lead)
    inclusion = create_inclusion(
        document, vendor, reprint_tier="STANDARD", permitted_marketing_use="FULL_REPRINT",
        reprint_copies_authorized=800,
    )

    adjusted = get_success_data(
        api_client.adjust_reprint_copies(
            inclusion["id"],
            {"delta_copies": 800, "permitted_marketing_use": "FULL_REPRINT"},
            make_vendor_rep_headers(vendor["id"]),
        )
    )
    assert adjusted["reprint_copies_used"] == 800
    assert adjusted["reprint_fee_cents"] == 468000, (
        "250000 base + 300 overage copies at 900 = 520000, less the 10 percent bracket"
    )
    assert adjusted["reprint_fee_cents"] != 520000


def test_discount_bracket_boundary_makes_the_larger_order_cheaper():
    """PRD §2.9: "The volume discount is selected from that pre-discount total, which
    already contains the overage component: 15 percent when the pre-discount total is
    at least 1,000,000 cents, otherwise 10 percent when it is at least 500,000 cents,
    otherwise no discount."
    PRD §2.9: "The overage copy count is the larger of 0 and the used copies minus the
    tier's included copies, and the overage fee is the overage copy count multiplied by
    the tier's per-copy rate."

    Design: Difficulty/combinatorial_formula/reprint_fee_bracket_selected_from_pre_discount_total
    """
    set_clock("2026-09-01T00:00:00Z")
    lead = create_analyst()
    vendor = create_vendor()
    document = create_document(lead)
    inclusion = create_inclusion(
        document, vendor, reprint_tier="STANDARD", permitted_marketing_use="FULL_REPRINT",
        reprint_copies_authorized=800,
    )
    vendor_headers = make_vendor_rep_headers(vendor["id"])

    below = get_success_data(
        api_client.adjust_reprint_copies(
            inclusion["id"], {"delta_copies": 777}, vendor_headers
        )
    )
    assert below["reprint_copies_used"] == 777
    assert below["reprint_fee_cents"] == 499300, (
        "250000 + 277 * 900 = 499300, which misses the 500000 bracket entirely"
    )

    above = get_success_data(
        api_client.adjust_reprint_copies(
            inclusion["id"], {"delta_copies": 1}, vendor_headers
        )
    )
    assert above["reprint_copies_used"] == 778
    assert above["reprint_fee_cents"] == 450180, (
        "250000 + 278 * 900 = 500200 clears the bracket, so the fee drops"
    )


def test_appeal_loop_is_capped_at_two_filings():
    """PRD §3.7: "The appeal loop runs `EXCLUDED` → `UNDER_APPEAL` → `APPEAL_DENIED` →
    `UNDER_APPEAL` and is capped at an `appeal_count` of 2."
    PRD §3.7: "an appeal attempted once `appeal_count` is already 2 is rejected with
    `ERR_APPEAL_LIMIT_REACHED` (HTTP 409)."

    Design: Difficulty/non_linear_state_machine/appeal_denied_loop_capped_at_two_filings
    """
    scenario = setup_published_document(exclude_vendor=True)
    inclusion = scenario["excluded_inclusion"]
    vendor_headers = make_vendor_rep_headers(scenario["excluded_vendor"]["id"])
    director_headers = TEST_USERS["research_director_headers"]

    set_clock("2026-09-10T00:00:00Z")
    first = get_success_data(
        api_client.file_appeal(
            inclusion["id"], {"appeal_grounds": "Scoring used a stale roadmap."},
            vendor_headers,
        )
    )
    assert first["inclusion_status"] == "UNDER_APPEAL"
    assert first["appeal_count"] == 1

    denied = get_success_data(
        api_client.decide_appeal(
            inclusion["id"],
            {"outcome": "DENY", "rationale": "Roadmap evidence was current."},
            director_headers,
        )
    )
    assert denied["inclusion_status"] == "APPEAL_DENIED"
    assert denied["appeal_count"] == 1

    second = get_success_data(
        api_client.file_appeal(
            inclusion["id"], {"appeal_grounds": "Second filing with new roadmap evidence."},
            vendor_headers,
        )
    )
    assert second["inclusion_status"] == "UNDER_APPEAL"
    assert second["appeal_count"] == 2

    # Deny the second appeal so the inclusion comes to rest in APPEAL_DENIED —
    # the other source state PRD 3.7 admits — leaving appeal_count as the only
    # gate on a third filing.  Filing straight from UNDER_APPEAL would instead
    # trip the target-state check (precedence 5) and report ERR_INVALID_STATE.
    second_denied = get_success_data(
        api_client.decide_appeal(
            inclusion["id"],
            {"outcome": "DENY", "rationale": "No new evidence on the second filing."},
            director_headers,
        )
    )
    assert second_denied["inclusion_status"] == "APPEAL_DENIED"
    assert second_denied["appeal_count"] == 2

    third = api_client.file_appeal(
        inclusion["id"], {"appeal_grounds": "Third filing attempt."}, vendor_headers
    )
    validate_error(third, ApiErrorId.ERR_APPEAL_LIMIT_REACHED)

    after = get_success_data(api_client.get_inclusion(inclusion["id"]))
    assert after["appeal_count"] == 2
    assert after["inclusion_status"] == "APPEAL_DENIED"


def test_appeal_may_be_filed_exactly_at_the_window_close():
    """PRD §2.4: "An appeal may be filed while the clock reading is at or before
    `appeal_window_closes_at`."
    PRD §3.7: "An appeal filed after the window closes is rejected with
    `ERR_APPEAL_WINDOW_CLOSED` (HTTP 409), and an appeal attempted once `appeal_count`
    is already 2 is rejected with `ERR_APPEAL_LIMIT_REACHED` (HTTP 409)."

    Design: Difficulty/non_linear_state_machine/appeal_denied_loop_capped_at_two_filings
    """
    scenario = setup_published_document(exclude_vendor=True)
    inclusion = scenario["excluded_inclusion"]
    vendor_headers = make_vendor_rep_headers(scenario["excluded_vendor"]["id"])
    director_headers = TEST_USERS["research_director_headers"]

    window = get_success_data(api_client.get_inclusion(inclusion["id"]))
    assert window["appeal_window_closes_at"] == "2026-10-01T00:00:00Z"

    set_clock("2026-10-01T00:00:00Z")
    accepted = get_success_data(
        api_client.file_appeal(
            inclusion["id"], {"appeal_grounds": "Filed on the last instant."}, vendor_headers
        )
    )
    assert accepted["inclusion_status"] == "UNDER_APPEAL"
    assert accepted["appeal_count"] == 1

    get_success_data(
        api_client.decide_appeal(inclusion["id"], {"outcome": "DENY"}, director_headers)
    )
    set_clock("2026-10-02T00:00:00Z")
    late = api_client.file_appeal(
        inclusion["id"], {"appeal_grounds": "Filed after the window."}, vendor_headers
    )
    validate_error(late, ApiErrorId.ERR_APPEAL_WINDOW_CLOSED)


def test_publish_cascade_locks_placements_and_flags_vendors():
    """PRD §3.6: "First, every inclusion on the document receives `placement_locked`
    true, and its `weighted_total_score` is frozen at its current value. Second, for
    each inclusion whose `inclusion_status` is `INCLUDED`, the linked `Vendor`'s
    `briefing_eligible` becomes true; for each inclusion whose `inclusion_status` is
    `EXCLUDED`, that inclusion's `appeal_window_closes_at` is set to `published_at`
    plus 30 days. Third, the document's `included_vendor_count` is recomputed from the
    frozen snapshot".

    Design: Difficulty/transitive_cascade/publish_cascade_locks_placements_then_flags_vendors
    """
    scenario = setup_published_document(exclude_vendor=True)
    document = get_document(scenario["document"])
    assert document["editorial_status"] == "PUBLISHED"
    assert document["included_vendor_count"] == 1

    included = get_success_data(api_client.get_inclusion(scenario["inclusion"]["id"]))
    excluded = get_success_data(api_client.get_inclusion(scenario["excluded_inclusion"]["id"]))
    assert included["placement_locked"] is True
    assert included["weighted_total_score"] == 3.86
    assert excluded["placement_locked"] is True
    assert excluded["inclusion_status"] == "EXCLUDED"
    assert excluded["appeal_window_closes_at"] == "2026-10-01T00:00:00Z"

    assert get_success_data(api_client.get_vendor(scenario["vendor"]["id"]))["briefing_eligible"] is True
    assert get_success_data(
        api_client.get_vendor(scenario["excluded_vendor"]["id"])
    )["briefing_eligible"] is False


def test_publish_cascade_reaches_every_inclusion_and_vendor_on_the_document():
    """PRD §3.6: "Second, for each inclusion whose `inclusion_status` is `INCLUDED`,
    the linked `Vendor`'s `briefing_eligible` becomes true; for each inclusion whose
    `inclusion_status` is `EXCLUDED`, that inclusion's `appeal_window_closes_at` is
    set to `published_at` plus 30 days. Third, the document's `included_vendor_count`
    is recomputed from the frozen snapshot, counting inclusions whose
    `inclusion_status` is `INCLUDED` or `APPEAL_UPHELD`."

    Design: Difficulty/transitive_cascade/publish_cascade_locks_placements_then_flags_vendors
    """
    set_clock("2026-09-01T00:00:00Z")
    scenario = setup_document_with_inclusion()
    second_vendor = create_vendor(
        vendor_name="Bluepeak Systems", hq_region="EMEA", employee_count_band="MIDMARKET"
    )
    fresh = get_document(scenario["document"])
    second_inclusion = create_inclusion(fresh, second_vendor)

    finalize_inclusion(scenario["inclusion"], "INCLUDE")
    finalize_inclusion(second_inclusion, "INCLUDE")
    submit_for_review(scenario["document"], scenario["lead"], scenario["reviewer"])
    record_peer_verdict(scenario["document"], scenario["reviewer"], "APPROVE")
    for inclusion, vendor in ((scenario["inclusion"], scenario["vendor"]),
                              (second_inclusion, second_vendor)):
        respond_fact_check(inclusion, vendor)
        decide_fact_check(inclusion, "ACCEPT")

    scenario["document"] = publish_document(get_document(scenario["document"]))
    document = get_document(scenario["document"])
    assert document["editorial_status"] == "PUBLISHED"
    assert document["included_vendor_count"] == 2

    first = get_success_data(api_client.get_inclusion(scenario["inclusion"]["id"]))
    other = get_success_data(api_client.get_inclusion(second_inclusion["id"]))
    assert first["placement_locked"] is True
    assert other["placement_locked"] is True
    assert get_success_data(
        api_client.get_vendor(scenario["vendor"]["id"])
    )["briefing_eligible"] is True
    assert get_success_data(
        api_client.get_vendor(second_vendor["id"])
    )["briefing_eligible"] is True


def test_reprint_copies_and_fee_return_to_their_pre_adjustment_values():
    """PRD §2.9: "Copy adjustments are made by supplying `delta_copies`, which is
    applied to `reprint_copies_used` and recomputes the fee".
    PRD §2.9: "The fee `reprint_fee_cents` is the pre-discount total multiplied by one
    minus the discount percentage, multiplied by the use multiplier for
    `permitted_marketing_use` — 0.00 for `NO_USE`, 0.50 for `INTERNAL_ONLY`, 0.75 for
    `SOCIAL_SNIPPET`, and 1.00 for `FULL_REPRINT` — rounded half up to a whole number
    of cents."

    Design: Difficulty/compensating_invariant/reprint_copies_conserved_across_consume_and_return
    """
    set_clock("2026-09-01T00:00:00Z")
    lead = create_analyst()
    vendor = create_vendor()
    document = create_document(lead)
    inclusion = create_inclusion(
        document, vendor, reprint_tier="STANDARD", permitted_marketing_use="FULL_REPRINT",
        reprint_copies_authorized=800,
    )
    vendor_headers = make_vendor_rep_headers(vendor["id"])
    assert inclusion["reprint_copies_used"] == 0
    assert inclusion["reprint_fee_cents"] == 250000

    consumed = get_success_data(
        api_client.adjust_reprint_copies(
            inclusion["id"], {"delta_copies": 800, "permitted_marketing_use": "FULL_REPRINT"},
            vendor_headers,
        )
    )
    assert consumed["reprint_copies_used"] == 800
    assert consumed["reprint_fee_cents"] == 468000

    returned = get_success_data(
        api_client.adjust_reprint_copies(
            inclusion["id"], {"delta_copies": -800, "permitted_marketing_use": "FULL_REPRINT"},
            vendor_headers,
        )
    )
    assert returned["reprint_copies_used"] == 0
    assert returned["reprint_fee_cents"] == 250000, (
        "The bracket is re-derived, so the fee returns to its pre-adjustment value"
    )
    assert returned["reprint_copies_authorized"] == 800


def test_returning_more_copies_than_were_consumed_is_refused():
    """PRD §2.9: "An adjustment is refused with `ERR_REPRINT_COPIES_EXCEEDED`
    (HTTP 409) when it would drive `reprint_copies_used` below 0 or above
    `reprint_copies_authorized`."

    Design: Difficulty/compensating_invariant/reprint_copies_conserved_across_consume_and_return
    """
    set_clock("2026-09-01T00:00:00Z")
    lead = create_analyst()
    vendor = create_vendor()
    document = create_document(lead)
    inclusion = create_inclusion(
        document, vendor, reprint_tier="STANDARD", permitted_marketing_use="FULL_REPRINT",
        reprint_copies_authorized=800,
    )
    vendor_headers = make_vendor_rep_headers(vendor["id"])

    refused = api_client.adjust_reprint_copies(
        inclusion["id"], {"delta_copies": -1}, vendor_headers
    )
    validate_error(refused, ApiErrorId.ERR_REPRINT_COPIES_EXCEEDED)

    unchanged = get_success_data(api_client.get_inclusion(inclusion["id"]))
    assert unchanged["reprint_copies_used"] == 0
    assert unchanged["reprint_fee_cents"] == 250000


def test_premium_reprint_constants_apply_as_declared():
    """PRD §2.9: "The base fee is 0 cents for the `NONE` tier, 250,000 cents for
    `STANDARD`, and 600,000 cents for `PREMIUM`. The copies included in the base fee
    are 0 for `NONE`, 500 for `STANDARD`, and 2,000 for `PREMIUM`; each copy beyond
    that allowance costs 900 cents on `STANDARD` and 700 cents on `PREMIUM`".

    Design: Corner/calculations/reprint_fee_premium_tier_constants
    """
    set_clock("2026-09-01T00:00:00Z")
    lead = create_analyst()
    vendor = create_vendor()
    document = create_document(lead)
    inclusion = create_inclusion(
        document, vendor, reprint_tier="PREMIUM", permitted_marketing_use="FULL_REPRINT",
        reprint_copies_authorized=2500,
    )

    adjusted = get_success_data(
        api_client.adjust_reprint_copies(
            inclusion["id"],
            {"delta_copies": 2500, "permitted_marketing_use": "FULL_REPRINT"},
            make_vendor_rep_headers(vendor["id"]),
        )
    )
    assert adjusted["reprint_copies_used"] == 2500
    assert adjusted["reprint_fee_cents"] == 855000, (
        "600000 + 500 * 700 = 950000, less the 10 percent bracket"
    )
    assert adjusted["permitted_marketing_use"] == "FULL_REPRINT"


def test_finalize_is_refused_once_the_placement_snapshot_is_pinned():
    """PRD §2.11: "Target state: the resource named by the request is in a state from
    which the requested transition exists, and a resource in a terminal state rejects
    every further transition. Failure is `ERR_INVALID_STATE` (HTTP 409)."
    PRD §3.7: "An `INCLUDE` requires the inclusion to be `UNDER_EVALUATION`".
    PRD §3.6: "First, every inclusion on the document receives `placement_locked` true,
    and its `weighted_total_score` is frozen at its current value."

    Design: Corner/cross_cutting_complexity_layers/version_pinning_blocks_a_second_finalize_after_publication
    """
    scenario = setup_published_document()
    inclusion = get_success_data(api_client.get_inclusion(scenario["inclusion"]["id"]))
    assert inclusion["placement_locked"] is True
    assert inclusion["inclusion_status"] == "INCLUDED"
    assert inclusion["weighted_total_score"] == 3.86

    resp = api_client.finalize_inclusion(
        inclusion["id"], {"outcome": "EXCLUDE"}, TEST_USERS["research_director_headers"]
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)

    unchanged = get_success_data(api_client.get_inclusion(inclusion["id"]))
    assert unchanged["inclusion_status"] == "INCLUDED"
    assert unchanged["weighted_total_score"] == 3.86
