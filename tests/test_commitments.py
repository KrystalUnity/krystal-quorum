import pytest

from krystal_quorum.commitments import (
    CommitmentCategory,
    CommitmentError,
    extract_commitments,
)


@pytest.mark.parametrize(
    ("heading", "category", "prefix"),
    [
        ("acceptance", CommitmentCategory.ACCEPTANCE, "AC"),
        ("acceptance criteria", CommitmentCategory.ACCEPTANCE, "AC"),
        ("success criteria", CommitmentCategory.ACCEPTANCE, "AC"),
        ("definition of done", CommitmentCategory.ACCEPTANCE, "AC"),
        ("scope", CommitmentCategory.SCOPE, "SCOPE"),
        ("planned scope", CommitmentCategory.SCOPE, "SCOPE"),
        ("implementation scope", CommitmentCategory.SCOPE, "SCOPE"),
        ("implementation map", CommitmentCategory.SCOPE, "SCOPE"),
        ("files", CommitmentCategory.SCOPE, "SCOPE"),
        ("files to change", CommitmentCategory.SCOPE, "SCOPE"),
        ("files and modules", CommitmentCategory.SCOPE, "SCOPE"),
        ("files or modules expected to change", CommitmentCategory.SCOPE, "SCOPE"),
        ("tests", CommitmentCategory.TESTS, "TEST"),
        ("testing", CommitmentCategory.TESTS, "TEST"),
        ("test plan", CommitmentCategory.TESTS, "TEST"),
        ("test strategy", CommitmentCategory.TESTS, "TEST"),
        ("verification", CommitmentCategory.TESTS, "TEST"),
        ("verification plan", CommitmentCategory.TESTS, "TEST"),
        ("tests and verification", CommitmentCategory.TESTS, "TEST"),
        ("rollback", CommitmentCategory.ROLLBACK, "RB"),
        ("rollback plan", CommitmentCategory.ROLLBACK, "RB"),
        ("recovery plan", CommitmentCategory.ROLLBACK, "RB"),
        ("security", CommitmentCategory.SECURITY, "SEC"),
        ("safety", CommitmentCategory.SECURITY, "SEC"),
        ("security and safety", CommitmentCategory.SECURITY, "SEC"),
        ("dependencies", CommitmentCategory.DEPENDENCIES, "DEP"),
        ("migrations", CommitmentCategory.DEPENDENCIES, "DEP"),
        ("dependencies and migrations", CommitmentCategory.DEPENDENCIES, "DEP"),
        ("observability", CommitmentCategory.OBSERVABILITY, "OBS"),
        ("monitoring", CommitmentCategory.OBSERVABILITY, "OBS"),
        ("telemetry", CommitmentCategory.OBSERVABILITY, "OBS"),
    ],
)
def test_extracts_every_normalized_heading_alias(
    heading: str, category: CommitmentCategory, prefix: str
) -> None:
    items = extract_commitments(f"##  {heading.upper()}  :\n- One commitment.\n")

    assert [(item.id, item.category, item.text, item.source_line, item.group) for item in items] == [
        (f"{prefix}-1", category, "One commitment.", 2, None)
    ]


def test_extracts_explicit_and_generated_commitments() -> None:
    plan = """# Plan
## Acceptance Criteria
- [AC-7] CLI exits one for incomplete work.
- JSON includes coverage.
## Tests
### Windows
- TEST-9: Run the CLI on Windows.
  - Include a path containing spaces.
"""

    items = extract_commitments(plan)

    assert [(item.id, item.category.value, item.source_line) for item in items] == [
        ("AC-7", "acceptance", 3),
        ("AC-1", "acceptance", 4),
        ("TEST-9", "tests", 7),
    ]
    assert items[2].group == "Windows"
    assert "Include a path containing spaces." in items[2].text


def test_heading_matching_is_exact_and_sections_close_at_equal_or_higher_levels() -> None:
    plan = """# Plan
## Acceptance Criteria Details
- Do not extract this item.
## Acceptance Criteria
### Runtime
- Extract this item.
## Notes
- Do not extract this item either.
# Appendix
- This is also outside the section.
"""

    items = extract_commitments(plan)

    assert [(item.id, item.text, item.source_line, item.group) for item in items] == [
        ("AC-1", "Extract this item.", 6, "Runtime")
    ]


def test_extracts_only_unnested_unordered_checklist_and_ordered_items() -> None:
    plan = """## Tests
- A bullet commitment.
  - Nested text remains with the bullet.
- [ ] A checklist commitment.
  1. Nested ordered text remains with the checklist.
1. An ordered commitment.
   Continued detail.
"""

    items = extract_commitments(plan)

    assert [(item.id, item.text) for item in items] == [
        ("TEST-1", "A bullet commitment.\n  - Nested text remains with the bullet."),
        (
            "TEST-2",
            "A checklist commitment.\n  1. Nested ordered text remains with the checklist.",
        ),
        ("TEST-3", "An ordered commitment.\n   Continued detail."),
    ]


@pytest.mark.parametrize(("fence", "indent"), [("```", "  "), ("~~~~", "   ")])
def test_ignores_fenced_code_without_changing_commitment_structure(
    fence: str, indent: str
) -> None:
    plan = f"""## Tests
- First real test.
{indent}{fence}python
## Acceptance
- [AC-9] This is code, not a commitment.
{indent}{fence}
- Second real test.
"""

    items = extract_commitments(plan)

    assert [(item.id, item.category, item.source_line) for item in items] == [
        ("TEST-1", CommitmentCategory.TESTS, 2),
        ("TEST-2", CommitmentCategory.TESTS, 7),
    ]
    assert "## Acceptance" in items[0].text
    assert "[AC-9] This is code, not a commitment." in items[0].text


def test_ignores_an_unindented_fence_after_a_blank_line_without_appending_it() -> None:
    plan = """## Tests
- First real test.

```python
## Acceptance
- [AC-9] This is code, not a commitment.
```
- Second real test.
"""

    items = extract_commitments(plan)

    assert [(item.id, item.category, item.text, item.source_line) for item in items] == [
        ("TEST-1", CommitmentCategory.TESTS, "First real test.", 2),
        ("TEST-2", CommitmentCategory.TESTS, "Second real test.", 8),
    ]


@pytest.mark.parametrize("indent", ["", " ", "  ", "   "])
def test_extracts_standalone_list_items_indented_up_to_three_spaces(indent: str) -> None:
    items = extract_commitments(f"## Tests\n{indent}- A standalone test.\n")

    assert [(item.id, item.text, item.source_line) for item in items] == [
        ("TEST-1", "A standalone test.", 2)
    ]


def test_does_not_extract_a_four_space_marker_without_a_parent_item() -> None:
    items = extract_commitments("## Tests\n    - This is not a standalone list item.\n")

    assert items == []


def test_retains_list_markers_nested_under_an_active_parent_item() -> None:
    plan = """## Tests
  - Parent test.
    - Nested detail, not a separate commitment.
  - Another standalone test.
"""

    items = extract_commitments(plan)

    assert [(item.id, item.text, item.source_line) for item in items] == [
        ("TEST-1", "Parent test.\n    - Nested detail, not a separate commitment.", 2),
        ("TEST-2", "Another standalone test.", 4),
    ]


def test_discards_unindented_prose_and_retains_confirmed_indented_continuations() -> None:
    plan = """## Tests
- First test.

  Its indented continuation follows a blank line.

This is section prose, not part of the first test.
- Second test.
"""

    items = extract_commitments(plan)

    assert [(item.id, item.text, item.source_line) for item in items] == [
        ("TEST-1", "First test.\n\n  Its indented continuation follows a blank line.", 2),
        ("TEST-2", "Second test.", 7),
    ]


def test_records_descendant_heading_paths_as_groups() -> None:
    plan = """## Scope
### Platforms
#### Windows
- Support long paths.
"""

    items = extract_commitments(plan)

    assert items[0].group == "Platforms > Windows"


def test_normalizes_crlf_and_preserves_unicode_source_text() -> None:
    plan = "## Security\r\n- Protect cafe\u0301 users.\r\n  Keep \u6f22\u5b57 data intact.\r\n"

    items = extract_commitments(plan)

    assert items[0].text == "Protect cafe\u0301 users.\n  Keep \u6f22\u5b57 data intact."
    assert items[0].source_line == 2


def test_generated_ids_avoid_explicit_id_collisions_in_source_order() -> None:
    plan = """## Acceptance
- [AC-2] Explicit second ID.
- First generated ID.
- Second generated ID.
"""

    items = extract_commitments(plan)

    assert [item.id for item in items] == ["AC-2", "AC-1", "AC-3"]


def test_rejects_duplicate_explicit_ids() -> None:
    plan = """## Acceptance
- [AC-1] First promise.
- [AC-1] Repeated promise.
"""

    with pytest.raises(CommitmentError, match="duplicate explicit commitment ID: AC-1"):
        extract_commitments(plan)


def test_rejects_explicit_ids_from_a_different_category() -> None:
    plan = """## Acceptance
- TEST-1: Wrong category.
"""

    with pytest.raises(
        CommitmentError,
        match="commitment ID TEST-1 does not match acceptance category",
    ):
        extract_commitments(plan)
