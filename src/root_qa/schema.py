"""ROOT schema helpers for MUSE-style output files.

This module intentionally classifies files by TTree and branch structure rather
than by filename, so the analyzer works across run IDs and file sizes.
"""

from __future__ import annotations

import re
from collections import Counter, defaultdict
from typing import Any

from root_qa.models import BranchReport, RootKey, TreeClassification


# uproot reports scalar branch types with a mix of C++ and ROOT spellings.
SCALAR_TYPENAMES = {
    "bool",
    "Bool_t",
    "bool_t",
    "char",
    "signed char",
    "unsigned char",
    "short",
    "unsigned short",
    "int",
    "unsigned int",
    "long",
    "unsigned long",
    "long long",
    "unsigned long long",
    "float",
    "double",
    "Float_t",
    "Double_t",
    "Char_t",
    "UChar_t",
    "Short_t",
    "UShort_t",
    "Int_t",
    "UInt_t",
    "Long_t",
    "ULong_t",
    "Long64_t",
    "ULong64_t",
    "int8_t",
    "uint8_t",
    "int16_t",
    "uint16_t",
    "int32_t",
    "uint32_t",
    "int64_t",
    "uint64_t",
    "float32_t",
    "float64_t",
}

SCINTILLATOR_TREES = {"BH", "BM", "SPS", "TCPV", "VETO"}
VECTOR_RE = re.compile(r"^(?:std::)?vector<(.+)>$")


class RootKeySelector:
    """Select the TTree cycles that should be analyzed."""

    def parse(self, key: str, classname: str) -> RootKey:
        """Split a ROOT key like ``dir/T;4`` into path, tree name, and cycle."""

        base, cycle = key, None
        last_segment = key.rsplit("/", 1)[-1]
        if ";" in last_segment:
            base, cycle_text = key.rsplit(";", 1)
            try:
                cycle = int(cycle_text)
            except ValueError:
                cycle = None
        return RootKey(
            key=key,
            path=base,
            name=base.rsplit("/", 1)[-1],
            cycle=cycle,
            classname=classname,
        )

    def select(
        self, classnames: dict[str, str], include_all_cycles: bool
    ) -> tuple[list[RootKey], dict[str, list[int]]]:
        trees = [
            self.parse(key, classname)
            for key, classname in classnames.items()
            if classname == "TTree"
        ]
        cycles_by_path: dict[str, list[int]] = defaultdict(list)
        for tree in trees:
            if tree.cycle is not None:
                cycles_by_path[tree.path].append(tree.cycle)

        # ROOT files may contain multiple cycles for a tree. The normal QA path
        # analyzes only the latest one while still reporting older cycles.
        if include_all_cycles:
            return sorted(trees, key=lambda tree: (tree.path, -(tree.cycle or 0))), cycles_by_path

        latest: dict[str, RootKey] = {}
        for tree in trees:
            previous = latest.get(tree.path)
            if previous is None or (tree.cycle or 0) > (previous.cycle or 0):
                latest[tree.path] = tree
        return sorted(latest.values(), key=lambda tree: tree.path), cycles_by_path


class BranchTypeClassifier:
    """Map uproot typenames into analyzer-level branch categories."""

    def normalize(self, typename: str | None) -> str:
        if typename is None:
            return ""
        return re.sub(r"\s+", " ", typename.replace("const ", "")).strip()

    def vector_inner_type(self, typename: str) -> str | None:
        """Return the scalar payload type from ``std::vector<T>`` branches."""

        match = VECTOR_RE.match(self.normalize(typename))
        if not match:
            return None
        inner = match.group(1).strip()
        if "," in inner:
            inner = inner.split(",", 1)[0].strip()
        return inner

    def kind(self, typename: str | None) -> str:
        normalized = self.normalize(typename)
        if normalized in SCALAR_TYPENAMES:
            return "scalar"
        inner = self.vector_inner_type(normalized)
        if inner in SCALAR_TYPENAMES:
            return "vector"
        # Custom experiment classes can often be listed by uproot but not safely
        # deserialized without dictionaries, so the analyzer treats them as
        # metadata-only payloads.
        return "opaque"

    def is_readable(self, kind: str) -> bool:
        return kind in {"scalar", "vector"}


class TreeFamilyClassifier:
    """Recognize the MUSE tree families observed in this dataset."""

    def classify(self, tree_name: str, branch_names: set[str]) -> TreeClassification:
        expected: set[str] = set()
        family = "unknown"

        if tree_name in SCINTILLATOR_TREES:
            family = "scintillator_hits"
            expected = {"EventInfo", f"{tree_name}_Hits", f"{tree_name}_PIDs"}
        elif tree_name == "GEM":
            family = "gem_hits"
            expected = {"EventInfo", "GEMhits"}
        elif tree_name == "GEMTracks":
            family = "gem_tracks"
            expected = {"EventInfo", "Tracks"}
        elif tree_name == "STT":
            family = "straw_tube_hits"
            expected = {"EventInfo", "StrawTubeHits"}
        elif tree_name == "PbGlass":
            family = "pbglass_hits"
            expected = {"EventInfo", "PbGlass_Hit"}
        elif tree_name == "Tracked":
            family = "tracked"
            expected = {"EventInfo", "TrackHits", "encrypted"}
        elif tree_name == "Vertex":
            family = "vertex"
            expected = {"EventInfo", "Vertices", "eVertices", "muVertices", "piVertices", "encrypted"}
        elif tree_name == "PathLength":
            family = "pathlength"
            expected = {"EventInfo", "allScattering", "eScattering", "muScattering", "piScattering", "encrypted"}
        elif tree_name == "cs":
            family = "cross_section"
            expected = {"EventInfo", "CSAcceptedEvents", "encrypted"}
        elif tree_name == "MMT":
            family = "mmt_raw_combined"
            expected = {
                "EventInfo",
                "TCPV",
                "BH",
                "VETO",
                "BM",
                "PbGlass",
                "SPS",
                "StrawTube",
                "TestPlane",
                "G_4t",
                "G_US",
                "G_MS",
                "G_DS",
            }
        elif tree_name == "T":
            family = "g4psi_flat_vectors"
            expected = {"EventInfo", "EventID", "EventSeed1", "EventSeed2"}

        missing = sorted(expected - branch_names)
        if family == "g4psi_flat_vectors" and not any(
            name.endswith("_Hit") for name in branch_names
        ):
            missing.append("*_Hit detector branches")

        confidence = "expected" if family != "unknown" and not missing else "partial"
        if family == "unknown":
            confidence = "unknown"

        return TreeClassification(
            family=family,
            confidence=confidence,
            expected_branches=sorted(expected),
            missing_expected_branches=missing,
        )


class BranchGroupSummarizer:
    """Group flat detector branches by ``prefix_suffix`` naming convention."""

    def summarize(self, branches: list[BranchReport]) -> list[dict[str, Any]]:
        groups: dict[str, dict[str, Any]] = {}
        for branch in branches:
            if "_" not in branch.name:
                continue
            # g4psi-style branches encode detector identity in the prefix and
            # measured quantity in the suffix, for example GEM0_GlobalHitX.
            prefix, suffix = branch.name.rsplit("_", 1)
            if not prefix or not suffix:
                continue
            group = groups.setdefault(
                prefix,
                {
                    "prefix": prefix,
                    "branch_count": 0,
                    "readable_count": 0,
                    "scalar_count": 0,
                    "vector_count": 0,
                    "opaque_count": 0,
                    "suffixes": [],
                },
            )
            group["branch_count"] += 1
            group["suffixes"].append(suffix)
            if branch.readable:
                group["readable_count"] += 1
            if branch.kind == "scalar":
                group["scalar_count"] += 1
            elif branch.kind == "vector":
                group["vector_count"] += 1
            else:
                group["opaque_count"] += 1

        rendered = []
        for group in groups.values():
            suffix_counter = Counter(group["suffixes"])
            rendered.append(
                {
                    **{key: value for key, value in group.items() if key != "suffixes"},
                    "suffixes": sorted(suffix_counter),
                }
            )
        return sorted(rendered, key=lambda group: (-group["branch_count"], group["prefix"]))
