# Apply results

Added reusable topology estimator and budget-completion candidate generation.
Added legal cut routing and mandatory single-action structural replanning.
Communication candidates now cover up to12distinct targets instead of multiple
prompt variants for the same target. LLM retains every final action choice.

36 Python3.9 tests pass (before later local transport tests). ZIP build passes
independent extraction/load, reproducibility, Python3.9 syntax, publicAPI AST,
allowlist and actual local credential exclusion checks. V2 SHA256:
38f37e009a82589486a16abd3b71635e68fd8edc98101adfc99deb6d0bdf6206.
Old ZIP e643b36711591c8f3e31a52db80ff0587f1df8277ca9904cf167307c18f5a543 unchanged.

Next Review: actual framework/LLM old-new paired sandbox results, then boundary
tests and final documentation. No official950 claim.
