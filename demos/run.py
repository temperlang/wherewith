# /// script
# requires-python = ">=3.11"
# ///
"""Runs Wherewith's example in each language and checks the output matches.

Usage, from anywhere in the repo, after building the libraries:

    temper build -b cpp -b csharp -b java -b js -b lua -b py -b rust
    uv run demos/run.py [LANGUAGE ...]

Each `demos/example/<language>/` builds and runs with that language's usual
tools, as demos/README.md shows; this runs the same commands. Every one
must print exactly `demos/example/expected.txt`. Exits non-zero on any
failure.
"""

import argparse
import difflib
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
EXAMPLE = ROOT / "demos" / "example"

# Commands per language, run in its directory. All but the last only build.
COMMANDS = {
    "cpp": [
        ["cmake", "-B", "build", "-DCMAKE_BUILD_TYPE=Release"],
        ["cmake", "--build", "build", "-j", "2"],
        ["./build/example"],
    ],
    # Building first keeps compiler warnings out of the output. No build
    # servers, which would stay running after.
    "csharp": [
        ["dotnet", "build", "-v", "q", "--nologo", "-nodeReuse:false", "-p:UseSharedCompilation=false"],
        ["dotnet", "run", "--no-build"],
    ],
    "java": [["./gradlew", "-q", "--no-daemon", "run"]],
    # ci, not install: it re-copies the generated library after a rebuild.
    "js": [["npm", "ci", "--silent", "--no-audit", "--no-fund"], ["npm", "start", "--silent"]],
    "lua": [["lua", "-l", "paths", "example.lua"]],
    "py": [["uv", "run", "-q", "example.py"]],
    "rust": [["cargo", "run", "-q", "--release"]],
}


def run_example(language):
    """Builds and runs one language's example, returning its output."""
    dir = EXAMPLE / language
    for args in COMMANDS[language]:
        result = subprocess.run(args, cwd=dir, capture_output=True, encoding="utf-8")
        if result.returncode != 0:
            raise RuntimeError(f"{' '.join(args)} failed:\n{result.stderr}{result.stdout}")
    return result.stdout


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("languages", nargs="*", metavar="LANGUAGE", help=", ".join(COMMANDS))
    languages = parser.parse_args().languages or list(COMMANDS)
    unknown = set(languages) - set(COMMANDS)
    if unknown:
        parser.error(f"unknown: {', '.join(sorted(unknown))}")
    expected = (EXAMPLE / "expected.txt").read_text(encoding="utf-8")
    failed = []
    for language in languages:
        try:
            actual = run_example(language)
        except (RuntimeError, OSError) as error:
            print(f"{language}: error\n{error}")
            failed.append(language)
            continue
        if actual == expected:
            print(f"{language}: ok, {len(actual.splitlines())} lines match")
        else:
            print(f"{language}: output differs")
            diff = difflib.unified_diff(
                expected.splitlines(keepends=True),
                actual.splitlines(keepends=True),
                "expected.txt",
                language,
            )
            sys.stdout.writelines(diff)
            failed.append(language)
    if failed:
        print(f"Failed: {' '.join(failed)}")
        sys.exit(1)


if __name__ == "__main__":
    main()
