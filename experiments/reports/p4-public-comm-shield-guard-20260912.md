# P4 public comm→shield guard local screen

The guard removes a communication candidate only when the same scanned live
node already has a legal, strictly positive public terminal-gain shield
candidate. It uses scan results, remaining budget, and action returns only.

The guard-disabled runner reproduced PUBLIC_GREEDY exactly (absolute score
difference at most `1e-8`) for every paired seed. All 39 guarded sessions had
zero failed actions.

| Cohort | Pairs | Result |
| --- | ---: | --- |
| existing | 6 families × 3 | BA negative hubs improved in all three repetitions: +47.218, +31.839, +57.445; the remaining 15 pairs tied. Mean pair delta +7.583. |
| independent | 4 families × 3 | All 12 pairs tied; mean delta 0.0. |
| holdout | 3 families × 3 | All 9 pairs tied; mean delta 0.0. |

The baseline made 13 observed comm→shield transitions in the existing cohort;
none occurred in independent or holdout. The guard suppressed 100, 85, and 52
currently dominated communication candidates in existing, independent, and
holdout respectively, without failures.

Conclusion: this is a platform trial candidate, not a promoted default. The
gain is confined to one seed family, so the pre-registered seed-block
bootstrap lower-bound-above-zero requirement has not been demonstrated. The
runtime switch defaults to off and can only be enabled by the selected
`CommanderAgent` persona setting `experimental_public_comm_shield_guard: true`
alongside `experimental_policy_mode: public_greedy`.
