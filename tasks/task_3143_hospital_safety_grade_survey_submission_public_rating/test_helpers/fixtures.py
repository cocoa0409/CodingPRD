"""Composite setup helpers.

Each helper walks the API through the multi-step preconditions a test needs,
building every resource from scratch because the server starts empty before
every test. Setup failures raise a "Setup failed" assertion carrying the
response body so the cause is obvious.
"""

from types import SimpleNamespace as NS

from .api_client import api_client
from .constants import (
    BASELINE_MEASURE_DEFINITIONS,
    CLOCK_2026_06_01,
    CLOCK_2026_07_15,
    DOCUMENT_CODES,
    FOUR_MEASURE_DEFINITIONS,
    FIVE_DOMAIN_MEASURE_DEFINITIONS,
    REFERENCE_MEASURE_DEFINITIONS,
    REFERENCE_RAW_VALUES,
    REFERENCE_SOURCE_PROGRAMS,
    SIX_DOCUMENT_CODES,
    WINDOW_END,
)
from .factories import (
    accept_preliminary_result_payload,
    create_correction_payload,
    create_employer_payload,
    create_hospital_payload,
    create_methodology_version_payload,
    create_preliminary_result_payload,
    create_reanalysis_request_payload,
    create_release_cycle_payload,
    create_score_run_payload,
    create_survey_measure_payload,
    create_survey_payload,
    decide_correction_payload,
    decide_reanalysis_payload,
    measure_definition,
    next_ccn,
    pending_methodology_change_payload,
    refresh_measures_payload,
    set_network_listing_payload,
    supporting_document,
)
from .test_users import TEST_USERS, make_purchaser_headers, make_respondent_headers

ADMIN = TEST_USERS["rating_admin_headers"]
ANALYST = TEST_USERS["analyst_headers"]
ENGINE = TEST_USERS["engine_headers"]
READER = TEST_USERS["reader_headers"]
PURCHASER = TEST_USERS["purchaser_headers"]


# ─── low-level plumbing ──────────────────────────────────────────────────────

def _ok(label, response, expected=None):
    """Return the success payload of a setup call, or fail loudly."""
    if expected is not None:
        assert response.status_code == expected, (
            f"Setup failed: {label} expected HTTP {expected}, "
            f"got {response.status_code}: {response.text}"
        )
    elif not (200 <= response.status_code < 300):
        raise AssertionError(
            f"Setup failed: {label} returned HTTP {response.status_code}: {response.text}"
        )
    try:
        body = response.json()
    except Exception as exc:  # pragma: no cover - defensive
        raise AssertionError(f"Setup failed: {label} returned non-JSON: {response.text}") from exc
    data = body.get("data")
    assert isinstance(data, dict), f"Setup failed: {label} returned no data object: {body}"
    return data


def set_clock(to_iso8601: str):
    """Advance the logical clock to a named instant."""
    result = _ok("set clock", api_client.set_clock(to_iso8601, ADMIN))
    _CLOCK_LAST["instant"] = to_iso8601
    return result


def current_hospital_version(hospital_id):
    """The hospital's current `version`, read through the declared GET surface.

    PRD §2.7 makes `expected_hospital_version` an optimistic-concurrency token:
    it must equal the hospital's current `version` *at the time of the write*,
    and "no other write operation in the API accepts a version field". Every
    setup helper that has mutated the hospital since the caller last held its
    representation must therefore re-read it rather than reuse a stale handle,
    or it is the *fixture* that violates the declared precondition.
    """
    return _ok("read hospital", api_client.get_hospital(hospital_id, READER))["version"]


def current_measure_set_version(measure_set_id):
    """The measure set's current `version`, read through `GET /hospital-measure-sets/{id}`."""
    return _ok("read measure set", api_client.get_measure_set(measure_set_id, READER))["version"]


# ─── Version-token coherence ─────────────────────────────────────────────────
#
# `expected_hospital_version` is an optimistic-concurrency token, not a fixed
# datum: PRD §2.7 requires it to equal the hospital's current `version` *at the
# time of the write*. A setup chain mutates the hospital at almost every step
# (pin, open survey, each recorded measure, submit, verify, refresh, …), so a
# handle captured at step 3 is stale by step 8 and would be refused — correctly.
#
# The setup helpers in this module therefore resolve the token live: they read
# the hospital (or measure set) immediately before they issue the guarded write
# and fall back to a fresh read whenever the caller-supplied value no longer
# matches. Tests that deliberately exercise the staleness rule never route
# through these helpers — they call `api_client` directly with an explicitly
# observed version, so the rejection they assert is unaffected.
#
# The helpers below return the *current* token; `_resolve_token` decides whether
# the caller's cached handle is still usable.

def _resolve_token(observed, live_reader):
    """Use ``observed`` when it is still current, else fall back to a live read."""
    live = live_reader()
    if observed is None:
        return live
    try:
        return int(observed) if int(observed) == int(live) else live
    except (TypeError, ValueError):
        return live


def _hospital_token(hospital_id, observed):
    return _resolve_token(
        observed, lambda: current_hospital_version(hospital_id))


def _measure_set_token(measure_set_id, observed):
    return _resolve_token(
        observed, lambda: current_measure_set_version(measure_set_id))


# ─── Logical-clock helpers ───────────────────────────────────────────────────
#
# PRD §2.9: the API runs on a logical clock whose startup default is exactly
# `2026-09-01T00:00:00Z` and which never falls back to wall-clock time. Setup
# only ever needs a *strictly later* instant than the one a previous refresh
# stamped into a measure set's `source_snapshot_at`, because PRD §3.4 refuses a
# refresh at an unchanged instant with `ERR_SNAPSHOT_ALREADY_CURRENT`. Deriving
# the instant from that stamp keeps the guarantee regardless of how many
# refreshes a fixture performs, and keeps every generated instant a well-formed
# calendar instant — a naive `2026-06-<n>` counter emits `2026-06-32`, which the
# server correctly rejects as `ERR_INVALID_REQUEST`.

_CLOCK_LAST = {"instant": CLOCK_2026_06_01}


def _instant_after(iso8601):
    """One hour after the given instant, rendered with three fractional digits."""
    from datetime import datetime, timedelta, timezone

    text = str(iso8601).strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        base = datetime.fromisoformat(text)
    except ValueError:
        base = datetime(2026, 6, 1, tzinfo=timezone.utc)
    if base.tzinfo is None:
        base = base.replace(tzinfo=timezone.utc)
    moment = base.astimezone(timezone.utc) + timedelta(hours=1)
    return moment.strftime("%Y-%m-%dT%H:%M:%S.000Z")


def advance_clock(from_instant=None):
    """Move the logical clock one hour past `from_instant` (or the last reset).

    Setup never pins a business instant with this helper, so moving by an hour
    inside the cycle's own review window is safe; what matters is that the
    instant strictly advances, so a refresh that would otherwise be refused as
    unchanged always makes progress.
    """
    base = from_instant or _CLOCK_LAST["instant"]
    instant = _instant_after(base)
    _CLOCK_LAST["instant"] = instant
    set_clock(instant)
    return instant


def register_hospital(**overrides):
    """Register an ACTIVE hospital."""
    return _ok("register hospital", api_client.create_hospital(create_hospital_payload(**overrides), ADMIN), 201)


def publish_methodology(measure_definitions, label="Test Methodology",
                        publication_date="2026-05-01T00:00:00Z", previous_version_id=None):
    """Author a methodology version and publish it."""
    payload = create_methodology_version_payload(
        measure_definitions, label=label, publication_date=publication_date,
    )
    if previous_version_id is not None:
        payload["previous_version_id"] = previous_version_id
    version = _ok("create methodology version",
                  api_client.create_methodology_version(payload, ADMIN), 201)
    published = _ok("publish methodology version",
                    api_client.publish_methodology_version(version["id"], ADMIN))
    return published


def pin_methodology(hospital_id, methodology_version_id):
    """Pin a published methodology version to a hospital."""
    return _ok("pin methodology version",
               api_client.pin_methodology_version(
                   hospital_id, {"methodology_version_id": methodology_version_id}, ADMIN), 201)


def open_survey(hospital_id, **overrides):
    """Open a survey as the hospital's own respondent."""
    return _ok("open survey", api_client.create_survey(
        hospital_id, create_survey_payload(**overrides), make_respondent_headers(hospital_id)), 201)


def record_measure(hospital_id, survey_id, measure_code, raw_value,
                   source_program_id="CMS_HOSPITAL_COMPARE", **overrides):
    """Record a reported measure for the hospital."""
    payload = create_survey_measure_payload(
        survey_id, measure_code, raw_value, source_program_id, **overrides)
    return _ok("record measure", api_client.create_survey_measure(
        hospital_id, payload, make_respondent_headers(hospital_id)), 201)


def submit_survey(hospital_id, survey_id):
    return _ok("submit survey", api_client.submit_survey(
        survey_id, make_respondent_headers(hospital_id)))


def verify_survey(survey_id, response="ACCEPT"):
    return _ok(f"verify survey ({response})", api_client.verify_survey(
        survey_id, {"verification_response": response}, ANALYST))


def resolve_survey(hospital_id, survey_id):
    return _ok("resolve survey", api_client.resolve_survey(
        survey_id, make_respondent_headers(hospital_id)))


def ingest_public_source_measure(hospital_id, measure_code, source_program_id, source_value):
    return _ok("ingest public source measure", api_client.create_public_source_measure(
        hospital_id,
        {"measure_code": measure_code, "source_program_id": source_program_id,
         "source_value": source_value},
        ADMIN), 201)


def _latest_snapshot_at(hospital_id):
    """The newest `source_snapshot_at` stamped on the hospital's measure sets."""
    response = api_client.list_measure_sets(READER, {"hospital_id": hospital_id})
    assert response.status_code == 200, (
        f"Setup failed: listing measure sets returned {response.status_code}: {response.text}")
    stamps = [
        row.get("source_snapshot_at")
        for row in response.json()["data"]
        if row.get("source_snapshot_at")
    ]
    if not stamps:
        return None
    return max(stamps)


def refresh_measures(hospital_id, expected_hospital_version=None, at=None):
    """Rematerialise a hospital's measure set.

    A refresh at an unchanged logical-clock instant rewrites nothing and is
    refused with `ERR_SNAPSHOT_ALREADY_CURRENT` (PRD §3.4), so the clock is
    advanced one hour past the set's own `source_snapshot_at` unless the caller
    pinned an instant. The version token is resolved against the hospital's
    current `version` immediately before the write, so a caller still holding an
    older representation of the hospital is served rather than refused.
    """
    if at is None:
        advance_clock(_latest_snapshot_at(hospital_id) or _CLOCK_LAST["instant"])
    else:
        set_clock(at)
    return _ok("refresh measures", api_client.refresh_measures(
        hospital_id,
        refresh_measures_payload(_hospital_token(hospital_id, expected_hospital_version)),
        ENGINE))


def cut_score_run(hospital_id, methodology_version_id, release_cycle_id,
                  expected_hospital_version=None):
    """Cut a score run, resolving the version token against the live hospital.

    PRD §3.5 guards the run on the *hospital's* version, so the token is always
    the hospital's current `version` — never a measure set's.
    """
    return _ok("cut score run", api_client.create_score_run(
        hospital_id,
        create_score_run_payload(methodology_version_id, release_cycle_id,
                                 _hospital_token(hospital_id, expected_hospital_version)),
        ENGINE), 201)


def create_cycle(methodology_version_id, label="Test Grades",
                 preliminary_release_date="2026-06-01T00:00:00Z",
                 correction_window_ends_at=WINDOW_END,
                 publication_date="2026-07-15T00:00:00Z"):
    return _ok("create release cycle", api_client.create_release_cycle(
        create_release_cycle_payload(
            methodology_version_id, label=label,
            preliminary_release_date=preliminary_release_date,
            correction_window_ends_at=correction_window_ends_at,
            publication_date=publication_date,
        ), ADMIN), 201)


def open_cycle_review(cycle_id):
    return _ok("open review", api_client.open_review(cycle_id, ENGINE))


def publish_cycle(cycle_id):
    return _ok("publish cycle", api_client.publish_release_cycle(cycle_id, ENGINE))


def get_grade_for(hospital_id, cycle_id):
    """Read the hospital's grade in the cycle."""
    response = api_client.list_hospital_grades(hospital_id, READER, {"release_cycle_id": cycle_id})
    assert response.status_code == 200, (
        f"Setup failed: listing grades returned {response.status_code}: {response.text}")
    rows = response.json()["data"]
    assert rows, f"Setup failed: no grade for hospital {hospital_id} in cycle {cycle_id}"
    return rows[0]


def get_review_for(hospital_id, cycle_id):
    """Read the hospital's preliminary-result review in the cycle."""
    response = api_client.list_hospital_reviews(hospital_id, READER, {"release_cycle_id": cycle_id})
    assert response.status_code == 200, (
        f"Setup failed: listing reviews returned {response.status_code}: {response.text}")
    rows = response.json()["data"]
    assert rows, f"Setup failed: no review for hospital {hospital_id} in cycle {cycle_id}"
    return rows[0]


def accept_review(hospital_id, review_id, expected_hospital_version=None):
    """Accept a preliminary result, resolving the token against the live hospital."""
    return _ok("accept preliminary result", api_client.accept_preliminary_result(
        hospital_id, review_id,
        accept_preliminary_result_payload(
            _hospital_token(hospital_id, expected_hospital_version)),
        make_respondent_headers(hospital_id)))


def file_correction(hospital_id, review_id, corrected_measure_codes,
                    correction_type="MEASURE_VALUE_ERROR"):
    return _ok("file correction", api_client.create_correction(
        hospital_id, review_id,
        create_correction_payload(corrected_measure_codes, correction_type),
        make_respondent_headers(hospital_id)), 201)


def decide_correction(hospital_id, review_id, correction_id, decision):
    return _ok(f"decide correction ({decision})", api_client.decide_correction(
        hospital_id, review_id, correction_id, decide_correction_payload(decision), ENGINE))


def raise_reanalysis(hospital_id, survey_id, subset_selector, document_count=6,
                     requested_delta=None):
    documents = [supporting_document(code) for code in DOCUMENT_CODES[:document_count]]
    return _ok("raise reanalysis request", api_client.create_reanalysis_request(
        hospital_id,
        create_reanalysis_request_payload(survey_id, subset_selector, documents, requested_delta),
        make_respondent_headers(hospital_id)), 201)


def decide_reanalysis(hospital_id, request_id, decision):
    return _ok(f"decide reanalysis ({decision})", api_client.decide_reanalysis_request(
        hospital_id, request_id, decide_reanalysis_payload(decision), ANALYST))


def withdraw_reanalysis(hospital_id, request_id):
    return _ok("withdraw reanalysis", api_client.decide_reanalysis_request(
        hospital_id, request_id, decide_reanalysis_payload("WITHDRAW"),
        make_respondent_headers(hospital_id)))


def register_employer(network_hospital_ids=None, **overrides):
    return _ok("register employer", api_client.create_employer(
        create_employer_payload(network_hospital_ids, **overrides), PURCHASER), 201)


def set_network(employer_id, network_hospital_ids, **overrides):
    return _ok("set network listing", api_client.set_network_listing(
        employer_id, set_network_listing_payload(network_hospital_ids, **overrides),
        make_purchaser_headers(employer_id)))


def raise_pending_change(hospital_id, to_methodology_version_id):
    return _ok("raise pending methodology change", api_client.create_pending_methodology_change(
        hospital_id, pending_methodology_change_payload(to_methodology_version_id), ADMIN), 201)


def review_pending_change(change_id, decision):
    return _ok("review pending methodology change", api_client.review_pending_methodology_change(
        change_id, {"decision": decision}, ANALYST))


# ─── Tier 1: state progression ───────────────────────────────────────────────

def verified_survey_hospital(measure_codes=None, raw_values=None, source_programs=None,
                             started=800, completed=600, discharges=1000,
                             validation_method="SOURCE_DOCUMENT", methodology_id=None,
                             hospital_overrides=None, verification="ACCEPT"):
    """Register a hospital, pin a methodology, and walk its survey to verification.

    Returns an NS with hospital, version, survey, measures, and the hospital's
    current version after the verification.
    """
    set_clock(CLOCK_2026_06_01)
    codes = measure_codes or ["o1"]
    values = raw_values or {code: 70.0 for code in codes}
    programs = source_programs or {code: "CMS_HOSPITAL_COMPARE" for code in codes}

    if methodology_id is None:
        version = publish_methodology(BASELINE_MEASURE_DEFINITIONS,
                                      label="Baseline Methodology")
        methodology_id = version["id"]
    hospital = register_hospital(**(hospital_overrides or {}))
    pin_methodology(hospital["id"], methodology_id)

    survey = open_survey(hospital["id"], started_survey_count=started,
                         completed_survey_count=completed,
                         entity_annual_discharges=discharges,
                         validation_method=validation_method)
    measures = []
    for code in codes:
        measures.append(record_measure(hospital["id"], survey["id"], code,
                                       values[code], programs.get(code)))

    submitted = submit_survey(hospital["id"], survey["id"])
    verified = verify_survey(survey["id"], verification)
    return NS(hospital=hospital, methodology_version_id=methodology_id,
              survey=verified, submitted=submitted, measures=measures,
              hospital_version=current_hospital_version(hospital["id"]))


def scored_hospital(raw_value=60.0, measure_code="o1", methodology_definitions=None,
                    methodology_label="Baseline Methodology", cycle_label="Baseline Grades",
                    publication_date="2026-07-15T00:00:00Z",
                    correction_window_ends_at=WINDOW_END, review_open=False,
                    cycle_published=False):
    """A hospital scored in a cycle, ready for review-stage tests.

    Returns an NS carrying the hospital, methodology version, cycle, run, grade
    and the hospital's version after scoring.
    """
    set_clock(CLOCK_2026_06_01)
    definitions = methodology_definitions or BASELINE_MEASURE_DEFINITIONS
    version = publish_methodology(definitions, label=methodology_label)
    hospital = register_hospital()
    pin_methodology(hospital["id"], version["id"])

    survey = open_survey(hospital["id"])
    record_measure(hospital["id"], survey["id"], measure_code, raw_value)
    submit_survey(hospital["id"], survey["id"])
    verify_survey(survey["id"], "ACCEPT")

    measure_set = refresh_measures(hospital["id"], current_hospital_version(hospital["id"]))
    cycle = create_cycle(version["id"], label=cycle_label,
                         preliminary_release_date=CLOCK_2026_06_01,
                         correction_window_ends_at=correction_window_ends_at,
                         publication_date=publication_date)
    run = cut_score_run(hospital["id"], version["id"], cycle["id"])
    hospital_now = _ok("read hospital", api_client.get_hospital(hospital["id"], READER))
    ctx = NS(hospital=hospital, methodology_version_id=version["id"],
             survey=survey, measure_set=measure_set, cycle=cycle, run=run,
             hospital_version=hospital_now["version"], review=None, grade=None)
    if review_open or cycle_published:
        cycle_now = open_cycle_review(cycle["id"])
        ctx.cycle = cycle_now
        ctx.review = get_review_for(hospital["id"], cycle["id"])
        ctx.grade = get_grade_for(hospital["id"], cycle["id"])
        hospital_now = _ok("read hospital", api_client.get_hospital(hospital["id"], READER))
        ctx.hospital_version = hospital_now["version"]
        if cycle_published:
            ctx.cycle = publish_cycle(cycle["id"])
    return ctx


def open_review_cycle(raw_value=60.0, challenged_measure_codes=None, measure_codes=None):
    """A cycle in OPEN_REVIEW with one hospital's review, ready for corrections."""
    set_clock(CLOCK_2026_06_01)
    definitions = BASELINE_MEASURE_DEFINITIONS
    version = publish_methodology(definitions, label="Baseline Methodology")
    hospital = register_hospital()
    pin_methodology(hospital["id"], version["id"])

    survey = open_survey(hospital["id"])
    # PRD §3.5 refuses a run whose pinned version omits any of the five domains,
    # so a scorable fixture reports one measure per domain by default.
    codes = measure_codes or [d["measure_code"] for d in definitions]
    for code in codes:
        record_measure(hospital["id"], survey["id"], code, raw_value)
    submit_survey(hospital["id"], survey["id"])
    verify_survey(survey["id"], "ACCEPT")

    measure_set = refresh_measures(hospital["id"], current_hospital_version(hospital["id"]))
    cycle = create_cycle(version["id"], label="Baseline Grades")
    run = cut_score_run(hospital["id"], version["id"], cycle["id"])

    cycle_now = open_cycle_review(cycle["id"])
    grade = get_grade_for(hospital["id"], cycle["id"])

    review = _ok("open preliminary result", api_client.create_preliminary_result(
        hospital["id"],
        create_preliminary_result_payload(grade["id"], challenged_measure_codes),
        ANALYST), 201)
    # Read the hospital's version *after* every mutation above: the value the
    # caller hands back as `expected_hospital_version` must equal the hospital's
    # version at the time of the next write (PRD §2.7), not at some earlier point.
    return NS(hospital=hospital, methodology_version_id=version["id"], survey=survey,
              measure_set=measure_set, cycle=cycle_now, run=run, grade=grade,
              review=review, hospital_version=current_hospital_version(hospital["id"]))


def open_review_cycle_with_review(challenged_measure_codes, raw_value=60.0, measure_codes=None):
    """A cycle in OPEN_REVIEW with an explicitly-challenged review for one hospital."""
    ctx = open_review_cycle(raw_value=raw_value, measure_codes=measure_codes)
    if challenged_measure_codes is not None:
        ctx.review = _ok("open preliminary result", api_client.create_preliminary_result(
            ctx.hospital["id"],
            create_preliminary_result_payload(ctx.grade["id"], challenged_measure_codes),
            ANALYST), 201)
        ctx.hospital_version = current_hospital_version(ctx.hospital["id"])
    return ctx


# ─── Tier 4: accumulation / threshold targeting ──────────────────────────────

def reference_methodology_hospital():
    """The seven-measure reference hospital, survey VERIFIED, set refreshed.

    Returns an NS with hospital, methodology_version_id, survey, measure_set and
    the hospital's version after the refresh.
    """
    set_clock(CLOCK_2026_06_01)
    version = publish_methodology(REFERENCE_MEASURE_DEFINITIONS, label="Main Methodology")
    hospital = register_hospital(name="P1 Regional Medical Center")
    pin_methodology(hospital["id"], version["id"])

    survey = open_survey(hospital["id"])
    for code, raw in REFERENCE_RAW_VALUES.items():
        record_measure(hospital["id"], survey["id"], code, raw,
                       REFERENCE_SOURCE_PROGRAMS[code])
    submit_survey(hospital["id"], survey["id"])
    verify_survey(survey["id"], "ACCEPT")

    measure_set = refresh_measures(hospital["id"], current_hospital_version(hospital["id"]))
    return NS(hospital=hospital, methodology_version_id=version["id"], survey=survey,
              measure_set=measure_set,
              hospital_version=current_hospital_version(hospital["id"]))


def reliability_survey_hospital(started=800, completed=600, discharges=1000,
                                methodology_definitions=None, raw_value=95.0,
                                verification="ACCEPT"):
    """A hospital whose survey has run through verification.

    The raw submitted counts drive the sample rate and the respondent scale, so
    the resulting reliability weight is whatever the pinned rule yields for them.
    ``verification`` may be left at ``DISCREPANCY_REQUEST`` for fixtures that
    only need the certification state to have been assigned.
    """
    set_clock(CLOCK_2026_06_01)
    definitions = methodology_definitions or FIVE_DOMAIN_MEASURE_DEFINITIONS
    version = publish_methodology(definitions, label="Measure-Grade Methodology")
    hospital = register_hospital(annual_discharges=1000)
    pin_methodology(hospital["id"], version["id"])

    # PRD §3.3 refuses a submission whose `completed_survey_count` exceeds its
    # `started_survey_count`, so callers must pass counts that satisfy that rule.
    survey = open_survey(hospital["id"], started_survey_count=started,
                         completed_survey_count=completed,
                         entity_annual_discharges=discharges)
    for definition in definitions:
        record_measure(hospital["id"], survey["id"], definition["measure_code"], raw_value)
    submit_survey(hospital["id"], survey["id"])
    verified = verify_survey(survey["id"], verification)
    if verification != "ACCEPT":
        return NS(hospital=hospital, methodology_version_id=version["id"], survey=verified,
                  measure_set=None, hospital_version=current_hospital_version(hospital["id"]))
    measure_set = refresh_measures(hospital["id"])
    return NS(hospital=hospital, methodology_version_id=version["id"], survey=verified,
              measure_set=measure_set,
              hospital_version=current_hospital_version(hospital["id"]))


def hospital_with_cycle_and_reanalysis(reference=True, requested_delta=None,
                                       subset_selector=None, document_count=6,
                                       raw_value=60.0, cycle_publication_date="2026-07-15T00:00:00Z"):
    """A scored hospital with a reanalysis request left UNDER_REVIEW.

    Returns an NS carrying the hospital, its survey, its cycle, run, grade and
    the under-review request.
    """
    if reference:
        base = reference_methodology_hospital()
        definitions_by_id = base.methodology_version_id
        cycle = create_cycle(definitions_by_id, label="Main Methodology Grades",
                             publication_date=cycle_publication_date)
        run = cut_score_run(base.hospital["id"], definitions_by_id, cycle["id"],
                            base.hospital_version)
        selector = subset_selector or [{"measure_code": "cpoe_order_entry_value"}]
    else:
        ctx = scored_hospital(raw_value=raw_value)
        definitions_by_id = ctx.methodology_version_id
        cycle = ctx.cycle
        run = ctx.run
        base = ctx
        selector = subset_selector or [{"measure_code": "o1"}]

    request = raise_reanalysis(base.hospital["id"], base.survey["id"], selector,
                               document_count=document_count, requested_delta=requested_delta)
    decide_reanalysis(base.hospital["id"], request["id"], "START_REVIEW")
    hospital_now = _ok("read hospital", api_client.get_hospital(base.hospital["id"], READER))
    return NS(hospital=base.hospital, survey=base.survey, measure_set=base.measure_set,
              methodology_version_id=definitions_by_id, cycle=cycle, run=run,
              request=request, hospital_version=hospital_now["version"])


def verified_survey_with_pending_reanalysis(document_count=6, subset_selector=None):
    """A VERIFIED survey whose reanalysis request sits UNDER_REVIEW."""
    set_clock(CLOCK_2026_06_01)
    version = publish_methodology(BASELINE_MEASURE_DEFINITIONS, label="Baseline Methodology")
    hospital = register_hospital()
    pin_methodology(hospital["id"], version["id"])
    survey = open_survey(hospital["id"])
    record_measure(hospital["id"], survey["id"], "o1", 70.0)
    submit_survey(hospital["id"], survey["id"])
    verified = verify_survey(survey["id"], "ACCEPT")
    request = raise_reanalysis(hospital["id"], survey["id"],
                               subset_selector or [{"measure_code": "o1"}],
                               document_count=document_count)
    decide_reanalysis(hospital["id"], request["id"], "START_REVIEW")
    hospital_now = _ok("read hospital", api_client.get_hospital(hospital["id"], READER))
    return NS(hospital=hospital, methodology_version_id=version["id"], survey=verified,
              request=request, hospital_version=hospital_now["version"])


# ─── Tier 5: finalization / publication ──────────────────────────────────────

def published_cycle_with_grades(grades_spec=None, methodology_definitions=None,
                                minimum_acceptable_letter="C", employer_network=None):
    """Publish a cycle over several hospitals and register an employer over them.

    ``grades_spec`` is a list of raw measure values, one per hospital.
    """
    set_clock(CLOCK_2026_06_01)
    definitions = methodology_definitions or BASELINE_MEASURE_DEFINITIONS
    version = publish_methodology(definitions, label="Baseline Methodology")
    cycle = create_cycle(version["id"], label="Baseline Grades")

    hospitals = []
    values = grades_spec if grades_spec is not None else [80.0, 5.0]
    for raw in values:
        hospital = register_hospital()
        pin_methodology(hospital["id"], version["id"])
        survey = open_survey(hospital["id"])
        for definition in definitions:
            record_measure(hospital["id"], survey["id"], definition["measure_code"], raw)
        submit_survey(hospital["id"], survey["id"])
        verified = verify_survey(survey["id"], "ACCEPT")
        measure_set = refresh_measures(hospital["id"], current_hospital_version(hospital["id"]))
        cut_score_run(hospital["id"], version["id"], cycle["id"])
        hospitals.append(hospital)

    open_cycle_review(cycle["id"])
    # PRD §2.9: publication is evaluated at or after the cycle's
    # `publication_date`, so the clock is moved onto that instant first.
    set_clock(CLOCK_2026_07_15)
    cycle_now = publish_cycle(cycle["id"])
    network = employer_network if employer_network is not None else \
        [h["id"] for h in hospitals]
    employer = register_employer(network, minimum_acceptable_letter=minimum_acceptable_letter)
    return NS(methodology_version_id=version["id"], cycle=cycle_now,
              hospitals=hospitals, employer=employer)


def employer_with_mixed_graded_network(extra_ungraded=2):
    """Employer over two graded hospitals and some ungraded ones."""
    ctx = published_cycle_with_grades(grades_spec=[80.0, 5.0])
    ungraded = [register_hospital()["id"] for _ in range(extra_ungraded)]
    network = [h["id"] for h in ctx.hospitals] + ungraded
    listing = set_network(ctx.employer["id"], network, minimum_acceptable_letter="C")
    return NS(methodology_version_id=ctx.methodology_version_id, cycle=ctx.cycle,
              hospitals=ctx.hospitals, ungraded=ungraded, employer=listing)


def relist_employer(employer_id, network_hospital_ids, **overrides):
    """Set an employer's network with the employer's own identity."""
    return _ok("set network listing", api_client.set_network_listing(
        employer_id, set_network_listing_payload(network_hospital_ids, **overrides),
        make_purchaser_headers(employer_id)))


__all__ = [name for name in dir() if not name.startswith("_")]