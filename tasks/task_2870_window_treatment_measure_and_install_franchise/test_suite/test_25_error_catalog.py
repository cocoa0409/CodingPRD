"""The catalog read as a promise: one code per entity, one status per code."""

from prd_bench_local_runner.testing import validate_error, validate_success

from test_helpers import factories as f
from test_helpers.api_errors import (
    ERR_COMMISSIONING_ATTEMPT_LIMIT,
    ERR_COMMISSIONING_NOT_VERIFIED,
    ERR_CONSULTATION_NOT_FOUND,
    ERR_DESIGNER_NOT_FOUND,
    ERR_INSTALL_JOB_NOT_FOUND,
    ERR_INVALID_REQUEST,
    ERR_LEAD_NOT_FOUND,
    ERR_OPENING_NOT_FOUND,
    ERR_QUOTE_NOT_DRAFT,
    ERR_QUOTE_NOT_FOUND,
    ERR_ROLE_NOT_PERMITTED,
    ERR_SAMPLE_CHECKOUT_NOT_FOUND,
    ERR_SAMPLE_KIT_NOT_FOUND,
    ERR_STALE_CONSULTATION_VERSION,
    ERR_TERRITORY_NOT_FOUND,
    ERR_UNAUTHENTICATED,
    ERR_VALUE_OUT_OF_RANGE,
    ERR_VENDOR_NOT_FOUND,
    ERR_VENDOR_ORDER_NOT_FOUND,
)
from test_helpers.assertions import assert_all_distinct
from test_helpers.fixtures import (
    accept_quote,
    book_consultation,
    build_quote,
    charter_territory,
    configure_opening,
    hire_designer,
    intake_lead,
    onboard_vendor,
    place_order,
    present_quote,
    read_consultation,
    read_install_job,
    read_opening,
    read_quote,
    receive_order,
    record_opening,
    schedule_install,
    set_clock,
    ship_order,
    single_opening_job,
)
from test_helpers.test_users import (
    designer_headers,
    empty_user_id_headers,
    franchisee_headers,
    franchisor_headers,
)

# One syntactically valid identifier that belongs to nothing in any collection.
ABSENT_ID = "11111111-1111-4111-8111-111111111111"

MOTORIZED_VENDOR = {"base_lead_time_days": 10, "motorization_extra_days": 3,
                    "cutoff_hour_utc": 15, "remake_policy": "SHARED_50_50",
                    "concurrent_capacity": 2,
                    "supported_lift_systems": ["CORDED", "CORDLESS",
                                               "MOTORIZED"],
                    "supported_hub_platforms": ["MATTER", "HOMEKIT"]}


def _refusal_body(response):
    """Read one error response as the standard error envelope and return its body."""
    body = response.json()
    assert body["response_type"] == "error"
    assert set(body["data"]) == {"error_id", "message"}
    assert isinstance(body["data"]["message"], str)
    assert body["data"]["message"] != ""
    assert set(body["meta"]) == {"api_request_id", "api_request_timestamp"}
    return body


def test_each_collection_answers_with_the_code_named_after_its_own_entity(api):
    """One absent id, eleven segments, eleven different not-found codes.

    "**Path existence** — every `{id}` path parameter must resolve to an existing row,
    validated left to right, with the first unresolvable segment deciding which of
    `ERR_TERRITORY_NOT_FOUND`, `ERR_DESIGNER_NOT_FOUND`, `ERR_SAMPLE_KIT_NOT_FOUND`,
    `ERR_LEAD_NOT_FOUND`, `ERR_CONSULTATION_NOT_FOUND`, `ERR_SAMPLE_CHECKOUT_NOT_FOUND`,
    `ERR_OPENING_NOT_FOUND`, `ERR_QUOTE_NOT_FOUND`, `ERR_VENDOR_NOT_FOUND`,
    `ERR_VENDOR_ORDER_NOT_FOUND` or `ERR_INSTALL_JOB_NOT_FOUND` is returned (all HTTP
    404)."

    "**Body reference existence** — every foreign key carried in the request body must
    resolve, validated in the order the fields are declared for that endpoint, returning
    the matching not-found error."

    "The `error_id` is a unique, machine-readable string that identifies the specific
    error."

    Design: Corner/errors/all_eleven_not_found_codes_are_triggerable_and_none_substitutes_for_another
    """
    hq = franchisor_headers()
    probes = (
        (api.get_territory, ERR_TERRITORY_NOT_FOUND),
        (api.get_designer, ERR_DESIGNER_NOT_FOUND),
        (api.get_sample_kit, ERR_SAMPLE_KIT_NOT_FOUND),
        (api.get_lead, ERR_LEAD_NOT_FOUND),
        (api.get_consultation, ERR_CONSULTATION_NOT_FOUND),
        (api.get_sample_checkout, ERR_SAMPLE_CHECKOUT_NOT_FOUND),
        (api.get_opening, ERR_OPENING_NOT_FOUND),
        (api.get_quote, ERR_QUOTE_NOT_FOUND),
        (api.get_vendor, ERR_VENDOR_NOT_FOUND),
        (api.get_vendor_order, ERR_VENDOR_ORDER_NOT_FOUND),
        (api.get_install_job, ERR_INSTALL_JOB_NOT_FOUND),
    )

    answered = []
    for read_one, expected_error_id in probes:
        response = read_one(ABSENT_ID, hq)
        validate_error(response, expected_error_id, 404)
        answered.append(_refusal_body(response)["data"]["error_id"])

    assert len(answered) == 11
    # No single code stands in for a collection it was not declared for.
    assert_all_distinct(answered, "not-found error ids")

    # The same two codes answer from the body-reference direction as well.
    world = single_opening_job(api, stop_after="accepted")
    territory, designer = world["territory"], world["designer"]
    consultation, quote = world["consultation"], world["quote"]

    validate_error(
        api.create_opening(
            f.opening_payload(consultation["id"], label="Corrective trip",
                              replaces_opening_id=ABSENT_ID),
            designer_headers(designer["id"])),
        ERR_OPENING_NOT_FOUND, 404)

    validate_error(
        api.create_vendor_order(
            f.vendor_order_payload(
                quote["id"], [world["opening"]["id"]],
                read_quote(api, territory, quote["id"])["version"],
                preferred_vendor_id=ABSENT_ID),
            franchisee_headers(territory["id"])),
        ERR_VENDOR_NOT_FOUND, 404)


def test_seven_failures_land_in_seven_different_status_classes(api):
    """401, 403, 404, 400, 422, 412 and 409 from one appointment, then a clean retry.

    "A request whose `X-User-ID` is absent, empty, or does not resolve to a known actor
    holding a role is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). A request whose
    resolved role is not among the roles the target endpoint permits is rejected with
    `ERR_ROLE_NOT_PERMITTED` (HTTP 403). Authentication is always evaluated before
    authorization, and both are evaluated before anything else about the request is
    examined."

    "**Request shape** — `ERR_INVALID_REQUEST` (HTTP 400) on every write endpoint when a
    required field is missing, a field carries the wrong JSON type, an enum value is not
    a declared member, an instant is not a valid ISO 8601 UTC string, or an array
    breaches its declared cardinality or contains duplicates."

    "**Numeric and interval domains** — `ERR_VALUE_OUT_OF_RANGE` (HTTP 422)."

    "A scheduled end instant must be strictly after its start instant; a hold end instant
    must be strictly after its hold start instant and no more than fourteen days after
    it; a hold start instant must be at or after the logical clock."

    "If that value does not equal the consultation's current `version`, the request is
    rejected with `ERR_STALE_CONSULTATION_VERSION` (HTTP 412) and nothing is written."

    "A new quote is stamped `DRAFT` with `revision_count` at zero, all of its monetary
    fields at zero, and `presented_at`, `expires_at` and `accepted_at` null."

    "The quote must be `DRAFT` — anything else is `ERR_QUOTE_NOT_DRAFT` — it must carry at
    least one attached opening, every attached opening must have a non-null `fabric_code`
    and a non-null `lift_system`, and every attached opening must satisfy the
    child-safety cordless requirement described below."

    Design: Corner/errors/every_http_status_class_in_the_catalog_is_reachable_with_its_declared_code
    """
    territory = charter_territory(api, postal_codes=["30301"])
    designer = hire_designer(api, territory)
    acting = designer_headers(designer["id"])
    lead = intake_lead(api, territory)
    consultation = book_consultation(api, designer, lead)
    configure_opening(api, designer,
                      record_opening(api, designer, consultation,
                                     label="First"),
                      fabric_code="LT-SHEER", lift_system="CORDED")

    # Captured before a second opening is measured, so it is about to go stale.
    stale_version = read_consultation(api, designer, consultation["id"])["version"]
    configure_opening(api, designer,
                      record_opening(api, designer, consultation,
                                     label="Second"),
                      fabric_code="LT-SHEER", lift_system="CORDED")

    # An empty identity: the role check never runs, so this cannot be a 403.
    unauthenticated = api.get_consultation(consultation["id"],
                                           empty_user_id_headers())
    validate_error(unauthenticated, ERR_UNAUTHENTICATED, 401)

    # Chartering is headquarters-only and a Designer is a peer, not a subordinate.
    forbidden = api.create_territory(
        f.territory_payload(legal_name="Pirate Blinds",
                            postal_codes=["30501"]), acting)
    validate_error(forbidden, ERR_ROLE_NOT_PERMITTED, 403)

    absent = api.get_designer(ABSENT_ID, franchisee_headers(territory["id"]))
    validate_error(absent, ERR_DESIGNER_NOT_FOUND, 404)

    # SIDE_MOUNT is not a declared member of the mount enum: a shape fault.
    misshapen = api.create_opening(
        f.opening_payload(consultation["id"], label="Bad mount",
                          mount_type="SIDE_MOUNT"), acting)
    validate_error(misshapen, ERR_INVALID_REQUEST, 400)

    # Well-shaped JSON carrying an impossible value: a different class entirely.
    empty_interval = api.create_consultation(
        f.consultation_payload(lead["id"], designer["id"],
                               scheduled_start_at="2026-08-06T15:00:00.000Z",
                               scheduled_end_at="2026-08-06T15:00:00.000Z"),
        acting)
    validate_error(empty_interval, ERR_VALUE_OUT_OF_RANGE, 422)

    stale = api.create_quote(f.quote_payload(consultation["id"], stale_version),
                             acting)
    validate_error(stale, ERR_STALE_CONSULTATION_VERSION, 412)

    # The 412 was purely about the version: the same call on a fresh read lands.
    fresh_version = read_consultation(api, designer,
                                      consultation["id"])["version"]
    assert fresh_version != stale_version
    draft = validate_success(
        api.create_quote(f.quote_payload(consultation["id"], fresh_version),
                         acting), 201)
    assert draft["status"] == "DRAFT"
    assert draft["opening_count"] == 2
    assert draft["subtotal_cents"] == 0

    presented = validate_success(api.present_quote(draft["id"], acting))
    assert presented["status"] == "PRESENTED"
    assert presented["subtotal_cents"] == 9920

    # A state conflict on replay, not a validation fault.
    replayed = api.present_quote(draft["id"], acting)
    validate_error(replayed, ERR_QUOTE_NOT_DRAFT, 409)

    refusals = (unauthenticated, forbidden, absent, misshapen, empty_interval,
                stale, replayed)
    statuses = [refusal.status_code for refusal in refusals]
    assert statuses == [401, 403, 404, 400, 422, 412, 409]
    assert_all_distinct(statuses, "HTTP status classes")
    for refusal in refusals:
        _refusal_body(refusal)


def test_only_accepted_pairs_spend_the_budget_and_the_fourth_is_refused(api):
    """Three accepted pairs, three failed verifications, then a job nobody can close.

    "A new job is stamped `install_status` `SCHEDULED`, and its
    `motorized_channel_count` is **frozen** at creation as the number of openings in the
    order's `opening_ids` whose `motorization_option` is anything other than `NONE`."

    "And `commissioning_attempt_count` must be strictly less than three, the cap on
    pairing attempts, or the call fails with `ERR_COMMISSIONING_ATTEMPT_LIMIT`; the
    counter increments on **every** accepted pair call, including the ones that later
    fail verification."

    "An accepted pair call stores `hub_platform` and `paired_channel_count`, increments
    `commissioning_attempt_count`, and drives `PENDING → PAIRED` or `FAILED → PAIRED`."

    "When `paired_channel_count` is less than `motorized_channel_count` the job moves
    `PAIRED → FAILED` and the call still returns HTTP 200 — a failed verification is a
    **recorded field observation**, not a request error."

    "It requires `install_status` to be `SCHEDULED`, the acting designer to be the
    assigned one, the referenced order to be `RECEIVED`, and `commissioning_status` to be
    either `NOT_REQUIRED` or `VERIFIED` — `PENDING`, `PAIRED` and `FAILED` all block
    completion with `ERR_COMMISSIONING_NOT_VERIFIED`."

    Design: Corner/errors/the_pair_attempt_budget_is_spent_only_by_accepted_calls_and_then_locks_the_job
    """
    territory = charter_territory(api, postal_codes=["30301"])
    designer = hire_designer(api, territory, certifications=["MOTORIZATION"])
    acting = designer_headers(designer["id"])
    vendor = onboard_vendor(api, **MOTORIZED_VENDOR)
    lead = intake_lead(api, territory,
                       requested_at="2026-08-03T00:00:00.000Z",
                       child_occupied_dwelling=False)
    consultation = book_consultation(api, designer, lead)

    slider = configure_opening(
        api, designer,
        record_opening(api, designer, consultation, label="Great room slider",
                       room_type="LIVING_ROOM",
                       **f.uniform_readings(60.000, 84.000)),
        fabric_code="WD-FAUX", lift_system="MOTORIZED",
        motorization_option="HARDWIRED")
    transom = configure_opening(
        api, designer,
        record_opening(api, designer, consultation, label="Landing transom"),
        fabric_code="LT-SHEER", lift_system="MOTORIZED",
        motorization_option="BATTERY")

    quote = build_quote(api, designer, consultation)
    set_clock(api, "2026-08-03T16:00:00.000Z")
    present_quote(api, designer, quote)
    accept_quote(api, designer, quote)
    order = place_order(api, territory, quote,
                        [slider["id"], transom["id"]], vendor)
    ship_order(api, vendor, order)
    set_clock(api, "2026-08-17T09:00:00.000Z")
    receive_order(api, territory, order)

    job = schedule_install(api, territory, order, designer)
    assert job["motorized_channel_count"] == 2
    assert job["commissioning_status"] == "PENDING"
    assert job["commissioning_attempt_count"] == 0
    assert job["install_status"] == "SCHEDULED"

    set_clock(api, "2026-08-20T09:30:00.000Z")

    # Each accepted pair spends exactly one unit of the three-attempt budget, and
    # each verification lands on FAILED because one channel is short of two.
    for spent, hub in ((1, "MATTER"), (2, "MATTER"), (3, "HOMEKIT")):
        paired = validate_success(api.pair_commissioning(
            job["id"], f.pair_payload(1, hub), acting))
        assert paired["commissioning_status"] == "PAIRED"
        assert paired["commissioning_attempt_count"] == spent
        assert paired["paired_channel_count"] == 1
        assert paired["hub_platform"] == hub
        assert paired["install_status"] == "SCHEDULED"

        failed = api.verify_commissioning(job["id"], acting)
        assert failed.status_code == 200
        observed = validate_success(failed)
        assert observed["commissioning_status"] == "FAILED"
        assert observed["install_status"] == "SCHEDULED"

    # FAILED is a legal from-state for pairing, so the refusal is about the budget.
    validate_error(
        api.pair_commissioning(job["id"], f.pair_payload(1, "MATTER"), acting),
        ERR_COMMISSIONING_ATTEMPT_LIMIT, 409)
    validate_error(api.complete_install_job(job["id"], acting),
                   ERR_COMMISSIONING_NOT_VERIFIED, 409)

    final = read_install_job(api, designer, job["id"])
    assert final["commissioning_attempt_count"] == 3
    assert final["commissioning_status"] == "FAILED"
    assert final["hub_platform"] == "HOMEKIT"
    assert final["paired_channel_count"] == 1
    # The two dimensions never coupled across all eight commissioning calls.
    assert final["install_status"] == "SCHEDULED"
    assert final["completed_at"] is None
    for member in (slider, transom):
        assert read_opening(api, designer, member["id"])["install_outcome"] == "PENDING"
