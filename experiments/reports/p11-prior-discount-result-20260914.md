# P11 unknown-node prior discount development result

The development-only `0.9` transfer-prior discount passed all four preregistered
screens on 36 paired executions. It changes only the response magnitude predicted
for a node that has no selected-prompt observation. A concrete node's observed
response remains unscaled.

| Metric | Result | Gate |
| --- | ---: | ---: |
| Mean discounted P11 gain over frozen P11 | +4.750208 | > +1 |
| Prompt-1-best group mean | +4.750208 | > 0 |
| Nonnegative topology-family means | 5 / 6 | >= 4 / 6 |
| Worst paired gain | -7.933781 | >= -10 |
| Win / tie / loss | 18 / 12 / 6 | descriptive |

The six prompt permutations have the same gain within each topology. This is
expected because both arms identify the same best prompt and spend the same
probe budget; the experiment isolates transfer-magnitude shrinkage rather than
prompt identification. Family means were ER `+15.498763`, BA `0`, WS
`-7.933781`, SBM negative bridges `+14.976080`, SBM violent cluster `0`, and
three sparse components `+5.960188`.

This is an internal P11 parameter screen, not evidence that P11 as a whole beats
the no-probe P9 archive and not an official-score estimate. Production remains
disabled until the separately frozen full-policy development and confirmation
gates pass. Compact machine-readable evidence is in
`p11-prior-discount-development-20260914.json`; full action traces remain under
`experiments/raw/` and are not submitted.
