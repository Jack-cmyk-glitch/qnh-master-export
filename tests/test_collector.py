import copy
import json

import pytest

from qnh_master_export.collector import Collector, output_lock
from qnh_master_export.errors import EmptyResultError, ExportError, RetryableError

TENANT = "demo-tenant"


def page(number, total=101):
    start = (number - 1) * 100
    return {
        "page": number,
        "total": total,
        "list": [
            {"spuId": f"demo-{i}", "tenantId": TENANT, "spuName": "虚构测试商品"}
            for i in range(start, min(start + 100, total))
        ],
    }


class Source:
    def __init__(self, pages):
        self.pages = pages
        self.calls = []

    def query_page(self, number, size):
        assert size == 100
        self.calls.append(number)
        result = self.pages[number]
        if isinstance(result, Exception):
            raise result
        return copy.deepcopy(result)


def collector(source, **kwargs):
    return Collector(source, sleep=lambda _: None, log=lambda _: None, **kwargs)


def test_full_export_preserves_unknown_fields(tmp_path):
    first = page(1)
    first["list"][0]["futureField"] = {"nested": ["原样保留", 0]}
    raw = collector(Source({1: first, 2: page(2)})).collect(tenant=TENANT, out=tmp_path)
    records = [json.loads(line) for line in raw.read_text(encoding="utf-8").splitlines()]
    state = json.loads((tmp_path / "manifest.json").read_text())
    assert len(records) == state["spu_collected"] == 101
    assert records[0]["futureField"] == {"nested": ["原样保留", 0]}
    assert state["status"] == "complete"
    assert set(state["pages"]) == {"1", "2"}
    assert not (tmp_path / ".collect.lock").exists()


def test_resume_after_failed_page(tmp_path):
    source = Source({1: page(1), 2: ExportError("disconnected")})
    with pytest.raises(ExportError, match="disconnected"):
        collector(source).collect(tenant=TENANT, out=tmp_path)
    state = json.loads((tmp_path / "manifest.json").read_text())
    assert state["status"] == "incomplete" and set(state["pages"]) == {"1"}
    assert not (tmp_path / "spus.jsonl").exists()
    resumed = Source({1: page(1), 2: page(2)})
    raw = collector(resumed).collect(tenant=TENANT, out=tmp_path)
    assert resumed.calls == [1, 2]
    assert len(raw.read_text(encoding="utf-8").splitlines()) == 101
    complete = Source({1: page(1)})
    collector(complete).collect(tenant=TENANT, out=tmp_path)
    assert complete.calls == [1]  # preflight only; no re-fetch of completed pages


def test_empty_result_creates_no_export_directory(tmp_path):
    out = tmp_path / "empty"
    with pytest.raises(EmptyResultError, match="权限/数据范围"):
        collector(Source({1: {"total": 0, "list": []}})).collect(tenant=TENANT, out=out)
    assert not out.exists()


@pytest.mark.parametrize("position", [0, 99])
def test_mixed_tenant_rejects_whole_first_page(tmp_path, position):
    first = page(1)
    first["list"][position]["tenantId"] = "other-demo-tenant"
    out = tmp_path / "mixed"
    with pytest.raises(ExportError, match="租户"):
        collector(Source({1: first})).collect(tenant=TENANT, out=out)
    assert not out.exists()


def test_later_page_mixed_tenant_not_checkpointed(tmp_path):
    second = page(2)
    second["list"][0]["tenantId"] = "other-demo-tenant"
    with pytest.raises(ExportError, match="租户"):
        collector(Source({1: page(1), 2: second})).collect(tenant=TENANT, out=tmp_path)
    state = json.loads((tmp_path / "manifest.json").read_text())
    assert set(state["pages"]) == {"1"}
    assert not (tmp_path / ".pages/000002.json").exists()


@pytest.mark.parametrize(
    "field,value", [("total", "101"), ("total", -1), ("total", True), ("list", None), ("page", 2)]
)
def test_malformed_pagination_fails(tmp_path, field, value):
    first = page(1)
    first[field] = value
    with pytest.raises(ExportError):
        collector(Source({1: first})).collect(tenant=TENANT, out=tmp_path)


def test_short_page_not_marked_complete(tmp_path):
    second = page(2, 102)
    second["list"].pop()
    with pytest.raises(ExportError, match="条数异常"):
        collector(Source({1: page(1, 102), 2: second})).collect(tenant=TENANT, out=tmp_path)
    assert not (tmp_path / "spus.jsonl").exists()


def test_cross_page_duplicates_rejected(tmp_path):
    second = page(2)
    second["list"][0]["spuId"] = "demo-0"
    with pytest.raises(ExportError, match="跨页重复"):
        collector(Source({1: page(1), 2: second})).collect(tenant=TENANT, out=tmp_path)


def test_within_page_duplicates_rejected(tmp_path):
    first = page(1)
    first["list"][1]["spuId"] = first["list"][0]["spuId"]
    with pytest.raises(ExportError, match="重复 SPU"):
        collector(Source({1: first})).collect(tenant=TENANT, out=tmp_path)


def test_total_changes_abort(tmp_path):
    with pytest.raises(ExportError, match="总数发生变化"):
        collector(Source({1: page(1), 2: page(2, 102)})).collect(tenant=TENANT, out=tmp_path)


def test_resume_wrong_scope_and_corrupt_page_fail(tmp_path):
    collector(Source({1: page(1, 1)})).collect(tenant=TENANT, out=tmp_path)
    other = page(1, 1)
    other["list"][0]["tenantId"] = "other-demo-tenant"
    with pytest.raises(ExportError, match="续采目录"):
        collector(Source({1: other})).collect(tenant="other-demo-tenant", out=tmp_path)
    (tmp_path / ".pages/000001.json").write_text("{}", encoding="utf-8")
    with pytest.raises(ExportError, match="损坏"):
        collector(Source({1: page(1, 1)})).collect(tenant=TENANT, out=tmp_path)


def test_changed_homepage_blocks_resume_even_if_count_equal(tmp_path):
    collector(Source({1: page(1, 1)})).collect(tenant=TENANT, out=tmp_path)
    changed = page(1, 1)
    changed["list"][0]["spuName"] = "修改后的虚构测试商品"
    with pytest.raises(ExportError, match="首页内容发生变化"):
        collector(Source({1: changed})).collect(tenant=TENANT, out=tmp_path)


def test_lock_prevents_two_writers_and_releases_on_error(tmp_path):
    with output_lock(tmp_path):
        with pytest.raises(ExportError, match="锁定"):
            with output_lock(tmp_path):
                pytest.fail("second writer acquired lock")
    assert not (tmp_path / ".collect.lock").exists()
    with pytest.raises(RuntimeError), output_lock(tmp_path):
        raise RuntimeError("simulated interruption")
    assert not (tmp_path / ".collect.lock").exists()


def test_gap_applies_before_second_request_and_retry():
    sleeps = []
    responses = iter([RetryableError("503"), page(1, 1), page(2)])

    class Recovering:
        def query_page(self, number, size):
            response = next(responses)
            if isinstance(response, Exception):
                raise response
            return response

    worker = Collector(Recovering(), sleep=sleeps.append, clock=lambda: 0)
    worker.fetch(1)
    worker.fetch(2)
    assert sleeps == [2, 1.2, 1.2]


def test_generic_errors_are_not_retried():
    source = Source({1: ExportError("timeout")})
    with pytest.raises(ExportError, match="timeout"):
        collector(source).fetch(1)
    assert source.calls == [1]


@pytest.mark.parametrize("gap", [0, 1, float("nan"), float("inf")])
def test_unsafe_gaps_rejected(gap):
    with pytest.raises(ExportError):
        collector(Source({}), gap=gap)
