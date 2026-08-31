# Worklog — task_2178_continuing_ed_noncredit

## Step 1: Create task directory — 2026-08-30T04:28:29.604856596Z

Created `tasks/task_2178_continuing_ed_noncredit/` and `tasks/task_2178_continuing_ed_noncredit/workspace/` (index 2178 = highest existing 2177 + 1).

## Step 3: Copy shared files — 2026-08-30T04:28:48.552776572Z

Copied `INSTRUCTION.md` -> `tasks/task_2178_continuing_ed_noncredit/workspace/INSTRUCTION.md` (1424 bytes). Run out of order (independent of Step 2), while the scaffold subagent was still running.

## Step 2: Generate scaffold — 2026-08-30T05:31:03.748916436Z

All three artifacts are written and lint clean.

## Files written

| File | Lines |
|---|---|
| `SCAFFOLD.yaml` | 2565 |
| `SCAFFOLD_DIFFICULTY_DESIGN.yaml` | 2555 |
| `SCAFFOLD_CORNER_DESIGN.yaml` | 4280 |

## SCAFFOLD.yaml (§1.0–§1.7)

- **Profile**: `workflow_orchestration` + `ledger_reconciliation`; layers `optimistic_concurrency`, `cascading_side_effects`, `dual_variant_calculation`, `rate_threshold_triggers`; topology `graph`; shape `parallel`; role model `segregation_of_duties`; `api_prefix: ""`. Difficulty band: expert-plus.
- **13 entities**: Course (self-referential prerequisite), Offering, Learner, Instructor, CorporateAccount, Voucher, Registration (self-referential transfer pointer), InstructorContract, CompletionRecord, CplPetition, CplCitation (m:n junction), RefundTransferRequest, MarketingMembership.
- **9 state machines / 52 transitions** — Registration has parallel `enrollment_status × payment_status` axes; CplPetition cycles `UNDER_REVIEW→REVISION_REQUESTED→SUBMITTED`; Offering cycles `OPEN↔WAITLIST_ONLY` and forks at census into `CENSUS_LOCKED` or `CANCELLED`; RefundTransferRequest forks `REFUND_APPROVED` / `TRANSFER_APPROVED` and rejoins at `SETTLED`; Voucher and CorporateAccount both cycle.
- **2 OCC concurrency rules** (`registration-create-stale-offering` on Offering, `voucher-issue-stale-account` on CorporateAccount), both 412.
- **10 calculations**, **29 ordered validations**, **57 endpoints** (incl. `POST /_clock/set_current_utc`, default clock `2026-08-01T00:00:00Z`), **38 errors**, **6 roles**.

## §1.8 — 22 rule instances (≥2 per rule, all nine rules)

dual_variant_calc 2 · combinatorial_formula 2 · non_linear_state_machine 3 · transitive_cascade 2 · priority_pair_validation_conflict 3 · boundary_precision_check 3 · cross_entity_state_dependency 3 · resource_temporal_overlap 2 · compensating_invariant 2.

Key pinned literals (all computed by executing the formulas): refund 30000 vs 54000; instructor pay 330090 vs 315894; net revenue 101048 (per-line) vs 101049 (sum-then-round); fee tier 2960/76960 vs the circular 1850/75850; kill fee 71875; fee breakpoint 1000/26000 at exactly 25000 vs 1500/26499 at 24999; CPL 3.0 CEU → 0.5 credits under the 75% cap, 1.5 CEU → 0.5 under 5-year decay.

## §1.9 — 9 sections, 69 instances (56 with recipes, 13 `excluded_because` stubs)

entities 11 · state_machines 9 · calculations 9 · validations 8 · endpoints 5 · errors 14 · rbac 5 · cross_cutting_complexity_layers 7 · consistency_model 1.

## Lint verdict (verbatim)

```
SCAFFOLD §1.8/§1.9 -> §1.5 lint report
============================================================
  SCAFFOLD:           SCAFFOLD.yaml
  Difficulty design:  SCAFFOLD_DIFFICULTY_DESIGN.yaml
  Corner design:      SCAFFOLD_CORNER_DESIGN.yaml

Coverage
  §1.5 endpoints declared:    57
  §1.1 entities declared:     13
  §1.8 instances scanned:     22
  §1.9 instances scanned:     56
  Calls scanned (§1.8+§1.9):  1096

VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
```

Additional self-checks (independent of the linter): zero duplicate instance names across both design files; zero unbound `${var}` placeholders in payloads, path templates, `as_user_id` or asserts; every `excluded_because.difficulty_instance` resolves to a real §1.8 instance name; all 38 error codes are triggered by at least one instance; all 57 endpoints are exercised; no forbidden concurrency vocabulary anywhere; `response_envelope` emitted verbatim; neither design key appears in `SCAFFOLD.yaml`. No sibling task directory was read.

## Step 4: Generate PRD — 2026-08-30T05:42:31.204470605Z

The PRD is complete and all three hard contracts pass.

## Output

`workspace/PRD.md` — 416 lines / 87,447 bytes.

Structure: §1 Introduction (3 paras) → §2 with 10 subsections (2.2 emitted byte-verbatim from `section-2.2-response-structure.md`, confirmed by exact substring match) → §3 with 10 domain subsections → §4 endpoint table (4 columns) → §5 error table (2 columns). File ends at §5 with no audit footer.

## Verified coverage counts

| Scaffold element | Scaffold | In PRD |
|---|---|---|
| Entities | 13 | 13 (all named; 93/93 field names in backticks) |
| State machines | 9 | 9 (all 52 transitions expressed with from/to, preconditions→error_id, side effects) |
| Calculations | 10 | 10 (incl. 6 variant branches: refund policy/pro-rata, pay census/final, and both census-fork arms) |
| Validations | 29 | 29 (full ascending-priority list enumerated in §2.8; conditions scattered into §3) |
| Endpoints | 57 | 57 rows, exact method+path match |
| Errors | 38 | 38 rows; all 38 also referenced in §2/§3 narrative |
| Roles | 6 | 6 (each `identity:` translated — 3 entity-backed, 3 opaque) |

## Hard Contract reports

```
Field coverage check:
- entities[].fields:        93 required, 93 present, 0 missing
- endpoints[].request_body: 49 required, 49 present, 0 missing
- endpoints[].query_params: 23 required, 23 present, 0 missing
Status: PASS
```

```
Rule coverage check:
- validations[] with priority:                29 checked, 29 expressed in prose, 0 missing
- concurrency_rules[] OCC rejections:          2 checked,  2 expressed (write_endpoint + expected_offering_version /
                                               expected_corporate_account_version + ERR_STALE_VERSION/412), 0 missing
- state_machines[].transitions:               52 checked, 52 fully expressed, 0 missing
- calculations[]:                             10 checked, 10 fully expressed (incl. pinned evaluation/rounding order), 0 missing
- validations[] conditions:                   29 checked, 29 matchable to error_id in prose, 0 missing
- endpoints[].side_effects / applies_to:      57 checked, 57 expressed, 0 missing
- entities[].fields[] structured content:     93 checked, 93 reconstructible from prose, 0 missing
- sibling-branch symmetry:                     7 groups checked, 7 with equal prose density, 0 asymmetric
Status: PASS
```

```
Path purity check (§3 only):
- backtick tokens scanned: 883
- tokens starting with `/`: 0
- bare HTTP-method tokens: 0
- method+path combined tokens: 0
Status: PASS
```

Also verified: zero fuzzy/approximating words, zero pseudocode operators (`==`, `>=`, `+=`, `&&`, …) anywhere in §2/§3 prose, all 38 state values and 65 enum members present as exact strings, and 2.2's placeholders (`req_RANDOMALPHANUM123456`, `2025-05-24T10:30:00.123Z`, `"data": { }`) untouched.

Two repairs were made during the contract sweep: the transfer-target compatibility rule (`ERR_TRANSFER_TARGET_INCOMPATIBLE`) was applying to only one of its two `applies_to` endpoints, and a stray "or updated" implied a non-existent course-update endpoint.

Both withheld design indices (`SCAFFOLD_DIFFICULTY_DESIGN.yaml`, `SCAFFOLD_CORNER_DESIGN.yaml`) were never opened, grepped, or referenced.

**Orchestrator verification (independent):** `PRD.md` = 416 lines / 87447 bytes; all five `## ` sections present (§1 L3, §2 L11, §3 L163, §4 L309, §5 L373); 57 endpoint table rows; 38 distinct `ERR_` codes; file terminates cleanly inside the §5 table — no truncation.

## Step 6: Generate implementation — 2026-08-30T05:59:17.546518425Z

Implementation complete at `workspace/implementation/`.

## Files written

| File | Lines | Contents |
|---|---|---|
| `core.py` | 514 | Error catalog (38 ids → HTTP), logical clock (starts `2026-08-01T00:00:00Z`, never falls back to wall clock), in-memory `Store` (13 dicts), `req_`/`meta`/`response_type`/`data` envelope, `limit`/`offset`/`total_count`/`has_more` pagination, `X-User-Role`/`X-User-ID` auth + 6 roles, shape validators, ROUND_HALF_UP Decimal helpers, per-type 404 lookups |
| `calc.py` | 203 | All 10 calculations with their constants (pinned 8-step pricing, per-line-rounded revenue, dual-variant refund, dual-variant instructor pay, kill fee, CEU award, loyalty/CEU ledger, CPL waterfall conversion) |
| `domain.py` | 484 | 13 serializers, derived counters, voucher/sponsor ledger movement + status re-derivation, marketing 3-axis recompute, seat resolution, waitlist promotion / `WAITLIST_ONLY→OPEN` fallback |
| `routes_catalog.py` | 378 | Courses, Offerings, census fork (lock + 4-hop cancellation cascade with kill-fee fan-out), closeout sweeps, registration create |
| `routes_people.py` | 268 | Learners, marketing memberships, instructors, sponsor accounts, deposits, voucher issue/assign/void |
| `routes_reg.py` | 347 | Registration pay/attendance/complete (4-hop completion cascade, certificate minting), instructor contracts, completion records + revoke |
| `routes_flow.py` | 402 | Refund/transfer request create/decide/settle (both arms), CPL petition pathway with segregation of duties, logical clock |
| `app.py` | 73 | Blueprint wiring, error handlers, global request lock, `0.0.0.0:$PORT` |
| `start.sh` / `requirements.txt` | 10 / 1 | Guarded `pip install`, `exec python3 app.py` |

**2,680 lines total. All 57 endpoints implemented** (verified by enumerating Flask's url_map: exactly 57 method+path pairs, matching the PRD §4 table 1:1).

## Boot check
`PORT=18933 bash start.sh` boots in <2s, answers `GET /courses` with HTTP 200 on `0.0.0.0`, and all 8 collection endpoints report `total_count=0` on a fresh process — **no entity seeding anywhere**. Storage is pure Python dicts; no file, SQLite, or /tmp persistence.

## Verification beyond boot
Three end-to-end smoke suites pass against fresh servers, covering: pricing tiers (fee band read off subtotal), OCC 412, voucher commit→consume at census with the `funded = available + unallocated + committed + consumed` identity holding, census-cancel cascade (full refund incl. processing fee, voucher unwind to `ASSIGNED`, kill fees 20000/26000 for ADJUNCT/MASTER), certificate `CEU-2026FA-0001`, attendance gate at exactly 0.8000 passing / 0.7 rejected, instructor pay 126500 under `CENSUS_LOCKED`, transfer settle with residual + `TRANSFERRED_OUT`, per-line revenue rounding, waitlist promotion then `WAITLIST_ONLY→OPEN` fallback, both refund bases diverging (20000 policy vs 18000 pro-rata), half-open instructor adjacency allowed / overlap rejected, closed-interval learner CEU load ceiling, marketing LAPSED override round-trip, segregation of duties 403, and CPL conversion flooring 0.6667 → 0.5.

Two judgement calls worth flagging, both resolved toward the PRD's literal text: (1) `computed_refund_cents` is set to 0 on a DENY (§3.9 "leaves `computed_refund_cents` at 0"); (2) the `OPEN→WAITLIST_ONLY` and `WAITLIST_ONLY→OPEN` auto-transitions carry their own declared `version` increment, so the offering gets +2 on a payment that closes the last seat.

## Step 5: Generate unit tests — 2026-08-30T06:09:22.230891151Z

Test infrastructure and suite are complete and verified.

## Files written

**`test_helpers/`** (2,278 lines)
| File | Lines |
|---|---|
| `__init__.py` | 43 |
| `api_client.py` | 255 (one method per PRD endpoint, 57 endpoints) |
| `api_errors.py` | 90 (38 error ids + HTTP map, registered with framework) |
| `assertions.py` | 238 (per-entity assertions + `assert_sponsor_ledger_conserved`, `assert_voucher_value_conserved`, `assert_certificate_number`, `assert_learner_ceu_ledger`) |
| `constants.py` | 121 |
| `factories.py` | 114 |
| `fixtures.py` | 1,004 (7 tiers: primitives → open section → seated learners → census-locked → issued completion → CPL petitions → sponsor money → multi-section boundary/overlap scenes) |
| `test_users.py` | 53 (`TEST_USERS`, `ANONYMOUS_HEADERS`, per-instance `make_learner_headers` / `make_instructor_headers` / `make_sponsor_headers` / `make_program_admin_headers`) |
| `types.py` | 360 (`CplCitation` correctly omits `updated_at`/`version`) |

**`test_suite/`** (3,669 lines, 11 files + conftest) — `test_01_catalog_and_learner_accounts` (364), `test_02_registration_pricing` (337), `test_03_seats_and_payment` (337), `test_04_census_fork` (257), `test_05_completion_and_ceu` (289), `test_06_instructor_contracting` (289), `test_07_refunds_and_transfers` (604), `test_08_sponsor_voucher_ledger` (350), `test_09_cpl_petitions` (413), `test_10_access_control` (178), `test_11_reads_and_not_found` (200), `conftest.py` (51).

## Coverage

- **Queue A (Difficulty): 44 tests** — all 22 instances across 9 rule ids, exactly 2 tests each.
- **Queue B (Corner): 55 tests** — 55 of the 56 non-stub instances, 1 test each. The 13 `excluded_because:` stubs were verified to cross-reference real difficulty instances and were not translated.
- **Total: 99 tests collected by pytest.**

## Instances skipped

| Instance | Reason |
|---|---|
| `Corner/entities/create_offering_rejects_unknown_status_field_in_body` | Fails the PRD-first filter on both conditions. The PRD's §2.8 rule-3 shape list never states that undeclared/system fields in a body are rejected, and §2.4 states the opposite for the one system field it does discuss — *"Clients never supply an `id`; a client-supplied `id` in a request body is ignored."* Two PRD-only implementers could faithfully ignore a supplied `status` rather than 400 it. Silence-pattern category: `enum-write-pathway` / undeclared-input handling. |

One sub-assertion was also dropped inside otherwise-generated tests: `Learner.marketing_opt_in` echoed on the response after a preference toggle. §3.3 calls `marketing_opt_in` *"a one-time consent flag captured at signup"* while also saying the toggle sends a fresh value, so whether the stored flag is rewritten is not uniquely derivable. The tests assert `marketing_status` and the membership rows instead, which is what the instance's `distinguishing_aspect` actually pins.

## Verification performed

- Every docstring ends with exactly one `Design:` line; all 99 tags resolve to real `name:` entries in the correct index; no stub is translated; no dual tags.
- Every PRD quote (whitespace-normalized) survives a literal substring match against `workspace/PRD.md` — 0 failures.
- No `pytest.mark.skip` / `skipif` / `xfail` anywhere; no "scaffold" or scaffold-section references in generated code.
- `pyflakes` clean; all 11 test modules import successfully; `pytest --collect-only` collects 99 tests.

## Step 7: Run tests and iterate — 2026-08-30T06:16:26.369757014Z

Clean exit: all 8 parallel rounds pass 99/99, with all 99 tests intact.

## Summary

**Iterations run:** 2

**Sweep results**
- Iteration 1 — 8/8 rounds at 98/99. Union of failures across all rounds was a single deterministic test (no flakiness anywhere): `test_04_census_fork.py::TestCensusHeadcountBoundary::test_one_short_of_the_minimum_cancels_the_section`, failing `assert 0 == 2`.
- Iteration 2 — 8/8 rounds at 99/99, zero failures.

**Tests deleted:** none. The single failure passed both STEP 1 sub-checks — PRD §3.6 verbatim-covers the census cancel fork, and the fork's outcome is uniquely derivable — so it resolved at STEP 2 as a test bug rather than a coverage gap.

**Fixes applied to `test_helpers/`:** none. The fixture (`setup_census_headcount_boundary_scene`) constructs preconditions faithfully — its sibling test `test_exactly_the_minimum_headcount_locks_the_section` passes off the same scene.

**Fixes applied to `test_suite/`:**
- `test_suite/test_04_census_fork.py`, `TestCensusHeadcountBoundary::test_one_short_of_the_minimum_cancels_the_section` — the test asserted `paid_enrollment_count == 2` on the *post-cascade* census response. PRD §3.2 defines the counter as "`paid_enrollment_count` is the number whose `enrollment_status` is `ENROLLED` **and** whose `payment_status` is either `PAID` or `VOUCHER_COMMITTED`", and §3.6 hop two moves every such registration to `WITHDRAWN`/`REFUNDED` — so 0 is the PRD-mandated post-cancel value. The assertion mis-translated PRD wording by reading the pre-fork headcount off the post-cascade representation. Fixed by reading the offering *before* the census call and asserting the boundary there, preserving the exact `== 2` evidence the boundary test exists to prove. Added the §3.2 counter-definition quote to the docstring.

**Fixes applied to `implementation/`:** none. `routes_catalog.py::_census_cancel` was already PRD-faithful in decrementing `paid_enrollment_count` as hop two withdraws each seat; weakening it to satisfy the test would have violated the §3.2 counter definition and §2.9's synchronous-counter rule.

**Additional verification**
- Independent quote audit: all 209 `PRD x.y: "..."` docstring quotations across the 99 tests are verbatim (whitespace-normalized) substrings of `workspace/PRD.md`, including the one I added — 0 missing. The suite is genuinely PRD-anchored, not scaffold-anchored.
- No `pytest.mark.skip` / `skipif` / `xfail` anywhere in `test_suite/` or `test_helpers/`.
- No on-disk persistence in `implementation/` — no SQLite, no JSON dump, no file writes; storage is in-memory dicts only.

**Deliverables on disk:** `workspace/implementation/results.{1..8}.json`, all from the final confirming sweep, each recording 99/99.

**Orchestrator verification (independent):** all 8 `results.N.json` re-read — every one reports `passed=99 total=99 failed=0`. Leak probe: none of the §1.8 worked-example literals (330090, 315894, 101048/101049, 71875, 26499, 75850, 76960, 54000) appear hardcoded anywhere in `implementation/*.py` — the near-clean first sweep is not a design-index leak. Persistence probe: no sqlite / json.dump / /tmp / pickle / shelve in the implementation.

## Step 8: Finalize PRD — 2026-08-30T06:19:26.15214790Z

## Result

`PRD.md` and `PRD_FINALIZED.md` are both **416 lines**; **0.0% line delta**. One sentence was inserted inline in §3.6 (~0.4% character delta).

## Adjudication of the `<step_7_diff>` item

I independently re-checked Step 7's call and **mostly** agree — but not entirely, which is why there is one edit.

- The fork comparison, hop-one/hop-two outcomes, and the `WITHDRAWN`/`REFUNDED` cascade are all verbatim in PRD §3.6, and `routes_catalog.py:218-254` matches them exactly. No edit.
- The test bug was real: the fixture (`test_helpers/fixtures.py:733`) is faithful, and `routes_catalog.py::_census_cancel` is PRD-faithful. No impl or fixture edit is warranted.
- **However**, the post-cancel value of `paid_enrollment_count` is only reachable in the PRD by treating §3.2's counter definitions as a standing invariant enforced synchronously per §2.9. That reading is *not* universally true of the implementation: §3.7 carves out completion explicitly (impl agrees), but closeout (`routes_catalog.py:273-297`) also leaves `confirmed_enrollment_count`/`paid_enrollment_count` counting `NO_SHOW` seats with no PRD carve-out. So an implementer who reads the counters as "incremental, adjust only where the PRD says so" would leave the cancelled section at 2, not 0 — and after Step 7's fix, **no test in the suite pins the post-cancel value anymore**. That makes PRD §3.6 the sole determinant, and it was silent.

## Change list

- **§3.6, hop two** — *insert* — added one sentence pinning the section's seat counters as the cancellation cascade unwinds each registration: previously-`ENROLLED` decrements `confirmed_enrollment_count` and `paid_enrollment_count` by 1 each, previously-`WAITLISTED` decrements `waitlist_count` by 1, previously-`PENDING` decrements nothing — `implementation/routes_catalog.py:233-238`

## Pre-edit search log

**Edit 1 — §3.6 hop-two counter maintenance**

(a) **Subject identified:** the `Offering` seat counters `confirmed_enrollment_count`, `paid_enrollment_count`, `waitlist_count` — every place the implementation writes them, not just the census-cancel site.

(b) **Impl paths enumerated** (grepped `paid_enrollment_count|confirmed_enrollment_count|waitlist_count` across all of `implementation/`, then read each hit in context):
- `domain.py:415-433` `seat_resolution` — post-payment: `confirmed +1` and `paid +1`, or `waitlist +1`; `OPEN → WAITLIST_ONLY` on the last seat.
- `domain.py:436-456` `seat_release` — waitlist promotion: `waitlist -1`, `confirmed +1`, `paid +1`; else `WAITLIST_ONLY → OPEN`.
- `routes_catalog.py:152-155` — creation, all counters at 0.
- `routes_catalog.py:200-215` `_census_lock` — **no** counter change (only `VOUCHER_COMMITTED → PAID` and revenue).
- `routes_catalog.py:218-254` `_census_cancel` — the Step 7 site; per-registration decrement keyed on the *pre-hop* `enrollment_status`.
- `routes_catalog.py:273-297` `complete_offering` — decrements `waitlist_count` on `WAITLISTED → WITHDRAWN` but deliberately does **not** decrement `confirmed`/`paid` on `ENROLLED → NO_SHOW`.
- `routes_flow.py:183-184` (refund settle) and `routes_flow.py:207-208` (transfer settle) — `confirmed -1`, `paid -1` on the source section, then `seat_release`.
- `routes_reg.py:131` (completion award) and `routes_reg.py:340` (revocation, `COMPLETED → NO_SHOW`) — **no** counter change.

(c) **Wording adjustment made:** I deliberately scoped the sentence to "**this hop**" of the cancellation cascade rather than restating §3.2's counter definition as an invariant. A general formulation ("the counters always equal their §3.2 definition") would have been a false universal — it contradicts `complete_offering`'s `NO_SHOW` handling and `routes_reg.py`'s completion/revocation paths, creating a brand-new mismatch at three sites Step 7 never exercised. I also keyed the sentence on the registration's status *immediately before the hop* (matching `previous_enrollment` in the impl) rather than on payment status, and explicitly named the `PENDING` no-op, so the sentence describes only what `_census_cancel` does and stays silent about §3.8 closeout, which remains out of scope.

**Orchestrator verification (independent):** `diff PRD.md PRD_FINALIZED.md` shows exactly one changed line (L245) — a single inline sentence added mid-paragraph in §3.6 hop two. No new sections, no other edits.

## Step 9: Complete PRD — 2026-08-30T06:26:33.723921663Z

All edits landed cleanly. `PRD_COMPLETED.md` is written.

## Summary

**Files:** source `workspace/PRD_FINALIZED.md` — 416 lines / 87,834 chars → `workspace/PRD_COMPLETED.md` — 416 lines / 92,282 chars (**+4,448 chars, +0 lines**; every change is an in-paragraph insert or revision, no new paragraphs, no new sections).

**Counts:** 25 edits across 22 paragraphs — **21 ambiguity-pins, 4 mismatch-revisions**.

### Changes

- **§2.1** — insert — ambiguity — a present-but-empty `X-User-ID` counts as missing for `ERR_UNAUTHENTICATED` — `core.py:271`
- **§2.3** — insert — ambiguity — non-integer `limit`/`offset` text is `ERR_INVALID_REQUEST`, not just out-of-range — `core.py:425-438`
- **§2.3** — insert — ambiguity — `created_at` ties broken by creation sequence (routine, since the logical clock is frozen between repositions) — `core.py:206-207`
- **§2.4** — revise — **mismatch** — citation representation is `id`, `petition_id`, `completion_record_id`, `weight`, `created_at` — not "only `id` and `created_at`" — `domain.py:168-175`
- **§3.1** — insert — ambiguity — census-cancel and closeout decrement the parent course's `active_offering_count` and bump its `version` — `routes_catalog.py:270-271, 297-298`; `domain.py:241-247`
- **§3.2** — insert — ambiguity — offering a contract is not gated by section `status`, versions neither section nor instructor; `offering_id` resolves before `instructor_id` — `routes_reg.py:179-180`
- **§3.2** — revise — **mismatch** — the section-state gate binds `DECLINE` as well as `ACCEPT` — `routes_reg.py:229-230`
- **§3.3** — insert — ambiguity — stored `marketing_opt_in` is never rewritten by the preference toggle; only `marketing_status` moves — `routes_people.py:74`
- **§3.3** — insert — ambiguity — a recompute restamps `recomputed_at` and bumps `version` on every row it evaluates even when `state` is unchanged; rows are created only when needed `ACTIVE` — `domain.py:317-331`
- **§3.4** — insert — ambiguity — issuing against a `SUSPENDED` account is `ERR_INVALID_STATE`, after the version guard and before the budget check — `routes_people.py:188-193`
- **§3.4** — revise — ambiguity — voucher-assign check order (ownership first → `ERR_NOT_RESOURCE_OWNER`; then `ISSUED`, account `ACTIVE`, expiry, all `ERR_INVALID_STATE`) — `routes_people.py:238-245`
- **§3.5** — insert — ambiguity — a `voucher_id` sent with `SELF_PAY` is ignored and never resolved (raises no not-found) — `routes_reg.py:54-57`
- **§3.7** — insert — ambiguity — `sessions_attended` is unbounded above by `total_sessions`; no registration- or section-state gate on the write — `routes_reg.py:101-107`
- **§3.8** — insert — ambiguity — the no-show sweep leaves `confirmed_enrollment_count`/`paid_enrollment_count` untouched — `routes_catalog.py:284-286`
- **§3.8** — insert — ambiguity — the `WAITLISTED` sweep decrements `waitlist_count`; `PENDING` decrements nothing; no promotion at closeout — `routes_catalog.py:287-293`
- **§3.9** — revise — **mismatch** — provisional `computed_refund_cents` is exactly 0 for a `TRANSFER`; `refund_basis` is still recorded on transfers — `routes_flow.py:71-74`
- **§3.9** — insert — ambiguity — a `refund_basis` override at decide is persisted onto the request on both arms; omission preserves the recorded basis — `routes_flow.py:129-130, 143-144`
- **§3.9** — insert — ambiguity — a settled refund of exactly zero leaves the money axis at `PAID` while the seat axis still moves to `WITHDRAWN` — `routes_flow.py:176-180`
- **§3.9** — insert — ambiguity — the destination re-check at settle fails with `ERR_INVALID_STATE`, not the incompatibility code — `routes_flow.py:192-193`
- **§3.9** — insert — ambiguity — the destination registration is returned at `version` 1 (price, payment and seat are all part of the single creation) — `routes_flow.py:195-198`
- **§3.10** — revise — **mismatch** — citation representation restated to match the serializer — `domain.py:168-175`
- **§3.10** — insert — ambiguity — citations attach only from `DRAFT`/`REVISION_REQUESTED`; other states are `ERR_INVALID_STATE` — `routes_flow.py:287-288`
- **§3.10** — insert — ambiguity — a petition with no citations is refused `ERR_INVALID_STATE` — `routes_flow.py:310-311`
- **§3.10** — insert — ambiguity — submit checks run in §2.8 priority order (retired course → ineligible citation → duplicate award), not the narrated order — `routes_flow.py:312-325`
- **§3.10** — insert — ambiguity — request-revision preserves an existing `decision_note` when omitted, whereas decide overwrites it (and nulls it) unconditionally — `routes_flow.py:356-357, 381`

### Structural verification (PRD_COMPLETED.md)

- `## ` sections: **5** (§1 Introduction, §2 Global Specifications, §3 Business Logic, §4 Endpoint Definitions, §5 Error Code Catalogue)
- `### ` subsections: **20** (unchanged)
- Endpoint table rows in §4: **57**
- Error table rows in §5: **38**
- Line count: **416**, identical to source — no truncation.

**Orchestrator verification (independent):** PRD.md 87447 chars → PRD_FINALIZED.md 87834 → PRD_COMPLETED.md 92282, all 416 lines. PRD_COMPLETED.md retains 5 `## ` sections, 57 endpoint rows, 38 distinct `ERR_` codes, and terminates cleanly inside the §5 table. `diff PRD_FINALIZED.md PRD_COMPLETED.md` = 22 changed lines, all in-paragraph.

---

# Pipeline complete

All 9 steps finished. Final state: 99/99 tests passing across 8 consecutive parallel stability rounds, 0 tests deleted, 0 implementation fixes required during Step 7.
