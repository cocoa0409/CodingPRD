"""Corner coverage: researcher card lifecycle, referral idempotency,
collection processing/digitization walk, and second-order state guards."""

import test_helpers as th

E = th.ApiErrorId


def test_researcher_lazy_expiry_and_renewal(api):
    """PRD §3.7: "stamping `card_expires_at` — null until this first activation
    — as the activation instant plus two years under anniversary arithmetic;
    the research card is valid for two years."
    PRD §3.7: "on any load of a registration, if the clock has reached or
    passed `card_expires_at`, the registration is persisted as `EXPIRED` right
    there — at exactly the expiry instant the card is expired, while one second
    earlier it is still active — and its `version` advances when that lazy
    transition fires."
    PRD §3.7: "The same activation call renews an `EXPIRED` registration back
    to `ACTIVE` with a fresh two-year `card_expires_at`."
    PRD §2.6: "Where a workflow requires an active researcher, the registration
    must be `ACTIVE`; the lazy expiry evaluation of §2.4 runs first, so a
    registration whose card has just lapsed is persisted `EXPIRED` and only
    then rejected with `ERR_RESEARCHER_NOT_ACTIVE` (409)."

    Design: Corner/state_machines/researcher_lazy_expiry_and_renewal
    """
    th.set_clock()
    bundle = th.setup_public_described_collection()
    ada = th.create_active_researcher()  # activated at the startup clock
    assert th.same_instant(ada["card_expires_at"], "2028-09-01T00:00:00Z")

    # One second before expiry the card is still ACTIVE.
    th.set_clock("2028-08-31T23:59:59Z")
    resp = api.create_pull_request(
        th.pull_request_payload(
            ada["id"], bundle["collection"]["id"], 1, 5, "2028-09-05T00:00:00Z"
        ),
        headers=th.make_researcher_headers(ada["id"]),
    )
    th.validate_success(resp, 201)

    # At exactly card_expires_at the lazy evaluation persists EXPIRED.
    th.set_clock("2028-09-01T00:00:00Z")
    loaded = th.validate_success(
        api.get_researcher(ada["id"], headers=th.TEST_USERS["research_room_staff_headers"]),
        200,
    )
    assert loaded["status"] == "EXPIRED"

    resp = api.create_pull_request(
        th.pull_request_payload(
            ada["id"], bundle["collection"]["id"], 6, 10, "2028-09-05T00:00:00Z"
        ),
        headers=th.make_researcher_headers(ada["id"]),
    )
    th.validate_error(resp, E.ERR_RESEARCHER_NOT_ACTIVE)

    renewed = th.validate_success(
        api.activate_researcher(
            ada["id"], headers=th.TEST_USERS["research_room_staff_headers"]
        ),
        200,
    )
    assert renewed["status"] == "ACTIVE"
    assert th.same_instant(renewed["card_expires_at"], "2030-09-01T00:00:00Z")

    resp = api.create_pull_request(
        th.pull_request_payload(
            ada["id"], bundle["collection"]["id"], 6, 10, "2028-09-05T00:00:00Z"
        ),
        headers=th.make_researcher_headers(ada["id"]),
    )
    th.validate_success(resp, 201)


def test_referral_respond_twice_rejected(api):
    """PRD §3.5: "The parent review must still be `IN_PROGRESS`
    (`ERR_REVIEW_NOT_IN_PROGRESS`), and the referral must still be `SENT` —
    answering an already-answered referral is rejected with
    `ERR_REFERRAL_ALREADY_RESPONDED` (409)."
    PRD §3.5: "Responding moves the referral to `RESPONDED` and records
    `decision`, `exemption_code`, and `responded_at`."

    Design: Corner/state_machines/referral_respond_twice_rejected
    """
    th.set_clock()
    ctx = th.setup_in_progress_mdr_with_referral()
    referral = ctx["referral"]
    liaison = th.make_agency_liaison_headers(referral["agency_id"])

    first = th.validate_success(
        api.respond_to_referral(
            referral["id"], th.respond_referral_payload("DECLASSIFY"), headers=liaison
        ),
        200,
    )
    assert first["status"] == "RESPONDED"
    assert first["decision"] == "DECLASSIFY"
    assert th.same_instant(first["responded_at"], th.STARTUP_CLOCK_UTC)

    th.validate_error(
        api.respond_to_referral(
            referral["id"], th.respond_referral_payload("EXEMPT", "B1"), headers=liaison
        ),
        E.ERR_REFERRAL_ALREADY_RESPONDED,
    )

    after = th.get_success_data(
        api.get_equity_referral(
            referral["id"], headers=th.TEST_USERS["declass_reviewer_headers"]
        )
    )
    assert after["status"] == "RESPONDED"
    assert after["decision"] == "DECLASSIFY"


def test_collection_processing_lifecycle_and_invalid_froms(api):
    """PRD §2.6: "The generic rejection is `ERR_INVALID_STATE` (409)"
    PRD §3.4: "A `ProcessingArchivist` may enqueue a collection for
    digitization when three conditions all hold: `processing_status` is
    `DESCRIBED` (`ERR_COLLECTION_NOT_DESCRIBED`, 409, otherwise),
    `restriction_posture` is `PUBLIC` (`ERR_COLLECTION_RESTRICTED`, 403,
    otherwise), and `digitization_status` is still `NOT_REQUESTED`
    (`ERR_INVALID_STATE` otherwise)."
    PRD §3.4: "The **processing dimension** (`processing_status`) walks
    `UNPROCESSED → PROCESSING → DESCRIBED → PUBLISHED`. The **digitization
    dimension** (`digitization_status`) walks `NOT_REQUESTED → QUEUED →
    DIGITIZED`."

    Design: Corner/state_machines/collection_processing_lifecycle_and_invalid_froms
    """
    th.set_clock()
    bundle = th.create_collection_bundle()
    collection = bundle["collection"]
    archivist = th.TEST_USERS["processing_archivist_headers"]

    th.validate_error(
        api.complete_description(
            collection["id"], th.description_payload(), headers=archivist
        ),
        E.ERR_INVALID_STATE,
    )
    th.validate_error(api.enqueue_digitization(collection["id"], headers=archivist),
                      E.ERR_COLLECTION_NOT_DESCRIBED)

    collection = th.begin_processing(collection)
    collection = th.describe_collection(collection)
    collection = th.enqueue_digitization(collection)
    collection = th.complete_digitization(collection)
    published = th.validate_success(
        api.publish_digital(
            collection["id"], headers=th.TEST_USERS["chief_archivist_headers"]
        ),
        200,
    )
    assert published["processing_status"] == "PUBLISHED"
    assert published["digitization_status"] == "DIGITIZED"

    th.validate_error(api.enqueue_digitization(collection["id"], headers=archivist),
                      E.ERR_INVALID_STATE)


def test_reproduction_double_pay_rejected(api):
    """PRD §3.8: "The owning `Researcher` pays a `QUOTED` request
    (`ERR_OWNERSHIP_MISMATCH` for anyone else; `ERR_REPRO_NOT_PAYABLE`, 409, if
    it is not `QUOTED`), recording a `payment_reference` as the request moves
    to `PAID`."

    Design: Corner/state_machines/reproduction_double_pay_rejected
    """
    th.set_clock()
    bundle = th.setup_public_described_collection()
    bob = th.create_active_researcher(
        "Bob Press", "bob@example.org", "JOURNALIST", "PP-2002"
    )
    repro = th.create_reproduction(bob, bundle["collection"], 10)

    paid = th.validate_success(
        api.pay_reproduction_request(
            repro["id"], th.pay_payload("card-txn-1"),
            headers=th.make_researcher_headers(bob["id"]),
        ),
        200,
    )
    assert paid["status"] == "PAID"
    assert paid["payment_reference"] == "card-txn-1"

    th.validate_error(
        api.pay_reproduction_request(
            repro["id"], th.pay_payload("card-txn-2"),
            headers=th.make_researcher_headers(bob["id"]),
        ),
        E.ERR_REPRO_NOT_PAYABLE,
    )

    after = th.get_success_data(
        api.get_reproduction_request(
            repro["id"], headers=th.TEST_USERS["research_room_staff_headers"]
        )
    )
    assert after["payment_reference"] == "card-txn-1"


def test_pull_return_before_fulfill_rejected(api):
    """PRD §3.7: "`ResearchRoomStaff` return a `PULLED` pull, moving it to
    `RETURNED`; returning anything else is rejected with
    `ERR_PULL_NOT_RETURNABLE` (409)."
    PRD §3.7: "the pull is late when `returned_at` falls strictly after
    `due_back_at` — a return at exactly the due instant is on time."
    PRD §3.7: "Fulfillment also feeds the collection's demand profile:
    `pull_count_total` increments by one, the collection's `version` advances,
    and if the collection is `QUEUED` for digitization its
    `digitization_priority` is recomputed on the spot."

    Design: Corner/state_machines/pull_return_before_fulfill_rejected
    """
    th.set_clock()
    bundle = th.setup_public_described_collection()
    collection = bundle["collection"]
    ada = th.create_active_researcher()
    pull = th.create_pull(ada, collection, 1, 5, "2026-09-10T00:00:00Z")
    staff = th.TEST_USERS["research_room_staff_headers"]

    th.validate_error(api.return_pull_request(pull["id"], headers=staff),
                      E.ERR_PULL_NOT_RETURNABLE)

    still = th.get_success_data(api.get_pull_request(pull["id"], headers=staff))
    assert still["status"] == "REQUESTED"

    pulled = th.validate_success(api.fulfill_pull_request(pull["id"], headers=staff), 200)
    assert pulled["status"] == "PULLED"

    returned = th.validate_success(api.return_pull_request(pull["id"], headers=staff), 200)
    assert returned["status"] == "RETURNED"
    assert returned["late_return"] is False
    assert th.same_instant(returned["due_back_at"], "2026-09-11T00:00:00Z")

    collection_after = th.read_collection(collection["id"])
    assert collection_after["pull_count_total"] == 1


def test_second_order_state_guards(api):
    """PRD §3.7: "`ResearchRoomStaff` fulfill a `REQUESTED` pull, moving it to
    `PULLED`; fulfilling anything else is rejected with
    `ERR_PULL_NOT_FULFILLABLE` (409)."
    PRD §3.8: "the owning researcher may cancel a request while it is still
    `QUOTED` (`ERR_REPRO_NOT_CANCELLABLE`, 409, otherwise)"
    PRD §3.4: "A `ProcessingArchivist` marks a `QUEUED` collection's
    digitization complete, moving it to `DIGITIZED`; completing a collection
    that is not `QUEUED` is rejected with `ERR_DIGITIZATION_NOT_QUEUED` (409)."
    PRD §3.4: "publishing digital surrogates moves a `DESCRIBED` collection to
    `PUBLISHED`, but only when the digitization dimension has reached
    `DIGITIZED` (`ERR_DIGITIZATION_NOT_READY`, 409, otherwise) and the posture
    is `PUBLIC` (`ERR_COLLECTION_RESTRICTED` otherwise)."

    Design: Corner/state_machines/second_order_state_guards
    """
    th.set_clock()
    bundle = th.setup_public_described_collection()
    collection = bundle["collection"]
    bob = th.create_active_researcher(
        "Bob Press", "bob@example.org", "JOURNALIST", "PP-2002"
    )
    staff = th.TEST_USERS["research_room_staff_headers"]
    archivist = th.TEST_USERS["processing_archivist_headers"]

    pull = th.create_fulfilled_pull(bob, collection, 1, 5, "2026-09-10T00:00:00Z")
    th.validate_error(api.fulfill_pull_request(pull["id"], headers=staff),
                      E.ERR_PULL_NOT_FULFILLABLE)

    repro = th.create_paid_reproduction(bob, collection, 10, "PHOTOPRINT")
    th.validate_error(
        api.cancel_reproduction_request(
            repro["id"], headers=th.make_researcher_headers(bob["id"])
        ),
        E.ERR_REPRO_NOT_CANCELLABLE,
    )

    th.validate_error(api.complete_digitization(collection["id"], headers=archivist),
                      E.ERR_DIGITIZATION_NOT_QUEUED)

    collection = th.enqueue_digitization(collection)
    th.validate_error(
        api.publish_digital(
            collection["id"], headers=th.TEST_USERS["chief_archivist_headers"]
        ),
        E.ERR_DIGITIZATION_NOT_READY,
    )

    after = th.read_collection(collection["id"])
    assert after["processing_status"] == "DESCRIBED"
    assert after["digitization_status"] == "QUEUED"
