## Step 1: Create task directory — 2026-09-06T03:15:59.990730850Z

Created /home/ubuntu/github/CodingPRD/tasks/task_2992_consumer_device_security_labeling and workspace/ (pre-assigned path from the invocation; no index auto-allocation performed).

## Step 2: Generate scaffold — 2026-09-06T05:07:49.524107721Z

Done — task 2992's Step-2 scaffold is complete and lints clean.

## Deliverables (`/home/ubuntu/github/CodingPRD/tasks/task_2992_consumer_device_security_labeling/`)

| file | lines | contents |
|---|---|---|
| `SCAFFOLD.yaml` | 2768 | §1.0–§1.7 only (no design keys). 15 entities, 8 state machines (LabelGrant and EnforcementCase each carry two independent status dimensions; ConformanceAssessment is cyclic), 2 `concurrency_rules` (`assessment-create-stale-product`, `renewal-create-stale-grant`), 8 calculations (weighted `conformance_score` with area floor + tiered grade and a PROVISIONAL/VERIFIED variant pair, `label_issuance_fee` band-from-subtotal, `enforcement_penalty` statutory-vs-revenue variants, penalty and bench-hour ledgers with conserved-quantity invariants, `label_validity_window`, `retailer_participation_tier`, `program_evaluation`), 34 ordered validations (priorities 10–70), 59 endpoints, 45 errors, 6 roles each with `identity:` (`role_model: segregation_of_duties`) |
| `SCAFFOLD_DIFFICULTY_DESIGN.yaml` | 1941 | single key `scaffold_difficulty_design`; 9 rule_ids × 2 instances = 19 depth probes (dual-variant, combinatorial formula, non-linear state machine, transitive cascade, priority-pair conflict, boundary precision, cross-entity state dependency, resource temporal overlap, compensating invariant) |
| `SCAFFOLD_CORNER_DESIGN.yaml` | 4773 | single key `scaffold_corner_design`; 97 breadth instances over all nine claim-extraction-guide sections: entities 15, state_machines 17, calculations 15, validations 25, endpoints 6, errors 2, rbac 9, complexity_layers 7, consistency_model 1 (26 of the 97 are `excluded_because:` stubs pointing at the §1.8 instance that already asserts the corner) |

## Verification

```
Coverage
  §1.5 endpoints declared:    59
  §1.1 entities declared:     15
  §1.8 instances scanned:     19
  §1.9 instances scanned:     71
  Calls scanned (§1.8+§1.9):  1067

VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
```

Independent cross-checks I also ran: all 45 error ids are referenced by at least one design instance (zero uncovered); 116 instance names unique across the union of both design files; every stub's `difficulty_instance` resolves to a real §1.8 `rule_id / name` and no stub carries a `test_recipe`; every `${var}` in every payload/path/assert is bound by an earlier `captures:` in the same instance (0 unbound across both files); no forbidden concurrency vocabulary anywhere.

## Two lint violations closed this session
- The Required-Fields entities instance was omitting `declared_support_period_end` from the `POST /labeling/products` payload, which the linter rejects even for a deliberate 422 test; it now sends an explicit `null` for that field (same ERR_INVALID_REQUEST claim, payload ⊆ input satisfied).
- `cascading_validation_grant_state_is_checked_before_the_stale_version` had a literal `expected_label_grant_version: 999`; it now captures the Product version (advanced to 2 by the assessment write) and sends `${product_v2}` against a grant still at version 1, so the doubly-faulty renewal still proves priority 41 runs before priority 46.

## Notes for the orchestrator
- `SCAFFOLD.yaml`'s `scenario:` block reproduces the scenario verbatim as instructed, so it still contains the line `Generate task harder than expert level!` — strip that one line before Step 4 so the difficulty directive does not reach `PRD.md`.
- I did not touch `workspace/` or `worklog.md` (both intact, owned by you), and `.scratch/step2/` has been removed; `.scratch/` itself is left in place and empty.

**Orchestrator post-step action:** stripped the two leading lines of `SCAFFOLD.yaml`'s `scenario:` block ("Generate task harder than expert level!" + blank line) per the known difficulty-directive leak; `grep -c "harder than expert" SCAFFOLD.yaml` == 0. All three YAMLs re-validated with `yaml.safe_load`. SCAFFOLD.yaml now 2766 lines.

## Step 3: Copy shared files — 2026-09-06T05:07:54.493063673Z

Copied ./INSTRUCTION.md to tasks/task_2992_consumer_device_security_labeling/workspace/INSTRUCTION.md (53 lines).

## Step 4: Generate PRD — 2026-09-06T05:26:42.113058253Z

PRD generation complete.

**Output:** `workspace/PRD.md` — **488 lines / 112,894 bytes**, built in 14 incremental `cat >> ... <<'PRDEOF'` appends (`wc -l` + `tail -3` verified after each).

**Section list**
- `# Consumer Device Security Labeling API — Product Requirements Document`
- `## 1. Introduction`
- `## 2. Global Specifications & System-Wide Principles` — 2.1 User and Role-Based Access Control · 2.2 API Response Structure (appended byte-identical from the doc-generator skill's section-2.2 file) · 2.3 Pagination · 2.4 The Logical Clock · 2.5 Common Resource Properties · 2.6 Rejection Precedence (all 34 rungs, each with error id + exact `applies_to` set) · 2.7 Segregation of Duties · 2.8 Optimistic Concurrency Control · 2.9 Numeric Precision and Rounding · 2.10 Conserved Quantities · 2.11 Parallel State Dimensions, Cascades and Compensation · 2.12 Flat Collections and Left-to-Right Identifier Resolution
- `## 3. Business Logic & Workflows` — 3.1 Tiers, Categories and the Criteria Catalogue · 3.2 Sponsors, Products and Spec-Change Notices · 3.3 The Conformity Assessment Review Cycle · 3.4 Scoring a Conformance Claim · 3.5 Accredited Laboratories and Third-Party Bench Testing · 3.6 Label Issuance, Registry Content and the Publication Decision · 3.7 Validity Windows, Renewal and the Expiry Sweep · 3.8 Retailer Participation, Consumer Education and Label Display · 3.9 Misuse Enforcement, Penalties and Appeal · 3.10 Consumer Recognition Surveys and Program Evaluation
- `## 4. Endpoint Definitions` — 4-column table, **59 rows** (all 59 scaffold endpoints, incl. the expiry sweep and `POST /_clock/set_current_utc`)
- `## 5. Error Code Catalogue` — 2-column table, **45 rows** (all 45 scaffold error ids)

**Tail is a real section boundary** — the file ends on the last row of the §5 table with no audit footer.

**Contract 1 — Field-Name Coverage: PASS.** Mechanical check over 164 required identifiers (129 `entities[].fields[].name`, all `endpoints[].input` names, path params `id` / `scannable_code`, the 9 `program-evaluation` response keys, the nested `violation_line_items` object keys `retail_listing_ref` / `channel` / `unit_count`, the 4 sweep counters, `to_iso8601` / `current_utc`): **0 missing**, verified under the strict test (exact standalone backticked token, no credit from words inside path strings). All 45 error ids and all 59 paths also present.

**Contract 2 — Rule Coverage: PASS.** All 8 state machines and every one of their 46 transitions are in prose (including both parallel dimensions on `LabelGrant` and `EnforcementCase`, the fork-join on `case_status`, and all four sweep-driven edges); all 8 calculations reconstructible step-for-step with pinned rounding order; both `concurrency_rules` plus the third `expected_product_version` site; all 34 validation rungs with their `applies_to` scopes; all cascade/compensation chains incl. the asymmetry (grants reinstate, display authorizations do not). Mechanical sweep confirms **68/68 enum + state values, 24/24 calculation constants, 6/6 role names** appear verbatim.

**Contract 3 — §3 Path Purity: PASS.** 296 unique backticked tokens in §3; **0** start with `/`, **0** are bare HTTP methods, **0** are method+path combinations, and **0** raw (unticked) `/labeling…` mentions.

**Two scaffold internal contradictions resolved** (documented unambiguously so implementer and test generator agree):
1. `ConformanceAssessment.submitted_at` — field description says never re-stamped, the resubmit `side_effects` says re-stamped. Resolved **not re-stamped** (field description + the `DEFICIENT → UNDER_REVIEW` transition, which omits it, outvote the one side-effect line).
2. `Product.update_policy_disclosed` — field says it blocks registry-*entry* creation, but validation priority 54 `applies_to` names only the *publication* endpoint. Resolved by the priority ladder: `disclosure_completeness` derives from the four registry values only; publication additionally requires `update_policy_disclosed` true; either failure returns `ERR_REGISTRY_DISCLOSURE_INCOMPLETE`.

No difficulty meta-commentary (`grep -i` for "difficulty"/"expert" → 0). The two withheld design files were never opened. `worklog.md`, `SCAFFOLD*.yaml` and `INSTRUCTION.md` untouched; `.scratch/step4/` removed.

**Orchestrator verification:** independently confirmed 488 lines, tail ends on the final error-table row (`ERR_LABEL_LEGITIMATELY_ISSUED | 422`) — not mid-sentence; all 5 top-level sections present; a yaml-driven cross-check confirms 45/45 scaffold error ids and 59/59 scaffold endpoint paths appear in PRD.md; `grep -in "harder than expert|expert level|difficulty"` → 0 hits. No regeneration needed.

## Step 6: Generate implementation — 2026-09-06T06:07:25.843259096Z

Implementation complete and smoke-verified.

## Deliverables — `workspace/implementation/`

| file | lines | role |
|---|---|---|
| `start.sh` (chmod +x) | 10 | reads `$PORT`, guarded `pip install` on `import flask`, `exec python3 app.py` in the foreground |
| `requirements.txt` | 1 | `Flask>=2.2` |
| `app.py` | 104 | blueprint registration, `ApiError`/404/405/HTTPException/Exception handlers, per-request `RLock`, `app.run(host="0.0.0.0", port=$PORT)` |
| `errors.py` | 79 | all 45 error IDs + HTTP statuses |
| `envelope.py` | 105 | logical clock (`2026-08-01T00:00:00Z`), 3-fraction-digit ISO, `meta`/`response_type`/`data` helpers |
| `store.py` | 177 | 15 in-memory dicts, id/timestamp/version helpers, typed lookups |
| `validation.py` | 207 | typed field validators, pagination, `Decimal` numbers |
| `auth.py` | 62 | rungs 1-4 (`X-User-ID`/`X-User-Role`, ownership, SoD) |
| `lookups.py` | 94 | rung-5 existence resolvers, `resolve_fk` (existence before shape), list wrapper |
| `serialize.py` | 305 | 15 serializers; `SecurityCriterion`/`RecognitionSurvey` omit `updated_at`/`version` |
| `calc.py` | 264 | scoring + floor gate, grades, issuance fee bands, penalty variants, ledgers, participation tier, rates |
| `cascades.py` | 268 | version-bumping cascades, sponsor suspend/reinstate (asymmetric), supersession, expiry sweep |
| `routes_config.py` / `routes_participants.py` / `routes_products.py` / `routes_assessments.py` / `routes_engagements.py` / `routes_grants.py` / `routes_display.py` / `routes_enforcement.py` / `routes_program.py` | 186 / 154 / 199 / 376 / 227 / 441 / 151 / 332 / 138 | the 59 endpoints |

Total 3880 lines. No seeding anywhere; every collection is empty on boot and the clock resets to `2026-08-01T00:00:00Z`.

## Verification

- **Route parity:** the 59 method+path pairs registered diff **exactly zero** against the 59 declared in `SCAFFOLD.yaml` §1.5.
- **Error parity:** all 45 error IDs and HTTP statuses match both the scaffold catalogue and PRD §5 with zero mismatches, zero missing, zero extras.
- **Smoke test** (two scripts in `.scratch/step6/`, `bash start.sh` on random high ports, own PID killed by port lookup each time — no broad `pkill`): **113/113 checks pass.**
  - Phase 1 (65 checks): envelope/meta/`req_` id shape, pagination meta, error envelope, config -> manufacturer -> product -> assessment -> responses -> submit -> decide -> grant (fee 110000 = 100000 subtotal in the 10% band) -> registry entry -> SoD-blocked then successful publication -> validity window -> public registry lookup (and 404 for an unknown code) -> retailer education-ack (single version bump to 2) -> display authorization -> 7-day changeover conflict 409 -> enforcement case (fabricated code, `code_matches_registry` false, unit count 14) -> notice -> SoD 403 -> adjudicate (STATUTORY_SCHEDULE 76020 = 56700+19320, per-line rounding, multiplier 1.00) -> 3-link cascade (ledger DELINQUENT -> grant SUSPENDED/SPONSOR_DELINQUENT -> display WITHDRAWN/GRANT_SUSPENDED) -> payment -> conserved ledger, grant reinstated, display deliberately **not** reinstated -> survey -> program evaluation (100.00/45.00 -> MEETING_TARGET) -> clock set -> sweep expires the grant and the second sweep is a no-op -> 401/403/404 rungs.
  - Phase 2 (48 checks): THIRD_PARTY_TEST route, floor gate (weighted 70.00 capped to 65.00, `gate_applied` true), `ERR_THIRD_PARTY_TEST_REQUIRED`, non-accredited lab, strict window order, bench-hour reservation/capacity conflict 409/hours exceeded 409, unknown failed criterion code 404, report ownership, VERIFIED rescore to 100.00 grade A with hours credited back, `https://` enforcement, duplicate registry entry 409, WITHHELD then republication, spec-change cascade (`spec_revision` 2, `STALE`, grant SUSPENDED/PRODUCT_SPEC_CHANGED/renewal_required), OCC 412, `ERR_ASSESSMENT_SPEC_STALE`, lab-referral/notice leg join preserving both legs' evidence, REVENUE_LINKED penalty 4000000, vacate SoD + conserved compensation (`upheld_case_count` back to 0, standing GOOD), payment on a vacated penalty 409, filters, `limit=200` -> 400.
- **Restart cleanliness:** a fresh `bash start.sh` serves within ~3s (guarded install is a no-op) and reports `total_count: 0`, empty-denominator rates `0.00`, and `BELOW_TARGET` — so `--isolation per-test-server` reboots carry no state.

## Interpretation decisions worth flagging

1. `POST /labeling/products` is **not** ownership-gated: PRD §2.1 names exactly fourteen ownership-checked writes and that is not one of them, even though the scaffold's `Product.manufacturer_id` description says a Manufacturer caller's id "MUST equal this value". PRD wins per the skill's precedence rule. Same for `POST /labeling/test-engagements`.
2. `POST /labeling/display-authorizations/{id}/withdraw` requires a `withdrawal_reason` input but always **stores** `RETAILER_REQUEST` (the field is `source: computed` with the three cascade-specific values); any non-empty string is accepted for the input.
3. `reviewer_note` is stored on all three decide outcomes; a renewal clears the predecessor's `suspension_reason` when it moves to `REVOKED` (PRD §3.7 invariant); `submitted_at` is stamped only on first submit.
4. `violation_type` vs `code_matches_registry` consistency is descriptive only and is not enforced (PRD §3.9 states the pairing but declares no error for it).
5. `ERR_LABEL_LEGITIMATELY_ISSUED` fires only when `reported_retailer_id` is present, the code resolves to an `ACTIVE` grant, and an `AUTHORIZED` authorization for that retailer+grant covers the current logical-clock instant.

Left running: nothing. Scratch artifacts (`smoke.py`, `smoke2.py`, server logs) are in `.scratch/step6/`; the parent `.scratch/` was not touched.

## Step 5: Generate unit tests — 2026-09-06T06:27:03.455084985Z

Step 5 complete. Both stages are on disk at the task root and independently audited.

## Deliverables

**Stage 1 — `test_helpers/` (2547 lines, 9 files)**

| file | lines |
|---|---|
| `__init__.py` | 168 |
| `api_client.py` | 307 |
| `api_errors.py` | 126 |
| `assertions.py` | 236 |
| `constants.py` | 118 |
| `factories.py` | 416 |
| `fixtures.py` | 641 |
| `test_users.py` | 92 |
| `types.py` | 443 |

**Stage 2 — `test_suite/` (8372 lines, 20 files incl. conftest; 229 test functions)**

`conftest.py` 113 · `test_01_conformance_score_variants.py` 268 · `test_02_combinatorial_formulas.py` 259 · `test_03_nonlinear_state_machines.py` 243 · `test_04_transitive_cascades.py` 221 · `test_05_validation_precedence_pairs.py` 257 · `test_06_boundary_precision.py` 239 · `test_07_cross_entity_state_dependency.py` 236 · `test_08_resource_temporal_overlap.py` 290 · `test_09_compensating_invariants.py` 331 · `test_10_entity_contracts.py` 1022 · `test_11_assessment_and_engagement_state.py` 855 · `test_12_grant_and_display_state.py` 596 · `test_13_calculation_corners.py` 447 · `test_14_validation_corners.py` 858 · `test_15_endpoint_corners.py` 474 · `test_16_error_catalogue.py` 145 · `test_17_rbac_and_segregation.py` 765 · `test_18_complexity_layers.py` 585 · `test_19_consistency_model.py` 168

## Instance coverage

- **§1.8 queue A (difficulty): 19 / 19 translated**, every one carrying >=2 tests. Zero skips.
- **§1.9 queue B (corner): 70 / 71 non-stub translated.** 27 of the 97 total entries are untranslated:
  - **26 x `stub-instance`** — each carries `excluded_because` pointing at the queue-A instance that covers it and has no `test_recipe` at all, so there is nothing to translate and no coverage gap: 11 under `calculations`, 11 under `validations`, 2 under `state_machines` (`parallel_dimensions_grant_status_independent_of_registry_publication_status`, `cyclic_deficiency_loop_terminates_at_the_tier_round_cap`), 2 under `complexity_layers`.
  - **1 x `contradicts-PRD`** — `Corner/state_machines/cross_entity_republication_restamps_the_entry_without_recomputing_the_window`. The recipe asserts a second publication re-stamps `published_at`/`published_by_user_id`, but the PRD says those keep their first-publication values. Skipped rather than weakened; the PRD-correct behaviour is already pinned by `test_03_nonlinear_state_machines.py::test_republication_keeps_the_original_published_at_and_validity_window`.

## Verification

- AST audit over all 229 test functions: **exactly one `Design:` line each, last in the docstring, every tag resolving to a real `name:` in the source yaml** (89 distinct tags — 19 difficulty, 70 corner). `PROBLEMS: 0`; no untagged, dual-tagged, or dangling tags; each test also carries exactly one verbatim-greppable `PRD:` citation, and no generated file mentions "scaffold" or a design-index section.
- `pytest --collect-only`: 229 tests collected, no import or collection errors.
- Output location confirmed: `test_helpers/` and `test_suite/` exist at the task root and neither exists under `workspace/`. `__pycache__` cleaned up.
- Fixture-correctness sweep clean on all nine reminders: money as JSON integer cents; full instants with `canonical_instant` normalisation in `assert_instant_equals`; blank-header tests send `""`; derived factories build a local `defaults` dict so no key arrives twice; `validate_success` never double-unwrapped (`fixtures.created/read` use `get_success_data(response)`); both `validate_paginated` and a domain `validate_unpaginated` provided; windowed-aggregate fixtures park the clock inside the window; multi-hop fixture helpers are phased; all 16 fabricated `scannable_code` literals are exactly 16 `[A-Z0-9-]` chars.

## Notes for Step 7 (design-index-vs-PRD discrepancies resolved PRD-first — do not "fix" the implementation to match the recipes)

`ERR_INVALID_REQUEST` is **400**, not 422 · `spec_revision` is **2** after a spec-change notice, not 1 · several recipe `scannable_code` literals were 15 or 20 chars and were widened to 16 · `disclosure_completeness` reads **COMPLETE** when the four registry conditions hold even with `update_policy_disclosed: false` (that flag is a separate publication gate) · `decided_overall_score`/`grade` are **non-null** on an `UNDER_REVIEW` `SELF_ATTESTATION` assessment.

**Orchestrator verification:** confirmed `test_helpers/` (2547 lines) and `test_suite/` (8372 lines) at the task root with no `workspace/test_helpers` or `workspace/test_suite` strays; file sizes stable across two checks ~9 min apart; `pytest --collect-only -q` -> 229 tests collected, 0 errors; `Design:` tag census 68 Difficulty + 161 Corner = 229, one per test.

## Step 7: Run tests and iterate — 2026-09-06T06:38:42.938057512Z

Step 7 is complete — the suite went green on the first iteration, with no fixes and no deletions required.

## Summary

**Iterations run:** 1 (single 8-round sweep; the verdict was clean, so no fix/re-run cycles were needed).

**Tests deleted:** none. No test failed, so no STEP 1a silence / STEP 1b non-unique-derivability adjudication was triggered.

**Fixes applied to `test_helpers/`:** none.

**Fixes applied to `test_suite/`:** none.

**Fixes applied to `implementation/`:** none. No file under the task dir was edited by the Step 7 agent — `git status` shows the task dir wholly untracked with no modifications beyond the sweep's own `results.*.json` / `SWEEP_DONE` / `sweep.log` artifacts. `worklog.md`, `PRD.md`, `INSTRUCTION.md`, `SCAFFOLD*.yaml`, `sweep.sh` and `summarize_sweep.py` untouched.

**Final sweep, per-round figures quoted from the 8 results files** (`workspace/implementation/results.1..8.json`):

```
round 1: 229/229 passed  failed=0 errors=0 skipped=0  397s
round 2: 229/229 passed  failed=0 errors=0 skipped=0  397s
round 3: 229/229 passed  failed=0 errors=0 skipped=0  397s
round 4: 229/229 passed  failed=0 errors=0 skipped=0  397s
round 5: 229/229 passed  failed=0 errors=0 skipped=0  397s
round 6: 229/229 passed  failed=0 errors=0 skipped=0  397s
round 7: 229/229 passed  failed=0 errors=0 skipped=0  397s
round 8: 229/229 passed  failed=0 errors=0 skipped=0  397s
union of failing tests across all rounds: 0
VERDICT: CLEAN 8/8
```

**Anti-false-positive checks the agent ran on that verdict:**
- All 8 `results.*.json` exist, are ~76 KB each, and have **8 distinct md5 sums** — 8 independent rounds, not one file copied.
- Each file carries `total=229`, `passed=229`, `len(tests)==229`, and per-round `duration_seconds` differing at sub-second granularity (396.953 - 397.029), so the identical `397s` is integer rounding, not a duplicated artifact.
- Collection complete: exactly **229** `def test_` functions across the 19 `test_suite/test_*.py` files, matching the 229 executed. `skipped=0` everywhere, so nothing was silently xfailed or skipped.
- The summarizer's key-name cross-check (`len(fails)` vs `total - passed - skipped`) did not fire, so the zero-failure reading is not a `status`/`outcome` key mismatch.
- `implementation/` contains only `.py` files plus `requirements.txt` and `start.sh` — no SQLite file, no JSON dump, no on-disk cache; state is in-memory only.

**Diagnostic context gathered while the sweep ran** (no action taken; recorded for Step 9). Three implementation details are permissive-but-consistent with the PRD rather than exact matches: `routes_config.create_device_category` would tolerate an explicit `exclusion_reason: null` beside `ELIGIBLE` where §3.1 says the field "must be omitted entirely"; `routes_grants.read_registry_entry` returns the zero-or-one-element array through `lookups.listing`, which attaches pagination meta; and `_mint_scannable_code` never emits hyphens although §3.6 permits them. No test in the current suite exercises any of the three, so all 8 rounds pass regardless.

**Orchestrator verification:** re-ran `summarize_sweep.py --detail` myself — 229/229 in all 8 rounds, union of failing tests 0, VERDICT CLEAN 8/8; `md5sum` over the 8 results files yields 8 distinct digests; `git status --porcelain` on the task dir shows only the untracked-dir entry (no modified tracked files). The raw `grep -c "def test_"` count is 230 rather than 229 because `test_suite/conftest.py:71` defines a fixture named `test_lab_operator_headers`; conftest.py is not collected as a test module, so 229 collected is correct.

## Step 8: Finalize PRD — SKIPPED — 2026-09-06T06:38:42.950520383Z

Skip condition from the skill met exactly: Step 7 exited on its first 8-round sweep with 0 test deletions, 0 `test_suite/` fixes, 0 `test_helpers/` fixes, and 0 `implementation/` fixes — zero iterations beyond the baseline. `PRD.md` therefore already determined every behavior the implementation exhibits at every site Step 7 could have touched, and there is no `<step_7_diff>` to target. No subagent spawned; `workspace/PRD_FINALIZED.md` is deliberately absent. Step 9 will consequently start from `workspace/PRD.md` (per its documented input fallback) and, being a full independent PRD-vs-implementation scan, remains the sole gate on residual ambiguity/mismatch.

## Step 9: Complete PRD — 2026-09-06T07:27:48.949359961Z

Run as FIVE sequential passes rather than one monolithic scan (four module-partitioned passes over `implementation/`, then a dedicated reconciliation pass), because a single-agent scan of a 19-module / 3,880-line implementation against a 488-line PRD reliably no-ops on the trailing modules. All five passes shared one output file; only pass A performed the `cp`.

**Source:** `workspace/PRD.md` (488 lines / 112,894 chars). `PRD_FINALIZED.md` does not exist — Step 8 was legitimately skipped.
**Output:** `workspace/PRD_COMPLETED.md` — **502 lines / 147,315 chars (+14 lines / +34,421 chars)**.
**Totals:** 88 changes — pass A 17, pass B 10 (7 ambiguity / 3 mismatch), pass C 18 (12 / 6), pass D 23 (19 / 4), reconciliation 20.

### Pass A — global/cross-cutting layer (app, envelope, errors, store, validation, auth, lookups, serialize)
17 changes (14 ambiguity-pins, 3 mismatch-revisions). Highlights: `api_request_id` is `req_` + exactly 20 `A-Z0-9` chars; `api_request_timestamp` comes from **wall-clock** time, the sole exception to the logical clock; the four computed-projection endpoints carry none of §2.5's common properties; bulk creates answer 201/`"array"` with no pagination fields; out-of-range `limit`/`offset` are **rejected, never clamped**; the `id` tie-break is load-bearing because the frozen clock makes `created_at` tie, so order is UUID order not insertion order; instants always render `Z` with exactly three fractional digits, sub-ms truncated toward zero; `null` is a present key, never omitted; **mismatch** — rung 3 is inverted for row-derived ownership (two ops compare the id ahead of existence, the other twelve skip rung 3 and report rung 5's not-found); **mismatch** — the two tier decimals are "at most 2 dp" and read back unpadded (`80.00` -> `80.0`); **mismatch** — unrouted paths return `ERR_NOT_FOUND` 404 and wrong-method `ERR_METHOD_NOT_ALLOWED` 405, neither in the §5 table, both decided before authentication. Verified already-correct: all 45 error ids + statuses, all 59 endpoint rows incl. authorized-role sets, the 13-vs-2 serializer split, the four SoD bars.

### Pass B — computation and cascade layer (calc.py, cascades.py)
10 changes (7 / 3). **Every numeric constant, band boundary, threshold inclusivity, rounding order and cap in `calc.py` already matched the PRD exactly** (area weights 0.30/0.30/0.25/0.15, floor 60.00 strict, cap 65.00, grades 90/80/tier-min, fee bands 50000/150000 at 0/0.10/0.18, 12000-cent supplement, statutory 4200/2750/6100, channel 1.15/1.35, step 0.25 cap 2.00, caps 5000000/25000000, rate 0.0004, BARRED 3 / DELINQUENT 25000, PLATINUM 5 / GOLD 2, targets 40.00/35.00, empty denominator -> 0.00), and the two tier decimals are quantized `Decimal` not float, so no binary-precision artifact reaches the `>=` comparison. The residual gaps were all in write-sets, cascade version semantics and pass ordering. Pinned: `apply_changes` is a **value-comparing write** — a recompute-to-same-state link is a true no-op (no `updated_at`, no `version`), each link is one mutation, a row reached by several links is recounted once; the sweep's five kinds of work run in a strict order each reading what earlier passes wrote; each sweep counter reports one transition only; the auth-expiry pass reads post-suspension status so a display whose grant died earlier in the same sweep never counts; the engagement predicate reads `window_start` alone. **Mismatches**: the provisional scoring pass writes `decided_min_area_score`+`gate_applied` on every submit/resubmit whatever the route while the verified pass overwrites them only on `THIRD_PARTY_TEST` (fixed at both call sites; the claim that "a tested assessment is by definition on the THIRD_PARTY_TEST route" was false); "Every adjudication" -> "Every **upheld** adjudication" recomputes the ledger. Deliberate non-change: intra-pass sweep iteration order is not externally observable, so nothing was pinned about it.

### Pass C — configuration and intake routes (config, participants, products, assessments, engagements)
18 changes (12 / 6). Pinned: criteria bulk create validates element-by-element in declared order and accepts an empty array (201, empty `data`); catalogue `practice_area ASC` is plain alphabetical, not §3.4's weighting order; a supplied `manufacturer_id` need not equal the acting id; every element's `criterion_id` resolves before any element's shape is judged; submit declares no body fields; decide requires `reviewer_note` and a null `decided_overall_score` fails `ERR_SCORE_BELOW_MINIMUM`; `submitted_at`/`decided_at`/`decided_by_user_id`/`last_deficiency_by_user_id`/`reviewer_note` all survive a resubmission; booking gates on neither the assessment's `route` nor its `status` nor ownership, and one assessment may carry several engagements; repeated `failed_criterion_codes` are legal and stored verbatim; cancel ownership is the engagement's `test_lab_id` for a lab operator but the two-hop assessment->product `manufacturer_id` for a manufacturer. **Mismatches**: rung 6's uniqueness list was under-inclusive (`lab_name`, `retailer_name`); tier decimals "exactly two" -> "at most two"; `provisional_area_scores` missing from the assessment's null-at-creation list; the resubmit upsert writes **both** answer fields so an element omitting `evidence_ref` nulls the stored reference (a real exception to the global optional-field convention); the resubmit reset is value-comparing not an unconditional stamp; §4's booking row said "for a third-party-tested assessment".

### Pass D — label, display, enforcement and evaluation routes (grants, display, enforcement, program)
23 changes (19 / 4). Pinned: a grant with no registry-entry row yields `ERR_REGISTRY_DISCLOSURE_INCOMPLETE`, not a not-found; all five publication requirements belong to the `PUBLISHED` decision alone (`WITHHELD` skips SoD, disclosure, support-period and standing); creating a registry entry touches the grant not at all; the public lookup returns exactly fourteen fields, is gated on `registry_publication_status` alone, so a suspended/revoked/expired grant still resolves and reports its `grant_status`; validity containment is inclusive at both bounds and a null bound fails outright; the `violation_type` <-> `code_matches_registry` pairings are descriptive and never enforced; the four exact preconditions of `ERR_LABEL_LEGITIMATELY_ISSUED`; the referral leg has **no once-only guard**, so referral->notice->referral overwrites `referred_test_lab_id`; vacate retains `penalty_cents`, `penalty_variant`, `aggravation_multiplier`, `adjudicated_at`/`_by` and the notice fields; payment reads `penalty_status` alone, never `case_status`; the retired predecessor keeps `renewal_required` exactly as it stood while `suspension_reason` is cleared. **Mismatches**: `scannable_code` mints 16 chars from `A-Z0-9` only — the PRD permitted hyphens; the renewal `conformance_currency` restore travels the value-comparing write; §3.9's "declared order is load-bearing for the penalty computation" softened (per-line rounding makes the total order-insensitive; order decides only the stored array); §4's expiry-sweep row omitted the support-period suspension pass. Confirmed already-correct: all nine program-evaluation field names incl. the deliberate `respondents_count` vs `recognized_total` asymmetry, and the 2/1/0-targets-cleared grade banding against the rounded rates.

### Pass E — reconciliation
20 changes / +3,653 chars, closing every cross-partition hand-off the four passes had reported but correctly refused to edit:
- **(a)** swept all 8 `unique_or_reject` call sites and completed rung 6's list with the missing `survey_period_label`; the list now names exactly eight and says so.
- **(b)** hoisted the row-dependent SoD rule to rung 4 for all four barred operations (bar read off the target row; unresolvable id yields the not-found code first; a null witness bars nobody), then trimmed the redundant local restatements while keeping the two operation-specific wrinkles the global rule loses. Surfaced one extra fact in the process: registry-publication parses the body **before** the SoD check (unlike the other three), so it is the one operation where a non-object body beats rung 4 — pinned rather than left silently wrong.
- **(c)** qualified rungs 19/27/28/34 as firing only for a `PUBLISHED` decision.
- **(d)** reconciled §2.5's "recomputation counts as a mutation" over-promise against §2.11's value-comparing-write rule.
- **(e)** corrected §2.3: four of the five domain sorts take `id` as final tie-break; the criteria catalogue is the exception.
- **(f)** §3.1's `exclusion_reason` "must be omitted entirely" -> "must carry no value", leaning on rung 6's null-equals-omission rule.
- **(g)** added `aggravation_multiplier` to §2.9's rates sentence without restating the formula.
- **(h)** resolved the half-pinned string-ceiling inconsistency by completing coverage compactly — one rung-6 sentence giving the full per-field table (64/100/200/320/500/1000/2000), naming `tier_code` as the sole floor+pattern exception and listing the genuinely unbounded inputs — then trimming all 10 scattered per-field mentions. A verifying grep confirms no input ceiling is now stated twice or left silent.
- **Work item 2 (cross-pass consistency):** one genuine contradiction found and fixed — §3.2 said a renewal publication's `conformance_currency` write increments `version` unconditionally while §3.6 correctly called the same write value-comparing; `routes_grants.py:339` uses `apply_changes`, so §3.2 was wrong. One near-miss tightened (§2.7 vs rung 4: added a one-sentence division of labour). The other four named seams were each verified rather than assumed and were clean.

**Orchestrator verification of the final deliverable:** `PRD.md` 488 lines / 112,894 chars vs `PRD_COMPLETED.md` 502 lines / 147,315 chars; `cmp` reports DIFFERENT (not byte-identical, so the scan demonstrably ran); all 5 top-level `## ` sections present; the file ends at a real boundary (the complete final error-table row `| ERR_LABEL_LEGITIMATELY_ISSUED | 422 |`), not mid-sentence; a yaml-driven cross-check confirms all 45 scaffold error ids and all 59 endpoint paths still appear. Pipeline complete.

