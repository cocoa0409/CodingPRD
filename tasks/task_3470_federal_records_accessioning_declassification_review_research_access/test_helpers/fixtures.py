"""Composite setup helpers.

Every interesting claim needs the system in a state that takes 5-15 API calls
to reach; these fixtures encapsulate those preambles so tests assert instead
of plumbing.  All setup calls go through ``get_success_data`` so a broken
precondition surfaces as a clear "Setup failed" naming the step, never as a
confusing assertion failure downstream.

Identity threading: entity-backed roles are always invoked through the
per-instance header builders — ``make_records_officer_headers(agency["id"])``,
``make_agency_liaison_headers(agency["id"])``,
``make_researcher_headers(registration["id"])`` — because every ownership
check compares X-User-ID to the owning entity's id.

Clock discipline: every date here is either the PRD §2.4 startup default
(2026-09-01T00:00:00Z, the server's boot state before any call) or an instant
reached by an explicit ``set_clock`` call.  ``set_clock`` is idempotent-safe:
a fixture that needs the startup clock sets it explicitly, so test order can
never leak clock state.
"""

from prd_bench_local_runner.testing import get_success_data

from . import factories as F
from .api_client import api_client as _api
from .constants import STARTUP_CLOCK_UTC
from .test_users import (
    TEST_USERS,
    make_agency_liaison_headers,
    make_records_officer_headers,
    make_researcher_headers,
)

ADMIN = TEST_USERS["admin_headers"]
APPRAISER = TEST_USERS["appraiser_headers"]
APPRAISER_2 = TEST_USERS["appraiser_2_headers"]
PROCESSING_ARCHIVIST = TEST_USERS["processing_archivist_headers"]
CHIEF_ARCHIVIST = TEST_USERS["chief_archivist_headers"]
DECLASS_REVIEWER = TEST_USERS["declass_reviewer_headers"]
RESEARCH_ROOM_STAFF = TEST_USERS["research_room_staff_headers"]
FOIA_OFFICER = TEST_USERS["foia_officer_headers"]
FOIA_APPEALS_OFFICER = TEST_USERS["foia_appeals_officer_headers"]
ANONYMOUS = TEST_USERS["anonymous_headers"]


# ─── Tier 0: logical clock ───────────────────────────────────────────────────
def set_clock(to_iso8601=STARTUP_CLOCK_UTC):
    """Set the server logical clock (PlatformAdmin-only, outside /records).

    Returns the ``{current_utc: ...}`` payload.  Defaults to the PRD §2.4
    startup default, so calling ``set_clock()`` at the head of a test pins the
    clock regardless of what any earlier call left behind."""
    return get_success_data(_api.set_clock(to_iso8601, headers=ADMIN))


# ─── Tier 1: agencies and researchers ────────────────────────────────────────
def create_agency(agency_code="DOJ", name="Department of Justice"):
    """Register an agency.  Returns the Agency resource."""
    return get_success_data(
        _api.create_agency(F.agency_payload(agency_code, name), headers=ADMIN)
    )


def register_researcher(
    full_name="Ada Research",
    email="ada@example.org",
    affiliation="ACADEMIC",
    id_document="DL-1001",
):
    """Self-register a researcher (PENDING).  Email is globally unique —
    callers creating several researchers must pass distinct emails."""
    return get_success_data(
        _api.create_researcher(
            F.researcher_payload(full_name, email, affiliation, id_document),
            headers=ANONYMOUS,
        )
    )


def activate_researcher(registration, staff_headers=None):
    """Activate a PENDING registration or renew an EXPIRED one.  Stamps
    card_expires_at = clock + 2 years (anniversary arithmetic)."""
    return get_success_data(
        _api.activate_researcher(registration["id"], headers=staff_headers or RESEARCH_ROOM_STAFF)
    )


def create_active_researcher(
    full_name="Ada Research",
    email="ada@example.org",
    affiliation="ACADEMIC",
    id_document="DL-1001",
):
    """Register + activate.  Returns the ACTIVE ResearcherRegistration."""
    return activate_researcher(
        register_researcher(full_name, email, affiliation, id_document)
    )


# ─── Tier 2: schedule lifecycle ──────────────────────────────────────────────
def create_draft_schedule(agency, **schedule_kwargs):
    """Create a DRAFT schedule for the agency (ownership: caller IS the
    agency).  Default is PERMANENT/FEDERAL/NONE with a 20-year lag."""
    return get_success_data(
        _api.create_schedule(
            F.schedule_payload(agency["id"], **schedule_kwargs),
            headers=make_records_officer_headers(agency["id"]),
        )
    )


def submit_schedule(schedule):
    """Submit a DRAFT schedule or resubmit a RETURNED one."""
    return get_success_data(
        _api.submit_schedule(
            schedule["id"], headers=make_records_officer_headers(schedule["agency_id"])
        )
    )


def appraise_schedule(schedule, recommendation="APPROVE", appraiser_headers=None):
    """Appraise a SUBMITTED schedule; stamps appraiser_id from the caller."""
    return get_success_data(
        _api.appraise_schedule(
            schedule["id"],
            F.appraise_payload(recommendation),
            headers=appraiser_headers or APPRAISER,
        )
    )


def decide_schedule(schedule, decision="APPROVE", decision_note="permanent value confirmed",
                    chief_headers=None):
    """Decide an APPRAISED schedule.  The decider's identity must differ from
    the recorded appraiser_id (segregation of duties) — the default
    CHIEF_ARCHIVIST identity is distinct from the default APPRAISER one."""
    return get_success_data(
        _api.decide_schedule(
            schedule["id"],
            F.decide_schedule_payload(decision, decision_note),
            headers=chief_headers or CHIEF_ARCHIVIST,
        )
    )


def create_approved_schedule(agency, appraiser_headers=None, chief_headers=None, **schedule_kwargs):
    """Walk a schedule DRAFT -> SUBMITTED -> APPRAISED -> APPROVED.
    Returns the APPROVED schedule."""
    schedule = create_draft_schedule(agency, **schedule_kwargs)
    schedule = submit_schedule(schedule)
    schedule = appraise_schedule(schedule, "APPROVE", appraiser_headers)
    return decide_schedule(schedule, "APPROVE", chief_headers=chief_headers)


def create_returned_schedule(agency, appraiser_headers=None, chief_headers=None, **schedule_kwargs):
    """Walk a schedule DRAFT -> SUBMITTED -> APPRAISED -> RETURNED.
    Returns the RETURNED schedule."""
    schedule = create_draft_schedule(agency, **schedule_kwargs)
    schedule = submit_schedule(schedule)
    schedule = appraise_schedule(schedule, "APPROVE", appraiser_headers)
    return decide_schedule(
        schedule, "RETURN", decision_note="insufficient appraisal rationale",
        chief_headers=chief_headers,
    )


# ─── Tier 3: transfers, accession, collections ───────────────────────────────
def create_transfer(agency, schedule, **transfer_kwargs):
    """Initiate a transfer (INITIATED) under an APPROVED PERMANENT schedule."""
    return get_success_data(
        _api.create_transfer(
            F.transfer_payload(schedule["id"], agency["id"], **transfer_kwargs),
            headers=make_records_officer_headers(agency["id"]),
        )
    )


def submit_metadata(transfer, metadata_elements=None, metadata_standard=None):
    """Submit metadata element names.  With no arguments, submits the complete
    required set for the transfer's declared standard, landing VALIDATED.

    PRD §3.2 leaves the required-element names to the implementation ("the
    system holds, for each metadata standard, a defined set of required
    element names"), so the complete-set path is discovery-based: submit,
    read ``last_missing_elements`` from a DEFICIENT response, and resubmit
    with those names merged in.  An explicit ``metadata_elements`` list is
    submitted verbatim (used to probe DEFICIENT)."""
    standard = metadata_standard or transfer["metadata_standard"]
    headers = make_records_officer_headers(transfer["agency_id"])
    if metadata_elements is not None:
        return get_success_data(
            _api.submit_transfer_metadata(
                transfer["id"],
                F.submit_metadata_payload(metadata_elements, standard),
                headers=headers,
            )
        )
    elements = F.metadata_elements_for(standard)
    data = get_success_data(
        _api.submit_transfer_metadata(
            transfer["id"],
            F.submit_metadata_payload(elements, standard),
            headers=headers,
        )
    )
    if data["status"] == "DEFICIENT":
        elements = list(elements) + [
            e for e in data["last_missing_elements"] if e not in elements
        ]
        data = get_success_data(
            _api.submit_transfer_metadata(
                transfer["id"],
                F.submit_metadata_payload(elements, standard),
                headers=headers,
            )
        )
    return data


def create_validated_transfer(agency, schedule, **transfer_kwargs):
    """Initiate a transfer and submit complete metadata.  Returns the
    VALIDATED transfer."""
    transfer = create_transfer(agency, schedule, **transfer_kwargs)
    return submit_metadata(transfer)


def accession_transfer(transfer, receipt_note="received and verified"):
    """Accession a VALIDATED transfer.  Returns the ACCESSIONED transfer,
    which carries ``collection_id`` of the collection created by the
    accession cascade."""
    return get_success_data(
        _api.accession_transfer(
            transfer["id"], F.accession_payload(receipt_note),
            headers=PROCESSING_ARCHIVIST,
        )
    )


def withdraw_transfer(transfer):
    """Withdraw an INITIATED, DEFICIENT, or VALIDATED transfer."""
    return get_success_data(
        _api.withdraw_transfer(
            transfer["id"], headers=make_records_officer_headers(transfer["agency_id"])
        )
    )


def read_collection(collection_id, headers=None):
    """GET one collection, returning the data payload (any declared role may
    read; ProcessingArchivist is the default reader)."""
    return get_success_data(
        _api.get_collection(collection_id, headers=headers or PROCESSING_ARCHIVIST)
    )


def create_collection_bundle(agency=None, schedule_kwargs=None, transfer_kwargs=None):
    """Accession a transfer into a fresh collection.

    Returns a bundle dict: {"agency", "schedule", "transfer", "collection"}.
    The collection is UNPROCESSED; its posture and backlog_score are the
    accession-time computations.  Default configuration: FEDERAL, PERMANENT,
    classification NONE, 50 units, records_cutoff_date 2001-03-15 (records
    age exactly 25 at the startup clock, lag anniversary long past).
    """
    agency = agency or create_agency()
    schedule = create_approved_schedule(agency, **(schedule_kwargs or {}))
    transfer = create_validated_transfer(agency, schedule, **(transfer_kwargs or {}))
    transfer = accession_transfer(transfer)
    collection = read_collection(transfer["collection_id"])
    return {
        "agency": agency,
        "schedule": schedule,
        "transfer": transfer,
        "collection": collection,
    }


# ─── Tier 4: collection processing states ────────────────────────────────────
def begin_processing(collection, archivist_headers=None):
    """Claim an UNPROCESSED collection; stamps assigned_archivist_id."""
    return get_success_data(
        _api.begin_processing(collection["id"], headers=archivist_headers or PROCESSING_ARCHIVIST)
    )


def describe_collection(collection, archivist_headers=None, **description_kwargs):
    """Complete the three description elements, moving PROCESSING ->
    DESCRIBED."""
    return get_success_data(
        _api.complete_description(
            collection["id"],
            F.description_payload(**description_kwargs),
            headers=archivist_headers or PROCESSING_ARCHIVIST,
        )
    )


def enqueue_digitization(collection, archivist_headers=None):
    """Enqueue a DESCRIBED, PUBLIC collection; stamps the demand-weighted
    digitization_priority snapshot."""
    return get_success_data(
        _api.enqueue_digitization(collection["id"], headers=archivist_headers or PROCESSING_ARCHIVIST)
    )


def complete_digitization(collection, archivist_headers=None):
    """Mark a QUEUED collection DIGITIZED."""
    return get_success_data(
        _api.complete_digitization(collection["id"], headers=archivist_headers or PROCESSING_ARCHIVIST)
    )


def publish_digital(collection, chief_headers=None):
    """Publish a DESCRIBED + DIGITIZED + PUBLIC collection (ChiefArchivist)."""
    return get_success_data(
        _api.publish_digital(collection["id"], headers=chief_headers or CHIEF_ARCHIVIST)
    )


def setup_public_described_collection(agency=None, unit_count=50, **kwargs):
    """The workhorse bundle for research-room and reproduction tests: an
    accessioned collection, classification NONE (posture PUBLIC), walked to
    DESCRIBED.  Returns the create_collection_bundle dict with the collection
    refreshed to its DESCRIBED state."""
    transfer_kwargs = dict(kwargs.pop("transfer_kwargs", {}) or {})
    transfer_kwargs.setdefault("unit_count", unit_count)
    bundle = create_collection_bundle(agency=agency, transfer_kwargs=transfer_kwargs, **kwargs)
    collection = begin_processing(bundle["collection"])
    collection = describe_collection(collection)
    bundle["collection"] = collection
    return bundle


def setup_classified_collection(agency=None, classification_default="SECRET", described=False,
                                **kwargs):
    """An accessioned classified collection (posture
    CLASSIFIED_REVIEW_REQUIRED).  With described=True it is also walked to
    DESCRIBED (posture stays restricted — description does not clear
    classification)."""
    schedule_kwargs = dict(kwargs.pop("schedule_kwargs", {}) or {})
    schedule_kwargs.setdefault("classification_default", classification_default)
    bundle = create_collection_bundle(agency=agency, schedule_kwargs=schedule_kwargs, **kwargs)
    if described:
        collection = begin_processing(bundle["collection"])
        collection = describe_collection(collection)
        bundle["collection"] = collection
    return bundle


def setup_presidential_collection(agency=None, **kwargs):
    """An accessioned PRESIDENTIAL-domain collection with classification NONE
    (born PUBLIC until a presidential restriction is imposed).  Uses the
    presidential defaults: lag 12 years, records_cutoff_date 2009-01-20."""
    schedule_kwargs = dict(kwargs.pop("schedule_kwargs", {}) or {})
    schedule_kwargs.setdefault("records_domain", "PRESIDENTIAL")
    schedule_kwargs.setdefault("transfer_lag_years", F.PRESIDENTIAL_TRANSFER_LAG_YEARS)
    transfer_kwargs = dict(kwargs.pop("transfer_kwargs", {}) or {})
    transfer_kwargs.setdefault("records_cutoff_date", F.PRESIDENTIAL_RECORDS_CUTOFF)
    transfer_kwargs.setdefault("unit_count", 30)
    return create_collection_bundle(
        agency=agency, schedule_kwargs=schedule_kwargs, transfer_kwargs=transfer_kwargs, **kwargs
    )


def setup_queued_collection(agency=None, **kwargs):
    """A PUBLIC DESCRIBED collection additionally enqueued for digitization
    (digitization_status QUEUED, priority snapshot stamped)."""
    bundle = setup_public_described_collection(agency=agency, **kwargs)
    bundle["collection"] = enqueue_digitization(bundle["collection"])
    return bundle


def setup_published_collection(agency=None, **kwargs):
    """The full walk: PUBLIC collection DESCRIBED -> QUEUED -> DIGITIZED ->
    PUBLISHED."""
    bundle = setup_queued_collection(agency=agency, **kwargs)
    collection = complete_digitization(bundle["collection"])
    bundle["collection"] = publish_digital(collection)
    return bundle


# ─── Tier 5: OCC + declassification reviews + equity referrals ───────────────
def current_collection_version(collection_id, headers=None):
    """Read the collection's current ``version`` — the value an
    ``expected_collection_version`` token must carry (PRD §2.7)."""
    return read_collection(collection_id, headers=headers)["version"]


def build_review_create_payload(collection_id, review_type, researcher=None,
                                justification=None, headers=None):
    """Build a review-create payload carrying a FRESH
    ``expected_collection_version`` read at call time.  For MANDATORY reviews
    pass the owning researcher and a justification."""
    version = current_collection_version(collection_id, headers=headers)
    return F.declass_review_payload(
        collection_id,
        review_type,
        version,
        requester_researcher_id=researcher["id"] if researcher else None,
        justification=justification,
    )


def create_open_systematic_review(collection):
    """Open a SYSTEMATIC review (ProcessingArchivist) with a fresh OCC token.
    The collection's records must be at least 25 years old at the clock."""
    payload = build_review_create_payload(collection["id"], "SYSTEMATIC")
    return get_success_data(
        _api.create_declass_review(payload, headers=PROCESSING_ARCHIVIST)
    )


def create_open_mdr(collection, researcher, justification="scholarly research"):
    """Open a MANDATORY declassification review as the owning ACTIVE
    researcher, with a fresh OCC token."""
    payload = build_review_create_payload(
        collection["id"], "MANDATORY", researcher=researcher, justification=justification
    )
    return get_success_data(
        _api.create_declass_review(payload, headers=make_researcher_headers(researcher["id"]))
    )


def begin_review(review, reviewer_headers=None):
    """Begin an OPEN review; stamps lead_reviewer_id."""
    return get_success_data(
        _api.begin_declass_review(review["id"], headers=reviewer_headers or DECLASS_REVIEWER)
    )


def create_in_progress_mdr(collection, researcher, justification="scholarly research"):
    """An MDR review opened by the researcher and begun by a DeclassReviewer
    (IN_PROGRESS)."""
    return begin_review(create_open_mdr(collection, researcher, justification))


def create_referrals(review, agency_ids, reviewer_headers=None):
    """Issue bulk equity referrals from an IN_PROGRESS review.  Returns the
    list of created EquityReferral resources (one per agency id)."""
    return get_success_data(
        _api.create_referrals(
            review["id"], F.referrals_payload(agency_ids),
            headers=reviewer_headers or DECLASS_REVIEWER,
        )
    )


def respond_referral(referral, decision="DECLASSIFY", exemption_code=None):
    """Respond to a referral as the referred agency's liaison (ownership:
    caller X-User-ID == referral.agency_id)."""
    return get_success_data(
        _api.respond_to_referral(
            referral["id"],
            F.respond_referral_payload(decision, exemption_code),
            headers=make_agency_liaison_headers(referral["agency_id"]),
        )
    )


def complete_review(review, reviewer_assessment="DECLASSIFY", exemption_code=None,
                    reviewer_headers=None):
    """Complete an IN_PROGRESS review; computes the outcome and cascades into
    the collection (classification cleared on DECLASSIFIED, posture
    recomputed, pending FOIA closed on a flip to PUBLIC)."""
    return get_success_data(
        _api.complete_declass_review(
            review["id"],
            F.complete_review_payload(reviewer_assessment, exemption_code),
            headers=reviewer_headers or DECLASS_REVIEWER,
        )
    )


def setup_in_progress_mdr_with_referral(referral_agency_code="CIA", classification_default="SECRET"):
    """Composite: classified collection + ACTIVE researcher + IN_PROGRESS MDR
    review holding one SENT referral to a second agency.

    Returns {"agency", "schedule", "transfer", "collection", "researcher",
             "referral_agency", "review", "referral"}."""
    bundle = setup_classified_collection(classification_default=classification_default)
    referral_agency = create_agency(referral_agency_code, "Central Intelligence Agency")
    researcher = create_active_researcher()
    review = create_in_progress_mdr(bundle["collection"], researcher)
    referrals = create_referrals(review, [referral_agency["id"]])
    bundle.update(
        {
            "referral_agency": referral_agency,
            "researcher": researcher,
            "review": review,
            "referral": referrals[0],
        }
    )
    return bundle


# ─── Tier 6: FOIA lifecycle ──────────────────────────────────────────────────
def create_foia(researcher, collection, description_of_records="all records responsive to the request"):
    """File a FOIA request (RECEIVED) as the owning ACTIVE researcher against
    a restricted collection."""
    return get_success_data(
        _api.create_foia_request(
            F.foia_request_payload(researcher["id"], collection["id"], description_of_records),
            headers=make_researcher_headers(researcher["id"]),
        )
    )


def adjudicate_foia(foia, decision="GRANT", claimed_exemptions=None, officer_headers=None):
    """Adjudicate a RECEIVED or IN_REVIEW request.  PARTIAL/DENY need a
    non-empty claimed_exemptions subset of {B1, B3, B5}."""
    return get_success_data(
        _api.adjudicate_foia_request(
            foia["id"],
            F.adjudicate_payload(decision, claimed_exemptions),
            headers=officer_headers or FOIA_OFFICER,
        )
    )


def create_denied_foia(researcher, collection, claimed_exemptions=None, officer_headers=None,
                       description_of_records="all records responsive to the request"):
    """A FOIA request adjudicated DENY (DENIED, appealable)."""
    foia = create_foia(researcher, collection, description_of_records)
    return adjudicate_foia(
        foia, "DENY", claimed_exemptions or ["B1"], officer_headers=officer_headers
    )


def appeal_foia(foia, appeal_reason="public interest outweighs"):
    """Appeal a PARTIAL_GRANT or DENIED request as the owning researcher."""
    # Ownership: the appeal caller must be the request's researcher.
    return get_success_data(
        _api.appeal_foia_request(
            foia["id"],
            F.appeal_payload(appeal_reason),
            headers=make_researcher_headers(foia["researcher_id"]),
        )
    )


def create_appealed_foia(researcher, collection, claimed_exemptions=None, officer_headers=None,
                         description_of_records="all records responsive to the request"):
    """A FOIA request walked RECEIVED -> DENIED -> APPEALED."""
    return appeal_foia(
        create_denied_foia(researcher, collection, claimed_exemptions, officer_headers,
                           description_of_records=description_of_records)
    )


def decide_appeal(foia, appeal_decision="GRANT", appeals_headers=None):
    """Decide an APPEALED request.  The decider's identity must differ from
    the recorded adjudicator_id (segregation of duties)."""
    return get_success_data(
        _api.decide_foia_appeal(
            foia["id"],
            F.decide_appeal_payload(appeal_decision),
            headers=appeals_headers or FOIA_APPEALS_OFFICER,
        )
    )


# ─── Tier 7: presidential restrictions ───────────────────────────────────────
def impose_restriction(collection, category="P5_CONFIDENTIAL_ADVICE", chief_headers=None):
    """Impose a P1..P6 restriction on a PRESIDENTIAL-domain collection
    (IMPOSED; recomputes the collection posture to PRESIDENTIAL_HOLD)."""
    return get_success_data(
        _api.create_presidential_restriction(
            F.restriction_payload(collection["id"], category),
            headers=chief_headers or CHIEF_ARCHIVIST,
        )
    )


def designate_representative(restriction, representative_id="rep-44", chief_headers=None):
    """Designate the former president's representative (in-state update on
    IMPOSED)."""
    return get_success_data(
        _api.designate_restriction_representative(
            restriction["id"],
            F.designate_payload(representative_id),
            headers=chief_headers or CHIEF_ARCHIVIST,
        )
    )


def notify_restriction(restriction, chief_headers=None):
    """Notify the designated representative; starts the 30-day cooling
    period (stamps notified_at from the logical clock)."""
    return get_success_data(
        _api.notify_restriction(restriction["id"], headers=chief_headers or CHIEF_ARCHIVIST)
    )


def create_notified_restriction(collection, category="P5_CONFIDENTIAL_ADVICE",
                                representative_id="rep-44"):
    """A restriction walked IMPOSED -> designate -> NOTIFIED."""
    restriction = impose_restriction(collection, category)
    restriction = designate_representative(restriction, representative_id)
    return notify_restriction(restriction)


def release_restriction(restriction, chief_headers=None):
    """Release a NOTIFIED restriction once the 30-day cooling period has
    elapsed; recomputes the collection posture and may fire the posture-flip
    cascade that closes pending FOIA requests."""
    return get_success_data(
        _api.release_restriction(restriction["id"], headers=chief_headers or CHIEF_ARCHIVIST)
    )


# ─── Tier 8: pull requests ───────────────────────────────────────────────────
def create_pull(researcher, collection, unit_start=1, unit_end=5, visit_date=F.DEFAULT_VISIT_DATE):
    """File a pull request (REQUESTED) as the owning ACTIVE researcher.
    due_back_at is visit_date + 24 hours; the pull occupies a reading-room
    seat on the visit day and the following UTC day."""
    return get_success_data(
        _api.create_pull_request(
            F.pull_request_payload(
                researcher["id"], collection["id"], unit_start, unit_end, visit_date
            ),
            headers=make_researcher_headers(researcher["id"]),
        )
    )


def fulfill_pull(pull, staff_headers=None):
    """Fulfill a REQUESTED pull (PULLED); increments the collection's
    pull_count_total and recomputes a QUEUED priority."""
    return get_success_data(
        _api.fulfill_pull_request(pull["id"], headers=staff_headers or RESEARCH_ROOM_STAFF)
    )


def return_pull(pull, staff_headers=None):
    """Return a PULLED pull (RETURNED).  A late return (clock strictly after
    due_back_at) suspends the researcher and cascades cancellations of their
    pending work."""
    return get_success_data(
        _api.return_pull_request(pull["id"], headers=staff_headers or RESEARCH_ROOM_STAFF)
    )


def create_fulfilled_pull(researcher, collection, unit_start=1, unit_end=5,
                          visit_date=F.DEFAULT_VISIT_DATE):
    """A pull walked REQUESTED -> PULLED."""
    return fulfill_pull(create_pull(researcher, collection, unit_start, unit_end, visit_date))


def fulfill_and_return_pull(pull):
    """Walk a PULLED pull to RETURNED at the current clock (late_return is
    computed from the clock versus due_back_at)."""
    return return_pull(pull)


# ─── Tier 9: reproduction requests ───────────────────────────────────────────
def create_reproduction(researcher, collection, page_count=10, format="DIGITAL_SCAN", rush=None):
    """File a reproduction request (QUOTED) as the owning ACTIVE researcher;
    fee_cents is computed at creation in the canonical PRD §3.8 order."""
    return get_success_data(
        _api.create_reproduction_request(
            F.reproduction_payload(researcher["id"], collection["id"], page_count, format, rush),
            headers=make_researcher_headers(researcher["id"]),
        )
    )


def pay_reproduction(repro, payment_reference="card-txn-1"):
    """Pay a QUOTED reproduction as the owning researcher (PAID)."""
    return get_success_data(
        _api.pay_reproduction_request(
            repro["id"],
            F.pay_payload(payment_reference),
            headers=make_researcher_headers(repro["researcher_id"]),
        )
    )


def fulfill_reproduction(repro, staff_headers=None):
    """Fulfill a PAID reproduction (FULFILLED); adds page_count to the
    collection's repro_pages_fulfilled and recomputes a QUEUED priority."""
    return get_success_data(
        _api.fulfill_reproduction_request(repro["id"], headers=staff_headers or RESEARCH_ROOM_STAFF)
    )


def cancel_reproduction(repro):
    """Cancel a QUOTED reproduction as the owning researcher; its pages stop
    counting toward the daily 200-page quota."""
    return get_success_data(
        _api.cancel_reproduction_request(
            repro["id"], headers=make_researcher_headers(repro["researcher_id"])
        )
    )


def create_paid_reproduction(researcher, collection, page_count=10, format="DIGITAL_SCAN",
                             rush=None, payment_reference="card-txn-1"):
    """A reproduction walked QUOTED -> PAID."""
    return pay_reproduction(
        create_reproduction(researcher, collection, page_count, format, rush),
        payment_reference,
    )


def create_fulfilled_reproduction(researcher, collection, page_count=10, format="DIGITAL_SCAN",
                                  rush=None):
    """A reproduction walked QUOTED -> PAID -> FULFILLED."""
    return fulfill_reproduction(
        create_paid_reproduction(researcher, collection, page_count, format, rush)
    )
