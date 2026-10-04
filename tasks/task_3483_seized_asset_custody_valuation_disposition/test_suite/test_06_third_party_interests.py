"""Third-party interests: the appeal loop, outcome/kind compatibility,
priority-position uniqueness, identity pinning, and the grant cascades."""

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    adjudicate_interest,
    appeal_interest,
    assert_third_party_interest,
    create_case,
    create_lien_payload,
    create_sell_authorized_asset,
    create_valued_asset,
    decide_retention,
    file_innocent_owner_claim,
    file_lien,
    forfeit_case,
    file_forfeiture,
    get_asset,
    intake_asset,
    make_claimant_headers,
    schedule_sale_event,
    validate_created,
    validate_error,
    validate_paginated,
)


def test_third_party_interest_appeal_cycle(api):
    """PRD §3.5: "A denied claimant gets one appeal."
    PRD §3.5: "A successful appeal moves the interest from `DENIED` to
    `APPEALED` and increments `appeal_count`, reopening it for another
    adjudication round under the same outcome-compatibility rules"
    PRD §3.5: "once the count has reached the limit, a further appeal is
    rejected with `ERR_APPEAL_EXHAUSTED`."

    Design: Difficulty/non_linear_state_machine/third_party_interest_appeal_cycle
    """
    case = create_case(
        case_number="26-MJ-0006", judicial_district="D. Ariz.",
        forfeiture_type="CIVIL", lead_agency_code="DEA",
    )
    asset = intake_asset(
        case["id"], asset_type="REAL_PROPERTY", description="ranch house",
        seized_on="2026-09-01T00:00:00Z", seizure_condition_grade="GOOD",
    )
    claim = file_innocent_owner_claim(asset["id"], petitioner_ref="cl-orma")
    adjudicate_interest(claim["id"], "DENY")
    appealed = appeal_interest(claim["id"], "cl-orma")
    assert appealed["status"] == "APPEALED"
    adjudicate_interest(claim["id"], "DENY")

    exhausted = api.appeal_third_party_interest(
        claim["id"], make_claimant_headers("cl-orma")
    )
    validate_error(exhausted, ApiErrorId.ERR_APPEAL_EXHAUSTED)
    assert exhausted.status_code == 409, (
        "the appeal budget of one is spent after FILED -> DENIED -> "
        "APPEALED -> DENIED"
    )

    rows, _ = validate_paginated(
        api.list_asset_third_party_interests(
            asset["id"], TEST_USERS["court_official_headers"]
        )
    )
    target = [r for r in rows if r["id"] == claim["id"]][0]
    assert target["status"] == "DENIED"
    assert target["appeal_count"] == 1


def test_innocent_owner_grant_cascade(api):
    """PRD §3.5: "Granting an innocent-owner claim is the consequential
    branch: it fires the return cascade on the asset. If the asset's
    `legal_state` stands at `SEIZED`, `VALUATION_PENDING`, `VALUED`,
    `DISPOSITION_REVIEW`, or `SALE_AUTHORIZED`, it moves to `RETURN_PENDING`;
    and every sale event of that asset standing at `OPEN_FOR_BIDS` or
    `CLOSED_PENDING_SETTLEMENT` is cancelled to `CANCELLED`."

    Design: Difficulty/transitive_cascade/innocent_owner_grant_cascade
    """
    case = create_case(
        case_number="26-MJ-0008", judicial_district="N.D. Ohio",
        forfeiture_type="CRIMINAL", lead_agency_code="FBI",
    )
    file_forfeiture(case["id"])
    forfeit_case(case["id"])
    asset = create_sell_authorized_asset(
        case["id"], raw_value_cents=900_000, grade="EXCELLENT",
        description="pickup",
    )
    event = schedule_sale_event(
        asset["id"], reserve_price_cents=900_000, auctioneer_ref="auc-3",
        slot_start="2026-09-08T10:00:00Z", slot_end="2026-09-08T12:00:00Z",
    )
    claim = file_innocent_owner_claim(asset["id"], petitioner_ref="cl-orma")

    granted = adjudicate_interest(claim["id"], "GRANT")
    assert granted["status"] == "GRANTED"

    after = get_asset(asset["id"])
    assert after["legal_state"] == "RETURN_PENDING", "cascade link 1"
    assert after["custody_state"] == "RELEASED_FOR_SALE", (
        "the grant cascade moves the legal dimension only"
    )
    events, _ = validate_paginated(
        api.list_asset_sale_events(
            asset["id"], TEST_USERS["court_official_headers"]
        )
    )
    assert events[0]["id"] == event["id"]
    assert events[0]["status"] == "CANCELLED", "cascade link 2"


def test_claim_grant_on_retained_asset_does_not_cascade(api):
    """PRD §3.5: "filings against `RETAINED` assets are still accepted, and a
    later grant there records the claim without firing the return cascade
    described below."

    Design: Corner/state_machines/claim_grant_on_retained_asset_does_not_cascade
    """
    case = create_case(
        case_number="26-MJ-1016", judicial_district="E.D. Mich.",
        forfeiture_type="CIVIL", lead_agency_code="USMS",
    )
    asset, _valuation = create_valued_asset(
        case["id"], raw_value_cents=2_000_000, grade="EXCELLENT",
        method="BLUE_BOOK", description="surplus sedan",
    )
    decide_retention(asset["id"], "RETAIN")
    claim = file_innocent_owner_claim(asset["id"], petitioner_ref="cl-orma")

    granted = adjudicate_interest(claim["id"], "GRANT")
    assert granted["status"] == "GRANTED", (
        "the grant records the claim even on a terminal-legal asset"
    )
    after = get_asset(asset["id"])
    assert after["legal_state"] == "RETAINED", (
        "the cascade's from-state list excludes RETAINED"
    )
    assert after["custody_state"] == "INTAKE"


def test_adjudicate_outcome_kind_mismatch_both_directions(api):
    """PRD §3.5: "the outcome must be compatible with the kind: `VERIFY`
    applies only to the four lien kinds and moves the interest to `VERIFIED`;
    `GRANT` applies only to `INNOCENT_OWNER` and moves it to `GRANTED`"
    PRD §3.5: "An incompatible pairing — verifying an innocent-owner claim or
    granting a lien — is rejected with `ERR_OUTCOME_KIND_MISMATCH`."

    Design: Corner/errors/adjudicate_outcome_kind_mismatch_both_directions
    """
    case = create_case(
        case_number="26-MJ-1025", judicial_district="D. Ariz.",
        forfeiture_type="CIVIL", lead_agency_code="DEA",
    )
    asset = intake_asset(
        case["id"], asset_type="REAL_PROPERTY", description="condo",
        seized_on="2026-09-01T00:00:00Z", seizure_condition_grade="GOOD",
    )
    claim = file_innocent_owner_claim(asset["id"], petitioner_ref="cl-orma")
    lien = file_lien(
        asset["id"], petitioner_ref="cl-bank", kind="LIEN_MORTGAGE",
        lienholder_name="Metro Bank", amount_cents=250_000, priority_position=1,
    )

    verify_on_claim = api.adjudicate_third_party_interest(
        claim["id"], "VERIFY", TEST_USERS["court_official_headers"]
    )
    validate_error(verify_on_claim, ApiErrorId.ERR_OUTCOME_KIND_MISMATCH)
    assert verify_on_claim.status_code == 422

    grant_on_lien = api.adjudicate_third_party_interest(
        lien["id"], "GRANT", TEST_USERS["court_official_headers"]
    )
    validate_error(grant_on_lien, ApiErrorId.ERR_OUTCOME_KIND_MISMATCH)
    assert grant_on_lien.status_code == 422

    rows, meta = validate_paginated(
        api.list_asset_third_party_interests(
            asset["id"], TEST_USERS["court_official_headers"]
        )
    )
    assert meta["total_count"] == 2
    statuses = {r["id"]: r["status"] for r in rows}
    assert statuses[claim["id"]] == "FILED"
    assert statuses[lien["id"]] == "FILED", (
        "a failed adjudication is not a state change"
    )


def test_lien_priority_conflict_frees_after_deny(api):
    """PRD §3.5: "Among an asset's interests standing at `FILED`, `VERIFIED`,
    or `APPEALED`, at most one lien may hold a given `priority_position`; a
    second lien filing at an occupied position is rejected with
    `ERR_PRIORITY_POSITION_CONFLICT`, while a position vacated by a denial is
    free again."

    Design: Corner/errors/lien_priority_conflict_frees_after_deny
    """
    case = create_case(
        case_number="26-MJ-1026", judicial_district="D. Nev.",
        forfeiture_type="CIVIL", lead_agency_code="ATF",
    )
    asset = intake_asset(
        case["id"], asset_type="REAL_PROPERTY", description="warehouse",
        seized_on="2026-09-01T00:00:00Z", seizure_condition_grade="FAIR",
    )
    lien_a = file_lien(
        asset["id"], petitioner_ref="cl-b1", kind="LIEN_TAX",
        lienholder_name="County", amount_cents=100_000, priority_position=1,
    )

    conflict = api.create_third_party_interest(
        create_lien_payload(
            asset["id"], "cl-b2", kind="LIEN_MORTGAGE",
            lienholder_name="Bank", amount_cents=200_000, priority_position=1,
        ),
        make_claimant_headers("cl-b2"),
    )
    validate_error(conflict, ApiErrorId.ERR_PRIORITY_POSITION_CONFLICT)
    assert conflict.status_code == 409

    adjudicate_interest(lien_a["id"], "DENY")
    lien_b = validate_created(
        api.create_third_party_interest(
            create_lien_payload(
                asset["id"], "cl-b2", kind="LIEN_MORTGAGE",
                lienholder_name="Bank", amount_cents=200_000,
                priority_position=1,
            ),
            make_claimant_headers("cl-b2"),
        )
    )
    assert_third_party_interest(lien_b)
    assert lien_b["status"] == "FILED"
    assert lien_b["priority_position"] == 1, (
        "DENIED releases the priority slot"
    )


def test_claimant_cannot_appeal_another_petitioners_interest(api):
    """PRD §3.5: "Filing it requires the caller's `X-User-ID` to equal the
    interest's `petitioner_ref` (`ERR_FORBIDDEN` otherwise) and the
    `appeal_count` to be below the appeal limit of one"
    PRD §2.1: "a `Claimant` may file or appeal a third-party interest only
    when the caller's `X-User-ID` equals that interest's `petitioner_ref`"

    Design: Corner/rbac/claimant_cannot_appeal_another_petitioners_interest
    """
    case = create_case(
        case_number="26-MJ-1034", judicial_district="D. Ariz.",
        forfeiture_type="CIVIL", lead_agency_code="DEA",
    )
    asset = intake_asset(
        case["id"], asset_type="VEHICLE", description="moped",
        seized_on="2026-09-01T00:00:00Z", seizure_condition_grade="FAIR",
    )
    claim = file_innocent_owner_claim(asset["id"], petitioner_ref="cl-orma")
    adjudicate_interest(claim["id"], "DENY")

    other = api.appeal_third_party_interest(
        claim["id"], make_claimant_headers("cl-other")
    )
    validate_error(other, ApiErrorId.ERR_FORBIDDEN)
    assert other.status_code == 403, "cl-other is not the petitioner"

    appealed = appeal_interest(claim["id"], "cl-orma")
    assert appealed["status"] == "APPEALED"
    assert appealed["appeal_count"] == 1
