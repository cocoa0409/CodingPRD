"""Entity shapes: declared fields, defaults, system fields and reference integrity.

Everything asserted here comes from PRD s2.2-s2.4 (envelope, identity, ordering),
s2.8 (shape validation) and the per-entity paragraphs of s3.
"""

from prd_bench_local_runner.testing import validate_error, validate_success

from test_helpers.api_errors import (
    ERR_ATHLETE_NOT_FOUND,
    ERR_COLLECTIVE_NOT_FOUND,
    ERR_CROSS_COLLECTIVE_REFERENCE,
    ERR_INVALID_REQUEST,
)
from test_helpers.assertions import (
    assert_append_only_shape,
    assert_collective_ledger,
    assert_contract_dimensions,
    assert_contract_money,
    assert_error_envelope_shape,
    assert_pagination_meta,
    assert_sequence_no_ascending,
    assert_system_fields,
    assert_timestamp_equals,
    read_data,
    rows_of,
)
from test_helpers.factories import (
    athlete_payload,
    collective_payload,
    commitment_payload,
    communication_log_payload,
    donor_member_payload,
    membership_tier_payload,
)
from test_helpers.fixtures import (
    build_athlete,
    build_collective,
    build_donor,
    build_draft_contract,
    build_open_tier,
    read_athlete,
)
from test_helpers.test_users import (
    make_admin_headers,
    make_compliance_headers,
    make_director_headers,
)

ABSENT_UUID = "00000000-0000-4000-8000-000000000000"
OTHER_ABSENT_UUID = "00000000-0000-4000-8000-0000000000ff"


def test_collective_creation_returns_every_declared_field(api):
    """Five required inputs are enough, and every remaining field is server-supplied.

    PRD s3.1: "`entity_structure`, which defaults to `FOR_PROFIT_LLC`"; "
    `communication_policy`, which defaults to `STRICT_SEPARATION`"; and "the row is
    stamped with `version` 1, a `structure_effective_at` equal to the current logical
    clock reading, a `structure_change_count` of 0, and a `funding_posture` of `OPEN`",
    while "The four ledger figures ... all begin at zero". PRD s3.1 also fixes
    charitable_deduction_enabled as "true if and only if `entity_structure` is
    `NONPROFIT_501C3`".

    Design: Corner/entities/collective_creation_returns_all_declared_fields
    """
    response = api.create_collective(
        collective_payload(
            "020100",
            name="Corner Collective",
            institution_name="Corner Institution",
            home_state_code="TX",
            association_ruleset="NCAA_2024",
        ),
        make_admin_headers(),
    )
    collective = read_data(response, expected_status=201)
    body = response.json()
    assert set(body.keys()) == {"meta", "response_type", "data"}
    assert body["response_type"] == "object"

    assert_system_fields(collective)
    assert collective["version"] == 1
    assert collective["name"] == "Corner Collective"
    assert collective["institution_name"] == "Corner Institution"
    assert collective["institution_ipeds_code"] == "020100"
    assert collective["home_state_code"] == "TX"
    assert collective["association_ruleset"] == "NCAA_2024"
    assert collective["entity_structure"] == "FOR_PROFIT_LLC"
    assert collective["communication_policy"] == "STRICT_SEPARATION"
    assert collective["charitable_deduction_enabled"] is False
    assert collective["structure_change_count"] == 0
    assert_collective_ledger(
        collective,
        settled_net_funds_cents=0,
        committed_unreleased_cents=0,
        released_total_cents=0,
        reversed_total_cents=0,
        funding_posture="OPEN",
    )
    assert_timestamp_equals(collective["created_at"], "2026-08-01T00:00:00Z")
    assert_timestamp_equals(collective["updated_at"], "2026-08-01T00:00:00Z")
    assert_timestamp_equals(collective["structure_effective_at"], "2026-08-01T00:00:00Z")


def test_deal_contract_retrieval_echoes_the_stored_row(api):
    """A detail GET reports the three status dimensions and the derived deal_kind.

    PRD s3.8 states that an individually negotiated contract "is stamped with
    `deal_kind` `INDIVIDUAL` and a null `allocation_batch_code`", begins in
    `lifecycle_status` `DRAFT` with `payment_status` `UNPAID`, and that a face value at
    or above the disclosure threshold starts in `DISCLOSURE_PENDING`.

    Design: Corner/entities/deal_contract_retrieval_returns_stored_values
    """
    collective = build_collective(
        api,
        "020200",
        name="Retrieval Collective",
        institution_name="Retrieval Institution",
        home_state_code="OH",
        association_ruleset="NCAA_2026",
    )
    athlete = build_athlete(
        api, collective["id"], "ath-ret", full_name="Ret Athlete", sport="FOOTBALL"
    )
    created = build_draft_contract(api, collective["id"], athlete["id"], 100000)

    fetched = read_data(api.get_deal_contract(created["id"], make_compliance_headers()))
    assert fetched["id"] == created["id"]
    assert fetched["deal_kind"] == "INDIVIDUAL"
    assert fetched["allocation_batch_code"] is None
    assert_contract_dimensions(
        fetched,
        lifecycle_status="DRAFT",
        payment_status="UNPAID",
        disclosure_status="DISCLOSURE_PENDING",
    )
    assert_contract_money(
        fetched,
        total_value_cents=100000,
        released_total_cents=0,
        deliverable_value_total_cents=0,
        clawback_amount_cents=0,
        termination_reason="NONE",
    )
    assert_timestamp_equals(fetched["effective_start_at"], "2026-08-01T00:00:00Z")
    assert_timestamp_equals(fetched["effective_end_at"], "2026-12-31T00:00:00Z")


def test_donor_listing_pages_after_the_filter_is_applied(api):
    """total_count counts filter matches, not page rows, and paging follows sequence_no.

    PRD s2.3: "`total_count` is the number of rows matching the filters before
    pagination is applied and `has_more` is true exactly when rows remain beyond the
    current page", and "`sequence_no` ascending is the sort order for every list
    endpoint in this specification".

    Design: Corner/entities/donor_member_listing_paginates_with_total_count_and_has_more
    """
    collective = build_collective(
        api,
        "020300",
        name="Paging Collective",
        institution_name="Paging Institution",
        home_state_code="CA",
        association_ruleset="NAIA",
    )
    tier = build_open_tier(api, collective["id"], "T1", 10000, 1)
    build_donor(
        api, collective["id"], tier["id"], display_name="Donor One", email="one@example.com"
    )
    build_donor(
        api, collective["id"], tier["id"], display_name="Donor Two", email="two@example.com"
    )
    third = build_donor(
        api,
        collective["id"],
        tier["id"],
        display_name="Donor Three",
        email="three@example.com",
    )

    response = api.list_donor_members(
        {"collective_id": collective["id"], "limit": 2, "offset": 2},
        make_director_headers(),
    )
    validate_success(response)
    rows = rows_of(response)
    assert len(rows) == 1
    assert rows[0]["id"] == third["id"]
    assert rows[0]["display_name"] == "Donor Three"
    assert_pagination_meta(
        response.json()["meta"], limit=2, offset=2, total_count=3, has_more=False
    )

    all_rows = rows_of(
        api.list_donor_members({"collective_id": collective["id"]}, make_director_headers())
    )
    assert_sequence_no_ascending(all_rows)


def test_an_absent_athlete_id_returns_the_athlete_specific_not_found(api):
    """A valid but absent UUID answers with the athlete's own 404 code.

    PRD s2.8, priority 6: "Every entity addressed by a path placeholder exists — the
    matching not-found code, on every endpoint with a path placeholder", and PRD s3.7:
    "an unknown athlete identifier yields `ERR_ATHLETE_NOT_FOUND`".

    Design: Corner/entities/get_athlete_with_unknown_uuid_returns_not_found
    """
    build_collective(
        api,
        "020400",
        name="NotFound Collective",
        institution_name="NotFound Institution",
        home_state_code="FL",
        association_ruleset="NCAA_2024",
    )

    response = api.get_athlete(ABSENT_UUID, make_compliance_headers())
    validate_error(response, ERR_ATHLETE_NOT_FOUND, expected_status=404)
    error = assert_error_envelope_shape(response)
    assert error["message"], "The catalog message must be a non-empty string"


def test_athlete_creation_without_a_portal_handle_fails_shape_validation(api):
    """portal_user_id is required and has no default, so omitting it is a 400.

    PRD s3.7 names "the `portal_user_id` that the athlete will present as their login
    handle" among the required inputs, and PRD s2.8 places "Request body and query shape
    — `ERR_INVALID_REQUEST`" at priority 5, where "every field the endpoint declares
    required is present and of the declared type".

    Design: Corner/entities/create_athlete_missing_portal_user_id_returns_invalid_request
    """
    collective = build_collective(
        api,
        "020500",
        name="Required Collective",
        institution_name="Required Institution",
        home_state_code="AL",
        association_ruleset="NAIA",
    )

    response = api.create_athlete(
        athlete_payload(
            collective["id"], None, full_name="No Portal Id", sport="SOFTBALL", class_year=2028
        ),
        make_director_headers(),
    )
    validate_error(response, ERR_INVALID_REQUEST, expected_status=400)

    listed = api.list_athletes({"collective_id": collective["id"]}, make_director_headers())
    assert rows_of(listed) == []
    assert listed.json()["meta"]["total_count"] == 0


def test_a_commitment_defaults_installments_total_to_one(api):
    """The optional installment count defaults to 1, not to 0 and not to null.

    PRD s3.4: "optionally `installments_total`, which defaults to 1 and is at least 1",
    and "The new commitment starts in `status` `ACTIVE` with `installments_charged` 0,
    `pause_reason` `NONE`, a null `superseded_by_commitment_id`, and the next commitment
    `sequence_no`." PRD s3.3 defines active_commitment_count as "the number of
    commitments whose owning donor member sits on that tier and whose `status` is
    `ACTIVE` or `PAST_DUE`".

    Design: Corner/entities/commitment_defaults_installments_total_to_one_when_omitted
    """
    collective = build_collective(
        api,
        "020600",
        name="Defaults Collective",
        institution_name="Defaults Institution",
        home_state_code="TX",
        association_ruleset="NCAA_2026",
    )
    tier = build_open_tier(api, collective["id"], "T2", 50000, 2)
    donor = build_donor(
        api, collective["id"], tier["id"], display_name="Def Donor", email="def@example.com"
    )

    commitment = read_data(
        api.create_commitment(
            commitment_payload(
                donor["id"],
                "MAJOR_GIFT_PLEDGE",
                250000,
                "NONE",
                expected_donor_member_version=donor["version"],
            ),
            make_director_headers(),
        ),
        expected_status=201,
    )
    assert commitment["installments_total"] == 1
    assert commitment["installments_charged"] == 0
    assert commitment["status"] == "ACTIVE"
    assert commitment["pause_reason"] == "NONE"
    assert commitment["superseded_by_commitment_id"] is None
    assert commitment["sequence_no"] == 1

    refreshed_tier = read_data(api.get_membership_tier(tier["id"], make_director_headers()))
    assert refreshed_tier["active_commitment_count"] == 1


def test_athlete_system_fields_come_from_the_server(api):
    """Two athletes take sequence_no 1 and 2 from the per-entity-type counter.

    PRD s2.4: "`sequence_no`, a monotonic per-entity-type insertion counter that starts
    at 1, is assigned when the row is created, is never reused", while "The `id` is used
    for identity only. It is never a selector for business logic, never a ranking input".
    PRD s3.7 fixes the remaining defaults: roster_weight "defaults to 1",
    tax_person_kind "defaults to `US_PERSON`", and "A new athlete begins in
    `eligibility_status` `ENROLLED` with `taxpayer_doc_on_file` `NONE`,
    `treaty_exempt_claimed` false".

    Design: Corner/entities/athlete_system_fields_generated_and_client_values_ignored
    """
    collective = build_collective(
        api,
        "020800",
        name="System Collective",
        institution_name="System Institution",
        home_state_code="CA",
        association_ruleset="NCAA_2026",
    )

    first = build_athlete(
        api,
        collective["id"],
        "ath-sys1",
        full_name="Sys One",
        sport="BASEBALL",
        class_year=2027,
    )
    second = build_athlete(
        api,
        collective["id"],
        "ath-sys2",
        full_name="Sys Two",
        sport="BASEBALL",
        class_year=2027,
    )

    assert first["sequence_no"] == 1
    assert second["sequence_no"] == 2
    assert first["id"] != second["id"]
    assert_system_fields(first)
    assert first["version"] == 1
    assert_timestamp_equals(first["created_at"], "2026-08-01T00:00:00Z")

    stored = read_athlete(api, first["id"])
    assert stored["roster_weight"] == 1
    assert stored["tax_person_kind"] == "US_PERSON"
    assert stored["taxpayer_doc_on_file"] == "NONE"
    assert stored["treaty_exempt_claimed"] is False
    assert stored["eligibility_status"] == "ENROLLED"
    assert stored["tax_form_required"] == "NONE"


def test_an_unknown_sport_and_an_out_of_range_class_year_are_both_refused(api):
    """Both closed domains are enforced at priority 5, before any business rule.

    PRD s3.7: "the `sport` — one of `FOOTBALL`, `MENS_BASKETBALL`,
    `WOMENS_BASKETBALL`, `BASEBALL` or `SOFTBALL` — and the `class_year`, an academic
    year from 2026 through 2031 inclusive". PRD s2.8 checks in one pass that "every enum
    field carries a declared value" and that "`class_year` is between 2026 and 2031
    inclusive".

    Design: Corner/entities/create_athlete_with_unknown_sport_enum_returns_invalid_request
    """
    collective = build_collective(
        api,
        "020900",
        name="Enum Collective",
        institution_name="Enum Institution",
        home_state_code="TX",
        association_ruleset="NCAA_2024",
    )

    bad_sport = api.create_athlete(
        athlete_payload(
            collective["id"], "ath-bad", full_name="Bad Sport", sport="LACROSSE", class_year=2028
        ),
        make_director_headers(),
    )
    validate_error(bad_sport, ERR_INVALID_REQUEST, expected_status=400)

    bad_year = api.create_athlete(
        athlete_payload(
            collective["id"], "ath-bad", full_name="Bad Year", sport="SOFTBALL", class_year=2025
        ),
        make_director_headers(),
    )
    validate_error(bad_year, ERR_INVALID_REQUEST, expected_status=400)

    assert rows_of(
        api.list_athletes({"collective_id": collective["id"]}, make_director_headers())
    ) == []


def test_a_communication_record_carries_no_version_and_no_updated_at(api):
    """The append-only log is frozen at write time, verdict included.

    PRD s2.4: "The communication log is the sole exception: a communication record
    carries only `id` and `created_at`. It has no `updated_at` and no `version` field at
    all, because it is append-only". PRD s3.1 adds that the fourth verdict clause applies
    "Otherwise the `verdict` is `PERMITTED` with `rationale_code` `POLICY_ALLOWS`", and
    that each record "is stamped with `logged_at` from the logical clock".

    Design: Corner/entities/communication_log_is_immutable_with_no_version_field
    """
    collective = build_collective(
        api,
        "021000",
        name="Immutable Collective",
        institution_name="Immutable Institution",
        home_state_code="OH",
        association_ruleset="NCAA_2026",
    )
    athlete = build_athlete(
        api, collective["id"], "ath-imm", full_name="Imm Athlete", sport="FOOTBALL"
    )

    record = read_data(
        api.create_communication_log(
            communication_log_payload(
                collective["id"],
                "COLLECTIVE_DIRECTOR",
                "INSTITUTION_PORTAL",
                "GENERAL_PROGRAM",
                athlete_id=athlete["id"],
                note="roster update",
            ),
            make_director_headers(),
        ),
        expected_status=201,
    )
    assert record["verdict"] == "PERMITTED"
    assert record["rationale_code"] == "POLICY_ALLOWS"
    assert record["sequence_no"] == 1
    assert_append_only_shape(record)
    assert_timestamp_equals(record["logged_at"], "2026-08-01T00:00:00Z")

    fetched = read_data(api.get_communication_log(record["id"], make_director_headers()))
    assert_append_only_shape(fetched)
    assert fetched["verdict"] == "PERMITTED"


def test_a_tier_under_an_absent_collective_is_a_parent_not_found(api):
    """The nested path resolves its outer entity first and creates no orphan.

    PRD s2.9: "Nested paths are validated left to right — the outer entity is resolved
    first, so addressing a tier collection under an unknown collective yields
    `ERR_COLLECTIVE_NOT_FOUND` ... before any body field is examined."

    Design: Corner/entities/create_membership_tier_under_unknown_collective_returns_not_found
    """
    collective = build_collective(
        api,
        "021100",
        name="Parent Collective",
        institution_name="Parent Institution",
        home_state_code="FL",
        association_ruleset="NAIA",
    )

    response = api.create_membership_tier(
        OTHER_ABSENT_UUID,
        membership_tier_payload("T1", 10000, 1, tier_name="Ghost"),
        make_director_headers(),
    )
    validate_error(response, ERR_COLLECTIVE_NOT_FOUND, expected_status=404)

    listed = api.list_membership_tiers(collective["id"], None, make_director_headers())
    assert rows_of(listed) == []
    assert listed.json()["meta"]["total_count"] == 0


def test_a_tier_of_another_collective_is_a_cross_collective_conflict(api):
    """The referenced tier exists, so the answer is 409 rather than 404.

    PRD s2.9: "all entities named in a single request must belong to the same
    collective: a donor member's `membership_tier_id` must name a tier of the collective
    given by its `collective_id` ... A violation is `ERR_CROSS_COLLECTIVE_REFERENCE`
    (HTTP 409)."

    Design: Corner/entities/cross_collective_donor_and_tier_reference_rejected
    """
    alpha = build_collective(
        api,
        "021200",
        name="Alpha Collective",
        institution_name="Alpha Institution",
        home_state_code="TX",
        association_ruleset="NCAA_2024",
    )
    beta = build_collective(
        api,
        "021300",
        name="Beta Collective",
        institution_name="Beta Institution",
        home_state_code="CA",
        association_ruleset="NCAA_2024",
    )
    beta_tier = build_open_tier(api, beta["id"], "T1", 10000, 1)

    response = api.create_donor_member(
        donor_member_payload(
            alpha["id"],
            beta_tier["id"],
            display_name="Wrong Tier Donor",
            email="wrong@example.com",
        ),
        make_director_headers(),
    )
    validate_error(response, ERR_CROSS_COLLECTIVE_REFERENCE, expected_status=409)
    assert_error_envelope_shape(response)

    stored_tier = read_data(api.get_membership_tier(beta_tier["id"], make_director_headers()))
    assert stored_tier["active_commitment_count"] == 0
    listed = api.list_donor_members({"collective_id": alpha["id"]}, make_director_headers())
    assert listed.json()["meta"]["total_count"] == 0
