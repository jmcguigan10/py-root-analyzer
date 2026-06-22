"""Dataset, file, and tree analyzers for ROOT QA.

The analyzers coordinate uproot reads, schema classification, sampled stats,
and issue aggregation while keeping rendering and CLI concerns separate.
"""

from __future__ import annotations

from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from root_qa.models import (
    BranchReport,
    DatasetReport,
    Deps,
    FileReport,
    Issue,
    Options,
    RootKey,
    TreeReport,
    short_error,
)
from root_qa.schema import (
    BranchGroupSummarizer,
    BranchTypeClassifier,
    RootKeySelector,
    TreeFamilyClassifier,
)
from root_qa.stats import StatsCalculator


class TreeAnalyzer:
    """Analyze one selected TTree cycle."""

    def __init__(
        self,
        options: Options,
        branch_classifier: BranchTypeClassifier,
        family_classifier: TreeFamilyClassifier,
        group_summarizer: BranchGroupSummarizer,
        stats_calculator: StatsCalculator,
    ) -> None:
        self.options = options
        self.branch_classifier = branch_classifier
        self.family_classifier = family_classifier
        self.group_summarizer = group_summarizer
        self.stats_calculator = stats_calculator

    def analyze(self, root_file: Any, tree_key: RootKey) -> TreeReport:
        """Build a typed report for one tree without assuming filename layout."""

        tree = root_file[tree_key.key]
        typenames = tree.typenames()
        branch_names = list(tree.keys())
        classification = self.family_classifier.classify(tree_key.name, set(branch_names))
        issues: list[Issue] = []
        branches: list[BranchReport] = []

        # Record every branch before sampling so opaque custom classes still
        # appear in the QA report even when they cannot be deserialized safely.
        for branch_name in branch_names:
            branch = tree[branch_name]
            typename = self.branch_classifier.normalize(
                typenames.get(branch_name, getattr(branch, "typename", ""))
            )
            kind = self.branch_classifier.kind(typename)
            entries = getattr(branch, "num_entries", None)
            entries_match = entries == tree.num_entries if entries is not None else None
            branch_report = BranchReport(
                name=branch_name,
                typename=typename,
                branch_class=getattr(branch, "classname", ""),
                title=getattr(branch, "title", ""),
                entries=int(entries) if entries is not None else None,
                entries_match_tree=entries_match,
                kind=kind,
                readable=self.branch_classifier.is_readable(kind),
            )
            branches.append(branch_report)
            if entries_match is False:
                issues.append(
                    Issue(
                        "error",
                        "branch",
                        branch_name,
                        f"Branch entries {entries} do not match tree entries {tree.num_entries}",
                    )
                )

        if classification.family == "unknown":
            issues.append(
                Issue(
                    "warning",
                    "tree",
                    tree_key.path,
                    "Tree did not match a known MUSE output family",
                )
            )
        for missing in classification.missing_expected_branches:
            issues.append(
                Issue("error", "tree", tree_key.path, f"Missing expected branch {missing}")
            )

        readable = [branch for branch in branches if branch.readable]
        sample_stats, sample_issues = self.stats_calculator.sample_tree(
            tree, readable, self.options.sample_entries
        )
        issues.extend(sample_issues)
        counts_by_kind = Counter(branch.kind for branch in branches)

        return TreeReport(
            key=tree_key.key,
            path=tree_key.path,
            name=tree_key.name,
            cycle=tree_key.cycle,
            entries=int(tree.num_entries),
            branch_count=len(branches),
            family=classification.family,
            confidence=classification.confidence,
            expected_branches=classification.expected_branches,
            missing_expected_branches=classification.missing_expected_branches,
            branch_kind_counts=dict(sorted(counts_by_kind.items())),
            readable_branch_count=sum(1 for branch in branches if branch.readable),
            opaque_branch_count=sum(1 for branch in branches if not branch.readable),
            branches=branches,
            branch_groups=self.group_summarizer.summarize(branches),
            sampled_entries=(
                min(self.options.sample_entries, int(tree.num_entries))
                if self.options.sample_entries > 0
                else 0
            ),
            sample_stats=sample_stats,
            issues=issues,
        )


class FileAnalyzer:
    """Analyze all selected TTrees in one ROOT file."""

    def __init__(self, options: Options, deps: Deps) -> None:
        self.options = options
        self.deps = deps
        self.root_key_selector = RootKeySelector()
        branch_classifier = BranchTypeClassifier()
        self.tree_analyzer = TreeAnalyzer(
            options=options,
            branch_classifier=branch_classifier,
            family_classifier=TreeFamilyClassifier(),
            group_summarizer=BranchGroupSummarizer(),
            stats_calculator=StatsCalculator(deps),
        )

    def analyze(self, path: Path) -> FileReport:
        """Open a ROOT file, select tree cycles, and aggregate file findings."""

        metadata = self._metadata(path)
        status = "ok"
        trees: list[TreeReport] = []
        tree_cycles: dict[str, list[int]] = {}
        object_class_counts: dict[str, int] = {}
        histogram_count = 0
        issues: list[Issue] = []

        try:
            with self.deps.uproot.open(path) as root_file:
                classnames = root_file.classnames(recursive=True)
                tree_keys, cycles_by_path = self.root_key_selector.select(
                    classnames, self.options.include_all_cycles
                )
                # Keep cycle information in the report even when only the
                # latest cycle is analyzed, since older cycles may explain
                # unexpected file size or entry-count differences.
                tree_cycles = {
                    tree_path: sorted(cycles, reverse=True)
                    for tree_path, cycles in sorted(cycles_by_path.items())
                    if len(cycles) > 1
                }
                for tree_path, cycles in tree_cycles.items():
                    issues.append(
                        Issue(
                            "info",
                            "tree",
                            tree_path,
                            f"Multiple TTree cycles present: {cycles}",
                        )
                    )

                # Non-tree objects are not deeply inspected, but class counts
                # make it visible when files contain large histogram payloads.
                non_tree_classes = Counter(
                    classname for classname in classnames.values() if classname != "TTree"
                )
                object_class_counts = dict(sorted(non_tree_classes.items()))
                histogram_count = sum(
                    count
                    for classname, count in non_tree_classes.items()
                    if classname.startswith("TH")
                )

                if not tree_keys:
                    issues.append(Issue("error", "file", str(path), "No TTrees found"))

                for tree_key in tree_keys:
                    try:
                        tree_report = self.tree_analyzer.analyze(root_file, tree_key)
                        trees.append(tree_report)
                        issues.extend(tree_report.issues)
                    except Exception as exc:  # noqa: BLE001
                        issues.append(
                            Issue(
                                "error",
                                "tree",
                                tree_key.key,
                                f"Could not analyze tree: {short_error(exc)}",
                            )
                        )
        except Exception as exc:  # noqa: BLE001
            status = "read_error"
            issues.append(
                Issue(
                    "error",
                    "file",
                    str(path),
                    f"Could not open/read ROOT file: {short_error(exc)}",
                )
            )

        if any(item.severity == "error" for item in issues):
            status = "format_error" if status != "read_error" else status

        return FileReport(
            path=metadata["path"],
            size_bytes=metadata["size_bytes"],
            size_mib=metadata["size_mib"],
            modified_utc=metadata["modified_utc"],
            status=status,
            families=sorted({tree.family for tree in trees}),
            trees=trees,
            tree_cycles=tree_cycles,
            object_class_counts=object_class_counts,
            histogram_count=histogram_count,
            issues=issues,
        )

    def _metadata(self, path: Path) -> dict[str, Any]:
        stat = path.stat()
        return {
            "path": str(path),
            "size_bytes": stat.st_size,
            "size_mib": round(stat.st_size / (1024 * 1024), 3),
            "modified_utc": datetime.fromtimestamp(stat.st_mtime, timezone.utc).isoformat(),
        }


class DatasetAnalyzer:
    """Run QA across every ROOT file selected by the CLI options."""

    def __init__(self, options: Options, deps: Deps) -> None:
        self.options = options
        self.file_analyzer = FileAnalyzer(options, deps)

    def analyze(self) -> DatasetReport:
        """Build the top-level dataset report."""

        files = self.find_root_files()
        file_reports = [self.file_analyzer.analyze(path) for path in files]
        dataset_issues = self.build_dataset_issues(file_reports)
        all_issues = dataset_issues + [
            item for file_report in file_reports for item in file_report.issues
        ]
        error_count = sum(1 for item in all_issues if item.severity == "error")
        warning_count = sum(1 for item in all_issues if item.severity == "warning")
        tree_count = sum(len(file_report.trees) for file_report in file_reports)
        branch_count = sum(
            tree.branch_count for file_report in file_reports for tree in file_report.trees
        )
        readable_count = sum(
            tree.readable_branch_count
            for file_report in file_reports
            for tree in file_report.trees
        )
        opaque_count = sum(
            tree.opaque_branch_count
            for file_report in file_reports
            for tree in file_report.trees
        )

        return DatasetReport(
            generated_at_utc=datetime.now(timezone.utc).isoformat(),
            data_dir=str(self.options.data_dir),
            recursive=self.options.recursive,
            include_all_cycles=self.options.include_all_cycles,
            sample_entries=self.options.sample_entries,
            root_file_count=len(files),
            qa_status="fail" if error_count else "pass",
            totals={
                "size_mib": round(
                    sum(file_report.size_bytes for file_report in file_reports) / (1024 * 1024),
                    3,
                ),
                "trees": tree_count,
                "branches": branch_count,
                "readable_branches": readable_count,
                "opaque_branches": opaque_count,
                "errors": error_count,
                "warnings": warning_count,
                "histograms": sum(file_report.histogram_count for file_report in file_reports),
            },
            issues=all_issues,
            files=file_reports,
        )

    def find_root_files(self) -> list[Path]:
        """Resolve the scan scope without relying on file naming conventions."""

        pattern = "**/*.root" if self.options.recursive else "*.root"
        files = sorted(path for path in self.options.data_dir.glob(pattern) if path.is_file())
        if self.options.max_files is not None:
            return files[: self.options.max_files]
        return files

    def build_dataset_issues(self, files: list[FileReport]) -> list[Issue]:
        """Compare selected tree entry counts against the dataset majority."""

        selected_entries: list[tuple[str, int]] = []
        for file_report in files:
            for tree in file_report.trees:
                selected_entries.append((f"{file_report.path}:{tree.key}", tree.entries))

        if len(selected_entries) <= 1:
            return []

        # The majority count avoids hard-coding a run size while still flagging
        # older cycles or partial outputs when --include-all-cycles is used.
        entry_counts = Counter(entries for _, entries in selected_entries)
        majority_entries, _ = entry_counts.most_common(1)[0]
        issues: list[Issue] = []
        for tree_path, entries in selected_entries:
            if entries != majority_entries:
                issues.append(
                    Issue(
                        "warning",
                        "dataset",
                        tree_path,
                        f"Tree entries {entries} differ from majority entry count {majority_entries}",
                    )
                )
        return issues
