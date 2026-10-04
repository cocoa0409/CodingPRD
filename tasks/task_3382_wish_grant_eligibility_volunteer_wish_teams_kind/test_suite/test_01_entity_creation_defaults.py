"""Entity creation defaults and computed fields on fresh records.

Covers chapter computed aggregates at creation, territory selector ranking,
referral intake computed fields, 404 envelope shape, required-field rejection,
donation-offer computed quantities, and volunteer initial state.
"""
from test_helpers import (
    ApiErrorId,
    NON_EXISTENT_UUID,
    TEST_USERS,
    api_client,
    assert_chapter,
    assert_chapter_fiscal,
    assert_donation_offer,
    assert_referral,
    assert_volunteer,
    create_chapter,
    create_chapter_payload,
    create_donation_offer,
    create_referral,
    create_referral_payload,
    create_volunteer,
    get_chapter,
    get_child,
    get_referral,
    get_volunteer,
    set_clock,
    validate_error,
    validate_success,
)

NATIONAL_ADMIN = TEST_USERS["national_admin_headers"]
REFERRAL_SOURCE = TEST_USERS["referral_source_headers"]
ELIGIBILITY_REVIEWER = TEST_USERS["eligibility_reviewer_headers"]
WISH_COORDINATOR = TEST_USERS["wish_coordinator_headers"]
IN_KIND_OFFICER = TEST_USERS["in_kind_officer_headers"]


def test_chapter_create_applies_computed_defaults():
    """PRD section 3.1: "From then on the chapter's posture, commitment totals,
    and grant averages are computed by the system (§2.9 and §3.8), and reading
    the chapter returns all of them together."
    PRD section 2.9: "Both report 0 while the count is 0."
    PRD section 2.4: "an integer `version` that starts at 1 on creation and
    increments by exactly one each time the resource changes"

    Design: Corner/entities/chapter_create_applies_computed_defaults
    """
    created = create_chapter(
        name="Metro Chapter", territory_zip_prefixes=["900"],
        fiscal_year_budget_cents=2000000, target_avg_cost_per_wish_cents=800000)
    chapter = get_chapter(created["id"])
    assert_chapter(chapter)
    assert_chapter_fiscal(
        chapter,
        committed_cost_cents=0,
        granted_wish_count=0,
        granted_cost_total_cents=0,
        granted_cash_total_cents=0,
        avg_cost_blended_cents=0,
        avg_cost_cash_cents=0,
        posture="OPEN",
    )
    assert chapter["version"] == 1, f"new chapter version must be 1, got {chapter['version']}"
    assert chapter["created_at"], "created_at must be present"


def test_child_chapter_assignment_longest_prefix_then_created_at():
    """PRD section 3.2: "the candidate offering the longest matching prefix
    wins, and remaining ties break on the candidate chapters' `created_at`,
    earliest first — never on chapter id. The winning chapter's id is recorded
    as the child's `chapter_id`."

    Design: Corner/entities/child_chapter_assignment_longest_prefix_then_created_at
    """
    set_clock()
    c1 = create_chapter(name="C1", territory_zip_prefixes=["900"])
    create_chapter(name="C2", territory_zip_prefixes=["90"])
    create_chapter(name="C3", territory_zip_prefixes=["900"],
                   fiscal_year_budget_cents=3000000)
    referral = create_referral(child_zip_code="90012")
    child = get_child(referral["child_id"])
    assert child["chapter_id"] == c1["id"], (
        "longest prefix (900, length 3) beats 90; the 900-tie between C1 and "
        f"C3 breaks on created_at ASC -> C1; got {child['chapter_id']}, "
        f"expected {c1['id']}"
    )


def test_referral_create_computes_age_and_initial_state():
    """PRD section 3.2: "The payload atomically creates — or, on re-referral
    after a terminal referral, reuses — the child record, and produces a
    referral in `PENDING_CERTIFICATION` status with `age_months_at_intake`
    computed from the logical clock and `child_id` linking the two records."

    Design: Corner/entities/referral_create_computes_age_and_initial_state
    """
    set_clock()
    create_chapter(territory_zip_prefixes=["900"])
    created = create_referral()  # canonical child dob 2016-03-10
    referral = get_referral(created["id"])
    assert_referral(referral)
    assert referral["age_months_at_intake"] == 125, (
        "dob 2016-03-10 at the 2026-09-01 logical clock is 125 complete "
        f"months, got {referral['age_months_at_intake']}"
    )
    assert referral["status"] == "PENDING_CERTIFICATION"
    assert referral["wish_id"] is None
    assert referral["qualifying_condition"] is None


def test_child_get_not_found_returns_404():
    """PRD section 2.10: "The first identifier that does not resolve yields
    `ERR_NOT_FOUND` (HTTP 404), regardless of whether later identifiers would
    also fail."
    PRD section 2.2: the error envelope carries `response_type` "error" and a
    `meta` object with `api_request_id`.

    Design: Corner/entities/child_get_not_found_returns_404
    """
    resp = api_client.get_child(NON_EXISTENT_UUID, WISH_COORDINATOR)
    validate_error(resp, ApiErrorId.ERR_NOT_FOUND)
    body = resp.json()
    assert body["response_type"] == "error"
    assert body["meta"]["api_request_id"], "error envelope must carry meta.api_request_id"


def test_referral_create_missing_required_child_dob_invalid_request():
    """PRD section 2.8: "then body well-formedness (`ERR_INVALID_REQUEST`):
    required fields present, types correct, enum values within their declared
    sets, dates parseable"
    PRD section 3.2 lists `child_date_of_birth` in the intake payload.

    Design: Corner/entities/referral_create_missing_required_child_dob_invalid_request
    """
    payload = create_referral_payload()
    del payload["child_date_of_birth"]
    resp = api_client.create_referral(payload, REFERRAL_SOURCE)
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)


def test_donation_offer_computed_quantities_on_create():
    """PRD section 3.5: "`quantity_reserved` starts at 0, and
    `quantity_available` is always `quantity_total` minus `quantity_reserved`.
    An offer opens in `AVAILABLE` status"
    PRD section 3.5: "Under `RETAIL_BASIS`, the unit value is simply the full
    `unit_retail_cents`"

    Design: Corner/entities/donation_offer_computed_quantities_on_create
    """
    offer = create_donation_offer(
        category="RETAILER", valuation_method="RETAIL_BASIS",
        quantity_total=10, unit_retail_cents=12000)
    fetched = api_client.get_donation_offer(offer["id"], IN_KIND_OFFICER)
    data = validate_success(fetched)
    assert_donation_offer(data)
    assert data["quantity_reserved"] == 0
    assert data["quantity_available"] == 10
    assert data["fmv_unit_cents"] == 12000
    assert data["status"] == "AVAILABLE"


def test_volunteer_create_initial_state_applied():
    """PRD section 3.1: "A new volunteer starts in `APPLIED` status and
    advances along a strict one-step ladder"
    PRD section 2.4: "an integer `version` that starts at 1 on creation and
    increments by exactly one each time the resource changes"

    Design: Corner/entities/volunteer_create_initial_state_applied
    """
    chapter = create_chapter()
    volunteer = create_volunteer(chapter["id"], full_name="Nina Park",
                                 email="nina@example.org")
    fetched = get_volunteer(volunteer["id"])
    assert_volunteer(fetched)
    assert fetched["status"] == "APPLIED"
    assert fetched["version"] == 1
