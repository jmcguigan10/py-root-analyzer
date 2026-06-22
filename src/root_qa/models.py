"""Shared report models for the ROOT QA pipeline.

The analyzer keeps its internal state in frozen dataclasses, then renders the
same JSON-compatible dictionaries as the original single-file script.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any


INSTALL_HINT = "python3 -m pip install uproot awkward numpy"


@dataclass(frozen=True)
class Options:
    """Normalized CLI options used by the analyzers."""

    data_dir: Path
    recursive: bool
    max_files: int | None
    include_all_cycles: bool
    sample_entries: int
    json_stdout: bool
    output: Path | None
    strict: bool


@dataclass(frozen=True)
class RootKey:
    """A parsed ROOT key, including the cycle suffix from names like ``T;4``."""

    key: str
    path: str
    name: str
    cycle: int | None
    classname: str


@dataclass(frozen=True)
class Deps:
    """Runtime imports kept together so analysis code stays easy to test."""

    uproot: Any
    awkward: Any
    numpy: Any


@dataclass(frozen=True)
class Issue:
    """One QA finding with enough context for both text and JSON reports."""

    severity: str
    scope: str
    path: str
    message: str

    def to_dict(self) -> dict[str, str]:
        return {
            "severity": self.severity,
            "scope": self.scope,
            "path": self.path,
            "message": self.message,
        }


@dataclass(frozen=True)
class TreeClassification:
    """Known MUSE tree family match and any missing required branches."""

    family: str
    confidence: str
    expected_branches: list[str]
    missing_expected_branches: list[str]


@dataclass(frozen=True)
class BranchReport:
    """Metadata for one TTree branch after type classification."""

    name: str
    typename: str
    branch_class: str
    title: str
    entries: int | None
    entries_match_tree: bool | None
    kind: str
    readable: bool

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "typename": self.typename,
            "branch_class": self.branch_class,
            "title": self.title,
            "entries": self.entries,
            "entries_match_tree": self.entries_match_tree,
            "kind": self.kind,
            "readable": self.readable,
        }


@dataclass(frozen=True)
class TreeReport:
    """Complete QA result for one selected TTree cycle."""

    key: str
    path: str
    name: str
    cycle: int | None
    entries: int
    branch_count: int
    family: str
    confidence: str
    expected_branches: list[str]
    missing_expected_branches: list[str]
    branch_kind_counts: dict[str, int]
    readable_branch_count: int
    opaque_branch_count: int
    branches: list[BranchReport]
    branch_groups: list[dict[str, Any]]
    sampled_entries: int
    sample_stats: dict[str, Any]
    issues: list[Issue]

    def to_dict(self) -> dict[str, Any]:
        return {
            "key": self.key,
            "path": self.path,
            "name": self.name,
            "cycle": self.cycle,
            "entries": self.entries,
            "branch_count": self.branch_count,
            "family": self.family,
            "confidence": self.confidence,
            "expected_branches": self.expected_branches,
            "missing_expected_branches": self.missing_expected_branches,
            "branch_kind_counts": self.branch_kind_counts,
            "readable_branch_count": self.readable_branch_count,
            "opaque_branch_count": self.opaque_branch_count,
            "branches": [branch.to_dict() for branch in self.branches],
            "branch_groups": self.branch_groups,
            "sampled_entries": self.sampled_entries,
            "sample_stats": self.sample_stats,
            "issues": [issue.to_dict() for issue in self.issues],
        }


@dataclass(frozen=True)
class FileReport:
    """QA result for one ROOT file."""

    path: str
    size_bytes: int
    size_mib: float
    modified_utc: str
    status: str
    families: list[str]
    trees: list[TreeReport]
    tree_cycles: dict[str, list[int]]
    object_class_counts: dict[str, int]
    histogram_count: int
    issues: list[Issue]

    def to_dict(self) -> dict[str, Any]:
        return {
            "path": self.path,
            "size_bytes": self.size_bytes,
            "size_mib": self.size_mib,
            "modified_utc": self.modified_utc,
            "status": self.status,
            "families": self.families,
            "trees": [tree.to_dict() for tree in self.trees],
            "tree_cycles": self.tree_cycles,
            "object_class_counts": self.object_class_counts,
            "histogram_count": self.histogram_count,
            "issues": [issue.to_dict() for issue in self.issues],
        }


@dataclass(frozen=True)
class DatasetReport:
    """Top-level report emitted by CLI and JSON output."""

    generated_at_utc: str
    data_dir: str
    recursive: bool
    include_all_cycles: bool
    sample_entries: int
    root_file_count: int
    qa_status: str
    totals: dict[str, Any]
    issues: list[Issue]
    files: list[FileReport]

    def to_dict(self) -> dict[str, Any]:
        return {
            "generated_at_utc": self.generated_at_utc,
            "data_dir": self.data_dir,
            "recursive": self.recursive,
            "include_all_cycles": self.include_all_cycles,
            "sample_entries": self.sample_entries,
            "root_file_count": self.root_file_count,
            "qa_status": self.qa_status,
            "totals": self.totals,
            "issues": [issue.to_dict() for issue in self.issues],
            "files": [file_report.to_dict() for file_report in self.files],
        }


def safe_float(value: Any) -> float | None:
    """Convert numeric values to JSON-safe finite floats."""

    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    if math.isnan(number) or math.isinf(number):
        return None
    return number


def short_error(exc: BaseException) -> str:
    """Keep exception text compact enough for table-like human reports."""

    message = str(exc).strip().splitlines()
    if not message:
        return exc.__class__.__name__
    return f"{exc.__class__.__name__}: {message[0]}"
