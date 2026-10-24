"""Outline interchange: parsing, rendering, and round-tripping."""

import pytest

from src.services.mindmap_outline import parse_outline, to_outline


def titles(children):
    return [c["title"] for c in children]


class TestParse:
    def test_headings_build_a_hierarchy(self):
        out = parse_outline("# Trip\n## Flights\n### Booking\n## Hotels\n")
        assert out["title"] == "Trip"
        assert titles(out["children"]) == ["Flights", "Hotels"]
        assert titles(out["children"][0]["children"]) == ["Booking"]

    def test_skipped_heading_levels_stay_siblings(self):
        """`#` -> `###` -> `###` must not nest the second h3 under the first."""
        out = parse_outline("# T\n### A\n### B\n")
        assert titles(out["children"]) == ["A", "B"]

    def test_returning_to_a_shallower_level(self):
        out = parse_outline("# T\n## A\n#### Deep\n## B\n")
        assert titles(out["children"]) == ["A", "B"]
        assert titles(out["children"][0]["children"]) == ["Deep"]

    def test_bullets_nest_under_the_current_heading(self):
        out = parse_outline("# T\n## Branch\n- one\n  - nested\n- two\n")
        branch = out["children"][0]
        assert titles(branch["children"]) == ["one", "two"]
        assert titles(branch["children"][0]["children"]) == ["nested"]

    def test_tabs_indent_like_two_spaces(self):
        out = parse_outline("# T\n## B\n- one\n\t- nested\n")
        assert titles(out["children"][0]["children"][0]["children"]) == ["nested"]

    def test_bullet_only_outline_needs_no_headings(self):
        out = parse_outline("- Alpha\n  - Beta\n- Gamma\n")
        assert titles(out["children"]) == ["Alpha", "Gamma"]
        assert out["title"] == "Alpha"

    def test_checkboxes_are_captured(self):
        out = parse_outline("# T\n## [x] done\n## [ ] todo\n")
        assert out["children"][0]["checked"] is True
        assert out["children"][1]["checked"] is False
        assert titles(out["children"]) == ["done", "todo"]

    def test_inline_markdown_is_stripped(self):
        out = parse_outline("# T\n## **Bold** and `code`\n- [Link](http://x.com)\n")
        assert out["children"][0]["title"] == "Bold and code"
        assert out["children"][0]["children"][0]["title"] == "Link"

    def test_dash_splits_title_from_description(self):
        out = parse_outline("# T\n- Budget — keep it under 2k\n")
        node = out["children"][0]
        assert node["title"] == "Budget"
        assert node["description"] == "keep it under 2k"

    def test_colon_stays_in_the_title(self):
        out = parse_outline("# T\n## Education: PhD in Physics\n")
        assert out["children"][0]["title"] == "Education: PhD in Physics"

    def test_prose_becomes_the_description(self):
        out = parse_outline("# T\n## Branch\nSome explanation here.\n")
        assert out["children"][0]["description"] == "Some explanation here."

    def test_code_fences_are_ignored(self):
        out = parse_outline("# T\n## Real\n```\n# not a heading\n- not a bullet\n```\n")
        assert titles(out["children"]) == ["Real"]

    def test_later_h1s_are_treated_as_branches(self):
        """Some generators emit every top-level branch as an h1."""
        out = parse_outline("# Map\n# One\n# Two\n")
        assert out["title"] == "Map"
        assert titles(out["children"]) == ["One", "Two"]

    @pytest.mark.parametrize("text", ["", "   \n\n", None])
    def test_empty_input_is_rejected(self, text):
        with pytest.raises(ValueError):
            parse_outline(text)

    def test_prose_only_input_is_rejected_with_guidance(self):
        with pytest.raises(ValueError, match="# Title"):
            parse_outline("just a sentence with no structure")


class TestRoundTrip:
    def _tree(self, children, title="My map"):
        return {"map": {"title": title}, "nodes": [{"children": children}]}

    def test_titles_and_hierarchy_survive(self):
        children = [
            {"title": "Alpha", "description": "", "metadata": {},
             "children": [{"title": "A1", "description": "", "metadata": {}, "children": []}]},
            {"title": "Beta", "description": "", "metadata": {}, "children": []},
        ]
        out = parse_outline(to_outline(self._tree(children)))
        assert out["title"] == "My map"
        assert titles(out["children"]) == ["Alpha", "Beta"]
        assert titles(out["children"][0]["children"]) == ["A1"]

    def test_description_and_checked_survive(self):
        children = [{"title": "Task", "description": "do the thing",
                     "metadata": {"checked": True}, "children": []}]
        out = parse_outline(to_outline(self._tree(children)))
        node = out["children"][0]
        assert node["title"] == "Task"
        assert node["description"] == "do the thing"
        assert node["checked"] is True

    def test_unchecked_nodes_emit_no_task_marker(self):
        """Maps that don't use checkboxes stay clean for other tools."""
        text = to_outline(self._tree(
            [{"title": "Plain", "description": "", "metadata": {}, "children": []}]))
        assert "[ ]" not in text and "[x]" not in text

    def test_depth_beyond_h6_falls_back_to_bullets(self):
        node = {"title": "L7", "description": "", "metadata": {}, "children": []}
        for i in range(6, 0, -1):
            node = {"title": f"L{i}", "description": "", "metadata": {}, "children": [node]}
        text = to_outline(self._tree([node]))
        assert "- L7" in text
        out = parse_outline(text)
        deep = out["children"][0]
        for _ in range(6):
            deep = deep["children"][0]
        assert deep["title"] == "L7"
