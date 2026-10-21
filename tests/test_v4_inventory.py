import pytest

from tapediag.inventory_diff import diff_inventory, inventory_capture


@pytest.fixture
def captures(fixtures):
    return [(fixtures / ("v4/inventory-" + phase + ".txt")).read_text()
            for phase in ("before", "after")]


def test_unique_tag_relocation_is_only_a_candidate(captures):
    result = diff_inventory(*captures, "SYNTH-LIB")
    assert len(result["events"]) == 2
    assert result["relocation_candidates"] == [{
        "barcode": "SYNTH-V4-A", "before": {"kind": "storage", "element": 1},
        "after": {"kind": "drive", "element": 0}}]
    assert not result["warnings"]
    assert result["sources"]


def test_identical_inventory(captures):
    result = diff_inventory(captures[0], captures[0], "SYNTH-LIB")
    assert result["events"] == result["relocation_candidates"] == []


def test_duplicate_tag_never_suggests_move(captures):
    before, after = [s.replace("SYNTH-V4-B", "SYNTH-V4-A") for s in captures]
    result = diff_inventory(before, after, "SYNTH-LIB")
    assert result["ambiguous_tags"] == ["SYNTH-V4-A"]
    assert result["relocation_candidates"] == []
    assert result["warnings"]


def test_empty_element_tag_is_ambiguous(captures):
    captures[1] = captures[1].replace("Storage Element 1:Empty", "Storage Element 1:Empty :VolumeTag=SYNTH-V4-A")
    result = diff_inventory(*captures, "SYNTH-LIB")
    assert not result["relocation_candidates"]
    assert result["ambiguous_tags"]


def test_missing_element_is_unknown_not_removed(captures):
    captures[1] = captures[1].replace("Storage Element 1:Empty\n", "")
    result = diff_inventory(*captures, "SYNTH-LIB")
    assert any(e["kind"] == "unobserved-after" for e in result["events"])
    assert result["relocation_candidates"] == []
    assert any("count differs" in w for w in result["warnings"])


def test_alternate_tag_and_ie_change(captures):
    captures = [s.replace("VolumeTag=SYNTH-V4-A", "AlternateVolumeTag=SYNTH-V4-A") for s in captures]
    captures[1] = captures[1].replace("Storage Element 2:Full", "Storage Element 2 IMPORT/EXPORT:Full")
    result = diff_inventory(*captures, "SYNTH-LIB")
    assert len(result["relocation_candidates"]) == 1
    assert any("type" in e.get("fields", {}) for e in result["events"])


def test_device_change_requires_mapping_review(captures):
    captures[1] = captures[1].replace("/dev/sg40", "/dev/sg41")
    assert any("device labels differ" in w for w in diff_inventory(*captures, "SYNTH-LIB")["warnings"])


@pytest.mark.parametrize("line", ["Storage Element 1:Empty", "Storage Element 1 IMPORT/EXPORT:Empty"])
def test_duplicate_storage_identity_refused(captures, line):
    with pytest.raises(ValueError, match="duplicate"):
        inventory_capture(captures[0] + line)


@pytest.mark.parametrize("text", ["", "junk", "Data Transfer Element 0:Full", "Storage Changer x:no Drives"])
def test_header_required(text):
    with pytest.raises(ValueError, match="header"):
        inventory_capture(text)


@pytest.mark.parametrize("identity", ["", " ", None, [], "a" * 129])
def test_identity_required(captures, identity):
    with pytest.raises(ValueError):
        diff_inventory(*captures, identity)


@pytest.mark.parametrize("value", [None, False, 0, [], {}, ["unexpected"]])
def test_fuzz_regression_nontext_inventory_refused(captures, value):
    with pytest.raises(ValueError, match="must be text"):
        inventory_capture(value)
    with pytest.raises(ValueError, match="must be text"):
        diff_inventory(value, captures[1], "SYNTH-LIB")
    with pytest.raises(ValueError, match="must be text"):
        diff_inventory(captures[0], value, "SYNTH-LIB")


def test_inventory_api_size_bound():
    with pytest.raises(ValueError, match="16 MiB"):
        inventory_capture(" " * (16 * 1024 * 1024 + 1))
