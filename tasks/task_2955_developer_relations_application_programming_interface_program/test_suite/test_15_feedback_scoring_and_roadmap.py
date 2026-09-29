"""Developer feedback and the roadmap it feeds: the referential prerequisites a submitted
item must satisfy, the two-pass triage scoring that folds an item's impact into its
product's shared demand index, the compensation a decline pays back into that index, and
the computed roadmap ranking read.
"""
from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import factories as f
from test_helpers.api_errors import ApiError
from test_helpers.assertions import (
    assert_fields,
    assert_id_sequence,
    assert_nulls,
)
from test_helpers.constants import UNKNOWN_ID
from test_helpers.test_users import DEV_REL_MANAGER, PLATFORM_ADMIN


def test_triaging_the_first_item_scores_it_against_the_index_it_has_just_joined(
    api, programme, certified_partner_entitlement
):
    """A DEFECT from a PARTNER-tier author holding a PROFESSIONAL certification takes a raw
    impact of 65.00, which becomes the product's whole demand index and lifts its own
    priority score to 73.45.

    PRD: "`raw_impact` is the severity weight multiplied by the tier weight, **plus** the certification bonus — the bonus is added after the product, not multiplied into it — rounded to 2 decimal places."

    Design: Difficulty/combinatorial_formula/feedback_priority_pinned_two_pass_demand_index
    """
    product_id = certified_partner_entitlement["product"]["id"]
    developer = certified_partner_entitlement["developer"]
    item = programme.submit_feedback(developer, product_id, category="DEFECT")

    triaged = validate_success(
        api.triage_feedback_item(item["id"], f.triage_payload(), DEV_REL_MANAGER)
    )

    # 40 x 1.50 + 5.00 = 65.00; factor 1 + 65.00/500 = 1.13; 65.00 x 1.13 = 73.45.
    assert_fields(
        triaged,
        "FeedbackItem",
        state="TRIAGED",
        author_top_tier="PARTNER",
        raw_impact=65.00,
        priority_score=73.45,
    )
    assert_fields(programme.read_product(product_id), "ApiProduct", demand_index=65.00)


def test_triaging_a_second_item_re_scores_the_first_against_the_grown_index(
    api, programme, certified_partner_entitlement
):
    """Folding a 20.00 documentation gap into the index lifts the shared demand factor to
    1.17, which re-scores the already-triaged defect from 73.45 to 76.05.

    PRD: "Because the factor is shared, triaging one item re-scores every other counted item of the same product — this is a ledger-wide recomputation, not a single-row update."

    Design: Difficulty/combinatorial_formula/feedback_priority_pinned_two_pass_demand_index
    """
    product_id = certified_partner_entitlement["product"]["id"]
    developer = certified_partner_entitlement["developer"]
    defect = programme.submit_feedback(developer, product_id, category="DEFECT")
    doc_gap = programme.submit_feedback(
        developer,
        product_id,
        category="DOC_GAP",
        body="The quickstart never mentions the documentation acknowledgement step.",
    )
    programme.triage_feedback(defect)

    triaged_doc_gap = validate_success(
        api.triage_feedback_item(doc_gap["id"], f.triage_payload(), DEV_REL_MANAGER)
    )

    # 10 x 1.50 + 5.00 = 20.00; index 85.00; factor 1.17; 20.00 x 1.17 = 23.40.
    assert_fields(
        triaged_doc_gap,
        "FeedbackItem",
        state="TRIAGED",
        author_top_tier="PARTNER",
        raw_impact=20.00,
        priority_score=23.40,
    )
    assert_fields(programme.read_product(product_id), "ApiProduct", demand_index=85.00)
    assert_fields(
        programme.read_feedback(defect["id"]),
        "FeedbackItem",
        raw_impact=65.00,
        priority_score=76.05,
    )


def test_declining_an_item_pays_its_impact_back_out_of_the_shared_index(
    api, programme, certified_partner_entitlement
):
    """Declining the documentation gap subtracts its 20.00 back out of the index, restores
    the defect's 73.45 score, and leaves the declined item with a null priority but its
    raw impact intact.

    PRD: "Declining moves it `TRIAGED → DECLINED` and compensates: the item's `raw_impact` is subtracted from the product's `demand_index`, the item's own `priority_score` is set back to null while its `raw_impact` is retained as the record of what was withdrawn, and every remaining counted item of the product is re-scored against the reduced index."

    Design: Difficulty/combinatorial_formula/feedback_priority_pinned_two_pass_demand_index
    """
    product_id = certified_partner_entitlement["product"]["id"]
    developer = certified_partner_entitlement["developer"]
    defect = programme.submit_feedback(developer, product_id, category="DEFECT")
    doc_gap = programme.submit_feedback(
        developer,
        product_id,
        category="DOC_GAP",
        body="The quickstart never mentions the documentation acknowledgement step.",
    )
    programme.triage_feedback(defect)
    programme.triage_feedback(doc_gap)

    declined = validate_success(
        api.decide_feedback_roadmap(
            doc_gap["id"], f.roadmap_decision_payload(decision="DECLINE"), DEV_REL_MANAGER
        )
    )

    assert_fields(declined, "FeedbackItem", state="DECLINED", raw_impact=20.00)
    assert_nulls(declined, ["priority_score"], "FeedbackItem")
    assert_fields(programme.read_product(product_id), "ApiProduct", demand_index=65.00)
    assert_fields(
        programme.read_feedback(defect["id"]),
        "FeedbackItem",
        raw_impact=65.00,
        priority_score=73.45,
    )


def test_a_product_with_no_feedback_reads_an_empty_roadmap_at_a_zero_demand_index(
    api, programme
):
    """A newly declared product ranks nothing and carries a demand index of exactly 0.00,
    with the default page window reported in the list meta.

    PRD: "At creation both allocated counters sit at 0, so `available_sustained_rpm` and `available_monthly_calls` equal the declared pools, and `demand_index` starts at 0.00."

    Design: Difficulty/boundary_precision_check/empty_roadmap_returns_zero_demand_index
    """
    product = programme.create_product()

    ranked, meta = validate_paginated(api.get_product_roadmap(product["id"], DEV_REL_MANAGER))

    assert ranked == [], f"expected an empty roadmap, got {ranked}"
    assert meta["total_count"] == 0, f"expected total_count 0, got {meta['total_count']}"
    assert meta["has_more"] is False, f"expected has_more False, got {meta['has_more']!r}"
    assert meta["limit"] == 10, f"expected the default limit of 10, got {meta['limit']}"
    assert meta["offset"] == 0, f"expected the default offset of 0, got {meta['offset']}"
    assert_fields(programme.read_product(product["id"]), "ApiProduct", demand_index=0.00)


def test_a_submitted_item_is_not_yet_ranked_and_does_not_move_the_index(api, programme):
    """An item still awaiting triage carries no scores of its own, stays out of the roadmap
    ranking, and leaves the product's demand index at 0.00.

    PRD: "Items in `SUBMITTED` are not yet scored and do not count; items in `DECLINED` have been removed from the index and do not count."

    Design: Difficulty/boundary_precision_check/empty_roadmap_returns_zero_demand_index
    """
    product = programme.create_product()
    developer = programme.onboarded_developer()
    submitted = programme.submit_feedback(developer, product["id"], category="DEFECT")

    item = validate_success(api.get_feedback_item(submitted["id"], PLATFORM_ADMIN))
    assert_fields(item, "FeedbackItem", state="SUBMITTED")
    assert_nulls(
        item,
        ["author_top_tier", "raw_impact", "priority_score", "triaged_by_user_id", "triaged_at"],
        "FeedbackItem",
    )

    ranked, meta = validate_paginated(api.get_product_roadmap(product["id"], PLATFORM_ADMIN))

    assert ranked == [], f"an untriaged item must not be ranked, got {ranked}"
    assert meta["total_count"] == 0, f"expected total_count 0, got {meta['total_count']}"
    assert meta["has_more"] is False, f"expected has_more False, got {meta['has_more']!r}"
    assert_fields(programme.read_product(product["id"]), "ApiProduct", demand_index=0.00)


def test_feedback_naming_an_unknown_product_is_refused_before_anything_is_recorded(
    api, programme
):
    """A developer aiming feedback at a product identifier that resolves to nothing is
    refused, and no item is recorded anywhere in the ledger.

    PRD: "Every foreign-key identifier supplied in the request body resolves to an existing resource, checked in the order the fields are declared for that endpoint, yielding whichever of `ERR_DEVELOPER_NOT_FOUND`, `ERR_API_PRODUCT_NOT_FOUND`, `ERR_API_VERSION_NOT_FOUND`, `ERR_ACCESS_APPLICATION_NOT_FOUND` or `ERR_USAGE_WINDOW_NOT_FOUND` applies — HTTP 404."

    Design: Corner/entities/feedback_item_body_fk_must_resolve
    """
    product = programme.create_product()
    developer = programme.onboarded_developer()

    validate_error(
        api.create_feedback_item(
            f.feedback_item_payload(developer["id"], UNKNOWN_ID),
            programme.headers_for(developer),
        ),
        ApiError.API_PRODUCT_NOT_FOUND,
    )

    _, meta = validate_paginated(api.list_feedback_items(DEV_REL_MANAGER))
    assert meta["total_count"] == 0, f"expected no recorded feedback, got {meta['total_count']}"
    assert_fields(programme.read_product(product["id"]), "ApiProduct", demand_index=0.00)


def test_a_feedback_item_scores_half_up_at_the_second_decimal(api, programme):
    """An ASSOCIATE-certified developer holding no entitlement scores a friction report at
    6.25, and the shared factor of 1.0125 rounds its priority up from 6.328125 to 6.33.

    PRD: "The certification bonus, read from the author's *current* `certification_level`, is **0** at `NONE`, **2.50** at `ASSOCIATE` and **5.00** at `PROFESSIONAL`."

    Design: Corner/calculations/feedback_scores_round_half_up_at_two_decimals
    """
    product = programme.create_product()
    associate = programme.onboarded_developer()
    programme.certify(associate, certification_level="ASSOCIATE")
    item = programme.submit_feedback(
        associate,
        product["id"],
        category="DX_FRICTION",
        body="The pagination defaults are surprising when the page is exactly full.",
    )

    triaged = validate_success(
        api.triage_feedback_item(item["id"], f.triage_payload(), DEV_REL_MANAGER)
    )

    # 15 x 0.25 + 2.50 = 6.25; factor 1.0125; 6.25 x 1.0125 = 6.328125 -> 6.33.
    assert_fields(
        triaged,
        "FeedbackItem",
        state="TRIAGED",
        author_top_tier="NONE",
        raw_impact=6.25,
        priority_score=6.33,
    )
    assert_fields(programme.read_product(product["id"]), "ApiProduct", demand_index=6.25)


def test_the_shared_factor_rounds_each_counted_item_up_on_its_own_exact_half(
    api, programme
):
    """With the index at 16.25 the factor 1.0325 lands the defect on an exact half at
    10.325 and the friction report on 6.453125, so the pair reads 10.33 and 6.45.

    PRD: "Each counted item's `priority_score` is its own `raw_impact` multiplied by that shared factor, rounded to 2 decimal places."

    Design: Corner/calculations/feedback_scores_round_half_up_at_two_decimals
    """
    product = programme.create_product()
    associate = programme.onboarded_developer()
    programme.certify(associate, certification_level="ASSOCIATE")
    friction = programme.submit_feedback(
        associate,
        product["id"],
        category="DX_FRICTION",
        body="The pagination defaults are surprising when the page is exactly full.",
    )
    programme.triage_feedback(friction)
    uncertified = programme.onboarded_developer()
    defect = programme.submit_feedback(uncertified, product["id"], category="DEFECT")

    triaged_defect = validate_success(
        api.triage_feedback_item(defect["id"], f.triage_payload(), DEV_REL_MANAGER)
    )

    # 40 x 0.25 + 0 = 10.00; index 16.25; factor 1.0325; 10.00 x 1.0325 = 10.325 -> 10.33.
    assert_fields(
        triaged_defect,
        "FeedbackItem",
        author_top_tier="NONE",
        raw_impact=10.00,
        priority_score=10.33,
    )
    assert_fields(programme.read_product(product["id"]), "ApiProduct", demand_index=16.25)
    assert_fields(
        programme.read_feedback(friction["id"]),
        "FeedbackItem",
        raw_impact=6.25,
        priority_score=6.45,
    )


def test_feedback_creation_resolves_its_author_before_its_product(api, programme):
    """When neither identifier in the body resolves, the author named first in the payload
    is the one the caller hears about.

    PRD: "A developer submits an item naming `developer_id`, the `api_product_id` the feedback targets, a `category` of `DEFECT`, `MISSING_FEATURE`, `DX_FRICTION` or `DOC_GAP`, and a `body` of between 10 and 2,000 characters."

    Design: Corner/endpoints/feedback_creation_links_two_existing_entities
    """
    programme.create_product()
    caller = programme.onboarded_developer()

    validate_error(
        api.create_feedback_item(
            f.feedback_item_payload(UNKNOWN_ID, UNKNOWN_ID),
            programme.headers_for(caller),
        ),
        ApiError.DEVELOPER_NOT_FOUND,
    )


def test_feedback_linking_an_existing_author_to_an_existing_product_is_recorded_unscored(
    api, programme
):
    """A submission naming a real developer and a real product is accepted as an unscored
    item that both list filters can find and that the roadmap does not yet rank.

    PRD: "The item starts in `state` `SUBMITTED` with `author_top_tier`, `raw_impact`, `priority_score`, `triaged_by_user_id`, `decision_note` and `triaged_at` all null."

    Design: Corner/endpoints/feedback_creation_links_two_existing_entities
    """
    product = programme.create_product()
    developer = programme.onboarded_developer()

    created = validate_success(
        api.create_feedback_item(
            f.feedback_item_payload(developer["id"], product["id"], category="MISSING_FEATURE"),
            programme.headers_for(developer),
        ),
        expected_status=201,
    )

    assert_fields(
        created,
        "FeedbackItem",
        developer_id=developer["id"],
        api_product_id=product["id"],
        category="MISSING_FEATURE",
        state="SUBMITTED",
    )
    assert_nulls(
        created,
        [
            "author_top_tier",
            "raw_impact",
            "priority_score",
            "triaged_by_user_id",
            "decision_note",
            "triaged_at",
        ],
        "FeedbackItem",
    )

    by_developer, developer_meta = validate_paginated(
        api.list_feedback_items(DEV_REL_MANAGER, params={"developer_id": developer["id"]})
    )
    assert_id_sequence(by_developer, [created["id"]])
    assert developer_meta["total_count"] == 1, (
        f"expected one item for the author, got {developer_meta['total_count']}"
    )

    by_product, product_meta = validate_paginated(
        api.list_feedback_items(DEV_REL_MANAGER, params={"api_product_id": product["id"]})
    )
    assert_id_sequence(by_product, [created["id"]])
    assert product_meta["total_count"] == 1, (
        f"expected one item for the product, got {product_meta['total_count']}"
    )

    _, roadmap_meta = validate_paginated(
        api.get_product_roadmap(product["id"], DEV_REL_MANAGER)
    )
    assert roadmap_meta["total_count"] == 0, (
        f"an unscored item must not be ranked, got {roadmap_meta['total_count']}"
    )


def _six_ranked_items(programme, product_id, developer):
    """Six items created a minute apart so their creation order is strictly ascending."""
    recipe = (
        ("DEFECT", "The catalogue read drops the final page of results."),
        ("MISSING_FEATURE", "A webhook for entitlement activation would remove polling."),
        ("DX_FRICTION", "The error envelope repeats the identifier in two shapes."),
        ("DX_FRICTION", "The sandbox seed data is hard to reset between runs."),
        ("DOC_GAP", "The throttling thresholds are not documented anywhere."),
        ("DEFECT", "The roadmap read ignores an offset beyond the last page."),
    )
    items = []
    for minute, (category, body) in enumerate(recipe):
        if minute:
            programme.set_clock(f"2026-08-01T00:{minute:02d}:00Z")
        items.append(
            programme.submit_feedback(developer, product_id, category=category, body=body)
        )
    return items


def test_the_roadmap_ranks_on_priority_then_impact_then_creation_order(api, programme):
    """Four counted items rank by priority score, and the two that tie at 3.93 on both
    score and impact are separated by which was submitted first; the declined and the
    untriaged items are absent altogether.

    PRD: "The product's roadmap read returns the product's `TRIAGED` and `ROADMAP_ACCEPTED` items ordered by `priority_score` descending, then `raw_impact` descending, then `created_at` ascending, and is available to a `DevRelManager` or a `PlatformAdmin`."

    Design: Corner/endpoints/roadmap_read_ranks_by_score_then_impact_then_creation
    """
    product = programme.create_product()
    developer = programme.onboarded_developer()
    defect, feature, friction, sandbox, doc_gap, untriaged = _six_ranked_items(
        programme, product["id"], developer
    )
    for item in (defect, feature, friction, sandbox, doc_gap):
        programme.triage_feedback(item)
    programme.decide_roadmap(doc_gap, decision="DECLINE")
    programme.decide_roadmap(defect, decision="ACCEPT")

    # Index 26.25 - 2.50 = 23.75; factor 1.0475; 10.00, 6.25, 3.75, 3.75 x 1.0475.
    assert_fields(programme.read_product(product["id"]), "ApiProduct", demand_index=23.75)

    ranked, meta = validate_paginated(api.get_product_roadmap(product["id"], DEV_REL_MANAGER))

    assert_id_sequence(ranked, [defect["id"], feature["id"], friction["id"], sandbox["id"]])
    assert meta["total_count"] == 4, f"expected four counted items, got {meta['total_count']}"
    assert meta["has_more"] is False, f"expected has_more False, got {meta['has_more']!r}"
    assert_fields(ranked[0], "FeedbackItem", state="ROADMAP_ACCEPTED", raw_impact=10.00,
                  priority_score=10.48)
    assert_fields(ranked[1], "FeedbackItem", state="TRIAGED", raw_impact=6.25,
                  priority_score=6.55)
    assert_fields(ranked[2], "FeedbackItem", state="TRIAGED", raw_impact=3.75,
                  priority_score=3.93)
    assert_fields(ranked[3], "FeedbackItem", state="TRIAGED", raw_impact=3.75,
                  priority_score=3.93)
    assert untriaged["id"] not in [i["id"] for i in ranked], (
        "an untriaged item must not appear in the ranking"
    )
    assert doc_gap["id"] not in [i["id"] for i in ranked], (
        "a declined item must not appear in the ranking"
    )


def test_the_roadmap_ranking_pages_without_losing_its_order(api, programme):
    """Asking for the third and fourth places of the ranking returns exactly the tied pair,
    still in creation order, and reports the whole counted set in the meta.

    PRD: "It is a computed read: it recomputes the ranking from current data rather than returning a stored ordering, and it accepts `limit` and `offset` like any other list."

    Design: Corner/endpoints/roadmap_read_ranks_by_score_then_impact_then_creation
    """
    product = programme.create_product()
    developer = programme.onboarded_developer()
    defect, feature, friction, sandbox, doc_gap, _untriaged = _six_ranked_items(
        programme, product["id"], developer
    )
    for item in (defect, feature, friction, sandbox, doc_gap):
        programme.triage_feedback(item)
    programme.decide_roadmap(doc_gap, decision="DECLINE")
    programme.decide_roadmap(defect, decision="ACCEPT")

    page, meta = validate_paginated(
        api.get_product_roadmap(product["id"], PLATFORM_ADMIN, params={"limit": 2, "offset": 2})
    )

    assert_id_sequence(page, [friction["id"], sandbox["id"]])
    assert meta["limit"] == 2, f"expected limit 2, got {meta['limit']}"
    assert meta["offset"] == 2, f"expected offset 2, got {meta['offset']}"
    assert meta["total_count"] == 4, f"expected total_count 4, got {meta['total_count']}"
    assert meta["has_more"] is False, f"expected has_more False, got {meta['has_more']!r}"


def test_a_roadmap_decision_before_triage_is_refused(api, programme):
    """An item that has never been triaged cannot be accepted onto the roadmap, and the
    refusal leaves both the item and its product's index exactly as they were.

    PRD: "A `DevRelManager` submits a `decision` of `ACCEPT` or `DECLINE` with an optional `decision_note`; the item must be in `TRIAGED`, otherwise `ERR_FEEDBACK_STATE_INVALID`."

    Design: Corner/errors/feedback_actions_require_their_own_state
    """
    product = programme.create_product()
    developer = programme.onboarded_developer()
    item = programme.submit_feedback(developer, product["id"], category="DEFECT")

    validate_error(
        api.decide_feedback_roadmap(
            item["id"], f.roadmap_decision_payload(decision="ACCEPT"), DEV_REL_MANAGER
        ),
        ApiError.FEEDBACK_STATE_INVALID,
    )

    unchanged = programme.read_feedback(item["id"])
    assert_fields(unchanged, "FeedbackItem", state="SUBMITTED")
    assert_nulls(unchanged, ["raw_impact", "priority_score", "triaged_at"], "FeedbackItem")
    assert_fields(programme.read_product(product["id"]), "ApiProduct", demand_index=0.00)


def test_an_item_cannot_be_triaged_a_second_time(api, programme):
    """Triage scores the item once; a repeat attempt is refused and the product's index is
    not double-counted.

    PRD: "The item must be in `SUBMITTED`, otherwise `ERR_FEEDBACK_STATE_INVALID` (HTTP 409)."

    Design: Corner/errors/feedback_actions_require_their_own_state
    """
    product = programme.create_product()
    developer = programme.onboarded_developer()
    item = programme.submit_feedback(developer, product["id"], category="DEFECT")

    triaged = validate_success(
        api.triage_feedback_item(item["id"], f.triage_payload(), DEV_REL_MANAGER)
    )
    # 40 x 0.25 = 10.00; factor 1.02; 10.00 x 1.02 = 10.20.
    assert_fields(
        triaged, "FeedbackItem", state="TRIAGED", raw_impact=10.00, priority_score=10.20
    )

    validate_error(
        api.triage_feedback_item(item["id"], f.triage_payload(), DEV_REL_MANAGER),
        ApiError.FEEDBACK_STATE_INVALID,
    )

    assert_fields(programme.read_product(product["id"]), "ApiProduct", demand_index=10.00)
    assert_fields(
        programme.read_feedback(item["id"]),
        "FeedbackItem",
        state="TRIAGED",
        raw_impact=10.00,
        priority_score=10.20,
    )
