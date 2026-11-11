"""SKU-level spreadsheet projection; raw JSONL remains the lossless source."""

from __future__ import annotations

import ast
import json
import re
from datetime import datetime, timezone
from pathlib import Path

from openpyxl import Workbook
from openpyxl.cell import WriteOnlyCell
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter

from .errors import EmptyResultError, ExportError

HEADERS = [
    "SPU编码",
    "商品名称",
    "商品类型",
    "后台商品类目",
    "品牌名称",
    "产地",
    "店内分类",
    "SKU编码",
    "规格名称",
    "商品条码",
    "货品单位",
    "重量",
    "重量单位",
    "箱重换算",
    "总部零售价",
    "基础价",
    "在售状态",
    "美团闪购类目",
    "饿了么类目",
    "京东类目",
    "京东品牌名称",
    "渠道销售属性",
    "SPU标签",
    "SKU标签",
    "覆盖门店数",
    "是否有图",
    "不符渠道规则类型",
    "不符渠道规则备注",
    "必卖",
    "库存自动上架",
    "商品卖点",
    "商品描述",
    "主图数",
    "主图URL",
    "详情图数",
    "详情图URL",
    "特殊图数",
    "配料图(type5)",
    "特殊图明细",
    "视频URL",
    "外部编码",
    "保质期(天)",
    "创建时间(UTC)",
    "更新时间(UTC)",
]
ILLEGAL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f]")
PICTURE_TYPES = {
    3: "实物图",
    4: "包装图",
    5: "配料图",
    6: "营养成分表",
    7: "侧面图",
    8: "背签图",
    9: "logo图",
    10: "资质图",
    12: "证书图",
    13: "医疗器械资质",
    14: "生产许可",
    17: "品牌授权",
    20: "检测报告",
    22: "授权书",
    23: "备案凭证",
    27: "其他资质",
    29: "细节图",
}


def urls(value):
    if not value:
        return []
    if isinstance(value, list):
        return [str(x) for x in value if x]
    try:
        parsed = ast.literal_eval(str(value))
    except (ValueError, SyntaxError):
        parsed = value
    return [str(x) for x in parsed if x] if isinstance(parsed, list) else [str(parsed)]


def labels(items):
    return "; ".join(
        str(x.get("labelName") or x.get("name") or x.get("labelTypeName") or "")
        if isinstance(x, dict)
        else str(x)
        for x in (items or [])
    )


def date_text(value):
    if value is None or value == "":
        return ""
    try:
        return datetime.fromtimestamp(int(value) / 1000, timezone.utc).strftime("%Y-%m-%d %H:%M")
    except (ValueError, TypeError, OverflowError, OSError):
        return ""


def rows_for(record):
    channels = {str(c.get("channelId")): c for c in record.get("spuChannelInfoList") or []}
    category = record.get("backendCategory") or {}
    categories = [
        c["name"]
        for group in record.get("storeFrontCategoryList") or []
        for c in group.get("storeCategoryList") or []
        if c.get("name")
    ]
    main, detail = urls(record.get("picUrlList")), urls(record.get("picContentList"))
    pictures, ingredients, special_count = [], "", 0
    for picture in record.get("mtSpecialPictureList") or []:
        links = urls(picture.get("pictureUrl"))
        if not links:
            continue
        special_count += 1
        kind = picture.get("pictureType")
        label = picture.get("pictureTitle") or PICTURE_TYPES.get(kind, f"type{kind}")
        pictures.append(f"{label}: {', '.join(links)}")
        if kind == 5 and not ingredients:
            ingredients = links[0]
    jd_brand = channels.get("300", {}).get("brandInfo") or {}
    if not isinstance(jd_brand, dict):
        jd_brand = {}
    video = record.get("videoInfo") or {}
    if not isinstance(video, dict):
        video = {}
    tips = record.get("abnormalTips") or ""
    if isinstance(tips, list):
        tips = ", ".join(map(str, tips))
    skus = record.get("skus")
    if skus is not None and not isinstance(skus, list):
        raise ExportError("主档 skus 结构异常。")
    for sku in skus or [{}]:
        if not isinstance(sku, dict):
            raise ExportError("SKU 记录必须是对象。")
        coverage = (sku.get("coverageInfo") or {}).get("storeCoverage") or {}
        price = (sku.get("suggestPrice") or {}).get("tenantSuggestPrice") or {}
        attributes = [
            f"{attr.get('attrName', '')}={attr.get('attrValue', '')}"
            for channel in sku.get("skuChannelInfoList") or []
            for attr in channel.get("saleAttrValueList") or []
        ]
        carton = next(
            (
                x["basicUnitConvertFactor"]
                for x in sku.get("cartonMeasureConvertFactorList") or []
                if x.get("basicUnitConvertFactor") is not None
            ),
            None,
        )
        yield [
            str(record.get("spuId", "")),
            record.get("spuName", ""),
            {1: "单规格", 2: "多规格"}.get(record.get("specType"), record.get("specType")),
            category.get("categoryCodePath") or category.get("categoryCode"),
            (record.get("brand") or {}).get("brandName"),
            record.get("productPlace") or record.get("originPlace"),
            " / ".join(dict.fromkeys(categories)),
            str(sku.get("skuId", "")),
            sku.get("specName"),
            ", ".join(map(str, sku.get("upcList") or [])),
            sku.get("saleUnit"),
            sku.get("weight"),
            sku.get("weightUnit"),
            carton,
            price.get("unifiedSuggestPrice"),
            sku.get("basicPrice"),
            {0: "下架", 1: "在售", 2: "下架"}.get(sku.get("onlineStatus"), sku.get("onlineStatus")),
            *(channels.get(cid, {}).get("categoryCodePath") for cid in ("100", "200", "300")),
            jd_brand.get("brandName"),
            "; ".join(dict.fromkeys(attributes)),
            labels(record.get("labelList")),
            labels(sku.get("skuLabelList")),
            f"{coverage.get('covered', '')}/{coverage.get('total', '')}" if coverage else "",
            "有" if main else "无",
            "; ".join(map(str, record.get("abnormalCodeList") or [])),
            record.get("abnormalMarkMsg") or tips,
            {1: "是", 2: "否"}.get(record.get("mustSale")),
            {0: "否", 1: "是"}.get(record.get("stockAutoShelf")),
            record.get("sellPoint"),
            record.get("description"),
            len(main),
            "\n".join(main),
            len(detail),
            "\n".join(detail),
            special_count,
            ingredients,
            "\n".join(pictures),
            video.get("videoUrl"),
            sku.get("externalCode"),
            sku.get("expirationDays"),
            date_text(record.get("createTime")),
            date_text(record.get("updateTime")),
        ]


def _cells(sheet, values, *, header=False):
    for value in values:
        if isinstance(value, (dict, list)):
            value = json.dumps(value, ensure_ascii=False)
        if isinstance(value, str):
            value = ILLEGAL.sub("", value)
            if len(value) > 32767:
                raise ExportError("字段超过 Excel 单元格 32767 字符限制；请使用完整 JSONL。")
        cell = WriteOnlyCell(sheet, value=value)
        if isinstance(value, str):
            # Explicit text prevents formulas and preserves barcodes/long IDs.
            cell.data_type = "s"
        if header:
            cell.font = Font(bold=True, color="FFFFFF")
            cell.fill = PatternFill("solid", fgColor="22835B")
        cell.alignment = Alignment(vertical="top", wrap_text=True)
        yield cell


def export_xlsx(jsonl, out):
    source, target = Path(jsonl), Path(out)
    if source.resolve() == target.resolve():
        raise ExportError("Excel 输出路径不能覆盖输入 JSONL。")
    if target.suffix.lower() != ".xlsx":
        raise ExportError("Excel 输出文件必须使用 .xlsx 扩展名。")
    # Validate input before opening write-only worksheet XML streams.
    spu_count = sku_count = 0
    try:
        with source.open(encoding="utf-8") as handle:
            for number, line in enumerate(handle, 1):
                if not line.strip():
                    continue
                try:
                    record = json.loads(line)
                except ValueError:
                    raise ExportError(f"JSONL 第 {number} 行格式错误；未跳过该行。") from None
                if not isinstance(record, dict):
                    raise ExportError(f"JSONL 第 {number} 行必须是对象。")
                for row in rows_for(record):
                    # Cell checks also run during validation to avoid partial files.
                    for value in row:
                        if isinstance(value, str) and len(ILLEGAL.sub("", value)) > 32767:
                            raise ExportError("字段超过 Excel 单元格 32767 字符限制；请使用完整 JSONL。")
                    sku_count += 1
                spu_count += 1
    except (TypeError, AttributeError, KeyError):
        raise ExportError("JSONL 字段结构异常；请检查主档接口版本。") from None
    if not spu_count:
        raise EmptyResultError("JSONL 无有效商品记录；未生成 0 行 Excel。")
    if sku_count > 1_048_575:
        raise ExportError("SKU 数超过单工作表容量；请使用 JSONL 分批处理。")
    target.parent.mkdir(parents=True, exist_ok=True)
    workbook = Workbook(write_only=True)
    sheet = workbook.create_sheet("主档SKU级")
    sheet.freeze_panes = "A2"
    for index, name in enumerate(HEADERS, 1):
        sheet.column_dimensions[get_column_letter(index)].width = 42 if "URL" in name else 22
    sheet.append(list(_cells(sheet, HEADERS, header=True)))
    temporary = target.with_name(target.name + ".tmp")
    try:
        with source.open(encoding="utf-8") as handle:
            for line in handle:
                if line.strip():
                    for row in rows_for(json.loads(line)):
                        sheet.append(list(_cells(sheet, row)))
        sheet.auto_filter.ref = f"A1:AR{sku_count + 1}"
        workbook.save(temporary)
        temporary.replace(target)
    finally:
        workbook.close()
        temporary.unlink(missing_ok=True)
    return {"spu": spu_count, "sku": sku_count, "path": str(target)}
