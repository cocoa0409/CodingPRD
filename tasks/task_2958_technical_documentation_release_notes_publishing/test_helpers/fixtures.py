"""Fixture builders that drive the API into every precondition state the suite needs.

Every builder reaches its target state through PRD-declared endpoints only —
the harness restarts the server before each test, so each builder starts from
an empty database and a logical clock reading its startup default of
``2026-08-01T00:00:00Z``.

Identity threading matters here: a ``Writer``'s ``X-User-ID`` is the id of the
``Writer`` row and a ``Reviewer``'s is the id of the ``Reviewer`` row (§2.1), so
every ownership-gated call below builds its headers from the entity it just
created rather than from a shared constant.

Locale profiles are deliberately registered *after* a documentation set has
published wherever a builder wants a clean single-job pipeline, because
publication auto-seeds a translation job for every ``ACTIVE`` locale whose
``publication_mode`` is ``SIMULTANEOUS`` (§3.6).
"""
from __future__ import annotations

from typing import Any, Optional, Sequence

from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .assertions import shift_date
from .constants import TEST_DEFAULTS
from .factories import (
    advance_release_train_payload,
    archive_doc_set_version_payload,
    assign_plan_item_payload,
    cancel_localization_job_payload,
    cancel_plan_item_payload,
    create_change_record_payload,
    create_clock_payload,
    create_deprecation_notice_payload,
    create_doc_set_version_payload,
    create_feedback_payload,
    create_locale_profile_payload,
    create_localization_job_payload,
    create_plan_item_payload,
    create_release_note_payload,
    create_release_train_payload,
    create_revision_payload,
    create_reviewer_payload,
    create_terminology_term_payload,
    create_topic_payload,
    create_writer_payload,
    decide_signoff_payload,
    deliver_localization_job_payload,
    editorial_pass_payload,
    exclude_change_record_payload,
    request_signoff_payload,
    unique_suffix,
)
from .test_users import (
    DOCS_LEAD_ALT_USER_ID,
    make_docs_lead_headers,
    make_localization_coordinator_headers,
    make_reader_headers,
    make_reviewer_headers,
    make_writer_headers,
)

DEFAULT_CLOCK = TEST_DEFAULTS["clock_default"]
DEFAULT_CLOCK_DATE = TEST_DEFAULTS["clock_default_date"]

_DOCS_LEAD = make_docs_lead_headers()
_LOC_COORD = make_localization_coordinator_headers()
_READER = make_reader_headers()


# ===========================================================================
# Tier 0 — single-call primitives
# ===========================================================================


def set_clock(current_utc: str, headers: Optional[dict[str, str]] = None) -> dict[str, Any]:
    """Move the logical clock forward to ``current_utc`` (§2.4)."""
    return get_success_data(
        api_client.set_clock(create_clock_payload(current_utc), headers or _DOCS_LEAD)
    )


def set_clock_date(day: str, headers: Optional[dict[str, str]] = None) -> dict[str, Any]:
    """Move the logical clock to midnight UTC on the given calendar day."""
    return set_clock(f"{day}T00:00:00Z", headers)


def create_release_train(**overrides: Any) -> dict[str, Any]:
    return get_success_data(
        api_client.create_release_train(create_release_train_payload(**overrides), _DOCS_LEAD),
        expected_status=201,
    )


def read_release_train(train_id: str) -> dict[str, Any]:
    return get_success_data(api_client.get_release_train(train_id, _DOCS_LEAD))


def create_writer(**overrides: Any) -> dict[str, Any]:
    return get_success_data(
        api_client.create_writer(create_writer_payload(**overrides), _DOCS_LEAD),
        expected_status=201,
    )


def read_writer(writer_id: str) -> dict[str, Any]:
    return get_success_data(api_client.get_writer(writer_id, _DOCS_LEAD))


def create_reviewer(**overrides: Any) -> dict[str, Any]:
    return get_success_data(
        api_client.create_reviewer(create_reviewer_payload(**overrides), _DOCS_LEAD),
        expected_status=201,
    )


def read_reviewer(reviewer_id: str) -> dict[str, Any]:
    return get_success_data(api_client.get_reviewer(reviewer_id, _DOCS_LEAD))


def create_plan_item(release_train_id: str, **overrides: Any) -> dict[str, Any]:
    return get_success_data(
        api_client.create_plan_item(
            create_plan_item_payload(release_train_id, **overrides), _DOCS_LEAD
        ),
        expected_status=201,
    )


def read_plan_item(plan_item_id: str) -> dict[str, Any]:
    return get_success_data(api_client.get_plan_item(plan_item_id, _DOCS_LEAD))


def assign_plan_item(plan_item_id: str, writer_id: str, **overrides: Any) -> dict[str, Any]:
    return get_success_data(
        api_client.assign_plan_item(
            plan_item_id, assign_plan_item_payload(writer_id, **overrides), _DOCS_LEAD
        )
    )


def cancel_plan_item(plan_item_id: str, **overrides: Any) -> dict[str, Any]:
    return get_success_data(
        api_client.cancel_plan_item(plan_item_id, cancel_plan_item_payload(**overrides), _DOCS_LEAD)
    )


def create_topic(plan_item_id: str, writer_id: str, **overrides: Any) -> dict[str, Any]:
    """Only the plan item's assigned writer may create its topics (§3.3)."""
    return get_success_data(
        api_client.create_topic(
            create_topic_payload(plan_item_id, **overrides), make_writer_headers(writer_id)
        ),
        expected_status=201,
    )


def read_topic(topic_id: str) -> dict[str, Any]:
    return get_success_data(api_client.get_topic(topic_id, _DOCS_LEAD))


def create_revision(topic_id: str, writer_id: str, **overrides: Any) -> dict[str, Any]:
    return get_success_data(
        api_client.create_revision(
            topic_id, create_revision_payload(**overrides), make_writer_headers(writer_id)
        ),
        expected_status=201,
    )


def submit_topic(topic_id: str, writer_id: str) -> dict[str, Any]:
    return get_success_data(
        api_client.submit_topic_for_review(topic_id, {}, make_writer_headers(writer_id))
    )


def request_signoff(topic_id: str, reviewer_id: str, **overrides: Any) -> dict[str, Any]:
    return get_success_data(
        api_client.request_signoff(
            topic_id, request_signoff_payload(reviewer_id, **overrides), _DOCS_LEAD
        ),
        expected_status=201,
    )


def decide_signoff(
    signoff_id: str, reviewer_id: str, decision: str, **overrides: Any
) -> dict[str, Any]:
    return get_success_data(
        api_client.decide_signoff(
            signoff_id,
            decide_signoff_payload(decision, **overrides),
            make_reviewer_headers(reviewer_id),
        )
    )


def create_terminology_term(**overrides: Any) -> dict[str, Any]:
    return get_success_data(
        api_client.create_terminology_term(
            create_terminology_term_payload(**overrides), _DOCS_LEAD
        ),
        expected_status=201,
    )


def retire_terminology_term(term_id: str) -> dict[str, Any]:
    return get_success_data(api_client.retire_terminology_term(term_id, {}, _DOCS_LEAD))


def create_locale_profile(**overrides: Any) -> dict[str, Any]:
    return get_success_data(
        api_client.create_locale_profile(create_locale_profile_payload(**overrides), _LOC_COORD),
        expected_status=201,
    )


def read_locale_profile(locale_id: str) -> dict[str, Any]:
    return get_success_data(api_client.get_locale_profile(locale_id, _LOC_COORD))


def read_localization_job(job_id: str) -> dict[str, Any]:
    return get_success_data(api_client.get_localization_job(job_id, _LOC_COORD))


def create_doc_set_version(
    release_train_id: str, expected_version: Optional[int] = None, **overrides: Any
) -> dict[str, Any]:
    """Open a draft documentation set, reading the train's live ``version`` when the
    caller does not pin one (§2.6)."""
    if expected_version is None:
        expected_version = read_release_train(release_train_id)["version"]
    return get_success_data(
        api_client.create_doc_set_version(
            create_doc_set_version_payload(release_train_id, expected_version, **overrides),
            _DOCS_LEAD,
        ),
        expected_status=201,
    )


def read_doc_set_version(doc_set_id: str) -> dict[str, Any]:
    return get_success_data(api_client.get_doc_set_version(doc_set_id, _DOCS_LEAD))


def publish_doc_set_version(doc_set_id: str) -> dict[str, Any]:
    return get_success_data(api_client.publish_doc_set_version(doc_set_id, {}, _DOCS_LEAD))


def archive_doc_set_version(doc_set_id: str, **overrides: Any) -> dict[str, Any]:
    return get_success_data(
        api_client.archive_doc_set_version(
            doc_set_id, archive_doc_set_version_payload(**overrides), _DOCS_LEAD
        )
    )


def create_change_record(release_train_id: str, **overrides: Any) -> dict[str, Any]:
    return get_success_data(
        api_client.create_change_record(
            create_change_record_payload(release_train_id, **overrides), _DOCS_LEAD
        ),
        expected_status=201,
    )


def read_change_record(record_id: str) -> dict[str, Any]:
    return get_success_data(api_client.get_change_record(record_id, _DOCS_LEAD))


def editorial_pass(record_id: str, **overrides: Any) -> dict[str, Any]:
    """An editor other than the submitter rewrites the record (§3.7), so this uses
    the alternate ``DocsLead`` identity."""
    return get_success_data(
        api_client.editorial_pass(
            record_id,
            editorial_pass_payload(**overrides),
            make_docs_lead_headers(DOCS_LEAD_ALT_USER_ID),
        )
    )


def exclude_change_record(record_id: str, **overrides: Any) -> dict[str, Any]:
    return get_success_data(
        api_client.exclude_change_record(
            record_id, exclude_change_record_payload(**overrides), _DOCS_LEAD
        )
    )


def create_release_note(
    doc_set_version_id: str, expected_version: Optional[int] = None, **overrides: Any
) -> dict[str, Any]:
    if expected_version is None:
        expected_version = read_doc_set_version(doc_set_version_id)["version"]
    return get_success_data(
        api_client.create_release_note(
            create_release_note_payload(doc_set_version_id, expected_version, **overrides),
            _DOCS_LEAD,
        ),
        expected_status=201,
    )


def read_release_note(note_id: str) -> dict[str, Any]:
    return get_success_data(api_client.get_release_note(note_id, _DOCS_LEAD))


def publish_release_note(note_id: str) -> dict[str, Any]:
    return get_success_data(api_client.publish_release_note(note_id, {}, _DOCS_LEAD))


def create_localization_job(
    topic_id: str, locale_profile_id: str, **overrides: Any
) -> dict[str, Any]:
    return get_success_data(
        api_client.create_localization_job(
            create_localization_job_payload(topic_id, locale_profile_id, **overrides), _LOC_COORD
        ),
        expected_status=201,
    )


def deliver_localization_job(job_id: str, **overrides: Any) -> dict[str, Any]:
    return get_success_data(
        api_client.deliver_localization_job(
            job_id, deliver_localization_job_payload(**overrides), _LOC_COORD
        )
    )


def rework_localization_job(job_id: str) -> dict[str, Any]:
    return get_success_data(api_client.rework_localization_job(job_id, {}, _LOC_COORD))


def publish_localization_job(job_id: str) -> dict[str, Any]:
    return get_success_data(api_client.publish_localization_job(job_id, {}, _LOC_COORD))


def cancel_localization_job(job_id: str, **overrides: Any) -> dict[str, Any]:
    return get_success_data(
        api_client.cancel_localization_job(
            job_id, cancel_localization_job_payload(**overrides), _LOC_COORD
        )
    )


def create_deprecation_notice(
    release_train_id: str, migration_guide_topic_id: str, **overrides: Any
) -> dict[str, Any]:
    return get_success_data(
        api_client.create_deprecation_notice(
            create_deprecation_notice_payload(
                release_train_id, migration_guide_topic_id, **overrides
            ),
            _DOCS_LEAD,
        ),
        expected_status=201,
    )


def read_deprecation_notice(notice_id: str) -> dict[str, Any]:
    return get_success_data(api_client.get_deprecation_notice(notice_id, _DOCS_LEAD))


def publish_deprecation_notice(notice_id: str) -> dict[str, Any]:
    return get_success_data(api_client.publish_deprecation_notice(notice_id, {}, _DOCS_LEAD))


def create_feedback(topic_id: str, locale_code: str, **overrides: Any) -> dict[str, Any]:
    return get_success_data(
        api_client.create_feedback(
            topic_id, create_feedback_payload(locale_code, **overrides), _READER
        ),
        expected_status=201,
    )


def advance_train(train_id: str, target_status: str) -> dict[str, Any]:
    return get_success_data(
        api_client.advance_release_train(
            train_id, advance_release_train_payload(target_status), _DOCS_LEAD
        )
    )


# ===========================================================================
# Tier 1 — entity-hierarchy bundles
#
# Each builder returns a mutable bundle dict so a consumer can keep drilling
# down.  ``**overrides`` always lands on the entity the builder is named after;
# ancestors take their overrides through the explicit ``*_overrides`` keywords.
# ===========================================================================


def _opts(value: Optional[dict[str, Any]]) -> dict[str, Any]:
    return dict(value or {})


def train_context(**overrides: Any) -> dict[str, Any]:
    """A registered release train, still ``PLANNED`` with an ``OPEN`` posture."""
    train = create_release_train(**overrides)
    return {"train": train, "train_id": train["id"]}


def roster_context(
    train_overrides: Optional[dict[str, Any]] = None, **overrides: Any
) -> dict[str, Any]:
    """A train plus one writer; ``**overrides`` configures the writer."""
    bundle = train_context(**_opts(train_overrides))
    writer = create_writer(**overrides)
    bundle.update(
        writer=writer,
        writer_id=writer["id"],
        writer_headers=make_writer_headers(writer["id"]),
    )
    return bundle


def plan_item_context(
    train_overrides: Optional[dict[str, Any]] = None,
    writer_overrides: Optional[dict[str, Any]] = None,
    **overrides: Any,
) -> dict[str, Any]:
    """A ``DRAFTED`` plan item on a train, with an unassigned writer standing by."""
    bundle = roster_context(train_overrides=train_overrides, **_opts(writer_overrides))
    plan_item = create_plan_item(bundle["train_id"], **overrides)
    bundle.update(plan_item=plan_item, plan_item_id=plan_item["id"])
    bundle["train"] = read_release_train(bundle["train_id"])
    return bundle


def assigned_plan_item_context(
    train_overrides: Optional[dict[str, Any]] = None,
    writer_overrides: Optional[dict[str, Any]] = None,
    plan_item_overrides: Optional[dict[str, Any]] = None,
    **overrides: Any,
) -> dict[str, Any]:
    """A plan item moved ``DRAFTED -> ASSIGNED``; ``**overrides`` configures the
    assignment body (``window_start_date``, ``window_end_date``)."""
    bundle = plan_item_context(
        train_overrides=train_overrides,
        writer_overrides=writer_overrides,
        **_opts(plan_item_overrides),
    )
    bundle["plan_item"] = assign_plan_item(
        bundle["plan_item_id"], bundle["writer_id"], **overrides
    )
    bundle["writer"] = read_writer(bundle["writer_id"])
    bundle["train"] = read_release_train(bundle["train_id"])
    return bundle


def topic_context(
    train_overrides: Optional[dict[str, Any]] = None,
    writer_overrides: Optional[dict[str, Any]] = None,
    plan_item_overrides: Optional[dict[str, Any]] = None,
    assign_overrides: Optional[dict[str, Any]] = None,
    **overrides: Any,
) -> dict[str, Any]:
    """A topic authored by the assigned writer; creating the first topic under a
    plan item moves that item ``ASSIGNED -> IN_AUTHORING`` (§3.3)."""
    bundle = assigned_plan_item_context(
        train_overrides=train_overrides,
        writer_overrides=writer_overrides,
        plan_item_overrides=plan_item_overrides,
        **_opts(assign_overrides),
    )
    topic = create_topic(bundle["plan_item_id"], bundle["writer_id"], **overrides)
    bundle.update(topic=topic, topic_id=topic["id"])
    bundle["plan_item"] = read_plan_item(bundle["plan_item_id"])
    return bundle


def revised_topic_context(
    revision_count: int = 1, **kwargs: Any
) -> dict[str, Any]:
    """A topic carrying ``revision_count`` source revisions.

    ``revision_overrides`` configures every appended revision; the remaining
    keywords are forwarded to :func:`topic_context`.
    """
    revision_overrides = _opts(kwargs.pop("revision_overrides", None))
    bundle = topic_context(**kwargs)
    revisions = []
    for _ in range(revision_count):
        revisions.append(
            create_revision(bundle["topic_id"], bundle["writer_id"], **revision_overrides)
        )
    bundle.update(revisions=revisions, revision=revisions[-1] if revisions else None)
    bundle["topic"] = read_topic(bundle["topic_id"])
    return bundle


def submitted_topic_context(**kwargs: Any) -> dict[str, Any]:
    """A topic in ``review_state`` ``PENDING_SIGNOFF`` with its plan item ``IN_REVIEW``."""
    bundle = revised_topic_context(**kwargs)
    bundle["topic"] = submit_topic(bundle["topic_id"], bundle["writer_id"])
    bundle["plan_item"] = read_plan_item(bundle["plan_item_id"])
    return bundle


def reviewer_pair(**overrides: Any) -> dict[str, Any]:
    """One ``ENGINEERING`` and one ``PRODUCT`` reviewer, the two disciplines a
    topic needs before it can reach ``FULLY_APPROVED`` (§3.5)."""
    engineering = create_reviewer(discipline="ENGINEERING", **overrides)
    product = create_reviewer(discipline="PRODUCT", **overrides)
    return {
        "engineering_reviewer": engineering,
        "engineering_reviewer_id": engineering["id"],
        "product_reviewer": product,
        "product_reviewer_id": product["id"],
    }


def pending_signoff_context(**kwargs: Any) -> dict[str, Any]:
    """A submitted topic holding one ``PENDING`` ``ENGINEERING`` sign-off."""
    bundle = submitted_topic_context(**kwargs)
    bundle.update(reviewer_pair())
    signoff = request_signoff(bundle["topic_id"], bundle["engineering_reviewer_id"])
    bundle.update(
        engineering_signoff=signoff,
        engineering_signoff_id=signoff["id"],
        signoff=signoff,
        signoff_id=signoff["id"],
    )
    return bundle


def fully_approved_topic_context(**kwargs: Any) -> dict[str, Any]:
    """A topic at ``review_state`` ``FULLY_APPROVED``: both disciplines approved and
    both pinned to the topic's current revision number (§3.5)."""
    bundle = pending_signoff_context(**kwargs)
    product_signoff = request_signoff(bundle["topic_id"], bundle["product_reviewer_id"])
    bundle.update(product_signoff=product_signoff, product_signoff_id=product_signoff["id"])
    bundle["engineering_signoff"] = decide_signoff(
        bundle["engineering_signoff_id"], bundle["engineering_reviewer_id"], "APPROVED"
    )
    bundle["product_signoff"] = decide_signoff(
        bundle["product_signoff_id"], bundle["product_reviewer_id"], "APPROVED"
    )
    bundle["topic"] = read_topic(bundle["topic_id"])
    bundle["plan_item"] = read_plan_item(bundle["plan_item_id"])
    bundle["train"] = read_release_train(bundle["train_id"])
    return bundle


def changes_requested_topic_context(**kwargs: Any) -> dict[str, Any]:
    """A topic at ``review_state`` ``CHANGES_REQUESTED`` after the four-hop cascade
    of §3.5, with its plan item in ``IN_REVISION``."""
    bundle = pending_signoff_context(**kwargs)
    product_signoff = request_signoff(bundle["topic_id"], bundle["product_reviewer_id"])
    bundle.update(product_signoff=product_signoff, product_signoff_id=product_signoff["id"])
    bundle["engineering_signoff"] = decide_signoff(
        bundle["engineering_signoff_id"], bundle["engineering_reviewer_id"], "CHANGES_REQUESTED"
    )
    bundle["topic"] = read_topic(bundle["topic_id"])
    bundle["plan_item"] = read_plan_item(bundle["plan_item_id"])
    bundle["train"] = read_release_train(bundle["train_id"])
    return bundle


# ===========================================================================
# Tier 2 — full-lifecycle shortcuts
# ===========================================================================


def draft_doc_set_context(**kwargs: Any) -> dict[str, Any]:
    """A fully approved topic plus an open ``DRAFT`` documentation set.

    ``doc_set_overrides`` configures the draft; remaining keywords flow down to
    :func:`fully_approved_topic_context`.
    """
    doc_set_overrides = _opts(kwargs.pop("doc_set_overrides", None))
    bundle = fully_approved_topic_context(**kwargs)
    doc_set = create_doc_set_version(bundle["train_id"], **doc_set_overrides)
    bundle.update(doc_set=doc_set, doc_set_id=doc_set["id"])
    bundle["train"] = read_release_train(bundle["train_id"])
    return bundle


def published_topic_context(
    locales: Optional[Sequence[dict[str, Any]]] = None, **kwargs: Any
) -> dict[str, Any]:
    """A topic taken live by a published documentation set.

    ``locales`` is a sequence of locale-profile override dicts registered
    *before* publication, so publication seeds one auto-created translation job
    per ``ACTIVE`` ``SIMULTANEOUS`` locale (§3.6).  Passing nothing leaves the
    translation pipeline empty, which is what most single-job builders want.
    """
    bundle = draft_doc_set_context(**kwargs)
    bundle["pre_publication_locales"] = [
        create_locale_profile(**overrides) for overrides in (locales or [])
    ]
    bundle["doc_set"] = publish_doc_set_version(bundle["doc_set_id"])
    bundle["topic"] = read_topic(bundle["topic_id"])
    bundle["plan_item"] = read_plan_item(bundle["plan_item_id"])
    bundle["writer"] = read_writer(bundle["writer_id"])
    bundle["train"] = read_release_train(bundle["train_id"])
    return bundle


def ga_train_context(**kwargs: Any) -> dict[str, Any]:
    """A train advanced to ``GA``, which the spine only permits once one of its
    documentation sets has reached ``PUBLISHED`` (§3.1)."""
    bundle = published_topic_context(**kwargs)
    advance_train(bundle["train_id"], "DOC_FREEZE")
    bundle["train"] = advance_train(bundle["train_id"], "GA")
    return bundle


def maintenance_train_context(**kwargs: Any) -> dict[str, Any]:
    """A train advanced all the way to ``MAINTENANCE``, whose posture is ``FROZEN``."""
    bundle = ga_train_context(**kwargs)
    bundle["train"] = advance_train(bundle["train_id"], "MAINTENANCE")
    return bundle


def localization_context(
    locale_overrides: Optional[dict[str, Any]] = None, **kwargs: Any
) -> dict[str, Any]:
    """A live topic plus one ``ACTIVE`` locale profile registered after publication,
    so the locale holds no auto-created job.

    ``**overrides`` configures the manual translation job's window.
    """
    job_overrides = {k: kwargs.pop(k) for k in list(kwargs) if k.startswith("window_")}
    bundle = published_topic_context(**kwargs)
    locale = create_locale_profile(**_opts(locale_overrides))
    bundle.update(locale=locale, locale_id=locale["id"], locale_code=locale["locale_code"])
    bundle["job_overrides"] = job_overrides
    return bundle


def queued_job_context(**kwargs: Any) -> dict[str, Any]:
    """A manual translation job in state ``QUEUED`` with a provisional quote."""
    bundle = localization_context(**kwargs)
    job = create_localization_job(
        bundle["topic_id"], bundle["locale_id"], **bundle["job_overrides"]
    )
    bundle.update(job=job, job_id=job["id"])
    bundle["locale"] = read_locale_profile(bundle["locale_id"])
    bundle["train"] = read_release_train(bundle["train_id"])
    return bundle


def translated_job_context(delivery_overrides: Optional[dict[str, Any]] = None, **kwargs: Any) -> dict[str, Any]:
    """A translation job delivered into state ``TRANSLATED`` with a final quote."""
    bundle = queued_job_context(**kwargs)
    bundle["job"] = deliver_localization_job(bundle["job_id"], **_opts(delivery_overrides))
    bundle["locale"] = read_locale_profile(bundle["locale_id"])
    bundle["train"] = read_release_train(bundle["train_id"])
    return bundle


def rework_requested_job_context(**kwargs: Any) -> dict[str, Any]:
    """A delivered translation bounced back to the vendor (``REWORK_REQUESTED``)."""
    bundle = translated_job_context(**kwargs)
    bundle["job"] = rework_localization_job(bundle["job_id"])
    return bundle


def scheduled_delayed_job_context(**kwargs: Any) -> dict[str, Any]:
    """A delivered job parked at ``SCHEDULED_DELAYED`` on a ``DELAYED`` locale, which
    keeps the locale's reservation in place (§3.8)."""
    locale_overrides = _opts(kwargs.pop("locale_overrides", None))
    locale_overrides.setdefault("publication_mode", "DELAYED")
    bundle = translated_job_context(locale_overrides=locale_overrides, **kwargs)
    bundle["job"] = publish_localization_job(bundle["job_id"])
    bundle["locale"] = read_locale_profile(bundle["locale_id"])
    return bundle


def published_localized_job_context(**kwargs: Any) -> dict[str, Any]:
    """A translation published on the simultaneous branch, which requires the train
    to be ``GA`` or ``MAINTENANCE`` (§3.8)."""
    bundle = translated_job_context(**kwargs)
    advance_train(bundle["train_id"], "DOC_FREEZE")
    bundle["train"] = advance_train(bundle["train_id"], "GA")
    bundle["job"] = publish_localization_job(bundle["job_id"])
    bundle["locale"] = read_locale_profile(bundle["locale_id"])
    bundle["train"] = read_release_train(bundle["train_id"])
    return bundle


def change_record_context(
    train_id: Optional[str] = None, **overrides: Any
) -> dict[str, Any]:
    """A change record in state ``SUBMITTED``; a fresh train is registered when the
    caller does not supply one."""
    bundle: dict[str, Any] = {}
    if train_id is None:
        bundle = train_context()
        train_id = bundle["train_id"]
    else:
        bundle = {"train_id": train_id, "train": read_release_train(train_id)}
    record = create_change_record(train_id, **overrides)
    bundle.update(change_record=record, change_record_id=record["id"])
    return bundle


def editorially_approved_change_record_context(
    train_id: Optional[str] = None,
    editorial_overrides: Optional[dict[str, Any]] = None,
    **overrides: Any,
) -> dict[str, Any]:
    """A change record moved to ``EDITORIALLY_APPROVED`` by a clean editorial pass —
    an editor whose id differs from the submitter's, with no blocker violations."""
    bundle = change_record_context(train_id, **overrides)
    bundle["change_record"] = editorial_pass(
        bundle["change_record_id"], **_opts(editorial_overrides)
    )
    return bundle


def rework_requested_change_record_context(
    blocker_term: Optional[str] = None,
    train_id: Optional[str] = None,
    **overrides: Any,
) -> dict[str, Any]:
    """A change record bounced to ``REWORK_REQUESTED`` by an editorial pass whose
    ``used_terms`` trip a ``BLOCKER`` term (§3.7)."""
    forbidden = blocker_term or f"forbidden-{unique_suffix()}"
    term = create_terminology_term(
        forbidden_forms=[forbidden], enforcement_severity="BLOCKER"
    )
    bundle = change_record_context(train_id, **overrides)
    bundle.update(blocker_term=term, blocker_term_id=term["id"], forbidden_form=forbidden)
    bundle["change_record"] = editorial_pass(
        bundle["change_record_id"], used_terms=[forbidden]
    )
    return bundle


def compiled_release_note_context(
    change_record_severities: Sequence[str] = ("MINOR",),
    documented: bool = True,
    **kwargs: Any,
) -> dict[str, Any]:
    """A ``COMPILED`` release note over a published documentation set.

    Each severity in ``change_record_severities`` produces one editorially
    approved change record.  With ``documented`` true every record's
    ``affected_component`` equals the bundle's plan item ``feature_key``, so the
    coverage factor is ``1.00``.
    """
    bundle = published_topic_context(**kwargs)
    feature_key = bundle["plan_item"]["feature_key"]
    records = []
    for severity in change_record_severities:
        record_overrides: dict[str, Any] = {"severity": severity}
        if documented:
            record_overrides["affected_component"] = feature_key
        record = create_change_record(bundle["train_id"], **record_overrides)
        records.append(editorial_pass(record["id"]))
    bundle.update(change_records=records, change_record_ids=[r["id"] for r in records])
    note = create_release_note(bundle["doc_set_id"])
    bundle.update(release_note=note, release_note_id=note["id"])
    bundle["doc_set"] = read_doc_set_version(bundle["doc_set_id"])
    return bundle


def published_release_note_context(**kwargs: Any) -> dict[str, Any]:
    """A release note published, which moves every included record to ``PUBLISHED``."""
    bundle = compiled_release_note_context(**kwargs)
    bundle["release_note"] = publish_release_note(bundle["release_note_id"])
    return bundle


def deprecation_notice_context(**kwargs: Any) -> dict[str, Any]:
    """A ``DRAFTED`` deprecation notice pointing at a live migration guide topic on
    the same product line.  ``**overrides`` (via ``notice_overrides``) configures
    the notice body."""
    notice_overrides = _opts(kwargs.pop("notice_overrides", None))
    bundle = published_topic_context(**kwargs)
    notice = create_deprecation_notice(
        bundle["train_id"], bundle["topic_id"], **notice_overrides
    )
    bundle.update(deprecation_notice=notice, deprecation_notice_id=notice["id"])
    return bundle


def published_deprecation_notice_context(**kwargs: Any) -> dict[str, Any]:
    """A ``PUBLISHED`` deprecation notice — the only thing that unblocks a release
    note carrying a ``BREAKING`` change (§3.7)."""
    bundle = deprecation_notice_context(**kwargs)
    bundle["deprecation_notice"] = publish_deprecation_notice(
        bundle["deprecation_notice_id"]
    )
    return bundle


def feedback_context(
    rows: Sequence[dict[str, Any]] = (),
    locale_overrides: Optional[dict[str, Any]] = None,
    **kwargs: Any,
) -> dict[str, Any]:
    """A live page with a locale profile registered and ``rows`` reader ratings left
    on it.  Each entry of ``rows`` is a feedback payload override dict."""
    bundle = published_topic_context(**kwargs)
    locale = create_locale_profile(**_opts(locale_overrides))
    bundle.update(locale=locale, locale_id=locale["id"], locale_code=locale["locale_code"])
    bundle["feedback"] = [
        create_feedback(bundle["topic_id"], locale["locale_code"], **overrides)
        for overrides in rows
    ]
    bundle["topic"] = read_topic(bundle["topic_id"])
    return bundle


# ===========================================================================
# Tier 3 — accumulation and threshold targeting
# ===========================================================================

#: Non-colliding authoring windows: each start sits three days past the previous
#: end, which clears the two-day leading-edge handoff buffer of §3.2.
_WINDOW_STRIDE_DAYS = 10
_WINDOW_LENGTH_DAYS = 7


def nth_authoring_window(index: int, base_date: str = TEST_DEFAULTS["window_start_date"]) -> dict[str, str]:
    """The ``index``-th authoring window in a collision-free series."""
    start = shift_date(base_date, index * _WINDOW_STRIDE_DAYS)
    return {
        "window_start_date": start,
        "window_end_date": shift_date(start, _WINDOW_LENGTH_DAYS),
    }


def multi_topic_train_context(
    topic_count: int = 2,
    approve_count: Optional[int] = None,
    plan_item_overrides: Optional[dict[str, Any]] = None,
    revision_overrides: Optional[dict[str, Any]] = None,
    **kwargs: Any,
) -> dict[str, Any]:
    """One train carrying ``topic_count`` plan items, each with a single topic.

    The first ``approve_count`` topics are driven all the way to
    ``FULLY_APPROVED`` (both disciplines pinned to the current revision), which
    also moves their plan items to ``APPROVED_CONTENT`` and lifts the train's
    ``approved_plan_item_count``.  All of this happens while the train is still
    ``PLANNED``, where the posture is unconditionally ``OPEN`` (§3.1).
    """
    if approve_count is None:
        approve_count = topic_count
    bundle = roster_context(**kwargs)
    bundle.update(reviewer_pair())
    plan_items: list[dict[str, Any]] = []
    topics: list[dict[str, Any]] = []
    for index in range(topic_count):
        plan_item = create_plan_item(bundle["train_id"], **_opts(plan_item_overrides))
        assign_plan_item(plan_item["id"], bundle["writer_id"], **nth_authoring_window(index))
        topic = create_topic(plan_item["id"], bundle["writer_id"])
        create_revision(topic["id"], bundle["writer_id"], **_opts(revision_overrides))
        if index < approve_count:
            submit_topic(topic["id"], bundle["writer_id"])
            eng = request_signoff(topic["id"], bundle["engineering_reviewer_id"])
            prod = request_signoff(topic["id"], bundle["product_reviewer_id"])
            decide_signoff(eng["id"], bundle["engineering_reviewer_id"], "APPROVED")
            decide_signoff(prod["id"], bundle["product_reviewer_id"], "APPROVED")
        plan_items.append(read_plan_item(plan_item["id"]))
        topics.append(read_topic(topic["id"]))
    bundle.update(
        plan_items=plan_items,
        plan_item_ids=[item["id"] for item in plan_items],
        topics=topics,
        topic_ids=[topic["id"] for topic in topics],
        writer=read_writer(bundle["writer_id"]),
        train=read_release_train(bundle["train_id"]),
    )
    return bundle


def train_at_ratio_context(
    total_plan_items: int, approved_plan_items: int, **kwargs: Any
) -> dict[str, Any]:
    """A train whose ``approved_topic_ratio`` is exactly
    ``approved_plan_items / total_plan_items``, for probing the posture bands."""
    return multi_topic_train_context(
        topic_count=total_plan_items, approve_count=approved_plan_items, **kwargs
    )


def published_topics_context(
    topic_count: int = 2,
    locales: Optional[Sequence[dict[str, Any]]] = None,
    **kwargs: Any,
) -> dict[str, Any]:
    """``topic_count`` topics taken live together by one documentation set.

    ``locales`` registers locale profiles before publication so the cascade
    seeds auto-created translation jobs (§3.6).
    """
    bundle = multi_topic_train_context(topic_count=topic_count, **kwargs)
    doc_set = create_doc_set_version(bundle["train_id"])
    bundle.update(doc_set=doc_set, doc_set_id=doc_set["id"])
    bundle["locale_profiles"] = [
        create_locale_profile(**overrides) for overrides in (locales or [])
    ]
    bundle["doc_set"] = publish_doc_set_version(doc_set["id"])
    bundle["topics"] = [read_topic(topic_id) for topic_id in bundle["topic_ids"]]
    bundle["plan_items"] = [read_plan_item(item_id) for item_id in bundle["plan_item_ids"]]
    bundle["writer"] = read_writer(bundle["writer_id"])
    bundle["train"] = read_release_train(bundle["train_id"])
    return bundle


def terminology_violation_context(
    blocker_forms: Sequence[str] = (),
    warning_forms: Sequence[str] = (),
    **kwargs: Any,
) -> dict[str, Any]:
    """A topic whose newest revision trips the named terminology violations.

    ``blocker_forms`` and ``warning_forms`` are forbidden wordings; one term is
    registered per entry, and a single revision submits all of them, so the
    topic's live counters land at exactly those two counts (§3.4).
    """
    revision_overrides = _opts(kwargs.pop("revision_overrides", None))
    blockers = [
        create_terminology_term(forbidden_forms=[form], enforcement_severity="BLOCKER")
        for form in blocker_forms
    ]
    warnings = [
        create_terminology_term(forbidden_forms=[form], enforcement_severity="WARNING")
        for form in warning_forms
    ]
    bundle = topic_context(**kwargs)
    revision_overrides["used_terms"] = list(blocker_forms) + list(warning_forms)
    revision = create_revision(bundle["topic_id"], bundle["writer_id"], **revision_overrides)
    bundle.update(
        blocker_terms=blockers,
        warning_terms=warnings,
        revision=revision,
        revisions=[revision],
        topic=read_topic(bundle["topic_id"]),
    )
    return bundle


def writer_at_capacity_context(**kwargs: Any) -> dict[str, Any]:
    """A writer whose ``committed_load_points`` exactly equals ``capacity_points``.

    Equality is accepted and only a strict excess is rejected (§3.2), so this is
    the state from which the very next assignment must fail.
    """
    plan_item_overrides = _opts(kwargs.pop("plan_item_overrides", None))
    bundle = roster_context(**kwargs)
    plan_item = create_plan_item(bundle["train_id"], **plan_item_overrides)
    bundle.update(plan_item=plan_item, plan_item_id=plan_item["id"])
    assign_plan_item(plan_item["id"], bundle["writer_id"], **nth_authoring_window(0))
    bundle["plan_item"] = read_plan_item(plan_item["id"])
    bundle["writer"] = read_writer(bundle["writer_id"])
    return bundle


def parallel_job_saturated_context(
    parallel_job_limit: int = 2,
    locale_overrides: Optional[dict[str, Any]] = None,
    window: Optional[dict[str, str]] = None,
    **kwargs: Any,
) -> dict[str, Any]:
    """A locale holding exactly ``parallel_job_limit`` open jobs whose closed windows
    all intersect, plus one spare live topic to aim the next request at.

    The locale is registered after publication so no auto-created job is in play;
    §3.8's ceiling then bites on the very next manual create.
    """
    job_window = dict(window or {
        "window_start_date": TEST_DEFAULTS["job_window_start_date"],
        "window_end_date": TEST_DEFAULTS["job_window_end_date"],
    })
    bundle = published_topics_context(topic_count=parallel_job_limit + 1, **kwargs)
    overrides = _opts(locale_overrides)
    overrides.setdefault("parallel_job_limit", parallel_job_limit)
    locale = create_locale_profile(**overrides)
    bundle.update(locale=locale, locale_id=locale["id"], locale_code=locale["locale_code"])
    jobs = [
        create_localization_job(topic_id, locale["id"], **job_window)
        for topic_id in bundle["topic_ids"][:parallel_job_limit]
    ]
    bundle.update(
        jobs=jobs,
        job_ids=[job["id"] for job in jobs],
        spare_topic_id=bundle["topic_ids"][parallel_job_limit],
        job_window=job_window,
    )
    bundle["locale"] = read_locale_profile(locale["id"])
    return bundle


# ===========================================================================
# Tier 4 — finalization and terminal states
# ===========================================================================


def cancelled_plan_item_context(**kwargs: Any) -> dict[str, Any]:
    """A plan item cancelled out of ``ASSIGNED``, which releases the writer's load
    points and decrements the train's ``plan_item_count`` (§3.2)."""
    cancel_overrides = _opts(kwargs.pop("cancel_overrides", None))
    bundle = assigned_plan_item_context(**kwargs)
    bundle["plan_item"] = cancel_plan_item(bundle["plan_item_id"], **cancel_overrides)
    bundle["writer"] = read_writer(bundle["writer_id"])
    bundle["train"] = read_release_train(bundle["train_id"])
    return bundle


def superseded_signoff_context(**kwargs: Any) -> dict[str, Any]:
    """A fully approved topic invalidated by a fresh source revision, which drives
    every sign-off to ``SUPERSEDED`` with its pin cleared (§3.3)."""
    bundle = fully_approved_topic_context(**kwargs)
    bundle["invalidating_revision"] = create_revision(
        bundle["topic_id"], bundle["writer_id"]
    )
    bundle["topic"] = read_topic(bundle["topic_id"])
    bundle["plan_item"] = read_plan_item(bundle["plan_item_id"])
    bundle["train"] = read_release_train(bundle["train_id"])
    return bundle


def superseded_draft_context(**kwargs: Any) -> dict[str, Any]:
    """Two successive drafts on one train, so the first is ``SUPERSEDED`` (§3.6)."""
    bundle = draft_doc_set_context(**kwargs)
    bundle["first_doc_set_id"] = bundle["doc_set_id"]
    second = create_doc_set_version(bundle["train_id"])
    bundle.update(second_doc_set=second, second_doc_set_id=second["id"])
    bundle["first_doc_set"] = read_doc_set_version(bundle["first_doc_set_id"])
    bundle["train"] = read_release_train(bundle["train_id"])
    return bundle


def superseded_release_note_context(**kwargs: Any) -> dict[str, Any]:
    """A second compilation on the same documentation set, which supersedes the
    first note while leaving its change records ``EDITORIALLY_APPROVED`` (§3.7)."""
    bundle = compiled_release_note_context(**kwargs)
    bundle["first_release_note_id"] = bundle["release_note_id"]
    second = create_release_note(bundle["doc_set_id"])
    bundle.update(second_release_note=second, second_release_note_id=second["id"])
    bundle["first_release_note"] = read_release_note(bundle["first_release_note_id"])
    bundle["doc_set"] = read_doc_set_version(bundle["doc_set_id"])
    return bundle


def excluded_change_record_context(**kwargs: Any) -> dict[str, Any]:
    """A change record dropped from customer communication for good (§3.7)."""
    exclusion_overrides = _opts(kwargs.pop("exclusion_overrides", None))
    bundle = change_record_context(**kwargs)
    bundle["change_record"] = exclude_change_record(
        bundle["change_record_id"], **exclusion_overrides
    )
    return bundle


def archived_doc_set_context(**kwargs: Any) -> dict[str, Any]:
    """A published documentation set archived through the five-hop cascade of §3.6."""
    archive_overrides = _opts(kwargs.pop("archive_overrides", None))
    bundle = published_topic_context(**kwargs)
    bundle["doc_set"] = archive_doc_set_version(bundle["doc_set_id"], **archive_overrides)
    bundle["topic"] = read_topic(bundle["topic_id"])
    bundle["train"] = read_release_train(bundle["train_id"])
    return bundle


def archived_doc_set_with_jobs_context(
    locales: Optional[Sequence[dict[str, Any]]] = None, **kwargs: Any
) -> dict[str, Any]:
    """A documentation set archived while auto-created translation jobs were open,
    so hops three through five of §3.6 actually have work to do."""
    archive_overrides = _opts(kwargs.pop("archive_overrides", None))
    locale_specs = list(locales) if locales is not None else [{}]
    bundle = published_topic_context(locales=locale_specs, **kwargs)
    bundle["locale_profiles"] = [
        read_locale_profile(locale["id"]) for locale in bundle["pre_publication_locales"]
    ]
    jobs, _meta = _list_jobs()
    bundle.update(jobs_before_archive=jobs, job_ids=[job["id"] for job in jobs])
    bundle["doc_set"] = archive_doc_set_version(bundle["doc_set_id"], **archive_overrides)
    bundle["topic"] = read_topic(bundle["topic_id"])
    bundle["train"] = read_release_train(bundle["train_id"])
    bundle["locale_profiles"] = [
        read_locale_profile(locale["id"]) for locale in bundle["pre_publication_locales"]
    ]
    return bundle


def _list_jobs() -> tuple[list[dict[str, Any]], dict[str, Any]]:
    response = api_client.list_localization_jobs(_LOC_COORD, {"limit": 100})
    body = response.json()
    return body["data"], body["meta"]


def end_of_life_train_context(**kwargs: Any) -> dict[str, Any]:
    """A train driven to ``END_OF_LIFE``, which requires the logical clock's date to
    have reached ``support_end_date`` (§3.1) and runs the deepest cascade.

    Auto-created translation jobs are seeded before publication by default so
    hops four and five of the cascade have jobs to cancel and ledgers to unwind.
    """
    locales = kwargs.pop("locales", [{}])
    bundle = published_topic_context(locales=locales, **kwargs)
    advance_train(bundle["train_id"], "DOC_FREEZE")
    advance_train(bundle["train_id"], "GA")
    advance_train(bundle["train_id"], "MAINTENANCE")
    support_end_date = bundle["train"]["support_end_date"]
    set_clock_date(support_end_date)
    jobs, _meta = _list_jobs()
    bundle["jobs_before_eol"] = jobs
    bundle["train"] = advance_train(bundle["train_id"], "END_OF_LIFE")
    bundle["topic"] = read_topic(bundle["topic_id"])
    bundle["doc_set"] = read_doc_set_version(bundle["doc_set_id"])
    bundle["locale_profiles"] = [
        read_locale_profile(locale["id"]) for locale in bundle["pre_publication_locales"]
    ]
    return bundle


_NOT_EXPORTED = {
    "annotations", "Any", "Optional", "Sequence",
    "get_success_data", "api_client", "shift_date", "TEST_DEFAULTS",
    "DOCS_LEAD_ALT_USER_ID",
}

__all__ = [
    name for name in dir()
    if not name.startswith("_") and name not in _NOT_EXPORTED
]
