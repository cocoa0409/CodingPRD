"""Driver identities, master-record claims (OCC + one-driver-one-record),
conviction posting, points windows, and the timeliness score."""

from test_helpers import (
    ASSOCIATION_ADMIN_HEADERS,
    AUDIT_AUTHORITY_HEADERS,
    DEFAULT_CLOCK_ISO,
    FEDERAL_VERIFIER_HEADERS,
    NON_EXISTENT_UUID,
    TIMELINESS_SCORE_FULL_BP,
    ApiErrorId,
    assert_conviction,
    assert_driver_identity,
    assert_error,
    assert_list_page,
    assert_ok,
    claim_driver_record,
    complete_transfer,
    conviction_payload,
    create_jurisdiction,
    current_driver_version,
    driver_record_payload,
    expected_dq_window,
    initiate_transfer,
    issue_license,
    list_driver_records,
    make_jurisdiction_registrar_headers,
    post_conviction,
    read_driver,
    read_jurisdiction,
    read_license,
    read_record,
    read_record_disqualifications,
    register_driver,
    setup_certified_jurisdiction,
    setup_conviction_world,
    setup_driver_record,
    setup_verified_license,
    surrender_transfer,
    verify_license,
)


def test_driver_create_and_retrieval(api):
    """PRD §3.3: "A `JurisdictionRegistrar` registers one with a `full_name`, a
    `date_of_birth`, an `ssn_last4_hash` — the salted hash of the social security
    number's last four digits against which the verification services later match — and
    a `lawful_status_basis` of `US_CITIZEN`, `PERMANENT_RESIDENT`, or
    `TEMPORARY_STATUS`."

    Design: Corner/entities/driver_create_and_retrieval
    """
    jurisdiction = create_jurisdiction(api, code="AA", name="State A")
    driver = register_driver(
        api,
        jurisdiction["id"],
        full_name="Round Trip",
        date_of_birth="1995-06-15",
        ssn_last4_hash="hRT1",
        lawful_status_basis="US_CITIZEN",
    )
    resp = api.get_driver(driver["id"], FEDERAL_VERIFIER_HEADERS)
    data = assert_ok(resp)
    assert_driver_identity(data)
    assert data["full_name"] == "Round Trip"
    assert data["date_of_birth"] == "1995-06-15"
    assert data["ssn_last4_hash"] == "hRT1"
    assert data["lawful_status_basis"] == "US_CITIZEN"


def test_conviction_is_immutable_event(api):
    """PRD §2.5: "The `Conviction` is the deliberate exception. Convictions are
    immutable once posted — never edited, never removed — so a conviction carries only
    `id` and `created_at`; both `updated_at` and `version` are absent from it."

    Design: Corner/entities/conviction_is_immutable_event
    """
    ctx = setup_conviction_world(api, code="AA")
    conviction = post_conviction(
        api,
        ctx["record_id"],
        ctx["jurisdiction_id"],
        offense_date="2026-08-10",
        conviction_date="2026-08-20",
        severity="NON_CMV",
        points=2,
    )
    # assert_conviction pins the full shape and the absence of updated_at/version.
    assert_conviction(conviction)
    for field in (
        "id",
        "created_at",
        "record_id",
        "offense_date",
        "conviction_date",
        "severity",
        "points",
        "posted_at",
        "is_late",
    ):
        assert field in conviction, f"conviction response carries {field}"


def test_driver_records_list_pagination(api):
    """PRD §2.3: "The `limit` parameter caps the number of items returned; it defaults
    to 10, with a minimum of 1 and a maximum of 100. The `offset` parameter skips a
    number of items from the front of the result set and defaults to 0."
    PRD §2.3: "Unless otherwise specified, every list endpoint returns its resources
    ordered by `created_at` ascending — a stable, deterministic order."
    PRD §2.3: "The `meta` object of a list response carries the pagination fields
    `limit`, `offset`, `total_count`, and `has_more`."

    Design: Corner/entities/driver_records_list_pagination
    """
    ctx = setup_certified_jurisdiction(api, code="AA", systems=("POINTER_NETWORK",))
    setup_driver_record(api, ctx, full_name="Page One", ssn_last4_hash="hPG1")
    record_one = ctx["record_id"]
    setup_driver_record(api, ctx, full_name="Page Two", ssn_last4_hash="hPG2")
    record_two = ctx["record_id"]

    resp1 = api.list_driver_records(
        ASSOCIATION_ADMIN_HEADERS, params={"limit": 1, "offset": 0}
    )
    rows1, meta1 = assert_list_page(resp1)
    assert len(rows1) == 1 and rows1[0]["id"] == record_one
    assert meta1["total_count"] == 2 and meta1["has_more"] is True
    assert meta1["limit"] == 1 and meta1["offset"] == 0

    resp2 = api.list_driver_records(
        ASSOCIATION_ADMIN_HEADERS, params={"limit": 1, "offset": 1}
    )
    rows2, meta2 = assert_list_page(resp2)
    assert len(rows2) == 1 and rows2[0]["id"] == record_two
    assert meta2["has_more"] is False and meta2["offset"] == 1


def test_driver_records_filtered_by_holding_jurisdiction(api):
    """PRD §3.3: "Records are inspectable singly or as lists filtered by `driver_id`,
    by `holding_jurisdiction_id`, or by both, and each record exposes its conviction
    history and its disqualification history as nested listings."

    Design: Corner/endpoints/driver_records_filtered_by_holding_jurisdiction
    """
    ctx_a = setup_certified_jurisdiction(api, code="AA", systems=("POINTER_NETWORK",))
    setup_driver_record(api, ctx_a, full_name="Filter One", ssn_last4_hash="hF01")
    record_a = ctx_a["record_id"]
    ctx_b = setup_certified_jurisdiction(api, code="BB", systems=("POINTER_NETWORK",))
    setup_driver_record(api, ctx_b, full_name="Filter Two", ssn_last4_hash="hF02")
    record_b = ctx_b["record_id"]

    rows, meta = list_driver_records(
        api, params={"holding_jurisdiction_id": ctx_a["jurisdiction_id"]}
    )
    assert meta["total_count"] == 1 and [r["id"] for r in rows] == [record_a]

    rows, meta = list_driver_records(api, params={"driver_id": ctx_b["driver_id"]})
    assert meta["total_count"] == 1 and [r["id"] for r in rows] == [record_b]
    assert rows[0]["holding_jurisdiction_id"] == ctx_b["jurisdiction_id"]


def test_record_claim_stale_driver_version_returns_412(api):
    """PRD §2.7: "A `POST /driver-exchange/driver-records` request must carry
    `expected_driver_version` equal to the driver identity's current `version`" and "If
    the driver identity's version has advanced since the client last read it — because
    another jurisdiction's record claim, or an earlier transfer initiation, legitimately
    became the driver's latest state — the request is rejected with `ERR_STALE_VERSION`
    (HTTP 412)".
    PRD §2.7: "On success, each of these two operations increments the driver identity's
    `version` by exactly one".

    Design: Corner/validations/record_claim_stale_driver_version_returns_412
    """
    ctx_a = setup_certified_jurisdiction(api, code="AA", systems=("POINTER_NETWORK",))
    ctx_b = setup_certified_jurisdiction(api, code="BB", systems=("POINTER_NETWORK",))
    driver = register_driver(api, ctx_a["jurisdiction_id"], full_name="Claimed Driver")
    observed_version = driver["version"]
    claim_driver_record(
        api, driver["id"], ctx_a["jurisdiction_id"], expected_driver_version=observed_version
    )

    resp = api.create_driver_record(
        driver_record_payload(driver["id"], observed_version),
        make_jurisdiction_registrar_headers(ctx_b["jurisdiction_id"]),
    )
    assert_error(resp, ApiErrorId.ERR_STALE_VERSION)

    assert read_driver(api, driver["id"])["version"] == observed_version + 1
    rows, meta = list_driver_records(api, params={"driver_id": driver["id"]})
    assert meta["total_count"] == 1
    assert rows[0]["holding_jurisdiction_id"] == ctx_a["jurisdiction_id"]


def test_record_already_held_with_fresh_version(api):
    """PRD §3.3: "And the one-driver-one-record invariant is absolute: if the driver
    already has an `ACTIVE` record in any jurisdiction, the claim is rejected with
    `ERR_RECORD_ALREADY_HELD`."

    Design: Corner/errors/record_already_held_with_fresh_version
    """
    ctx_a = setup_certified_jurisdiction(api, code="AA", systems=("POINTER_NETWORK",))
    ctx_b = setup_certified_jurisdiction(api, code="BB", systems=("POINTER_NETWORK",))
    driver = register_driver(api, ctx_a["jurisdiction_id"], full_name="Held Elsewhere")
    claim_driver_record(api, driver["id"], ctx_a["jurisdiction_id"])

    fresh_version = current_driver_version(api, driver["id"])
    resp = api.create_driver_record(
        driver_record_payload(driver["id"], fresh_version),
        make_jurisdiction_registrar_headers(ctx_b["jurisdiction_id"]),
    )
    assert_error(resp, ApiErrorId.ERR_RECORD_ALREADY_HELD)


def test_record_claim_unknown_driver_not_found(api):
    """PRD §2.6: "Path identifiers and body foreign keys must reference existing
    resources, validated left to right; the first missing reference yields the
    corresponding not-found error" — here `ERR_DRIVER_NOT_FOUND` (HTTP 404).

    Design: Corner/errors/record_claim_unknown_driver_not_found
    """
    jurisdiction = create_jurisdiction(api, code="AA", name="State A")
    driver = register_driver(api, jurisdiction["id"], full_name="Real Driver")
    resp = api.create_driver_record(
        driver_record_payload(NON_EXISTENT_UUID, driver["version"]),
        make_jurisdiction_registrar_headers(jurisdiction["id"]),
    )
    assert_error(resp, ApiErrorId.ERR_DRIVER_NOT_FOUND)


def test_record_claim_requires_active_jurisdiction(api):
    """PRD §3.3: "The claiming jurisdiction must be `ACTIVE` and hold a `CERTIFIED`
    `POINTER_NETWORK` participation, failures surfacing per the ladder's pinned
    sub-order as `ERR_JURISDICTION_NOT_ACTIVE` or `ERR_PARTICIPATION_NOT_CERTIFIED`."

    Design: Corner/errors/record_claim_requires_active_jurisdiction
    """
    # APPLIED jurisdiction whose POINTER_NETWORK participation is already CERTIFIED:
    # the membership gate fires even though the certification gate would pass.
    ctx = setup_certified_jurisdiction(
        api, code="AA", systems=("POINTER_NETWORK",), activate=False
    )
    driver = register_driver(api, ctx["jurisdiction_id"], full_name="Not Active Yet")
    resp = api.create_driver_record(
        driver_record_payload(driver["id"], driver["version"]),
        make_jurisdiction_registrar_headers(ctx["jurisdiction_id"]),
    )
    assert_error(resp, ApiErrorId.ERR_JURISDICTION_NOT_ACTIVE)


def test_conviction_post_to_transferred_out_record_rejected(api):
    """PRD §3.4: "The target record must be `ACTIVE`: a posting aimed at a
    `TRANSFERRED_OUT` record is rejected with `ERR_RECORD_NOT_ACTIVE`, because retired
    records are immutable."
    PRD §3.3: "A `TRANSFERRED_OUT` record is a read-only artifact of history."

    Design: Corner/state_machines/conviction_post_to_transferred_out_record_rejected
    """
    # AA can post convictions (POINTER + COMMERCIAL certified); the record moves to BB.
    ctx_a = setup_certified_jurisdiction(
        api, code="AA", systems=("POINTER_NETWORK", "COMMERCIAL_DRIVER_NETWORK")
    )
    setup_verified_license(api, ctx_a, license_class="STANDARD")
    ctx_b = setup_certified_jurisdiction(api, code="BB", systems=("POINTER_NETWORK",))
    transfer = initiate_transfer(
        api, ctx_a["driver_id"], ctx_a["license_id"], ctx_b["jurisdiction_id"]
    )
    surrender_transfer(api, transfer["id"], ctx_a["jurisdiction_id"])
    complete_transfer(api, transfer["id"], ctx_b["jurisdiction_id"])

    resp = api.create_conviction(
        conviction_payload(
            ctx_a["record_id"],
            offense_date="2026-08-10",
            conviction_date="2026-08-20",
            severity="CMV_SERIOUS",
            points=3,
        ),
        make_jurisdiction_registrar_headers(ctx_a["jurisdiction_id"]),
    )
    assert_error(resp, ApiErrorId.ERR_RECORD_NOT_ACTIVE)
    assert read_record(api, ctx_a["record_id"])["points_total"] == 0, (
        "nothing was persisted against the retired record"
    )


def test_driver_points_offense_vs_conviction_window(api):
    """PRD §3.4: "The operational total `points_total` sums the `points` of every
    conviction on the record whose `offense_date` falls within the trailing 1,095-day
    window — three years — ending on the logical clock's current date, both boundary
    days included, so a conviction exactly 1,095 days old still counts. The abstract
    total `abstract_points_total` is the identical sum keyed on `conviction_date`
    instead of `offense_date`; the two diverge whenever a conviction's offense and
    conviction dates straddle the window boundary differently."

    Design: Difficulty/dual_variant_calc/driver_points_offense_vs_conviction_window
    """
    ctx = setup_conviction_world(api, code="AA")
    # At the 2026-09-01 startup clock the offense window is [2023-09-02, 2026-09-01]:
    # the 2023-01-15 offense falls outside it, both conviction dates fall inside the
    # conviction window.
    post_conviction(
        api,
        ctx["record_id"],
        ctx["jurisdiction_id"],
        offense_date="2023-01-15",
        conviction_date="2026-08-25",
        severity="NON_CMV",
        points=6,
    )
    post_conviction(
        api,
        ctx["record_id"],
        ctx["jurisdiction_id"],
        offense_date="2026-08-01",
        conviction_date="2026-08-20",
        severity="NON_CMV",
        points=5,
    )
    record = read_record(api, ctx["record_id"])
    assert record["points_total"] == 5, "only the 2026-08-01 offense is inside the window"
    assert record["abstract_points_total"] == 11, (
        "both conviction dates are inside the conviction window"
    )
    assert read_record_disqualifications(api, ctx["record_id"]) == [], (
        "5 < 12 and no CMV_MAJOR conviction: no disqualification is created"
    )


def test_conviction_deadline_exactly_30_vs_31_days(api):
    """PRD §3.4: "a conviction is late when the number of days from its `conviction_date`
    to the posted date exceeds 30, and the deadline is inclusive — exactly 30 days is
    timely, while 31 days is late."
    PRD §3.4: "The eligible set for that score is the convictions on records the
    jurisdiction holds whose `severity` is `CMV_SERIOUS` or `CMV_MAJOR`;
    `timeliness_score_bp` is ten thousand times the timely share of that set, rounded
    half up to an integer, and a full 10,000 while the set is empty."

    Design: Difficulty/boundary_precision_check/conviction_deadline_exactly_30_vs_31_days
    """
    ctx = setup_conviction_world(api, code="AA")
    # Posted at the 2026-09-01 startup clock: 2026-08-02 is exactly 30 days out.
    timely = post_conviction(
        api,
        ctx["record_id"],
        ctx["jurisdiction_id"],
        offense_date="2026-07-20",
        conviction_date="2026-08-02",
        severity="CMV_SERIOUS",
        points=1,
    )
    assert timely["is_late"] is False, "exactly 30 days is timely (inclusive deadline)"
    late = post_conviction(
        api,
        ctx["record_id"],
        ctx["jurisdiction_id"],
        offense_date="2026-07-15",
        conviction_date="2026-08-01",
        severity="CMV_SERIOUS",
        points=1,
    )
    assert late["is_late"] is True, "31 days is the first late day"

    jurisdiction = read_jurisdiction(api, ctx["jurisdiction_id"])
    assert jurisdiction["timeliness_score_bp"] == 5000, (
        "1 of 2 commercial convictions timely, in basis points"
    )
    record = read_record(api, ctx["record_id"])
    assert record["points_total"] == 2
    assert read_record_disqualifications(api, ctx["record_id"]) == []


def test_timeliness_empty_and_noncommercial_excluded(api):
    """PRD §3.4: "The eligible set for that score is the convictions on records the
    jurisdiction holds whose `severity` is `CMV_SERIOUS` or `CMV_MAJOR`;
    `timeliness_score_bp` is ten thousand times the timely share of that set, rounded
    half up to an integer, and a full 10,000 while the set is empty."

    Design: Corner/calculations/timeliness_empty_and_noncommercial_excluded
    """
    ctx = setup_conviction_world(api, code="AA")
    assert read_jurisdiction(api, ctx["jurisdiction_id"])["timeliness_score_bp"] == (
        TIMELINESS_SCORE_FULL_BP
    ), "the empty eligible set is fully timely"

    # A NON_CMV conviction 83 days late is flagged but never enters the eligible set.
    conviction = post_conviction(
        api,
        ctx["record_id"],
        ctx["jurisdiction_id"],
        offense_date="2026-06-01",
        conviction_date="2026-06-10",
        severity="NON_CMV",
        points=2,
    )
    assert conviction["is_late"] is True
    assert read_jurisdiction(api, ctx["jurisdiction_id"])["timeliness_score_bp"] == (
        TIMELINESS_SCORE_FULL_BP
    ), "NON_CMV convictions never enter the timeliness set"


def test_points_threshold_exactly_12_triggers_disqualification(api):
    """PRD §3.4: "a just-posted conviction whose `severity` is `CMV_MAJOR` warrants a
    disqualification with a base duration of 365 days and `basis` `AUTO_MAJOR`; failing
    that, a new point total of at least 12 warrants one with a base of 90 days and
    `basis` `AUTO_POINTS`; otherwise nothing is created."

    Design: Corner/calculations/points_threshold_exactly_12_triggers_disqualification
    """
    ctx = setup_conviction_world(api, code="AA")
    record_x = ctx["record_id"]
    ctx_y = setup_driver_record(api, ctx, full_name="Driver Y", ssn_last4_hash="hDY1")
    record_y = ctx_y["record_id"]
    specs_x = [
        {"offense_date": "2026-08-10", "conviction_date": "2026-08-20", "points": 6},
        {"offense_date": "2026-08-12", "conviction_date": "2026-08-21", "points": 6},
    ]
    specs_y = [
        {"offense_date": "2026-08-10", "conviction_date": "2026-08-20", "points": 6},
        {"offense_date": "2026-08-12", "conviction_date": "2026-08-21", "points": 5},
    ]
    for spec in specs_x:
        post_conviction(api, record_x, ctx["jurisdiction_id"], **spec)
    for spec in specs_y:
        post_conviction(api, record_y, ctx["jurisdiction_id"], **spec)

    expected_start, expected_end = expected_dq_window(DEFAULT_CLOCK_ISO, 90)
    disqualifications_x = read_record_disqualifications(api, record_x)
    assert len(disqualifications_x) == 1, "12 >= 12 triggers the disqualification"
    assert disqualifications_x[0]["basis"] == "AUTO_POINTS"
    assert disqualifications_x[0]["start_date"] == expected_start == "2026-09-01"
    assert disqualifications_x[0]["end_date"] == expected_end == "2026-11-30"
    assert read_record(api, record_x)["points_total"] == 12

    assert read_record_disqualifications(api, record_y) == [], "11 < 12 does not trigger"
    assert read_record(api, record_y)["points_total"] == 11


def test_conviction_to_license_suspension_cascade(api):
    """PRD §2.8: "Posting a conviction recomputes the record's point totals; the
    disqualification evaluation may then create or extend a disqualification; and a
    created disqualification — automatic or judicial alike — suspends every `ACTIVE`
    license of class `COMMERCIAL` riding on that record, while `STANDARD` licenses are
    untouched."
    PRD §3.4: "a just-posted conviction whose `severity` is `CMV_MAJOR` warrants a
    disqualification with a base duration of 365 days and `basis` `AUTO_MAJOR`".

    Design: Difficulty/transitive_cascade/conviction_to_license_suspension_cascade
    """
    ctx = setup_conviction_world(api, code="AA")
    setup_verified_license(api, ctx, license_class="COMMERCIAL")

    conviction = post_conviction(
        api,
        ctx["record_id"],
        ctx["jurisdiction_id"],
        offense_date="2026-08-15",
        conviction_date="2026-08-25",
        severity="CMV_MAJOR",
        points=6,
    )
    # Link 1: the posting recomputed the record's points.
    assert read_record(api, ctx["record_id"])["points_total"] == 6
    # Link 2: the evaluation created an AUTO_MAJOR disqualification (365 days from the
    # logical clock date).
    expected_start, expected_end = expected_dq_window(DEFAULT_CLOCK_ISO, 365)
    disqualifications = read_record_disqualifications(api, ctx["record_id"])
    assert len(disqualifications) == 1
    assert disqualifications[0]["basis"] == "AUTO_MAJOR"
    assert disqualifications[0]["start_date"] == expected_start == "2026-09-01"
    assert disqualifications[0]["end_date"] == expected_end == "2027-09-01"
    # Link 3: the disqualification's creation — not the conviction POST directly —
    # suspended the COMMERCIAL license.
    assert read_license(api, ctx["license_id"])["status"] == "SUSPENDED"
    # The conviction itself was timely: posted 2026-09-01, convicted 2026-08-25.
    assert conviction["is_late"] is False


def test_federal_verifier_cannot_post_conviction(api):
    """PRD §2.1: "`FederalVerifier` operates the social-security-number and
    lawful-status verification services consulted at license issuance."
    PRD §2.6: "**Role authorization.** The declared role must be among the endpoint's
    authorized roles, else `ERR_INSUFFICIENT_PERMISSIONS` (HTTP 403)." — rung 2 fires
    before the existence rung, so even a nonexistent record id surfaces the role error.

    Design: Corner/rbac/federal_verifier_cannot_post_conviction
    """
    resp = api.create_conviction(
        conviction_payload(
            NON_EXISTENT_UUID,
            offense_date="2026-08-01",
            conviction_date="2026-08-10",
            severity="NON_CMV",
            points=2,
        ),
        FEDERAL_VERIFIER_HEADERS,
    )
    assert_error(resp, ApiErrorId.ERR_INSUFFICIENT_PERMISSIONS)
