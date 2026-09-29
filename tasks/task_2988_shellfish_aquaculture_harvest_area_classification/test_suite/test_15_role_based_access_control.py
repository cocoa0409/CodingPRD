"""Identity, role authorisation and the three ownership models (PRD §2.1, §2.7).

The §2.7 ladder puts authentication (rung 1) above role authorisation (rung 2),
which sits above existence (rung 3) and ownership (rung 4). These tests walk that
prefix of the ladder across every shape of principal the PRD defines: the three
opaque roles whose `X-User-ID` is never compared to a record `id`
(`ShellfishControlAuthority`, `SitingReviewer`, `FarmOperator`), the two
record-backed roles whose `X-User-ID` *is* a `Hatchery` id or a `Dealer` id
(`HatcheryOperator`, `SeafoodDealer`), and the wide read scope §2.1 grants
everybody on growing areas and on the logical clock.

Every denial here is paired with the identical payload succeeding under the right
principal, so each test pins the refusal on the identity alone rather than on the
request body or on the state of the world. The role lists asserted against are
the ones tabulated in §4; the ownership rules come from §2.1, §3.4 (lease
submission and segregation of duties), §3.5 (seed shipments) and §3.9 (shipment
assembly).
"""
from test_helpers import (
    ApiErrorId,
    api_client,
    classification_decision_payload,
    create_dealer,
    create_draft_lease,
    create_hatchery,
    create_lease_under_review,
    create_listed_dealer,
    design_world,
    DW_AREA_CODE,
    dw_dealer_payload,
    dw_hatchery_payload,
    dw_lease_payload_overrides,
    dw_seed_lot_payload_overrides,
    get_success_data,
    is_iso8601_timestamp,
    iso,
    make_authority_headers,
    make_hatchery_operator_headers,
    make_seafood_dealer_headers,
    NON_EXISTENT_UUID,
    review_payload,
    seed_lot_payload,
    shipment_payload,
    submit_lease_payload,
    TEST_USERS,
    validate_error,
    validate_paginated,
    validate_success,
)

AUTHORITY = TEST_USERS["authority_headers"]
REVIEWER_A = TEST_USERS["reviewer_headers"]
REVIEWER_B = TEST_USERS["reviewer_b_headers"]
OPERATOR = TEST_USERS["operator_headers"]
OPERATOR_B = TEST_USERS["operator_b_headers"]

# A `ShellfishControlAuthority` header pair whose `X-User-ID` is the empty
# string. PRD §2.1 treats an empty string exactly as it treats an absent header.
# The value must be `""` and never `" "`: a whitespace-only header value never
# reaches the server at all, because the HTTP client rejects it first.
BLANK_ID_AUTHORITY = make_authority_headers("")


# --------------------------------------------------------------------------
# Role authorisation: an operation exclusive to the authority
# --------------------------------------------------------------------------
def _area_with_five_accepted_samples():
    """GA-114 holding five ACCEPTED samples of 2 MPN, one per calendar day from
    2026-07-05, all from station ST-1 so none supersedes another.

    Five accepted samples clear the `MIN_SAMPLES_FOR_DECISION` rung, and the
    statistics land at a geometric mean and 90th percentile of 2.0, so
    `eligible_classification` reads APPROVED and the sample sweep cannot have
    fired (its trigger is a geometric mean strictly above 14.0).
    """
    return design_world(stage="area", sample_mpns=[2, 2, 2, 2, 2],
                        sample_start_date="2026-07-05")


def test_farm_operator_cannot_record_a_classification_decision():
    """PRD §4 lists `ShellfishControlAuthority` as the only role authorised on
    POST classification-decisions, so a `FarmOperator` sending it is refused at
    rung 2 with ERR_UNAUTHORIZED (403). The refusal is about the role alone: the
    authority then sends the byte-identical body — same target classification,
    same `expected_area_version`, same note shape — and it is accepted, which
    also proves the refused call wrote nothing, since a bumped version would have
    made the second request stale (ERR_STALE_AREA_VERSION).

    RESTRICTED is a strict downgrade from APPROVED, so §3.1 exempts it from the
    data-support test and lets it skip a rank, and §2.10 keeps the two status
    dimensions independent: `harvest_status` must still read OPEN afterwards.

    Two deviations from the design recipe, both PRD-driven. §3.1 states the
    decision response is "the updated area, at HTTP 200", so 200 is asserted
    rather than 201. And the expected version is read from the area rather than
    hard-coded to 2, because §3.2 advances the version on every sample ingest
    that changes a field, so five ingests have already moved it past 1.

    Design: Corner/rbac/farm_operator_cannot_record_a_classification_decision
    """
    world = _area_with_five_accepted_samples()
    area = world["area"]
    version = area["version"]
    assert area["accepted_sample_count"] == 5
    assert area["eligible_classification"] == "APPROVED"
    assert area["classification"] == "APPROVED"
    assert area["harvest_status"] == "OPEN"

    refused = api_client.create_classification_decision(
        area["id"],
        classification_decision_payload("RESTRICTED", version,
                                        decision_note="operator attempt"),
        OPERATOR)
    validate_error(refused, ApiErrorId.ERR_UNAUTHORIZED, 403)

    accepted = api_client.create_classification_decision(
        area["id"],
        classification_decision_payload("RESTRICTED", version,
                                        decision_note="authority downgrade"),
        AUTHORITY)
    decided = validate_success(accepted, 200)
    assert decided["classification"] == "RESTRICTED"
    assert decided["version"] == version + 1
    assert decided["harvest_status"] == "OPEN"

    stored = get_success_data(api_client.get_growing_area(area["id"], AUTHORITY))
    assert stored["classification"] == "RESTRICTED"
    assert stored["harvest_status"] == "OPEN"


# --------------------------------------------------------------------------
# Authentication runs before authorisation and before lookup
# --------------------------------------------------------------------------
def test_blank_user_id_header_returns_unauthenticated():
    """PRD §2.1 requires both identity headers to be present *and* non-empty, and
    rejects an empty string with ERR_UNAUTHENTICATED (401) "before anything else
    about the request is examined". Two reads carry the same empty `X-User-ID`
    with an otherwise perfectly authorised role: one names a growing area that
    exists, the other a UUID that does not. Both answer 401, which is the
    observable consequence of rung 1 sitting above rung 3 — the second read never
    reaches the lookup that would have produced ERR_GROWING_AREA_NOT_FOUND (404).

    Both responses must still be well-formed §2.2 error envelopes: a `meta`
    carrying a server-minted `api_request_id` prefixed `req_`, and a non-empty
    human-readable `data.message`.

    Design: Corner/rbac/blank_user_id_header_returns_unauthenticated
    """
    area = design_world(stage="area")["area"]

    on_existing = api_client.get_growing_area(area["id"], BLANK_ID_AUTHORITY)
    on_missing = api_client.get_growing_area(NON_EXISTENT_UUID, BLANK_ID_AUTHORITY)

    for response in (on_existing, on_missing):
        body = validate_error(response, ApiErrorId.ERR_UNAUTHENTICATED, 401)
        assert body["message"].strip()
        assert response.json()["meta"]["api_request_id"].startswith("req_")

    assert on_missing.status_code != 404


# --------------------------------------------------------------------------
# Record-backed ownership: the hatchery the caller *is*
# --------------------------------------------------------------------------
def _lease_with_two_certified_hatcheries():
    """GA-114 with APPROVED lease L-2988-01, plus two hatcheries that are both
    pathogen-free certified for CRASSOSTREA_VIRGINICA through 2027-03-31 — H1
    (Sound Hatchery, NCSP-77) and H2 (Bay Hatchery, NCSP-88).

    Certifying both for the same species is what isolates the rule under test:
    neither sanitary gate of §3.5 can be the reason either request fails.
    """
    world = design_world(stage="lease")
    world["h1"] = create_hatchery(dw_hatchery_payload())
    world["h2"] = create_hatchery(dw_hatchery_payload(
        name="Bay Hatchery", ncsp_certificate_no="NCSP-88"))
    return world


def test_hatchery_operator_cannot_record_a_seed_lot_for_another_hatchery():
    """A `HatcheryOperator`'s `X-User-ID` *is* a `Hatchery` id (PRD §2.1), so
    §3.5 requires the `hatchery_id` in the body to equal it and refuses a
    mismatch with ERR_HATCHERY_OWNERSHIP_VIOLATION (403). H2 sends a shipment
    naming H1 as the shipping hatchery and is refused; H1 then sends the very
    same payload and is accepted at 201 with `status` RECEIVED. Both hatcheries
    hold a current certificate for the shipped species, so the refusal cannot be
    ERR_HATCHERY_CERTIFICATE_EXPIRED or ERR_SPECIES_NOT_CERTIFIED, and ownership
    (rung 4) is reached only because both the hatchery and the lease resolve at
    rung 3.

    The design's closing check is a filtered list read. §4 declares that seed
    lots may be filtered by hatchery but the PRD never names the query parameter,
    so this asserts the equivalent fact against the unfiltered list: the database
    starts empty, so exactly one seed lot exists and its `hatchery_id` is H1's —
    which is also what makes "H2 has none" true.

    Design: Corner/rbac/hatchery_operator_cannot_record_a_seed_lot_for_another_hatchery
    """
    world = _lease_with_two_certified_hatcheries()
    payload = seed_lot_payload(world["h1"]["id"], world["lease"]["id"],
                               **dw_seed_lot_payload_overrides())

    refused = api_client.create_seed_lot(
        payload, make_hatchery_operator_headers(world["h2"]["id"]))
    validate_error(refused, ApiErrorId.ERR_HATCHERY_OWNERSHIP_VIOLATION, 403)

    accepted = api_client.create_seed_lot(
        payload, make_hatchery_operator_headers(world["h1"]["id"]))
    lot = validate_success(accepted, 201)
    assert lot["hatchery_id"] == world["h1"]["id"]
    assert lot["status"] == "RECEIVED"

    rows, meta = validate_paginated(api_client.list_seed_lots(AUTHORITY))
    assert meta["total_count"] == 1
    assert [row["hatchery_id"] for row in rows] == [world["h1"]["id"]]


# --------------------------------------------------------------------------
# Record-backed ownership: the dealer the caller *is*
# --------------------------------------------------------------------------
def _tagged_lot_with_a_second_listed_dealer():
    """The reference world walked to a TAGGED lot — 10 bushels landed under D1
    (Coastal Shellstock, NC-1234-SS, LISTED) at the 2026-08-10T11:00:00Z harvest
    clock — plus a second LISTED North Carolina dealer D2 (Sound Packers,
    NC-5678-SS) that owns nothing at all.
    """
    world = design_world(stage="tagged")
    world["dealer2"] = create_listed_dealer(dw_dealer_payload(
        name="Sound Packers", certification_no="NC-5678-SS"))
    return world


def test_dealer_cannot_assemble_a_shipment_for_another_dealer():
    """PRD §3.9 makes a `SeafoodDealer`'s acting identity a dealer identifier
    that must equal the body's `dealer_id`, refusing a mismatch with
    ERR_DEALER_OWNERSHIP_VIOLATION. That check is rung 4 of the §2.7 ladder,
    far above the rung-13 roster checks, so D2 consigning a shipment in D1's
    name is answered on the ownership ground and not with
    ERR_LOT_DEALER_MISMATCH — and the roster is in fact coherent here, since the
    lot on it really does belong to D1. D1 then sends the identical body and it
    is accepted at 201 with `lot_count` 1 and `total_bushels` 10, the bushels of
    the single tagged lot.

    The design's closing check filters shipments by dealer. §4 declares such a
    filter without naming the parameter, so the equivalent unfiltered assertion
    is made instead: against a freshly emptied database exactly one shipment
    exists and no shipment names D2.

    Design: Corner/rbac/dealer_cannot_assemble_a_shipment_for_another_dealer
    """
    world = _tagged_lot_with_a_second_listed_dealer()
    payload = shipment_payload(
        world["dealer"]["id"], [world["lot"]["id"]],
        destination_state="VA", carrier="Coastal Freight")

    refused = api_client.create_shipment(
        payload, make_seafood_dealer_headers(world["dealer2"]["id"]))
    body = validate_error(refused, ApiErrorId.ERR_DEALER_OWNERSHIP_VIOLATION, 403)
    assert body["error_id"] != ApiErrorId.ERR_LOT_DEALER_MISMATCH

    accepted = api_client.create_shipment(
        payload, make_seafood_dealer_headers(world["dealer"]["id"]))
    shipment = validate_success(accepted, 201)
    assert shipment["dealer_id"] == world["dealer"]["id"]
    assert shipment["lot_count"] == 1
    assert shipment["total_bushels"] == 10

    rows, meta = validate_paginated(api_client.list_shipments(AUTHORITY))
    assert meta["total_count"] == 1
    assert all(row["dealer_id"] != world["dealer2"]["id"] for row in rows)


# --------------------------------------------------------------------------
# Opaque identity is still owned
# --------------------------------------------------------------------------
def test_another_operator_cannot_submit_a_lease_it_does_not_own():
    """A `FarmOperator`'s `X-User-ID` is opaque — the PRD says it "is not the `id`
    of any record" — yet §2.1 still stamps it onto the lease as
    `operator_user_id` and makes every lease-scoped write an equality test against
    that stored value. So a second operator holding the very same `FarmOperator`
    role, which §4 authorises on POST submit, clears rung 2 and is stopped at rung
    4 with ERR_LEASE_OWNERSHIP_VIOLATION — pointedly not ERR_UNAUTHORIZED, even
    though both errors are 403. The owning operator then submits the identical
    body and §3.4 moves the lease to UNDER_REVIEW with `revision_round` still 0,
    because this is a first submission rather than a resubmission.

    The design's third assertion names `navigation_cleared` and
    `environmental_cleared`. §3.4 defines no such booleans: the lease carries
    `navigation_clearance` and `environmental_clearance` over PENDING / CLEARED /
    OBJECTION, and submission "resets both clearance legs to `PENDING` with both
    reviewer identities set back to null". That PENDING-and-null form is asserted
    here, which is the same claim in the vocabulary the PRD actually defines.

    Design: Corner/rbac/another_operator_cannot_submit_a_lease_it_does_not_own
    """
    area = design_world(stage="area")["area"]
    lease = create_draft_lease(area["id"], OPERATOR, dw_lease_payload_overrides())
    assert lease["status"] == "DRAFT"
    assert lease["operator_user_id"] == OPERATOR["X-User-ID"]
    assert lease["operator_user_id"] != OPERATOR_B["X-User-ID"]

    refused = api_client.submit_lease(
        lease["id"], submit_lease_payload(submission_note="not my lease"),
        OPERATOR_B)
    body = validate_error(refused, ApiErrorId.ERR_LEASE_OWNERSHIP_VIOLATION, 403)
    assert body["error_id"] != ApiErrorId.ERR_UNAUTHORIZED

    accepted = api_client.submit_lease(
        lease["id"],
        submit_lease_payload(submission_note="initial siting package"),
        OPERATOR)
    submitted = validate_success(accepted, 200)
    assert submitted["status"] == "UNDER_REVIEW"
    assert submitted["revision_round"] == 0

    stored = get_success_data(api_client.get_lease(lease["id"], AUTHORITY))
    assert stored["navigation_clearance"] == "PENDING"
    assert stored["environmental_clearance"] == "PENDING"
    assert stored["navigation_reviewer_user_id"] is None
    assert stored["environmental_reviewer_user_id"] is None


# --------------------------------------------------------------------------
# Segregation of duties inside one role
# --------------------------------------------------------------------------
def test_same_reviewer_cannot_record_both_clearance_legs():
    """Both clearance legs are `SitingReviewer` operations in §4, so a role
    allowlist cannot separate them. §3.4 separates them on identity instead:
    before a leg is recorded the acting `X-User-ID` is compared against the
    *sibling* leg's recorded reviewer identity, and a match is refused with
    ERR_SEGREGATION_OF_DUTIES (409, rung 12). Reviewer A, whose identity is
    already stamped as `navigation_reviewer_user_id`, is therefore refused on the
    environmental leg while a second reviewer records the identical body
    immediately afterwards. The refused call leaves the environmental leg PENDING
    with a null reviewer identity, which is what keeps the second attempt
    reachable — had the leg been written, §3.4 would answer the retry with
    ERR_INVALID_LEASE_STATE instead, since the state check precedes segregation.

    The design's closing assertion expects `status` UNDER_REVIEW after the second
    clearance and names boolean `*_cleared` fields. Neither is PRD-derivable: the
    lease carries `navigation_clearance` / `environmental_clearance` enums, and
    §3.4's join rule says "clearing a leg while the sibling leg already reads
    CLEARED completes the join and moves `status` to PENDING_DECISION". The
    PENDING_DECISION form is asserted, which is the outcome the PRD uniquely
    derives; the authority decision is indeed still outstanding, but the lease
    has left UNDER_REVIEW to await it.

    Design: Corner/rbac/same_reviewer_cannot_record_both_clearance_legs
    """
    area = design_world(stage="area")["area"]
    lease = create_lease_under_review(
        area["id"], OPERATOR, dw_lease_payload_overrides())
    assert lease["status"] == "UNDER_REVIEW"

    lease = get_success_data(api_client.navigation_review(
        lease["id"],
        review_payload("CLEARED", review_note="outside the marked channel"),
        REVIEWER_A))
    assert lease["navigation_clearance"] == "CLEARED"
    assert lease["navigation_reviewer_user_id"] == REVIEWER_A["X-User-ID"]
    assert lease["status"] == "UNDER_REVIEW"

    refused = api_client.environmental_review(
        lease["id"], review_payload("CLEARED", review_note="no SAV impact"),
        REVIEWER_A)
    validate_error(refused, ApiErrorId.ERR_SEGREGATION_OF_DUTIES, 409)

    held = get_success_data(api_client.get_lease(lease["id"], AUTHORITY))
    assert held["environmental_clearance"] == "PENDING"
    assert held["environmental_reviewer_user_id"] is None
    assert held["status"] == "UNDER_REVIEW"

    accepted = api_client.environmental_review(
        lease["id"], review_payload("CLEARED", review_note="no SAV impact"),
        REVIEWER_B)
    joined = validate_success(accepted, 200)
    assert joined["environmental_clearance"] == "CLEARED"
    assert joined["navigation_clearance"] == "CLEARED"
    assert joined["environmental_reviewer_user_id"] == REVIEWER_B["X-User-ID"]
    assert joined["navigation_reviewer_user_id"] == REVIEWER_A["X-User-ID"]
    assert joined["status"] == "PENDING_DECISION"


# --------------------------------------------------------------------------
# The shared operations every role holds
# --------------------------------------------------------------------------
def test_every_role_can_read_growing_areas_and_move_the_clock():
    """§2.1 says "growing-area reads are open to all five roles" and "the logical
    clock endpoint is open to all five roles", and §4 spells both lists out in
    full. This exercises every one of the five, including the two record-backed
    roles acting under a real `Hatchery` id and a real `Dealer` id rather than a
    placeholder, so a blanket allowlist admitting only the authority — or one that
    admits the entity-backed roles but then tries to scope their rows by
    ownership — fails here. §2.1 forbids that scoping outright: "read endpoints do
    not filter rows by ownership, so a role that may read a collection sees every
    row in it", which is why all five reads must report the same
    `total_count` of 1 and the same GA-114 row.

    The clock call is made by the `SeafoodDealer`, the least privileged principal
    in the set, and §2.5 has it answer the object `{"current_utc": ...}` — a
    state-changing call on no resource, so HTTP 200 per §4. The instant is
    compared by prefix rather than by literal equality because §2.5 does not fix
    the fractional-second width of the echoed value.

    Design: Corner/rbac/every_role_can_read_growing_areas_and_move_the_clock
    """
    design_world(stage="area")
    hatchery = create_hatchery(dw_hatchery_payload())
    dealer = create_dealer(dw_dealer_payload())

    readers = {
        "ShellfishControlAuthority": AUTHORITY,
        "SitingReviewer": REVIEWER_A,
        "FarmOperator": OPERATOR,
        "HatcheryOperator": make_hatchery_operator_headers(hatchery["id"]),
        "SeafoodDealer": make_seafood_dealer_headers(dealer["id"]),
    }

    for role, headers in readers.items():
        response = api_client.list_growing_areas(headers)
        rows, meta = validate_paginated(response)
        body = response.json()
        assert body["response_type"] == "array", role
        assert isinstance(body["data"], list), role
        assert meta["total_count"] == 1, role
        assert [row["code"] for row in rows] == [DW_AREA_CODE], role

    moved = api_client.set_clock(iso(2026, 8, 2), readers["SeafoodDealer"])
    clock = validate_success(moved, 200)
    assert is_iso8601_timestamp(clock["current_utc"])
    assert clock["current_utc"].startswith("2026-08-02T00:00:00")
