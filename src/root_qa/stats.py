"""Sampled numeric QA for readable ROOT branches.

Only scalar branches and vectors of scalar values are sampled here. Branches
backed by opaque experiment classes are reported by schema metadata instead.
"""

from __future__ import annotations

from typing import Any

from root_qa.models import BranchReport, Deps, Issue, safe_float, short_error


class StatsCalculator:
    """Compute compact scalar and vector summaries from awkward arrays."""

    def __init__(self, deps: Deps) -> None:
        self.deps = deps

    def numeric_stats(self, values: Any) -> dict[str, Any]:
        """Return JSON-safe aggregate stats for a flat numeric array."""

        np = self.deps.numpy
        array = np.asarray(values)
        if array.size == 0:
            return {"count": 0}
        if array.dtype.kind not in "biufc":
            return {"count": int(array.size), "dtype": str(array.dtype)}
        finite = array[np.isfinite(array)]
        if finite.size == 0:
            return {"count": int(array.size), "finite_count": 0, "dtype": str(array.dtype)}
        stats = {
            "count": int(array.size),
            "finite_count": int(finite.size),
            "min": safe_float(finite.min()),
            "max": safe_float(finite.max()),
            "mean": safe_float(finite.mean()),
            "std": safe_float(finite.std()),
        }
        if array.dtype.kind == "b":
            stats["true_fraction"] = safe_float(finite.mean())
        return stats

    def awkward_values_to_numpy(self, values: Any) -> Any:
        """Flatten awkward arrays before aggregate stats are calculated."""

        ak = self.deps.awkward
        np = self.deps.numpy
        clean = ak.drop_none(values)
        # axis=None handles both scalar arrays and nested vector branches.
        flat = ak.flatten(clean, axis=None)
        try:
            return ak.to_numpy(flat, allow_missing=False)
        except TypeError:
            return ak.to_numpy(flat)
        except Exception:
            return np.asarray(flat.to_list())

    def summarize_array(self, values: Any, kind: str) -> dict[str, Any]:
        """Summarize scalar values and vector multiplicity for one branch."""

        ak = self.deps.awkward
        np = self.deps.numpy
        summary: dict[str, Any] = {"kind": kind}
        if kind == "vector":
            # Multiplicity is often the most useful QA signal for detector hit
            # vectors: empty events, unusually large events, and occupancy shifts.
            counts = ak.num(values, axis=1)
            count_array = np.asarray(ak.to_numpy(counts))
            multiplicity = self.numeric_stats(count_array)
            multiplicity["nonempty_fraction"] = (
                safe_float((count_array > 0).mean()) if count_array.size else None
            )
            summary["multiplicity"] = multiplicity

        flat = self.awkward_values_to_numpy(values)
        summary["values"] = self.numeric_stats(flat)
        return summary

    def sample_tree(
        self,
        tree: Any,
        readable_branches: list[BranchReport],
        sample_entries: int,
    ) -> tuple[dict[str, Any], list[Issue]]:
        """Sample readable branches from one TTree with a safe fallback path."""

        if sample_entries <= 0 or not readable_branches:
            return {}, []

        names = [branch.name for branch in readable_branches]
        entry_stop = min(sample_entries, int(tree.num_entries))
        stats: dict[str, Any] = {}
        errors: list[Issue] = []

        def summarize_from_arrays(arrays: Any, branch_subset: list[BranchReport]) -> None:
            for branch in branch_subset:
                try:
                    values = arrays[branch.name]
                    stats[branch.name] = self.summarize_array(values, branch.kind)
                except Exception as exc:  # noqa: BLE001
                    errors.append(
                        Issue(
                            "error",
                            "branch",
                            branch.name,
                            f"Could not summarize readable branch: {short_error(exc)}",
                        )
                    )

        try:
            arrays = tree.arrays(names, entry_stop=entry_stop, library="ak")
            summarize_from_arrays(arrays, readable_branches)
            return stats, errors
        except Exception as exc:  # noqa: BLE001
            errors.append(
                Issue(
                    "warning",
                    "tree",
                    getattr(tree, "name", "<tree>"),
                    f"Batch read failed, retrying branch-by-branch: {short_error(exc)}",
                )
            )

        # If one branch breaks a batch read, retry independently so a single
        # problematic branch does not hide stats for the rest of the tree.
        for branch in readable_branches:
            try:
                arrays = tree.arrays([branch.name], entry_stop=entry_stop, library="ak")
                summarize_from_arrays(arrays, [branch])
            except Exception as exc:  # noqa: BLE001
                errors.append(
                    Issue(
                        "error",
                        "branch",
                        branch.name,
                        f"Could not read branch marked as primitive/vector: {short_error(exc)}",
                    )
                )
        return stats, errors
