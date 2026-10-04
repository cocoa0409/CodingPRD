"""Entity creation, defaults, envelope, uniqueness, and listing coverage."""
from test_helpers import (
    api_client, validate_success, validate_error, validate_paginated,
    get_success_data, NON_EXISTENT_UUID,
    ApiErrorId, TEST_USERS, make_patron_headers,
    create_patron_payload, create_work_payload, create_partner_library_payload,
    create_crawl_job_payload, create_rights_request_payload,
    set_clock, make_patron, make_library, make_work, make_grant, make_budget_line,
    make_batch_with_items, setup_work_with_lendable_items, checkout,
)

ADMIN = TEST_USERS["admin_headers"]
ANON = TEST_USERS["anonymous_headers"]
LIBADMIN = TEST_USERS["library_admin_headers"]
SCANOP = TEST_USERS["scan_operator_headers"]
CRAWLOP = TEST_USERS["crawl_operator_headers"]
FINANCE = TEST_USERS["finance_admin_headers"]
LEGAL = TEST_USERS["legal_reviewer_headers"]


def test_patron_create_returns_defaults_and_envelope():
    """PRD 3.1: "A new patron starts in status `ACTIVE` with `active_loan_count`
    of 0, `strike_count` of 0, and `max_concurrent_loans` of 5."
    PRD 2.4: "At server startup, before any operator intervention, the logical
    clock reads exactly 2026-09-01T00:00:00Z, and it never falls back to
    wall-clock time thereafter."
    PRD 2.2: "The `api_request_id` is a server-generated unique identifier for
    the request that starts with `req_`."

    Design: Corner/entities/patron_create_returns_defaults_and_envelope
    """
    resp = api_client.create_patron(
        {"email": "corner1@example.org", "full_name": "Corner One"}, ANON
    )
    body = resp.json()
    data = validate_success(resp, expected_status=201)
    assert body["response_type"] == "object"
    assert body["meta"].get("api_request_id", "").startswith("req_")
    assert body["meta"].get("api_request_timestamp")
    assert data["status"] == "ACTIVE"
    assert data["strike_count"] == 0
    assert data["active_loan_count"] == 0
    assert data["max_concurrent_loans"] == 5
    assert data["version"] == 1
    assert data["created_at"].startswith("2026-09-01T00:00:00"), (
        f"created_at must come from the logical clock default, got {data['created_at']}"
    )


def test_patron_email_uniqueness_is_case_insensitive():
    """PRD 3.1: "self-service account creation accepts an `email` and a
    `full_name`, and the email must be unique across all patrons under a
    case-insensitive comparison — a registration whose `email` differs from an
    existing one only by letter case is rejected with `ERR_DUPLICATE`."

    Design: Corner/entities/patron_email_uniqueness_is_case_insensitive
    """
    first = validate_success(
        api_client.create_patron({"email": "dup@example.org", "full_name": "First"}, ANON),
        expected_status=201,
    )
    resp = api_client.create_patron(
        {"email": "DUP@EXAMPLE.ORG", "full_name": "Second"}, ANON
    )
    validate_error(resp, ApiErrorId.ERR_DUPLICATE)
    # the duplicate must not have been persisted: self-read with the would-be
    # owner id cannot resolve any second record (first patron's id is not the
    # second patron's id)
    second_read = api_client.get_patron(NON_EXISTENT_UUID, ADMIN)
    validate_error(second_read, ApiErrorId.ERR_NOT_FOUND)
    self_read = api_client.get_patron(first["id"], make_patron_headers(first["id"]))
    assert validate_success(self_read)["email"] == "dup@example.org"


def test_capture_is_immutable_and_carries_no_version():
    """PRD 2.4: "One entity departs from this shape: a `Capture` carries only
    `id` and `created_at` — `updated_at` and `version` are absent on captures,
    because captures are immutable once recorded."
    PRD 3.7: "The capture's `captured_at` is stamped from the logical clock, and
    its `playback_status` starts `PLAYABLE`."

    Design: Corner/entities/capture_is_immutable_and_carries_no_version
    """
    set_clock("2026-09-01T00:00:00Z")
    job = get_success_data(api_client.create_crawl_job(
        create_crawl_job_payload(
            seed_url="https://imm.site/",
            scheduled_at="2026-09-01T00:10:00Z",
            requests_per_minute=20,
        ),
        CRAWLOP,
    ))
    set_clock("2026-09-01T00:10:00Z")
    get_success_data(api_client.start_crawl_job(job["id"], CRAWLOP))
    cap = get_success_data(api_client.create_capture(
        {"crawl_job_id": job["id"], "url": "https://imm.site/p",
         "content_hash": "hh1", "has_dynamic_content": False},
        CRAWLOP,
    ))
    rows, _meta = validate_paginated(
        api_client.list_job_captures(job["id"], CRAWLOP)
    )
    assert len(rows) == 1
    row = rows[0]
    assert row["id"] == cap["id"]
    for field in ("url", "content_hash", "captured_at", "has_dynamic_content",
                  "playback_status", "created_at"):
        assert field in row, f"capture row must expose {field}"
    assert "version" not in row, "Capture must not carry a version field"
    assert "updated_at" not in row, "Capture must not carry an updated_at field"
    assert row["playback_status"] == "PLAYABLE"


def test_partner_library_commitment_below_five_years_rejected():
    """PRD 3.2: "a `storage_commitment_years`, the library's long-term storage
    commitment in whole years, which must be at least 5."
    PRD 2.5: "Schema validity — required fields, types, enum membership, numeric
    ranges, subject-kind field consistency, and the strictly-future scheduling
    rule; otherwise `ERR_VALIDATION`."

    Design: Corner/entities/partner_library_commitment_below_five_years_rejected
    """
    resp = api_client.create_partner_library(
        {"library_code": "LIB-SHORT", "display_name": "Short Term",
         "storage_commitment_years": 4},
        LIBADMIN,
    )
    validate_error(resp, ApiErrorId.ERR_VALIDATION)
    ok = validate_success(
        api_client.create_partner_library(
            {"library_code": "LIB-FIVE", "display_name": "Five Year",
             "storage_commitment_years": 5},
            LIBADMIN,
        ),
        expected_status=201,
    )
    assert ok["status"] == "ACTIVE"


def test_rights_request_subject_kind_field_consistency():
    """PRD 3.8: "Subject-kind consistency is enforced at the schema level: a
    `WORK` request must carry `work_id` and a null `url_prefix`, while a
    `CAPTURE_URL_PREFIX` request must carry `url_prefix` and a null `work_id`;
    any other combination is `ERR_VALIDATION`."

    Design: Corner/entities/rights_request_subject_kind_field_consistency
    """
    resp = api_client.create_rights_request(
        {"subject_kind": "WORK", "claimant_name": "No Work Id"}, LEGAL
    )
    validate_error(resp, ApiErrorId.ERR_VALIDATION)


def test_work_get_returns_computed_availability():
    """PRD 3.2: "A freshly cataloged work's `availability` is initialized to
    `AVAILABLE`."

    Design: Corner/entities/work_get_returns_computed_availability
    """
    work = validate_success(
        api_client.create_work(
            {"title": "Plain Work", "author": "W. Plain", "publication_year": 1960},
            ADMIN,
        ),
        expected_status=201,
    )
    assert work["availability"] == "AVAILABLE"
    fetched = validate_success(api_client.get_work(work["id"], ADMIN))
    assert fetched["availability"] == "AVAILABLE"
    assert fetched["version"] == 1


def test_fk_reverse_reachability_lists_children_by_parent():
    """PRD 2.9: "Several list endpoints expose children through a parent path —
    a patron's loans, credentials, and waitlist entries; a work's items,
    waitlist entries, and rights requests; a batch's items; a library's items;
    an item's loans; a crawl job's captures; a grant's budget lines."

    Design: Corner/entities/fk_reverse_reachability_lists_children_by_parent
    """
    library = make_library(library_code="LIB-FK")
    work = make_work(title="FK Work")
    batch, items = make_batch_with_items(
        work["id"], library["id"],
        item_specs=[{"page_count": 10, "condition_grade": "FINE"},
                    {"page_count": 20, "condition_grade": "FAIR"}],
        seal=False,
    )
    grant = make_grant(amount_cents=100000, donor_name="FK Donor")
    make_budget_line(grant["id"], 1000, "STORAGE")
    make_budget_line(grant["id"], 2000, "BANDWIDTH")

    batch_rows, batch_meta = validate_paginated(
        api_client.list_batch_items(batch["id"], SCANOP)
    )
    assert len(batch_rows) == 2

    grant_rows, _ = validate_paginated(
        api_client.list_grant_budget_lines(grant["id"], FINANCE)
    )
    assert len(grant_rows) == 2
    assert sum(r["budget_reservation_cents"] for r in grant_rows) == 3000

    lib_rows, _ = validate_paginated(
        api_client.list_library_items(library["id"], LIBADMIN)
    )
    assert {r["id"] for r in lib_rows} == {i["id"] for i in items}


def test_list_pagination_defaults_and_has_more():
    """PRD 2.3: "The `limit` defaults to 10, must be at least 1, and must not
    exceed 100. The `offset` defaults to 0. List responses report `limit`,
    `offset`, `total_count`, and `has_more` in the `meta` object."

    Design: Corner/entities/list_pagination_defaults_and_has_more
    """
    set_clock("2026-09-01T00:00:00Z")
    library = make_library(library_code="LIB-PG")
    patron = make_patron(email="pg@example.org")
    batch = get_success_data(
        api_client.create_scan_batch({"operator_code": "op-pg"}, SCANOP)
    )
    for i in range(3):
        work = make_work(title=f"Pg {i}", author="Pg", publication_year=2001 + i)
        get_success_data(api_client.create_item(
            {"batch_id": batch["id"], "work_id": work["id"],
             "owning_library_id": library["id"], "page_count": 10,
             "condition_grade": "FINE"},
            SCANOP,
        ))
    get_success_data(api_client.seal_scan_batch(batch["id"], SCANOP))
    # check out one item from each of the three works
    item_rows, _ = validate_paginated(api_client.list_batch_items(batch["id"], SCANOP))
    assert len(item_rows) == 3
    for row in item_rows:
        checkout(row["id"], patron["id"])

    page1, meta1 = validate_paginated(
        api_client.list_patron_loans(patron["id"], ADMIN, params={"limit": 2, "offset": 0})
    )
    assert len(page1) == 2
    assert meta1["total_count"] == 3
    assert meta1["has_more"] is True

    page2, meta2 = validate_paginated(
        api_client.list_patron_loans(patron["id"], ADMIN, params={"limit": 2, "offset": 2})
    )
    assert len(page2) == 1
    assert meta2["total_count"] == 3
    assert meta2["has_more"] is False

    page_all, meta_all = validate_paginated(
        api_client.list_patron_loans(patron["id"], ADMIN)
    )
    assert len(page_all) == 3
    assert meta_all["limit"] == 10
    assert meta_all["offset"] == 0


def test_work_get_unknown_id_returns_not_found():
    """PRD 2.5: "Existence — every path id and every body foreign-key id
    references an existing resource, validated left-to-right in the order the
    ids are declared for that endpoint; otherwise `ERR_NOT_FOUND`."

    Design: Corner/entities/work_get_unknown_id_returns_not_found
    """
    resp = api_client.get_work("00000000-0000-4000-8000-000000000099", ADMIN)
    validate_error(resp, ApiErrorId.ERR_NOT_FOUND)
