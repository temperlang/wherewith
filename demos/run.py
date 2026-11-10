# /// script
# requires-python = ">=3.11"
# ///
"""Runs Wherewith's example and tour in each language and checks the output matches.

Usage, from anywhere in the repo, after building the libraries:

    temper build -b cpp -b csharp -b java -b js -b lua -b py -b rust
    uv run demos/run.py [LANGUAGE ...]

Each `demos/example/<language>/` and `demos/tour/<language>/` builds and
runs with that language's usual tools, as demos/README.md shows; this runs
the same commands. Every one must print exactly its `expected.txt`.

The tour's Temper is a test in `src/tour-tests.temper.md`, which checks
what it prints against the text in its `tourOutput`, on every backend, in
`temper test`. This checks that text is `demos/tour/expected.txt`, so the
Temper prints what every language prints. Exits non-zero on any failure.
"""

import argparse
import difflib
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DEMOS = ROOT / "demos"
TEMPER_TOUR = ROOT / "src" / "tour-tests.temper.md"

# Each demo, and its program's name in each language.
DEMO_NAMES = {"example": "example", "tour": "tour"}

# Commands per language, run in its directory, for a program `name`. All
# but the last only build.
def commands(language, name):
    return {
        "cpp": [
            ["cmake", "-B", "build", "-DCMAKE_BUILD_TYPE=Release"],
            ["cmake", "--build", "build", "-j", "2"],
            [f"./build/{name}"],
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
        "lua": [["lua", "-l", "paths", f"{name}.lua"]],
        "py": [["uv", "run", "-q", f"{name}.py"]],
        "rust": [["cargo", "run", "-q", "--release"]],
    }[language]


LANGUAGES = ["cpp", "csharp", "java", "js", "lua", "py", "rust"]


def run_demo(demo, language):
    """Builds and runs one language's demo, returning its output."""
    dir = DEMOS / demo / language
    for args in commands(language, DEMO_NAMES[demo]):
        result = subprocess.run(args, cwd=dir, capture_output=True, encoding="utf-8")
        if result.returncode != 0:
            raise RuntimeError(f"{' '.join(args)} failed:\n{result.stderr}{result.stdout}")
    return result.stdout


def temper_text(text):
    """Text as the lines of a Temper multi-line string, with `\\` and `${`
    escaped."""
    lines = (line.replace("\\", "\\\\").replace("${", "\\${") for line in text.splitlines())
    return "".join('      "' + line + "\n" for line in lines)


def check_temper_tour(expected):
    """Whether the Temper tour's `tourOutput` is the tour's expected text.
    Prints what to paste there if not."""
    source = TEMPER_TOUR.read_text(encoding="utf-8")
    start, end = '    let tourOutput = """\n', "    ;\n"
    if start not in source:
        print(f"temper: no tourOutput in {TEMPER_TOUR.relative_to(ROOT)}")
        return False
    at = source.index(start) + len(start)
    want = temper_text(expected)
    if source[at : source.index(end, at)] == want:
        print("temper: ok, its tourOutput is the expected text; temper test checks it prints that")
        return True
    print(f"temper: {TEMPER_TOUR.relative_to(ROOT)}'s tourOutput differs; it should be:\n{start}{want}{end}")
    return False


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("languages", nargs="*", metavar="LANGUAGE", help=", ".join(LANGUAGES))
    languages = parser.parse_args().languages or LANGUAGES
    unknown = set(languages) - set(LANGUAGES)
    if unknown:
        parser.error(f"unknown: {', '.join(sorted(unknown))}")
    failed = []
    for demo in DEMO_NAMES:
        expected = (DEMOS / demo / "expected.txt").read_text(encoding="utf-8")
        if demo == "tour" and not check_temper_tour(expected):
            failed.append("tour (temper)")
        for language in languages:
            try:
                actual = run_demo(demo, language)
            except (RuntimeError, OSError) as error:
                print(f"{demo}, {language}: error\n{error}")
                failed.append(f"{demo} ({language})")
                continue
            if actual == expected:
                print(f"{demo}, {language}: ok, {len(actual.splitlines())} lines match")
            else:
                print(f"{demo}, {language}: output differs")
                diff = difflib.unified_diff(
                    expected.splitlines(keepends=True),
                    actual.splitlines(keepends=True),
                    f"{demo}/expected.txt",
                    language,
                )
                sys.stdout.writelines(diff)
                failed.append(f"{demo} ({language})")
    if failed:
        print(f"Failed: {', '.join(failed)}")
        sys.exit(1)


if __name__ == "__main__":
    main()
