# root-qa

Format-aware QA for MUSE-style CERN ROOT files.

The analyzer reads `.root` files with `uproot`, classifies files by TTree and
branch schema, reports duplicate TTree cycles, marks custom C++ object branches
as metadata-only, and samples readable scalar/vector branches for compact QA
statistics.

## Install

From this project directory:

```bash
python3 -m pip install -e .
```

This installs the `root-qa` console script and the required Python packages:
`uproot`, `awkward`, and `numpy`.

You can also run from source without installing:

```bash
python analyze_root_files.py --help
```

## Pixi Install

If this package directory owns the `pixi.toml`, use an editable PyPI path
dependency that points at the project root:

```toml
[workspace]
name = "root-qa"
channels = ["conda-forge"]
platforms = ["osx-arm64"]

[dependencies]
python = "3.12.*"

[pypi-dependencies]
root-qa = { path = ".", editable = true }

[tasks]
help = "root-qa --help"
qa = "root-qa --data-dir ../../data --sample-entries 25 --strict"
quick = "root-qa --config configs/quick.toml --data-dir ../../data"
```

Then run:

```bash
pixi install
pixi run root-qa --help
pixi run qa
```

If the Pixi workspace lives in the parent repo instead, point the path at this
package directory:

```toml
[pypi-dependencies]
root-qa = { path = ".tmp/root_qa", editable = true }
```

`editable = true` is the Pixi equivalent of `pip install -e .`: changes under
`src/root_qa` are picked up without rebuilding or reinstalling the package.

## Run

From this package directory, the parent repo's sample data is at `../../data`:

```bash
python analyze_root_files.py --data-dir ../../data
```

After editable install, use the console script:

```bash
root-qa --data-dir ../../data
```

The default behavior is recursive scanning, latest TTree cycle only, 1000
sampled entries per readable tree, and human-readable output.

## Config Files

TOML config files provide defaults for the same options exposed by the CLI.
Paths in config files are resolved relative to the current working directory,
not relative to the config file.

Available presets:

```bash
root-qa --config configs/quick.toml --data-dir ../../data
root-qa --config configs/full.toml --data-dir ../../data
root-qa --config configs/all_cycles.toml --data-dir ../../data
```

Precedence is:

```text
built-in defaults < TOML config < explicit CLI arguments
```

For example, this uses the quick preset but scans all files:

```bash
root-qa --config configs/quick.toml --data-dir ../../data --max-files 999
```

This uses the all-cycle preset but switches back to latest-cycle analysis:

```bash
root-qa --config configs/all_cycles.toml --data-dir ../../data --latest-cycle-only
```

Supported config keys:

```toml
data_dir = "../../data"
recursive = true
max_files = 4
include_all_cycles = false
sample_entries = 1000
json_stdout = false
# Omit optional keys such as max_files and output when they are not needed.
output = "/tmp/root_qa_report.json"
strict = true
```

## CLI Options

```bash
root-qa --help
```

Important flags:

- `--data-dir PATH`: directory to scan for `.root` files.
- `--top-level-only` / `--recursive`: choose scan depth.
- `--max-files N`: limit sorted files analyzed.
- `--include-all-cycles` / `--latest-cycle-only`: choose ROOT TTree cycle policy.
- `--sample-entries N`: sample size for readable scalar/vector branches.
- `--json` / `--human`: output format for stdout.
- `--output PATH`: always write the full JSON report to a file.
- `--strict` / `--no-strict`: return exit code `1` when QA errors are present.

## Output And Exit Codes

Human output is a compact summary suitable for terminal scans. JSON output keeps
the full structured report, including file metadata, selected trees, branch
classification, branch groups, sampled stats, and issues.

Exit codes:

- `0`: analysis completed.
- `1`: strict mode found QA errors.
- `2`: bad input, bad config, or missing dependencies.
- `3`: one or more ROOT files could not be opened or read usefully.

## ROOT Format Notes

The analyzer intentionally does not deserialize opaque experiment-specific C++
classes such as `ScintHits`, `Vertices`, `museTrackSet`, or `MRTEventInfo`.
Those branches are still reported with tree, branch, type, entry count, and
metadata-only status.

Readable branches are scalar values and vectors of scalar values. For vectors,
the report includes multiplicity statistics so occupancy changes are visible
without fully exporting events.

ROOT files can contain multiple cycles for the same TTree, such as `T;4` and
`T;3`. By default only the latest cycle is analyzed, while older cycles are
reported. Use `--include-all-cycles` when debugging partial or historical tree
cycles.

## Development Checks

Compile source without leaving cache files in the repo:

```bash
python3 - <<'PY'
from pathlib import Path
import py_compile

for path in [Path("analyze_root_files.py"), *sorted(Path("src/root_qa").glob("*.py"))]:
    py_compile.compile(str(path), cfile=f"/tmp/{path.name}.pyc", doraise=True)
    print("compile ok", path)
PY
```

Run baseline checks against the parent repo data:

```bash
python analyze_root_files.py --data-dir ../../data --sample-entries 25 --strict
python analyze_root_files.py --config configs/quick.toml --data-dir ../../data
python analyze_root_files.py --config configs/all_cycles.toml --data-dir ../../data
python analyze_root_files.py --config configs/full.toml --json --output /tmp/root_qa_report.json --data-dir ../../data
```
