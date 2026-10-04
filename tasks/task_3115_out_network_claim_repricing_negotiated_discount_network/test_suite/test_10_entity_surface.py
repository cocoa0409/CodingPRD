"""Corner queue: entity surface — creation defaults, retrieval round-trips,
pagination, required fields, computed fields, enums, rate-row immutability."""
from test_helpers import (
    api_client, validate_success, validate_error, validate_paginated,
    get_success_data,
    create_payer, create_provider, create_medicare_entry, create_ucr_rate,
    create_claim, add_line,
    create_payer_client_payload, create_provider_payload, create_claim_payload,
    create_claim_line_payload,
    make_payer_rep_headers,
    TEST_USERS, NON_EXISTENT_UUID, ApiErrorId,
)

OPS = TEST_USERS["ops_admin_headers"]
NET = TEST_USERS["network_admin_headers"]


def test_payer_client_create_returns_defaults_and_system_fields():
    """PRD §3.1: "an optional `minimum_invoice_cents` floor that defaults to 0
    (fee invoices whose gross fees fall strictly below the floor are still
    issued; the floor gates nothing when it is 0), and an optional
    `transparency_reporting_enabled` flag that defaults to false. A newly
    created `PayerClient` is `ACTIVE`."
    PRD §2.4: "All entities except `MedicareFeeScheduleEntry` and
    `UsualCustomaryRate` carry `created_at`, `updated_at`, and an integer
    `version` that starts at 1 and increments by exactly 1 on every mutation of
    that resource, including system-driven cascades that touch the entity."

    Design: Corner/entities/payer_client_create_returns_defaults_and_system_fields
    """
    payer = validate_success(api_client.create_payer_client(
        create_payer_client_payload(payer_name="Acme Health Plan"), OPS), 201)
    assert payer["status"] == "ACTIVE"
    assert payer["version"] == 1
    assert payer["minimum_invoice_cents"] == 0
    assert payer["transparency_reporting_enabled"] is False
    assert payer["id"]
    assert payer["created_at"] and payer["updated_at"]


def test_provider_get_round_trips_and_unknown_id_returns_404():
    """PRD §3.2: "Providers may be fetched individually or listed with `limit`
    and `offset`."
    PRD §2.10: "then path-id existence checked left-to-right (`ERR_NOT_FOUND`)"
    PRD §5: "`ERR_NOT_FOUND` | 404"

    Design: Corner/entities/provider_get_round_trips_and_unknown_id_returns_404
    """
    provider = validate_success(api_client.create_provider(
        create_provider_payload(npi="2000000001", legal_name="Round Trip MD",
                                tin="T-9"), NET), 201)
    reader = make_payer_rep_headers("ignored-opaque-read")
    fetched = validate_success(api_client.get_provider(provider["id"], reader), 200)
    assert fetched["npi"] == "2000000001"
    assert fetched["legal_name"] == "Round Trip MD"
    assert fetched["tin"] == "T-9"

    res = api_client.get_provider(NON_EXISTENT_UUID, reader)
    validate_error(res, ApiErrorId.ERR_NOT_FOUND)


def test_claims_list_paginates_with_total_count_and_has_more():
    """PRD §2.3: "Responses include `limit`, `offset`, `total_count`, and
    `has_more` inside the `meta` envelope so the caller can page
    deterministically."
    PRD §3.3: "Claims themselves may be fetched, or listed with
    `payer_client_id`, `provider_id`, `status`, or `network_status` filters plus
    pagination."

    Design: Corner/entities/claims_list_paginates_with_total_count_and_has_more
    """
    payer = create_payer()
    provider = create_provider(npi="2000000002")
    pr = make_payer_rep_headers(payer["id"])
    for ref in ("L1", "L2", "L3"):
        get_success_data(api_client.create_claim(
            create_claim_payload(payer["id"], provider["id"],
                                 external_claim_ref=ref), pr))

    page1, meta1 = validate_paginated(api_client.list_claims(
        pr, params={"payer_client_id": payer["id"], "limit": 2, "offset": 0}))
    assert len(page1) == 2
    assert meta1["total_count"] == 3
    assert meta1["has_more"] is True

    page2, meta2 = validate_paginated(api_client.list_claims(
        pr, params={"payer_client_id": payer["id"], "limit": 2, "offset": 2}))
    assert len(page2) == 1
    assert meta2["has_more"] is False


def test_claim_missing_required_field_returns_invalid_request():
    """PRD §2.10: "Malformed request bodies — missing required fields, wrong
    types, non-positive amounts, or `quantity_units` below 1 — are rejected with
    `ERR_INVALID_REQUEST` (HTTP 400)."
    PRD §3.3: "A `PayerRep` ingests a claim by supplying `payer_client_id`,
    `provider_id`, an `external_claim_ref` that is unique among that payer's
    claims"

    Design: Corner/entities/claim_missing_required_field_returns_invalid_request
    """
    payer = create_payer()
    provider = create_provider(npi="2000000003")
    pr = make_payer_rep_headers(payer["id"])
    payload = create_claim_payload(payer["id"], provider["id"])
    del payload["external_claim_ref"]
    res = api_client.create_claim(payload, pr)
    validate_error(res, ApiErrorId.ERR_INVALID_REQUEST)

    data, meta = validate_paginated(api_client.list_claims(
        pr, params={"payer_client_id": payer["id"]}))
    assert meta["total_count"] == 0


def test_claim_computed_fields_null_before_pricing_and_input_ignored():
    """PRD §3.3: "A newly ingested claim is in `RECEIVED` status with
    `billed_amount_cents` equal to 0, and `methodology_used`,
    `allowed_amount_cents`, `payer_liability_cents`, `savings_cents`, and
    `rbp_amount_cents` are all null."
    PRD §3.3: "The first line added moves the claim from `RECEIVED` to
    `PENDING_LINES`; subsequent lines keep it in `PENDING_LINES`."

    Design: Corner/entities/claim_computed_fields_null_before_pricing_and_input_ignored
    """
    payer = create_payer()
    provider = create_provider(npi="2000000004")
    pr = make_payer_rep_headers(payer["id"])
    payload = create_claim_payload(payer["id"], provider["id"],
                                   external_claim_ref="C1")
    payload["allowed_amount_cents"] = 1  # computed field — must be ignored
    claim = validate_success(api_client.create_claim(payload, pr), 201)
    get_success_data(api_client.add_claim_line(
        claim["id"], create_claim_line_payload(quantity_units=1,
                                               unit_charge_cents=10000), pr))

    claim = validate_success(api_client.get_claim(claim["id"], pr), 200)
    assert claim["allowed_amount_cents"] is None
    assert claim["payer_liability_cents"] is None
    assert claim["savings_cents"] is None
    assert claim["methodology_used"] is None
    assert claim["status"] == "PENDING_LINES"
    assert claim["billed_amount_cents"] == 10000


def test_claim_invalid_enum_value_rejected():
    """PRD §2.10: "Malformed request bodies — missing required fields, wrong
    types, non-positive amounts, or `quantity_units` below 1 — are rejected with
    `ERR_INVALID_REQUEST` (HTTP 400)."
    PRD §3.1: "picks a `claim_type` from `PROFESSIONAL`, `FACILITY`, `ANCILLARY`,
    or `EMERGENCY`"

    Design: Corner/entities/claim_invalid_enum_value_rejected
    """
    payer = create_payer()
    provider = create_provider(npi="2000000005")
    pr = make_payer_rep_headers(payer["id"])
    res = api_client.create_claim(
        create_claim_payload(payer["id"], provider["id"],
                             external_claim_ref="C2", claim_type="DENTAL"), pr)
    validate_error(res, ApiErrorId.ERR_INVALID_REQUEST)


def test_medicare_and_ucr_rows_are_immutable_without_version_field():
    """PRD §2.4: "`MedicareFeeScheduleEntry` and `UsualCustomaryRate` are
    exception rows: they carry only `id` and `created_at` — `updated_at` and
    `version` are absent from both entities."
    PRD §3.2: "Neither table row carries `updated_at` or `version`; they are
    immutable reference data once loaded."

    Design: Corner/entities/medicare_and_ucr_rows_are_immutable_without_version_field
    """
    create_medicare_entry(procedure_code="00100", region_code="R9",
                          base_rate_cents=5000, geographic_adjustment_factor=1.00)
    rows, meta = validate_paginated(api_client.list_medicare_entries(
        NET, params={"procedure_code": "00100", "region_code": "R9"}))
    assert len(rows) == 1
    row = rows[0]
    assert row["id"] and row["created_at"]
    assert "version" not in row, "rate rows carry no version field"
    assert "updated_at" not in row, "rate rows carry no updated_at field"
