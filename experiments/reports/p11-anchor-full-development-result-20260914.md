# P11 response-anchor full development result

The full anchor screen reused the independently audited original-P11 arm from
the completed 252-case development report and ran only fresh anchor candidates.
The runner re-audited the control raw file and bound it to the separate strict
audit before execution.

The experiment stopped at case 187/252 under its preregistered logical rejection
rule. It is deliberately recorded as `aborted=true`, `complete=false`, and
`development_gate_passed=false`; no metric from the ordered partial cohort is
reported as a complete 252-case estimate.

Rejecting case:

- case: `p9:ws_resampled:901:centered_independent:wide:24.0_7.0_-12.0`
- selected prompt: 1, which is the true best ID
- original frozen P11 score: `692.1816460555559`
- anchor score: `645.1002046487604`
- paired gain: `-47.081441406795534`
- low probe nodes: `[45,37]`; only node 45 was used because it was informative
- ordinary resources: 6 probe budget + 2 anchor budget = 8
- action, prompt identity, public-history replay and planning errors: zero

The failure is not an anchor action rejection or probe-cost accounting error.
The low identification node gave prompt 1 a first-equivalent public response of
`25.505976`. The selected-prompt anchor on node 10 returned `8.867232`. Excluding
the identification magnitude therefore sharply lowered the unknown-node prior.
At action 55 the anchor arm chose `shield 29`, while frozen P11 communicated with
node 23. Frozen P11 finished with 37 communications and no shields; the anchor
arm finished with 25 communications and five shields. The resulting allocation
lost 47.08 terminal units despite a valid anchor and no erased-persuasion event.

This demonstrates the limitation hidden by the 36-case legacy screen: a single
high-influence anchor can be a low response-factor sample. Replacing the low
probe magnitude with that one sample can overcorrect target ranking and open
structure actions too early. The positive first 186 ordered cases cannot
override the fixed worst-pair gate.

No 1401-1403 holdout was opened, and the anchor is not combined with the 0.9
unknown-prior discount. Any future anchor approach would require a separately
registered multi-sample or shrinkage rule rather than selecting a coefficient
from this failed case.

Machine report:
`experiments/reports/p11-anchor-full-development-20260914.json`, SHA-256
`69d9d9cbb19b390c4a9939fd3c88a673e2a573835927f9d048a61a26e75ba9b2`.

Identities:

- original control raw SHA-256: `1a7af53669f16da719217ec8232f558585fdf8da7ac8ef0e2e4a52c8424864d3`
- original strict audit SHA-256: `4676a6dc1823df4ac591faeca02eaf5e5c47765a3544cb76f8aa5c2bcd914cd6`
- anchor source SHA-256: `f75796c6d46ff3cbb6e6461950e517d6cae7e10482a84fd09bb8641c1918c04e`
- runner SHA-256: `03d336cf046e4d30ec42bfa61b4e2fa52aeee5909b7e4a608ddae0d8f6ae7b77`
- partial raw SHA-256: `37ad1f4abf14339f55ab8e5cf322784f7b2b8d505d1f15b2085c2b196a5c05cf`
