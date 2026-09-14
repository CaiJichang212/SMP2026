# P10 combined fresh confirmation result

## Verdict

The frozen `combined` candidate completed all 48 preregistered confirmation
cases. Its overall paired gain over the original P9 archive was +11.9345 with
a graph/repetition-block bootstrap 95% interval of [8.3180, 15.4579]. However,
the independent and degree-correlated stratum means were negative. The
prespecified requirement that every stratum mean be nonnegative failed, so this
candidate is not qualified for release.

No threshold, selected variant or strategy source changed during confirmation.
Repetitions beyond 1203 were not generated.

## Paired scores

| Stratum vs P9 | Cases | Mean | Minimum | W/T/L |
|---|---:|---:|---:|---:|
| independent | 12 | -0.8909 | -12.9638 | 2/7/3 |
| aligned, 20% contamination | 12 | +29.2899 | -4.2883 | 11/0/1 |
| inverse, 20% contamination | 12 | +20.7874 | -0.4061 | 10/1/1 |
| degree-correlated stress | 12 | -1.4485 | -21.1076 | 1/8/3 |
| overall | 48 | +11.9345 | -21.1076 | 24/16/8 |

All four topology-family means were positive: ER +18.5762, BA +9.6376, WS
+16.6840 and SBM +2.8401. Positive topology and overall means do not override
the two failed response strata.

Against the historical official-best archive, the combined candidate averaged
+19.0408 with 36 wins, 5 ties and 7 losses. This remains a local synthetic
comparison and is not an official-score estimate.

## Execution audit

- 28 complete plans were selected by maximum equal-budget terminal gain; all
  28 prefixes completed, with zero prefix failures and no pending final action.
- Response adaptation activated in 12/12 aligned, 10/12 inverse, 1/12
  independent and 2/12 degree-correlated cases.
- Every arm had zero action, P8-planning and P10-planning failures.
- Every host step emitted zero or one public action; recorded action deltas sum
  to each episode's action count.
- Remaining budgets were nonnegative and response adaptation was never disabled.

The rare independent and degree-correlated response activations show that a
0.95 posterior gate can still select a persona model under out-of-model finite
samples. Other losses occurred when an approved complete structure prefix used
a response assumption that did not match the realized allocation. These are
strategy failures, not missing platform diagnostics.

## Evidence identity

The first collector attempt produced zero rows and failed only while reading a
legacy controller's absent `llm_accepted` diagnostic. After adding compatible
collection and the complete audit schema, the same frozen 48 cases were run
once. This is an instrumentation replay of the original confirmation cohort,
not another holdout.

The ignored full raw evidence SHA-256 is
`ffcbfd38103c4ffd06551036279625efc8402658c5a9a29aed586078278d8ca4`.
The compact report is `p10-combined-confirmation-20260914.json`. The compact
statistical gate is false because `each_stratum_mean_nonnegative` is false.
