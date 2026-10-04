"""Queue B / entities: envelope, round-trip, listing, 404, cycle defaults."""
from test_helpers import (
    api_client, validate_success, validate_error, validate_paginated,
    ApiErrorId, TEST_USERS, NON_EXISTENT_UUID,
    make_applicant, make_reference_product, make_application,
    add_be_study, submit_application, list_cycles, make_applicant_headers,
    assert_applicant_company, assert_reference_product,
)

ADMIN = TEST_USERS["program_admin_headers"]
REVIEWER = TEST_USERS["regulatory_reviewer_headers"]


def test_applicant_create_envelope_defaults_and_fixed_clock():
    """PRD section 2.4: "Before any administrative action is taken, the
    logical clock reads exactly 2026-09-01T00:00:00Z." PRD section 2.5:
    "`version` is an integer that the server increments by one on every
    mutation of the resource." The creation response carries the full envelope
    and the pinned creation instant.

    Design: Corner/entities/applicant_company_create_returns_envelope_defaults_and_fixed_clock
    """
    resp = api_client.create_applicant_company({
        "legal_name": "Envelope Pharma", "contact_email": "reg@env.example",
        "headquarters_country": "US"}, ADMIN)
    assert resp.status_code == 201
    body = resp.json()
    assert body["response_type"] == "object"
    assert body["meta"]["api_request_id"] and body["meta"]["api_request_timestamp"]
    data = body["data"]
    assert_applicant_company(data)
    assert data["legal_name"] == "Envelope Pharma"
    assert data["headquarters_country"] == "US"
    assert data["version"] == 1
    assert data["created_at"].startswith("2026-09-01T00:00:00"), (
        f"created_at is stamped from the pinned logical clock, got {data['created_at']}")


def test_reference_product_get_round_trips_full_configuration():
    """PRD section 3.1: "The product's full set of approved indication codes
    is recorded in `indication_codes`, and `patent_owner_user_id` stores the
    opaque `X-User-ID` of the `InnovatorSponsor` authorized to list patents
    and report litigation for this product."

    Design: Corner/entities/reference_product_get_round_trips_full_configuration
    """
    rld = make_reference_product(
        brand_name="Roundtrip", active_ingredient="roundtripol", strength="55 mg",
        dosage_form="CAPSULE", rld_approval_date="2015-02-14",
        is_new_chemical_entity=False, indication_codes=["IND-A", "IND-B"],
        patent_owner_user_id="innovator-ops-50")
    fetched = validate_success(api_client.get_reference_product(rld["id"], REVIEWER), 200)
    assert_reference_product(fetched)
    assert fetched["rld_approval_date"] == "2015-02-14"
    assert fetched["is_new_chemical_entity"] is False
    assert fetched["indication_codes"] == ["IND-A", "IND-B"]
    assert fetched["patent_owner_user_id"] == "innovator-ops-50"


def test_applications_list_filters_by_applicant_and_paginates():
    """PRD section 2.3: "`limit` caps the number of returned items: it
    defaults to 10, accepts a minimum of 1 and a maximum of 100. `offset`
    skips that many items from the start of the collection and defaults to 0."
    and list endpoints "additionally accept an optional `status` filter or
    reverse foreign-key filters such as `applicant_id`".

    Design: Corner/entities/applications_list_filters_by_applicant_and_paginates
    """
    ac_a = make_applicant(legal_name="Lister A", contact_email="a@la.example")
    ac_b = make_applicant(legal_name="Lister B", contact_email="b@lb.example")
    rld = make_reference_product(brand_name="Listex", rld_approval_date="2010-01-01")
    make_application(rld["id"], ac_a["id"], review_priority="STANDARD")
    make_application(rld["id"], ac_a["id"], review_priority="PRIORITY")
    make_application(rld["id"], ac_a["id"], review_priority="STANDARD")
    make_application(rld["id"], ac_b["id"])

    rows, meta = validate_paginated(api_client.list_applications(
        ADMIN, params={"applicant_id": ac_a["id"], "limit": 2, "offset": 0}))
    assert len(rows) == 2 and meta["total_count"] == 3 and meta["has_more"] is True

    rows, meta = validate_paginated(api_client.list_applications(
        ADMIN, params={"applicant_id": ac_a["id"], "limit": 2, "offset": 2}))
    assert len(rows) == 1 and meta["total_count"] == 3 and meta["has_more"] is False

    rows, _ = validate_paginated(api_client.list_applications(
        ADMIN, params={"applicant_id": ac_b["id"]}))
    assert len(rows) == 1

    rows, meta = validate_paginated(api_client.list_applications(
        ADMIN, params={"status": "DRAFT"}))
    assert len(rows) == 4 and meta["limit"] == 10 and meta["offset"] == 0


def test_application_get_with_unknown_id_returns_not_found():
    """PRD section 2.7: "Fourth, identifiers must resolve: path identifiers
    are validated left to right, then body-referenced identifiers
    (`reference_product_id`, `patent_id`, `facility_id`, `application_id`) in
    the endpoint's input declaration order, each unresolvable identifier
    producing its own 404" — for an unknown application id that is
    `ERR_APPLICATION_NOT_FOUND`.

    Design: Corner/entities/application_get_with_unknown_id_returns_application_not_found
    """
    resp = api_client.get_application(NON_EXISTENT_UUID, ADMIN)
    validate_error(resp, ApiErrorId.ERR_APPLICATION_NOT_FOUND)
    assert resp.status_code == 404


def test_review_cycle_snapshot_defaults_at_submit():
    """PRD section 3.3: "A successful filing stamps `received_date` with the
    current logical date, sets `current_cycle_number` to 1, and opens the
    first `ReviewCycle` in `OPEN` status with `opened_date` equal to the
    receipt date and `base_review_months` snapshotted at 8 for a `PRIORITY`
    application or 10 for a `STANDARD` one."

    Design: Corner/entities/review_cycle_snapshot_defaults_at_submit
    """
    applicant = make_applicant(legal_name="Defaults Co")
    rld = make_reference_product(brand_name="Defaultex")
    app = make_application(rld["id"], applicant["id"])
    add_be_study(app["id"], applicant["id"])
    submit_application(app["id"], applicant["id"])

    cycles = list_cycles(app["id"])
    assert len(cycles) == 1
    cycle = cycles[0]
    assert cycle["cycle_number"] == 1 and cycle["status"] == "OPEN"
    assert cycle["base_review_months"] == 10
    assert cycle["major_amendment_extensions_count"] == 0
    assert cycle["goal_date"] == "2027-07-01", "2026-09-01 + 10 calendar months"
