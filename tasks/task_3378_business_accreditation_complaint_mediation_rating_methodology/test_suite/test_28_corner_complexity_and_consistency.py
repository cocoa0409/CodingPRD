"""Corner queue — complexity layers and consistency: rating-dispute OCC
(PRD §2.8), the pinned logical-clock default (PRD §2.4), derived scam-count
reconciliation as the window slides (PRD §3.6/§3.8), and immediate
accreditation visibility on full payment (PRD §3.3)."""

from test_helpers import (
    ApiErrorId,
    CLOCK_START_ISO,
    TEST_USERS,
    compute_snapshot,
    create_bureau,
    create_business,
    create_consumer,
    create_rating_dispute_payload,
    create_rating_snapshot_payload,
    file_complaint,
    file_scam_report,
    get_business,
    ledger_entry_payload,
    make_business_rep_headers,
    parse_iso,
    publish_scam_report,
    set_clock,
    setup_approved_application,
    validate_success,
    validate_error,
    validate_paginated,
)

ADMIN = TEST_USERS["bureau_admin_headers"]


def test_rating_dispute_occ_stale_version_rejected_fresh_accepted(api):
    """PRD §2.8: "The request must carry `expected_business_version`, a
    non-optional field holding the `version` of the Business as the client
    last observed it. If the business's current `version` differs — because,
    for example, a new published snapshot or an appeal recomputation has
    advanced it since the client read the rating — the filing is rejected
    with `ERR_STALE_VERSION` (HTTP 412)."
    PRD §3.7: "Filing commits the dispute directly into `UNDER_APPEAL_REVIEW`
    — `FILED` is a zero-duration state, entered and left within the act of
    creation — stamps `filed_at`, and increments the business's `version` by
    1."

    Design: Corner/complexity_layers/rating_dispute_occ_stale_version_rejected_fresh_version_accepted
    """
    set_clock(CLOCK_START_ISO)
    create_bureau(name="Heartland Bureau", territory_state_codes=["IA", "NE"],
                  local_dues_fee_cents=0)
    business = create_business(legal_name="BigBox Services Inc",
                               home_state_code="IA", employee_count=250,
                               founded_on="2018-01-01T00:00:00Z")
    stale_version = business["version"]
    # Publishing advances Business.version (PRD §3.7), superseding the view.
    snap = compute_snapshot(business, variant="PUBLISHED")
    assert get_business(business["id"])["version"] == stale_version + 1

    resp = api.create_rating_dispute(
        business["id"],
        create_rating_dispute_payload(
            snapshot_id=snap["id"], expected_business_version=stale_version,
            reason="stale view"),
        make_business_rep_headers(business["id"]))
    validate_error(resp, ApiErrorId.ERR_STALE_VERSION)

    fresh_version = get_business(business["id"])["version"]
    resp = api.create_rating_dispute(
        business["id"],
        create_rating_dispute_payload(
            snapshot_id=snap["id"], expected_business_version=fresh_version,
            reason="fresh view"),
        make_business_rep_headers(business["id"]))
    dispute = validate_success(resp, 201)
    assert dispute["status"] == "UNDER_APPEAL_REVIEW"
    assert get_business(business["id"])["version"] == fresh_version + 1, \
        "the filing itself advances the business version"


def test_logical_clock_defaults_to_pinned_start_without_any_set_call(api):
    """PRD §2.4: "At startup, before any clock operation has been issued, the
    logical clock reads exactly 2026-09-01T00:00:00Z, and it never falls back
    to the host's wall clock."

    Design: Corner/complexity_layers/logical_clock_defaults_to_pinned_start_without_any_set_call
    """
    # No POST /_clock/set_current_utc anywhere in this test.
    bureau = create_bureau(name="Heartland Bureau",
                           territory_state_codes=["IA", "NE"],
                           local_dues_fee_cents=0)
    consumer = create_consumer(full_name="Pat Consumer",
                               email="pat@example.com", home_state_code="IA")
    business = create_business(legal_name="BigBox Services Inc",
                               home_state_code="IA", employee_count=250,
                               founded_on="2018-01-01T00:00:00Z")
    complaint = file_complaint(consumer, business)
    pinned = parse_iso("2026-09-01T00:00:00Z")
    assert parse_iso(complaint["filed_at"]) == pinned
    assert parse_iso(business["created_at"]) == pinned
    assert parse_iso(bureau["created_at"]) == pinned


def test_scam_report_aging_out_reconciles_derived_count_and_deduction(api):
    """PRD §3.8: "the business's `published_scam_count_12m` (the count of its
    `PUBLISHED` reports whose `published_at` falls within the trailing 365
    days) recomputes"
    PRD §3.6: "`scam_deduction` is 10 points when `published_scam_count_12m`
    is 3 or more, and 0 points otherwise."

    Design: Corner/complexity_layers/scam_report_aging_out_reconciles_derived_count_and_deduction
    """
    set_clock(CLOCK_START_ISO)
    create_bureau(name="Heartland Bureau", territory_state_codes=["IA", "NE"],
                  local_dues_fee_cents=0)
    consumer = create_consumer(full_name="Pat Consumer",
                               email="pat@example.com", home_state_code="IA")
    business = create_business(legal_name="BigBox Services Inc",
                               home_state_code="IA", employee_count=250,
                               founded_on="2018-01-01T00:00:00Z")
    publish_scam_report(file_scam_report(consumer, business))
    assert get_business(business["id"])["published_scam_count_12m"] == 1
    # 2027-09-02: the 2026-09-01 publication has left the trailing 365 days.
    set_clock("2027-09-02T00:00:00Z")
    assert get_business(business["id"])["published_scam_count_12m"] == 0
    resp = api.create_rating_snapshot(
        business["id"], create_rating_snapshot_payload("PROVISIONAL"), ADMIN)
    snap = validate_success(resp, 201)
    assert snap["scam_deduction"] == 0
    assert snap["score"] == 100
    assert snap["grade"] == "A_PLUS"
    patterns = validate_success(api.list_scam_patterns(ADMIN), 200)["patterns"]
    assert all(p["business_id"] != business["id"] for p in patterns)


def test_full_payment_immediately_reflects_accreditation_everywhere(api):
    """PRD §3.3: "A payment that exactly covers the balance moves the invoice
    to `PAID` with `balance_cents` at 0 — and this is the moment accreditation
    lands: the linked application advances from `APPROVED_PENDING_DUES` to
    `ACCREDITED`, the business's `accreditation_status` moves from
    `NOT_ACCREDITED` to `ACCREDITED` (or, for a business recovering from
    suspension, from `SUSPENDED` back to `ACCREDITED`), and the business's
    `version` increments by 1."

    Design: Corner/consistency_model/full_payment_immediately_reflects_accreditation_everywhere
    """
    set_clock(CLOCK_START_ISO)
    create_bureau(name="Heartland Bureau", territory_state_codes=["IA", "NE"],
                  local_dues_fee_cents=0)
    business = create_business(legal_name="Consistency Micro LLC",
                               home_state_code="IA", employee_count=2,
                               founded_on="2020-01-01T00:00:00Z")
    app, invoice = setup_approved_application(business)
    version_before = get_business(business["id"])["version"]
    resp = api.post_ledger_entry(
        invoice["id"], ledger_entry_payload("PAYMENT", 40375),
        make_business_rep_headers(business["id"]))
    paid = validate_success(resp, 201)
    assert paid["status"] == "PAID" and paid["balance_cents"] == 0
    # No daily close in between: the cascade is visible on the next reads.
    rows, _meta = validate_paginated(api.list_accreditation_applications(
        business["id"], make_business_rep_headers(business["id"])))
    current = [r for r in rows if r["id"] == app["id"]][0]
    assert current["status"] == "ACCREDITED"
    mirror = get_business(business["id"])
    assert mirror["accreditation_status"] == "ACCREDITED"
    assert mirror["version"] == version_before + 1
