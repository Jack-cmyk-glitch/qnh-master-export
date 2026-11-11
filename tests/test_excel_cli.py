import json
from pathlib import Path

import pytest
from openpyxl import load_workbook

from qnh_master_export.cli import main
from qnh_master_export.errors import ExportError
from qnh_master_export.excel import HEADERS, export_xlsx

DEMO = Path(__file__).resolve().parents[1] / "examples/demo.jsonl"


def test_demo_round_trip_and_text_safety(tmp_path):
    record = json.loads(DEMO.read_text(encoding="utf-8"))
    record["spuName"] = '=HYPERLINK("https://example.invalid", "text")'
    record["spuId"] = "123456789012345678901"
    record["skus"][0]["skuId"] = "00001234567890123456789"
    record["skus"][0]["expirationDays"] = 0
    source = tmp_path / "test.jsonl"
    source.write_text(json.dumps(record, ensure_ascii=False) + "\n", encoding="utf-8")
    target = tmp_path / "test.xlsx"
    result = export_xlsx(source, target)
    assert result["spu"] == 1 and result["sku"] == 2
    workbook = load_workbook(target, data_only=False)
    try:
        sheet = workbook.active
        assert sheet.max_column == 44
        assert [c.value for c in sheet[1]] == HEADERS
        row = dict(zip(HEADERS, sheet[2]))
        assert row["商品名称"].value == record["spuName"]
        assert row["商品名称"].data_type == "s"
        assert row["SPU编码"].value == "123456789012345678901"
        assert row["SKU编码"].value.startswith("0000")
        assert row["商品条码"].value == "0000000000001"
        assert row["总部零售价"].value == 0
        assert row["基础价"].value == 0
        assert row["保质期(天)"].value == 0
        assert row["配料图(type5)"].value == "https://example.invalid/ingredients.jpg"
        assert sheet.freeze_panes == "A2"
        assert sheet.auto_filter.ref == "A1:AR3"
    finally:
        workbook.close()


def test_invalid_line_does_not_silently_drop_or_replace_output(tmp_path):
    source = tmp_path / "invalid.jsonl"
    source.write_text(DEMO.read_text(encoding="utf-8") + "{broken}\n", encoding="utf-8")
    target = tmp_path / "keep.xlsx"
    target.write_bytes(b"existing output")
    with pytest.raises(ExportError, match="第 2 行"):
        export_xlsx(source, target)
    assert target.read_bytes() == b"existing output"


def test_empty_jsonl_fails_without_workbook(tmp_path, capsys):
    source = tmp_path / "empty.jsonl"
    source.write_text("\n", encoding="utf-8")
    assert main(["xlsx", "--jsonl", str(source)]) == 3
    assert "0 行 Excel" in capsys.readouterr().err
    assert not source.with_suffix(".xlsx").exists()


def test_excel_cell_limit_is_explicit(tmp_path):
    record = json.loads(DEMO.read_text(encoding="utf-8"))
    record["description"] = "x" * 32768
    source = tmp_path / "too-long.jsonl"
    source.write_text(json.dumps(record), encoding="utf-8")
    with pytest.raises(ExportError, match="32767"):
        export_xlsx(source, tmp_path / "out.xlsx")
    assert not (tmp_path / "out.xlsx").exists()


def test_cli_offline_example(tmp_path, capsys):
    target = tmp_path / "demo.xlsx"
    assert main(["xlsx", "--jsonl", str(DEMO), "--out", str(target)]) == 0
    assert "SPU 1 / SKU 2" in capsys.readouterr().out
    assert target.exists()


def test_output_cannot_overwrite_input(tmp_path):
    source = tmp_path / "sample.jsonl"
    source.write_text(DEMO.read_text(encoding="utf-8"), encoding="utf-8")
    with pytest.raises(ExportError, match="覆盖输入"):
        export_xlsx(source, source)


def test_unsupported_record_shape_returns_clean_failure(tmp_path, capsys):
    source = tmp_path / "bad.jsonl"
    source.write_text('{"backendCategory":17}', encoding="utf-8")
    assert main(["xlsx", "--jsonl", str(source)]) == 2
    assert "字段结构异常" in capsys.readouterr().err
