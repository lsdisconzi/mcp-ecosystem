"""The one destination rule every staging path shares.

`BUNDLE_LAYOUT` holds two shapes of destination — a folder a source is dropped
into, and a file that *is* the destination — and staging got that wrong for as
long as it existed: `copy_source_into_bundle` created a **directory** named after
the layout template for every key, so staging into ``contract`` produced a
``contract/`` folder beside the real ``contract.json``. Nothing failed. The
bundle simply grew a second home for the same fact, which is the kind of
divergence a manifest hash cannot see because both copies are present and
self-consistent.

These tests are structural on purpose. They do not enumerate the current keys as
a literal list (that would be a second copy of `BUNDLE_LAYOUT`, drifting
silently in exactly the way `SOURCE_DIRECTORY_KINDS` exists to prevent); they
assert the *rule* holds for whatever the layout says today, and they pin the
declared folder set against the shape it claims to describe.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from violation_pack.pack import (
    BUNDLE_LAYOUT,
    SOURCE_DIRECTORY_KINDS,
    copy_source_into_bundle,
    is_layout_kind,
    staged_source_path,
    write_source_into_bundle,
)


# ---------------------------------------------------------------------------
# The declared folder set must describe the real layout
# ---------------------------------------------------------------------------

def test_declared_folder_kinds_are_exactly_the_suffix_free_layout_keys():
    """`SOURCE_DIRECTORY_KINDS` is declared, so it can be pinned — and must be.

    The set is *not* derived from the templates, because "has no suffix" would
    silently misplace a future folder whose name carries a dot (``Legal
    framework.v2``). Declaring it buys the loud failure below instead.
    """
    suffix_free = {key for key, rel in BUNDLE_LAYOUT.items() if Path(rel).suffix == ""}
    assert suffix_free == set(SOURCE_DIRECTORY_KINDS), (
        "a layout key whose template has no suffix is a folder a source is copied "
        "into — either add it to SOURCE_DIRECTORY_KINDS or give its template a "
        "file extension, because the two must agree"
    )


def test_every_folder_kind_really_templates_to_a_folder_name():
    """The declared folders must not name a nested path, or `name` is dropped."""
    for key in SOURCE_DIRECTORY_KINDS:
        template = Path(BUNDLE_LAYOUT[key])
        assert template.parent == Path("."), (
            f"{key} templates to a nested path ({BUNDLE_LAYOUT[key]}); a staged "
            f"source would land beside it, not inside it"
        )
        assert "{violation_id}" not in BUNDLE_LAYOUT[key], (
            f"{key} is declared a folder but its name needs the violation id"
        )


# ---------------------------------------------------------------------------
# is_layout_kind
# ---------------------------------------------------------------------------

def test_is_layout_kind_accepts_every_key_and_nothing_else():
    assert set(BUNDLE_LAYOUT) == {k for k in BUNDLE_LAYOUT if is_layout_kind(k)}
    for refusal in ("", "  ", "transcripts", "Transcripts", None, 0, [], True):
        assert not is_layout_kind(refusal), refusal


# ---------------------------------------------------------------------------
# staged_source_path
# ---------------------------------------------------------------------------

def test_a_folder_kind_keeps_the_source_name(tmp_path):
    root = tmp_path / "build" / "CL-030"
    assert staged_source_path(root, "transcripts_dir", "sentencia.pdf") == (
        root / "Transcripts" / "sentencia.pdf"
    )


def test_a_file_kind_is_the_destination_itself(tmp_path):
    """`contract` means `contract.json` — not a `contract/` folder beside it."""
    root = tmp_path / "build" / "CL-030"
    dest = staged_source_path(root, "contract", "my-contract.json")
    assert dest == root / "contract.json"
    assert dest.is_dir() is False
    # The name it was handed is deliberately ignored: a file key has exactly one
    # home, and two sources staged there are the same fact restated.
    assert staged_source_path(root, "contract", "other.json") == dest


def test_the_violation_id_comes_off_the_bundle_directory_name(tmp_path):
    """``build/CL-030/`` -> ``CL-030``, the same convention `resolve_bundle_dir` uses."""
    assert staged_source_path(tmp_path / "CL-030", "violation_main", "x.json") == (
        tmp_path / "CL-030" / "CL-030.json"
    )
    assert staged_source_path(tmp_path / "BR-001", "element_grid", "x.json") == (
        tmp_path / "BR-001" / "Schema" / "element_grid_BR-001.json"
    )


@pytest.mark.parametrize("name", ["../../../../etc/passwd", "sub/dir/x.md", "./x.md", " .hidden "])
def test_a_staged_name_is_reduced_to_its_basename(tmp_path, name):
    root = tmp_path / "build" / "CL-030"
    dest = staged_source_path(root, "transcripts_dir", name)
    assert dest.parent == root / "Transcripts"
    assert dest.name not in {"", ".", ".."}
    assert root in dest.parents


@pytest.mark.parametrize("name", ["", "   ", ".", "..", "a/..", " . "])
def test_a_staged_name_that_survives_as_nothing_is_refused(tmp_path, name):
    """Rejecting is the point: a nameless staged source has no destination.

    ``"   "`` is in the list because it is a legal file name — it would stage a
    file that no listing can tell apart from the directory it sits in. ``"a/.."``
    is the traversal spelling of ``"."``, which only the basename reduction
    catches.
    """
    with pytest.raises(ValueError):
        staged_source_path(tmp_path / "CL-030", "transcripts_dir", name)


def test_a_kind_that_is_not_a_layout_key_raises(tmp_path):
    with pytest.raises(KeyError):
        staged_source_path(tmp_path / "CL-030", "not_a_kind", "x.md")


# ---------------------------------------------------------------------------
# Both ways in land in the same place
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("kind", sorted(BUNDLE_LAYOUT))
def test_copy_and_upload_agree_on_the_destination(tmp_path, kind):
    """A reviewer who drags a file in and one who picks it out of `data/law`
    must not end up with two different layouts — so one rule, two callers."""
    root = tmp_path / "build" / "CL-030"
    root.mkdir(parents=True)
    source = tmp_path / "data" / "law" / "opinion.md"
    source.parent.mkdir(parents=True)
    source.write_text("the authority", encoding="utf-8")

    copied = copy_source_into_bundle(source, root, kind)
    uploaded = write_source_into_bundle(root, kind, source.name, b"the authority")

    assert copied == staged_source_path(root, kind, source.name)
    assert uploaded == copied
    assert copied.read_text(encoding="utf-8") == "the authority"


def test_staging_a_file_kind_does_not_leave_a_directory_of_that_name(tmp_path):
    """The regression this module was written for, stated as an oracle."""
    root = tmp_path / "build" / "CL-030"
    root.mkdir(parents=True)
    source = tmp_path / "contract.json"
    source.write_text('{"violation_id": "CL-030"}', encoding="utf-8")

    dest = copy_source_into_bundle(source, root, "contract")

    assert dest == root / "contract.json"
    assert (root / "contract.json").is_file()
    assert not (root / "contract").exists(), (
        "a file key is a destination, not a folder — a `contract/` directory here "
        "is the same fact stored twice, and a manifest hash cannot see it"
    )


def test_staging_creates_missing_parent_directories(tmp_path):
    """A fresh bundle has neither `Transcripts/` nor `Schema/` yet."""
    root = tmp_path / "build" / "CL-030"
    root.mkdir(parents=True)
    source = tmp_path / "corte.html"
    source.write_text("<html></html>", encoding="utf-8")

    dest = copy_source_into_bundle(source, root, "transcripts_dir")

    assert dest.is_file()
    assert (root / "Transcripts").is_dir()


# ---------------------------------------------------------------------------
# A staged write must not travel through a symlink
# ---------------------------------------------------------------------------

@pytest.fixture
def bundle_with_a_linked_source(tmp_path):
    """A bundle whose `Legal framework/CPCL.md` is a symlink out of the tree.

    This is the real on-disk convention, not a contrivance:
    ``build/CL-030/Legal framework/CPCL.md -> ../../../data/law/CL/CodigoPenal.md``.
    The bundle references the canonical law file by link so the two cannot drift.
    """
    root = tmp_path / "build" / "CL-030"
    (root / "Legal framework").mkdir(parents=True)
    outside = tmp_path / "data" / "law" / "CL" / "CodigoPenal.md"
    outside.parent.mkdir(parents=True)
    outside.write_text("the real corpus file", encoding="utf-8")
    link = root / "Legal framework" / "CPCL.md"
    link.symlink_to(Path("../../../data/law/CL/CodigoPenal.md"))
    return root, outside, link


def test_copying_onto_a_linked_destination_does_not_write_through_it(tmp_path, bundle_with_a_linked_source):
    """`copy2` follows a destination symlink — straight out of the bundle.

    ``shutil.copy2(src, dest)`` opens ``dest`` for writing, which resolves the
    link, so staging a source whose basename matches a linked entry edits the
    file the link points at. For `Legal framework/` that file is in ``data/law``,
    i.e. **outside the workspace**, and the route would still answer 200 with a
    sha256 of bytes it wrote to a path nobody asked it to touch.
    """
    root, outside, link = bundle_with_a_linked_source
    source = tmp_path / "CPCL.md"
    source.write_text("staged by the reviewer", encoding="utf-8")

    dest = copy_source_into_bundle(source, root, "framework_dir")

    assert dest.read_text(encoding="utf-8") == "staged by the reviewer"
    assert not dest.is_symlink(), "the staged copy is a real file in the bundle"
    assert outside.read_text(encoding="utf-8") == "the real corpus file", (
        "staging must never rewrite the corpus file a bundle symlink points at"
    )


def test_uploading_onto_a_linked_destination_does_not_write_through_it(tmp_path, bundle_with_a_linked_source):
    """The upload path writes with `write_bytes`, which follows links too."""
    root, outside, link = bundle_with_a_linked_source

    dest = write_source_into_bundle(root, "framework_dir", "CPCL.md", b"staged by the reviewer")

    assert dest.read_bytes() == b"staged by the reviewer"
    assert not dest.is_symlink()
    assert outside.read_text(encoding="utf-8") == "the real corpus file"


def test_staging_a_name_that_is_not_linked_still_adds_a_file(tmp_path, bundle_with_a_linked_source):
    """The symlink guard must not turn every sibling into a conflict."""
    root, outside, link = bundle_with_a_linked_source

    dest = write_source_into_bundle(root, "framework_dir", "CC.md", b"a second law")

    assert dest == root / "Legal framework" / "CC.md"
    assert dest.read_bytes() == b"a second law"
    assert link.is_symlink() and link.read_text(encoding="utf-8") == "the real corpus file"
