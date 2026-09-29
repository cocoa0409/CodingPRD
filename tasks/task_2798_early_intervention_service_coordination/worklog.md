## Step 1: Create task directory — 2026-09-04T22:49:00.000Z

Created /home/ubuntu/github/CodingPRD/tasks/task_2798_early_intervention_service_coordination and its workspace/ subdirectory. Index 2798 was pre-assigned by the invocation (no ./tasks/ scan performed, per orchestration instructions — concurrent pipelines on this host make auto-allocation collision-prone).

## Step 2: Generate scaffold — 2026-09-05T00:46:00.000Z

Done. All three scaffold artifacts for task 2798 are complete and lint-clean.

**Lint verdict (verbatim):**
```
SCAFFOLD §1.8/§1.9 -> §1.5 lint report
============================================================
  SCAFFOLD:           tasks/task_2798_early_intervention_service_coordination/SCAFFOLD.yaml
  Difficulty design:  tasks/task_2798_early_intervention_service_coordination/SCAFFOLD_DIFFICULTY_DESIGN.yaml
  Corner design:      tasks/task_2798_early_intervention_service_coordination/SCAFFOLD_CORNER_DESIGN.yaml

Coverage
  §1.5 endpoints declared:    50
  §1.1 entities declared:     12
  §1.8 instances scanned:     19
  §1.9 instances scanned:     61
  Calls scanned (§1.8+§1.9):  1316

VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
```

**Deliverables** (in `/home/ubuntu/github/CodingPRD/tasks/task_2798_early_intervention_service_coordination/`)
- `SCAFFOLD.yaml` — 2658 lines / 162 KB. Flat §1.0–§1.7 only (no `scaffold_difficulty_design` / `scaffold_corner_design` keys). 12 entities, 50 endpoints, 62 error codes, 6 roles, 62 numbered validations, 8 calculations, 4 state machines.
- `SCAFFOLD_DIFFICULTY_DESIGN.yaml` — 2072 lines / 144 KB. Single top-level key; 9 rules / 19 instances.
- `SCAFFOLD_CORNER_DESIGN.yaml` — 5085 lines / 337 KB. Single top-level key; all 9 guide sections in order — entities 15, state_machines 15, calculations 12, validations 13, endpoints 6, errors 13, rbac 5, complexity_layers 4, consistency_model 1 = 84 instances (61 real + 23 excluded stubs).

**Verified invariants:** instance names unique across the §1.8 ∪ §1.9 union (103 names, 0 collisions); every stub's `excluded_because.difficulty_instance` resolves to a real §1.8 instance name and carries no `grounds`/`test_recipe`; every real instance has `claim_type`, `grounds`, `distinguishing_aspect`, `test_recipe`; all three files `yaml.safe_load` clean. Independent role/endpoint resolver over all 927 corner-design calls reports only 10 mismatches, each an intentional `ERR_ROLE_NOT_PERMITTED` trigger inside a negative-trigger-named instance. Error-code coverage: all 62 codes are referenced by at least one design instance (`ERR_STALE_REFERRAL_VERSION` was the last gap, now covered by the optimistic-concurrency instance).

**Notes for the caller:**
- `scenario:` deliberately omits the meta-directive line "Generate task harder than expert level!" — that intent is encoded as `complexity_profile.difficulty_level: beyond_expert` instead, so the directive cannot leak into PRD.md downstream.
- Two work items during the final pass: 35 calls to the ProgramAdmin-exclusive `POST /ei/ifsps` / `POST /ei/ifsp-services` had been written as `as: ServiceCoordinator` and were rewritten (with the stray `as_user_id` dropped); one rbac instance was renamed to `determining_officer_cannot_waive_the_row_they_determined` so `scaffold_lint.py`'s `_NEGATIVE_NAME_RE` recognises its deliberate `ERR_ROLE_NOT_PERMITTED` trigger.
- `workspace/` and `worklog.md` were left untouched; no other directory under `tasks/` was created, read, or deleted.

Orchestrator verification: all three files exist (2658 / 2072 / 5085 lines); `grep -rn "harder than expert"` over the task dir returns nothing, so the difficulty directive did not leak.

## Step 3: Copy shared files — 2026-09-05T00:46:30.000Z

Copied /home/ubuntu/github/CodingPRD/INSTRUCTION.md to workspace/INSTRUCTION.md (1424 bytes).

## Step 4: Generate PRD — 2026-09-05T01:03:00.000Z

PRD generation for task 2798 is complete.

**Output:** `workspace/PRD.md`

**Final line count: 493 lines** (112,935 bytes), written in 7 chunked heredoc appends. The file ends at a real section boundary: the exact last heading is `## 5. Error Handling`, and the final line is the last row of its completed 2-column table, `| ERR_LEDGER_WOULD_UNBALANCE | 409 |`. No audit footer, no contract report inside the document.

**Structure:** §1 Introduction; §2 with 11 subsections (2.1 RBAC, 2.2 the fixed verbatim response-structure block, 2.3 Pagination, 2.4 Record Identity/Audit Fields/the one append-only register, 2.5 Logical Clock, 2.6 OCC, 2.7 Cascade Discipline, 2.8 Validation Order, 2.9 Rounding, 2.10 Conserved Quantities, 2.11 Natural Environments); §3 with 9 workflow subsections; §4 with a 4-column table covering all **50** endpoints; §5 with a 2-column table covering all **62** errors.

**Hard Contract reports**

- **Contract 1 — Field-Name Coverage: PASS.** Two independent passes. Pass 1 (flat extraction) checked 146 distinct entity field names, all entity enum values, and all 94 distinct `input` identifiers across the 50 endpoints: 0 missing. Pass 2 (per-entity walk: Child 7, Referral 35, ServiceCoordinator 8, Assessment 11, IFSP 13, IFSPService 15, Provider 7, ProviderAuthorization 12, ServiceVisit 15, CostShare 24, ContactLog 7, TransitionPlan 11 = 165 field entries) plus all computed-read output keys: 0 missing. Every identifier appears verbatim in backticks. (Note: verification had to strip fenced code blocks first — the §2.2 json fences otherwise desynchronize naive backtick pairing and produce false negatives.)
- **Contract 2 — Rule Coverage: PASS.** All 62 error IDs from the catalog are named in §1–§3 prose (not just in the §5 table); the full 62-rule priority ladder with `applies_to` endpoint scopes is in §2.8 and each condition is restated in domain narrative in §3. All 44 state names across the 10 state machines appear in backticks in the prose. All 35 numeric constants from the 14 calculations appear (45, 120, 1580000/15,800, 555000/5,550, tier ceilings 250.0/400.0/600.0, rates 0.00/0.05/0.10/0.15, caps 0/12000/30000/60000, 0.60, 1.50/1.00/0.50/0.75/0.50, 4, 180, clamp 1.00–3.00, 0.9000, 4, 30, 90, 270, 270, 6, 180, 20, 30), as does `QUALIFYING_METHODS`. Both dual variants (GROSS/NET timeline, PROVISIONAL/FINAL cost share), both parallel ServiceVisit status dimensions, the OCC rule, and all sibling-branch symmetries (notify-lea opt-out vs. notified; the four Referral→EXITED edges) are covered. No pseudocode operators appear anywhere in the document, and no fuzzy hedges remain.
- **Contract 3 — §3 Path Purity: PASS.** Of 384 distinct backticked tokens in §3, zero start with `/`, zero are a bare HTTP method, and zero combine method+path. The strings `/ei` and `_clock` occur 0 times in §3 in any form. Endpoints are referenced there only by state-transition framing, role + action verb, or capability description.

**Scaffold inconsistencies resolved in prose (worth flagging to the implementer/test author):**
1. Validation priority 23 gates both session scheduling and authorization revocation on `status == ACTIVE` with `ERR_AUTHORIZATION_NOT_ACTIVE`, but the ProviderAuthorization state machine allows `→ REVOKED` from `ACTIVE`, `EXHAUSTED` and `SUSPENDED`. PRD states: revocation is permitted from all three, refused only for already-`REVOKED`/`EXPIRED`; scheduling requires strictly `ACTIVE`.
2. Scaffold priority 1 names the header `X-Role`; the skill mandates `X-User-Role`. Used `X-User-Role` throughout.
3. `documented_at_utc` appears only in a ServiceVisit side_effect, not in any entity field list or endpoint side_effect — deliberately omitted rather than invented.
4. `headroom_points` is in the caseload-summary output with no scaffold formula — defined in prose as `max_weighted_caseload_points` minus `weighted_caseload_points` to two decimals.
5. `ATTEMPTED_NO_ANSWER` appears in `monthly_contact_compliance.input_set` but is not a `contact_method` enum value — ignored; the PRD states only that `EMAIL` and `LETTER` never qualify.
6. `ERR_INSURANCE_POLICY_REQUIRED`'s `applies_to` lists only the insurance-consent and finalize operations, though the `insurance_policy_id` field description implies the requirement at determination time too. The PRD enforces it exactly on the two scoped operations.

The two withheld design files were never opened, grepped, or referenced, and no sibling task directory was read.

Orchestrator truncation check (per known doc-generator failure mode): `wc -l` = 493, last heading `## 5. Error Handling` at line 426, final line is a complete table row `| ERR_LEDGER_WOULD_UNBALANCE | 409 |`. §4 endpoint table spans 369-425 and §5 error table 426-493 — both complete. Not truncated; no regeneration needed.

## Step 5: Generate unit tests — 2026-09-05T03:15:00.000Z

Generation is complete. Both stages are finished, verified, and at the task root — nothing was written under `workspace/`.

## What was produced

`test_helpers/` (Stage 1, 2,652 lines)

| file | lines |
|---|---|
| `__init__.py` | 172 |
| `api_client.py` | 299 |
| `api_errors.py` | 169 |
| `assertions.py` | 363 |
| `constants.py` | 140 |
| `factories.py` | 482 |
| `fixtures.py` | 680 |
| `test_users.py` | 97 |
| `types.py` | 250 |

`test_suite/` (Stage 2, 7,458 lines, 104 test functions → **114 collected tests**)

`conftest.py` 64 · queue A: `test_01` 257, `test_02` 265, `test_03` 262, `test_04` 300, `test_05` 223, `test_06` 408, `test_07` 236, `test_08` 247, `test_09` 285 · queue B: `test_10_entity_lifecycle` 883, `test_11_state_machines` 688, `test_12_calculations` 608, `test_13_validations` 906, `test_14_endpoints` 415, `test_15_error_sweeps` 626, `test_16_rbac` 454, `test_17_complexity_layers` 226, `test_18_consistency_model` 105.

## Design-index coverage (mechanically verified)

- **Queue A:** 19 difficulty instances, every one covered by >=2 tests (38 tags, all `(rule_id, name)` pairs resolve to real instances).
- **Queue B:** 84 corner instances = 61 non-stub + 23 `excluded_because:` stubs. All 61 non-stub instances covered (66 tags); **zero** stubs translated; zero uncovered non-stub instances.
- Every one of the 104 test functions carries **exactly one** `Design:` line, and it is the last non-blank docstring line. No untagged, dual-tagged, or dangling tags.
- Final PRD-citation pass: every docstring carries >=1 verbatim, whitespace-normalized-grep-able `PRD x.y: "…"` quote from `workspace/PRD.md`.

## Bugs caught during the final passes

- `test_10_entity_lifecycle.py` called `create_provider(...)` without importing it — a guaranteed `NameError` at runtime. Import added.
- `test_16_rbac.py` had the same defect for `read_cost_share` (and an unused `read_caseload_summary`). Fixed.
- Five lines exceeded the 88-char style limit across `test_01`, `test_02`, `test_06`, `test_10`, `test_16`. Rewrapped.
- An AST-level undefined-name scan now reports clean for all 19 test-suite files, `unused: []` everywhere, and `pytest --collect-only` collects all 114 tests with no import errors.

## Instances where the design asserted something the PRD does not derive

- `ERR_INSURANCE_POLICY_REQUIRED` on `POST /ei/cost-shares` — PRD lines 138/327 place that code only on `/insurance-consent` and `/finalize`, so the trigger was replaced with the `/insurance-consent` path (all asserted numbers preserved: 369.8 → TIER_1 → 2,600 assessed → 1,560 offset → 1,040 final).
- The design's "no `Child`/`ServiceCoordinator`/`Provider` row is created" assertion in the role-exclusive sweep is unobservable (those entities have no list endpoint); the observable half is asserted instead (assessments, cost-shares and contact-logs all `total_count == 0`, plus `gross_elapsed_days == 0` proving the clock never moved).
- A design-supplied second notify-LEA date (2026-04-21) would have run ahead of the logical clock and surfaced `ERR_DATE_IN_FUTURE` instead of the intended state error; the retry uses the same date with a different `lea_code` so the 409 is unambiguous.

Orchestrator verification: both directories are at the task root (nothing named test_helpers/test_suite/test_* under workspace/); 10,110 total lines across the two dirs.

## Step 6: Generate implementation — 2026-09-05T02:35:00.000Z

Implementation is complete and verified.

## What was done

Full Python + Flask implementation at `workspace/implementation/` — 28 files, 3,652 lines, all written via chunked appends. Storage is in-memory only (`store.Store` dicts, reset on every boot); no seeding, no SQLite, no disk persistence (grep for `open(`/`sqlite`/`pickle`/`json.dump`/`shelve` returns nothing).

Structure: `app.py` (app factory, 13 blueprints, envelope-emitting handlers for `ApiError` + 400/404/405/500), `store.py` (logical clock defaulting to `2026-08-01T00:00:00Z`, ISO-instant formatting with exactly 3 fractional digits, `Decimal`/ROUND_HALF_UP helpers, row version bookkeeping), `auth.py`, `errors.py`, `envelope.py`, `validate.py`, `domain.py`, `helpers.py`, `services/{compute,money,cascades}.py`, and 13 modules under `routes/`. `start.sh` is executable, does a guarded `pip install`, and `exec python3 app.py` on `$PORT` (default 10000) with `threaded=False`, so it boots clean per test under `--isolation per-test-server`.

## Final verification

Fresh boot on port 27311 (random high port), ran the end-to-end smoke script: **FAILURES: 0**. Derived values confirmed: statutory deadline 2026-08-19, excluded 4 / net 23 days, FPL threshold 2,690,000 cents → 334.6% → TIER_1 → assessed 4000, visit share 1000 ACCRUED, ledger 1000 = 900 + 100 after a waive, void correctly refused with `ERR_LEDGER_WOULD_UNBALANCE`, finalize 353.2%, monthly contact COMPLIANT, provider suspension cascading to auth SUSPENDED + line AT_RISK (8 makeup units) + `service_gap_flag` true, notify-lea lead 104 → TIMELY, exit after 126 days → NOT_COMPARABLE x3 and case weight 0.00. The server was then killed by its own PID only (1404232), port 27311 confirmed free; `__pycache__` removed.

## Key PRD-fidelity decisions in the final pass

- **Uniform version rule**: `store.mark()` bumps `version` exactly once per request for every row that actually changed, including secondary/cascade effects (PRD lines 90, 118). Residual `bump=False` call sites are now inert.
- **`auth.py`**: removed a non-PRD `X-Role` header fallback; both `X-User-ID` and `X-User-Role` are now required and the role must be declared, else `ERR_UNAUTHENTICATED`.
- `services/compute.recompute_service_gap` derives `service_gap_flag` from any AT_RISK line on the case (PRD line 301 says "recomputed") rather than being force-set by the provider cascade.
- §2.8's 14-level ladder was taken as normative over §3.x narrative orderings (e.g. credential-expiry → service-type-mismatch → window-overlap → date-range → pool; `ERR_UNITS_EXCEED_AUTHORIZATION` before `ERR_ACTUAL_UNITS_EXCEED_SCHEDULED`).
- Waive gate is PROVISIONAL or VERIFIED → otherwise `ERR_COST_SHARE_NOT_PROVISIONAL`, with `ERR_SEGREGATION_OF_DUTIES` checked at ladder level 7, ahead of state.

## One PRD gap worth flagging to the test-suite side

PRD §2.8 item 5 ends with "A `contactLogId` must likewise resolve for `GET /ei/contact-logs/{contactLogId}`" but §5's error table has **no contact-log not-found identifier**. I implemented `ERR_CONTACT_LOG_NOT_FOUND` at 404 by analogy. If the generated tests assert a different `error_id` for that case, this is the single spot where an id mismatch could occur (status 404 is unambiguous either way).

## Line counts (`wc -l`)

`app.py` 74, `auth.py` 63, `domain.py` 226, `envelope.py` 74, `errors.py` 94, `helpers.py` 121, `requirements.txt` 1, `start.sh` 8, `store.py` 280, `validate.py` 173; `routes/`: `__init__.py` 0, `assessments.py` 126, `authorizations.py` 133, `children.py` 47, `clock.py` 21, `contact_logs.py` 64, `coordinators.py` 60, `cost_shares.py` 173, `ifsp_services.py` 90, `ifsps.py` 188, `providers.py` 65, `referrals.py` 370, `transition_plans.py` 142, `visits.py` 321; `services/`: `__init__.py` 0, `cascades.py` 175, `compute.py` 408, `money.py` 155. **Total 3,652.**

All hard constraints respected: writes confined to `workspace/implementation/`; `test_suite/`, `test_helpers/`, `worklog.md`, both SCAFFOLD design files, and every sibling task directory were never read or modified.

## Step 7: Run tests and iterate — 2026-09-05T03:22:00.000Z

All 8 parallel rounds pass 114/114. Final state is clean (sweep artifacts and caches removed; `worklog.md` untouched).

## Iterations run: 3

**Iteration 1** — 89/114 in all 8 rounds, identical failure set (fully deterministic, no flakiness anywhere in the three sweeps).
**Iteration 2** — 113/114 in all 8 rounds.
**Iteration 3** — 114/114 in all 8 rounds, 0 skipped, ~212 s per round.

## Tests deleted: none

Every failing assertion traced to a verbatim PRD sentence and was uniquely derivable from it. No test was weakened, skipped, or relaxed; no `error_id` assertion was downgraded.

## Fixes applied to the test artifact

- `test_helpers/api_errors.py` + all `test_suite/*.py` (mechanical, 55 references): tests referenced `ApiErrorId.ERR_<NAME>` while the enum members are declared unprefixed (`UNAUTHENTICATED = "ERR_UNAUTHENTICATED"`). Both spellings were in use across the suite. Normalized every reference to the declared member name — **21 of the 25 failures were this single `AttributeError`**, not implementation defects. No expected `error_id` string changed.
- `test_suite/test_15_error_sweeps.py` — `TestNotificationDeadlineSign`: the setup asserted `read_referral(...)["third_birthday_date"]`, but PRD §3.1 derives `third_birthday_date` on the **Child**, not the Referral (the `Referral` shape in `test_helpers/types.py` correctly omits it, and test_06/test_13 already read it off the child). Changed to `read_child(api, case.child_id)`, added the `read_child` import.
- `test_suite/test_01_dual_variant_calculations.py` — `_build_divergent_timeline_case` fixture, two setup bugs against PRD §3.3/§2.7:
  1. It authored an INITIAL plan and left it in `DRAFT`, then expected the clock to be stopped. PRD §3.3 lists the qualifying stop-clock statuses verbatim as `PENDING_CONSENT`, `ACTIVE`, `AMENDMENT_PENDING`, `SUPERSEDED`, `CLOSED` — `DRAFT` is excluded, and test_03 independently relies on that same enumeration. Added the plan's first service line so it advances `DRAFT → PENDING_CONSENT`.
  2. The stored referral row still read `IN_PROGRESS`, because PRD §3.3's recompute-trigger list (assessment completion, eligibility determination, meeting-date recording, clock advance, compliance read) does not include adding a service line. Added a clock set after the line, which PRD §2.7 declares recomputes the elapsed counts and verdict for every non-terminal case. Timeline arithmetic is unchanged by both edits (gross 54 / excluded 12 / net 42, stop date = meeting date).

## Fixes applied to `implementation/`

- `workspace/implementation/services/money.py`, `recompute_cost_share`: it wrote `assessed_monthly_fee_cents` in **both** variants, overwriting the provisional figure (2600) with the verified-tier figure (5200) at finalization. PRD §3.8 enumerates exactly what finalization recomputes — "`fpl_percent`, `tier_code`, `coinsurance_rate`, `monthly_cap_cents` and `effective_coinsurance_rate` are all recomputed" — `assessed_monthly_fee_cents` is absent from that list and is defined solely as the provisional-time store ("the capped figure is stored as `assessed_monthly_fee_cents`"), consistent with "Finalization deliberately does **not** re-price history." Moved the write into the provisional branch; the recomputed capped figure still drives `insurance_offset_cents` (3120) and `final_monthly_fee_cents` (2080).

## Notable

The 25-failure iteration-1 count was misleading: only **one** real implementation defect existed. 21 failures were a single enum-naming inconsistency in the test artifact, and 3 more were test-setup preconditions that contradicted PRD. No PRD-required implementation check was removed or weakened, no endpoint/field/side-effect was added, and storage remains in-memory only.

### Orchestrator independent re-verification

Because the Step 7 subagent deleted its sweep artifacts (a known failure mode is a subagent claiming a clean sweep with no results.*.json on disk), the orchestrator re-ran the full 8-round sweep itself under `setsid nohup` after clearing `__pycache__`. Result: all 8 files present, **114/114 passed, 0 failed in every round**. The persisted `workspace/implementation/results.{1..8}.json` are from this orchestrator-run sweep.

## Step 8: Finalize PRD — 2026-09-05T03:25:00.000Z

PRD_FINALIZED.md is written and intact (ends at the `## 5. Error Handling` table, last row `ERR_LEDGER_WOULD_UNBALANCE | 409`).

## Line/byte counts
- PRD.md: 493 lines / 112,933 bytes
- PRD_FINALIZED.md: 493 lines / 113,722 bytes
- Delta: 0 lines (+0.00%); +789 bytes (+0.70%) — the single edit is inline inside one paragraph, so no line count change.

## Changes
- §3.8 "The final variant" — insert — pinned that `assessed_monthly_fee_cents` is written once at determination time and is *not* recomputed by finalization (even across a tier change), and that `insurance_offset_cents` / `final_monthly_fee_cents` are computed from a freshly re-derived-and-capped monthly figure (eligible lines re-priced as they stand at finalization, at the recomputed `coinsurance_rate`, per-line rounding before summation, capped at the recomputed `monthly_cap_cents`) rather than from the stored `assessed_monthly_fee_cents` — `implementation/services/money.py:81-96` (write moved into the provisional branch at :94; `capped` at :72 drives :87-92).

## Pre-edit search log
Edit 1 (§3.8 final variant)
- (a) Subject: the lifecycle of `assessed_monthly_fee_cents` and which monetary figure feeds `insurance_offset_cents` / `final_monthly_fee_cents`.
- (b) Paths enumerated: grepped `assessed_monthly_fee_cents` across all of `implementation/` — only three sites exist (`routes/cost_shares.py:56` initialises it to 0 at creation, `services/money.py:94` writes it in the provisional branch, `domain.py:209` lists it in the cost-share serializer). Read `services/money.py` in full (`recompute_cost_share`, `monthly_raw_cents`, `eligible_fee_lines`, `compute_visit_share`, `apply_charge`/`reverse_charge`, `assert_ledger`) and `routes/cost_shares.py` in full (create / finalize / waive / insurance-consent) to enumerate every caller of `recompute_cost_share`: exactly two — create with `final=False`, finalize with `final=True`. Checked `services/cascades.py` for any cost-share money mutation on the case-exit / supersession cascades: it only sets `status` to `CLOSED` (:123-125), never a fee field. Confirmed `insurance-consent` recomputes nothing, and `waive` touches only ledger fields. Also confirmed no service-line write path re-runs the fee.
- (c) Wording adjustments made to stay consistent with all of them: (1) said "not among the fields finalization recomputes" rather than asserting the PRD's five-field list is exhaustive, because `recompute_cost_share` also re-writes `fpl_threshold_cents` on the final branch (same value, since `household_size` cannot change, so unobservable — but an exhaustiveness claim would have been false); (2) qualified the re-pricing with "as they stand at finalization", because `monthly_raw_cents` re-reads `eligible_fee_lines` live rather than reusing any determination-time snapshot; (3) reused the existing "eligible chargeable lines described above" phrasing instead of restating the eligibility predicate, so the empty-set → 0 rule already stated in the monthly-fee paragraph continues to govern the final variant too (impl: `raw = 0` when no `ACTIVE` plan or no eligible line).

Nothing else in `<step_7_diff>` warranted a PRD edit: the 55 `ApiErrorId.ERR_*` renames are a pure test-artifact naming bug; the `third_birthday_date`-on-Child fix is already determined by §3.1 (derived at child registration; not in the referral field list of §3.1, and `implementation/domain.py:130` carries it only on `Child`); and both `_build_divergent_timeline_case` fixes are already determined verbatim by §3.3's stop-clock status list (DRAFT excluded), §3.3's recompute-trigger list (service-line addition absent), §3.5's `DRAFT → PENDING_CONSENT` first-line rule, and §2.7's clock-set cascade.

## Step 9: Complete PRD — 2026-09-05T04:05:00.000Z

Orchestrator note on method: per the known Step 9 failure mode (a single-shot full scan of a 493-line / 113 KB PRD silently under-covers and can return a byte-identical file), the scan was run as **three sequential passes over one shared PRD_COMPLETED.md, partitioned by implementation module**. Pass 1 performed the `cp` from PRD_FINALIZED.md; passes 2 and 3 were explicitly forbidden to re-copy. Slices: pass 1 = app/auth/envelope/errors/validate/store/helpers/domain + routes/{children,clock,coordinators,referrals,assessments}; pass 2 = routes/{ifsps,ifsp_services,providers,authorizations,visits} + services/{cascades,compute}; pass 3 = routes/{cost_shares,contact_logs,transition_plans} + services/money. Open items were handed forward explicitly between passes (`documented_at_utc` from pass 1 → pass 2; `select_cost_share`/`compute_visit_share` and transition-plan status handling from pass 2 → pass 3).

### Pass 1 (core + intake) — 20 ambiguity-pins, 4 mismatch-revisions
cp done first. PRD_FINALIZED.md 493 lines / 113,722 chars → PRD_COMPLETED.md 494 lines / 122,486 chars (+1 line for a new `ERR_CONTACT_LOG_NOT_FOUND | 404` table row, +8,764 chars). Changes:
- §2.2 revise mismatch — `api_request_timestamp` comes from the logical clock, not wall clock — envelope.py:9, store.py:69
- §2.3 insert — integer parsing; `limit` 101–200 echoed verbatim in `meta.limit` while the page truncates to 100 — envelope.py:43,69
- §2.3 insert — `created_at` ties break by insertion order; `has_more` = skipped + page-length < `total_count` — store.py:273, envelope.py:22
- §2.3 insert — filters are exact string equality, never enum-validated (out-of-domain → empty page, not an error); unknown query params ignored — routes/referrals.py:105, routes/assessments.py:86
- §2.4 insert — `created_at`/`updated_at` are clock stamps; no-op write bumps nothing; multi-field/multi-branch write bumps `version` once; row created+mutated in one request stays version 1 — store.py:225,246,262
- §2.5 insert — clock may be set backwards; endpoint returns `data` = `{current_utc}` only — routes/clock.py:16
- §2.5 insert — instant parsing accepts 1–9 fractional digits, omitted seconds, space separator, numeric offsets; normalised to canonical 3-digit UTC — store.py:73
- §2.6 revise mismatch — the referral-version-bumping write list is illustrative, not closed — store.py:225, routes/assessments.py:64
- §2.8 rung 1 revise mismatch — `X-User-ID` required non-empty for every role, opaque included — auth.py:32
- §2.8 rung 3 insert — explicit null == absent; empty body == `{}`; non-object refused; trimmed string/min-length; integers reject bools/fractions; arrays reject duplicates; two cross-field rules report `ERR_INVALID_REQUEST` at this rung — validate.py:33,52,161
- §2.8 rung 5 insert — contact-log 404 identifier is `ERR_CONTACT_LOG_NOT_FOUND` — helpers.py:96, errors.py:32
- §2.11 insert — the 20-character minimum is counted after trimming — validate.py:57
- §3.1 insert — future `date_of_birth` is `ERR_INVALID_REQUEST` (400), not `ERR_DATE_IN_FUTURE` — routes/children.py:27
- §3.1 insert — referral `county_code` is an uppercase whitespace-free token — routes/referrals.py:35
- §3.2 insert — `max_weighted_caseload_points` any number in [1.00, 40.00], stored rounded half up to 2 dp — routes/coordinators.py:22
- §3.2 revise mismatch — auto-selection folds capacity into candidacy, so an all-out-of-headroom roster reports `ERR_NO_ELIGIBLE_COORDINATOR`; `ERR_CASELOAD_CAP_EXCEEDED` only on the named-coordinator path — routes/referrals.py:171
- §3.2 insert — utilization tie then `created_at` tie breaks by registration order — routes/referrals.py:177
- §3.3 insert — assessment justification mandatory for CLINIC/PROGRAM_OFFICE as a 400 checked before `referral_id` resolution; omitted `domains_assessed` stores null — routes/assessments.py:30,44
- §3.3 insert — scheduling allowed from every non-terminal status, refused only from NOT_ELIGIBLE/EXITED — routes/assessments.py:36
- §3.3 insert — with several qualifying initial plans the most recently authored supplies the stop date; a WITHDRAWN plan never stops the clock — services/compute.py:288
- §3.3 insert — the timeline-compliance read recomputes without persisting; a GET never bumps `updated_at`/`version` — routes/referrals.py:354
- §3.4 insert — the revert re-derives `initial_ifsp_meeting_date`, recomputes counters and `monthly_contact_status`, bumps `Referral.version`; a live ACTIVE/AMENDMENT_PENDING plan suppresses it — routes/assessments.py:59, services/compute.py:332
- §3.9 insert — pre-service exit naming REACHED_AGE_THREE/NO_LONGER_ELIGIBLE, or any exit from INTAKE/terminal, is `ERR_REFERRAL_STATE_INVALID`; ratings on a pre-service edge still stored — routes/referrals.py:294,323
- §4/§5 insert — trailing slashes insignificant; off-contract `ERR_NOT_FOUND` (404), `ERR_METHOD_NOT_ALLOWED` (405), `ERR_INTERNAL` (500) plus the new `ERR_CONTACT_LOG_NOT_FOUND` (404) row — app.py:35,48, errors.py:77

Deliberately left alone: the eligible branch of eligibility determination skips a `case_weight_points`/coordinator recompute §3.2 implies, but every weight term is provably unchanged across EVALUATION_PENDING → ELIGIBILITY_DETERMINED, so output is identical.

### Pass 2 (plan / provider / visit) — 19 ambiguity-pins, 10 mismatch-revisions
No re-copy; 30 targeted Edits. 494 lines / 122,486 chars → 494 lines / 131,427 chars.
- §2.6 insert — case `version` bumped on every accepted plan authoring, whatever the plan type — routes/ifsps.py:79
- §2.7 insert — clock-cascade hop order: authorization expiry → per-case timeline/case-weight/monthly-contact → coordinator aggregates — services/cascades.py:155-175
- §3.2 revise mismatch — corrected the recompute-trigger list for `case_weight_points` — services/compute.py:196-232
- §3.2 revise mismatch — the live-service-line term counts lines across all plans of the case, not just the ACTIVE plan; a COMPLETED line stops counting — services/compute.py:181-193
- §3.5 insert — `authoring_coordinator_id` is provenance only, never resolved against the roster — routes/ifsps.py:57
- §3.5 revise mismatch — authoring an INITIAL plan does not stop the 45-day clock (new plan is DRAFT), though it does set `initial_ifsp_meeting_date` — services/compute.py:246-279
- §3.5 revise mismatch — `declined_service_ids` is a min-1 unique-id array, so an empty array is `ERR_INVALID_REQUEST`, not `ERR_ALL_SERVICES_DECLINED`; ignored under FULL consent — routes/ifsps.py:96-140
- §3.5 insert — partial-consent guards: omitted array under PARTIAL yields `ERR_ALL_SERVICES_DECLINED`; declined ids matched including already-DISCONTINUED lines, while the "all declined" test counts only live lines — routes/ifsps.py:120-140
- §3.5 insert — a declined line is marked `declined_by_family`, moved to DISCONTINUED, pool recomputed, authorizations untouched; every consent recomputes case weight, monthly contact, service gap, coordinator aggregates — routes/ifsps.py:141-180
- §3.5 revise mismatch — supersession discontinues every line not already DISCONTINUED, COMPLETED included — services/cascades.py:68-81
- §3.5 insert — superseded plan's `service_line_count` and `non_natural_setting_line_count` recomputed to 0 — services/cascades.py:80
- §3.6 insert — `credential_expiry_date` accepted with no future/past constraint at registration; only gates authorization windows — routes/providers.py:24-40
- §3.6 insert — a PLANNED line advances to AUTHORIZED on its first authorization; a line past PLANNED is left alone — routes/authorizations.py:81-82
- §3.6 revise mismatch — authorization check order: credential expiry before service-type mismatch; window overlap before the end<start range test — routes/authorizations.py:30-65
- §3.6 insert — `units_remaining` = `authorized_units − units_consumed − units_released`, recomputed after any write touching either counter — services/compute.py:148-151
- §3.6 insert — expiry cancels no session and recomputes only the line's pool — services/cascades.py:134-152
- §3.6 insert — revocation additionally recomputes `makeup_owed_units` and `service_gap_flag`; cascade-driven revocations write the same units_released/revoked_date/reason triple — routes/authorizations.py:123-131, services/cascades.py:20-33
- §3.6 revise mismatch — the provider cascade recomputes `service_gap_flag` (does not force it true), touches only ACTIVE authorizations, also recomputes case weight and coordinator aggregates — services/cascades.py:36-65
- §3.7 insert — fields a later documentation or void writes begin null, not zero (`documented_at_utc`, `family_share_cents`) — routes/visits.py:98-108
- §3.7 insert — the authorization-window test compares only `scheduled_start`'s calendar date, so a session may run past `end_date` — routes/visits.py:81-85
- §3.7 insert — `actual_units` required only for DELIVERED (`ERR_INVALID_REQUEST`, ahead of the temporal rung); actual_start/actual_end/session_note stored unvalidated against the schedule — routes/visits.py:166-181
- §3.7 insert — authorization standing not re-checked at documentation; authorization-remaining test precedes scheduled-units test; `documented_at_utc` is the logical-clock instant of acceptance, never cleared by a void (resolves pass 1's VISIT_FIELDS handover) — routes/visits.py:186-215
- §3.7 revise — non-delivery also zeroes `family_share_cents` and stamps both documentation fields; a server/cascade cancellation leaves them null — routes/visits.py:261-269, services/cascades.py:11-16
- §3.7 revise mismatch — `service_gap_flag` true when any line on any plan of the case is AT_RISK, whatever that plan's status — services/compute.py:366-373
- §3.7 insert — a void reverses the cost-share row recorded on the session at documentation time (never re-selected), always recomputes the provider's `active_authorization_count`, never reopens a COMPLETED line — routes/visits.py:286-319
- §3.9 revise mismatch — the IFSP_PENDING → EXITED edge discontinues every non-DISCONTINUED line, recomputes the withdrawn plan's counts, cancels its DRAFT transition plan — services/cascades.py:97-108
- §3.9 revise mismatch — the closure cascade discontinues every non-DISCONTINUED line, COMPLETED included — services/cascades.py:68-81
- §3.9 insert — a DRAFT transition plan at exit becomes CANCELLED; other statuses untouched — services/cascades.py:118-122
- §3.9 insert — the closed plan's line counts recomputed to 0; each cancelled session's `actual_units` and `family_share_cents` zeroed — services/cascades.py:11-16,80

### Pass 3 (cost share / contact / transition) — 10 ambiguity-pins, 2 mismatch-revisions
No re-copy; targeted Edits only. 494 lines / 131,427 chars → 494 lines / 135,457 chars.
- §2.5 insert — `conference_held_date` is exempt from the not-in-the-future rule and accepted as supplied — routes/transition_plans.py:26,48
- §2.8 rung 3 revise mismatch — notify-lea's `lea_code`/`opt_out_signed_date` either/or pairing added to the rung-3 cross-field enumeration, so it reports `ERR_INVALID_REQUEST` ahead of `ERR_TRANSITION_PLAN_NOT_FOUND` — routes/transition_plans.py:92-103
- §3.8 ¶1 insert — creation never raises `ERR_INSURANCE_POLICY_REQUIRED` (consent true with no policy is accepted); initial nulls/zeros pinned — routes/cost_shares.py:20-64
- §3.8 ¶1 revise — determination-time `ERR_REFERRAL_STATE_INVALID` fires only for NOT_ELIGIBLE/EXITED; INTAKE permits it — routes/cost_shares.py:29
- §3.8 revise — the session's month bucket is the `YYYY-MM` prefix of `scheduled_start` in canonical UTC — services/money.py:113, store.py:141-145
- §3.8 insert — `month_accrued_cents` is a per-determination running total, never reset at a calendar-month boundary — services/money.py:122,130-137
- §3.8 revise mismatch — the three ledger totals are maintained incrementally; finalization changes none of them, only re-checking the identity — services/money.py:81-97, routes/cost_shares.py:118-119
- §3.8 insert — repeated waivers allowed while a balance remains; `waiver_reason_code` records only the latest — routes/cost_shares.py:144-148
- §3.8 insert — both insurance-consent fields are written from the request, so an omitted `insurance_policy_id` is stored null and clears any prior identifier — routes/cost_shares.py:168-171
- §3.9 revise — contact-log `ERR_REFERRAL_STATE_INVALID` fires only for the two terminal statuses — routes/contact_logs.py:28
- §3.9 insert — `lea_code` must be a non-empty uppercase whitespace-free token; branch pairing refused with `ERR_INVALID_REQUEST` before plan lookup — routes/transition_plans.py:89,92-102
- §3.9 insert — the parent IFSP's status is not re-checked at notification, so an ACTIVE → AMENDMENT_PENDING plan still permits it — routes/transition_plans.py:107

Verified already-pinned in pass 3's slice: Step 8's §3.8 wording still matches services/money.py:81-97 exactly and was left as is; FPL threshold/percent/tiering, per-line-round-before-sum, `select_cost_share` order, `compute_visit_share` exempt-before-cap ordering, apply/reverse charge, `assert_ledger`, qualifying contact methods, `contact_month` derivation, the day-20 COMPLIANT/DUE/DELINQUENT rule, the 270/90-day grading, transition-window gate, TRANSITION_PLAN_LIVE duplicate set, list-filter sets and every ladder position already matched uniquely.

### Step 9 aggregate + orchestrator verification
Total across three passes: **49 ambiguity-pins, 16 mismatch-revisions.** PRD.md 493 lines / 112,933 chars → PRD_FINALIZED.md 493 / 113,722 → PRD_COMPLETED.md 494 lines / 135,457 chars (+22,524 chars / +19.9% over PRD.md). `cmp` confirms PRD_COMPLETED.md is NOT byte-identical to PRD_FINALIZED.md (the known "scan never ran" tell), and the file still ends at the complete `## 5. Error Handling` table with the final row `| ERR_LEDGER_WOULD_UNBALANCE | 409 |`. `find` confirms no .py file under implementation/, test_suite/ or test_helpers/ was modified after the orchestrator's verified 8-round sweep, so the persisted results.{1..8}.json (114/114, 0 failed, all 8 rounds) still describe the shipped code exactly. Steps 8 and 9 touched documentation only.

PIPELINE COMPLETE.
