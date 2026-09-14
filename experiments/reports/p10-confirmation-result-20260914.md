# P10 combined confirmation result

## Decision

The frozen combined candidate **failed** its preregistered statistical gate and
is not eligible for entry sealing, qualification, build integration, packaging,
or production. The release gate remains false. No threshold was changed after
opening repetitions 1201--1203.

The raw 48-case report is stored under ignored `experiments/raw/`. The compact
qualification result is `p10-confirmation-qualification-20260914.json`, whose
raw input hash is
`ffcbfd38103c4ffd06551036279625efc8402658c5a9a29aed586078278d8ca4`.

## Frozen gate

| Component vs P9 | Result | Pass |
| --- | ---: | --- |
| Complete Cartesian cohort | 48 / 48 | yes |
| Mean paired gain | +11.934473 | yes |
| Family-block bootstrap 95% CI | [8.318039, 15.457919] | yes |
| Every stratum mean nonnegative | two negative strata | **no** |
| Positive topology-family means | 4 / 4 | yes |
| Statistical gate | false | **no** |

The primary comparison had 24 wins, 16 ties and 8 losses, ranging from
-21.107570 to +72.920091.

| Stratum vs P9 | Cases | Mean | Win / tie / loss | Minimum |
| --- | ---: | ---: | ---: | ---: |
| independent | 12 | **-0.890878** | 2 / 7 / 3 | -12.963774 |
| aligned contaminated | 12 | +29.289890 | 11 / 0 / 1 | -4.288337 |
| inverse contaminated | 12 | +20.787420 | 10 / 1 / 1 | -0.406125 |
| degree correlated | 12 | **-1.448539** | 1 / 8 / 3 | -21.107570 |

Every topology family had a positive aggregate mean: ER +18.576201, BA
+9.637585, WS +16.683967 and SBM +2.840139. Those aggregates do not override
the two failed response-stratum conditions.

## Runtime audit

The analyzer independently regenerated every seed and replayed 144 complete
candidate/control episodes. It verified scan facts, clipped communication
returns, action legality, per-action budget movement, final component scores,
archive and source hashes, and both paired deltas. It also matched every host
step to zero or one public action.

- Maximum actions in one host step: 1
- Maximum host calls / LLM calls: 88 / 87
- Action or planning failures: 0
- Explicit P10 plan approvals / completed prefixes: 28 / 28
- Prefix failures: 0
- Response gate activations: 25
- Response estimator disablements: 0

For every approved plan, the selected model decision contained the same plan ID
and the first post-scan actions exactly matched the stored structure prefix.
Terminal payloads contained only P10, P8 and PG-reference alternatives, with
PG score/ROI zero and proposal ROI equal to continuation gain divided by current
total budget. The response posterior and activation record were independently
reconstructed from successful public first responses.

## Loss attribution

Three losses activated only the gated-response mechanism:

- BA 1201 aligned: -4.288337, first divergence at action 59.
- ER 1203 independent: -7.018086, a false aligned activation after six
  observations; first divergence at action 57.
- ER 1203 inverse: -0.406125, first divergence at action 58.

Four losses activated only the complete-plan mechanism:

- WS 1201 independent: -12.963774; prefix shields 28, 45 and 47.
- WS 1201 degree-correlated: -2.371457; the same three-shield prefix.
- SBM 1201 independent: -6.770003; prefix cuts 5-9 then shields 25 and 30.
- SBM 1201 degree-correlated: -21.107570; the same cut/shield prefix.

WS 1202 degree-correlated lost -1.702119 with both mechanisms active. Its first
divergence was the three-shield prefix at action 51; the response gate activated
only after 13 observations and switched one later decision. A joint log cannot
identify an additive causal split, so this case is not assigned to one mechanism.

## Historical official-best control

Against `starnet-public-greedy-experimental-20260908.zip`, combined averaged
+19.040764 with 36 wins, 5 ties and 7 losses. Every stratum mean was positive:
independent +1.747810, aligned +38.632988, inverse +22.109864 and
degree-correlated +13.672395. The complete compact report retains every loss by
stratum, topology family and repetition. This secondary result does not repair
the failed primary P9 gate.

## Next experiment boundary

The failure supports two separate hypotheses: plan approval needs a guard for
ordinary independent/degree-correlated response regimes, and the response gate
can become overconfident in an independent sample. Any revised plan or response
gate requires a new protocol and new holdout. Reusing this confirmation cohort
to tune either rule would turn it into development data.
