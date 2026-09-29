"""Numeric thresholds and default test values drawn from the PRD."""

# ---------------------------------------------------------------------------
# Thresholds, weights, and formula coefficients stated in the PRD
# ---------------------------------------------------------------------------

THRESHOLDS = {
    # --- §2.3 Pagination ---
    "limit_default": 10,
    "limit_min": 1,
    "limit_max": 100,
    "offset_default": 0,
    "offset_min": 0,

    # --- §2.4 Logical clock ---
    "clock_startup_default": "2026-08-01T00:00:00Z",

    # --- §3.1 Readiness posture bands ---
    "posture_open_ratio": 0.80,
    "posture_restricted_ratio": 0.50,
    "vacuous_approved_topic_ratio": 1.00,

    # --- §3.1 Release train field bounds ---
    "product_key_min_len": 2,
    "product_key_max_len": 12,
    "version_label_min_len": 1,
    "version_label_max_len": 20,

    # --- §3.2 Writer / reviewer field bounds ---
    "person_key_min_len": 3,
    "person_key_max_len": 40,
    "full_name_min_len": 1,
    "full_name_max_len": 120,

    # --- §3.2 Plan item field bounds ---
    "feature_key_min_len": 1,
    "feature_key_max_len": 60,
    "planned_page_count_min": 1,
    "planned_page_count_max": 500,
    "complexity_points_min": 0,
    "complexity_points_max": 100,

    # --- §3.2 Load point formula ---
    "size_points_per_page": 2,
    "depth_points_cap": 20,
    "ia_points": {"NEW_TOPIC": 4, "EXISTING_TOPIC_UPDATE": 1, "CONCEPT_HUB": 6},
    "audience_multiplier": {"CRITICAL": 1.5, "STANDARD": 1.0, "INTERNAL": 0.75},
    "seniority_divisor": {"PRINCIPAL": 1.25, "SENIOR": 1.0, "ASSOCIATE": 0.80},
    "load_points_floor": 3.0,
    "rework_load_points_per_unit": 1.0,

    # --- §3.2 Writer window collision ---
    "writer_window_handoff_buffer_days": 2,

    # --- §3.3 Topics / information architecture ---
    "slug_min_len": 3,
    "slug_max_len": 60,
    "title_min_len": 1,
    "title_max_len": 160,
    "ia_depth_root": 0,
    "ia_depth_max": 4,

    # --- §3.3 Source revisions ---
    "body_word_count_min": 1,
    "body_word_count_max": 200000,
    "used_terms_min_len": 0,
    "used_terms_max_len": 200,
    "used_term_min_len": 1,
    "used_term_max_len": 60,
    "summary_min_len": 1,
    "summary_max_len": 200,

    # --- §3.4 Terminology terms ---
    "term_min_len": 2,
    "term_max_len": 60,
    "preferred_form_min_len": 2,
    "preferred_form_max_len": 60,
    "forbidden_forms_min_len": 1,
    "forbidden_forms_max_len": 20,
    "forbidden_form_min_len": 2,
    "forbidden_form_max_len": 60,

    # --- §3.5 Review ---
    "comment_max_len": 500,
    "signoff_latency_grace_days": 3,

    # --- §3.6 Doc set versions ---
    "doc_set_version_label_min_len": 1,
    "doc_set_version_label_max_len": 40,
    "eol_notice_text_min_len": 10,
    "eol_notice_text_max_len": 300,
    "projection_memory_discount_pct": 70,

    # --- §3.7 Change records / release notes ---
    "internal_summary_min_len": 1,
    "internal_summary_max_len": 300,
    "customer_facing_text_min_len": 10,
    "customer_facing_text_max_len": 300,
    "exclusion_reason_min_len": 5,
    "exclusion_reason_max_len": 200,
    "affected_component_min_len": 1,
    "affected_component_max_len": 60,
    "severity_weights": {
        "BREAKING": 40,
        "SECURITY": 25,
        "MAJOR": 12,
        "MINOR": 4,
        "PATCH": 1,
    },
    "impact_score_cap": 100,

    # --- §3.8 Locale profiles ---
    "locale_code_len": 5,
    "tm_coverage_pct_min": 0,
    "tm_coverage_pct_max": 100,
    "sla_days_min": 1,
    "sla_days_max": 120,
    "parallel_job_limit_min": 1,
    "parallel_job_limit_max": 20,

    # --- §3.8 Quote formula ---
    "memory_discount_pct": 70,
    "rush_surcharge_pct": 15,
    "discount_band_10_min_cents": 500000,
    "discount_band_6_min_cents": 200000,
    "discount_band_3_min_cents": 50000,
    "discount_pct_band_10": 10,
    "discount_pct_band_6": 6,
    "discount_pct_band_3": 3,
    "discount_pct_band_0": 0,

    # --- §3.8 Delivery ---
    "translated_word_count_min": 1,
    "translated_word_count_max": 400000,
    "sla_grace_days": 3,
    "cancel_reason_min_len": 5,
    "cancel_reason_max_len": 200,

    # --- §3.9 Deprecation notices ---
    "min_notice_days": {"BREAKING": 180, "MAJOR": 90, "MINOR": 30},

    # --- §3.10 Reader feedback and deflection ---
    "rating_min": 1,
    "rating_max": 5,
    "session_key_min_len": 6,
    "session_key_max_len": 60,
    "feedback_comment_max_len": 500,
    "deflection_window_days": 30,

    # --- §3.10 Health score ---
    "health_score_max": 100,
    "health_score_min": 0,
    "churn_penalty_per_revision": 4,
    "churn_penalty_free_revisions": 2,
    "blocker_penalty_per_violation": 12,
    "warning_penalty_per_violation": 3,
    "latency_penalty_per_day": 2,
    "latency_penalty_grace_days": 3,
    "rating_penalty_per_point": 4,
    "rating_penalty_reference": 5,
    "deflection_penalty_per_pct": 0.06,
    "deflection_penalty_reference": 100,
}


# ---------------------------------------------------------------------------
# Reusable literal defaults for building valid payloads
# ---------------------------------------------------------------------------

TEST_DEFAULTS = {
    # Clock
    "clock_default": "2026-08-01T00:00:00Z",
    "clock_default_date": "2026-08-01",

    # Release train
    "product_key": "DOCSPLAT",
    "version_label": "2026.1",
    "doc_freeze_date": "2026-08-10",
    "ga_date": "2026-08-20",
    "support_end_date": "2027-08-20",
    "localization_budget_cap_cents": 100000000,

    # Writer / reviewer
    "writer_person_key": "writer-alpha",
    "writer_full_name": "Alex Writer",
    "seniority_tier": "SENIOR",
    "capacity_points": 500.0,
    "reviewer_person_key": "reviewer-eng",
    "reviewer_full_name": "Robin Reviewer",
    "discipline": "ENGINEERING",

    # Plan item
    "feature_key": "feature-alpha",
    "ia_placement": "NEW_TOPIC",
    "audience_tier": "STANDARD",
    "planned_page_count": 3,
    "complexity_points": 10,
    "window_start_date": "2026-08-02",
    "window_end_date": "2026-08-09",

    # Topic / revision
    "slug": "getting-started",
    "title": "Getting Started",
    "body_word_count": 1000,
    "summary": "Initial draft of the getting started page.",

    # Terminology
    "term": "login",
    "preferred_form": "sign in",
    "forbidden_forms": ["log in", "logon"],
    "enforcement_severity": "BLOCKER",

    # Doc set version
    "doc_set_version_label": "docs-2026.1",
    "eol_notice_text": "This documentation set has reached end of life.",

    # Change record
    "internal_summary": "Refactored the authentication handshake.",
    "severity": "MINOR",
    "category": "FEATURE",
    "affected_component": "feature-alpha",
    "customer_facing_text": "Signing in is now faster and more reliable.",
    "exclusion_reason": "Internal-only change with no customer impact.",

    # Locale profile
    "locale_code": "fr-FR",
    "publication_mode": "SIMULTANEOUS",
    "tm_coverage_pct": 40.00,
    "per_word_rate_cents": 12.50,
    "sla_days": 10,
    "parallel_job_limit": 5,

    # Localization job
    "job_window_start_date": "2026-08-02",
    "job_window_end_date": "2026-08-20",
    "translated_word_count": 1000,
    "tm_matched_word_count": 400,
    "cancel_reason": "Vendor contract terminated early.",

    # Deprecation notice
    "deprecation_feature_key": "legacy-endpoint",
    "severity_tier": "MINOR",
    "announce_date": "2026-08-01",
    "deprecated_date": "2026-08-15",
    "removal_date": "2026-10-01",

    # Reader feedback
    "rating": 4,
    "outcome": "RESOLVED_SELF_SERVE",
    "session_key": "session-abc123",
    "feedback_comment": "This page answered my question.",

    # Opaque operator identities
    "docs_lead_user_id": "docs-lead-001",
    "docs_lead_alt_user_id": "docs-lead-002",
    "localization_coordinator_user_id": "loc-coord-001",
    "support_analyst_user_id": "support-analyst-001",
    "reader_user_id": "reader-001",
}
