"""Entity-level reading of the contract: the fields a creation must return, the
defaults the server supplies for what the client omitted, the mirrors it keeps
up to date, the two evidence rows it may never rewrite, and the rejections that
guard shape and reference before any business rule runs.
"""

from test_helpers import (
    ANONYMOUS,
    INVESTIGATOR,
    OFFICER,
    REVIEWER,
    UNKNOWN_ID_A,
    UNKNOWN_ID_B,
    ApiErrorId,
    assert_funds,
    assert_immutable_evidence_fields,
    assert_instant_equals,
    assert_meta,
    assert_points,
    assert_posture,
    assert_rate,
    assert_three_fraction_digits,
    evaluate,
    file_snapshot,
    is_valid_uuid,
    make_seller_headers,
    publish_rule,
    read_notices,
    read_seller,
    register_seller,
    seller_payload,
    set_clock,
    validate_error,
    validate_paginated,
    validate_success,
)

CLOCK = "2026-08-01T00:00:00.000Z"


# --------------------------------------------------------------------------
# Creation, retrieval and listing of the root entity
# --------------------------------------------------------------------------
def test_registration_returns_every_declared_field_at_its_declared_default(api):
    """PRD §3.1: "Otherwise a fresh seller starts empty and clean:
    `enforcement_state` `ACTIVE`, `disbursement_state` `NORMAL`, `ban_reason`
    null, `severity_points_balance` 0.00, `health_score` and `metric_tier` both
    null because no evaluation has yet run, `available_balance_cents`,
    `held_balance_cents`, `lifetime_credited_cents`, `lifetime_debited_cents`,
    `open_defect_claim_units`, and `reinstated_count` all zero."

    Design: Corner/entities/entity_seller_registration_returns_every_declared_field_with_defaults
    """
    set_clock(api, CLOCK)

    response = api.register_seller(
        seller_payload(
            legal_name="Harbor Tools LLC", email="ops@harbor-tools.example",
            tax_id_hash="TAX-HT-0001", payout_bank_token="BANK-HT-0001",
            address_fingerprint="ADDR-HT-0001", device_fingerprint="DEV-HT-0001",
        ),
        ANONYMOUS,
    )

    seller = validate_success(response, 201)
    assert is_valid_uuid(seller["id"]), f"id={seller['id']!r} is not a UUID"
    assert seller["legal_name"] == "Harbor Tools LLC"
    assert seller["email"] == "ops@harbor-tools.example"
    # §3.1: email_domain is derived by the server from email, never supplied.
    assert seller["email_domain"] == "harbor-tools.example"
    assert_posture(seller, enforcement_state="ACTIVE", disbursement_state="NORMAL",
                   severity_points_balance="0.00")
    # A seller who has never been evaluated is null, not a perfect 100.00 / HEALTHY.
    assert seller["health_score"] is None
    assert seller["metric_tier"] is None
    assert_funds(seller, available=0, held=0, credited=0, debited=0)
    assert seller["open_defect_claim_units"] == 0
    assert seller["reinstated_count"] == 0
    assert seller["ban_reason"] is None
    # No incumbent existed, so no link was minted and nothing was flagged.
    assert seller["registration_risk_flag"] is False
    assert seller["root_seller_id"] is None
    assert seller["version"] == 1
    assert_instant_equals(seller["created_at"], CLOCK, "created_at")

    links, links_meta = validate_paginated(api.list_related_account_links(OFFICER))
    assert links == [], f"an empty database minted a link anyway: {links}"
    assert_meta(links_meta, total_count=0, has_more=False)
    assert read_notices(api, seller["id"]) == []


def test_a_read_returns_the_stored_row_inside_the_success_envelope(api):
    """PRD §2.2: "The `data` field contains the resource object or an array of
    resource objects."

    PRD §2.2: "The `api_request_timestamp` is a server-generated ISO 8601 UTC
    timestamp with three fractional digits."

    Design: Corner/entities/entity_seller_retrieval_returns_the_stored_row_in_the_success_envelope
    """
    set_clock(api, CLOCK)
    seller = register_seller(
        api, legal_name="Harbor Tools LLC", email="ops@harbor-tools.example",
        tax_id_hash="TAX-HT-0001", payout_bank_token="BANK-HT-0001",
        address_fingerprint="ADDR-HT-0001",
    )

    response = api.get_seller(seller["id"], INVESTIGATOR)

    body = response.json()
    assert response.status_code == 200
    assert body["response_type"] == "object"
    assert body["meta"]["api_request_id"].startswith("req_"), body["meta"]
    assert_three_fraction_digits(body["meta"]["api_request_timestamp"],
                                "api_request_timestamp")

    stored = validate_success(response, 200)
    assert stored["id"] == seller["id"]
    assert stored["legal_name"] == "Harbor Tools LLC"
    assert_posture(stored, enforcement_state="ACTIVE", disbursement_state="NORMAL")
    # A read is not a mutation, so §2.4's per-mutation increment never runs.
    assert stored["version"] == 1


def _three_registered_sellers(api):
    """Three sellers with disjoint matching signals, so no registration mints a
    link and all three stay ACTIVE / NORMAL."""
    set_clock(api, CLOCK)
    first = register_seller(
        api, legal_name="Harbor Tools LLC", email="ops@harbor-tools.example",
        tax_id_hash="TAX-HT-0001", payout_bank_token="BANK-HT-0001",
        address_fingerprint="ADDR-HT-0001",
    )
    second = register_seller(
        api, legal_name="Ridgeline Supply LLC", email="ops@ridgeline-supply.example",
        tax_id_hash="TAX-RS-0002", payout_bank_token="BANK-RS-0002",
        address_fingerprint="ADDR-RS-0002",
    )
    third = register_seller(
        api, legal_name="Quarry Lane Goods LLC", email="ops@quarry-lane.example",
        tax_id_hash="TAX-QL-0003", payout_bank_token="BANK-QL-0003",
        address_fingerprint="ADDR-QL-0003",
    )
    return first, second, third


def test_the_seller_list_pages_the_collection_and_filters_narrow_the_count(api):
    """PRD §2.3: "Every list response carries `limit`, `offset`, `total_count`,
    and `has_more` inside the `meta` object of the envelope described in §2.2."

    Design: Corner/entities/entity_seller_list_returns_pagination_envelope_and_honours_state_filter
    """
    everyone = {seller["id"] for seller in _three_registered_sellers(api)}

    page_one, meta_one = validate_paginated(
        api.list_sellers(OFFICER, {"limit": 2, "offset": 0})
    )
    page_two, meta_two = validate_paginated(
        api.list_sellers(OFFICER, {"limit": 2, "offset": 2})
    )

    assert len(page_one) == 2, f"limit=2 returned {len(page_one)} rows"
    assert_meta(meta_one, total_count=3, has_more=True, limit=2, offset=0)
    assert len(page_two) == 1
    assert_meta(meta_two, total_count=3, has_more=False, limit=2, offset=2)
    # The two pages tile the collection exactly once: no row is repeated or lost.
    first_ids = [row["id"] for row in page_one]
    second_ids = [row["id"] for row in page_two]
    assert set(first_ids) | set(second_ids) == everyone
    assert set(first_ids).isdisjoint(second_ids)

    watchlisted, watch_meta = validate_paginated(
        api.list_sellers(OFFICER, {"enforcement_state": "WATCHLIST"})
    )
    active, active_meta = validate_paginated(
        api.list_sellers(OFFICER, {"enforcement_state": "ACTIVE", "limit": 100})
    )

    # The equality filter narrows total_count itself, not merely the page.
    assert watchlisted == []
    assert_meta(watch_meta, total_count=0, has_more=False)
    assert {row["id"] for row in active} == everyone
    assert_meta(active_meta, total_count=3, has_more=False, limit=100)


def test_an_unknown_seller_identifier_is_rejected_before_any_logic(api):
    """PRD §2.9: "Identifiers templated into a URL are resolved strictly left to
    right, and the first identifier that does not name a live row decides the
    rejection."

    Design: Corner/entities/entity_unknown_seller_id_returns_seller_not_found
    """
    set_clock(api, CLOCK)
    seller = register_seller(
        api, legal_name="Harbor Tools LLC", email="ops@harbor-tools.example",
        tax_id_hash="TAX-HT-0001", payout_bank_token="BANK-HT-0001",
        address_fingerprint="ADDR-HT-0001",
    )

    missing = api.get_seller(UNKNOWN_ID_A, INVESTIGATOR)
    sub_resource = api.list_seller_listings(UNKNOWN_ID_A, INVESTIGATOR)

    error = validate_error(missing, ApiErrorId.SELLER_NOT_FOUND.value)
    assert isinstance(error["message"], str) and error["message"].strip() != ""
    assert missing.json()["response_type"] == "error"
    # A sub-resource list on an unknown parent is a 404, never an empty 200 page.
    validate_error(sub_resource, ApiErrorId.SELLER_NOT_FOUND.value)
    assert read_seller(api, seller["id"])["version"] == 1


# --------------------------------------------------------------------------
# Required inputs, and the defaults the server supplies for the rest
# --------------------------------------------------------------------------
def test_omitting_a_required_input_field_persists_nothing(api):
    """PRD §2.8: "Request shape — required fields present, types correct, enum
    values in range, string lengths and numeric ranges within their declared
    bounds, datetimes ISO 8601 UTC with three fractional digits, and `limit`
    within 1 through 100; yielding `ERR_INVALID_REQUEST`."

    Design: Corner/entities/entity_missing_required_input_field_is_rejected
    """
    set_clock(api, CLOCK)
    seller = register_seller(
        api, legal_name="Harbor Tools LLC", email="ops@harbor-tools.example",
        tax_id_hash="TAX-HT-0001", payout_bank_token="BANK-HT-0001",
        address_fingerprint="ADDR-HT-0001",
    )

    # §3.2: a listing carries a sku of 1 to 40 characters; it is not optional.
    without_sku = api.create_listing(
        {"seller_id": seller["id"], "title": "Titanium Pry Bar 18in",
         "category_code": "TOOLS-HAND"},
        make_seller_headers(seller["id"]),
    )
    # §3.2: a rule is published with a base_severity_weight between 0.50 and 8.00.
    without_weight = api.create_policy_rule(
        {"code": "LA-REQ-1", "category": "LISTING_ACCURACY", "removal_scope": "ACCOUNT"},
        OFFICER,
    )

    validate_error(without_sku, ApiErrorId.INVALID_REQUEST.value)
    validate_error(without_weight, ApiErrorId.INVALID_REQUEST.value)

    listings, listings_meta = validate_paginated(
        api.list_seller_listings(seller["id"], INVESTIGATOR)
    )
    rules, rules_meta = validate_paginated(api.list_policy_rules(OFFICER))
    assert listings == [], f"the refused listing was persisted anyway: {listings}"
    assert_meta(listings_meta, total_count=0, has_more=False)
    assert rules == [], f"the refused rule was persisted anyway: {rules}"
    assert_meta(rules_meta, total_count=0, has_more=False)


def test_a_published_rule_defaults_its_plan_flag_and_derives_its_exemption(api):
    """PRD §3.2: "An optional `requires_poa` flag defaults to true and declares
    whether an appeal against an action citing this rule must be backed by an
    accepted plan of action. The server derives `decay_exempt` itself: it is true
    exactly when `category` is `INTELLECTUAL_PROPERTY` or `RESTRICTED_PRODUCT`,
    and false for the other three categories."

    Design: Corner/entities/entity_policy_rule_defaults_requires_poa_and_derives_decay_exempt
    """
    set_clock(api, CLOCK)

    accuracy = validate_success(
        api.create_policy_rule(
            {"code": "LA-DEF-1", "category": "LISTING_ACCURACY",
             "base_severity_weight": 2.00, "removal_scope": "ACCOUNT"},
            OFFICER,
        ),
        201,
    )
    infringement = validate_success(
        api.create_policy_rule(
            {"code": "IP-DEF-1", "category": "INTELLECTUAL_PROPERTY",
             "base_severity_weight": 3.00, "removal_scope": "LISTING",
             "requires_poa": False},
            OFFICER,
        ),
        201,
    )
    restricted = validate_success(
        api.create_policy_rule(
            {"code": "RP-DEF-1", "category": "RESTRICTED_PRODUCT",
             "base_severity_weight": 1.50, "removal_scope": "LISTING"},
            OFFICER,
        ),
        201,
    )
    shipping = validate_success(
        api.create_policy_rule(
            {"code": "SP-DEF-1", "category": "SHIPPING_PERFORMANCE",
             "base_severity_weight": 2.50, "removal_scope": "ACCOUNT"},
            OFFICER,
        ),
        201,
    )

    # The default is applied where the flag was omitted and honoured where it was not.
    assert accuracy["requires_poa"] is True
    assert restricted["requires_poa"] is True
    assert shipping["requires_poa"] is True
    assert infringement["requires_poa"] is False

    # decay_exempt is never an input: it follows the category alone.
    assert accuracy["decay_exempt"] is False
    assert shipping["decay_exempt"] is False
    assert infringement["decay_exempt"] is True
    assert restricted["decay_exempt"] is True

    assert_points(accuracy["base_severity_weight"], "2.00", "base_severity_weight")
    assert_points(restricted["base_severity_weight"], "1.50", "base_severity_weight")
    assert accuracy["version"] == 1


def test_the_optional_provenance_and_listing_flags_take_their_declared_defaults(api):
    """PRD §3.3: "An optional `source` field records the provenance of the
    counters as either `PLATFORM_PIPELINE` or `MANUAL_CORRECTION`, and defaults
    to `PLATFORM_PIPELINE`."

    PRD §3.2: "A new listing begins in state `ACTIVE` with
    `removal_policy_category` null and `suppressed_by_suspension` false."

    Design: Corner/entities/entity_optional_defaults_applied_on_snapshot_and_listing
    """
    set_clock(api, CLOCK)
    seller = register_seller(
        api, legal_name="Harbor Tools LLC", email="ops@harbor-tools.example",
        tax_id_hash="TAX-HT-0001", payout_bank_token="BANK-HT-0001",
        address_fingerprint="ADDR-HT-0001",
    )

    snapshot = validate_success(
        api.create_snapshot(
            {"seller_id": seller["id"],
             "window_start": "2026-07-01T00:00:00.000Z",
             "window_end": "2026-08-01T00:00:00.000Z",
             "order_volume": 500, "delivered_or_refunded_volume": 480,
             "defect_claims_pending": 3, "defect_claims_substantiated": 2,
             "late_shipments": 10, "pre_fulfillment_cancellations": 5,
             "shipments_total": 490, "shipments_with_valid_tracking": 485},
            OFFICER,
        ),
        201,
    )
    listing = validate_success(
        api.create_listing(
            {"seller_id": seller["id"], "sku": "HT-PRY-18",
             "title": "Titanium Pry Bar 18in", "category_code": "TOOLS-HAND"},
            make_seller_headers(seller["id"]),
        ),
        201,
    )

    assert snapshot["source"] == "PLATFORM_PIPELINE"
    assert listing["state"] == "ACTIVE"
    assert listing["removal_policy_category"] is None
    assert listing["suppressed_by_suspension"] is False
    # §3.2: restricted_flag is the seller's own optional declaration, false by default.
    assert listing["restricted_flag"] is False

    stored = read_seller(api, seller["id"])
    # §3.3: filing refreshes the exposure figure from the newest window and
    # increments the seller's version; creating a listing touches neither.
    assert stored["open_defect_claim_units"] == 3
    assert stored["version"] == 2


# --------------------------------------------------------------------------
# Computed mirrors, and the two rows that are history rather than state
# --------------------------------------------------------------------------
def test_the_sellers_health_fields_mirror_the_latest_evaluation(api):
    """PRD §3.4: "The evaluation records `evaluated_at` from the logical clock and
    copies its own `health_score` and `metric_tier` onto the seller, incrementing
    the seller's `version` by one."

    Design: Corner/entities/entity_seller_health_fields_follow_the_latest_evaluation
    """
    set_clock(api, CLOCK)
    seller = register_seller(
        api, legal_name="Harbor Tools LLC", email="ops@harbor-tools.example",
        tax_id_hash="TAX-HT-0001", payout_bank_token="BANK-HT-0001",
        address_fingerprint="ADDR-HT-0001",
    )
    file_snapshot(
        api, seller["id"], "2026-05-01T00:00:00.000Z", "2026-06-01T00:00:00.000Z",
        order_volume=1000, delivered_or_refunded_volume=1000, defect_claims_pending=0,
        defect_claims_substantiated=0, late_shipments=0, pre_fulfillment_cancellations=0,
        shipments_total=1000, shipments_with_valid_tracking=1000,
        source="PLATFORM_PIPELINE",
    )
    first = evaluate(api, seller["id"], INVESTIGATOR)

    # A clean window scores perfectly, so the mirror starts at the top of the range.
    assert_points(first["health_score"], "100.00", "health_score")
    assert first["metric_tier"] == "HEALTHY"
    assert first["breached_metrics"] == []
    assert_instant_equals(first["evaluated_at"], CLOCK, "evaluated_at")
    mirrored = read_seller(api, seller["id"])
    assert_points(mirrored["health_score"], "100.00", "health_score")
    assert mirrored["metric_tier"] == "HEALTHY"

    # A day later, a second window of the same size carries thirty proven claims.
    set_clock(api, "2026-08-02T00:00:00.000Z")
    file_snapshot(
        api, seller["id"], "2026-07-01T00:00:00.000Z", "2026-08-01T00:00:00.000Z",
        order_volume=1000, delivered_or_refunded_volume=1000, defect_claims_pending=0,
        defect_claims_substantiated=30, late_shipments=0, pre_fulfillment_cancellations=0,
        shipments_total=1000, shipments_with_valid_tracking=1000,
        source="PLATFORM_PIPELINE",
    )

    second = validate_success(api.create_health_evaluation(seller["id"], INVESTIGATOR), 201)

    assert second["input_snapshot_count"] == 2
    assert_instant_equals(second["input_window_start"], "2026-05-01T00:00:00.000Z",
                          "input_window_start")
    assert_instant_equals(second["input_window_end"], "2026-08-01T00:00:00.000Z",
                          "input_window_end")
    # The provisional reading sees only the latest window, the settled one both.
    assert_rate(second["odr_provisional"], "0.0300", "odr_provisional")
    assert_rate(second["odr_final"], "0.0150", "odr_final")
    assert_rate(second["odr_variant_delta"], "0.0150", "odr_variant_delta")
    assert second["breached_metrics"] == ["ORDER_DEFECT_RATE"]
    # 100.00 - round2(42.50 x (0.0150 - 0.0100) / 0.0100) = 100.00 - 21.25.
    assert_points(second["health_score"], "78.75", "health_score")
    assert second["metric_tier"] == "AT_RISK"
    assert_instant_equals(second["evaluated_at"], "2026-08-02T00:00:00.000Z",
                          "evaluated_at")

    stored = read_seller(api, seller["id"])
    # The mirror is the latest evaluation outright, not an average of 100.00 and
    # 78.75 and not the best figure the seller ever posted.
    assert_points(stored["health_score"], "78.75", "health_score")
    assert stored["metric_tier"] == "AT_RISK"
    assert stored["version"] == 5
    # A metric tier never touches the enforcement dimension.
    assert_posture(stored, enforcement_state="ACTIVE", disbursement_state="NORMAL",
                   severity_points_balance="0.00")


def test_evidence_rows_are_appended_and_never_restated(api):
    """PRD §2.4: "Two resources do not: a `MetricSnapshot` and a
    `HealthEvaluation` are immutable evidence records, and they carry only `id`
    and `created_at` — both `updated_at` and `version` are absent from those two
    resources entirely."

    Design: Corner/entities/entity_health_evaluation_and_snapshot_rows_are_immutable_history
    """
    set_clock(api, CLOCK)
    seller = register_seller(
        api, legal_name="Harbor Tools LLC", email="ops@harbor-tools.example",
        tax_id_hash="TAX-HT-0001", payout_bank_token="BANK-HT-0001",
        address_fingerprint="ADDR-HT-0001",
    )
    snapshot = file_snapshot(
        api, seller["id"], "2026-07-01T00:00:00.000Z", "2026-08-01T00:00:00.000Z",
        order_volume=800, delivered_or_refunded_volume=800, defect_claims_pending=0,
        defect_claims_substantiated=4, late_shipments=8, pre_fulfillment_cancellations=4,
        shipments_total=800, shipments_with_valid_tracking=790,
        source="PLATFORM_PIPELINE",
    )
    first = evaluate(api, seller["id"], INVESTIGATOR)

    second = validate_success(api.create_health_evaluation(seller["id"], OFFICER), 201)

    # The same input set filed twice yields two rows, not one restated row.
    assert second["id"] != first["id"]
    assert_immutable_evidence_fields(snapshot)
    assert_immutable_evidence_fields(first)
    assert_immutable_evidence_fields(second)

    # 4/800 = 0.0050, 8/800 = 0.0100, 4/800 = 0.0050, 790/800 = 0.9875: nothing
    # breaches, so both readings of the identical set score a perfect hundred.
    for evaluation in (first, second):
        assert_rate(evaluation["odr_final"], "0.0050", "odr_final")
        assert_rate(evaluation["late_shipment_rate"], "0.0100", "late_shipment_rate")
        assert_rate(evaluation["cancellation_rate"], "0.0050", "cancellation_rate")
        assert_rate(evaluation["valid_tracking_rate"], "0.9875", "valid_tracking_rate")
        assert_points(evaluation["health_score"], "100.00", "health_score")
        assert evaluation["metric_tier"] == "HEALTHY"
        assert_instant_equals(evaluation["evaluated_at"], CLOCK, "evaluated_at")

    filed, meta = validate_paginated(
        api.list_health_evaluations(
            REVIEWER, {"seller_id": seller["id"], "metric_tier": "HEALTHY", "limit": 10}
        )
    )
    assert {row["id"] for row in filed} == {first["id"], second["id"]}
    assert_meta(meta, total_count=2, has_more=False, limit=10)
    # One at registration, one for the snapshot, one for each evaluation.
    assert read_seller(api, seller["id"])["version"] == 4


# --------------------------------------------------------------------------
# Declared constraints, server-owned fields and body reference resolution
# --------------------------------------------------------------------------
def _snapshot_body(seller_id, **overrides):
    """A snapshot that would be accepted as written, so each rejection below
    differs from it in exactly one declared constraint."""
    body = {
        "seller_id": seller_id,
        "window_start": "2026-07-01T00:00:00.000Z",
        "window_end": "2026-08-01T00:00:00.000Z",
        "order_volume": 100,
        "delivered_or_refunded_volume": 100,
        "defect_claims_pending": 0,
        "defect_claims_substantiated": 0,
        "late_shipments": 0,
        "pre_fulfillment_cancellations": 0,
        "shipments_total": 100,
        "shipments_with_valid_tracking": 100,
    }
    body.update(overrides)
    return body


def test_four_declared_snapshot_constraints_all_land_on_invalid_request(api):
    """PRD §3.3: "A snapshot names its subject with `seller_id` and its interval
    with `window_start` and `window_end`, both ISO 8601 UTC instants with three
    fractional digits, where `window_end` must be strictly later than
    `window_start`."

    PRD §3.3: "The counters a snapshot carries are all non-negative integers."

    Design: Corner/entities/entity_metric_snapshot_type_constraints_are_rejected
    """
    set_clock(api, CLOCK)
    seller = register_seller(
        api, legal_name="Harbor Tools LLC", email="ops@harbor-tools.example",
        tax_id_hash="TAX-HT-0001", payout_bank_token="BANK-HT-0001",
        address_fingerprint="ADDR-HT-0001",
    )

    # An enum value outside the declared range.
    bad_enum = api.create_snapshot(
        _snapshot_body(seller["id"], source="GUESSTIMATE"), OFFICER
    )
    # "Strictly later", so equality is not enough.
    bad_window = api.create_snapshot(
        _snapshot_body(seller["id"], window_end="2026-07-01T00:00:00.000Z"), OFFICER
    )
    # §3.3: valid-tracking shipments may not exceed shipments_total.
    bad_bound = api.create_snapshot(
        _snapshot_body(seller["id"], shipments_with_valid_tracking=101), OFFICER
    )
    bad_negative = api.create_snapshot(
        _snapshot_body(seller["id"], order_volume=-1), OFFICER
    )

    for response in (bad_enum, bad_window, bad_bound, bad_negative):
        validate_error(response, ApiErrorId.INVALID_REQUEST.value)

    filed, meta = validate_paginated(api.list_seller_snapshots(seller["id"], OFFICER))
    assert filed == [], f"a refused window was filed anyway: {filed}"
    assert_meta(meta, total_count=0, has_more=False)
    stored = read_seller(api, seller["id"])
    # Nothing was filed, so nothing refreshed the exposure figure or the version.
    assert stored["version"] == 1
    assert stored["open_defect_claim_units"] == 0


def test_a_filed_report_takes_its_identity_and_history_from_the_server(api):
    """PRD §3.5: "A filed report opens in state `REPORTED` with `detected_at`
    taken from the logical clock, `auto_generated` false, and both
    `adjudicated_at` and `decision_note` null; it returns a 201 status."

    Design: Corner/entities/entity_violation_system_fields_are_server_generated
    """
    set_clock(api, CLOCK)
    rule = publish_rule(
        api, code="LA-SYS-1", category="LISTING_ACCURACY", base_severity_weight=2.00,
        removal_scope="ACCOUNT", requires_poa=False,
    )
    seller = register_seller(
        api, legal_name="Harbor Tools LLC", email="ops@harbor-tools.example",
        tax_id_hash="TAX-HT-0001", payout_bank_token="BANK-HT-0001",
        address_fingerprint="ADDR-HT-0001",
    )

    response = api.create_violation(
        {"seller_id": seller["id"], "policy_rule_id": rule["id"],
         "reporter_type": "BUYER", "evidence_reference": "EV-HT-0001"},
        INVESTIGATOR,
    )

    violation = validate_success(response, 201)
    assert violation["state"] == "REPORTED"
    # Only the BREACHING evaluation cascade of §3.4 ever sets this flag true.
    assert violation["auto_generated"] is False
    assert_instant_equals(violation["detected_at"], CLOCK, "detected_at")
    assert violation["adjudicated_at"] is None
    assert violation["decision_note"] is None
    # An account-scoped rule needs no cited item, and none was supplied.
    assert violation["listing_id"] is None
    assert violation["evidence_reference"] == "EV-HT-0001"
    assert_instant_equals(violation["created_at"], CLOCK, "created_at")
    assert violation["version"] == 1

    # §3.5: filing alone gates no money; only opening the investigation does.
    assert_posture(read_seller(api, seller["id"]), enforcement_state="ACTIVE",
                   disbursement_state="NORMAL")


def test_body_references_are_resolved_in_the_order_the_endpoint_declares_them(api):
    """PRD §2.9: "The same discipline governs foreign keys carried in a request
    body: they are resolved in the order in which the endpoint declares its input
    fields, and the first unresolvable reference decides the rejection, drawing
    from the same catalogue plus `ERR_POLICY_RULE_NOT_FOUND`."

    Design: Corner/entities/entity_body_foreign_keys_are_validated_left_to_right_and_return_not_found
    """
    set_clock(api, CLOCK)
    rule = publish_rule(
        api, code="LA-FK-1", category="LISTING_ACCURACY", base_severity_weight=2.00,
        removal_scope="ACCOUNT", requires_poa=False,
    )
    seller = register_seller(
        api, legal_name="Harbor Tools LLC", email="ops@harbor-tools.example",
        tax_id_hash="TAX-HT-0001", payout_bank_token="BANK-HT-0001",
        address_fingerprint="ADDR-HT-0001",
    )

    unknown_seller = api.create_violation(
        {"seller_id": UNKNOWN_ID_A, "policy_rule_id": rule["id"],
         "reporter_type": "BUYER", "evidence_reference": "EV-FK-0001"},
        INVESTIGATOR,
    )
    unknown_rule = api.create_violation(
        {"seller_id": seller["id"], "policy_rule_id": UNKNOWN_ID_B,
         "reporter_type": "BUYER", "evidence_reference": "EV-FK-0002"},
        INVESTIGATOR,
    )
    both_unknown = api.create_violation(
        {"seller_id": UNKNOWN_ID_A, "policy_rule_id": UNKNOWN_ID_B,
         "reporter_type": "BUYER", "evidence_reference": "EV-FK-0003"},
        INVESTIGATOR,
    )

    validate_error(unknown_seller, ApiErrorId.SELLER_NOT_FOUND.value)
    validate_error(unknown_rule, ApiErrorId.POLICY_RULE_NOT_FOUND.value)
    # §3.5 declares seller_id before policy_rule_id, so the seller decides.
    validate_error(both_unknown, ApiErrorId.SELLER_NOT_FOUND.value)

    filed, meta = validate_paginated(api.list_violations(INVESTIGATOR))
    assert filed == [], f"a refused report was filed anyway: {filed}"
    assert_meta(meta, total_count=0, has_more=False)
