"""Render typed QA reports as JSON or a readable text format."""

from __future__ import annotations

import json

from root_qa.models import DatasetReport, FileReport, Issue


class JsonReportRenderer:
    """Serialize reports while preserving the public JSON field names."""

    def render(self, report: DatasetReport) -> str:
        return json.dumps(report.to_dict(), indent=2, sort_keys=True)


class HumanReportRenderer:
    """Render a scan-friendly text summary for terminal use."""

    def render(self, report: DatasetReport) -> str:
        """Render the dataset header followed by one block per ROOT file."""

        lines: list[str] = []
        mode = "recursive" if report.recursive else "top-level only"
        lines.append(f"Found {report.root_file_count} .root files under {report.data_dir} ({mode}).")
        lines.append(
            "QA "
            f"{report.qa_status.upper()}: "
            f"{report.totals['trees']} trees, "
            f"{report.totals['branches']} branches, "
            f"{report.totals['readable_branches']} readable, "
            f"{report.totals['opaque_branches']} metadata-only, "
            f"{report.totals['errors']} errors, "
            f"{report.totals['warnings']} warnings"
        )

        dataset_messages = [item for item in report.issues if item.scope == "dataset"]
        for item in dataset_messages[:10]:
            lines.append(f"  {self.format_issue(item)}")
        if len(dataset_messages) > 10:
            lines.append(f"  ... {len(dataset_messages) - 10} more dataset issues")

        if not report.files:
            lines.append("No .root files found.")
            return "\n".join(lines)

        for index, file_report in enumerate(report.files, start=1):
            lines.extend(self.render_file(index, file_report))
        return "\n".join(lines)

    def render_file(self, index: int, file_report: FileReport) -> list[str]:
        """Render one ROOT file and its selected trees."""

        lines: list[str] = [""]
        family_text = ", ".join(file_report.families) if file_report.families else "no_trees"
        lines.append(
            f"[{index}] {file_report.path} "
            f"({file_report.size_mib} MiB, {file_report.status}, {family_text})"
        )

        for tree_path, cycle_list in file_report.tree_cycles.items():
            lines.append(f"    cycles: {tree_path} -> {cycle_list}")

        for tree in file_report.trees:
            counts = tree.branch_kind_counts
            count_text = ", ".join(f"{name}={value}" for name, value in sorted(counts.items()))
            lines.append(
                f"    tree {tree.key}: family={tree.family} "
                f"entries={tree.entries} branches={tree.branch_count} "
                f"({count_text})"
            )
            if tree.missing_expected_branches:
                lines.append(f"      missing: {', '.join(tree.missing_expected_branches)}")

            top_groups = tree.branch_groups[:8]
            if top_groups:
                rendered = ", ".join(
                    f"{group['prefix']}:{group['branch_count']}" for group in top_groups
                )
                lines.append(f"      branch groups: {rendered}")

            if tree.sample_stats:
                shown = list(tree.sample_stats)[:8]
                lines.append(f"      sampled readable branches: {', '.join(shown)}")
                if len(tree.sample_stats) > len(shown):
                    lines.append(f"      ... {len(tree.sample_stats) - len(shown)} more sampled branches")

        visible_issues = [
            item for item in file_report.issues if item.severity in {"error", "warning"}
        ]
        for item in visible_issues[:8]:
            lines.append(f"    {self.format_issue(item)}")
        if len(visible_issues) > 8:
            lines.append(f"    ... {len(visible_issues) - 8} more issues")
        return lines

    def format_issue(self, item: Issue) -> str:
        """Keep issue formatting identical across dataset and file sections."""

        return f"{item.severity.upper()} {item.scope} {item.path}: {item.message}"
