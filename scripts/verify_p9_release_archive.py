#!/usr/bin/env python3
"""Verify final ZIP differs from tested assembly only in qualification metadata."""
from __future__ import annotations
import argparse
import ast
import hashlib
import json
from pathlib import Path
import subprocess
import sys
from zipfile import ZipFile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from build_submission import assemble_model, strip_project_imports, verify_p8_release
from starnet.policy.p8_qualification import (
    P8_GATE_REPORT_RELATIVE_PATH, P8_GATE_REPORT_SHA256,
)


_QUALIFICATION_METADATA = {
    "P8_CERTIFIED_MODE", "P8_GATE_REPORT_SHA256", "P8_GATE_REPORT_RELATIVE_PATH",
}


def qualification_structure(source):
    """Normalize only the three approved qualification metadata values."""
    tree = ast.parse(source)
    if (tree.body and isinstance(tree.body[0], ast.Expr)
            and isinstance(tree.body[0].value, ast.Constant)
            and isinstance(tree.body[0].value.value, str)):
        tree.body[0].value = ast.Constant(value="<qualification-docstring>")
    counts = {name: 0 for name in _QUALIFICATION_METADATA}
    for node in tree.body:
        if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            if node.target.id in _QUALIFICATION_METADATA:
                if not isinstance(node.value, ast.Constant) or not (
                    isinstance(node.value.value, str) or node.value.value is None
                ):
                    raise ValueError("qualification metadata must be a string or None literal")
                counts[node.target.id] += 1
                node.value = ast.Constant(value="<qualification-metadata>")
        elif isinstance(node, ast.Assign):
            names = [target.id for target in node.targets if isinstance(target, ast.Name)]
            if len(names) == 1 and names[0] in _QUALIFICATION_METADATA:
                if not isinstance(node.value, ast.Constant) or not (
                    isinstance(node.value.value, str) or node.value.value is None
                ):
                    raise ValueError("qualification metadata must be a string or None literal")
                counts[names[0]] += 1
                node.value = ast.Constant(value="<qualification-metadata>")
    if any(count != 1 for count in counts.values()):
        raise ValueError("qualification metadata fields are incomplete or ambiguous")
    return ast.dump(tree, include_attributes=False)


def require_unique_members(names):
    files = [name for name in names if not name.endswith("/")]
    if len(files) != len(set(files)):
        raise ValueError("archive contains duplicate members")
    return set(files)


def load_current_seal(path, *, relative_path=P8_GATE_REPORT_RELATIVE_PATH,
                      expected_sha256=P8_GATE_REPORT_SHA256):
    gate_report = (ROOT / relative_path).resolve()
    if (path.resolve() != gate_report
            or hashlib.sha256(path.read_bytes()).hexdigest() != expected_sha256):
        raise ValueError("sealed report is not the current qualification evidence")
    evidence = json.loads(path.read_text())
    if (evidence.get("release_gate_passed") is not True
            or evidence.get("release_gate_pending") is not None):
        raise ValueError("qualification evidence is not a completed release seal")
    return evidence


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--archive", type=Path, required=True)
    parser.add_argument("--sealed-report", type=Path, required=True)
    parser.add_argument("--validated-commit", default="539e458")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    verify_p8_release()
    evidence = load_current_seal(args.sealed_report)
    relative = "src/starnet/policy/p8_qualification.py"
    historical = subprocess.check_output(
        ["git", "show", f"{args.validated_commit}:{relative}"], cwd=ROOT,
    )
    if hashlib.sha256(historical).hexdigest() != evidence["source_snapshot"][relative]:
        raise ValueError("qualification source does not match validated snapshot")
    current = (ROOT / relative).read_text()

    if qualification_structure(current) != qualification_structure(historical.decode()):
        raise ValueError("qualification changed outside approved metadata")
    for path, expected in evidence["source_snapshot"].items():
        if path != relative and hashlib.sha256((ROOT / path).read_bytes()).hexdigest() != expected:
            raise ValueError(f"runtime body changed after qualification: {path}")
    final_code = assemble_model()
    before = strip_project_imports(historical.decode(), ROOT / relative)
    after = strip_project_imports(current, ROOT / relative)
    begin = f"# Begin inline: {relative}\n"
    end = f"\n# End inline: {relative}\n\n"
    needle = begin + after + end
    if final_code.count(needle) != 1:
        raise ValueError("ambiguous qualification inline boundary")
    reconstructed = final_code.replace(needle, begin + before + end)
    if hashlib.sha256(reconstructed.encode()).hexdigest() != evidence["validated_unreleased_model_sha256"]:
        raise ValueError("final assembly differs from tested candidate outside metadata")
    with ZipFile(args.archive) as bundle:
        files = require_unique_members(bundle.namelist())
        required = {"config.json", "starnet_model.py"}
        required.update("prompt/" + path.name for path in (ROOT / "src/starnet/submission/prompt").iterdir() if path.is_file())
        if files != required or bundle.read("starnet_model.py") != final_code.encode():
            raise ValueError("archive members or model do not match qualified assembly")
        if bundle.read("config.json") != (ROOT / "src/starnet/submission/config.json").read_bytes():
            raise ValueError("archive configuration differs")
        for name in files:
            if name.startswith("prompt/") and bundle.read(name) != (ROOT / "src/starnet/submission" / name).read_bytes():
                raise ValueError("archive prompt differs")
    result = {"passed": True, "archive": str(args.archive),
              "archive_sha256": hashlib.sha256(args.archive.read_bytes()).hexdigest(),
              "model_sha256": hashlib.sha256(final_code.encode()).hexdigest(),
              "sealed_report_sha256": hashlib.sha256(args.sealed_report.read_bytes()).hexdigest(),
              "validated_commit": args.validated_commit,
              "only_qualification_metadata_changed": True}
    args.output.write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps(result))


if __name__ == "__main__":
    main()
