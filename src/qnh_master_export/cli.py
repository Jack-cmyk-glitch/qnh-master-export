from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

from . import __version__
from .bridge import OpenCLIBridge
from .collector import Collector
from .errors import EmptyResultError, ExportError
from .excel import export_xlsx


def parser():
    root = argparse.ArgumentParser(description="牵牛花商品主档：只读采集、断点续采与 Excel 导出")
    root.add_argument("--version", action="version", version=__version__)
    sub = root.add_subparsers(dest="command", required=True)
    for command in ("clients", "doctor", "pull", "run"):
        item = sub.add_parser(
            command,
            help={
                "clients": "列出浏览器扩展连接（不打印账号资料）",
                "doctor": "验证已登录牵牛花页面的绑定",
                "pull": "采集 JSONL，可断点续跑",
                "run": "采集 JSONL 并导出 Excel",
            }[command],
        )
        item.add_argument("--daemon", default="http://127.0.0.1:19825", help="OpenCLI 本机 HTTP 地址")
        item.add_argument("--client", help="可选的扩展 client ID（需要多 client daemon 支持）")
        if command in ("pull", "run"):
            item.add_argument("--tenant", required=True, help="预期租户 ID；逐条校验")
            item.add_argument("--out", type=Path, help="输出目录；相同目录续采")
            item.add_argument("--gap", type=float, default=1.2, help="请求完成到下一请求的间隔秒数，至少 1.2")
            item.add_argument("--retries", type=int, default=3, help="仅对已完成的 HTTP 5xx 重试，1–5")
    item = sub.add_parser("xlsx", help="从已有 JSONL 离线导出 Excel")
    item.add_argument("--jsonl", required=True, type=Path)
    item.add_argument("--out", type=Path, help="输出 .xlsx 文件路径")
    return root


def main(argv=None):
    args = parser().parse_args(argv)
    try:
        if args.command == "xlsx":
            result = export_xlsx(args.jsonl, args.out or args.jsonl.with_suffix(".xlsx"))
            print(f"SPU {result['spu']} / SKU {result['sku']} → {result['path']}")
            return 0
        bridge = OpenCLIBridge(args.daemon, args.client)
        if args.command == "clients":
            clients = bridge.clients()
            for client in clients:
                # Never print the complete daemon payload (it may include identities).
                print(
                    json.dumps(
                        {"client": client.get("clientId") or "default", "version": client.get("version")},
                        ensure_ascii=False,
                    )
                )
            if not clients:
                raise ExportError("没有在线扩展；请安装并启用 Browser Bridge，然后运行 opencli doctor。")
            return 0
        if args.command == "doctor":
            bridge.bind()
            print("已绑定 qnh.meituan.com/home.html；此检查不验证商品数据权限。")
            return 0
        default_name = "qnh_" + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        target = args.out or Path("exports") / default_name
        raw = Collector(bridge, gap=args.gap, retries=args.retries).collect(tenant=args.tenant, out=target)
        print(f"采集完成 → {raw}")
        if args.command == "run":
            result = export_xlsx(raw, target / "master.xlsx")
            print(f"Excel：SPU {result['spu']} / SKU {result['sku']} → {result['path']}")
        return 0
    except EmptyResultError as exc:
        print(f"空结果：{exc}", file=sys.stderr)
        return 3
    except (ExportError, OSError) as exc:
        print(f"失败：{exc}", file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        print("已中断；使用相同 --out 续采。", file=sys.stderr)
        return 130
