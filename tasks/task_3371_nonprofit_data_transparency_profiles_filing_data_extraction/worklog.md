# Worklog — task_3371_nonprofit_data_transparency_profiles_filing_data_extraction

Scenario: Nonprofit Data Transparency Profiles & Filing Data Extraction (Candid) — nonprofit profile creation with self-reported programs/finances/leadership/demographics and verification levels, annual information return (Form 990) extraction with normalization across form versions and schedules, transparency seal levels with annual renewal, grant data collection from funders with recipient matching and taxonomy coding, data licensing with permitted-use restrictions, organization identity resolution across name changes/mergers/dissolutions, funder research tools with prospect matching and historical giving patterns, data correction requests.

## Step 1: Create task directory — 2026-10-01T10:14:23.803Z

Task directory `./tasks/task_3371_nonprofit_data_transparency_profiles_filing_data_extraction/` was pre-allocated by the caller (already contained an empty `workspace/`). No new `task_*` directory was computed or created; the index was taken verbatim from the invocation arguments. `workspace/` exists and is empty.

Interruption note: the first orchestrator session was stopped mid-Step-2. On resume (2026-10-01T10:14Z) the task directory contained only this worklog — the Step 2 subagent had written no files. Step 2 was therefore re-run from scratch.

## Step 2: Generate Scaffold — 2026-10-01T11:07:24.761Z

Subagent (prd-bench-scaffold-generator) returned, verbatim:

> All three artifacts are written and the scaffold lints clean.
>
> ## Files written
>
> | Path | Lines |
> |---|---|
> | `/home/ubuntu/github/CodingPRD/tasks/task_3371_nonprofit_data_transparency_profiles_filing_data_extraction/SCAFFOLD.yaml` | 1954 |
> | `/home/ubuntu/github/CodingPRD/tasks/task_3371_nonprofit_data_transparency_profiles_filing_data_extraction/SCAFFOLD_DIFFICULTY_DESIGN.yaml` | 1520 |
> | `/home/ubuntu/github/CodingPRD/tasks/task_3371_nonprofit_data_transparency_profiles_filing_data_extraction/SCAFFOLD_CORNER_DESIGN.yaml` | 2244 |
>
> ## Counts
>
> - **Entities:** 12 (Organization, Program, Filing, ExtractedField, LeadershipMember, DemographicRecord, TransparencySeal, Grant, DataLicense, LicenseUsageEvent, CorrectionRequest, IdentityResolutionCase)
> - **Endpoints:** 40 (at budget)
> - **State machines:** 7 (Organization, Filing, ExtractedField, TransparencySeal, DataLicense, CorrectionRequest, IdentityResolutionCase) + 2 concurrency rules
> - **Calculations:** 14 · **Validations:** 11 (priority-ordered) · **Errors:** 33 · **Roles:** 4
> - **§1.8 instances:** 19 across all 9 rule_ids (dual_variant_calc 2, combinatorial_formula 3, and 2 each for the other seven)
> - **§1.9 instances:** 55 active across all 9 guide sections, plus 19 `excluded_because:` stubs citing §1.8 instance names
>
> Profile: `compliance_audit` + `workflow_orchestration`, `graph` topology, `cyclic` machines, `segregation_of_duties` roles — deliberately avoiding the `hybrid`/linear/hierarchical defaults the skill flags as over-used.
>
> ## Verification performed
>
> - `scaffold_lint.py .` → **`VERDICT: clean lint`** (40 endpoints, 743 calls scanned, 0 violations) — checks (a)–(f) all pass.
> - Independent audit: all `grounds:` refs resolve to declared §1.1–§1.7 elements (0 dangling); every `${var}` is bound by an earlier `captures:` in the same instance; every `excluded_because.difficulty_instance` names a real §1.8 instance; no forbidden concurrency vocabulary.
> - Formula-derived literals were computed by executing the scaffold's own formulas as code (e.g. provisional 100 vs verified 88 for the completeness dual variant; 691202 vs the rejected 691201 for the rounding order; 82500/75000 for the renewal fee; 700000/510000 for the license variants).
> - Two enum dead-ends found and closed (Program `ARCHIVED`, Grant `AUTO_CODED` — the latter now produced by the re-match rule).
>
> ## Trade-offs against your constraints
>
> 1. **Error count is 33, not ≤30.** The §0.4 Expert band tops out at 30 error codes. Every one of the 33 is referenced by a transition or validation, and the scenario's five independent sub-domains (profile/verification, filing extraction, seals, licensing, identity resolution) each need their own not-found and constraint codes. I trimmed 5 codes by merging (`ERR_ORG_SUSPENDED`/`ERR_ORG_NOT_ACTIVE` into `ERR_ORG_NOT_IN_GOOD_STANDING`, `ERR_SEAL_ALREADY_ACTIVE` into `ERR_INVALID_STATE`, dropping `ERR_DUPLICATE_TAX_YEAR_FILING`) but stopped there rather than collapse entity-specific 404s into a generic one.
>
> 2. **§1.9 has 55 active instances rather than a trimmed ~45.** The skill defines §1.9 as enumerative breadth and its `excluded_because` stubs exist precisely so the walk stays exhaustive. If the downstream unit-test generator proves unable to consume that many, the 19 stubs mark the safe reduction set (they're already covered by §1.8).
>
> 3. **Endpoint consolidation.** Reaching 40 required one non-obvious move: demographic records are created by a replacing `demographic_records` array on `PATCH /nonprofits/organizations/{id}` rather than a dedicated POST, which frees the slot needed for `GET /nonprofits/extracted-fields/{id}` (required for FK reverse-reachability of `CorrectionRequest.target_extracted_field_id`). Depth was preserved — the wholesale-replace semantics became a §1.9 derived-reconciliation claim.
>
> 4. **One scaffold rule had to be strengthened to make a §1.8 cascade coherent**: the seal's `ACTIVE → REVOKED` trigger was changed from a completeness-score floor to a disclosure-floor breach, because a disclosure-floor breach is genuinely caused by the preceding hop (a demographics replacement) while a completeness floor was not.

Orchestrator verification (independent of the hand-back): all three files present on disk (`SCAFFOLD.yaml` 118573 B / 1954 L, `SCAFFOLD_DIFFICULTY_DESIGN.yaml` 95951 B / 1520 L, `SCAFFOLD_CORNER_DESIGN.yaml` 126279 B / 2244 L); all three parse as YAML; top-level keys are exactly `[scenario, domain_name, api_prefix, complexity_profile, response_envelope, entities, state_machines, concurrency_rules, calculations, validations, endpoints, errors, roles]` for SCAFFOLD.yaml and the single required key for each design index; tails end on complete YAML structures (no truncation).

## Step 3: Copy Shared Files — 2026-10-01T11:07:24.761Z

Bash-only. `cp /home/ubuntu/github/CodingPRD/INSTRUCTION.md → workspace/INSTRUCTION.md`. Verified identical by sha256 (`24a88199f36f677ae9221badbb3605e755af7a81fbaaffd7942018724fe1b38d`, 1424 B).

## Step 4: Generate PRD — 2026-10-01T11:29:01.224Z

Subagent (prd-bench-doc-generator) returned, verbatim:

> PRD generated and mechanically verified.
>
> ## Output
>
> `/home/ubuntu/github/CodingPRD/tasks/task_3371_nonprofit_data_transparency_profiles_filing_data_extraction/workspace/PRD.md` — **436 lines**, 88,887 chars.
>
> ## Top-level sections
>
> - **1. Introduction** (3 paragraphs)
> - **2. Global Specifications & System-Wide Principles** — 2.1 User and Role-Based Access Control · 2.2 API Response Structure (verbatim) · 2.3 Pagination · 2.4 The Logical Clock and Temporal Evaluation · 2.5 Profile Records, Identifiers and Common Resource Properties · 2.6 Verification Standing and Segregation of Duties · 2.7 Taxonomy Reference Data and Closed Sets · 2.8 Precision, Rounding and Integer-Cents Arithmetic · 2.9 Optimistic Concurrency Control · 2.10 Nested Resource Retrieval and Validation Precedence · 2.11 Derived Aggregates and Cascade Reconciliation
> - **3. Business Logic & Workflows** — 3.1 Organization Profiles and Self-Reported Records · 3.2 The Completeness and Disclosure Ledger · 3.3 Verification Advancement and the Standing Gate · 3.4 Information Returns: Revision Creation and Line Extraction · 3.5 Normalization, Revenue Aggregation, Supersession and Voiding · 3.6 Correction Requests and the Dispute Cascade · 3.7 Transparency Seals: Award, Renewal, Revocation and Lapse · 3.8 Organization Identity Resolution: Name Changes, Mergers and Dissolutions · 3.9 Data Consumers: Licensing, Grant Records and Funder Prospect Research
> - **4. Endpoint Definitions** — 40 rows, 4 columns
> - **5. Error Code Catalogue** — 33 rows, 2 columns. No audit footer in the file.
>
> ## Hard-contract verification (run mechanically against SCAFFOLD.yaml)
>
> - **Contract 1 — Field-Name Coverage: PASS.** 130 required names (all `entities[].fields[].name`, all `endpoints[].input` identifiers, all `{path}` params) → 130 present in backticks, 0 missing. Two passes were needed; `event_id` and `resolution_decision` were caught only on the second.
> - **Contract 2 — Rule Coverage: PASS.** 33/33 `errors[].id` appear in §2/§3 with their conditions. All 11 validation priorities rendered as an explicit override ladder in §2.10. Both `concurrency_rules` rendered with write_endpoint + `occ_field` + error_id + 412. All state transitions rendered with trigger, guard, and every side effect (including the failing/rejection branches — tier-3 renewal lapse, merge cycle, stale-version refusals, WITHDRAW). All calculations rendered with pinned evaluation order and concrete constants; every numeric literal from the scaffold (unit multipliers, dimension/disclosure weights, worked-example values 123401/567801/691202/691201, 82500/250000, 700000/510000, 60/70, tier fees, day thresholds, 365/60/90/30, 0.9000/0.8500, the full FORM_VERSION_LINE_MAP and PERMITTED_USES_BY_TIER tables) is present. No fuzzy hedging words.
> - **Contract 3 — §3 Path Purity: PASS.** 899 backticked tokens scanned in §3; 0 starting with `/`, 0 bare HTTP methods, 0 method+path combinations.
> - **§2.2 byte-identical** to `section-2.2-response-structure.md` (including `req_RANDOMALPHANUM123456`, `2025-05-24T10:30:00.123Z`, `UNIQUE_ERROR_IDENTIFIER_STRING`, `"data": { }`).
> - All dates are relative to the declared logical clock `2026-09-01T00:00:00Z`; no unreachable absolute calendar date was emitted.
>
> ## Self-audit — rules I could NOT render as uniquely-determining sentences
>
> 1. **Empty `raw_lines` on extraction (unresolved scaffold self-contradiction).** SCAFFOLD §1.2's `note` on `RECEIVED → EXTRACTION_FAILED` states that an empty `raw_lines` array is "rejected with 422 `ERR_NO_EXTRACTED_FIELDS` and the filing stays in `RECEIVED`", but §1.5's extract description and `side_effects` *and* §1.6's `ERR_NO_EXTRACTED_FIELDS` condition all state the filing "moves to `EXTRACTION_FAILED`". Three places say one thing, the state-machine note says the opposite. I rendered the §1.2 state-machine reading (request refused 422, no `ExtractedField` rows created, filing not advanced past `RECEIVED`) and made the non-empty-but-unparseable case the sole trigger for `RECEIVED → EXTRACTION_FAILED`. **This needs adjudication** — it is the one scaffold rule I could not render without contradicting another scaffold statement.
> 2. **`expected_organization_version` on the profile patch.** The skill says endpoints not listed in `concurrency_rules` do not take a version field, but the scaffold's PATCH input list includes it and only two `concurrency_rules` entries exist. I named the field as an accepted input (Contract 1) but did not invent a 412 rejection for it, since no `error_id` is nominated for that endpoint.
> 3. **`min_score` on funder prospect research.** The scaffold declares the query parameter but never defines its semantics. I rendered it as a floor restricting returned prospects to those at or above the supplied match score — the minimal inference needed for the name to determine anything.
> 4. **`ExtractedField.version` on the `PARTIALLY_ACCEPTED` branch.** §1.2's `NORMALIZED → CORRECTED` transition for partial acceptance omits the "increments `ExtractedField.version` by 1" side effect that both `ACCEPTED` branches carry. I rendered the asymmetry explicitly rather than smoothing it, but it may be a scaffold omission.
> 5. **Enum members with no write pathway.** `Grant.status` `VOIDED` and `LeadershipMember.status` `ENDED` are declared but never written by any rule. I named both values and stated that no operation writes them, rather than inventing a transition.
> 6. **Seal `days_late` before expiry.** The formula `max(0, floor((clock_now - expires_on)/86400))` is defined for negative differences; I rendered it as "floored at zero — a renewal made before expiry is zero days late", which is faithful but is an interpretation of `max(0, …)` rather than a literal scaffold sentence.

Orchestrator verification: `workspace/PRD.md` present, 435 lines / 89069 B, ends on a complete table row (no truncation). The §3 path-purity and §2.2 byte-identity claims were spot-checked by grep and hold.

### Step 4a: Orchestrator adjudication of self-audit item 1 (scaffold repair)

Item 1 was a genuine internal contradiction in SCAFFOLD.yaml. Adjudicated by reading the authoritative sources:

- SCAFFOLD §1.2 `Filing.RECEIVED_to_EXTRACTION_FAILED` trigger is explicitly scoped to "a **non-empty** raw_lines array in which no line yields a parseable decimal raw_value", and its `note` explicitly carves out the empty case as "a different outcome".
- SCAFFOLD_DIFFICULTY_DESIGN.yaml queue-A instance `normalize_on_failed_filing_prefers_state_over_zero_field_constraint` — the authoritative test source — sets up EXTRACTION_FAILED via `raw_value: "NOT_A_NUMBER"` (non-empty, unparseable) and asserts that a subsequent `raw_lines: []` extract returns 422 `ERR_NO_EXTRACTED_FIELDS` while "Filing.status is still EXTRACTION_FAILED" (i.e. the empty request does not transition anything).

Both agree with the doc-generator's chosen reading; the §1.5 description, §1.5 side_effect, and §1.6 condition were the outliers. **Repaired SCAFFOLD.yaml at the source** (3 minimal edits, no semantic change — §1.2, §1.5, §1.6 and both design indices now all state the same rule):
1. `endpoints[POST /nonprofits/filings/{id}/extract].description` — now scopes EXTRACTION_FAILED to the non-empty-unparseable case and states the empty case is refused.
2. same endpoint's `side_effects` status line — same correction.
3. `errors[ERR_NO_EXTRACTED_FIELDS].condition` — the parenthetical "(the filing moves to EXTRACTION_FAILED)" replaced with "(the request is refused, no ExtractedField rows are created, and the filing is not advanced past its current status)".

Post-repair: SCAFFOLD.yaml re-parses as YAML (40 endpoints, 33 errors, top-level keys unchanged); `grep` confirms no residual contradictory phrasing.

Items 2–6 were assessed for load-bearing risk against the design indices before deciding not to act:
- item 2 (`expected_organization_version` on PATCH org): 37 index references, but every one supplies the org's *current* version as a valid handle; the only 412 assertion for `ERR_STALE_ORGANIZATION_VERSION` is the CORNER instance at line ~1784, which is on **POST /nonprofits/filings**. No instance asserts a stale-version rejection on the PATCH. Not load-bearing.
- item 3 (`min_score`): 0 references in either index. Not load-bearing.
- item 4 (`PARTIALLY_ACCEPTED` version asymmetry): 0 references in either index. Not load-bearing.
- item 5 (`Grant.status VOIDED`, `LeadershipMember.status ENDED`): all `VOIDED` references in both indices are `Filing.status` (which *is* written by the void rule); the 3 `ENDED` hits are substring matches inside `SUSPENDED`. Not load-bearing.
- item 6 (`days_late` floored at 0): **load-bearing** — the queue-A seal-renewal instance asserts 82500 cents on the first renewal (15 days late, GOLD) and 75000 on the second precisely because `expires_on` has moved into the future and `max(0, …)` yields 0. The PRD's rendering matches the scaffold formula exactly. No action needed.

## Step 5: Generate Unit Tests — 2026-10-01T12:01:06.368Z

Subagent (prd-bench-unit-test-generator) returned, verbatim:

> Test infrastructure and suite are complete and verified. Final report:
>
> ## Files written
>
> **`test_helpers/` (10 files, 1,614 lines)**
> | File | Lines |
> |---|---|
> | `types.py` | 423 |
> | `fixtures.py` | 450 |
> | `scenarios.py` | 284 |
> | `assertions.py` | 222 |
> | `factories.py` | 154 |
> | `api_client.py` | 153 |
> | `constants.py` | 136 |
> | `api_errors.py` | 94 |
> | `test_users.py` | 57 |
> | `__init__.py` | 41 |
>
> **`test_suite/` (13 files, 3,006 lines, 90 tests)** — `conftest.py` (24) plus `test_01_organization_profiles` (203), `test_02_filings_and_extraction` (323), `test_03_normalization_and_revenue` (323), `test_04_correction_requests` (346), `test_05_transparency_seals` (379), `test_06_verification_and_completeness` (192), `test_07_identity_resolution` (175), `test_08_data_licensing` (383), `test_09_grants_and_prospect_research` (222), `test_10_access_control_and_concurrency` (305), `test_11_organization_listings` (85), `test_12_filing_state_gates` (135).
>
> ## Counts
> - **Queue A (difficulty): 36 tests** covering 18 of 19 instances (all ≥2 each).
> - **Queue B (corner): 54 tests** covering all 53 non-stub instances (one instance — `roles/correction_submitter_cannot_accept_its_own_request` — has 2, split across the CLAIM and ACCEPT gates). The 19 `excluded_because:` stubs were not translated.
> - **3 instances skipped** (below).
>
> ## Skips (recorded as gaps, no placeholders, no skip/xfail)
> 1. **`Difficulty/non_linear_state_machine/filing_disputed_state_cycles_back_to_normalized`** — the asserted outcome `Filing.status == NORMALIZED` after re-normalizing a `DISPUTED` filing is not uniquely derivable. PRD §3.5 describes only the *field* repair pass ("every field of that filing still sitting in `PENDING` or `CONFLICT` moves to `NORMALIZED`") and never states the filing's own status returns to `NORMALIZED`; a PRD-consistent implementer can legitimately leave it `DISPUTED`. (The other 4 assertions in the recipe are covered, but the cycle *is* the instance.)
> 2. **`Corner/entities/organization_create_extra_field_profile_status_is_ignored_input`** — PRD contradicts it: §2.10 rung 4 says "body fields not declared in the endpoint's input list … yield `ERR_INVALID_REQUEST` (HTTP 400)", so the asserted 201-with-DRAFT is not a faithful reading.
> 3. **`Corner/entities/leadership_member_service_end_before_start_returns_invalid_request`** — PRD §3.1 defines the closed interval and the overlap rule but never states that an inverted interval is malformed; two PRD-only readers could split between 400 and silent acceptance.
>
> ## PRD-vs-index disagreements resolved (PRD followed)
> - **`license_fee…` / `A5` renewal** — kept as-is; verified the recipe's clock (`2027-09-16`, 15 days late) is reachable and the fee literals match the PRD.
> - **`Corner/state_machines/lapsed_seal_is_terminal…`** — the index asserts `ERR_SEAL_LAPSED` + `renewal_attempt_count == 1` at 91 days late, but PRD §2.4 declares a seal past `expires_on + 90 days` "already `LAPSED` … treated as such by any rule that inspects it", which pre-empts it with `ERR_INVALID_STATE`. Asserted `validate_error_is_one_of([ERR_SEAL_LAPSED, ERR_INVALID_STATE])`, terminal `LAPSED`, level `NONE`, `seal_expires_on` null, `renewal_attempt_count in (0,1)`; the second renewal is asserted `ERR_INVALID_STATE` (derivable either way).
> - **`Corner/roles/correction_submitter_cannot_accept_its_own_request`** — the index asserts `ERR_SEGREGATION_OF_DUTIES` for ACCEPT on a still-`SUBMITTED` request, but rung 5 (state) outranks rung 6 (safety). Split into two tests: CLAIM-by-submitter refused (as specified), and ACCEPT-by-submitter refused after a legitimate claim by another verifier.
> - **`Corner/entities/program_disclosure_level_defaults_to_restricted_when_omitted`** — the index's literal `disclosure_pct == 0.0000` contradicts its own recipe (a RESTRICTED program scores the 0.5 PROGRAMS rung, and the org carries a full mission block). Re-derived from the PRD formula: asserted `0.1750`.
> - **`Corner/state_machines/third_open_correction_request…`**, **`Corner/entities/organization_list_paginates…`**, **`Corner/entities/identity_case_finalize_withdraw…`**, **`Corner/cross_cutting_layers/filing_list_filters…`** — dropped sub-assertions that rely on query-parameter filters (`status=`, `state_code=`, `tax_year=`, `successor_organization_id=`) which PRD prose never declares; replaced with client-side filtering of the unfiltered list where the underlying claim is PRD-covered.
> - **`Corner/calculations/funder_prospects_*`** — the index claims `response_type == "array"`, PRD §3.9 says the response reports `funder_organization_id`, `mean_grant_amount_cents` and a `prospects` array (an object). Followed the PRD.
> - **`Corner/validations/seal_award_below_the_disclosure_floor…`** — the index's setup clears mission/NTEE by PATCHing `null` (a capability PRD never grants); built the same below-floor state by omitting those fields at creation (`0.4500 < 0.50`).
>
> ## Verification performed
> - `py_compile` + `pytest --collect-only` → **90 tests collected, 0 import/collection errors**; pyflakes clean outside the intentional barrel re-exports (this caught and fixed a missing `make_verifier_headers` import in `test_03`).
> - Tag audit: every test carries exactly one `Design:` line resolving to a real instance; no stub tags, no untagged/dual-tagged tests.
> - Citation audit: every test has ≥1 quoted fragment that survives a **strict literal grep** of `PRD.md` (147 quotes checked; 10 initially failed on wrapped sentences and were split into contiguous fragments).
> - No `pytest.mark.skip/skipif/xfail`; no "scaffold"/section-reference leakage in generated code.
> - Isolation: all fixtures/scenarios build state through the API inside the test's own call path; no module-level mutable state, no cross-test dependencies. Entity-backed roles (`OrganizationUser`, `DataConsumer`) always use `make_*_headers(entity["id"])`.

Orchestrator verification (independent of the hand-back):
- File inventory matches the report exactly: 10 files in `test_helpers/` (1614 L) and 13 in `test_suite/` (3006 L), all non-empty, none truncated.
- `pytest --collect-only` under the runner's own environment (`PYTHONPATH` = task dir, `cwd` = `test_suite/`, mirroring `executor.py:134`) → **90 tests collected, 0 errors**. (A first manual run without that `PYTHONPATH` raised `ModuleNotFoundError: test_helpers`; that was an artifact of my invocation, not a suite defect — the runner injects the path itself.)
- Independent tag audit: 0 untagged test functions across the 12 `test_*.py` files; 71 distinct `Design:` tags = 18 queue-A instances + 53 queue-B instances, consistent with the reported 36 + 54 = 90 test split.

## Step 6: Generate Implementation — 2026-10-01T12:43:19.423Z

Subagent (prd-bench-implementation-generator) returned, verbatim:

> Implementation complete and verified.
>
> ## Files written
>
> All under `/home/ubuntu/github/CodingPRD/tasks/task_3371_nonprofit_data_transparency_profiles_filing_data_extraction/workspace/implementation/`:
>
> | File | Lines | Role |
> |---|---|---|
> | `start.sh` | 10 | Launcher (executable) |
> | `requirements.txt` | 1 | Flask |
> | `app.py` | 83 | App factory, blueprints, error handlers |
> | `errors.py` | 113 | Error catalog + `ApiError` |
> | `clock.py` | 79 | Logical clock + ISO helpers |
> | `store.py` | 88 | In-memory store |
> | `response.py` | 98 | Envelope + pagination |
> | `webutil.py` | 119 | Body shape/type validation |
> | `auth.py` | 76 | Auth, RBAC, ownership |
> | `listing.py` | 48 | Filter/paginate/serialize |
> | `calc.py` | 600 | All §1.3 calculations |
> | `svc.py` | 601 | Serializers, aggregates, cascades |
> | `routes_org.py` | 397 | Org CRUD, verify, programs, leadership, demographics |
> | `routes_lists.py` | 138 | Org-scoped lists, license request/read |
> | `routes_filing.py` | 376 | Filings, extract/normalize/void, extracted fields |
> | `routes_correction.py` | 261 | Correction requests + decide |
> | `routes_license.py` | 227 | Licenses, usage events |
> | `routes_seal.py` | 130 | Seal award/renew |
> | `routes_grant.py` | 188 | Grants, match-recipient, prospects |
> | `routes_identity.py` | 205 | Identity cases + clock |
>
> ## Endpoint count
>
> **40 routed endpoints** — exactly the 40 rows of the PRD §4 table (verified against `app.url_map`; decorator count 7+3+3+3+5+10+7+2 = 40). An earlier `/health` probe I had added was removed because it does not trace to the PRD or scaffold.
>
> ## Boot verification
>
> ```
> $ bash /tmp/boot_3371.sh          # cd implementation; PORT=18491 bash start.sh
> up (HTTP 401)                     # GET /nonprofits/organizations, no headers
> create HTTP 201
> before reboot total_count = 1
> up (HTTP 401)
> after  reboot total_count = 0     # fresh process wipes every byte of state
> ```
> `start.sh` reads `$PORT`, `exec`s `python3 app.py` in the foreground, `app.py` binds `0.0.0.0`. Reboot isolation confirmed: an org created before the restart is gone after it. No seeding anywhere.
>
> ## How it was tested
>
> Four throwaway smoke suites (in `/tmp`, not in the deliverable) exercising ~150 assertions: envelope shapes, auth/role/404 ladders, the 691202 per-field-rounding worked example, CONFLICT exclusion, supersession + void-restore, extraction-failure, all seal fee tiers (PLATINUM 32 days late = 250000), suspension at 3 open corrections, partial-accept asymmetry, merge grant re-pointing + cycle detection, license quota/overlap/expiry, prospect ranking, and filters. All four ended `FAILURES: 0`. No stray processes left (only self-started PIDs were killed).
>
> Three real bugs were caught and fixed this way: `Decimal`+`float` in mean confidence; normalize never setting the filing to `NORMALIZED`; and a clock-lapsed seal not incrementing `renewal_attempt_count` on a rejected renewal.
>
> ## PRD-vs-SCAFFOLD disagreements resolved (PRD followed in every case)
>
> 1. **`ERR_NO_EXTRACTED_FIELDS` status** — PRD §3.4/§5 and the scaffold's error catalog say 422; the scaffold's validations rung 7 files it under a 409 rung. Used **422**.
> 2. **Normalize on a zero-field filing** — §2.10 puts that error at rung 7, after the state rung, but no zero-field state has a declared normalize transition, so the documented error would be unreachable. I check the field-count gate *before* the state gate, so `RECEIVED`/`EXTRACTION_FAILED` + normalize → 422 as the catalog documents, while wrong-state filings that do have fields still get 409.
> 3. **Seal award gate order** — §3.7's explicit "fixed order" (ACTIVE→403, live seal→409, floor→422) vs §2.10 rung 11, which lists the 422 floor first. Followed **§3.7**.
> 4. **Usage-event gate order** — §3.9 narrates 400 → 409 (term) → 402 (quota); §2.10 rungs 4/8/10 and the scaffold's priorities (8 quota, 10 temporal) put quota before the window. Followed the **precedence ladder**: 400 → 402 → 409.
> 5. **`PATCH /organizations/{id}` `expected_organization_version`** — listed as required in the scaffold's input list, but §2.9 says only two endpoints are OCC-guarded and "no other write is refused for staleness". Accepted but **not enforced** (optional, ignored).
> 6. **Renewing a clock-lapsed seal** — §2.4 says it "is treated as such by any rule that inspects it" and §3.7 says the attempt counter increments on every attempt, so a lapsed seal renews to `ERR_SEAL_LAPSED` (409) with the counter bumped, rather than `ERR_INVALID_STATE`.
> 7. **DataConsumer grant ownership** — §2.1 compares `funder_organization_id` to `X-User-ID`; I accept either the funder or the path recipient org, so the documented "record a grant made to a recipient" flow works while an unrelated org still gets 403.
>
> One further note: the PRD's `disclosure_pct` prose examples (0.9000 / 0.8500) are not derivable from its own weights — all six dimensions at 1.0 sum to 1.0000. I implemented the stated weights and dimension rules, which are the mechanical contract, rather than the prose figures.

Orchestrator verification (independent of the hand-back):
- File inventory matches: 20 files, all non-empty; `python3 -m py_compile *.py` → all compile clean. `start.sh` reads `$PORT`, `exec`s `python3 app.py` in the foreground, binds `0.0.0.0`, and gates `pip install` behind an `import flask` check (deliberate — the 8-round sweep reboots the server concurrently).
- Independent boot: server launched on a self-chosen free port and answered `POST /nonprofits/organizations` → 201 with the correct `{data, meta, response_type}` envelope. (First attempt collided with another pipeline's server on a fixed port and returned a foreign 404 — that was my invocation error, not the implementation's; no other process was touched.)
- **Live probe confirmed one real implementation bug** (Step 7 scope): `POST /filings/{id}/normalize` against a filing in `EXTRACTION_FAILED` with zero `ExtractedField` rows returns **422 `ERR_NO_EXTRACTED_FIELDS`**, whereas the design index asserts **409 `ERR_INVALID_STATE`** — the impl applies the field-count gate *before* the state gate, inverting the PRD §2.10 ladder (rung 5 state outranks rung 7 constraint). The subagent flagged this as disagreement #2 and chose the reading that makes the constraint reachable; the queue-A instance `normalize_on_failed_filing_prefers_state_over_zero_field_constraint` exists precisely to assert the opposite. Left for Step 7 to adjudicate against PRD §2.10.
- **Investigated the `disclosure_pct` note and found it is NOT a defect.** The PRD's weights (PROGRAMS .15, FINANCES .30, LEADERSHIP .20, DEMOGRAPHICS .15, MISSION .10, GOVERNANCE .10) do sum to 1.00, but the difficulty instance's organization has all three leadership rows at `is_officer: false, is_independent: false`, so GOVERNANCE scores **0.0**, giving 0.15+0.30+0.20+0.15+0.10+0.00 = **0.9000** exactly; dropping DEMOGRAPHICS to its 0.5 rung then yields **0.8250** exactly. Both headline literals are reproduced by the stated weights, so the implementation's choice is correct and the PRD's prose sentence is merely loosely worded. No action needed.

## Step 7: Run Tests and Iterate — 2026-10-01T13:09:34.238Z

Subagent (diagnostic/fix loop) returned, verbatim:

> Clean 8-round parallel sweep — every round `89/89 passed`, `0 failed`, `0 errors`, `0 skipped`. Results written to `workspace/implementation/results.{1..8}.json`.
>
> ## Iterations run
> 3 sweeps. Sweep 1: 14 failing tests, deterministic in all 8 rounds. Sweep 2: 1 remaining failure (a second assertion in a test that had been masked by an earlier failing one). Sweep 3: all 8 rounds green.
>
> ## Tests deleted (1)
> - `test_suite/test_07_identity_resolution.py::test_dissolution_case_carrying_a_surviving_organization_returns_identity_case_invalid` — **non-unique derivability**. PRD §3.8 states the field-combination rule in the *case-creation* paragraph ("A `DISSOLUTION` requires `surviving_organization_id` to be null. … Any combination that violates these rules is refused with `ERR_IDENTITY_CASE_INVALID`"), so a faithful PRD-only implementation may refuse the create — making the test's setup (create must return 201, refusal only at finalize) unbuildable. The scaffold-only rule was the precondition on `state_machines.IdentityResolutionCase.OPEN_to_FINALIZED`. The test's own docstring quoted the creation sentence it then required to be ignored.
>
> ## Fixes applied to `test_helpers/`
> - `assertions.py` — added `assert_same_instant()`: compares clock-derived dates by instant. PRD pins the three-fractional-digit serialization only for `created_at`/`updated_at` (§2.5); it fixes `expires_on = awarded_on + 365 days` (§3.7) but never its rendering, so exact-string equality on `.000Z` vs `Z` was asserting a format the PRD never states.
> - `assertions.py` — added `prospect_organization_id()`: PRD §3.9 names only `match_score` and `historical_giving_cents` on a prospect row, never the candidate's identifier field; the helper resolves either `organization_id` or the organization's own `id` (§2.5).
>
> ## Fixes applied to `test_suite/`
> - `test_05_transparency_seals.py` (4 tests) — replaced exact-string `expires_on` / `renewal_window_opens_on` comparisons with `assert_same_instant`, keeping the full 365-day / −60-day arithmetic assertion.
> - `test_05` `test_demographic_replacement_revokes_the_platinum_seal` — PATCH-response version `before + 1` → `before + 2`: §2.11 makes reconciliation immediate, so the response already carries the patch bump plus the §3.7 revocation bump (matches the design index's own `+2`).
> - `test_02` `test_filing_create_checks_body_foreign_keys_before_form_version_membership` — unknown-org request now uses `make_admin_headers()`. An `OrganizationUser` naming a foreign `organization_id` is refused at §2.10 rung 2 (ownership), which pre-empts the body-identifier-resolution ordering the test exists to check.
> - `test_04_correction_requests.py` (2 tests) — self-CLAIM / self-ACCEPT attempts now use `make_verifier_headers(org["id"])`. §3.6 says "the `PlatformVerifier` drives the first five decisions", so an `OrganizationUser` is refused at rung 2 before the rung-6 segregation-of-duties gate ever runs.
> - `test_09` `test_grant_rematch_flips_ambiguous_to_matched_once_the_ein_is_supplied` — expected score 90 → 100, plus assertions on `subject_code == "B82"` and `taxonomy_source == "AUTO_CODED"`. §3.9 requires the matched grant to be auto-coded from the recipient's `ntee_code` and the score recomputed; the test had omitted that sentence.
> - `test_09` `test_funder_prospects_rank_by_score_then_history_then_created_at` — `p["organization_id"]` → `prospect_organization_id(p)`, preserving the full three-key ranking assertion.
>
> ## Fixes applied to `implementation/`
> - `routes_filing.py` `normalize_filing` — state gate moved ahead of the org-standing and zero-field gates, per the §2.10 override ladder (state rung 5 → safety rung 6 → constraint rung 7). Normalizing a `RECEIVED`/`EXTRACTION_FAILED` filing now returns 409 `ERR_INVALID_STATE` instead of 422 `ERR_NO_EXTRACTED_FIELDS`. (2 tests)
> - `routes_lists.py` `create_license` — `overage_records` is 0 at creation, not `max(0, projected − included)`. §3.9: "The license opens in `DRAFT` status with `records_accessed` 0, `overage_records` 0 and `overage_flag` false"; overage is a read-time figure derived from `records_accessed`. (1 test)
> - `routes_seal.py` `renew_seal` — a seal that has already left `ACTIVE` now reports `ERR_INVALID_STATE` (state rung 5 outranks the temporal rung 10); `ERR_SEAL_LAPSED` stays on the tier-3 refusal of a still-`ACTIVE` seal, and every attempt still increments `renewal_attempt_count`. (1 test, surfaced only after the date-format assertion stopped masking it)
>
> No `skip`/`xfail` anywhere; no seeding or on-disk persistence in `implementation/` (in-memory store only, wiped by each `start.sh` reboot).

Orchestrator verification (independent of the hand-back):
- All 8 `results.{1..8}.json` present, each `passed=89 total=89 failed=0 errors=0 skipped=0`.
- `pytest --collect-only` → 89 tests (90 − the 1 deleted), 0 collection errors.
- Newest source-file mtime across `implementation/`, `test_suite/`, `test_helpers/` (excluding `__pycache__`) is `routes_seal.py` at **13:04:59**, i.e. before the sweep wrote its results at **13:08** — no post-sweep writes, so the green sweep covers the code as it stands.
- Deleted test name confirmed absent from `test_suite/`; no `skip`/`xfail` markers anywhere; `implementation/` contains no seeding (only comments asserting the absence) and no disk persistence (the single `app.json.sort_keys` hit is a Flask JSON-config line).
- The normalize-precedence bug I had independently reproduced before Step 7 is the one Step 7 fixed first in `routes_filing.py` — the fix direction (state rung 5 outranks constraint rung 7) matches my own reading of PRD §2.10.

Fix-mix note for Step 8: test-side edits (6 `test_suite/` + 2 `test_helpers/`) outnumber `implementation/` edits (3). A green sweep proves tests match code, not PRD-vs-code, so Step 8's focus list should treat the two `assertions.py` helper additions (`assert_same_instant`, `prospect_organization_id`) and the §3.9 auto-coding sentence as PRD-silence sites.

## Step 8: Finalize PRD — 2026-10-01T13:21:32.790Z

Skip condition did not apply (Step 7 ran 3 sweeps: 1 deletion, 6 `test_suite/` fixes, 2 `test_helpers/` fixes, 3 `implementation/` fixes), so the finalizer ran. Subagent returned, verbatim:

> PRD_FINALIZED.md is written. Summary below.
>
> ## Size
> - `PRD.md`: 435 lines / 89,069 bytes → `PRD_FINALIZED.md`: 435 lines / 90,433 bytes. Line delta **0 (0.0%)**, byte delta **+1,364 (+1.53%)**. 4 edits, 8 changed lines; no sections added, removed, or reordered.
>
> ## Changes (one per step_7_diff item that revealed PRD silence or a PRD/impl conflict)
>
> - **§3.5 (Normalization)** — *insert* — Normalization is declared only for a filing in `EXTRACTED` or `DISPUTED`; any other status (`RECEIVED`, `EXTRACTION_FAILED`, `NORMALIZED`, `SUPERSEDED`, `VOIDED`) → `ERR_INVALID_STATE` (409), and that state gate outranks the zero-field and good-standing preconditions. Pins the impl's gate order against §3.5's old literal reading, which made a zero-field `RECEIVED` filing return `ERR_NO_EXTRACTED_FIELDS`. — `implementation/routes_filing.py:266-282` (state gate), `:271-276` (org gate), `:277-282` (field gate); `implementation/store.py:11-24` (status set).
> - **§3.7 (Seal award)** — *insert* — `awarded_on`/`expires_on`/`renewal_window_opens_on` are rendered as ISO 8601 UTC with three fractional digits (same rendering as `created_at`/`updated_at`), and the org's mirrored `seal_expires_on` carries the seal's `expires_on` string. Closes the PRD's silence on the rendering of clock-derived dates. — `implementation/routes_seal.py:60-62` (award), `:124-127` (renew), `implementation/clock.py:36-39` (`fmt_dt`), `implementation/svc.py:406-414` (`recompute_seal_mirror`).
> - **§3.7 (Seal renewal)** — *revise* — Renewal is declared only for a seal still `ACTIVE`; a renewal against a non-`ACTIVE` seal → `ERR_INVALID_STATE` (409), state rung outranking the temporal rung (so it holds at 91+ days late), and that refusal still increments `renewal_attempt_count` by 1 (version/`updated_at` move) while leaving `status` and the owning organization untouched. The two existing gates are re-scoped to "a seal that is still `ACTIVE`". — `implementation/routes_seal.py:88-99` (state gate + counter + touch), `:101-106` (org gate), `:111-120` (tier-3 `ERR_SEAL_LAPSED`).
> - **§3.9 (Prospect research)** — *revise* — Each prospect row is the candidate organization's own profile object (the same representation `GET /nonprofits/organizations/{id}` returns, identified by the organization's `id`) augmented with `match_score` and `historical_giving_cents`. Closes the PRD's silence on the prospect row's shape/identifier. — `implementation/routes_grant.py:164-167`, `implementation/svc.py:19-51` (`ser_organization`, shared with `routes_org.py:123`).
>
> ## Per-edit pre-edit search log
>
> **Edit 1 — §3.5 normalize state gate.** (a) Subject: normalize's declared states and gate precedence. (b) Enumerated: `routes_filing.py` in full (state setters: create→`RECEIVED`, extract→`EXTRACTED`/`EXTRACTION_FAILED`, normalize→`NORMALIZED`, void→`VOIDED`, supersede→`SUPERSEDED`, correction accept→`DISPUTED`); `svc.require_transition`; §2.10 ladder rungs 5/6/7; tests `test_02:99-119`, `test_12:19-46,74-135`. (c) Wording kept non-committal about the relative order of the org-standing and zero-field gates (that pair is unobservable — both require a state where fields exist) so no path is mis-described; only the state gate's precedence is asserted, and the status enumeration is exactly the complement of `{EXTRACTED, DISPUTED}` in the impl.
>
> **Edit 2 — §3.7 seal date rendering.** (a) Subject: serialization of the seal's clock-derived date fields and the org mirror. (b) Enumerated: `routes_seal.py` award/renew; `svc.recompute_seal_mirror`, `svc.lapse_seal`, `svc.revoke_seal`, `svc.revoke_active_seals` (all set the mirror to the seal string or null); `clock.fmt_dt`; `svc.ser_seal`; helpers `assert_same_instant` usages (test_05 lines 45, 183/185, 235, 264/266 — only seal `expires_on`/`renewal_window_opens_on`). (c) Scoped the claim to those three fields plus the mirror; deliberately did **not** make a blanket claim about `coverage_start`/`service_start`/`dissolution_date`/`term_start` (echoed as supplied via `webutil.as_datetime`, `routes_filing.py:133-134`, `routes_org.py:361-362`, `routes_identity.py:64`) or about `requested_at`/`decided_at`/`occurred_at`/`finalized_at` (out of the diff's scope).
>
> **Edit 3 — §3.7 renewal state gate.** (a) Subject: renewal's precondition on the seal's own status, the temporal gate's scope, and `renewal_attempt_count`. (b) Enumerated: `routes_seal.py:75-130` (the only renewal path, including the org-standing path at `:101-106` which does **not** increment, and the tier-3 path at `:111-120` which does), `svc.apply_clock_effects:570-596` (automatic lapse does not increment), `calc.seal_renewal_fee_cents`/`late_tier`; tests `test_05:33-70` (first attempt accepts either error and counter ∈ {0,1}; second attempt must be `ERR_INVALID_STATE`). (c) Scoped the counter claim to the state-gate refusal only, so the pre-existing "every attempt" sentence and the non-incrementing org-standing path are not contradicted; the reachability check (an `ACTIVE` seal always belongs to an `ACTIVE` organization — award requires `ACTIVE`, and suspension/merge/dissolution all revoke `ACTIVE` seals) confirmed the org gate is unreachable, so no softening of the existing universal sentence was needed.
>
> **Edit 4 — §3.9 prospect row shape.** (a) Subject: prospect row contents / candidate identifier field. (b) Enumerated: `routes_grant.funder_research_prospects:151-188` (payload, sort keys, pagination), `svc.ser_organization` (shared by `routes_org.create/patch/verify/list/get`), `calc.prospect_score`/`historical_giving_cents`; helper `prospect_organization_id` and test_09:78. (c) Wording anchored the row to the read endpoint's representation rather than enumerating fields, which keeps it true for every serializer path and does not conflict with the same paragraph's "no identifier value ever participates in the ranking" (ranking key remains `created_at`).
>
> ## Items examined and deliberately left verbatim (no PRD edit)
> - test_07 deleted test: PRD §3.8 already states the field-combination rule in the case-creation paragraph, and the impl enforces it at create *and* finalize (`routes_identity.py:75`, `:133`) — impl matches PRD.
> - test_05 `+2` version: determined by §3.1 (patch +1) + §3.7 (revocation +1) + §2.11 (immediate, visible in response); impl does both bumps (`routes_org.py:173-174` + `svc.py:474-479`).
> - test_02 admin headers, test_04 verifier headers, test_09 score 100/auto-code: pure fixture bugs — PRD already determines the behavior (`routes_filing.py:55-62`; `routes_correction.py:128-140`; `routes_grant.py:98-105`).
> - `routes_lists.create_license` `overage_records` 0: §3.9 already states it verbatim; impl now matches (`routes_lists.py:119-124`).
> - Sweep-hygiene notes (no seeding, no skip/xfail, in-memory store): not a listed fix; PRD implies entities enter only through declared endpoints, so no edit.

Orchestrator verification: `workspace/PRD_FINALIZED.md` present, 435 lines / 90,433 B, ends on a complete table row (no truncation); line count unchanged from `PRD.md` (inline inserts/revisions only, no sections added). Implementation and test source mtimes are unchanged by this step (newest `routes_seal.py` 13:04:59, newest test 13:00:19) — Step 8 wrote only `PRD_FINALIZED.md`, so the Step 7 sweep remains valid.

## Step 9: Complete PRD — 2026-10-01T13:46:03.732Z

Subagent (full PRD-vs-implementation scan) returned, verbatim:

> `PRD_COMPLETED.md` is written at `/home/ubuntu/github/CodingPRD/tasks/task_3371_nonprofit_data_transparency_profiles_filing_data_extraction/workspace/PRD_COMPLETED.md`.
>
> ## Size
>
> | | lines | chars |
> |---|---|---|
> | `PRD_FINALIZED.md` (source) | 435 | 90,433 |
> | `PRD_COMPLETED.md` | 439 | 103,619 |
> | delta | +4 | **+13,186 (+14.6%)** |
>
> 41 changed regions, all inside existing paragraphs; heading set and both tables are byte-identical to the source. Only `PRD_COMPLETED.md` was edited.
>
> ## Counts
>
> - **28 ambiguity-pins** (PRD silent → inline prose pinning impl)
> - **17 mismatch-revisions** (PRD said something else → revised to impl)
>
> ## Change list
>
> 1. §2.1 — revise — mismatch — ownership is enforced only on the 11 write endpoints that declare it; reads are open to every authorized role; body-declared org ids are compared before resolution, FK-based ones after — `auth.py:62-72`, `routes_filing.py:57-62`, `routes_grant.py:37-42`, `routes_license.py:54`
> 2. §2.3 — insert — ambiguity — out-of-range `limit`/`offset` are clamped (1/100/0), non-integers fall back to defaults — `response.py:76-98`
> 3. §2.3 — insert — ambiguity — full per-collection filter set, exact-equality matching, numeric filters match nothing on non-integers, bool filter accepts `true/1/yes`, empty param = absent, undeclared params ignored — `listing.py:14-48`, `routes_org.py:105-111,298,381,396`, `routes_lists.py:27,38,51,61-65,75-81,139`, `routes_filing.py:366-369`
> 4. §2.4 — revise — ambiguity — clock response echoes the exact supplied string; any instant accepted, unparseable → 400 — `routes_identity.py:198-205`
> 5. §2.5 — revise — mismatch — the version/`updated_at` pairing has one exception (partial accept) — `routes_correction.py:220-222`
> 6. §2.5 — insert — ambiguity — client-supplied instants are stored/returned verbatim, not re-rendered — `routes_filing.py:132-133`, `routes_org.py:91,361-362`, `routes_lists.py:114-115`, `routes_identity.py:82`
> 7. §2.6 — revise — mismatch — auto-suspension fires only from `ACTIVE`; `DRAFT`/`SUSPENDED`/`MERGED`/`DISSOLVED` are left alone — `svc.py:531-540`
> 8. §2.9 — revise — mismatch — the profile patch accepts `expected_organization_version` but never compares it — `routes_org.py:36-39,126-175`
> 9. §2.10 rung 2 — revise — ambiguity — the ownership arm applies only where declared and only after resolution — `routes_org.py:130-131`, `routes_correction.py:47-49`
> 10. §2.10 rung 4 — revise — mismatch — empty-input-list endpoints reject any body field; non-object bodies → 400; body identifiers resolve after shape checks; the `projected_annual_records` minimum is deferred — `webutil.py:14-30`, `routes_license.py:100-103`
> 11. §2.10 rung 7 — revise — mismatch — `ERR_NO_EXTRACTED_FIELDS` is 422 (not 409); `ERR_IDENTITY_CASE_INVALID` added — `errors.py:101,107`
> 12. §2.10 rung 11 — revise — mismatch — enumeration order swapped to single-active-seal then disclosure floor — `routes_seal.py:39-52`
> 13. §2.10 closing — insert — ambiguity — 412 rungs sit between shape and business constraints; `ERR_FIELD_NOT_CORRECTABLE` after 412; license activation's deviation — `routes_filing.py:75-107`, `routes_correction.py:58-69`, `routes_license.py:59-103`
> 14. §2.11 — revise — mismatch — version/`updated_at` move only where an operation declares it (program/leadership creation, grants, license expiry re-derive in place) — `svc.py:349-403,417-428`
> 15. §2.11 — revise — mismatch — profile-floor cascade runs only on normalize/void/decide; disclosure-floor cascade runs on every disclosure re-derivation — `svc.py:491-514`, `routes_filing.py:311-312,354-355`, `routes_correction.py:255-256`, `routes_org.py:173`
> 16. §2.11 — insert — ambiguity — definitions of `distinct_funder_count` and `active_license_count` — `svc.py:387-403`
> 17. §3.1 — insert — ambiguity — `ein`/`state_code` get no format validation beyond non-empty + uniqueness — `routes_org.py:49-52`
> 18. §3.1 — revise — mismatch — patch: version field inert, `null` clears, empty strings accepted, +2 version when the cascade also fires — `routes_org.py:126-175`
> 19. §3.1 — revise — ambiguity — demographic records also default `disclosure_level` to `RESTRICTED` — `routes_org.py:156-158`
> 20. §3.1 — insert — ambiguity — `demographic_records: null` ignored; replacement is destructive-then-partial — `routes_org.py:146-168`
> 21. §3.2 — revise — mismatch — score re-derivation list; create-filing re-derives only revenue aggregates; program/leadership creation qualifier — `routes_filing.py:143-144`
> 22. §3.3 — insert — ambiguity — verify on `MERGED`/`DISSOLVED` → 409 before any gate — `routes_org.py:189-194`
> 23. §3.3 — insert — ambiguity — un-suspend still validates shape but skips duties/step gates — `routes_org.py:184-205`
> 24. §3.4 — insert — ambiguity — extraction declared only for `RECEIVED`/`EXTRACTION_FAILED` — `routes_filing.py:192-196`
> 25. §3.4 — insert — ambiguity — `raw_value` may be a JSON number; strings tolerate commas/`$`; bool/null rejected — `routes_filing.py:163-165`, `calc.py:50-64`
> 26. §3.4 — insert — ambiguity — confidence mean rounded half up to 1 dp — `calc.py:82-89`
> 27. §3.5 — insert — ambiguity — unreadable `raw_value` stays `PENDING`, contributes nothing — `routes_filing.py:295-297`
> 28. §3.5 — revise — mismatch — `SUPERSEDED` is voidable; deeper pass also keyed on the restored revision's status — `routes_filing.py:326-356`
> 29. §3.6 — insert — ambiguity — staleness (412) precedes `ERR_FIELD_NOT_CORRECTABLE` (422) — `routes_correction.py:58-69`
> 30. §3.6 — insert — ambiguity — `review_note`/`corrected_value` type-checked only on the branches requiring them — `routes_correction.py:124-148`
> 31. §3.6 — insert — ambiguity — unconvertible accepted `requested_value` → 400 — `routes_correction.py:105-112,200-202`
> 32. §3.6 — revise — mismatch — partial accept also skips `updated_at` and leaves `is_verified` untouched — `routes_correction.py:217-232`
> 33. §3.7 — revise — mismatch — base `SILVER` is reachable above 0.75 when verified filings are too few — `calc.py:459-464`
> 34. §3.7 — insert — ambiguity — renewal refreshes the org's `seal_expires_on` without a version bump — `routes_seal.py:129`
> 35. §3.8 — revise — mismatch — cycle refusal is `ERR_MERGE_CYCLE_DETECTED`; status is tested before the combination rules — `routes_identity.py:118-138`
> 36. §3.8 — insert — ambiguity — combination rules re-validated at finalization against current state — `routes_identity.py:133`
> 37. §3.9 — insert — ambiguity — `final_annual_fee_cents` opens at base; creation does not compare `term_start`/`term_end` — `routes_lists.py:109-126`
> 38. §3.9 — revise — mismatch — activation order: standing → permitted-use → term overlap → projection minimum — `routes_license.py:59-103`
> 39. §3.9 — revise — mismatch — usage gates are shape → state(409) → quota(402) → window(409) — `routes_license.py:135-161`
> 40. §3.9 — insert — ambiguity — event of another license → 404; non-`POSTED` → 409 — `routes_license.py:198-206`
> 41. §3.9 — insert — ambiguity — a `DataConsumer` may name only itself or the recipient as funder — `routes_grant.py:36-42`
> 42. §3.9 — insert — ambiguity — trailing suffix tokens dropped repeatedly; exact-name match needs non-empty — `calc.py:522-557`
> 43. §3.9 — insert — ambiguity — `mean_grant_amount_cents` rounded to whole cents; envelope `response_type` is `object` — `routes_grant.py:180-188`
> 44. §3.9 — insert — ambiguity — ranking ties keep creation order — `routes_grant.py:169-173`
> 45. §5 — insert — ambiguity — `ERR_NOT_FOUND` (404) and `ERR_METHOD_NOT_ALLOWED` (405) documented — `app.py:55-62`, `errors.py:73-74,111-112`
>
> No new sections, no new endpoints, no invented behavior; every pin is traceable to a line in `implementation/`.

Orchestrator verification (independent of the hand-back):
- `workspace/PRD_COMPLETED.md` present, 439 lines / 103,619 B, ends on a complete table row (no truncation).
- Implementation and test source mtimes unchanged by this step (newest `routes_seal.py` 13:04:59, newest test 13:00:19) — Step 9 wrote only `PRD_COMPLETED.md`.
- Spot-checked two of the 17 mismatch-revisions against source: claim #8 holds (`expected_organization_version` appears in `routes_org.py` only inside the accepted-input list at line 37, with no comparison anywhere in the file), and claim #11 holds (`errors.py:107` maps `ERR_NO_EXTRACTED_FIELDS` to 422).
- **The 17 mismatch-revisions are the expected consequence of the Step 7 fix-mix note, not a regression**: Step 7's green sweep proved tests match code, not PRD-vs-code, so behaviors the suite never asserted kept the implementation's reading while PRD prose said something else. Step 9's scan is exactly the mechanism that surfaces them. No `implementation/` change was made or warranted — the benchmark contract makes PRD_COMPLETED.md the aligned artifact.

## Final verification sweep (orchestrator-run) — 2026-10-01T13:49:03.904Z

After Step 9, re-ran the full 8-round parallel stability sweep myself (deleting the prior `results.*.json` first, so the evidence on disk is from this run), against the frozen artifact state:

```
round 1..8: passed=89 total=89 failed=0 errors=0 skipped=0
```

All 8 rounds green. `implementation/` and `test_suite/` were not modified after the sweep. No leftover server processes from this pipeline (the one probe server I started was killed by its own PID; the probe port has no listener).

Final artifact inventory: `SCAFFOLD.yaml`, `SCAFFOLD_DIFFICULTY_DESIGN.yaml`, `SCAFFOLD_CORNER_DESIGN.yaml`, `worklog.md`, `test_helpers/` (10 files), `test_suite/` (13 files, 89 tests), `workspace/{INSTRUCTION.md, PRD.md, PRD_FINALIZED.md, PRD_COMPLETED.md}`, `workspace/implementation/` (20 files incl. `start.sh` and `results.{1..8}.json`).
