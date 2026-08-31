"""Opening the case: firms, recalls and the distribution tree."""
from test_helpers import (
    ApiErrorId,
    NON_EXISTENT_UUID,
    RecallCase,
    assert_consignee,
    assert_distribution_record,
    assert_firm,
    assert_recall,
    create_consignee_payload,
    create_distribution_record_payload,
    create_firm_payload,
    create_recall_payload,
    draft_case,
    make_coordinator_headers,
    make_firm_officer_headers,
    register_firm,
    validate_error,
    validate_paginated,
    validate_success,
)

COORDINATOR = make_coordinator_headers("coord-1")


def test_firm_registration_applies_policy_defaults_and_zero_counters(api):
    """PRD §3.1: "Two insurance policy terms may be supplied at registration and both have defaults if they are not: `policy_deductible_cents`, which defaults to 2,500,000 cents — twenty-five thousand dollars — and must not be negative, and `policy_aggregate_cents`, which defaults to 100,000,000 cents — one million dollars — and must be strictly positive."
    PRD §3.1: "The firm's two running counters are server-owned and always start at zero: `policy_paid_to_date_cents`, which accumulates the amounts actually paid across every claim of this firm that reached partial or full payment, and `open_recall_count`, which tracks how many of the firm's recalls have not yet terminated."
    PRD §2.4: "Its `version` is an integer that begins at 1 when the row is created and increases by exactly one on every mutation of that row, whether the mutation came from a direct client write or from a cascade triggered elsewhere in the case file."

    Design: Corner/entities/firm_creation_applies_policy_defaults_and_zero_counters
    """
    response = api.create_firm(
        create_firm_payload(name="Northvale Foods", registration_number="FFR-10021"),
        COORDINATOR,
    )
    firm = validate_success(response, 201)
    assert_firm(firm)
    assert firm["policy_deductible_cents"] == 2500000
    assert firm["policy_aggregate_cents"] == 100000000
    assert firm["policy_paid_to_date_cents"] == 0
    assert firm["open_recall_count"] == 0
    assert firm["version"] == 1


def test_opening_a_recall_starts_in_draft_and_counts_against_the_firm(api):
    """PRD §3.1: "A newly opened case has `status` `DRAFT` and no `hazard_class` at all — the field is null until the recall is classified — and its whole derived apparatus (`effectiveness_check_level`, `sample_tier_scope`, `eligible_consignee_count`, `required_sample_size`, `responded_count`, `report_cadence_days`, `overdue_report_count`, `total_shipped_units`, `accounted_units`, `units_awaiting_disposition`, `units_pending_verification`, `units_disposed_verified`, `contact_effectiveness_pct`, `quantity_effectiveness_pct`, `official_effectiveness_pct`, `total_loaded_cost_cents`, `insurable_loaded_cost_cents` and `termination_denied_count`) starts at zero, with `compliance_flag` starting at `COMPLIANT`."
    PRD §3.1: "Opening the case also increments the firm's `open_recall_count` by one, which is a mutation of the firm row and therefore advances the firm's `version`."

    Design: Corner/entities/recall_creation_starts_draft_and_increments_firm_open_recall_count
    """
    firm = register_firm()
    officer = make_firm_officer_headers(firm["id"])

    response = api.create_recall(create_recall_payload(firm["id"]), officer)
    recall = validate_success(response, 201)
    assert_recall(recall)
    assert recall["status"] == "DRAFT"
    assert recall["hazard_class"] is None
    assert recall["effectiveness_check_level"] is None
    assert recall["total_shipped_units"] == 0
    assert recall["accounted_units"] == 0
    assert recall["total_loaded_cost_cents"] == 0
    assert recall["compliance_flag"] == "COMPLIANT"
    assert recall["version"] == 1

    firm_after = validate_success(api.get_firm(firm["id"], COORDINATOR))
    assert firm_after["open_recall_count"] == 1


def test_recall_listing_paginates_and_filters_by_firm(api):
    """PRD §2.3: "`limit` controls page size: it defaults to 10 when omitted, may not be smaller than 1, and may not be larger than 100."
    PRD §2.3: "List responses set `response_type` to `"array"` and populate four pagination fields in `meta`: `limit` and `offset` echo the effective values actually applied, `total_count` is the number of rows matching the filter before the page window is taken, and `has_more` is true when rows remain beyond the current window."

    Design: Corner/entities/recall_listing_paginates_with_total_count_and_has_more
    """
    firm = register_firm()
    officer = make_firm_officer_headers(firm["id"])
    for description, agency, lot in (
        ("Spinach A", "FDA", "L-1"),
        ("Spinach B", "FDA", "L-2"),
        ("Spinach C", "USDA", "L-3"),
    ):
        validate_success(
            api.create_recall(
                create_recall_payload(
                    firm["id"], product_description=description, agency=agency,
                    lot_codes=[lot],
                ),
                officer,
            ),
            201,
        )

    first_page = api.list_recalls(
        COORDINATOR, params={"firm_id": firm["id"], "limit": 2, "offset": 0}
    )
    assert first_page.json()["response_type"] == "array"
    rows, meta = validate_paginated(first_page)
    assert len(rows) == 2, f"Expected a page of 2, got {len(rows)}"
    assert meta["total_count"] == 3
    assert meta["has_more"] is True
    assert meta["limit"] == 2
    assert meta["offset"] == 0

    second_rows, second_meta = validate_paginated(
        api.list_recalls(
            COORDINATOR, params={"firm_id": firm["id"], "limit": 2, "offset": 2}
        )
    )
    assert len(second_rows) == 1
    assert second_meta["total_count"] == 3
    assert second_meta["has_more"] is False

    all_rows, all_meta = validate_paginated(
        api.list_recalls(COORDINATOR, params={"firm_id": firm["id"]})
    )
    assert len(all_rows) == 3
    assert all_meta["total_count"] == 3


def test_reading_an_unknown_recall_returns_recall_not_found(api):
    """PRD §2.6: "The `Recall` addressed by the leading `/recalls/{id}` path segment, or reached through a sub-resource's `recall_id`, exists — otherwise `ERR_RECALL_NOT_FOUND` (404)."

    Design: Corner/entities/get_recall_with_unknown_uuid_returns_not_found
    """
    response = api.get_recall(NON_EXISTENT_UUID, COORDINATOR)
    validate_error(response, ApiErrorId.ERR_RECALL_NOT_FOUND.value)
    assert response.status_code == 404
    assert response.json()["response_type"] == "error"


def test_opening_a_recall_without_agency_is_an_invalid_request(api):
    """PRD §3.1: "Opening a recall case requires the `firm_id` of the recalling firm, a `product_description`, the owning `agency`, the `initiation_type`, and `lot_codes` — an array of affected lot code strings that must contain at least one element."
    PRD §2.6: "The request body conforms to the endpoint's input schema: required fields present, enum values in range, integers non-negative where §3 says non-negative, quantity fields strictly positive where §3 says positive, `lot_codes` carrying at least one element, ISO 8601 instants parseable, and `period_start` strictly earlier than `period_end` — otherwise `ERR_INVALID_REQUEST` (400)."

    Design: Corner/entities/create_recall_missing_required_agency_returns_invalid_request
    """
    firm = register_firm()
    officer = make_firm_officer_headers(firm["id"])

    payload = create_recall_payload(firm["id"])
    payload.pop("agency")
    response = api.create_recall(payload, officer)
    validate_error(response, ApiErrorId.ERR_INVALID_REQUEST.value)
    assert response.status_code == 400

    rows, meta = validate_paginated(
        api.list_recalls(COORDINATOR, params={"firm_id": firm["id"]})
    )
    assert rows == []
    assert meta["total_count"] == 0
    firm_after = validate_success(api.get_firm(firm["id"], COORDINATOR))
    assert firm_after["open_recall_count"] == 0


def test_consignee_tier_is_derived_from_the_parent_chain(api):
    """PRD §3.1: "Omitting `parent_consignee_id` declares a direct consignee — one the firm shipped to itself — and gives it a `tier` of 1."
    PRD §3.1: "Supplying `parent_consignee_id` declares that an upstream consignee re-shipped to this one, and the new consignee's `tier` is one greater than its parent's."

    Design: Corner/entities/consignee_tier_is_computed_from_the_parent_chain_and_input_ignored
    """
    case = draft_case()
    c1 = case.add_consignee("Metro Distributors", "DISTRIBUTOR")
    c2 = case.add_consignee("Harbor Grocery", "RETAILER", parent_consignee_id=c1["id"])
    c3 = case.add_consignee("Pier Cafe", "RESTAURANT", parent_consignee_id=c2["id"])

    for consignee in (c1, c2, c3):
        assert_consignee(consignee)
    assert c1["tier"] == 1
    assert c2["tier"] == 2
    assert c3["tier"] == 3
    assert c1["parent_consignee_id"] is None

    kids_of_c1, _ = validate_paginated(api.list_sub_consignees(c1["id"], COORDINATOR))
    assert [row["id"] for row in kids_of_c1] == [c2["id"]]
    kids_of_c2, _ = validate_paginated(api.list_sub_consignees(c2["id"], COORDINATOR))
    assert [row["id"] for row in kids_of_c2] == [c3["id"]]
    kids_of_c3, meta = validate_paginated(api.list_sub_consignees(c3["id"], COORDINATOR))
    assert kids_of_c3 == []
    assert meta["total_count"] == 0


def test_a_fourth_generation_consignee_breaches_the_tier_cap(api):
    """PRD §3.1: "The tree is capped at three levels: a computed `tier` that would exceed 3 is refused with `ERR_CONSIGNEE_TIER_LIMIT`, so a consignee two hops below a direct consignee is the deepest the distribution list can go."

    Design: Corner/entities/consignee_beyond_tier_three_rejected_with_tier_limit
    """
    case = draft_case()
    c1 = case.add_consignee("Metro Distributors", "DISTRIBUTOR")
    c2 = case.add_consignee("Harbor Grocery", "RETAILER", parent_consignee_id=c1["id"])
    c3 = case.add_consignee("Pier Cafe", "RESTAURANT", parent_consignee_id=c2["id"])

    response = api.create_consignee(
        case.recall_id,
        create_consignee_payload(
            name="Pier Cafe Annex", consignee_type="INSTITUTION",
            parent_consignee_id=c3["id"],
        ),
        case.officer,
    )
    validate_error(response, ApiErrorId.ERR_CONSIGNEE_TIER_LIMIT.value)
    assert response.status_code == 422

    _, meta = validate_paginated(api.list_consignees(case.recall_id, COORDINATOR))
    assert meta["total_count"] == 3
    _, sub_meta = validate_paginated(api.list_sub_consignees(c3["id"], COORDINATOR))
    assert sub_meta["total_count"] == 0


def test_parent_consignee_from_another_recall_is_not_found(api):
    """PRD §2.6: "The `Consignee` addressed by a `/consignees/{id}` path segment or named by a `consignee_id` body field exists **and** belongs to the recall in the path — otherwise `ERR_CONSIGNEE_NOT_FOUND` (404)."
    PRD §2.9: "Where a body field names a consignee, that consignee must both exist and belong to the recall named in the path — cross-recall references are not silently tolerated and are not treated as authorization failures."

    Design: Corner/entities/consignee_from_another_recall_cannot_be_used_as_parent_returns_not_found
    """
    firm = register_firm()
    officer = make_firm_officer_headers(firm["id"])
    recall_a = validate_success(
        api.create_recall(
            create_recall_payload(
                firm["id"], product_description="Spinach A", lot_codes=["L-1"]
            ),
            officer,
        ),
        201,
    )
    recall_b = validate_success(
        api.create_recall(
            create_recall_payload(
                firm["id"], product_description="Spinach B", lot_codes=["L-2"]
            ),
            officer,
        ),
        201,
    )
    consignee_a = validate_success(
        api.create_consignee(recall_a["id"], create_consignee_payload(), officer), 201
    )

    response = api.create_consignee(
        recall_b["id"],
        create_consignee_payload(
            name="Cross-linked child", consignee_type="RETAILER",
            parent_consignee_id=consignee_a["id"],
        ),
        officer,
    )
    validate_error(response, ApiErrorId.ERR_CONSIGNEE_NOT_FOUND.value)
    assert response.status_code == 404

    rows, meta = validate_paginated(api.list_consignees(recall_b["id"], COORDINATOR))
    assert rows == []
    assert meta["total_count"] == 0


def test_shipment_line_with_zero_quantity_is_rejected(api):
    """PRD §3.4: "A shipment line is declared by a `FirmRecallOfficer` and names the `consignee_id` it went to, the `lot_code` shipped, the `quantity_shipped` — an integer that must be strictly greater than zero — and a `ship_date` as an ISO 8601 UTC instant."

    Design: Corner/entities/distribution_record_with_zero_quantity_shipped_rejected
    """
    case = draft_case()
    consignee = case.add_consignee()

    response = api.create_distribution_record(
        case.recall_id,
        create_distribution_record_payload(consignee["id"], 0),
        case.officer,
    )
    validate_error(response, ApiErrorId.ERR_INVALID_REQUEST.value)
    assert response.status_code == 400

    rows, meta = validate_paginated(
        api.list_consignee_distribution_records(consignee["id"], COORDINATOR)
    )
    assert rows == []
    assert meta["total_count"] == 0
    assert case.read_recall()["total_shipped_units"] == 0


def test_consignee_shipment_sub_listing_returns_only_that_consignees_lines(api):
    """PRD §3.4: "A newly declared line is in `status` `DECLARED` with `effective_quantity` 0, `quantity_confirmed` null and `reconcile_round` 0."
    PRD §3.4: "A declared line contributes nothing at all to the recall's `total_shipped_units`; only reconciliation gives a line weight."

    Design: Corner/endpoints/distribution_records_sub_resource_returns_only_the_addressed_consignees_lines
    """
    case = draft_case()
    c1 = case.add_consignee("Metro Distributors", "DISTRIBUTOR")
    c2 = case.add_consignee("Harbor Grocery", "RETAILER")
    d1 = case.add_shipment(c1["id"], 600)
    d2 = case.add_shipment(c2["id"], 400, ship_date="2026-08-21T00:00:00Z")

    rows_1, meta_1 = validate_paginated(
        api.list_consignee_distribution_records(c1["id"], COORDINATOR)
    )
    assert meta_1["total_count"] == 1
    assert rows_1[0]["id"] == d1["id"]
    assert rows_1[0]["quantity_shipped"] == 600

    rows_2, meta_2 = validate_paginated(
        api.list_consignee_distribution_records(c2["id"], COORDINATOR)
    )
    assert meta_2["total_count"] == 1
    assert rows_2[0]["id"] == d2["id"]
    assert rows_2[0]["quantity_shipped"] == 400

    all_rows, all_meta = validate_paginated(
        api.list_distribution_records(case.recall_id, COORDINATOR)
    )
    assert all_meta["total_count"] == 2
    for row in all_rows:
        assert_distribution_record(row)
        assert row["status"] == "DECLARED"
        assert row["effective_quantity"] == 0
    assert case.read_recall()["total_shipped_units"] == 0


def test_correcting_a_confirmed_line_is_an_invalid_accounting_state(api):
    """PRD §3.4: "`CORRECT` is only available from `DISPUTED`, moves `DISPUTED → CORRECTED`, and requires a `quantity_confirmed` in the body that is present and strictly greater than zero — omit it or send zero and the request is refused with `ERR_INVALID_REQUEST`; the supplied value is stored as `quantity_confirmed` and becomes the line's `effective_quantity`."
    PRD §3.4: "An outcome the line's current `status` does not permit is refused with `ERR_INVALID_ACCOUNTING_STATE`, and no reconciliation of any kind is permitted once the recall has terminated."

    Design: Corner/errors/correcting_a_confirmed_distribution_record_returns_invalid_accounting_state
    """
    case = draft_case()
    consignee = case.add_consignee()
    record = case.confirmed_shipment(consignee["id"], 600)

    response = api.reconcile_distribution_record(
        record["id"], {"outcome": "CORRECT", "quantity_confirmed": 550}, case.officer
    )
    validate_error(response, ApiErrorId.ERR_INVALID_ACCOUNTING_STATE.value)
    assert response.status_code == 409

    after = validate_success(
        api.list_distribution_records(case.recall_id, COORDINATOR)
    )[0]
    assert after["status"] == "CONFIRMED"
    assert after["effective_quantity"] == 600
    assert after["quantity_confirmed"] is None
    assert after["reconcile_round"] == 1
    assert case.read_recall()["total_shipped_units"] == 600


def test_reading_an_unknown_firm_returns_firm_not_found(api):
    """PRD §2.6: "The `Firm` addressed by a path segment or by the `firm_id` body field exists — otherwise `ERR_FIRM_NOT_FOUND` (404). Applies to `GET /firms/{id}` and `POST /recalls`."

    Design: Corner/errors/get_firm_with_unknown_uuid_returns_firm_not_found
    """
    response = api.get_firm(NON_EXISTENT_UUID, COORDINATOR)
    validate_error(response, ApiErrorId.ERR_FIRM_NOT_FOUND.value)
    assert response.status_code == 404


class TestDistributionLedgerConservation:
    """A confirm → dispute → confirm round trip leaves the unit ledger intact."""

    def test_dispute_then_reconfirm_restores_total_shipped_units(self, api):
        """PRD §2.8: "Reconciling a distribution line as confirmed, then disputing it, then confirming it again restores the recall's shipped-unit total to exactly its pre-cycle value."
        PRD §3.4: "Every reconciliation, whatever the outcome, increments `reconcile_round` by one and re-sums the recall's `total_shipped_units` from the `effective_quantity` of all its lines, then recomputes `quantity_effectiveness_pct` and `official_effectiveness_pct`."

        Design: Difficulty/compensating_invariant/distribution_confirm_dispute_confirm_conserves_total_shipped_units
        """
        case = RecallCase(agency="USDA")
        c1 = case.add_consignee("Metro Distributors", "DISTRIBUTOR")
        c2 = case.add_consignee("Harbor Grocery", "RETAILER")
        d1 = case.confirmed_shipment(c1["id"], 600)
        case.confirmed_shipment(c2["id"], 400, ship_date="2026-08-21T00:00:00Z")

        total_before = case.read_recall()["total_shipped_units"]
        assert total_before == 1000

        case.reconcile(d1["id"], "DISPUTE")
        mid = case.read_recall()
        assert mid["total_shipped_units"] == 400
        assert mid["quantity_effectiveness_pct"] == 0.00

        case.reconcile(d1["id"], "CONFIRM")
        total_after = case.read_recall()["total_shipped_units"]
        assert total_after == 1000
        assert total_after == total_before

    def test_reconfirmed_line_clears_quantity_confirmed_and_counts_rounds(self, api):
        """PRD §3.4: "`CONFIRM` moves `DECLARED → CONFIRMED` or `DISPUTED → CONFIRMED`, sets `effective_quantity` to `quantity_shipped`, and — on the return from `DISPUTED` — clears `quantity_confirmed` back to null."
        PRD §3.4: "`DISPUTE` moves `DECLARED → DISPUTED`, `CONFIRMED → DISPUTED` or `CORRECTED → DISPUTED` and sets `effective_quantity` to 0."

        Design: Difficulty/compensating_invariant/distribution_confirm_dispute_confirm_conserves_total_shipped_units
        """
        case = RecallCase(agency="USDA")
        c1 = case.add_consignee("Metro Distributors", "DISTRIBUTOR")
        c2 = case.add_consignee("Harbor Grocery", "RETAILER")
        d1 = case.confirmed_shipment(c1["id"], 600)
        case.confirmed_shipment(c2["id"], 400, ship_date="2026-08-21T00:00:00Z")

        disputed = case.reconcile(d1["id"], "DISPUTE")
        assert disputed["status"] == "DISPUTED"
        assert disputed["effective_quantity"] == 0

        reconfirmed = case.reconcile(d1["id"], "CONFIRM")
        assert_distribution_record(reconfirmed)
        assert reconfirmed["status"] == "CONFIRMED"
        assert reconfirmed["effective_quantity"] == 600
        assert reconfirmed["reconcile_round"] == 3
        assert reconfirmed["quantity_confirmed"] is None
