from __future__ import annotations

import hashlib
import json
import math
import os
import time
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

from .bridge import MASTER_PATH
from .errors import EmptyResultError, ExportError, RetryableError

PAGE_SIZE = 100


def timestamp():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def atomic_write(path, text):
    path = Path(path)
    temporary = path.with_name(path.name + ".tmp")
    with temporary.open("w", encoding="utf-8", newline="\n") as handle:
        handle.write(text)
        handle.flush()
        os.fsync(handle.fileno())
    temporary.replace(path)


@contextmanager
def output_lock(directory):
    lock = directory / ".collect.lock"
    try:
        fd = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    except FileExistsError:
        raise ExportError("输出目录已锁定；确认没有采集进程后，才可移除 .collect.lock。") from None
    try:
        with os.fdopen(fd, "w") as handle:
            handle.write(str(os.getpid()))
        yield
    finally:
        lock.unlink(missing_ok=True)


class Collector:
    def __init__(self, source, *, gap=1.2, retries=3, log=print, sleep=time.sleep, clock=time.monotonic):
        if not math.isfinite(gap) or gap < 1.2 or not 1 <= retries <= 5:
            raise ExportError("请求间隔必须 >= 1.2 秒，重试次数必须在 1–5 之间。")
        self.source, self.gap, self.retries = source, gap, retries
        self.log, self.sleep, self.clock = log, sleep, clock
        self.last_request = None

    def fetch(self, page):
        for attempt in range(self.retries):
            if self.last_request is not None:
                self.sleep(max(0, self.gap - (self.clock() - self.last_request)))
            try:
                return self.source.query_page(page, PAGE_SIZE)
            except RetryableError:
                if attempt + 1 == self.retries:
                    raise
                self.sleep(min(2 ** (attempt + 1), 16))
            finally:
                self.last_request = self.clock()
        raise AssertionError("unreachable")

    @staticmethod
    def validate(data, *, page, tenant, total=None):
        count = data.get("total")
        records = data.get("list")
        if type(count) is not int or count < 0 or not isinstance(records, list):
            raise ExportError("主档分页结构异常；total 必须是非负整数，list 必须是数组。")
        if total is not None and total != count:
            raise ExportError("采集中商品总数发生变化；请用新目录重采，避免漏项。")
        if "page" in data and data["page"] != page:
            raise ExportError("平台返回的页码不符；已停止。")
        expected = min(PAGE_SIZE, max(0, count - (page - 1) * PAGE_SIZE))
        if len(records) != expected:
            raise ExportError(f"第 {page} 页条数异常（预期 {expected}，实际 {len(records)}）；未标记完成。")
        ids = set()
        for record in records:
            if not isinstance(record, dict) or str(record.get("tenantId")) != tenant:
                raise ExportError(f"第 {page} 页出现其他租户或缺少租户标识；整页拒收。")
            sid = record.get("spuId")
            if not isinstance(sid, (str, int)) or isinstance(sid, bool) or not str(sid):
                raise ExportError(f"第 {page} 页缺少有效 SPU 编码。")
            if str(sid) in ids:
                raise ExportError(f"第 {page} 页存在重复 SPU；请用新目录重采。")
            ids.add(str(sid))
        return count, records, ids

    def collect(self, *, tenant, out):
        tenant = str(tenant).strip()
        if not tenant:
            raise ExportError("必须指定预期租户 --tenant。")
        first = self.fetch(1)
        if first.get("total") == 0 and first.get("list") == []:
            raise EmptyResultError(
                "主档返回 0 条；可能是无商品、账号权限/数据范围受限或登录态异常。"
                "请与平台页面核对；未生成成功导出。"
            )
        total, _, _ = self.validate(first, page=1, tenant=tenant)
        directory = Path(out)
        directory.mkdir(parents=True, exist_ok=True)
        with output_lock(directory):
            return self._collect_locked(directory, tenant, total, first)

    def _collect_locked(self, directory, tenant, total, first):
        state_path = directory / "manifest.json"
        page_dir = directory / ".pages"
        page_dir.mkdir(exist_ok=True)
        scope = {
            "schema_version": 1,
            "tenant": tenant,
            "endpoint": MASTER_PATH,
            "page_size": PAGE_SIZE,
            "total_reported": total,
        }
        if state_path.exists():
            try:
                state = json.loads(state_path.read_text(encoding="utf-8"))
            except (ValueError, OSError):
                raise ExportError("续采 manifest 损坏；请保留现场并使用新目录。") from None
            if not isinstance(state, dict) or any(state.get(k) != v for k, v in scope.items()):
                raise ExportError("续采目录的租户、接口或商品总量不符；请使用新目录。")
        else:
            if any(page_dir.iterdir()) or (directory / "spus.jsonl").exists():
                raise ExportError("目录包含无 manifest 的旧数据；请使用新目录。")
            state = {**scope, "started_at": timestamp(), "pages": {}}
        if not isinstance(state.get("pages"), dict):
            raise ExportError("续采 manifest 的 pages 格式异常。")
        page_count = math.ceil(total / PAGE_SIZE)
        if not set(state["pages"]).issubset({str(p) for p in range(1, page_count + 1)}):
            raise ExportError("续采 manifest 含无效页码。")
        seen = set()
        # Verify durable page content, not just a page number checkpoint.
        for key, digest in state["pages"].items():
            path = page_dir / f"{int(key):06d}.json"
            try:
                raw = path.read_bytes()
                if hashlib.sha256(raw).hexdigest() != digest:
                    raise ValueError("digest mismatch")
                data = json.loads(raw)
            except (ValueError, OSError):
                raise ExportError(f"续采第 {key} 页文件缺失或损坏；已停止。") from None
            if not isinstance(data, dict):
                raise ExportError(f"续采第 {key} 页格式异常。")
            _, _, ids = self.validate(data, page=int(key), tenant=tenant, total=total)
            if key == "1" and data["list"] != first["list"]:
                raise ExportError("续采首页内容发生变化；请用新目录重采。")
            if ids & seen:
                raise ExportError("续采数据存在跨页重复；请用新目录重采。")
            seen |= ids
        state["status"] = "incomplete"
        state.pop("completed_at", None)
        atomic_write(state_path, json.dumps(state, ensure_ascii=False, indent=2) + "\n")
        for page in range(1, page_count + 1):
            if str(page) in state["pages"]:
                continue
            data = first if page == 1 else self.fetch(page)
            _, records, ids = self.validate(data, page=page, tenant=tenant, total=total)
            if ids & seen:
                raise ExportError("发现跨页重复 SPU；数据可能已变化，请用新目录重采。")
            raw = json.dumps(data, ensure_ascii=False, indent=2) + "\n"
            atomic_write(page_dir / f"{page:06d}.json", raw)
            state["pages"][str(page)] = hashlib.sha256(raw.encode("utf-8")).hexdigest()
            atomic_write(state_path, json.dumps(state, ensure_ascii=False, indent=2) + "\n")
            seen |= ids
            self.log(f"页 {page}/{page_count}：本页 {len(records)} SPU，累计 {len(seen)}")
        if len(seen) != total:
            raise ExportError("采集条数与平台总数不符；未生成成功导出。")
        target = directory / "spus.jsonl"
        temporary = directory / "spus.jsonl.tmp"
        with temporary.open("w", encoding="utf-8", newline="\n") as handle:
            for page in range(1, page_count + 1):
                data = json.loads((page_dir / f"{page:06d}.json").read_text(encoding="utf-8"))
                for record in data["list"]:
                    handle.write(json.dumps(record, ensure_ascii=False) + "\n")
            handle.flush()
            os.fsync(handle.fileno())
        temporary.replace(target)
        state.update(status="complete", spu_collected=len(seen), completed_at=timestamp())
        atomic_write(state_path, json.dumps(state, ensure_ascii=False, indent=2) + "\n")
        return target
