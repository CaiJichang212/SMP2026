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


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--archive", type=Path, required=True)
    parser.add_argument("--sealed-report", type=Path, required=True)
    parser.add_argument("--validated-commit", default="539e458")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    verify_p8_release()
    evidence = json.loads(args.sealed_report.read_text())
    relative = "src/starnet/policy/p8_qualification.py"
    historical = subprocess.check_output(
        ["git", "show", f"{args.validated_commit}:{relative}"], cwd=ROOT,
    )
    if hashlib.sha256(historical).hexdigest() != evidence["source_snapshot"][relative]:
        raise ValueError("qualification source does not match validated snapshot")
    current = (ROOT / relative).read_text()

    def function_bodies(source):
        return [ast.dump(node, include_attributes=False) for node in ast.parse(source).body
                if isinstance(node, (ast.FunctionDef, ast.ClassDef))]

    if function_bodies(current) != function_bodies(historical.decode()):
        raise ValueError("qualification logic changed after entry validation")
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
        files = {name for name in bundle.namelist() if not name.endswith("/")}
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
