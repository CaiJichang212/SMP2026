# Public response mixture ledger robustness review

The pure ledger now fails closed for prediction inputs that can appear after a
real action has already succeeded:

- an unknown persona uses a valid target's own observed response when present,
  otherwise it returns the fixed 12.75 prior;
- unknown-persona, nonnumeric and nonfinite observations return `False`, leave
  posterior weights unchanged and are recorded only as rejected diagnostics;
- density support comparisons use a `1e-9` tolerance so floating subtraction at
  registered `r` boundaries 0.2, 0.65, 1.05 and 1.5 is not misclassified;
- public action values and inferred deltas themselves are not rounded or
  widened by this tolerance.

`observe_first` intentionally still has no `node_id`. It cannot detect a caller
submitting the same node twice, so the runtime adapter must call it only for a
successful first communication. Adding identity to the established interface
was deferred rather than changing every caller during controller integration.

No posterior thresholds, model weights, likelihood mixtures or statistical
results were changed, and no new experiment matrix was run.
