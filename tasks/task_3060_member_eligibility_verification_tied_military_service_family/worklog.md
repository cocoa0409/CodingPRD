# Worklog — task_3060_member_eligibility_verification_tied_military_service_family

## Step 1: Create task directory — 2026-09-29T18:45:55.000Z

Verified pre-allocated task directory `./tasks/task_3060_member_eligibility_verification_tied_military_service_family/` exists with `workspace/` inside (per command args, index was not recomputed).

## Step 2: Generate scaffold — 2026-09-29T19:30:49.000Z

Done. All three scaffold artifacts are written and lint-clean.

**Files written** (under `/home/ubuntu/github/CodingPRD/tasks/task_3060_member_eligibility_verification_tied_military_service_family/`):
- `SCAFFOLD.yaml` — §1.0–§1.7 (no design keys)
- `SCAFFOLD_DIFFICULTY_DESIGN.yaml` — single top-level key `scaffold_difficulty_design`
- `SCAFFOLD_CORNER_DESIGN.yaml` — single top-level key `scaffold_corner_design`

**Counts:**
- Entities: 11 (EligibilityCase, ServiceRecord, EvidenceDocument, Member, Household, AddressAssignment, DeploymentOrder, ProtectionClaim, ProductOffering, ProductEntitlement, SurvivorSupportCase)
- State machines: 7 (incl. Member parallel status × deployment_posture dimensions, EligibilityCase MORE_INFO_REQUIRED revision loop)
- Calculations: 6 (eligibility_category_assignment, scra_rate_relief, survivor_continuance, household_aggregate_recompute, product_availability_matrix, protection_relief_cap)
- Validations: 31 priority rows; Errors: 30; Roles: 6 (segregation-of-duties model: reconstructing officer cannot approve the same case; Benefits vs Verification separation)
- Endpoints: 59 (incl. `POST /membership/_clock/set_current_utc` with the mandatory 2026-09-01T00:00:00Z default, and OCC-guarded link-household / deployment-orders with `expected_member_version`)
- Concurrency rules: 2 (both true-race OCC on Member.version)
- §1.8: 9 rule_ids × 2 instances = 18; §1.9: 40 instances across all nine claim-extraction-guide sections; zero name collisions across the union; every `grounds` reference verified to resolve.

**Lint verdict (verbatim):** `VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.` (578 calls scanned, 0 violations; one caveat — the lint's sub-resource FK check hardcodes `{id}` as the path placeholder, so FK reachability for AddressAssignment/DeploymentOrder is satisfied via declared filtered-list GETs `/membership/addresses?member_id=` and `/membership/deployment-orders?member_id=` alongside the existing nested list endpoints.)

**Difficulty levers** (beyond expert band): dual-variant calcs on two different domains (survivor continuance spouse/child window, SCRA end-dated vs open-ended proration), pinned floor-per-period-then-sum rounding with a discriminating fixture (106 cents/month → 90 vs 91), pinned evaluation-order cap check (netting before cap comparison), depth-3 revocation cascade (member → entitlement closure → household aggregate) vs grant-triggered transfer cascade, two priority-conflict pairs (state-vs-safety 5/8, constraint-vs-fiscal 17/18), lineage-depth boundary at MAX_LINEAGE_DEPTH=3 (inclusive), empty-set boundaries on evidence/record presence, half-open vs inclusive overlap semantics on two different resources, grandfathering stickiness across reinstate, and clock-driven deployment auto-activation.

## Step 3: Copy INSTRUCTION.md — 2026-09-29T19:30:49.000Z

Copied `./INSTRUCTION.md` → `./tasks/task_3060_member_eligibility_verification_tied_military_service_family/workspace/INSTRUCTION.md`.

## Step 4: Generate PRD — 2026-09-29T19:39:55.000Z

All mechanical audits pass. Final Contract 2 rule-coverage walkthrough against the scaffold:

**Contract 1 — Field-Name Coverage: PASS**
- `entities[].fields`: 78 required, 78 present, 0 missing
- `endpoints[].input` (request bodies + query filters incl. `limit`/`offset`, `date_of_death`, `loss_note`, `to_iso8601`, `transfer_household_id`, `expected_member_version`): 64 required, 64 present, 0 missing
- All 6 role names, all 21 state values (after fixing `CANCELLED`), and all 79 enum literals present verbatim in backticks

**Contract 2 — Rule Coverage: PASS**
- Validations with priority: 30 checked, all expressed in §2.7's explicit ordered narrative (auth → role/ownership → existence → well-formedness → state → duplicates → SoD → interval overlaps → FK resolution → lineage depth → lineage proof → derivation → product gate → household → SCRA → relief cap → OCC → sponsor/beneficiary activeness → evidence family → deployment temporal → no-relief → reinstatement evidence → duty-station conflict)
- OCC rules: 2 checked, 2 expressed — `link-household` and `deployment-orders` both named with `expected_member_version` + `ERR_STALE_VERSION` (412), stale-view framing, no concurrency/race wording
- State-machine transitions: all 17 transitions across 7 machines expressed with preconditions paired to error IDs and side effects (grandfather cascade, descendant one-generation suspension, survivor auto-create with spouse/child fallback, entitlement re-key/close split on grant, household transfer with dual aggregate recompute)
- Calculations: 6 checked, 6 expressed in precise prose — category assignment (incl. extended lineage variant), scra_rate_relief (per-period floor-then-sum, 600 bps cap, 60/12 period constants, proration variant), survivor_continuance (50000-cent deductible, 0.20/3mo vs 0.30/2mo shares, floor-then-months order), household aggregate (pinned member-matrices-first order, ACTIVE/SUSPENDED inclusion), 24-facet product matrix (4 groups × 6 facets, {0,6,12,18,24} counts, suspended variant), protection_relief_cap (4-step pinned order, `min(bank_offset, gross−1)` netting, empty-entitlement exemption)
- All 30 error IDs matched to trigger conditions in §2/§3 prose
- Endpoint side effects (version increments on OCC writes, `REGISTERED` auto-activation on clock advance, `GRANDFATHERED_RETIRE` cascade) all covered
- Sibling branches symmetric (DENY / REQUEST_MORE_INFO / APPROVE; the three closure reasons; the three claim types)

**Contract 3 — §3 Path Purity: PASS** — 420 backtick tokens scanned in §3, 0 path tokens, 0 bare HTTP methods, 0 method+path combos.

**Output:** `/home/ubuntu/github/CodingPRD/tasks/task_3060_member_eligibility_verification_tied_military_service_family/workspace/PRD.md` — 290 lines.

Structure: §1 (2 paragraphs), §2.1–2.10 (RBAC with per-role identity semantics, verbatim §2.2 envelope, pagination, common fields + member number, logical clock pinned at `2026-09-01T00:00:00Z`, segregation of duties, validation ordering, OCC, household aggregation discipline, cent precision), §3.1–3.11 organized by workflow (case intake → evidence → adjudication → reconstruction → deployment/posture → protection claims + relief arithmetic → product catalog/matrix → eligibility loss → death/survivor → households → addresses), §4 four-column endpoint table (58 rows), §5 two-column error catalogue (30 rows). The two forbidden difficulty-design files were not read or referenced.

## Step 5: Generate unit tests — 2026-09-29T20:00:00.000Z

Generated complete test infrastructure for `task_3060_member_eligibility_verification_tied_military_service_family`.

### Files written

`test_helpers/` (Stage 1):
- `types.py` — status/category enums, role enum, TypedDicts for all 11 entities
- `api_client.py` — `ApiClient(GenericApiClient)` with one method per PRD endpoint (~45 methods, `/membership` prefix)
- `api_errors.py` — all 30 PRD error IDs with the §5 HTTP status map, registered via `set_error_http_status_map`
- `constants.py` — MAX_LINEAGE_DEPTH 3, SCRA_CAP_BPS 600, OPEN_ENDED_PERIODS 12, survivor deductible/rates/months, facet groups
- `factories.py` — payload factories for all creatable entities (input fields only)
- `test_users.py` — opaque-role shared headers (officer-A/B/C for segregation-of-duties) + `make_member_headers` / `make_officer_headers` builders for the entity-backed Member role
- `fixtures.py` — composite builders: `approve_direct_member` / `approve_family_member` (full case→submit→reconstruction-by-A→decide-by-B pipeline), `setup_active_member_with_deployment`, `setup_member_spouse_survivor_case`, plus clock/order/claim/entitlement/household helpers and pytest fixtures
- `__init__.py` — barrel export

`test_suite/` (Stage 2): `conftest.py` + 11 test files (`test_01` eligibility case workflow, `test_02` family derivation/lineage, `test_03` member lifecycle, `test_04` deployment orders, `test_05` protection claims, `test_06` survivor support, `test_07` households, `test_08` addresses, `test_09` product catalog, `test_10` auth/roles/existence, `test_11` records/evidence/members).

### Coverage
- **Queue A (difficulty):** 18/18 instances covered with exactly 2 tests each (36 tests)
- **Queue B (corner):** all 40 non-stub instances covered with ≥1 test each (50 tests); the index contains no `excluded_because` stubs
- **Total: 86 tests**, all collected cleanly by pytest

### Instances skipped
None. Every non-stub instance passed the PRD-first two-condition filter. The two priority-pair instances (`state_beats_business_safety…`, `referential_beats_fiscal…`) were translatable because PRD §2.7 explicitly pins the validation priority order in prose.

### Stage 2 self-check results
- Tag audit: every test docstring ends with exactly one `Design:` line; all 86 tags resolve to real yaml instances; no untagged/dual-tagged tests (one cross-file duplicate test name was found and renamed during the audit)
- Verbatim citation check: every quoted PRD span greps verbatim against `workspace/PRD.md` (ellipsis-segment-aware); initial failures from trailing punctuation and line-wrap ellipses were fixed
- No `pytest.mark.skip` / `skipif` / `xfail` anywhere
- All files compile; `test_helpers` imports cleanly against the installed `prd_bench_local_runner` framework

One notable setup detail: approval requires verified service records, and the only reachable verification pathway for direct-service cases is the record-reconstruction endpoint (officer A) followed by a decide from a different officer (officer B) to satisfy segregation of duties — this pipeline is baked into the `approve_direct_member` fixture.

## Step 6: Generate implementation — 2026-09-29T20:28:01.000Z

Done. Summary:

## Files written

All under `/home/ubuntu/github/CodingPRD/tasks/task_3060_member_eligibility_verification_tied_military_service_family/workspace/implementation/`:

- `start.sh` — guarded launcher (`pip install` only when flask missing), `exec python3 app.py`, reads `PORT` (default 10000), binds `0.0.0.0`
- `requirements.txt` — `flask>=3.0`
- `app.py` — Flask entrypoint, blueprint registration, error handlers, request-level RLock
- `store.py` — in-memory tables, sequence lists, logical clock (pinned `2026-09-01T00:00:00Z`), member-number counter
- `errors.py`, `envelope.py`, `paginate.py`, `helpers.py`, `auth.py` — envelope helpers (`meta`/`response_type`/`data`, `error_id`/`message`, `limit`/`offset`/`total_count`/`has_more`), date/field validators, `X-User-ID`/`X-User-Role` extraction
- `domain.py` — product-availability matrix (4 groups × 6 facets, DEPLOYMENT gated on posture), household aggregate recompute (matrices-then-sum), entitlement cascades, serializers
- `routes_cases.py` — eligibility cases, service records, evidence, submit/decide/record-reconstruction, flat service-record/evidence reads
- `routes_members.py` — member reads, product-matrix, eligibility-loss (DOCUMENTATION_REVOKED → SUSPENDED with grandfathering; FRAUD_CONFIRMED → REVOKED with descendant cascade), reinstate, deceased with survivor-case auto-create, link/delink household with OCC
- `routes_addresses.py` — address CRUD + half-open overlap + retroactive duty-station conflict
- `routes_deployments.py` — deployment orders with auto-activation on POST and clock advance, inclusive overlap, complete/cancel with posture release
- `routes_claims.py` — protection claims, scra_rate_relief (per-period floor → sum, 600 bps cap, 12-period open-ended variant), protection_relief_cap, supersede cascade
- `routes_products.py` — product offerings CRUD + retire/category-change cascades, entitlement open/close with category gate
- `routes_households.py` — households (create with auto-link, dissolve precondition), survivor cases (grant waterfall with 50000-cent deductible, 0.20×3 spouse / 0.30×2 lineal, entitlement transfer + household move; close with mandatory resolution_note)
- `routes_clock.py` — `_clock/set_current_utc` with REGISTERED→ACTIVE auto-activation sweep

## Endpoint count

56 distinct declared endpoints implemented (Flask URL map reports 59 rules including HEAD/OPTIONS auto-routes). All entries from §1.5 and PRD §4 are covered.

## Boot smoke test

- Started via `PORT=31879 bash start.sh`, captured PID 484643
- `GET /membership/product-offerings` → HTTP 200 with correct envelope (`data: []`, pagination meta fields present)
- Killed exactly that PID via `kill $SERVER_PID`; server stopped cleanly
- Earlier end-to-end run (PID 475067, port 31878) exercised: case create → service record (`service_days=1825` computed) → evidence upload → submit → approve blocked by `ERR_SERVICE_RECORD_UNVERIFIED` → record-reconstruction → same officer blocked by `ERR_SEGREGATION_OF_DUTIES` → second officer approves → member minted with `member_number=0000000001`, `VETERAN_HONORABLE` → product matrix shows 6 facets AVAILABLE (BANKING) / DEPLOYMENT UNAVAILABLE → clock advance to 2026-10-01 succeeded

No seeding at startup; store boots empty; `start.sh` re-invocation is a no-op install and `exec`s a fresh Python process.

## Step 7: Run tests and iterate — 2026-09-29T20:43:53.000Z

All 8 rounds pass cleanly (85/85 each; total dropped from 86 to 85 due to the one deletion). Exiting with the summary.

## Summary

- **Iterations run:** 2 (initial sweep: 3 consistent failures in all 8 rounds; post-fix sweep: 85/85 in all 8 rounds).

- **Tests deleted (1):**
  - `test_retroactive_pcs_without_closing_prior_rejected` (test_suite/test_08_addresses.py) — **ERROR-PRECEDENCE SILENCE** collapse. The test posts a new `is_duty_station` address (2026-09-01) that *overlaps* the member's open duty interval (from 2026-01-01) and demands `ERR_DUTY_STATION_CONFLICT`. PRD §3.11's retroactive-PCS sentence covers only `effective_from` *earlier* than the current open duty interval (this request isn't), and PRD §2.9's priority sentence puts `ERR_ADDRESS_OVERLAP` before `ERR_DUTY_STATION_CONFLICT` ("Interval checks... precede foreign-key resolution... the duty-station conflict check... close[s] the order"), so a faithful implementation returns `ERR_ADDRESS_OVERLAP`. The relax-to-set exception cannot apply — `ERR_DUTY_STATION_CONFLICT` is unreachable for this request. The scaffold's own recipe (`duty_station_change_closes_prior_interval`) shares the flawed premise. The PRD-covered companion (`test_pcs_after_closing_prior_interval_accepted`) remains.

- **Fixes applied to `test_helpers/`:** none.

- **Fixes applied to `test_suite/` (2):**
  - `test_07_households.py::test_aggregate_counts_linked_active_and_suspended_only` — test bug in setup: added `requires_active_status=False` to the offering. With the PRD-stated default `true` (§3.7: "requires_active_status, defaulting to true"), PRD §3.7's suspended variant forces the cascade-suspended child's matrix to 0, so the asserted aggregate of 6 was only reachable on an implementation violating §3.7. The fix isolates the §2.9 input-set rule the test targets; the implementation was already faithful.
  - `test_09_product_catalog.py::test_matrix_reflects_category_gate` — removed non-derivable per-facet assertions (`matrix["facets"]["BANKING"] == "AVAILABLE"` treating each group as a single string). PRD §3.7 specifies a "24-facet availability matrix: four facet groups... of six facets each" without pinning the serialized facet representation, so a faithful implementation emitting six entries per group failed the test (unique-derivability collapse). Kept the PRD-derivable assertions: `available_facet_count == 6`, presence of the per-group `facets` detail, and the identity fields (`eligibility_category`, `status`, `deployment_posture`). Also dropped the now-unused `OFFICER_A` import in `test_08_addresses.py`.

- **Fixes applied to `implementation/`:** none — the implementation was faithful on all three failures.

## Step 8: Finalize PRD — 2026-09-29T20:48:00.000Z

Done. `PRD_FINALIZED.md` written at workspace/PRD_FINALIZED.md.

**Line counts:** PRD.md 290 lines → PRD_FINALIZED.md 290 lines (one sentence appended inline to §2.7; word delta +46, ~0% line delta).

**Changes (1 edit):**
- §2.7 — insert — appended sentence clarifying that a duty-station posting whose `effective_from` is not earlier than the member's current open duty-station interval (not a retroactive PCS under §3.11) but which overlaps an existing same-type interval is rejected with `ERR_ADDRESS_OVERLAP`, not `ERR_DUTY_STATION_CONFLICT` — impl: `implementation/routes_addresses.py:78-92` (malformed-interval check at :79, retroactive-duty-conflict check at :82-89, same-type overlap at :92).

**Items needing no edit:**
- `test_07_households.py::test_aggregate_counts_linked_active_and_suspended_only` — pure test-fixture bug; PRD §3.7 already pins `requires_active_status` defaulting to true and the suspended variant forcing base availability off. Implementation (`domain.py:24-25`) is faithful. No PRD edit.
- `test_09_product_catalog.py::test_matrix_reflects_category_gate` — PRD §3.7 deliberately leaves the serialized `facets` representation unpinned ("the per-group `facets` detail including per-offering base availability"); the impl's shape (six-entry lists per group plus per-offering entries, `domain.py:44-59`) is one legal realization. Pinning it would over-constrain beyond step_7's scope. No PRD edit.

**Per-edit pre-edit search log:**
- Edit 1 (§2.7 address-guard precedence):
  - (a) Subject: relative precedence of `ERR_ADDRESS_OVERLAP` vs `ERR_DUTY_STATION_CONFLICT` on address writes.
  - (b) Impl paths enumerated and read: full `implementation/routes_addresses.py` — `create_address` (:59-106; effective_to validation :78-79, duty-conflict check :81-89, overlap check :91-92), `patch_address` (:145-192; no duty-conflict check, overlap at :183-186), `_validate_no_overlap` (:47-56), `_intervals_overlap` (:33-44); repo-wide grep confirmed `ERR_DUTY_STATION_CONFLICT` is raised at exactly one site (:88). Also reviewed surviving test `test_pcs_after_closing_prior_interval_accepted` (test_08_addresses.py:76-96), which is consistent with either precedence.
  - (c) Wording adjustment made: the first draft claimed flat precedence ("the `ERR_ADDRESS_OVERLAP` family … precedes `ERR_DUTY_STATION_CONFLICT`"), which mis-described the `create_address` retroactive path (duty-conflict fires *before* overlap when `effective_from` is earlier than the open duty interval's start, routes_addresses.py:82-89 before :92). The sentence was re-scoped to the non-retroactive case only — exactly the deleted test's scenario — leaving the retroactive case free for the implementation's order and consistent with §3.11.

## Step 9: Complete PRD — 2026-09-29T20:59:00.000Z

Done. PRD_COMPLETED.md produced at `workspace/PRD_COMPLETED.md` — same line count (290), inline insert/revise edits only, no new sections.

- **Source vs output**: PRD_FINALIZED.md 290 lines / 48,091 chars → PRD_COMPLETED.md 290 lines / 52,822 chars (+4,731 chars).
- **Counts**: 23 ambiguity-pins, 3 mismatch-revisions.

### Changes

- §2.1 — insert — ambiguity — pinned that flat-resource reads (address, order, claim, entitlement) and household creation as `Member` enforce ownership against the resource's/`primary_member_id`'s `member_id` with `ERR_FORBIDDEN_ROLE` — `routes_addresses.py:140,150`, `routes_deployments.py:196`, `routes_claims.py:111`, `routes_products.py:243`, `routes_households.py:56`
- §2.3 — insert — ambiguity — non-integer/out-of-range `limit`/`offset` rejected `ERR_INVALID_REQUEST` 400 — `paginate.py:14-28`
- §2.3 — insert — ambiguity — list sort ties broken by ascending `id` — all route files' `.sort(key=lambda r: (r["created_at"], r["id"]))`
- §2.4 — insert — ambiguity — `version` starts at 1 on creation — `helpers.py:143`
- §2.5 — insert — ambiguity — clock set accepts bare date / naive datetime as UTC, normalizes to Z whole-second form, returns `{"current_utc": ...}` — `routes_clock.py:21-37`
- §2.7 — revise — **mismatch** — `ERR_DUTY_STATION_CONFLICT` moved from "closes the order" into the interval-check tier before `ERR_INVALID_REFERENCE`, first within that group — `routes_addresses.py:82-92`
- §2.7 — insert — ambiguity — missing sponsor at submit surfaces as `ERR_LINEAGE_DEPTH_EXCEEDED` — `routes_cases.py:234`
- §2.7 — insert — ambiguity — entitlement belonging to a different member yields `ERR_NOT_FOUND` on close — `routes_products.py:255-256`
- §3.2 — insert — ambiguity — `service_days` defined as end-minus-start calendar-day difference, computed once at record creation — `routes_cases.py:132-133`
- §3.2 — revise — **mismatch** — `authenticity_channel` is always `SELF_DECLARED` at upload (upload accepts no channel field) — `routes_cases.py:193`
- §3.3 — insert — ambiguity — submit valid from `INTAKE` or `MORE_INFO_REQUIRED`, else `ERR_INVALID_STATE`; missing sponsor fails with `ERR_LINEAGE_DEPTH_EXCEEDED` — `routes_cases.py:218-235`
- §3.3 — revise — **mismatch** — DENY records the supplied decision note as `denial_reason` (no separate `denial_reason` input); decide requires `UNDER_REVIEW` status — `routes_cases.py:298-305`
- §3.3 — insert — ambiguity — member minted with status `ACTIVE`, posture `NONE`; case's `eligibility_category` also set on approval — `routes_cases.py:368-377`
- §3.4 — insert — ambiguity — reconstruction decision restricted to `APPROVE`/`DENY`; officer id recorded on either outcome; verified records' `version` increments — `routes_cases.py:395-407`
- §3.5 — insert — ambiguity — `end_date` earlier than `start_date` rejected with `ERR_DEPLOYMENT_OVERLAP` — `routes_deployments.py:97-98`
- §3.5 — insert — ambiguity — cancelled orders excluded from overlap check; PATCH may clear `end_date` to null; non-REGISTERED/ACTIVE order PATCH fails `ERR_INVALID_STATE`; self-exclusion on revalidation — `routes_deployments.py:37,145-168`
- §3.6 — insert — ambiguity — `base_rate_bps`/`monthly_interest_cents` mandatory for RATE_REDUCTION else `ERR_INVALID_REQUEST`; `deployment_order_id` must resolve to same member's order else `ERR_INVALID_REFERENCE` — `routes_claims.py:52-60`
- §3.6.1 — insert — ambiguity — period count defined as full month boundaries crossed — `helpers.py:146-160`
- §3.6.1 — insert — ambiguity — `ERR_NO_RELIEF_AVAILABLE` also fires on zero period count or zero floored per-period relief — `routes_claims.py:130-132`
- §3.6.1 — insert — ambiguity — bank offset and outstanding sum both exclude the claim under decision — `routes_claims.py:187-197`
- §3.7 — insert — ambiguity — `facets` shape pinned: 4 group keys → 6-element AVAILABLE/UNAVAILABLE arrays, plus one key per active offering id → single availability value — `domain.py:44-59`
- §3.7 — insert — ambiguity — category-gate update grandfathers only `OPEN` entitlements; already-GRANDFATHERED untouched — `routes_products.py:154-165`
- §3.9 — insert — ambiguity — unresolvable `beneficiary_member_id` fails `ERR_INVALID_REFERENCE`; survivor selection defined (sponsored members with spouse/child relationships, excluding DECEASED, earliest by created_at); new survivor case fields null — `routes_members.py:146-186`
- §3.9 — insert — ambiguity — grant requires case `OPEN` else `ERR_INVALID_STATE` — `routes_households.py:165-166`
- §3.11 — insert — ambiguity — all five address fields mandatory at creation — `routes_addresses.py:69-73`
- §3.11 — insert — ambiguity — PATCH mutates only `effective_from`/`effective_to`/`is_duty_station`, null `effective_to` re-opens, self-exclusion on overlap revalidation, retroactive-PCS guard applies to creation only — `routes_addresses.py:160-186`
- §4 (12 endpoint-table rows) — insert — ambiguity — pinned exact filter query-parameter names for list endpoints and clock response body — `routes_cases.py:91-102,423,446`, `routes_members.py:32-46`, `routes_addresses.py:125-130`, `routes_deployments.py:181-186`, `routes_claims.py:96-101`, `routes_products.py:87-93,228-233`, `routes_households.py:79-84,138-146`, `routes_clock.py:37`

One notable behavior left unpinned deliberately: a direct-service/cadet `APPROVE` with zero service records passes the all-verified check vacuously in impl (`routes_cases.py:342-344`); since submission already requires a record and no deletion path exists, the state is unreachable and no prose change was needed.
