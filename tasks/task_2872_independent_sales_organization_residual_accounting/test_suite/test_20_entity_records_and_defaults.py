"""Entity records, declared defaults, computed fields and flat-topology lookups.

Every test builds its own state through the public endpoints only; the harness
restarts the server and empties the database before each one, and the logical
clock starts at 2026-08-01T00:00:00Z.
"""

from test_helpers import (
    ADMIN_ONE,
    ANALYST_ONE,
    CONTROLLER_ONE,
    NON_EXISTENT_UUID,
    ApiErrorId,
    api_client,
    assert_agent,
    assert_chargeback_event,
    assert_merchant,
    assert_processor_program,
    create_agent_payload,
    create_chargeback_payload,
    create_merchant_payload,
    create_processor_program_payload,
    create_residual_batch_payload,
    create_residual_line_payload,
    is_valid_uuid,
    set_logical_clock,
    validate_error,
    validate_paginated,
    validate_success,
)

UNKNOWN_ID = NON_EXISTENT_UUID


def _pct(value) -> float:
    """Percentages are decimal fractions; accept either a JSON number or string."""
    return float(value)


def test_create_processor_program_returns_full_record_with_defaults():
    """A newly registered program begins with `status` set to `ACTIVE` and `posted_batch_count` at 0.

    `minimum_billing_mode` is optional at registration, defaults to
    `SHORTFALL_BILLED` when omitted.

    Design: Corner/entities/create_processor_program_returns_full_record_with_defaults
    """
    payload = create_processor_program_payload(
        name="FirstAtlantic Core",
        buy_rate_bps=45,
        buy_rate_per_item_cents=6,
        assessment_bps=13,
        normalization_mode="NET_REVENUE_SPLIT",
    )
    payload.pop("minimum_billing_mode", None)

    response = api_client.create_processor_program(payload, ADMIN_ONE)
    data = validate_success(response, 201)
    body = response.json()

    assert body["response_type"] == "object", (
        f"a single created resource must report response_type object, got {body['response_type']!r}"
    )
    assert body["meta"]["api_request_id"].startswith("req_"), (
        f"api_request_id must start with req_, got {body['meta']['api_request_id']!r}"
    )
    assert isinstance(body["meta"]["api_request_timestamp"], str) and body["meta"][
        "api_request_timestamp"
    ], "api_request_timestamp must be a non-empty server-generated timestamp"

    assert data["name"] == "FirstAtlantic Core", "name must be echoed verbatim"
    assert data["buy_rate_bps"] == 45, f"buy_rate_bps expected 45, got {data['buy_rate_bps']}"
    assert data["buy_rate_per_item_cents"] == 6, (
        f"buy_rate_per_item_cents expected 6, got {data['buy_rate_per_item_cents']}"
    )
    assert data["assessment_bps"] == 13, (
        f"assessment_bps expected 13, got {data['assessment_bps']}"
    )
    assert data["normalization_mode"] == "NET_REVENUE_SPLIT", (
        f"normalization_mode expected NET_REVENUE_SPLIT, got {data['normalization_mode']!r}"
    )

    assert data["minimum_billing_mode"] == "SHORTFALL_BILLED", (
        "an omitted minimum_billing_mode takes the declared default SHORTFALL_BILLED, got "
        f"{data['minimum_billing_mode']!r}"
    )
    assert data["status"] == "ACTIVE", (
        f"a newly registered program begins ACTIVE, got {data['status']!r}"
    )
    assert data["posted_batch_count"] == 0, (
        f"posted_batch_count starts at 0, got {data['posted_batch_count']}"
    )

    assert is_valid_uuid(data["id"]), f"id must be a bare UUID, got {data['id']!r}"
    assert "_" not in data["id"], f"id must carry no type prefix, got {data['id']!r}"
    assert data["version"] == 1, f"version starts at 1 on creation, got {data['version']}"
    assert data["created_at"] == data["updated_at"], (
        "an unmutated row's updated_at equals its created_at, got "
        f"{data['created_at']!r} vs {data['updated_at']!r}"
    )
    assert_processor_program(data)


def test_read_back_processor_program_by_id():
    """every other successful operation, including all state transitions and all reads, returns HTTP 200 with the affected or requested resource in `data`.

    Design: Corner/entities/read_back_processor_program_by_id
    """
    created = validate_success(
        api_client.create_processor_program(
            create_processor_program_payload(
                name="Gross House Program",
                buy_rate_bps=50,
                buy_rate_per_item_cents=5,
                assessment_bps=12,
                normalization_mode="GROSS_SPLIT",
                minimum_billing_mode="NO_MINIMUM",
            ),
            ADMIN_ONE,
        ),
        201,
    )

    read = validate_success(api_client.get_processor_program(created["id"], ANALYST_ONE), 200)

    assert read["id"] == created["id"], "the read must address the same row"
    assert read["normalization_mode"] == "GROSS_SPLIT", (
        f"normalization_mode expected GROSS_SPLIT, got {read['normalization_mode']!r}"
    )
    assert read["minimum_billing_mode"] == "NO_MINIMUM", (
        f"an explicit NO_MINIMUM must be stored as given, got {read['minimum_billing_mode']!r}"
    )
    assert read["buy_rate_bps"] == 50, f"buy_rate_bps expected 50, got {read['buy_rate_bps']}"
    assert read["buy_rate_per_item_cents"] == 5, (
        f"buy_rate_per_item_cents expected 5, got {read['buy_rate_per_item_cents']}"
    )
    assert read["assessment_bps"] == 12, (
        f"assessment_bps expected 12, got {read['assessment_bps']}"
    )
    assert read["version"] == 1, (
        f"no mutation happened, so version stays 1, got {read['version']}"
    )
    assert read["status"] == "ACTIVE", f"status expected ACTIVE, got {read['status']!r}"

    for field, value in created.items():
        assert read[field] == value, (
            f"the read path must return the stored row unchanged; {field} was {value!r} "
            f"at creation but {read[field]!r} on read"
        )
    assert_processor_program(read)


def test_list_agents_paginates_with_total_count_and_has_more():
    """`total_count` (the number of rows matching the filters before pagination), and `has_more` (true when rows remain beyond the current page).

    Design: Corner/entities/list_agents_paginates_with_total_count_and_has_more
    """
    a1 = validate_success(
        api_client.create_agent(
            create_agent_payload(
                name="A1 Principal",
                split_pct=0.30,
                override_pct=0.55,
                vesting_start_date="2024-01-15",
            ),
            ADMIN_ONE,
        ),
        201,
    )
    a2 = validate_success(
        api_client.create_agent(
            create_agent_payload(
                name="A2 Regional",
                split_pct=0.40,
                override_pct=0.50,
                vesting_start_date="2025-01-15",
            ),
            ADMIN_ONE,
        ),
        201,
    )
    a3 = validate_success(
        api_client.create_agent(
            create_agent_payload(
                name="A3 Rep",
                split_pct=0.45,
                override_pct=0.45,
                vesting_start_date="2026-02-01",
            ),
            ADMIN_ONE,
        ),
        201,
    )

    first_response = api_client.list_agents(ADMIN_ONE, {"limit": 2, "offset": 0})
    first_rows, first_meta = validate_paginated(first_response)
    assert first_response.json()["response_type"] == "array", (
        "a list read must report response_type array"
    )
    assert len(first_rows) == 2, f"limit=2 must return 2 rows, got {len(first_rows)}"
    assert first_meta["total_count"] == 3, (
        f"total_count counts the whole filtered set, expected 3, got {first_meta['total_count']}"
    )
    assert first_meta["has_more"] is True, (
        "rows remain beyond the first page, so has_more must be true"
    )
    assert first_meta["limit"] == 2, f"meta.limit must echo 2, got {first_meta['limit']}"
    assert first_meta["offset"] == 0, f"meta.offset must echo 0, got {first_meta['offset']}"

    second_rows, second_meta = validate_paginated(
        api_client.list_agents(ADMIN_ONE, {"limit": 2, "offset": 2})
    )
    assert len(second_rows) == 1, (
        f"offset=2 leaves exactly one row of three, got {len(second_rows)}"
    )
    assert second_meta["total_count"] == 3, (
        f"total_count is page-independent, expected 3, got {second_meta['total_count']}"
    )
    assert second_meta["has_more"] is False, (
        "no rows remain beyond the second page, so has_more must be false"
    )
    assert second_meta["offset"] == 2, f"meta.offset must echo 2, got {second_meta['offset']}"

    paged_ids = [row["id"] for row in first_rows] + [row["id"] for row in second_rows]
    assert len(paged_ids) == len(set(paged_ids)), (
        f"no row may repeat across pages, got {paged_ids}"
    )
    assert set(paged_ids) == {a1["id"], a2["id"], a3["id"]}, (
        "the two pages together must cover exactly the three created agents"
    )
    for row in first_rows + second_rows:
        assert_agent(row)


def test_address_every_collection_with_unknown_id_returns_not_found():
    """A path segment that names no row produces that entity's not-found error.

    Design: Corner/entities/address_every_collection_with_unknown_id_returns_not_found
    """
    probes = [
        ("processor program", api_client.get_processor_program(UNKNOWN_ID, ADMIN_ONE),
         ApiErrorId.ERR_PROGRAM_NOT_FOUND.value),
        ("agent", api_client.get_agent(UNKNOWN_ID, ADMIN_ONE),
         ApiErrorId.ERR_AGENT_NOT_FOUND.value),
        ("advance", api_client.get_agent_advance(UNKNOWN_ID, ADMIN_ONE),
         ApiErrorId.ERR_ADVANCE_NOT_FOUND.value),
        ("merchant", api_client.get_merchant(UNKNOWN_ID, ADMIN_ONE),
         ApiErrorId.ERR_MERCHANT_NOT_FOUND.value),
        ("chargeback event", api_client.get_chargeback_event(UNKNOWN_ID, ANALYST_ONE),
         ApiErrorId.ERR_CHARGEBACK_NOT_FOUND.value),
        ("residual batch", api_client.get_residual_batch(UNKNOWN_ID, ANALYST_ONE),
         ApiErrorId.ERR_BATCH_NOT_FOUND.value),
        ("residual line", api_client.get_residual_line(UNKNOWN_ID, ANALYST_ONE),
         ApiErrorId.ERR_LINE_NOT_FOUND.value),
        ("profitability row", api_client.get_merchant_profitability(UNKNOWN_ID, CONTROLLER_ONE),
         ApiErrorId.ERR_PROFITABILITY_NOT_FOUND.value),
        ("allocation", api_client.get_residual_allocation(UNKNOWN_ID, CONTROLLER_ONE),
         ApiErrorId.ERR_ALLOCATION_NOT_FOUND.value),
        ("statement", api_client.get_agent_statement(UNKNOWN_ID, CONTROLLER_ONE),
         ApiErrorId.ERR_STATEMENT_NOT_FOUND.value),
        ("adjustment", api_client.get_statement_adjustment(UNKNOWN_ID, CONTROLLER_ONE),
         ApiErrorId.ERR_ADJUSTMENT_NOT_FOUND.value),
    ]

    seen = []
    for label, response, expected_error_id in probes:
        error = validate_error(response, expected_error_id)
        assert response.json()["response_type"] == "error", (
            f"the {label} lookup must use the error envelope"
        )
        seen.append(error["error_id"])

    assert len(seen) == 11, f"all eleven collections must be probed, got {len(seen)}"
    assert len(set(seen)) == 11, (
        f"each collection reports its own not-found identifier; got duplicates in {seen}"
    )


def test_create_merchant_missing_required_field_invalid_request():
    """Every required input field is present, every value has the declared JSON type, every enum-typed field carries a value drawn from that field's declared set, integer cent fields are integers, and the fields that must be non-negative are non-negative.

    Design: Corner/entities/create_merchant_missing_required_field_invalid_request
    """
    program = validate_success(
        api_client.create_processor_program(create_processor_program_payload(), ADMIN_ONE), 201
    )
    agent = validate_success(
        api_client.create_agent(
            create_agent_payload(split_pct=0.45, override_pct=0.45), ADMIN_ONE
        ),
        201,
    )

    missing = create_merchant_payload(agent["id"], program["id"], mid="MID-1001")
    missing.pop("monthly_minimum_cents")
    validate_error(
        api_client.create_merchant(missing, ADMIN_ONE),
        ApiErrorId.ERR_INVALID_REQUEST.value,
    )

    wrong_type = create_merchant_payload(
        agent["id"], program["id"], mid="MID-1002", monthly_minimum_cents="2500"
    )
    validate_error(
        api_client.create_merchant(wrong_type, ADMIN_ONE),
        ApiErrorId.ERR_INVALID_REQUEST.value,
    )

    negative_money = create_merchant_payload(
        agent["id"],
        program["id"],
        mid="MID-1003",
        monthly_minimum_cents=2500,
        equipment_lease_monthly_cents=-100,
    )
    validate_error(
        api_client.create_merchant(negative_money, ADMIN_ONE),
        ApiErrorId.ERR_INVALID_REQUEST.value,
    )

    rows, meta = validate_paginated(api_client.list_merchants(ADMIN_ONE, {}))
    assert meta["total_count"] == 0, (
        f"no partial merchant row may be written by a refused boarding, got {meta['total_count']}"
    )
    assert rows == [], f"the merchant collection must still be empty, got {rows}"


def test_omitted_optional_inputs_take_declared_defaults():
    """`upfront_bonus_cents` — the boarding bonus already paid to the owning agent — is optional and defaults to 0 when omitted.

    a `parent_agent_id` naming the agent immediately above it — null for a top-level
    principal, and null by default when the field is omitted at creation

    `minimum_billing_mode` is optional at registration, defaults to
    `SHORTFALL_BILLED` when omitted

    Design: Corner/entities/omitted_optional_inputs_take_declared_defaults
    """
    program_payload = create_processor_program_payload()
    program_payload.pop("minimum_billing_mode", None)
    program = validate_success(
        api_client.create_processor_program(program_payload, ADMIN_ONE), 201
    )

    agent_payload = create_agent_payload(split_pct=0.45, override_pct=0.45)
    agent_payload.pop("parent_agent_id", None)
    agent = validate_success(api_client.create_agent(agent_payload, ADMIN_ONE), 201)

    merchant_payload = create_merchant_payload(agent["id"], program["id"], mid="MID-1001")
    merchant_payload.pop("upfront_bonus_cents", None)
    merchant = validate_success(api_client.create_merchant(merchant_payload, ADMIN_ONE), 201)

    assert merchant["upfront_bonus_cents"] == 0, (
        f"an omitted upfront_bonus_cents defaults to 0, got {merchant['upfront_bonus_cents']!r}"
    )
    assert merchant["clawed_back_bonus_cents"] == 0, (
        f"boarding leaves clawed_back_bonus_cents at 0, got {merchant['clawed_back_bonus_cents']}"
    )
    assert merchant["status"] == "PENDING", (
        f"boarding leaves the merchant PENDING, got {merchant['status']!r}"
    )
    assert merchant["attrition_date"] is None, (
        f"attrition_date must be null at boarding, got {merchant['attrition_date']!r}"
    )
    assert merchant["reactivation_date"] is None, (
        f"reactivation_date must be null at boarding, got {merchant['reactivation_date']!r}"
    )
    assert_merchant(merchant)

    stored_agent = validate_success(api_client.get_agent(agent["id"], ADMIN_ONE), 200)
    assert stored_agent["parent_agent_id"] is None, (
        f"an omitted parent_agent_id defaults to null, got {stored_agent['parent_agent_id']!r}"
    )
    assert stored_agent["hierarchy_depth"] == 0, (
        f"a top-level principal sits at depth 0, got {stored_agent['hierarchy_depth']}"
    )
    assert stored_agent["portfolio_merchant_count"] == 1, (
        "boarding raises the owning agent's portfolio_merchant_count by one, got "
        f"{stored_agent['portfolio_merchant_count']}"
    )

    stored_program = validate_success(
        api_client.get_processor_program(program["id"], ADMIN_ONE), 200
    )
    assert stored_program["minimum_billing_mode"] == "SHORTFALL_BILLED", (
        "an omitted minimum_billing_mode defaults to SHORTFALL_BILLED, got "
        f"{stored_program['minimum_billing_mode']!r}"
    )


def test_computed_hierarchy_and_portfolio_fields_derive_from_related_rows():
    """Its `hierarchy_depth` is 0 when no parent was named, and otherwise one greater than the parent's `hierarchy_depth`.

    `portfolio_merchant_count` is the broader count of the agent's merchants in
    any of `PENDING`, `ACTIVE` or `ATTRITED`

    `vested_pct` evaluated immediately against the vesting schedule and the
    logical clock

    Design: Corner/entities/computed_hierarchy_and_portfolio_fields_derive_from_related_rows
    """
    program = validate_success(
        api_client.create_processor_program(create_processor_program_payload(), ADMIN_ONE), 201
    )
    a1 = validate_success(
        api_client.create_agent(
            create_agent_payload(
                name="A1 Principal",
                split_pct=0.30,
                override_pct=0.55,
                vesting_start_date="2024-01-15",
            ),
            ADMIN_ONE,
        ),
        201,
    )
    a2 = validate_success(
        api_client.create_agent(
            create_agent_payload(
                name="A2 Regional",
                split_pct=0.40,
                override_pct=0.50,
                vesting_start_date="2025-01-15",
                parent_agent_id=a1["id"],
            ),
            ADMIN_ONE,
        ),
        201,
    )
    a3 = validate_success(
        api_client.create_agent(
            create_agent_payload(
                name="A3 Rep",
                split_pct=0.45,
                override_pct=0.45,
                vesting_start_date="2026-02-01",
                parent_agent_id=a2["id"],
            ),
            ADMIN_ONE,
        ),
        201,
    )

    active_merchant = validate_success(
        api_client.create_merchant(
            create_merchant_payload(
                a3["id"],
                program["id"],
                mid="MID-1001",
                monthly_minimum_cents=2500,
                per_transaction_fee_cents=15,
                equipment_lease_monthly_cents=3900,
                boarded_on="2026-04-10",
            ),
            ADMIN_ONE,
        ),
        201,
    )
    validate_success(
        api_client.create_merchant(
            create_merchant_payload(
                a3["id"],
                program["id"],
                mid="MID-1002",
                monthly_minimum_cents=2500,
                per_transaction_fee_cents=20,
                equipment_lease_monthly_cents=0,
                boarded_on="2026-06-01",
            ),
            ADMIN_ONE,
        ),
        201,
    )
    validate_success(api_client.activate_merchant(active_merchant["id"], ADMIN_ONE), 200)

    stored_a1 = validate_success(api_client.get_agent(a1["id"], ADMIN_ONE), 200)
    stored_a2 = validate_success(api_client.get_agent(a2["id"], ADMIN_ONE), 200)
    stored_a3 = validate_success(api_client.get_agent(a3["id"], ADMIN_ONE), 200)

    assert stored_a1["hierarchy_depth"] == 0, (
        f"A1 has no parent, so hierarchy_depth is 0, got {stored_a1['hierarchy_depth']}"
    )
    assert stored_a2["hierarchy_depth"] == 1, (
        f"A2 sits one hop below A1, expected 1, got {stored_a2['hierarchy_depth']}"
    )
    assert stored_a3["hierarchy_depth"] == 2, (
        f"A3 sits two hops below A1, expected 2, got {stored_a3['hierarchy_depth']}"
    )

    assert stored_a3["portfolio_merchant_count"] == 2, (
        "one ACTIVE plus one PENDING merchant counts as 2, got "
        f"{stored_a3['portfolio_merchant_count']}"
    )
    assert stored_a3["portfolio_attrition_bps"] == 0, (
        "no merchant has attrited, so the rate is 0, got "
        f"{stored_a3['portfolio_attrition_bps']}"
    )
    assert stored_a3["residual_hold"] is False, (
        "a zero attrition rate leaves residual_hold false, got "
        f"{stored_a3['residual_hold']!r}"
    )
    assert stored_a1["portfolio_merchant_count"] == 0, (
        "the count is per owning agent, not per subtree, so A1 owns 0 merchants, got "
        f"{stored_a1['portfolio_merchant_count']}"
    )

    assert stored_a1["vested_pct"] == 50, (
        f"A1 anchored 2024-01-15 vests at 50 against the 2026-08-01 clock, got "
        f"{stored_a1['vested_pct']}"
    )
    assert stored_a2["vested_pct"] == 25, (
        f"A2 anchored 2025-01-15 vests at 25, got {stored_a2['vested_pct']}"
    )
    assert stored_a3["vested_pct"] == 0, (
        f"A3 anchored 2026-02-01 is still inside the twelve-month cliff, got "
        f"{stored_a3['vested_pct']}"
    )

    assert stored_a3["trailing_residual_cents"] == 0, (
        f"no statement exists yet, got {stored_a3['trailing_residual_cents']}"
    )
    assert stored_a3["advance_outstanding_cents"] == 0, (
        f"no advance was funded, got {stored_a3['advance_outstanding_cents']}"
    )
    assert stored_a3["lifetime_clawback_cents"] == 0, (
        f"no clawback has been applied, got {stored_a3['lifetime_clawback_cents']}"
    )
    for agent in (stored_a1, stored_a2, stored_a3):
        assert_agent(agent)


def test_system_fields_are_server_managed_across_a_patch():
    """Most resources additionally carry `updated_at` — same format as `created_at`, refreshed on every mutation — and `version`, an integer that starts at 1 on creation and increments by exactly 1 on every mutation of that row.

    Design: Corner/entities/system_fields_are_server_managed_across_a_patch
    """
    created = validate_success(
        api_client.create_agent(
            create_agent_payload(
                name="A1 Principal",
                split_pct=0.30,
                override_pct=0.55,
                vesting_start_date="2024-01-15",
            ),
            ADMIN_ONE,
        ),
        201,
    )
    assert created["version"] == 1, (
        f"version starts at 1 on creation, got {created['version']}"
    )

    set_logical_clock("2026-08-15T12:00:00Z", ADMIN_ONE)

    patched = validate_success(
        api_client.update_agent(
            created["id"], {"name": "A1 Principal Renamed", "split_pct": 0.35}, ADMIN_ONE
        ),
        200,
    )

    assert patched["id"] == created["id"], (
        f"the server-minted id survives a patch untouched, got {patched['id']!r}"
    )
    assert patched["created_at"] == created["created_at"], (
        "created_at records when the row was first written and never moves, got "
        f"{patched['created_at']!r} instead of {created['created_at']!r}"
    )
    assert patched["version"] == 2, (
        f"one mutation advances version by exactly 1, expected 2, got {patched['version']}"
    )
    assert patched["updated_at"] > patched["created_at"], (
        "updated_at is refreshed to the current logical instant, which is now later than "
        f"created_at; got updated_at {patched['updated_at']!r} and created_at "
        f"{patched['created_at']!r}"
    )

    assert patched["name"] == "A1 Principal Renamed", (
        f"the amended name must be stored, got {patched['name']!r}"
    )
    assert _pct(patched["split_pct"]) == 0.35, (
        f"split_pct was amended to 0.35, got {patched['split_pct']!r}"
    )
    assert _pct(patched["override_pct"]) == _pct(created["override_pct"]), (
        f"override_pct was not part of the patch, got {patched['override_pct']!r}"
    )
    assert patched["vesting_start_date"] == created["vesting_start_date"], (
        f"vesting_start_date was not part of the patch, got {patched['vesting_start_date']!r}"
    )
    assert_agent(patched)


def test_enum_and_numeric_domain_violations_reported_per_band():
    """`split_pct`, `override_pct` and `recoupment_pct` must be decimal fractions inside the closed interval from 0 through 1 inclusive; a value outside that interval yields `ERR_INVALID_PCT_RANGE` (422) on agent creation, agent amendment and advance funding.

    every enum-typed field carries a value drawn from that field's declared set

    Separately, every accounting-month input must match the exact
    four-digit-year, hyphen, two-digit-month shape with the month between 01 and
    12 inclusive; a malformed value yields `ERR_INVALID_PERIOD_MONTH` (422) on
    batch ingest, on chargeback booking, and on the `first_recoupment_month` and
    `last_recoupment_month` of an advance.

    Design: Corner/entities/enum_and_numeric_domain_violations_reported_per_band
    """
    program = validate_success(
        api_client.create_processor_program(create_processor_program_payload(), ADMIN_ONE), 201
    )

    validate_error(
        api_client.create_processor_program(
            create_processor_program_payload(
                name="Bad Mode", normalization_mode="NETT_REVENUE"
            ),
            ADMIN_ONE,
        ),
        ApiErrorId.ERR_INVALID_REQUEST.value,
    )

    validate_error(
        api_client.create_agent(
            create_agent_payload(
                name="Over Split",
                split_pct=1.5,
                override_pct=0.55,
                vesting_start_date="2024-01-15",
            ),
            ADMIN_ONE,
        ),
        ApiErrorId.ERR_INVALID_PCT_RANGE.value,
    )

    validate_error(
        api_client.create_residual_batch(
            create_residual_batch_payload(
                program["id"],
                period_month="2026-13",
                coverage_start="2026-07-01",
                coverage_end="2026-08-01",
                file_checksum="sha256:dom-0001",
            ),
            ANALYST_ONE,
        ),
        ApiErrorId.ERR_INVALID_PERIOD_MONTH.value,
    )

    _, program_meta = validate_paginated(api_client.list_processor_programs(ADMIN_ONE, {}))
    assert program_meta["total_count"] == 1, (
        f"only the setup program may exist, got {program_meta['total_count']}"
    )
    _, agent_meta = validate_paginated(api_client.list_agents(ADMIN_ONE, {}))
    assert agent_meta["total_count"] == 0, (
        f"the refused agent creation wrote nothing, got {agent_meta['total_count']}"
    )
    _, batch_meta = validate_paginated(api_client.list_residual_batches(ANALYST_ONE, {}))
    assert batch_meta["total_count"] == 0, (
        f"the refused batch ingest wrote nothing, got {batch_meta['total_count']}"
    )


def test_chargeback_event_is_append_only_with_no_version():
    """Both `updated_at` and `version` are absent from a `ChargebackEvent` — not null, absent.

    Design: Corner/entities/chargeback_event_is_append_only_with_no_version
    """
    program = validate_success(
        api_client.create_processor_program(create_processor_program_payload(), ADMIN_ONE), 201
    )
    agent = validate_success(
        api_client.create_agent(
            create_agent_payload(split_pct=0.45, override_pct=0.45), ADMIN_ONE
        ),
        201,
    )
    merchant = validate_success(
        api_client.create_merchant(
            create_merchant_payload(agent["id"], program["id"], mid="MID-1001"), ADMIN_ONE
        ),
        201,
    )
    validate_success(api_client.activate_merchant(merchant["id"], ADMIN_ONE), 200)

    july = validate_success(
        api_client.create_chargeback_event(
            merchant["id"],
            create_chargeback_payload(
                amount_cents=4500,
                occurred_on="2026-07-12",
                period_month="2026-07",
                liability="AGENT_CHARGED",
            ),
            ANALYST_ONE,
        ),
        201,
    )
    june = validate_success(
        api_client.create_chargeback_event(
            merchant["id"],
            create_chargeback_payload(
                amount_cents=9900,
                occurred_on="2026-06-30",
                period_month="2026-06",
                liability="ISO_ABSORBED",
            ),
            ANALYST_ONE,
        ),
        201,
    )

    for event in (july, june):
        assert "version" not in event, (
            f"a chargeback event must not carry version, got {event.get('version')!r}"
        )
        assert "updated_at" not in event, (
            f"a chargeback event must not carry updated_at, got {event.get('updated_at')!r}"
        )
        assert is_valid_uuid(event["id"]), f"id must be a UUID, got {event['id']!r}"
        assert event["created_at"], "created_at must be present on an append-only event"
        assert_chargeback_event(event)

    read = validate_success(api_client.get_chargeback_event(july["id"], ANALYST_ONE), 200)
    assert read["amount_cents"] == 4500, (
        f"amount_cents expected 4500, got {read['amount_cents']}"
    )
    assert read["liability"] == "AGENT_CHARGED", (
        f"liability expected AGENT_CHARGED, got {read['liability']!r}"
    )
    assert read["period_month"] == "2026-07", (
        f"period_month expected 2026-07, got {read['period_month']!r}"
    )
    assert read["merchant_id"] == merchant["id"], (
        "the event must point back at the merchant it was booked against"
    )
    assert "version" not in read and "updated_at" not in read, (
        "the read path must not invent version or updated_at for a chargeback event"
    )

    filtered_rows, filtered_meta = validate_paginated(
        api_client.list_chargeback_events(
            ANALYST_ONE, {"merchant_id": merchant["id"], "period_month": "2026-07"}
        )
    )
    assert filtered_meta["total_count"] == 1, (
        "period_month matches by exact equality, so only the July event qualifies; got "
        f"{filtered_meta['total_count']}"
    )
    assert [row["id"] for row in filtered_rows] == [july["id"]], (
        f"the June event must be filtered out, got {[row['id'] for row in filtered_rows]}"
    )

    _, merchant_meta = validate_paginated(
        api_client.list_chargeback_events(ANALYST_ONE, {"merchant_id": merchant["id"]})
    )
    assert merchant_meta["total_count"] == 2, (
        f"both events remain readable under the merchant filter, got {merchant_meta['total_count']}"
    )


def test_body_foreign_keys_are_validated_before_state_rules():
    """An agent reference that names no agent — `parent_agent_id` on agent creation or amendment, `owning_agent_id` on merchant boarding, `new_agent_id` on reassignment, `target_agent_id` on portfolio transfer — yields `ERR_REFERENCED_AGENT_NOT_FOUND` (404).

    A `processor_program_id` that names no program, whether on merchant boarding or
    on batch ingest, yields `ERR_REFERENCED_PROGRAM_NOT_FOUND` (404). A merchant
    reference that names no merchant — `merchant_id` on a residual line,
    `source_merchant_id` on an adjustment proposal — yields
    `ERR_REFERENCED_MERCHANT_NOT_FOUND` (404).

    Design: Corner/entities/body_foreign_keys_are_validated_before_state_rules
    """
    program = validate_success(
        api_client.create_processor_program(create_processor_program_payload(), ADMIN_ONE), 201
    )
    agent = validate_success(
        api_client.create_agent(
            create_agent_payload(split_pct=0.45, override_pct=0.45), ADMIN_ONE
        ),
        201,
    )
    batch = validate_success(
        api_client.create_residual_batch(
            create_residual_batch_payload(
                program["id"],
                period_month="2026-07",
                coverage_start="2026-07-01",
                coverage_end="2026-08-01",
                file_checksum="sha256:fk-0001",
            ),
            ANALYST_ONE,
        ),
        201,
    )
    assert batch["state"] == "RECEIVED", (
        f"an ingested batch starts RECEIVED, got {batch['state']!r}"
    )

    validate_error(
        api_client.create_merchant(
            create_merchant_payload(UNKNOWN_ID, program["id"], mid="MID-1001"), ADMIN_ONE
        ),
        ApiErrorId.ERR_REFERENCED_AGENT_NOT_FOUND.value,
    )

    validate_error(
        api_client.create_merchant(
            create_merchant_payload(agent["id"], UNKNOWN_ID, mid="MID-1002"), ADMIN_ONE
        ),
        ApiErrorId.ERR_REFERENCED_PROGRAM_NOT_FOUND.value,
    )

    validate_error(
        api_client.create_residual_line(
            batch["id"],
            create_residual_line_payload(
                UNKNOWN_ID,
                transaction_count=10,
                sales_volume_cents=1000,
                interchange_cents=10,
                assessments_cents=1,
                gross_income_cents=100,
            ),
            ANALYST_ONE,
        ),
        ApiErrorId.ERR_REFERENCED_MERCHANT_NOT_FOUND.value,
    )

    _, merchant_meta = validate_paginated(api_client.list_merchants(ADMIN_ONE, {}))
    assert merchant_meta["total_count"] == 0, (
        f"no merchant may be written by a refused boarding, got {merchant_meta['total_count']}"
    )
    stored_batch = validate_success(api_client.get_residual_batch(batch["id"], ANALYST_ONE), 200)
    assert stored_batch["line_count"] == 0, (
        f"the refused append left no line behind, got line_count {stored_batch['line_count']}"
    )
    _, line_meta = validate_paginated(
        api_client.list_residual_lines(ANALYST_ONE, {"residual_batch_id": batch["id"]})
    )
    assert line_meta["total_count"] == 0, (
        f"no residual line row exists for the batch, got {line_meta['total_count']}"
    )
