"""Command-line boundary for the ROOT QA package."""

from __future__ import annotations

import argparse
import sys
import tomllib
from pathlib import Path
from typing import Any

from root_qa.analyzer import DatasetAnalyzer
from root_qa.models import Deps, INSTALL_HINT, Options
from root_qa.render import HumanReportRenderer, JsonReportRenderer


DEFAULT_OPTIONS = {
    "data_dir": Path("data"),
    "recursive": True,
    "max_files": None,
    "include_all_cycles": False,
    "sample_entries": 1000,
    "json_stdout": False,
    "output": None,
    "strict": False,
}

CONFIG_KEYS = set(DEFAULT_OPTIONS)


class DependencyLoader:
    """Load optional runtime dependencies and report all missing packages."""

    def load(self) -> tuple[Deps | None, list[str]]:
        missing: list[str] = []
        modules: dict[str, Any] = {}
        for name in ("uproot", "awkward", "numpy"):
            try:
                modules[name] = __import__(name)
            except ImportError:
                missing.append(name)
        if missing:
            return None, missing
        return Deps(uproot=modules["uproot"], awkward=modules["awkward"], numpy=modules["numpy"]), []


class ConfigLoader:
    """Load TOML config files that provide CLI defaults."""

    def load(self, path: Path) -> tuple[dict[str, Any] | None, str | None]:
        if not path.exists():
            return None, f"Config file does not exist: {path}"
        if not path.is_file():
            return None, f"Config path is not a file: {path}"
        if path.suffix != ".toml":
            return None, f"Config file must use .toml extension: {path}"

        try:
            with path.open("rb") as config_file:
                raw_config = tomllib.load(config_file)
        except tomllib.TOMLDecodeError as exc:
            return None, f"Could not parse TOML config {path}: {exc}"

        unknown = sorted(set(raw_config) - CONFIG_KEYS)
        if unknown:
            return None, f"Unknown config keys in {path}: {', '.join(unknown)}"

        try:
            return self._coerce(raw_config), None
        except TypeError as exc:
            return None, str(exc)

    def _coerce(self, raw_config: dict[str, Any]) -> dict[str, Any]:
        config = dict(raw_config)
        if "data_dir" in config:
            config["data_dir"] = self._optional_path("data_dir", config["data_dir"])
        if "output" in config:
            config["output"] = self._optional_path("output", config["output"])
        if "max_files" in config:
            config["max_files"] = self._optional_int("max_files", config["max_files"])
        if "sample_entries" in config:
            config["sample_entries"] = self._int("sample_entries", config["sample_entries"])
        for key in ("recursive", "include_all_cycles", "json_stdout", "strict"):
            if key in config and not isinstance(config[key], bool):
                raise TypeError(f"Config key {key} must be a boolean")
        return config

    def _optional_path(self, key: str, value: Any) -> Path | None:
        if value is None:
            return None
        if not isinstance(value, str):
            raise TypeError(f"Config key {key} must be a string or null")
        return Path(value)

    def _optional_int(self, key: str, value: Any) -> int | None:
        if value is None:
            return None
        return self._int(key, value)

    def _int(self, key: str, value: Any) -> int:
        if not isinstance(value, int) or isinstance(value, bool):
            raise TypeError(f"Config key {key} must be an integer")
        return value


class Cli:
    """Parse CLI options, run analysis, render output, and choose exit codes."""

    def parse_args(self, argv: list[str] | None = None) -> Options:
        """Normalize argparse output into the shared Options model."""

        parser = argparse.ArgumentParser(
            description="Run format-aware QA over MUSE-style .root files."
        )
        parser.add_argument(
            "--config",
            default=None,
            type=Path,
            help="TOML config file that provides defaults for this run.",
        )
        parser.add_argument(
            "--data-dir",
            default=None,
            type=Path,
            help="Directory to scan for .root files. Default: data",
        )
        parser.add_argument(
            "--top-level-only",
            dest="recursive",
            action="store_false",
            default=None,
            help="Only scan .root files directly inside --data-dir.",
        )
        parser.add_argument(
            "--recursive",
            dest="recursive",
            action="store_true",
            default=None,
            help="Scan .root files recursively under --data-dir.",
        )
        parser.add_argument(
            "--max-files",
            type=int,
            default=None,
            help="Analyze at most this many .root files after sorting by path.",
        )
        parser.add_argument(
            "--include-all-cycles",
            dest="include_all_cycles",
            action="store_true",
            default=None,
            help="Analyze every TTree key cycle instead of only the latest cycle.",
        )
        parser.add_argument(
            "--latest-cycle-only",
            dest="include_all_cycles",
            action="store_false",
            default=None,
            help="Analyze only the latest cycle for each TTree.",
        )
        parser.add_argument(
            "--sample-entries",
            type=int,
            default=None,
            help="Entries to sample per readable tree for numeric/vector QA. Default: 1000",
        )
        parser.add_argument(
            "--json",
            dest="json_stdout",
            action="store_true",
            default=None,
            help="Print the full report as JSON instead of a human summary.",
        )
        parser.add_argument(
            "--human",
            dest="json_stdout",
            action="store_false",
            default=None,
            help="Print the compact human summary instead of JSON.",
        )
        parser.add_argument(
            "--output",
            type=Path,
            default=None,
            help="Optional path to write the JSON report.",
        )
        parser.add_argument(
            "--strict",
            dest="strict",
            action="store_true",
            default=None,
            help="Exit with code 1 when format errors are detected.",
        )
        parser.add_argument(
            "--no-strict",
            dest="strict",
            action="store_false",
            default=None,
            help="Do not fail the command for format errors.",
        )
        args = parser.parse_args(argv)
        config, error = self.load_config(args.config)
        if error is not None:
            parser.error(error)

        values = dict(DEFAULT_OPTIONS)
        values.update(config)
        for key in CONFIG_KEYS:
            value = getattr(args, key, None)
            if value is not None:
                values[key] = value

        return Options(
            data_dir=values["data_dir"],
            recursive=values["recursive"],
            max_files=values["max_files"],
            include_all_cycles=values["include_all_cycles"],
            sample_entries=max(0, values["sample_entries"]),
            json_stdout=values["json_stdout"],
            output=values["output"],
            strict=values["strict"],
        )

    def load_config(self, path: Path | None) -> tuple[dict[str, Any], str | None]:
        if path is None:
            return {}, None
        config, error = ConfigLoader().load(path)
        if config is None:
            return {}, error
        return config, None

    def run(self, argv: list[str] | None = None) -> int:
        """Execute the full command and return a shell exit code."""

        options = self.parse_args(argv)
        validation_code = self.validate_options(options)
        if validation_code is not None:
            return validation_code

        deps, missing = DependencyLoader().load()
        if deps is None:
            print(
                "Missing required Python packages: "
                f"{', '.join(missing)}\nInstall with: {INSTALL_HINT}",
                file=sys.stderr,
            )
            return 2

        report = DatasetAnalyzer(options, deps).analyze()
        serialized = JsonReportRenderer().render(report)
        if options.output is not None:
            options.output.write_text(serialized + "\n", encoding="utf-8")

        if options.json_stdout:
            print(serialized)
        else:
            print(HumanReportRenderer().render(report))

        if options.strict and report.qa_status == "fail":
            return 1
        if any(file_report.status == "read_error" for file_report in report.files):
            return 3
        return 0

    def validate_options(self, options: Options) -> int | None:
        """Validate filesystem inputs before importing heavy analysis deps."""

        if not options.data_dir.exists():
            print(f"Data directory does not exist: {options.data_dir}", file=sys.stderr)
            return 2
        if not options.data_dir.is_dir():
            print(f"Data path is not a directory: {options.data_dir}", file=sys.stderr)
            return 2
        return None


def main(argv: list[str] | None = None) -> int:
    """Entrypoint used by the compatibility wrapper."""

    return Cli().run(argv)
