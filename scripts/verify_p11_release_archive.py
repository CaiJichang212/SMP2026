#!/usr/bin/env python3
"""Verify P11 metadata-only activation, final ZIP bytes and ZIP execution."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import sys
from zipfile import ZipFile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from scripts import build_submission
from scripts.p11_release_common import (
    qualification_structure, require_unique_archive_members, sha256,
    validate_prompt_entry,
)
from starnet.policy.p11_qualification import (
    P11_GATE_REPORT_RELATIVE_PATH, P11_GATE_REPORT_SHA256,
)


QUALIFICATION = "src/starnet/policy/p11_qualification.py"
MANIFEST = ROOT / "experiments/manifests/p11-release-sources-20260914.json"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--archive", type=Path, required=True)
    parser.add_argument("--activation-report", type=Path, required=True)
    parser.add_argument("--final-entry", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    verifier = getattr(build_submission, "verify_p11_release", None)
    if not callable(verifier):
        raise ValueError("canonical build has no independent P11 release verifier")
    verifier()
    gate_path = (ROOT / str(P11_GATE_REPORT_RELATIVE_PATH)).resolve()
    if (args.activation_report.resolve() != gate_path
            or sha256(args.activation_report) != P11_GATE_REPORT_SHA256):
        raise ValueError("activation report is not current P11 qualification evidence")
    evidence = json.loads(args.activation_report.read_text())
    if (evidence.get("activation_seal_passed") is not True
            or evidence.get("unreleased_entry_gate_passed") is not True
            or evidence.get("release_gate_passed") is not False):
        raise ValueError("P11 activation report is not a sealed pre-ZIP result")
    if not MANIFEST.is_file():
        raise ValueError("P11 source-review manifest is missing")
    manifest = json.loads(MANIFEST.read_text())
    expected_paths = set(build_submission.INLINE_MODULES) | {
        "src/starnet/submission/config.json",
    }
    expected_paths.update(
        str(path.relative_to(ROOT))
        for path in (ROOT / "src/starnet/submission/prompt").glob("*.txt")
    )
    if (manifest.get("activation_report_sha256") != P11_GATE_REPORT_SHA256
            or set(manifest.get("files", {})) != expected_paths):
        raise ValueError("P11 source-review manifest coverage mismatch")
    for relative, expected in manifest["files"].items():
        if sha256(ROOT / relative) != expected:
            raise ValueError(f"P11 reviewed source changed: {relative}")

    historical = subprocess.check_output(
        ["git", "show", f"{evidence['validated_commit']}:{QUALIFICATION}"], cwd=ROOT,
    ).decode()
    current = (ROOT / QUALIFICATION).read_text()
    if hashlib.sha256(historical.encode()).hexdigest() != evidence["source_snapshot"][QUALIFICATION]:
        raise ValueError("P11 historical qualification blob mismatch")
    if qualification_structure(current) != qualification_structure(historical):
        raise ValueError("P11 qualification changed outside sealed metadata")
    for relative, expected in evidence["source_snapshot"].items():
        if relative != QUALIFICATION and sha256(ROOT / relative) != expected:
            raise ValueError(f"P11 strategy changed after activation seal: {relative}")

    final_code = build_submission.assemble_model()
    before = build_submission.strip_project_imports(historical, ROOT / QUALIFICATION)
    after = build_submission.strip_project_imports(current, ROOT / QUALIFICATION)
    begin = f"# Begin inline: {QUALIFICATION}\n"
    end = f"\n# End inline: {QUALIFICATION}\n\n"
    needle = begin + after + end
    if final_code.count(needle) != 1:
        raise ValueError("P11 qualification inline boundary is ambiguous")
    reconstructed = final_code.replace(needle, begin + before + end)
    if hashlib.sha256(reconstructed.encode()).hexdigest() != evidence["validated_unreleased_model_sha256"]:
        raise ValueError("final P11 assembly differs from tested strategy outside metadata")

    with ZipFile(args.archive) as bundle:
        files = require_unique_archive_members(bundle.namelist())
        required = {"config.json", "starnet_model.py"}
        required.update(
            "prompt/" + path.name
            for path in (ROOT / "src/starnet/submission/prompt").iterdir()
            if path.is_file()
        )
        if files != required or bundle.read("starnet_model.py") != final_code.encode():
            raise ValueError("P11 archive members or model differ from canonical assembly")
        if bundle.read("config.json") != (ROOT / "src/starnet/submission/config.json").read_bytes():
            raise ValueError("P11 archive config differs from canonical source")
        for name in files:
            if name.startswith("prompt/") and bundle.read(name) != (
                ROOT / "src/starnet/submission" / name
            ).read_bytes():
                raise ValueError("P11 archive prompt differs from canonical source")

    archive_sha256 = sha256(args.archive)
    final_entry = validate_prompt_entry(
        json.loads(args.final_entry.read_text()),
        hashlib.sha256(final_code.encode()).hexdigest(),
    )
    if (final_entry.get("unreleased_candidate_assembly") is not False
            or final_entry.get("archive_sha256") != archive_sha256
            or final_entry.get("final_zip_execution") is not True):
        raise ValueError("P11 final-entry evidence is not for this ZIP")
    result = {
        "release_gate_passed": True,
        "activation_report_sha256": sha256(args.activation_report),
        "source_manifest_sha256": sha256(MANIFEST),
        "archive": str(args.archive), "archive_sha256": archive_sha256,
        "model_sha256": hashlib.sha256(final_code.encode()).hexdigest(),
        "final_entry_sha256": sha256(args.final_entry),
        "strategy_bytes_match_unreleased_evidence": True,
        "only_p11_qualification_metadata_changed": True,
        "platform_score": None,
    }
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps(result), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
