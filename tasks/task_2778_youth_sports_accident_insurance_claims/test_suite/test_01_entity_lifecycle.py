"""Entity lifecycle: master data, policy quotes, rosters and their system fields.

The program's master data is authored by the underwriting desk, its policy quotes
are priced the moment they are written, and its athlete-level fields are
projections of the enrollment rows beneath them. These tests pin the declared
defaults, the echoed benefit schedule, the paginated reads, the request-shape and
reference-resolution failures, and the four system-managed properties every
resource in the program carries.
"""
import re

from test_helpers import (
    NON_EXISTENT_UUID,
    ApiErrorId,
    add_participant,
    assert_enrollment,
    assert_league,
    assert_league_policy,
    assert_participant,
    assert_sport_classification,
    canonical_iso,
    create_enrollment_payload,
    create_league,
    create_league_payload,
    create_league_policy_payload,
    create_sport_classification,
    create_sport_classification_payload,
    is_valid_uuid,
    make_claims_examiner_headers,
    make_league_admin_headers,
    make_program_admin_headers,
    read_participant,
    setup_active_policy,
    validate_error,
    validate_paginated,
    validate_success,
)

# An ISO 8601 UTC timestamp carrying exactly three fractional-second digits.
THREE_FRACTIONAL_DIGITS = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}Z$")


def test_registering_a_league_echoes_every_declared_field_and_starts_sanctioned(api):
    """PRD §3.1: "A `ProgramAdministrator` registers a **League** by supplying its legal `name`, a short operator-assigned `league_code`, the two-letter `state_code` of the US state in which it operates, the `governing_body_code` of the national body that sanctions it, and a `contact_email` for the league administrator of record."
    PRD §3.1: "A newly registered league starts with `sanctioning_status` set to `SANCTIONED` and `in_force_policy_count` set to 0."
    PRD §2.4: "`version` — an integer that starts at 1 and increments by one on every mutation of the row."
    PRD §4: "Endpoints that create a new resource return HTTP 201; every other successful call returns HTTP 200."

    Design: Corner/entities/league_creation_returns_declared_fields_with_sanctioned_default
    """
    response = api.create_league(
        create_league_payload(
            name="Ashfield Youth Sports",
            league_code="AYS-100",
            state_code="CO",
            governing_body_code="USYSA",
            contact_email="admin@ays.example",
        ),
        make_program_admin_headers(),
    )
    league = validate_success(response, 201)
    assert response.json()["response_type"] == "object", (
        "a single created league is returned as an object, got "
        f"{response.json()['response_type']!r}"
    )
    assert_league(league)

    assert league["name"] == "Ashfield Youth Sports", league["name"]
    assert league["league_code"] == "AYS-100", league["league_code"]
    assert league["state_code"] == "CO", league["state_code"]
    assert league["governing_body_code"] == "USYSA", league["governing_body_code"]
    assert league["contact_email"] == "admin@ays.example", league["contact_email"]

    # No sanctioning_status was supplied, so the declared starting value applies.
    assert league["sanctioning_status"] == "SANCTIONED", (
        "a newly registered league starts SANCTIONED, got "
        f"{league['sanctioning_status']!r}"
    )
    assert league["in_force_policy_count"] == 0, (
        "a newly registered league holds no in-force terms, got "
        f"{league['in_force_policy_count']}"
    )
    assert league["version"] == 1, (
        f"version starts at 1, got {league['version']}"
    )
    assert league["id"], "id must be server-minted and non-null"
    assert league["created_at"], "created_at must be server-minted and non-null"
    assert league["updated_at"], "updated_at must be server-minted and non-null"


def test_reading_a_sport_classification_returns_the_stored_benefit_schedule(api):
    """PRD §3.1: "Finally, the classification carries the benefit schedule itself as `service_category_caps` — a map from a service category to the maximum allowed amount in cents for that category."
    PRD §3.1: "Its keys must be a subset of the seven recognised categories `EMERGENCY_ROOM`, `SURGERY`, `DIAGNOSTIC_IMAGING`, `PHYSICAL_THERAPY`, `DENTAL`, `AMBULANCE` and `PHYSICIAN_OFFICE`, and every value must be an integer of zero or more cents; a map containing a key outside that set is a request-shape failure."
    PRD §3.1: "The hazard class immediately determines the echoed `hazard_load_bps` field: a low-hazard sport carries no load at all, a moderate-hazard sport carries 1150 basis points, a high-hazard sport 2625 basis points, and a contact sport 4075 basis points — so writing a contact sport costs a little over forty percent more per athlete than writing the same rate at low hazard."
    PRD §3.1: "`deductible_cents` is the per-claim deductible the program applies when it pays excess of other insurance, and may be zero."
    PRD §3.1: "`travel_buffer_minutes`, which may be zero, is the default buffer applied on both sides of an activity window when looking for athlete scheduling collisions."

    Design: Corner/entities/sport_classification_get_by_id_returns_stored_benefit_schedule
    """
    caps = {
        "EMERGENCY_ROOM": 400000,
        "SURGERY": 1500000,
        "DIAGNOSTIC_IMAGING": 250000,
        "PHYSICAL_THERAPY": 18000,
        "DENTAL": 200000,
        "AMBULANCE": 150000,
        "PHYSICIAN_OFFICE": 40000,
    }
    created = validate_success(
        api.create_sport_classification(
            create_sport_classification_payload(
                sport_code="SOCCER_U10",
                sport_name="Soccer U10",
                hazard_class="CLASS_2_MODERATE",
                base_rate_per_participant_cents=1600,
                deductible_cents=20000,
                per_injury_limit_cents=1000000,
                cat_attachment_point_cents=1000000,
                aggregate_limit_cents=10000000,
                cat_lifetime_max_cents=5000000,
                minimum_participants=20,
                travel_buffer_minutes=45,
                service_category_caps=dict(caps),
            ),
            make_program_admin_headers(),
        ),
        201,
    )

    # The claims desk reads master data it did not author.
    fetched = validate_success(
        api.get_sport_classification(created["id"], make_claims_examiner_headers())
    )
    assert_sport_classification(fetched)

    assert fetched["id"] == created["id"], "GET by id must return the row just written"
    assert fetched["sport_code"] == "SOCCER_U10", fetched["sport_code"]
    assert fetched["sport_name"] == "Soccer U10", fetched["sport_name"]
    assert fetched["hazard_class"] == "CLASS_2_MODERATE", fetched["hazard_class"]
    assert fetched["hazard_load_bps"] == 1150, (
        "a CLASS_2_MODERATE sport carries a hazard load of 1150 basis points, got "
        f"{fetched['hazard_load_bps']}"
    )
    assert fetched["base_rate_per_participant_cents"] == 1600, (
        fetched["base_rate_per_participant_cents"]
    )
    assert fetched["deductible_cents"] == 20000, fetched["deductible_cents"]
    assert fetched["per_injury_limit_cents"] == 1000000, fetched["per_injury_limit_cents"]
    assert fetched["cat_attachment_point_cents"] == 1000000, (
        fetched["cat_attachment_point_cents"]
    )
    assert fetched["aggregate_limit_cents"] == 10000000, fetched["aggregate_limit_cents"]
    assert fetched["cat_lifetime_max_cents"] == 5000000, fetched["cat_lifetime_max_cents"]
    assert fetched["minimum_participants"] == 20, fetched["minimum_participants"]
    assert fetched["travel_buffer_minutes"] == 45, fetched["travel_buffer_minutes"]

    assert fetched["service_category_caps"] == caps, (
        "the whole seven-key benefit schedule must be returned unchanged, got "
        f"{fetched['service_category_caps']!r}"
    )
    assert set(fetched["service_category_caps"]) == set(caps), (
        "no benefit category may be dropped or invented"
    )


def test_roster_list_of_three_athletes_pages_at_limit_two_with_a_whole_set_total(api):
    """PRD §2.3: "`limit` sets the maximum number of rows returned; it defaults to 10 when absent, must be at least 1, and must not exceed 100."
    PRD §2.3: "`offset` sets how many rows to skip; it defaults to 0 and must not be negative."
    PRD §2.3: "Unless a specific endpoint says otherwise, list results are sorted by `created_at` in ascending order."
    PRD §2.3: "Every list response carries `limit`, `offset`, `total_count` and `has_more` inside the `meta` object of the envelope."
    PRD §2.3: "Participants may be filtered by `league_id` and `roster_status`."

    Design: Corner/entities/participant_list_paginates_with_total_count_and_has_more
    """
    league = create_league(
        name="Brookline Youth Sports",
        league_code="BYS-101",
        state_code="MA",
        governing_body_code="USYSA",
        contact_email="admin@bys.example",
    )
    league_headers = make_league_admin_headers(league["id"])

    expected_ids = []
    for first_name, last_name, dob, email in (
        ("Anya", "Petrosyan", "2014-01-15", "g20@bys.example"),
        ("Bo", "Nakamura", "2014-02-16", "g21@bys.example"),
        ("Cleo", "Mbeki", "2014-03-17", "g22@bys.example"),
    ):
        athlete = add_participant(
            league["id"],
            first_name=first_name,
            last_name=last_name,
            date_of_birth=dob,
            guardian_email=email,
        )
        expected_ids.append(athlete["id"])

    first_page, first_meta = validate_paginated(
        api.list_participants(
            league_headers, {"league_id": league["id"], "limit": 2, "offset": 0}
        )
    )
    assert len(first_page) == 2, f"limit 2 must return 2 rows, got {len(first_page)}"
    assert first_meta["limit"] == 2, first_meta["limit"]
    assert first_meta["offset"] == 0, first_meta["offset"]
    assert first_meta["total_count"] == 3, (
        "total_count counts the whole filtered roster, not the page, got "
        f"{first_meta['total_count']}"
    )
    assert first_meta["has_more"] is True, (
        "one athlete is still unread after the first page of two"
    )

    second_page, second_meta = validate_paginated(
        api.list_participants(
            league_headers, {"league_id": league["id"], "limit": 2, "offset": 2}
        )
    )
    assert len(second_page) == 1, (
        f"the third athlete is the only row left, got {len(second_page)}"
    )
    assert second_meta["offset"] == 2, second_meta["offset"]
    assert second_meta["total_count"] == 3, second_meta["total_count"]
    assert second_meta["has_more"] is False, (
        "nothing follows the last athlete on the roster"
    )

    paged_ids = [row["id"] for row in first_page] + [row["id"] for row in second_page]
    assert len(set(paged_ids)) == 3, f"no athlete may appear twice, got {paged_ids}"
    assert set(paged_ids) == set(expected_ids), (
        "the two pages together must cover the whole roster"
    )
    assert paged_ids == expected_ids, (
        "athletes are returned in ascending created_at order, got "
        f"{paged_ids} for {expected_ids}"
    )
    for row in first_page + second_page:
        assert_participant(row)


def test_reading_a_policy_id_that_matches_no_term_reports_the_policy_as_not_found(api):
    """PRD §2.6: "Both are resolved before any business rule runs, and both are resolved in a fixed order so that failures are reproducible."
    PRD §2.6: "The first segment that does not resolve to a live row determines the response, which is the 404 code naming that entity: `ERR_LEAGUE_NOT_FOUND`, `ERR_SPORT_CLASSIFICATION_NOT_FOUND`, `ERR_LEAGUE_POLICY_NOT_FOUND`, `ERR_PARTICIPANT_NOT_FOUND`, `ERR_ENROLLMENT_NOT_FOUND`, `ERR_FAMILY_HEALTH_PLAN_NOT_FOUND`, `ERR_SANCTIONED_ACTIVITY_NOT_FOUND`, `ERR_INJURY_REPORT_NOT_FOUND`, `ERR_CLAIM_NOT_FOUND`, `ERR_PROVIDER_BILL_NOT_FOUND`, `ERR_COORDINATION_RECORD_NOT_FOUND` or `ERR_BENEFIT_PAYMENT_NOT_FOUND`."

    Design: Corner/entities/unknown_league_policy_id_returns_league_policy_not_found
    """
    response = api.get_league_policy(NON_EXISTENT_UUID, make_program_admin_headers())
    validate_error(
        response, ApiErrorId.ERR_LEAGUE_POLICY_NOT_FOUND, expected_status=404
    )
    assert response.json()["response_type"] == "error", (
        "an unresolved policy identifier is an error, not an empty success"
    )


def test_quoting_a_term_without_an_expiration_date_fails_the_request_shape_check(api):
    """PRD §3.2: "The request names the `league_id` of the holding league and the `sport_classification_id` that fixes the rating basis and every limit, sets the term boundaries `term_effective_date` and `term_expiration_date`, and declares the `enrolled_participant_count` — at least one — that the premium will be rated on."
    PRD §2.7: "4. **Request shape** — every required input field present and non-null; every enum value a declared member of its set; every integer within its declared bound; `provider_npi` exactly ten digits; `state_code` exactly two uppercase letters; every datetime a parseable ISO 8601 UTC instant; `limit` within 1 through 100 and `offset` not negative (`ERR_INVALID_REQUEST`)."
    PRD §2.7: "Checks are evaluated strictly in the sequence below, and the **first** violated check determines the response; no later check is evaluated once one has failed."

    Design: Corner/entities/league_policy_create_without_term_expiration_date_rejected
    """
    league = create_league(
        name="Cardinal Ridge Baseball",
        league_code="CRB-102",
        state_code="MO",
        governing_body_code="USYSA",
        contact_email="admin@crb.example",
    )
    sport = create_sport_classification("baseball")

    payload = create_league_policy_payload(
        league["id"],
        sport["id"],
        term_effective_date="2026-03-01",
        enrolled_participant_count=404,
    )
    del payload["term_expiration_date"]

    validate_error(
        api.create_league_policy(payload, make_program_admin_headers()),
        ApiErrorId.ERR_INVALID_REQUEST,
        expected_status=400,
    )

    rows, meta = validate_paginated(
        api.list_league_policies(
            make_program_admin_headers(), {"league_id": league["id"]}
        )
    )
    assert rows == [], (
        f"a rejected quote must not persist a term, got {len(rows)} rows"
    )
    assert meta["total_count"] == 0, meta["total_count"]


def test_quote_omitting_both_elections_prices_the_term_excess_only_without_the_cat_layer(api):
    """PRD §3.2: "Two optional elections complete the request: `coverage_basis_election`, which is `EXCESS_ONLY` unless the request says `FULL_EXCESS_PERMITTED`, and `cat_layer_elected`, a boolean that is false unless the request says otherwise."
    PRD §3.2: "If `cat_layer_elected` is true, `cat_layer_charge_cents` is the gross premium multiplied by 850 basis points — eight and a half percent — divided by ten thousand and rounded half up to whole cents."
    PRD §3.2: "If the layer was not elected, the charge is exactly 0."
    PRD §3.2: "`premium_subtotal_cents` is the gross premium plus the catastrophic layer charge."
    PRD §3.2: "A subtotal below 500,000 cents (five thousand dollars) earns no credit at all; a subtotal from 500,000 through 1,499,999 cents earns 300 basis points; a subtotal from 1,500,000 through 4,999,999 cents earns 550 basis points; a subtotal of 5,000,000 cents (fifty thousand dollars) or more earns 800 basis points."
    PRD §3.2: "`volume_credit_cents` is the subtotal multiplied by `volume_credit_bps`, divided by ten thousand, and rounded half up to whole cents."
    PRD §3.2: "`annual_premium_cents` is the subtotal less the volume credit, but never less than the program's minimum annual premium of 25,000 cents — two hundred and fifty dollars."
    PRD §3.2: "A newly quoted policy takes `status` `QUOTED` and `renewal_quote_status` `NONE`, and immediately mirrors five figures from its sport classification onto itself — `deductible_cents`, `per_injury_limit_cents`, `cat_attachment_point_cents`, `aggregate_limit_cents` and `cat_lifetime_max_cents` — so that a claim can be determined without traversing back to master data."

    Design: Corner/entities/league_policy_create_applies_coverage_basis_and_cat_layer_defaults
    """
    league = create_league(
        name="Deerfield Baseball League",
        league_code="DBL-103",
        state_code="WI",
        governing_body_code="USYSA",
        contact_email="admin@dbl.example",
    )
    sport = create_sport_classification("baseball")

    payload = create_league_policy_payload(
        league["id"],
        sport["id"],
        term_effective_date="2026-03-01",
        term_expiration_date="2027-03-01",
        enrolled_participant_count=404,
    )
    del payload["coverage_basis_election"]
    del payload["cat_layer_elected"]

    policy = validate_success(
        api.create_league_policy(payload, make_program_admin_headers()), 201
    )
    assert_league_policy(policy)

    assert policy["coverage_basis_election"] == "EXCESS_ONLY", (
        "an unstated coverage basis election is EXCESS_ONLY, got "
        f"{policy['coverage_basis_election']!r}"
    )
    assert policy["cat_layer_elected"] is False, (
        "an unstated catastrophic layer election is false, got "
        f"{policy['cat_layer_elected']!r}"
    )

    # 75 athletes at 1.0000, 325 at 0.9250 and 4 at 0.8500 on a 1850-cent rate,
    # each band line loaded by 1150 basis points and rounded on its own.
    assert policy["gross_premium_cents"] == 781833, policy["gross_premium_cents"]
    assert policy["cat_layer_charge_cents"] == 0, (
        "an unelected catastrophic layer costs exactly 0, got "
        f"{policy['cat_layer_charge_cents']}"
    )
    assert policy["premium_subtotal_cents"] == 781833, policy["premium_subtotal_cents"]
    assert policy["volume_credit_bps"] == 300, (
        "a subtotal of 781833 cents sits in the 300 basis point credit tier, got "
        f"{policy['volume_credit_bps']}"
    )
    assert policy["volume_credit_cents"] == 23455, policy["volume_credit_cents"]
    assert policy["annual_premium_cents"] == 758378, (
        "without the catastrophic layer the same 404-athlete term costs 758378 "
        f"cents, got {policy['annual_premium_cents']}"
    )
    assert policy["status"] == "QUOTED", policy["status"]
    assert policy["renewal_quote_status"] == "NONE", policy["renewal_quote_status"]


def test_enrolling_an_athlete_recomputes_the_roster_fields_the_create_call_never_accepts(api):
    """PRD §3.3: "A newly added athlete begins with `roster_status` `ROSTERED` and `enrolled_policy_count` 0."
    PRD §3.3: "Both of those athlete-level fields are derived from enrollment rows rather than supplied."
    PRD §3.3: "`enrolled_policy_count` is the number of this athlete's enrollments whose `status` is `ENROLLED`."
    PRD §3.3: "`roster_status` is `ROSTERED` while at least one enrollment of the athlete is `ENROLLED`, becomes `INACTIVE` once every enrollment of the athlete has been withdrawn, and — importantly for the moment just after an athlete is added — reads `ROSTERED` when the athlete has no enrollment rows at all."
    PRD §3.3: "A new enrollment starts with `status` `ENROLLED`, `lifetime_cat_benefit_used_cents` 0 and `coverage_status` `COVERED`, and its creation immediately recomputes the athlete's `enrolled_policy_count` and `roster_status`."
    PRD §3.3: "The `withdrawn_on_date` field stays null while the enrollment is live."

    Design: Corner/entities/participant_roster_fields_are_computed_from_enrollments
    """
    bundle = setup_active_policy(
        league_overrides={
            "name": "Elmwood Baseball Association",
            "league_code": "EBA-104",
            "state_code": "KS",
            "governing_body_code": "USYSA",
            "contact_email": "admin@eba.example",
        }
    )
    league_headers = make_league_admin_headers(bundle["league"]["id"])

    athlete = add_participant(
        bundle["league"]["id"],
        first_name="Farid",
        last_name="Karimov",
        date_of_birth="2014-04-18",
        guardian_email="g23@eba.example",
    )
    assert_participant(athlete)

    before = read_participant(athlete["id"])
    assert before["enrolled_policy_count"] == 0, (
        "an athlete with no enrollment rows is enrolled under no policy, got "
        f"{before['enrolled_policy_count']}"
    )
    assert before["roster_status"] == "ROSTERED", (
        "an athlete with no enrollment rows at all reads ROSTERED, got "
        f"{before['roster_status']!r}"
    )

    enrollment = validate_success(
        api.create_enrollment(
            create_enrollment_payload(
                athlete["id"], bundle["policy"]["id"], enrolled_on_date="2026-03-05"
            ),
            league_headers,
        ),
        201,
    )
    assert_enrollment(enrollment)
    assert enrollment["status"] == "ENROLLED", enrollment["status"]
    assert enrollment["coverage_status"] == "COVERED", enrollment["coverage_status"]
    assert enrollment["lifetime_cat_benefit_used_cents"] == 0, (
        enrollment["lifetime_cat_benefit_used_cents"]
    )
    assert enrollment["withdrawn_on_date"] is None, (
        "a live enrollment carries no withdrawal date, got "
        f"{enrollment['withdrawn_on_date']!r}"
    )

    after = read_participant(athlete["id"])
    assert after["enrolled_policy_count"] == 1, (
        "the single ENROLLED enrollment must be counted, got "
        f"{after['enrolled_policy_count']}"
    )
    assert after["roster_status"] == "ROSTERED", after["roster_status"]


def test_recording_probation_on_a_league_refreshes_its_system_fields_to_version_two(api):
    """PRD §2.4: "`id` — a server-minted UUID string."
    PRD §2.4: "It carries no type prefix; the resource's collection, not its identifier, tells you what kind of thing it is."
    PRD §2.4: "`created_at` — an ISO 8601 UTC timestamp with three fractional digits, recording when the row was first written."
    PRD §2.4: "`updated_at` — an ISO 8601 UTC timestamp in the same format, refreshed on every mutation of the row."
    PRD §2.4: "`version` — an integer that starts at 1 and increments by one on every mutation of the row."
    PRD §3.1: "Governing bodies do occasionally discipline leagues, and the underwriting desk records those decisions by submitting a new `sanctioning_status` together with a free-text `reason`."
    PRD §3.1: "Standing moves among exactly three values — `SANCTIONED`, `PROBATION` and `SUSPENDED` — and only along five legal edges: `SANCTIONED → PROBATION`, `SANCTIONED → SUSPENDED`, `PROBATION → SUSPENDED`, `PROBATION → SANCTIONED` and `SUSPENDED → SANCTIONED`."

    Design: Corner/entities/system_fields_are_server_minted_and_version_increments_on_mutation
    """
    league = create_league(
        name="Fairmount Athletic League",
        league_code="FAL-105",
        state_code="OR",
        governing_body_code="USYSA",
        contact_email="admin@fal.example",
    )
    assert league["version"] == 1, f"a freshly registered league is at version 1, got {league['version']}"
    assert league["sanctioning_status"] == "SANCTIONED", league["sanctioning_status"]

    minted_id = league["id"]
    assert is_valid_uuid(minted_id), f"id must be a bare UUID, got {minted_id!r}"
    assert len(minted_id) == 36, (
        f"a UUID string is 36 characters long, got {len(minted_id)} in {minted_id!r}"
    )
    assert "_" not in minted_id, (
        f"an identifier carries no type prefix such as lg_ or league_, got {minted_id!r}"
    )
    created_at = league["created_at"]

    updated = validate_success(
        api.set_league_sanctioning_status(
            minted_id,
            {
                "sanctioning_status": "PROBATION",
                "reason": "late submission of coach certification records",
            },
            make_program_admin_headers(),
        )
    )
    assert_league(updated)

    assert updated["id"] == minted_id, "the identifier is never re-minted"
    assert updated["sanctioning_status"] == "PROBATION", updated["sanctioning_status"]
    assert updated["version"] == 2, (
        f"the sanctioning decision is one mutation, so version goes 1 to 2, got {updated['version']}"
    )
    assert canonical_iso(updated["created_at"]) == canonical_iso(created_at), (
        "created_at records when the row was first written and never moves: "
        f"{updated['created_at']!r} against {created_at!r}"
    )
    assert canonical_iso(updated["updated_at"]) >= canonical_iso(updated["created_at"]), (
        "updated_at is refreshed on the mutation and cannot precede created_at"
    )
    for field_name in ("created_at", "updated_at"):
        assert THREE_FRACTIONAL_DIGITS.match(updated[field_name]), (
            f"{field_name} must be an ISO 8601 UTC timestamp with exactly three "
            f"fractional digits, got {updated[field_name]!r}"
        )


def test_classifying_a_sport_under_an_unknown_hazard_class_is_rejected_outright(api):
    """PRD §3.1: "A classification is created with a unique `sport_code` (a duplicate is refused with `ERR_DUPLICATE_SPORT_CODE`), a human-readable `sport_name`, a `hazard_class` of `CLASS_1_LOW`, `CLASS_2_MODERATE`, `CLASS_3_HIGH` or `CLASS_4_CONTACT`, and a manual annual `base_rate_per_participant_cents` of at least one cent."
    PRD §2.7: "4. **Request shape** — every required input field present and non-null; every enum value a declared member of its set; every integer within its declared bound; `provider_npi` exactly ten digits; `state_code` exactly two uppercase letters; every datetime a parseable ISO 8601 UTC instant; `limit` within 1 through 100 and `offset` not negative (`ERR_INVALID_REQUEST`)."
    PRD §3.1: "The hazard class immediately determines the echoed `hazard_load_bps` field: a low-hazard sport carries no load at all, a moderate-hazard sport carries 1150 basis points, a high-hazard sport 2625 basis points, and a contact sport 4075 basis points — so writing a contact sport costs a little over forty percent more per athlete than writing the same rate at low hazard."

    Design: Corner/entities/sport_classification_rejects_hazard_class_outside_the_enum
    """
    payload = create_sport_classification_payload(
        sport_code="LACROSSE_U14",
        sport_name="Lacrosse U14",
        hazard_class="CLASS_5_EXTREME",
        base_rate_per_participant_cents=5000,
        deductible_cents=30000,
        per_injury_limit_cents=2000000,
        cat_attachment_point_cents=2000000,
        aggregate_limit_cents=20000000,
        cat_lifetime_max_cents=5000000,
        minimum_participants=18,
        travel_buffer_minutes=60,
        service_category_caps={
            "EMERGENCY_ROOM": 400000,
            "SURGERY": 2000000,
            "DIAGNOSTIC_IMAGING": 250000,
            "PHYSICAL_THERAPY": 18000,
            "DENTAL": 200000,
            "AMBULANCE": 150000,
            "PHYSICIAN_OFFICE": 40000,
        },
    )

    validate_error(
        api.create_sport_classification(payload, make_program_admin_headers()),
        ApiErrorId.ERR_INVALID_REQUEST,
        expected_status=400,
    )

    rows, meta = validate_paginated(
        api.list_sport_classifications(make_program_admin_headers())
    )
    assert rows == [], (
        "an out-of-set hazard class must not be stored verbatim nor defaulted, got "
        f"{len(rows)} classifications"
    )
    assert meta["total_count"] == 0, meta["total_count"]


def test_enrolling_an_athlete_under_another_leagues_policy_is_out_of_scope(api):
    """PRD §3.3: "The league administrator creates one by naming the `participant_id`, the `league_policy_id` of the sport policy the athlete is to be covered under, and the `enrolled_on_date` on which the athlete joined that roster."
    PRD §3.3: "The athlete and the policy must belong to the same league — the athlete's own `league_id` must equal the policy's `league_id`, and a mismatch is `ERR_SCOPE_MISMATCH`."
    PRD §2.6: "Only once every referenced row exists does the server check that those rows are *mutually in scope* — that they actually belong together in the same aggregate."
    PRD §2.6: "A scope failure is `ERR_SCOPE_MISMATCH` (HTTP 422) and is described where each affected workflow appears in §3."

    Design: Corner/entities/enrollment_rejects_participant_belonging_to_a_different_league
    """
    bundle = setup_active_policy(
        league_overrides={
            "name": "Grandview Baseball",
            "league_code": "GVB-106",
            "state_code": "NE",
            "governing_body_code": "USYSA",
            "contact_email": "admin@gvb.example",
        }
    )
    holding_league = bundle["league"]
    policy = bundle["policy"]

    other_league = create_league(
        name="Hillcrest Baseball",
        league_code="HCB-107",
        state_code="NE",
        governing_body_code="USYSA",
        contact_email="admin@hcb.example",
    )
    # The athlete sits on the other league's roster, so both references resolve
    # but they do not belong together.
    outsider = add_participant(
        other_league["id"],
        first_name="Gita",
        last_name="Ramachandran",
        date_of_birth="2014-05-19",
        guardian_email="g24@hcb.example",
    )

    validate_error(
        api.create_enrollment(
            create_enrollment_payload(
                outsider["id"], policy["id"], enrolled_on_date="2026-03-05"
            ),
            make_league_admin_headers(holding_league["id"]),
        ),
        ApiErrorId.ERR_SCOPE_MISMATCH,
        expected_status=422,
    )

    rows, meta = validate_paginated(
        api.list_enrollments(
            make_program_admin_headers(), {"league_policy_id": policy["id"]}
        )
    )
    assert rows == [], (
        f"no enrollment may be written across leagues, got {len(rows)} rows"
    )
    assert meta["total_count"] == 0, meta["total_count"]
