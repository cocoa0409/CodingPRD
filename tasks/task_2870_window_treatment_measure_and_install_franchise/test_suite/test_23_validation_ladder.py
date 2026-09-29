"""The ladder itself: which rung answers when one request breaks several rules."""

from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import factories as f
from test_helpers.api_errors import (
    ERR_CHANNEL_COUNT_EXCEEDS_ORDER,
    ERR_CROSS_TERRITORY_FORBIDDEN,
    ERR_DESIGNER_NOT_FOUND,
    ERR_HUB_PLATFORM_UNSUPPORTED,
    ERR_INSUFFICIENT_MOUNT_DEPTH,
    ERR_INVALID_REQUEST,
    ERR_MOTORIZATION_CERT_REQUIRED,
    ERR_MOTOR_OPTION_MISMATCH,
    ERR_OPENINGS_ALREADY_RESOLVED,
    ERR_OPENING_ALREADY_ORDERED,
    ERR_OPENING_NOT_ON_QUOTE,
    ERR_QUOTE_NOT_ACCEPTED,
    ERR_REMAKE_NOT_OFFERED,
    ERR_REMAKE_WINDOW_CLOSED,
    ERR_ROLE_NOT_PERMITTED,
    ERR_STALE_QUOTE_VERSION,
    ERR_TERRITORY_OWNERSHIP_REQUIRED,
)
from test_helpers.assertions import (
    assert_inches_equal,
    assert_instant_equals,
    assert_ledger_entry,
    assert_page_meta,
)
from test_helpers.fixtures import (
    CLOCK_START,
    accept_quote,
    add_sample_kit,
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
    read_designer,
    read_install_job,
    read_opening,
    read_order,
    read_quote,
    read_territory,
    receive_order,
    record_opening,
    schedule_install,
    set_clock,
    ship_order,
    single_opening_job,
)
from test_helpers.test_users import (
    designer_headers,
    franchisee_headers,
    franchisor_headers,
)

ABSENT_DESIGNER_ID = "11111111-1111-4111-8111-111111111111"
UNDECLARED_STATUS = {"status": "RETIRED_PLEASE"}
CORDED_CAPACITY_FIVE = {"base_lead_time_days": 10, "motorization_extra_days": 3,
                        "cutoff_hour_utc": 15, "remake_policy": "SHARED_50_50",
                        "concurrent_capacity": 5,
                        "supported_lift_systems": ["CORDED"]}


def test_one_malformed_body_climbs_the_whole_authorization_ladder(api):
    """The same bad enum answers role, then existence, then ownership, then shape.

    "When a single request violates several rules at once, exactly one error is returned,
    and which one is fully determined."

    "**Authorization** — the actor's role must appear in the endpoint's permitted roles
    list; otherwise `ERR_ROLE_NOT_PERMITTED`, on every endpoint."

    "**Path existence** — every `{id}` path parameter must resolve to an existing row,
    validated left to right, with the first unresolvable segment deciding which of
    `ERR_TERRITORY_NOT_FOUND`, `ERR_DESIGNER_NOT_FOUND`, `ERR_SAMPLE_KIT_NOT_FOUND`,
    `ERR_LEAD_NOT_FOUND`, `ERR_CONSULTATION_NOT_FOUND`, `ERR_SAMPLE_CHECKOUT_NOT_FOUND`,
    `ERR_OPENING_NOT_FOUND`, `ERR_QUOTE_NOT_FOUND`, `ERR_VENDOR_NOT_FOUND`,
    `ERR_VENDOR_ORDER_NOT_FOUND` or `ERR_INSTALL_JOB_NOT_FOUND` is returned (all HTTP
    404)."

    "**Territory ownership** — `ERR_TERRITORY_OWNERSHIP_REQUIRED`, on all `Franchisee`
    operations against `Territory`, `Designer`, `SampleKit`, `Lead` and `VendorOrder`
    rows."

    "**Request shape** — `ERR_INVALID_REQUEST` (HTTP 400) on every write endpoint when a
    required field is missing, a field carries the wrong JSON type, an enum value is not a
    declared member, an instant is not a valid ISO 8601 UTC string, or an array breaches
    its declared cardinality or contains duplicates."

    Design: Corner/validations/one_malformed_body_climbs_the_whole_authorization_ladder
    """
    home = charter_territory(api, postal_codes=["30301"])
    stranger = charter_territory(api, legal_name="Southmark Window Fashions",
                                 postal_codes=["30401"])
    designer = hire_designer(api, home)
    version_before = designer["version"]

    # Rung 2: the endpoint lists only Franchisee, so the body is never read.
    validate_error(
        api.patch_designer(designer["id"], dict(UNDECLARED_STATUS),
                           designer_headers(designer["id"])),
        ERR_ROLE_NOT_PERMITTED, 403)

    # Rung 3: an unresolvable path parameter outranks the bad enum in the body.
    validate_error(
        api.patch_designer(ABSENT_DESIGNER_ID, dict(UNDECLARED_STATUS),
                           franchisee_headers(home["id"])),
        ERR_DESIGNER_NOT_FOUND, 404)

    # Rung 5: the other franchisee is refused on ownership, not with a leaky 404.
    validate_error(
        api.patch_designer(designer["id"], dict(UNDECLARED_STATUS),
                           franchisee_headers(stranger["id"])),
        ERR_TERRITORY_OWNERSHIP_REQUIRED, 403)

    # Rung 7: only the owning franchisee gets as far as the undeclared value.
    validate_error(
        api.patch_designer(designer["id"], dict(UNDECLARED_STATUS),
                           franchisee_headers(home["id"])),
        ERR_INVALID_REQUEST, 400)

    unchanged = read_designer(api, home, designer["id"])
    assert unchanged["version"] == version_before
    assert unchanged["status"] == "ACTIVE"
    assert unchanged["certifications"] == []

    restated = validate_success(api.patch_designer(
        designer["id"], f.designer_patch(certifications=["MOTORIZATION"]),
        franchisee_headers(home["id"])))
    assert restated["certifications"] == ["MOTORIZATION"]
    assert restated["version"] == version_before + 1


def test_territory_coherence_is_checked_on_both_ends_of_a_linkage(api):
    """One error id guards two different linkages, and neither refusal leaves a trace.

    "**Territory coherence of a linkage** — `ERR_CROSS_TERRITORY_FORBIDDEN` (HTTP 422) on
    `POST /blinds/consultations`, `POST /blinds/sample-checkouts` and
    `POST /blinds/install-jobs`."

    "The kit and the appointment must also belong to the same franchise: the kit's owning
    territory must equal the territory of the appointment's lead, and a mismatch is
    `ERR_CROSS_TERRITORY_FORBIDDEN`."

    Design: Corner/validations/territory_coherence_is_checked_on_both_ends_of_a_linkage
    """
    home = charter_territory(api, postal_codes=["30301"])
    other = charter_territory(api, legal_name="Southmark Window Fashions",
                              postal_codes=["30401"])
    designer = hire_designer(api, home)
    foreign_kit = add_sample_kit(api, other, kit_code="SHEERS-A",
                                 replacement_value_cents=50000)
    hq = franchisor_headers()
    own_lead = validate_success(api.create_lead(f.lead_payload(
        customer_name="Ana Ruiz", postal_code="30301"), hq), 201)
    foreign_lead = validate_success(api.create_lead(f.lead_payload(
        customer_name="Bo Chen", postal_code="30401",
        requested_at="2026-08-01T09:00:00.000Z"), hq), 201)

    # Both rows exist; it is the pairing of them that is illegal.
    validate_error(
        api.create_consultation(
            f.consultation_payload(foreign_lead["id"], designer["id"],
                                   service_postal_code="30401"),
            designer_headers(designer["id"])),
        ERR_CROSS_TERRITORY_FORBIDDEN, 422)

    appointment = book_consultation(api, designer, own_lead)
    assert appointment["status"] == "SCHEDULED"

    validate_error(
        api.create_sample_checkout(
            f.sample_checkout_payload(foreign_kit["id"], appointment["id"],
                                      "2026-08-02T09:00:00.000Z",
                                      "2026-08-04T17:00:00.000Z"),
            designer_headers(designer["id"])),
        ERR_CROSS_TERRITORY_FORBIDDEN, 422)

    stocked = validate_success(api.get_sample_kit(
        foreign_kit["id"], franchisee_headers(other["id"])))
    assert stocked["status"] == "AVAILABLE"
    assert stocked["open_loan_count"] == 0

    untouched = read_territory(api, other)
    assert untouched["on_loan_kit_count"] == 0
    assert untouched["available_kit_count"] == 1

    assert read_consultation(api, designer,
                            appointment["id"])["open_sample_loan_count"] == 0
    _rows, meta = validate_paginated(api.list_sample_checkouts(
        designer_headers(designer["id"]), consultation_id=appointment["id"]))
    assert_page_meta(meta, total_count=0, has_more=False)

    still_routed = validate_success(api.get_lead(foreign_lead["id"], hq))
    assert still_routed["status"] == "ROUTED"
    assert still_routed["territory_id"] == other["id"]


def _two_quotes_one_accepted(api):
    """One accepted quote with two openings, and a second draft quote with one.

    The lone opening on the draft quote is the foreign one the placement below
    tries to smuggle in.
    """
    territory = charter_territory(api, postal_codes=["30301"])
    designer = hire_designer(api, territory)
    vendor = onboard_vendor(api, **CORDED_CAPACITY_FIVE)
    first_lead = intake_lead(api, territory, customer_name="Ana Ruiz")
    second_lead = intake_lead(api, territory, customer_name="Bo Chen",
                              source="REFERRAL",
                              requested_at="2026-08-01T09:00:00.000Z")
    first_visit = book_consultation(api, designer, first_lead)
    second_visit = book_consultation(
        api, designer, second_lead,
        scheduled_start_at="2026-08-03T16:00:00.000Z",
        scheduled_end_at="2026-08-03T17:00:00.000Z")
    mine = []
    for label in ("Front left", "Front right"):
        opening = record_opening(api, designer, first_visit, label=label)
        mine.append(configure_opening(api, designer, opening,
                                      fabric_code="LT-SHEER",
                                      lift_system="CORDED"))
    theirs = record_opening(api, designer, second_visit, label="Other house")
    theirs = configure_opening(api, designer, theirs, fabric_code="LT-SHEER",
                               lift_system="CORDED")

    accepted = build_quote(api, designer, first_visit)
    other_quote = build_quote(api, designer, second_visit)
    present_quote(api, designer, accepted)
    accepted = accept_quote(api, designer, accepted)
    return {"territory": territory, "designer": designer, "vendor": vendor,
            "accepted": accepted, "other_quote": other_quote,
            "first": mine[0], "second": mine[1], "foreign": theirs}


def test_opening_membership_is_checked_before_prior_placement(api):
    """Rung 10 answers for a foreign opening; rung 15 answers for a re-used one.

    "**Membership of a named opening** — `ERR_OPENING_NOT_ON_QUOTE` (HTTP 422) on
    `POST /blinds/vendor-orders`, `POST /blinds/install-jobs/{id}/exception` and
    `POST /blinds/openings`."

    "Every named opening must carry that quote's id, or the request fails with
    `ERR_OPENING_NOT_ON_QUOTE`, and every named opening must still have `install_outcome`
    `PENDING`."

    "No named opening may already sit on an order whose `status` is `PLACED`, `SHIPPED`,
    `RECEIVED` or `REMAKE_REQUESTED`; that is `ERR_OPENING_ALREADY_ORDERED`."

    Design: Corner/validations/opening_membership_is_checked_before_prior_placement
    """
    world = _two_quotes_one_accepted(api)
    territory, designer = world["territory"], world["designer"]
    quote, vendor = world["accepted"], world["vendor"]
    owner = franchisee_headers(territory["id"])
    version = quote["version"]

    # The whole placement is refused rather than partially accepted for the good one.
    validate_error(
        api.create_vendor_order(f.vendor_order_payload(
            quote["id"], [world["first"]["id"], world["foreign"]["id"]],
            version, preferred_vendor_id=vendor["id"]), owner),
        ERR_OPENING_NOT_ON_QUOTE, 422)

    order = place_order(api, territory, quote, [world["first"]["id"]], vendor,
                        expected_quote_version=version)
    assert order["opening_ids"] == [world["first"]["id"]]
    assert order["order_cost_cents"] == 2083

    version = read_quote(api, territory, quote["id"])["version"]
    validate_error(
        api.create_vendor_order(f.vendor_order_payload(
            quote["id"], [world["first"]["id"], world["second"]["id"]],
            version, preferred_vendor_id=vendor["id"]), owner),
        ERR_OPENING_ALREADY_ORDERED, 409)

    orders, meta = validate_paginated(
        api.list_vendor_orders(owner, quote_id=quote["id"]))
    assert_page_meta(meta, total_count=1, has_more=False)
    assert orders[0]["id"] == order["id"]
    assert read_quote(api, territory, quote["id"])["version"] == version

    # The perfectly placeable second opening was refused with its neighbour.
    assert read_opening(api, designer,
                        world["second"]["id"])["measure_status"] == "QUOTED"
    assert read_territory(api,
                          territory)["open_order_exposure_cents"] == 2083

    bystander = read_quote(api, territory, world["other_quote"]["id"])
    assert bystander["status"] == "DRAFT"
    assert bystander["subtotal_cents"] == 0


def test_the_inside_depth_rule_applies_only_to_inside_mounts(api):
    """2.499 inside is refused, 2.500 inside passes, and 0.500 outside passes too.

    "An inside mount is refused outright when the pocket is too shallow to hold the
    headrail: `depth_in` must be at least 2.500 inches, and anything less is
    `ERR_INSUFFICIENT_MOUNT_DEPTH`."

    "An outside mount, which hangs on the face of the wall, carries no depth requirement
    at all."

    "For an `OUTSIDE` mount the service starts from the **widest** width and the
    **tallest** height, because the blind has to cover the largest point of the opening: it
    adds an overlap of 1.500 inches on each of the two sides — three inches of extra width
    in total — and adds to the tallest height a header allowance of 3.000 inches plus a
    sill overlap of 1.500 inches, then rounds each result **up** to the next higher exact
    eighth of an inch."

    Design: Corner/validations/the_inside_depth_rule_applies_only_to_inside_mounts
    """
    territory = charter_territory(api, postal_codes=["30301"])
    designer = hire_designer(api, territory)
    lead = intake_lead(api, territory)
    appointment = book_consultation(api, designer, lead)
    author = designer_headers(designer["id"])

    validate_error(
        api.create_opening(f.opening_payload(
            appointment["id"], label="Too shallow inside", depth_in=2.499),
            author),
        ERR_INSUFFICIENT_MOUNT_DEPTH, 422)

    # Exactly the minimum satisfies an at-least test.
    deep_enough = validate_success(api.create_opening(f.opening_payload(
        appointment["id"], label="Exactly deep enough", depth_in=2.500),
        author), 201)
    assert_inches_equal(deep_enough["ordered_width_in"], 23.500,
                        "ordered_width_in")

    shallow_outside = validate_success(api.create_opening(f.opening_payload(
        appointment["id"], label="Shallow but outside", mount_type="OUTSIDE",
        depth_in=0.500), author), 201)
    assert_inches_equal(shallow_outside["ordered_width_in"], 27.000,
                        "ordered_width_in")
    assert_inches_equal(shallow_outside["ordered_height_in"], 52.500,
                        "ordered_height_in")
    assert_inches_equal(shallow_outside["depth_in"], 0.500, "depth_in")

    assert read_consultation(api, designer,
                            appointment["id"])["measured_opening_count"] == 2
    _rows, meta = validate_paginated(api.list_openings(
        author, consultation_id=appointment["id"]))
    assert_page_meta(meta, total_count=2, has_more=False)


def test_the_motor_package_must_agree_with_the_lift_system_in_both_directions(api):
    """A MOTORIZED lift with the default NONE fails; a CORDED lift with BATTERY fails too.

    "Motor packages and lift systems must agree: `motorization_option` must be `NONE`
    whenever `lift_system` is anything other than `MOTORIZED`, and must **not** be `NONE`
    when `lift_system` is `MOTORIZED`."

    "The configuration payload carries `fabric_code`, which must be one of `LT-SHEER`,
    `CL-LINEN`, `BO-THERMAL` or `WD-FAUX`; `lift_system`, one of `CORDED`, `CORDLESS`,
    `CONTINUOUS_LOOP` or `MOTORIZED`; and an optional `motorization_option` defaulting to
    `NONE`, whose other members are `BATTERY` and `HARDWIRED`."

    "A newly recorded opening is stamped with `measure_status` `MEASURED`,
    `install_outcome` `PENDING`, `credited` false, `list_price_cents` zero and
    `billable_sqft` zero, and with `quote_id`, `fabric_code` and `lift_system` all null."

    Design: Corner/validations/the_motor_package_must_agree_with_the_lift_system_in_both_directions
    """
    territory = charter_territory(api, postal_codes=["30301"])
    designer = hire_designer(api, territory)
    lead = intake_lead(api, territory)
    appointment = book_consultation(api, designer, lead)
    opening = record_opening(api, designer, appointment, label="Study window")
    assert opening["list_price_cents"] == 0
    author = designer_headers(designer["id"])

    # The caller omits the field entirely and the default it lands on is the breach.
    validate_error(
        api.configure_opening(opening["id"], f.configuration_payload(
            fabric_code="LT-SHEER", lift_system="MOTORIZED"), author),
        ERR_MOTOR_OPTION_MISMATCH, 422)
    validate_error(
        api.configure_opening(opening["id"], f.configuration_payload(
            fabric_code="LT-SHEER", lift_system="CORDED",
            motorization_option="BATTERY"), author),
        ERR_MOTOR_OPTION_MISMATCH, 422)

    refused = read_opening(api, designer, opening["id"])
    assert refused["measure_status"] == "MEASURED"
    assert refused["list_price_cents"] == 0

    priced = validate_success(api.configure_opening(
        opening["id"], f.configuration_payload(fabric_code="LT-SHEER",
                                               lift_system="MOTORIZED",
                                               motorization_option="BATTERY"),
        author))
    assert priced["list_price_cents"] == 17460
    assert priced["measure_status"] == "CONFIGURED"
    assert read_consultation(api, designer,
                            appointment["id"])["configured_opening_count"] == 1


def test_the_pairing_request_is_gated_by_certification_then_platform_then_channel_count(api):
    """Three refusals in ladder order, and none of them spends an attempt.

    "The acting designer's `certifications` must include `MOTORIZATION`, or the request is
    refused with `ERR_MOTORIZATION_CERT_REQUIRED` (HTTP 403)."

    "The reported `hub_platform` must be a member of the manufacturing vendor's
    `supported_hub_platforms`, and since `NONE` is never a member of that set, reporting
    `NONE` always fails with `ERR_HUB_PLATFORM_UNSUPPORTED` (HTTP 422)."

    "And `commissioning_attempt_count` must be strictly less than three, the cap on
    pairing attempts, or the call fails with `ERR_COMMISSIONING_ATTEMPT_LIMIT`; the counter
    increments on **every** accepted pair call, including the ones that later fail
    verification."

    "A negative count is `ERR_VALUE_OUT_OF_RANGE`; a count above the frozen figure is
    `ERR_CHANNEL_COUNT_EXCEEDS_ORDER` (HTTP 422), because the order cannot contain more
    channels than it carries."

    "When `paired_channel_count` equals `motorized_channel_count` the job moves
    `PAIRED → VERIFIED`, which satisfies the completion guard on the first dimension
    without changing `install_status`."

    Design: Corner/validations/the_pairing_request_is_gated_by_certification_then_platform_then_channel_count
    """
    world = single_opening_job(
        api, lift_system="MOTORIZED", motorization_option="BATTERY",
        room_type="LIVING_ROOM",
        vendor_kwargs={"base_lead_time_days": 10, "motorization_extra_days": 3,
                       "cutoff_hour_utc": 15, "remake_policy": "SHARED_50_50",
                       "concurrent_capacity": 5,
                       "supported_lift_systems": ["MOTORIZED"],
                       "supported_hub_platforms": ["ALEXA"]},
        stop_after="scheduled")
    territory, designer = world["territory"], world["designer"]
    job = world["install_job"]
    assert world["opening"]["list_price_cents"] == 17460
    assert world["quote"]["install_fee_cents"] == 14500
    assert world["order"]["order_cost_cents"] == 7333
    assert job["motorized_channel_count"] == 1
    assert job["commissioning_status"] == "PENDING"
    author = designer_headers(designer["id"])

    validate_error(
        api.pair_commissioning(job["id"], f.pair_payload(1, "ALEXA"), author),
        ERR_MOTORIZATION_CERT_REQUIRED, 403)

    validate_success(api.patch_designer(
        designer["id"], f.designer_patch(certifications=["MOTORIZATION"]),
        franchisee_headers(territory["id"])))

    # A declared enum member that this manufacturer simply does not support.
    validate_error(
        api.pair_commissioning(job["id"], f.pair_payload(1, "GOOGLE_HOME"),
                               author),
        ERR_HUB_PLATFORM_UNSUPPORTED, 422)
    validate_error(
        api.pair_commissioning(job["id"], f.pair_payload(2, "ALEXA"), author),
        ERR_CHANNEL_COUNT_EXCEEDS_ORDER, 422)

    paired = validate_success(
        api.pair_commissioning(job["id"], f.pair_payload(1, "ALEXA"), author))
    assert paired["commissioning_status"] == "PAIRED"

    # The three refusals never touched the counter, so the budget of three is intact.
    assert paired["commissioning_attempt_count"] == 1

    verified = validate_success(api.verify_commissioning(job["id"], author))
    assert verified["commissioning_status"] == "VERIFIED"
    assert verified["hub_platform"] == "ALEXA"

    settled = read_install_job(api, designer, job["id"])
    assert settled["install_status"] == "SCHEDULED"


def test_the_version_check_outranks_both_the_quote_state_and_the_prior_placement(api):
    """Rung 11 answers twice over rung 15: once for state, once for prior placement.

    "**Stale parent version** — `ERR_STALE_CONSULTATION_VERSION` on `POST /blinds/quotes`
    and `ERR_STALE_QUOTE_VERSION` on `POST /blinds/vendor-orders`, both HTTP 412."

    "A `POST /blinds/vendor-orders` request must carry `expected_quote_version` as a
    non-optional field holding the client's last observed `version` of the named `Quote`."

    "Each successful placement increments the quote's `version`, so a second placement must
    carry the version read after the first one landed."

    "The quote must be `ACCEPTED`, or the request fails with `ERR_QUOTE_NOT_ACCEPTED`, and
    it must not have expired."

    Design: Corner/validations/the_version_check_outranks_both_the_quote_state_and_the_prior_placement
    """
    world = single_opening_job(
        api, vendor_kwargs=dict(CORDED_CAPACITY_FIVE), stop_after="quoted")
    territory, designer = world["territory"], world["designer"]
    vendor, opening = world["vendor"], world["opening"]
    owner = franchisee_headers(territory["id"])
    draft_version = world["quote"]["version"]
    presented = present_quote(api, designer, world["quote"])
    presented_version = presented["version"]
    assert presented_version != draft_version

    # Reported even though a PRESENTED quote could not have been placed against anyway.
    validate_error(
        api.create_vendor_order(f.vendor_order_payload(
            presented["id"], [opening["id"]], draft_version,
            preferred_vendor_id=vendor["id"]), owner),
        ERR_STALE_QUOTE_VERSION, 412)

    # With the current version the state error is reachable, proving rung 11 fired first.
    validate_error(
        api.create_vendor_order(f.vendor_order_payload(
            presented["id"], [opening["id"]], presented_version,
            preferred_vendor_id=vendor["id"]), owner),
        ERR_QUOTE_NOT_ACCEPTED, 409)

    accepted = accept_quote(api, designer, presented)
    accepted_version = accepted["version"]
    order = validate_success(api.create_vendor_order(f.vendor_order_payload(
        accepted["id"], [opening["id"]], accepted_version,
        preferred_vendor_id=vendor["id"]), owner), 201)
    assert order["order_cost_cents"] == 2083

    # Not ERR_OPENING_ALREADY_ORDERED: the placement bumped the version first.
    validate_error(
        api.create_vendor_order(f.vendor_order_payload(
            accepted["id"], [opening["id"]], accepted_version,
            preferred_vendor_id=vendor["id"]), owner),
        ERR_STALE_QUOTE_VERSION, 412)

    orders, meta = validate_paginated(
        api.list_vendor_orders(owner, quote_id=accepted["id"]))
    assert_page_meta(meta, total_count=1, has_more=False)
    assert orders[0]["id"] == order["id"]
    assert read_territory(api,
                          territory)["open_order_exposure_cents"] == 2083
    assert (read_quote(api, territory, accepted["id"])["version"]
            == accepted_version + 1)


THREE_POLICIES = (("Ashcroft Mills", "NO_REMAKE"),
                  ("Brightline Shade", "SHARED_50_50"),
                  ("Cascade Coverings", "FULL_VENDOR_90D"))


def _three_policies_one_installed(api):
    """Three manufacturers with three remake policies, and four received orders.

    Orders A, B and D hang off one accepted quote; order C hangs off a second
    quote and is installed, which resolves its opening.
    """
    territory = charter_territory(api, postal_codes=["30301"])
    designer = hire_designer(api, territory)
    refuser, sharer, warranty = (
        onboard_vendor(api, name=name, **dict(CORDED_CAPACITY_FIVE,
                                              remake_policy=policy))
        for name, policy in THREE_POLICIES)
    first_lead = intake_lead(api, territory, customer_name="Ana Ruiz")
    second_lead = intake_lead(api, territory, customer_name="Bo Chen",
                              source="REFERRAL",
                              requested_at="2026-08-01T09:00:00.000Z")
    first_visit = book_consultation(api, designer, first_lead)
    second_visit = book_consultation(
        api, designer, second_lead,
        scheduled_start_at="2026-08-03T16:00:00.000Z",
        scheduled_end_at="2026-08-03T17:00:00.000Z")
    trio = []
    for label in ("Bay left", "Bay centre", "Bay right"):
        opening = record_opening(api, designer, first_visit, label=label,
                                 room_type="LIVING_ROOM")
        trio.append(configure_opening(api, designer, opening,
                                      fabric_code="LT-SHEER",
                                      lift_system="CORDED"))
    kitchen = record_opening(api, designer, second_visit, label="Kitchen",
                             room_type="KITCHEN")
    kitchen = configure_opening(api, designer, kitchen,
                                fabric_code="LT-SHEER", lift_system="CORDED")

    big_quote = build_quote(api, designer, first_visit)
    present_quote(api, designer, big_quote)
    big_quote = accept_quote(api, designer, big_quote)
    assert big_quote["net_sales_cents"] == 14880

    lone_quote = build_quote(api, designer, second_visit)
    present_quote(api, designer, lone_quote)
    lone_quote = accept_quote(api, designer, lone_quote)

    refused_order = place_order(api, territory, big_quote, [trio[0]["id"]],
                                refuser)
    shared_order = place_order(api, territory, big_quote, [trio[1]["id"]],
                               sharer)
    second_shared = place_order(api, territory, big_quote, [trio[2]["id"]],
                                sharer)
    warranty_order = place_order(api, territory, lone_quote,
                                 [kitchen["id"]], warranty)
    for order, vendor in ((refused_order, refuser), (shared_order, sharer),
                          (second_shared, sharer), (warranty_order, warranty)):
        ship_order(api, vendor, order)
        received = receive_order(api, territory, order)
        assert_instant_equals(received["received_at"], CLOCK_START,
                              "received_at")

    job = schedule_install(api, territory, warranty_order, designer)
    set_clock(api, "2026-08-20T13:00:00.000Z")
    signed = validate_success(api.complete_install_job(
        job["id"], designer_headers(designer["id"])))
    assert signed["install_status"] == "COMPLETED"
    assert read_opening(api, designer,
                        kitchen["id"])["install_outcome"] == "INSTALLED"
    return {"territory": territory, "designer": designer, "sharer": sharer,
            "refused_order": refused_order, "shared_order": shared_order,
            "second_shared": second_shared,
            "warranty_order": warranty_order}


def test_the_ninety_day_remake_window_binds_one_policy_and_not_the_other(api):
    """One request, three policies: refused outright, refused late, and accepted late.

    "The vendor's `remake_policy` must not be `NO_REMAKE`, or the request fails with
    `ERR_REMAKE_NOT_OFFERED` — such a manufacturer refuses remakes altogether."

    "When the vendor's policy is `FULL_VENDOR_90D` the logical clock must be at most ninety
    days after the order's `received_at`, or the request fails with
    `ERR_REMAKE_WINDOW_CLOSED`; a `SHARED_50_50` policy has no window limit at all."

    "And a `FULL_CREDIT` remake additionally requires every opening in the order's
    `opening_ids` to still have `install_outcome` `PENDING`, because revenue already trued
    up by a completed install cannot be reversed wholesale; a breach is
    `ERR_OPENINGS_ALREADY_RESOLVED`."

    "A `SHARED_50_50` vendor's target is half of `remake_cost_cents` rounded **down** to a
    whole cent, and the territory's target is whatever remains — so on an odd cost of 7403
    cents the vendor takes 3701 and the territory 3702, the extra cent landing on the
    territory rather than on the manufacturer."

    Design: Corner/validations/the_ninety_day_remake_window_binds_one_policy_and_not_the_other
    """
    world = _three_policies_one_installed(api)
    territory, designer = world["territory"], world["designer"]
    owner = franchisee_headers(territory["id"])

    validate_error(
        api.remake_vendor_order(world["refused_order"]["id"],
                                f.remake_payload("REPLACEMENT"), owner),
        ERR_REMAKE_NOT_OFFERED, 422)

    # Forty-seven days inside the warranty window, so the window is not what refused it.
    validate_error(
        api.remake_vendor_order(world["warranty_order"]["id"],
                                f.remake_payload("FULL_CREDIT"), owner),
        ERR_OPENINGS_ALREADY_RESOLVED, 409)

    shared = validate_success(api.remake_vendor_order(
        world["shared_order"]["id"], f.remake_payload("REPLACEMENT"), owner))
    assert shared["status"] == "PLACED"
    assert shared["remake_cost_cents"] == 2083
    assert shared["vendor_absorbed_cents"] == 1041
    assert shared["territory_absorbed_cents"] == 1042
    assert shared["promised_ship_date"] == "2026-08-26"

    set_clock(api, "2026-11-06T10:00:00.000Z")
    validate_error(
        api.remake_vendor_order(world["warranty_order"]["id"],
                                f.remake_payload("REPLACEMENT"), owner),
        ERR_REMAKE_WINDOW_CLOSED, 409)

    # Ninety-seven days out, and the sharing policy still accepts.
    late = validate_success(api.remake_vendor_order(
        world["second_shared"]["id"], f.remake_payload("REPLACEMENT"), owner))
    assert late["status"] == "PLACED"
    assert late["territory_absorbed_cents"] == 1042
    assert late["promised_ship_date"] == "2026-11-12"

    rows, meta = validate_paginated(api.list_ledger_entries(territory["id"],
                                                           owner))
    assert_page_meta(meta, total_count=4, has_more=False)
    assert [(row["entry_type"], row["amount_cents"]) for row in rows] == [
        ("NET_SALES_ROYALTY", 818),
        ("NET_SALES_ROYALTY", 273),
        ("REMAKE_CHARGEBACK", 1042),
        ("REMAKE_CHARGEBACK", 1042),
    ]
    assert_ledger_entry(rows[2], "REMAKE_CHARGEBACK", 1042, 2083,
                        "remake_replacement", "VENDOR_ORDER",
                        source_entity_id=world["shared_order"]["id"],
                        territory_id=territory["id"])

    counters = read_territory(api, territory)
    assert counters["remake_chargeback_cents"] == 2084
    assert counters["royalty_accrued_cents"] == 1091
    assert counters["net_sales_cents"] == 19840
    assert counters["open_order_exposure_cents"] == 4166

    for untouched_id in (world["refused_order"]["id"],
                        world["warranty_order"]["id"]):
        untouched = read_order(api, territory, untouched_id)
        assert untouched["status"] == "RECEIVED"
        assert untouched["remake_count"] == 0

    assert read_order(api, territory,
                     world["shared_order"]["id"])["remake_count"] == 1
    assert read_order(api, territory,
                     world["second_shared"]["id"])["remake_count"] == 1
    assert validate_success(api.get_vendor(
        world["sharer"]["id"], franchisor_headers()))["open_order_count"] == 2
    assert read_designer(api, territory,
                        designer["id"])["status"] == "ACTIVE"


def test_every_gate_satisfied_at_its_exact_boundary_still_passes(api):
    """Six gates each met at the value where one more unit would refuse the request.

    "A royalty rate must be at least 0 and at most 0.15."

    "A territory whose `open_leads_count` is one below its `lead_capacity_per_week` is
    still eligible and routes; one whose count has reached its capacity does not."

    "First the billable dimensions are established as floors, not as the ordered dimensions
    themselves: the billable width is the larger of `ordered_width_in` and 12.000 inches,
    and the billable height is the larger of `ordered_height_in` and 12.000 inches, so no
    opening is ever priced as smaller than a foot in either direction."

    "Where the requirement applies, `lift_system` must be `CORDLESS` or `MOTORIZED`; both
    `CORDED` and `CONTINUOUS_LOOP` are refused with `ERR_CORD_HAZARD_NOT_PERMITTED`
    (HTTP 422)."

    "The territory's `open_order_exposure_cents` plus the new order's `order_cost_cents`
    must be at most its `credit_limit_cents`; a breach is `ERR_CREDIT_LIMIT_EXCEEDED`."

    Design: Corner/validations/every_gate_satisfied_at_its_exact_boundary_still_passes
    """
    territory = charter_territory(api, postal_codes=["30301"],
                                royalty_rate_pct=0.15,
                                lead_capacity_per_week=1,
                                credit_limit_cents=1016)
    assert territory["royalty_rate_pct"] == 0.15
    designer = hire_designer(api, territory)
    vendor = onboard_vendor(api, **dict(CORDED_CAPACITY_FIVE,
                                        concurrent_capacity=1,
                                        supported_lift_systems=["CORDLESS"]))

    # Zero open leads is strictly below a capacity of one, so this routes.
    lead = intake_lead(api, territory, child_occupied_dwelling=True)
    assert lead["status"] == "ROUTED"
    assert lead["territory_id"] == territory["id"]

    appointment = book_consultation(api, designer, lead)
    opening = validate_success(api.create_opening(f.opening_payload(
        appointment["id"], label="Transom", room_type="BATH",
        **f.uniform_readings(12.375, 12.250, depth_in=2.500)),
        designer_headers(designer["id"])), 201)
    assert_inches_equal(opening["ordered_width_in"], 11.875,
                        "ordered_width_in")
    assert_inches_equal(opening["ordered_height_in"], 12.000,
                        "ordered_height_in")

    # The 11.875 ordered width is raised to the 12.000 billable floor.
    priced = configure_opening(api, designer, opening,
                               fabric_code="LT-SHEER",
                               lift_system="CORDLESS")
    assert priced["billable_sqft"] == 1.000
    assert priced["list_price_cents"] == 2420

    # A new quote is stamped DRAFT with all of its monetary fields at zero;
    # presentation is the moment the price is computed.
    quote = build_quote(api, designer, appointment)
    assert quote["status"] == "DRAFT"
    assert quote["subtotal_cents"] == 0

    presented = present_quote(api, designer, quote)
    assert presented["status"] == "PRESENTED"
    assert presented["subtotal_cents"] == 2420
    assert presented["install_fee_cents"] == 10000
    assert presented["total_cents"] == 12420
    assert presented["discount_cents"] == 0
    accepted = accept_quote(api, designer, presented)
    assert accepted["status"] == "ACCEPTED"

    owner = franchisee_headers(territory["id"])
    rows, meta = validate_paginated(api.list_ledger_entries(
        territory["id"], owner, entry_type="NET_SALES_ROYALTY"))
    assert_page_meta(meta, total_count=1, has_more=False)
    assert_ledger_entry(rows[0], "NET_SALES_ROYALTY", 363, 2420,
                        "quote_accepted", "QUOTE",
                        source_entity_id=accepted["id"],
                        territory_id=territory["id"])

    # The cost equals the credit limit exactly, and only exposure past it refuses.
    order = place_order(api, territory, accepted, [opening["id"]], vendor)
    assert order["order_cost_cents"] == 1016
    assert order["promised_ship_date"] == "2026-08-11"

    counters = read_territory(api, territory)
    assert counters["open_order_exposure_cents"] == 1016
    assert counters["open_order_exposure_cents"] == counters["credit_limit_cents"]
    assert validate_success(api.get_vendor(
        vendor["id"], franchisor_headers()))["open_order_count"] == 1
