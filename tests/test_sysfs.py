from pathlib import Path

from tapediag.sysfs import inventory_sysfs


def make_device(root, address, pdt, sg=None, tape=None):
    device = root / "devices" / address
    device.mkdir(parents=True)
    for name, value in {"type": str(pdt), "vendor": "SYNTH", "model": "DEMO", "rev": "0001"}.items():
        (device / name).write_text(value + "\n")
    for cls, node in (("scsi_generic", sg), ("scsi_tape", tape)):
        if node:
            entry = root / "class" / cls / node
            entry.mkdir(parents=True)
            (entry / "device").symlink_to(device)
            sibling = device / cls / node
            sibling.mkdir(parents=True)
    return device


def test_sysfs_enumerates_cached_attrs_and_deduplicates(tmp_path):
    make_device(tmp_path, "9:0:1:0", 1, "sg9", "st0")
    make_device(tmp_path, "9:0:2:0", 8, "sg10")
    make_device(tmp_path, "9:0:3:0", 0, "sg11")
    result = inventory_sysfs(tmp_path)
    assert len(result["devices"]) == 2
    by_kind = {d["kind"]: d for d in result["devices"]}
    assert by_kind["drive"]["generic_device"] == "/dev/sg9"
    assert by_kind["drive"]["nonrewinding_device"] == "/dev/nst0"
    assert by_kind["changer"]["address"] == "9:0:2:0"
    assert result["warnings"] == []


def test_sysfs_tape_class_without_sg_and_missing_attributes(tmp_path):
    device = make_device(tmp_path, "9:0:1:0", 1, tape="st0")
    (device / "vendor").unlink()
    result = inventory_sysfs(tmp_path)
    assert result["devices"][0]["generic_device"] is None
    assert result["devices"][0]["vendor"] is None
    assert result["devices"][0]["device"] == "/dev/st0"


def test_missing_sysfs_classes_are_reported(tmp_path):
    result = inventory_sysfs(tmp_path)
    assert not result["devices"] and result["warnings"]
