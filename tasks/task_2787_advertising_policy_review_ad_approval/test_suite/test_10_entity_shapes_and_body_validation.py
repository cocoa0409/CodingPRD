"""What the server itself writes into a row, and what it refuses to write at all.

These cases stay close to the entity declarations: the fields a creation seeds without
being asked to, the defaults a minimal request materialises, the denormalised counters
that only the server may move, the two record types that carry no revision fields, and
the refusals that a malformed or unresolvable body earns before any business rule runs.
"""

import pytest

from test_helpers import (
    ADMIN,
    NON_EXISTENT_UUID,
    ApiErrorId,
    api_client,
    assert_append_only_identity,
    assert_fresh_creative_baseline,
    assert_instant_equals,
    factories,
    fixtures,
    make_advertiser_headers,
    validate_error,
    validate_paginated,
    validate_success,
)

FIN_CREDIT = "FIN_CREDIT"
SPIRITS = "ALC_SPIRITS"
HATE_SPEECH = "HATE_SPEECH"


def _fin_credit_rule():
    """A REGULATED rule so that `declared_category_codes` resolves."""
    return fixtures.create_policy_rule(
        FIN_CREDIT,
        "REGULATED",
        4.00,
        title="Consumer credit offers",
        confidence_auto_disapprove_threshold=0.90,
        confidence_manual_threshold=0.55,
        review_sla_hours=48,
        default_queue="STANDARD",
    )


def _beacon_advertiser(legal_name="Beacon Lending Co"):
    """An advertiser with no verifications and no enforcement history."""
    return fixtures.create_advertiser(
        legal_name=legal_name,
        country_code="US",
        industry_code="CONSUMER_FINANCE",
    )


def test_a_freshly_authored_creative_is_born_on_both_axes_with_server_seeded_fields():
    """PRD §3.3: "A creative is born with `review_status` `DRAFT` and
    `destination_status` `NOT_CHECKED`, with both `risk_score_provisional` and
    `risk_score_final` at 0.00, `limited_country_codes` empty,
    `approved_under_certification_id` null, `screening_run_count` at 0,
    `serving_eligible` false and `blocking_reason_codes` exactly
    `[REVIEW_NOT_APPROVED, DESTINATION_NOT_CLEARED]`."

    PRD §2.11: "A freshly created creative therefore reports `serving_eligible` false
    with `blocking_reason_codes` exactly `[REVIEW_NOT_APPROVED,
    DESTINATION_NOT_CLEARED]`, since it is neither approved nor destination-cleared but
    its account is in good standing and it is not political."

    PRD §2.4: "A `version` integer starts at 1 on creation and increments by exactly 1
    on every mutation of that row."

    PRD §4: "Operations that bring a new resource into existence — a policy rule, a
    country variation, an advertiser, an enforcement action, a reviewer, a creative, a
    screening run, a destination check, a certification or an appeal — return `201
    Created`."

    Design: Corner/From Table 1 (Entities)/entity_creation_ad_creative_returns_201_with_both_state_axes_at_their_initial_values
    """
    _fin_credit_rule()
    advertiser_id = _beacon_advertiser()["id"]

    created = validate_success(
        api_client.create_ad_creative(
            factories.create_ad_creative_payload(
                advertiser_id,
                [FIN_CREDIT],
                ["US"],
                headline="Refinance in ten minutes",
                body_text=(
                    "Refinance your card balance in ten minutes with a fixed rate."
                ),
                landing_page_url="https://www.beaconlending.example/refi",
                display_url="https://www.beaconlending.example/refi",
            ),
            make_advertiser_headers(advertiser_id),
        ),
        201,
    )

    assert_fresh_creative_baseline(created)
    # Neither optional field was supplied, so both take their declared defaults.
    assert created["political_flag"] is False
    assert created["disclaimer_text"] is None

    # Nothing is recomputed at read time, so the read repeats the creation response.
    fetched = fixtures.read_creative(created["id"], advertiser_id=advertiser_id)
    assert fetched == created


def test_a_licence_bracketing_the_clock_is_stored_active_and_read_back_unchanged():
    """PRD §3.5: "A certification is born with `status` `SUBMITTED` and a null
    `revocation_reason`, except that when the logical clock is already at or after
    `valid_from` and strictly before `valid_until` it is born `ACTIVE` outright."

    PRD §3.5: "Either the advertiser itself or a `PolicyAdmin` may submit one, naming
    the `advertiser_id` that holds it, the `policy_rule_id` it certifies against, the
    `license_number` issued by the authority (1 to 60 characters), the
    `issuing_country_code` of the authority (exactly two uppercase letters), and the
    half-open validity interval `valid_from` to `valid_until`."

    Design: Corner/From Table 1 (Entities)/entity_retrieval_get_certification_returns_the_stored_interval_and_its_activation_status
    """
    rule = fixtures.create_policy_rule(
        SPIRITS,
        "RESTRICTED",
        6.00,
        title="Alcohol - spirits",
        requires_certification=True,
        requires_disclaimer=True,
        confidence_auto_disapprove_threshold=0.90,
        confidence_manual_threshold=0.55,
        review_sla_hours=48,
        default_queue="REGULATED_CERT",
    )
    advertiser = fixtures.create_advertiser(
        legal_name="Northline Spirits LLC",
        country_code="US",
        industry_code="ALCOHOL_RETAIL",
    )
    advertiser_id = advertiser["id"]

    created = validate_success(
        api_client.create_certification(
            factories.create_certification_payload(
                advertiser_id,
                rule["id"],
                "2026-07-01T00:00:00Z",
                "2026-12-01T00:00:00Z",
                "US",
                license_number="TTB-NL-2026-441",
            ),
            make_advertiser_headers(advertiser_id),
        ),
        201,
    )

    stored = validate_success(
        api_client.get_certification(
            created["id"], make_advertiser_headers(advertiser_id)
        ),
        200,
    )
    # 2026-07-01 <= 2026-08-01 (the logical clock) < 2026-12-01.
    assert stored["status"] == "ACTIVE"
    assert stored["advertiser_id"] == advertiser_id
    assert stored["policy_rule_id"] == rule["id"]
    assert stored["license_number"] == "TTB-NL-2026-441"
    assert stored["issuing_country_code"] == "US"
    assert_instant_equals(stored["valid_from"], "2026-07-01T00:00:00Z", "valid_from")
    assert_instant_equals(stored["valid_until"], "2026-12-01T00:00:00Z", "valid_until")
    assert stored["revocation_reason"] is None
    assert stored["version"] == 1


def test_the_creative_listing_windows_the_filtered_set_and_defaults_to_a_limit_of_ten():
    """PRD §2.3: "The `limit` parameter caps the number of items returned; it defaults
    to 10 when omitted, may not be smaller than 1, and may not be larger than 100."

    PRD §2.3: "Unless a specific list operation declares a different ordering in the §4
    table, list results are sorted by `created_at` ascending."

    PRD §2.3: "Every list response repeats four pagination fields inside the envelope's
    `meta` object: `limit`, `offset`, `total_count` and `has_more`."

    Design: Corner/From Table 1 (Entities)/entity_listing_ad_creatives_paginates_by_created_at_with_total_count_and_has_more
    """
    _fin_credit_rule()
    advertiser_id = _beacon_advertiser()["id"]
    rival_id = _beacon_advertiser("Rival Lending Co")["id"]

    ordered = [
        fixtures.create_creative(
            advertiser_id,
            [FIN_CREDIT],
            ["US"],
            headline=f"Offer {word}",
            body_text=f"Refinance offer number {word} for existing customers.",
            landing_page_url=f"https://www.beaconlending.example/{word}",
            display_url=f"https://www.beaconlending.example/{word}",
        )["id"]
        for word in ("one", "two", "three")
    ]
    rival_creative_id = fixtures.create_creative(
        rival_id,
        [FIN_CREDIT],
        ["US"],
        headline="Rival offer",
        body_text="A rival refinance offer that must be filtered out.",
        landing_page_url="https://www.rivallending.example/one",
        display_url="https://www.rivallending.example/one",
    )["id"]

    page_one, meta_one = validate_paginated(
        api_client.list_ad_creatives(
            ADMIN, {"advertiser_id": advertiser_id, "limit": 2, "offset": 0}
        )
    )
    assert [row["id"] for row in page_one] == ordered[:2]
    assert meta_one["total_count"] == 3
    assert meta_one["has_more"] is True
    assert meta_one["limit"] == 2
    assert meta_one["offset"] == 0

    page_two, meta_two = validate_paginated(
        api_client.list_ad_creatives(
            ADMIN, {"advertiser_id": advertiser_id, "limit": 2, "offset": 2}
        )
    )
    assert [row["id"] for row in page_two] == ordered[2:]
    assert meta_two["total_count"] == 3
    assert meta_two["has_more"] is False

    unpaginated, meta_all = validate_paginated(
        api_client.list_ad_creatives(ADMIN, {"advertiser_id": advertiser_id})
    )
    assert [row["id"] for row in unpaginated] == ordered
    assert meta_all["limit"] == 10
    assert meta_all["offset"] == 0
    assert meta_all["has_more"] is False

    # The window is computed against the filtered set, not the whole table.
    for rows in (page_one, page_two, unpaginated):
        assert rival_creative_id not in [row["id"] for row in rows]


def test_a_creative_without_declared_categories_is_a_body_shape_refusal():
    """PRD §2.10: "Request-body shape: valid JSON, no unknown fields, every required
    field present, and every value satisfying its declared type, enum membership, string
    length, decimal precision, non-empty-array and no-duplicate-element constraints, and
    the `https://` prefix requirement on URL fields — `ERR_INVALID_REQUEST`."

    PRD §3.3: "An `Advertiser` authors a creative by supplying its own `advertiser_id`,
    the `headline` of 1 to 200 characters and the `body_text` of 1 to 2000 characters
    that the classifier will screen, the non-empty `declared_category_codes` array naming
    the policy codes it self-declares, the non-empty `target_country_codes` array of
    distinct two-letter uppercase country codes it intends to serve in, the
    `landing_page_url` a click resolves to, and the `display_url` shown in the ad — both
    URLs must begin with the literal text `https://` and must contain a host segment."

    Design: Corner/From Table 1 (Entities)/ad_creative_create_missing_required_declared_category_codes_returns_invalid_request
    """
    _fin_credit_rule()
    advertiser_id = _beacon_advertiser()["id"]
    headers = make_advertiser_headers(advertiser_id)

    omitted = factories.create_ad_creative_payload(
        advertiser_id,
        [FIN_CREDIT],
        ["US"],
        headline="No categories",
        body_text="This request omits declared_category_codes entirely.",
        landing_page_url="https://www.beaconlending.example/x",
        display_url="https://www.beaconlending.example/x",
    )
    del omitted["declared_category_codes"]
    validate_error(
        api_client.create_ad_creative(omitted, headers),
        ApiErrorId.ERR_INVALID_REQUEST,
        400,
    )

    # An empty array is just as illegal as an absent one: the constraint is non-empty.
    validate_error(
        api_client.create_ad_creative(
            factories.create_ad_creative_payload(
                advertiser_id,
                [],
                ["US"],
                headline="Empty categories",
                body_text="This request supplies an empty declared_category_codes array.",
                landing_page_url="https://www.beaconlending.example/y",
                display_url="https://www.beaconlending.example/y",
            ),
            headers,
        ),
        ApiErrorId.ERR_INVALID_REQUEST,
        400,
    )

    _rows, meta = validate_paginated(
        api_client.list_ad_creatives(ADMIN, {"advertiser_id": advertiser_id})
    )
    assert meta["total_count"] == 0, "a refused request performs no side effect"


def test_a_rule_created_from_four_fields_alone_materialises_every_declared_default():
    """PRD §3.1: "Two booleans state what an approval demands:
    `requires_certification`, which when true means an approval of a matched creative
    must be backed by a covering licence, and `requires_disclaimer`, which when true
    means an approval demands non-empty disclosure text on the creative. Both default to
    false."

    PRD §3.1: "`confidence_auto_disapprove_threshold` is the classifier confidence at or
    above which a match is treated as an automatic disapproval; it defaults to 0.90."

    PRD §3.1: "`confidence_manual_threshold` is the confidence at or above which a match
    instead routes to a human; it defaults to 0.55."

    PRD §3.1: "`review_sla_hours`, an integer from 1 to 336 defaulting to 48, is how
    many hours a routed task on this rule gets before its deadline."

    PRD §3.1: "`default_queue`, one of `STANDARD`, `REGULATED_CERT` or `POLITICAL` and
    defaulting to `STANDARD`, names the queue a routed task lands in when this rule is
    the primary finding."

    PRD §3.1: "A newly registered rule begins with `country_override_count` at 0."

    Design: Corner/From Table 1 (Entities)/policy_rule_defaults_are_applied_when_every_optional_input_is_omitted
    """
    created = validate_success(
        api_client.create_policy_rule(
            {
                "code": "SUP_HEALTH",
                "title": "Health supplements",
                "category_class": "REGULATED",
                "base_severity_weight": 3.00,
            },
            ADMIN,
        ),
        201,
    )

    stored = fixtures.read_policy_rule(created["id"])
    assert stored["requires_certification"] is False
    assert stored["requires_disclaimer"] is False
    assert stored["confidence_auto_disapprove_threshold"] == pytest.approx(
        0.90, abs=0.01
    )
    assert stored["confidence_manual_threshold"] == pytest.approx(0.55, abs=0.01)
    assert stored["review_sla_hours"] == 48
    assert stored["default_queue"] == "STANDARD"
    assert stored["country_override_count"] == 0
    assert stored["version"] == 1
    assert stored["base_severity_weight"] == pytest.approx(3.00, abs=0.01)


def test_each_country_variation_bumps_the_counter_and_the_rules_own_version():
    """PRD §3.1: "Attaching a variation increments the parent rule's
    `country_override_count` by 1 and advances the rule's `version` by 1."

    PRD §2.9: "A policy rule's `country_override_count` tracks the number of country
    variations attached to it and starts at 0."

    PRD §3.1: "`requires_license`, defaulting to false, means that in this country an
    approval demands a certification whose `issuing_country_code` equals this
    `country_code`."

    PRD §3.1: "`requires_disclaimer`, defaulting to false, means approval in this
    country demands non-empty disclosure text."

    Design: Corner/From Table 1 (Entities)/computed_field_country_override_count_tracks_override_inserts_and_bumps_the_rule_version
    """
    rule = fixtures.create_policy_rule(
        SPIRITS,
        "RESTRICTED",
        6.00,
        title="Alcohol - spirits",
        requires_certification=True,
        requires_disclaimer=True,
        confidence_auto_disapprove_threshold=0.90,
        confidence_manual_threshold=0.55,
        review_sla_hours=48,
        default_queue="REGULATED_CERT",
    )
    assert rule["version"] == 1
    assert rule["country_override_count"] == 0

    us_override = validate_success(
        api_client.create_country_override(
            rule["id"],
            factories.create_country_override_payload(
                "US",
                "RESTRICTED_CERT_REQUIRED",
                requires_license=True,
                requires_disclaimer=True,
                severity_multiplier=1.50,
            ),
            ADMIN,
        ),
        201,
    )
    after_first = fixtures.read_policy_rule(rule["id"])
    assert after_first["country_override_count"] == 1
    assert after_first["version"] == 2

    se_override = fixtures.add_country_override(
        rule["id"], "SE", "BLOCKED", severity_multiplier=2.00
    )
    after_second = fixtures.read_policy_rule(rule["id"])
    assert after_second["country_override_count"] == 2
    assert after_second["version"] == 3

    assert us_override["severity_multiplier"] == pytest.approx(1.50, abs=0.01)
    assert us_override["requires_license"] is True
    # The variation row is its own resource and was never mutated after insertion.
    assert us_override["version"] == 1
    assert se_override["requires_license"] is False
    assert se_override["requires_disclaimer"] is False

    _rows, meta = validate_paginated(
        api_client.list_country_overrides(rule["id"], ADMIN)
    )
    assert meta["total_count"] == 2


def test_the_revision_loop_hands_the_second_run_the_next_sequence_index():
    """PRD §3.4: "An accepted run records `ad_creative_id`, takes `sequence_index` as
    one greater than the highest index already used on that creative — so indices are
    contiguous from 1 and the greatest index is always the latest run — and snapshots the
    creative's `version` at acceptance into `creative_version_at_run`."

    PRD §3.4: "The run itself records `decision_count` as the number of decision rows it
    created, `max_confidence` as the highest `confidence` among them (0.00 when the run
    carried no decisions), `provisional_risk_score` as a snapshot of the creative's
    provisional risk score at run time, and `outcome`."

    PRD §3.3: "Revision resets the destination axis to `NOT_CHECKED`, resets both
    `risk_score_provisional` and `risk_score_final` to 0.00, resets
    `limited_country_codes` to the empty array and `approved_under_certification_id` to
    null, expires any queued review task standing on this creative, and increments the
    creative's `version` by 1."

    Design: Corner/From Table 1 (Entities)/system_fields_screening_run_sequence_index_is_contiguous_across_the_revision_loop
    """
    rule = fixtures.create_policy_rule(
        HATE_SPEECH,
        "PROHIBITED",
        12.00,
        title="Hateful content",
        confidence_auto_disapprove_threshold=0.90,
        confidence_manual_threshold=0.55,
        review_sla_hours=24,
        default_queue="STANDARD",
    )
    advertiser = fixtures.create_verified_advertiser(
        legal_name="Loud Media Group",
        country_code="US",
        industry_code="PUBLISHING",
    )
    advertiser_id = advertiser["id"]

    creative = fixtures.create_creative(
        advertiser_id,
        [HATE_SPEECH],
        ["US"],
        headline="Speak your mind",
        body_text="Speak your mind about the neighbours you cannot stand.",
        landing_page_url="https://www.loudmedia.example/speak",
        display_url="https://www.loudmedia.example/speak",
    )
    creative_id = creative["id"]

    first_submit = fixtures.submit_creative(creative_id, advertiser_id)
    version_at_first_run = first_submit["version"]
    run_one = fixtures.screen_creative(
        creative_id, [(rule["id"], 0.95)], version_at_first_run
    )
    assert run_one["sequence_index"] == 1
    assert run_one["creative_version_at_run"] == version_at_first_run
    assert run_one["outcome"] == "AUTO_DISAPPROVED"
    # No country variation exists, so the multiplier is the neutral 1.00.
    assert run_one["provisional_risk_score"] == pytest.approx(11.40, abs=0.01)

    fixtures.revise_creative(
        creative_id,
        advertiser_id,
        headline="Speak kindly",
        body_text="Speak kindly about the neighbours on your street.",
    )
    second_submit = fixtures.submit_creative(creative_id, advertiser_id)
    version_at_second_run = second_submit["version"]

    run_two = fixtures.screen_creative(
        creative_id, [(rule["id"], 0.30)], version_at_second_run
    )
    # The only route to index 2 is the revision loop, and the counter is per creative.
    assert run_two["sequence_index"] == 2
    assert run_two["creative_version_at_run"] == version_at_second_run
    assert version_at_second_run > version_at_first_run
    assert run_two["outcome"] == "AUTO_APPROVED"
    assert run_two["decision_count"] == 1
    assert run_two["max_confidence"] == pytest.approx(0.30, abs=0.01)
    assert run_two["provisional_risk_score"] == pytest.approx(0.00, abs=0.01)

    final = fixtures.read_creative(creative_id, advertiser_id=advertiser_id)
    assert final["screening_run_count"] == 2
    assert final["review_status"] == "AUTO_APPROVED"
    assert final["risk_score_provisional"] == pytest.approx(0.00, abs=0.01)

    rows, meta = validate_paginated(api_client.list_screening_runs(creative_id, ADMIN))
    assert meta["total_count"] == 2
    assert [row["sequence_index"] for row in rows] == [1, 2]


def test_an_illegal_enum_and_an_out_of_range_weight_are_both_body_refusals():
    """PRD §3.1: "Its `category_class` places it in one of the three framework tiers:
    `PROHIBITED` for content that may never run, `RESTRICTED` for content that may run
    only under review and licence, and `REGULATED` for content that is permitted but
    tracked."

    PRD §3.1: "The rule's `base_severity_weight`, a value between 0.01 and 20.00 carried
    to exactly 2 decimals, is the points weight the rule contributes before any country
    multiplier or reason factor is applied."

    PRD §2.10: "When one request breaks several rules, the server reports exactly one
    error — the one earliest in the following order — and performs no side effect
    whatsoever."

    Design: Corner/From Table 1 (Entities)/type_constraints_invalid_category_class_and_out_of_range_weight_return_invalid_request
    """
    validate_error(
        api_client.create_policy_rule(
            {
                "code": "GAM_CASINO",
                "title": "Casino gambling",
                "category_class": "BANNED",
                "base_severity_weight": 8.00,
            },
            ADMIN,
        ),
        ApiErrorId.ERR_INVALID_REQUEST,
        400,
    )

    validate_error(
        api_client.create_policy_rule(
            {
                "code": "GAM_CASINO",
                "title": "Casino gambling",
                "category_class": "RESTRICTED",
                "base_severity_weight": 25.00,
            },
            ADMIN,
        ),
        ApiErrorId.ERR_INVALID_REQUEST,
        400,
    )

    # Neither refusal consumed the code, so the legal request still succeeds.
    accepted = validate_success(
        api_client.create_policy_rule(
            {
                "code": "GAM_CASINO",
                "title": "Casino gambling",
                "category_class": "RESTRICTED",
                "base_severity_weight": 8.00,
                "confidence_auto_disapprove_threshold": 0.90,
                "confidence_manual_threshold": 0.55,
            },
            ADMIN,
        ),
        201,
    )
    assert accepted["category_class"] == "RESTRICTED"
    assert accepted["base_severity_weight"] == pytest.approx(8.00, abs=0.01)

    _rows, meta = validate_paginated(api_client.list_policy_rules(ADMIN))
    assert meta["total_count"] == 1


def test_a_screening_run_and_its_decision_carry_no_revision_fields_at_all():
    """PRD §2.4: "Five record types are append-only evidence rather than mutable state,
    and they carry only `id` and `created_at` — both `updated_at` and `version` are
    absent from them entirely: `ScreeningRun`, `ClassifierDecision`, `DestinationCheck`,
    `PoliticalArchiveEntry` and `ViolationLedgerEntry`."

    PRD §2.4: "Nothing in the system rewrites or deletes a row of any of these five
    types; corrections are expressed by writing a further row, which is why an appeal
    reversal is a new ledger entry rather than an edit of the original assessment."

    PRD §3.4: "Alongside the disposition each decision records
    `country_multiplier_applied`, which is the country multiplier of its rule for this
    creative as defined in §3.1, and `assessed_points`, which is the rule's
    `base_severity_weight` multiplied by that `country_multiplier_applied` and then
    multiplied by the decision's own `confidence`, with the product rounded half-up to 2
    decimals."

    Design: Corner/From Table 1 (Entities)/immutability_screening_run_and_classifier_decision_expose_no_version_and_no_update_endpoint
    """
    rule = _fin_credit_rule()
    advertiser = fixtures.create_verified_advertiser(
        legal_name="Beacon Lending Co",
        country_code="US",
        industry_code="CONSUMER_FINANCE",
    )
    _creative, run = fixtures.screened_creative(
        advertiser["id"],
        [FIN_CREDIT],
        [(rule["id"], 0.30)],
        ["US"],
        headline="Fixed rate refinance",
        body_text="A fixed rate refinance offer with no origination fee.",
        landing_page_url="https://www.beaconlending.example/fixed",
        display_url="https://www.beaconlending.example/fixed",
    )

    stored_run = validate_success(api_client.get_screening_run(run["id"], ADMIN), 200)
    assert_append_only_identity(stored_run)
    assert stored_run["decision_count"] == 1

    rows, meta = validate_paginated(
        api_client.list_run_classifier_decisions(run["id"], ADMIN)
    )
    assert meta["total_count"] == 1
    decision = rows[0]
    assert_append_only_identity(decision)
    assert decision["disposition"] == "BELOW_THRESHOLD"
    assert decision["country_multiplier_applied"] == pytest.approx(1.00, abs=0.01)
    # 4.00 * 1.00 * 0.30, recorded even though the row scores nothing.
    assert decision["assessed_points"] == pytest.approx(1.20, abs=0.01)


def test_a_variation_under_an_unknown_rule_fails_on_the_path_identifier():
    """PRD §2.5: "Where a path names more than one resource, identifiers are resolved
    strictly left to right and the request fails on the first identifier that resolves to
    nothing."

    PRD §2.5: "A request addressing the country variations of a policy rule that does
    not exist fails on the rule; a request addressing the screening runs of a creative
    that does not exist fails on the creative."

    PRD §2.5: "Each identifier position has its own dedicated not-found error, all of
    them HTTP 404: an unresolvable `advertiser_id` yields `ERR_ADVERTISER_NOT_FOUND`, an
    unresolvable `ad_creative_id` yields `ERR_AD_CREATIVE_NOT_FOUND`, an unresolvable
    `policy_rule_id` yields `ERR_POLICY_RULE_NOT_FOUND`"

    Design: Corner/From Table 1 (Entities)/parent_relationship_country_override_under_an_unknown_policy_rule_returns_policy_rule_not_found
    """
    real_rule = fixtures.create_policy_rule(
        SPIRITS,
        "RESTRICTED",
        6.00,
        title="Alcohol - spirits",
        requires_certification=True,
    )

    validate_error(
        api_client.create_country_override(
            NON_EXISTENT_UUID,
            factories.create_country_override_payload(
                "US", "BLOCKED", severity_multiplier=2.00
            ),
            ADMIN,
        ),
        ApiErrorId.ERR_POLICY_RULE_NOT_FOUND,
        404,
    )
    validate_error(
        api_client.list_country_overrides(NON_EXISTENT_UUID, ADMIN),
        ApiErrorId.ERR_POLICY_RULE_NOT_FOUND,
        404,
    )

    rows, meta = validate_paginated(
        api_client.list_country_overrides(real_rule["id"], ADMIN)
    )
    assert rows == []
    assert meta["total_count"] == 0
    # No row leaked onto the real rule from the rejected insert.
    assert fixtures.read_policy_rule(real_rule["id"])["country_override_count"] == 0


def test_unresolvable_body_foreign_keys_each_report_their_own_not_found():
    """PRD §2.5: "The same discipline applies to foreign keys arriving in a request
    body. A body-supplied `advertiser_id`, `policy_rule_id`, `prior_action_id`,
    `disapproval_notice_id` or `evidence_certification_id` must resolve, and every element
    of `declared_category_codes` must match the `code` of an existing policy rule — a miss
    there reports `ERR_POLICY_RULE_NOT_FOUND`."

    PRD §2.10: "Resolution of foreign keys supplied in the body, as described in §2.5."

    Design: Corner/From Table 1 (Entities)/flat_topology_ad_creative_body_fks_are_validated_and_unknown_ids_return_not_found
    """
    _fin_credit_rule()
    advertiser_id = _beacon_advertiser()["id"]

    validate_error(
        api_client.create_ad_creative(
            factories.create_ad_creative_payload(
                NON_EXISTENT_UUID,
                [FIN_CREDIT],
                ["US"],
                headline="Orphan creative",
                body_text="A creative whose advertiser_id does not resolve to any row.",
                landing_page_url="https://www.beaconlending.example/orphan",
                display_url="https://www.beaconlending.example/orphan",
            ),
            make_advertiser_headers(NON_EXISTENT_UUID),
        ),
        ApiErrorId.ERR_ADVERTISER_NOT_FOUND,
        404,
    )

    validate_error(
        api_client.create_ad_creative(
            factories.create_ad_creative_payload(
                advertiser_id,
                ["NOT_A_RULE"],
                ["US"],
                headline="Unknown category",
                body_text="A creative declaring a category code that no rule defines.",
                landing_page_url="https://www.beaconlending.example/unknown",
                display_url="https://www.beaconlending.example/unknown",
            ),
            make_advertiser_headers(advertiser_id),
        ),
        ApiErrorId.ERR_POLICY_RULE_NOT_FOUND,
        404,
    )

    _rows, meta = validate_paginated(api_client.list_ad_creatives(ADMIN))
    assert meta["total_count"] == 0, "neither rejected request wrote a row"
