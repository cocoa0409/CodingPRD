"""Typed API client — one method per endpoint of PRD §4."""
from __future__ import annotations

from typing import Any, Optional

import requests

from prd_bench_local_runner.testing import GenericApiClient


def canonical_instant(value: Optional[str]) -> Optional[str]:
    """Normalise an ISO-8601 UTC instant to exactly three fractional digits.

    §2.4 requires instants with "exactly three fractional-second digits and a
    trailing ``Z``".  Test comparisons route through here so that a server
    rendering ``...T00:00:00Z`` and one rendering ``...T00:00:00.000Z`` compare
    equal on the instant they denote rather than on their spelling.
    """
    if value is None:
        return None
    text = str(value).strip()
    if text.endswith("Z"):
        text = text[:-1]
    if "+" in text[10:]:
        text = text[: 10 + text[10:].index("+")]
    if "." in text:
        head, frac = text.split(".", 1)
        frac = (frac + "000")[:3]
    else:
        head, frac = text, "000"
    return f"{head}.{frac}Z"


def instants_equal(left: Optional[str], right: Optional[str]) -> bool:
    """True when two ISO-8601 instants denote the same moment."""
    return canonical_instant(left) == canonical_instant(right)


class ApiClient(GenericApiClient):
    """One method per endpoint in the PRD §4 routing table."""

    # -- Logical clock (§2.4) ------------------------------------------------

    def set_clock(self, payload: dict[str, Any], headers: dict[str, str]) -> requests.Response:
        return self._request("POST", "/_clock/set_current_utc", payload, headers)

    # -- Release trains (§3.1) ----------------------------------------------

    def create_release_train(self, payload: dict[str, Any], headers: dict[str, str]) -> requests.Response:
        return self._request("POST", "/release-trains", payload, headers)

    def get_release_train(self, train_id: str, headers: dict[str, str]) -> requests.Response:
        return self._request("GET", f"/release-trains/{train_id}", None, headers)

    def list_release_trains(
        self, headers: dict[str, str], params: Optional[dict[str, Any]] = None
    ) -> requests.Response:
        return self._request("GET", "/release-trains", params, headers)

    def advance_release_train(
        self, train_id: str, payload: dict[str, Any], headers: dict[str, str]
    ) -> requests.Response:
        return self._request("POST", f"/release-trains/{train_id}/advance", payload, headers)

    # -- Writers (§3.2) -----------------------------------------------------

    def create_writer(self, payload: dict[str, Any], headers: dict[str, str]) -> requests.Response:
        return self._request("POST", "/writers", payload, headers)

    def get_writer(self, writer_id: str, headers: dict[str, str]) -> requests.Response:
        return self._request("GET", f"/writers/{writer_id}", None, headers)

    def list_writers(
        self, headers: dict[str, str], params: Optional[dict[str, Any]] = None
    ) -> requests.Response:
        return self._request("GET", "/writers", params, headers)

    def list_writer_revisions(
        self, writer_id: str, headers: dict[str, str], params: Optional[dict[str, Any]] = None
    ) -> requests.Response:
        return self._request("GET", f"/writers/{writer_id}/revisions", params, headers)

    # -- Reviewers (§3.2) ---------------------------------------------------

    def create_reviewer(self, payload: dict[str, Any], headers: dict[str, str]) -> requests.Response:
        return self._request("POST", "/reviewers", payload, headers)

    def get_reviewer(self, reviewer_id: str, headers: dict[str, str]) -> requests.Response:
        return self._request("GET", f"/reviewers/{reviewer_id}", None, headers)

    def list_reviewers(
        self, headers: dict[str, str], params: Optional[dict[str, Any]] = None
    ) -> requests.Response:
        return self._request("GET", "/reviewers", params, headers)

    # -- Plan items (§3.2) --------------------------------------------------

    def create_plan_item(self, payload: dict[str, Any], headers: dict[str, str]) -> requests.Response:
        return self._request("POST", "/plan-items", payload, headers)

    def get_plan_item(self, plan_item_id: str, headers: dict[str, str]) -> requests.Response:
        return self._request("GET", f"/plan-items/{plan_item_id}", None, headers)

    def list_plan_items(
        self, headers: dict[str, str], params: Optional[dict[str, Any]] = None
    ) -> requests.Response:
        return self._request("GET", "/plan-items", params, headers)

    def assign_plan_item(
        self, plan_item_id: str, payload: dict[str, Any], headers: dict[str, str]
    ) -> requests.Response:
        return self._request("POST", f"/plan-items/{plan_item_id}/assign", payload, headers)

    def cancel_plan_item(
        self, plan_item_id: str, payload: dict[str, Any], headers: dict[str, str]
    ) -> requests.Response:
        return self._request("POST", f"/plan-items/{plan_item_id}/cancel", payload, headers)

    # -- Topics and revisions (§3.3) ---------------------------------------

    def create_topic(self, payload: dict[str, Any], headers: dict[str, str]) -> requests.Response:
        return self._request("POST", "/topics", payload, headers)

    def get_topic(self, topic_id: str, headers: dict[str, str]) -> requests.Response:
        return self._request("GET", f"/topics/{topic_id}", None, headers)

    def list_topics(
        self, headers: dict[str, str], params: Optional[dict[str, Any]] = None
    ) -> requests.Response:
        return self._request("GET", "/topics", params, headers)

    def create_revision(
        self, topic_id: str, payload: dict[str, Any], headers: dict[str, str]
    ) -> requests.Response:
        return self._request("POST", f"/topics/{topic_id}/revisions", payload, headers)

    def list_topic_revisions(
        self, topic_id: str, headers: dict[str, str], params: Optional[dict[str, Any]] = None
    ) -> requests.Response:
        return self._request("GET", f"/topics/{topic_id}/revisions", params, headers)

    def submit_topic_for_review(
        self, topic_id: str, payload: Optional[dict[str, Any]], headers: dict[str, str]
    ) -> requests.Response:
        return self._request("POST", f"/topics/{topic_id}/submit-review", payload or {}, headers)

    # -- Sign-offs (§3.5) ---------------------------------------------------

    def request_signoff(
        self, topic_id: str, payload: dict[str, Any], headers: dict[str, str]
    ) -> requests.Response:
        return self._request("POST", f"/topics/{topic_id}/sign-offs", payload, headers)

    def list_topic_signoffs(
        self, topic_id: str, headers: dict[str, str], params: Optional[dict[str, Any]] = None
    ) -> requests.Response:
        return self._request("GET", f"/topics/{topic_id}/sign-offs", params, headers)

    def get_signoff(self, signoff_id: str, headers: dict[str, str]) -> requests.Response:
        return self._request("GET", f"/sign-offs/{signoff_id}", None, headers)

    def list_signoffs(
        self, headers: dict[str, str], params: Optional[dict[str, Any]] = None
    ) -> requests.Response:
        return self._request("GET", "/sign-offs", params, headers)

    def decide_signoff(
        self, signoff_id: str, payload: dict[str, Any], headers: dict[str, str]
    ) -> requests.Response:
        return self._request("POST", f"/sign-offs/{signoff_id}/decide", payload, headers)

    # -- Reader feedback and deflection (§3.10) ----------------------------

    def create_feedback(
        self, topic_id: str, payload: dict[str, Any], headers: dict[str, str]
    ) -> requests.Response:
        return self._request("POST", f"/topics/{topic_id}/feedback", payload, headers)

    def list_topic_feedback(
        self, topic_id: str, headers: dict[str, str], params: Optional[dict[str, Any]] = None
    ) -> requests.Response:
        return self._request("GET", f"/topics/{topic_id}/feedback", params, headers)

    def get_deflection_summary(
        self, topic_id: str, headers: dict[str, str], params: Optional[dict[str, Any]] = None
    ) -> requests.Response:
        return self._request("GET", f"/topics/{topic_id}/deflection-summary", params, headers)

    # -- Doc set versions (§3.6) -------------------------------------------

    def create_doc_set_version(
        self, payload: dict[str, Any], headers: dict[str, str]
    ) -> requests.Response:
        return self._request("POST", "/doc-set-versions", payload, headers)

    def get_doc_set_version(self, doc_set_id: str, headers: dict[str, str]) -> requests.Response:
        return self._request("GET", f"/doc-set-versions/{doc_set_id}", None, headers)

    def list_doc_set_versions(
        self, headers: dict[str, str], params: Optional[dict[str, Any]] = None
    ) -> requests.Response:
        return self._request("GET", "/doc-set-versions", params, headers)

    def publish_doc_set_version(
        self, doc_set_id: str, payload: Optional[dict[str, Any]], headers: dict[str, str]
    ) -> requests.Response:
        return self._request("POST", f"/doc-set-versions/{doc_set_id}/publish", payload or {}, headers)

    def archive_doc_set_version(
        self, doc_set_id: str, payload: dict[str, Any], headers: dict[str, str]
    ) -> requests.Response:
        return self._request("POST", f"/doc-set-versions/{doc_set_id}/archive", payload, headers)

    # -- Change records (§3.7) ---------------------------------------------

    def create_change_record(
        self, payload: dict[str, Any], headers: dict[str, str]
    ) -> requests.Response:
        return self._request("POST", "/change-records", payload, headers)

    def get_change_record(self, record_id: str, headers: dict[str, str]) -> requests.Response:
        return self._request("GET", f"/change-records/{record_id}", None, headers)

    def list_change_records(
        self, headers: dict[str, str], params: Optional[dict[str, Any]] = None
    ) -> requests.Response:
        return self._request("GET", "/change-records", params, headers)

    def editorial_pass(
        self, record_id: str, payload: dict[str, Any], headers: dict[str, str]
    ) -> requests.Response:
        return self._request("POST", f"/change-records/{record_id}/editorial-pass", payload, headers)

    def exclude_change_record(
        self, record_id: str, payload: dict[str, Any], headers: dict[str, str]
    ) -> requests.Response:
        return self._request("POST", f"/change-records/{record_id}/exclude", payload, headers)

    # -- Release notes (§3.7) ----------------------------------------------

    def create_release_note(
        self, payload: dict[str, Any], headers: dict[str, str]
    ) -> requests.Response:
        return self._request("POST", "/release-notes", payload, headers)

    def get_release_note(self, note_id: str, headers: dict[str, str]) -> requests.Response:
        return self._request("GET", f"/release-notes/{note_id}", None, headers)

    def list_release_notes(
        self, headers: dict[str, str], params: Optional[dict[str, Any]] = None
    ) -> requests.Response:
        return self._request("GET", "/release-notes", params, headers)

    def publish_release_note(
        self, note_id: str, payload: Optional[dict[str, Any]], headers: dict[str, str]
    ) -> requests.Response:
        return self._request("POST", f"/release-notes/{note_id}/publish", payload or {}, headers)

    # -- Locale profiles (§3.8) --------------------------------------------

    def create_locale_profile(
        self, payload: dict[str, Any], headers: dict[str, str]
    ) -> requests.Response:
        return self._request("POST", "/locale-profiles", payload, headers)

    def get_locale_profile(self, locale_id: str, headers: dict[str, str]) -> requests.Response:
        return self._request("GET", f"/locale-profiles/{locale_id}", None, headers)

    def list_locale_profiles(
        self, headers: dict[str, str], params: Optional[dict[str, Any]] = None
    ) -> requests.Response:
        return self._request("GET", "/locale-profiles", params, headers)

    # -- Localization jobs (§3.8) ------------------------------------------

    def create_localization_job(
        self, payload: dict[str, Any], headers: dict[str, str]
    ) -> requests.Response:
        return self._request("POST", "/localization-jobs", payload, headers)

    def get_localization_job(self, job_id: str, headers: dict[str, str]) -> requests.Response:
        return self._request("GET", f"/localization-jobs/{job_id}", None, headers)

    def list_localization_jobs(
        self, headers: dict[str, str], params: Optional[dict[str, Any]] = None
    ) -> requests.Response:
        return self._request("GET", "/localization-jobs", params, headers)

    def deliver_localization_job(
        self, job_id: str, payload: dict[str, Any], headers: dict[str, str]
    ) -> requests.Response:
        return self._request("POST", f"/localization-jobs/{job_id}/deliver", payload, headers)

    def rework_localization_job(
        self, job_id: str, payload: Optional[dict[str, Any]], headers: dict[str, str]
    ) -> requests.Response:
        return self._request("POST", f"/localization-jobs/{job_id}/rework", payload or {}, headers)

    def publish_localization_job(
        self, job_id: str, payload: Optional[dict[str, Any]], headers: dict[str, str]
    ) -> requests.Response:
        return self._request("POST", f"/localization-jobs/{job_id}/publish", payload or {}, headers)

    def cancel_localization_job(
        self, job_id: str, payload: dict[str, Any], headers: dict[str, str]
    ) -> requests.Response:
        return self._request("POST", f"/localization-jobs/{job_id}/cancel", payload, headers)

    # -- Terminology terms (§3.4) ------------------------------------------

    def create_terminology_term(
        self, payload: dict[str, Any], headers: dict[str, str]
    ) -> requests.Response:
        return self._request("POST", "/terminology-terms", payload, headers)

    def get_terminology_term(self, term_id: str, headers: dict[str, str]) -> requests.Response:
        return self._request("GET", f"/terminology-terms/{term_id}", None, headers)

    def list_terminology_terms(
        self, headers: dict[str, str], params: Optional[dict[str, Any]] = None
    ) -> requests.Response:
        return self._request("GET", "/terminology-terms", params, headers)

    def retire_terminology_term(
        self, term_id: str, payload: Optional[dict[str, Any]], headers: dict[str, str]
    ) -> requests.Response:
        return self._request("POST", f"/terminology-terms/{term_id}/retire", payload or {}, headers)

    # -- Deprecation notices (§3.9) ----------------------------------------

    def create_deprecation_notice(
        self, payload: dict[str, Any], headers: dict[str, str]
    ) -> requests.Response:
        return self._request("POST", "/deprecation-notices", payload, headers)

    def get_deprecation_notice(self, notice_id: str, headers: dict[str, str]) -> requests.Response:
        return self._request("GET", f"/deprecation-notices/{notice_id}", None, headers)

    def list_deprecation_notices(
        self, headers: dict[str, str], params: Optional[dict[str, Any]] = None
    ) -> requests.Response:
        return self._request("GET", "/deprecation-notices", params, headers)

    def publish_deprecation_notice(
        self, notice_id: str, payload: Optional[dict[str, Any]], headers: dict[str, str]
    ) -> requests.Response:
        return self._request("POST", f"/deprecation-notices/{notice_id}/publish", payload or {}, headers)

    # -- Raw escape hatches -------------------------------------------------

    def raw_get(
        self, path: str, headers: dict[str, str], params: Optional[dict[str, Any]] = None
    ) -> requests.Response:
        return self._request("GET", path, params, headers)

    def raw_post(
        self, path: str, payload: Optional[dict[str, Any]], headers: dict[str, str]
    ) -> requests.Response:
        return self._request("POST", path, payload, headers)


#: Module-level shared client instance.
api_client = ApiClient()
