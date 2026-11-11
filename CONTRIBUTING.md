# 参与贡献

需要 Python 3.10+。安装与检查：

```bash
python -m venv .venv
# macOS/Linux
source .venv/bin/activate
# Windows PowerShell: .venv\Scripts\Activate.ps1
python -m pip install -e '.[dev]'
ruff check .
ruff format --check .
pytest -q
python -m build
```

测试全程离线，使用虚构商品和本机 HTTP 测试服务，不需要商家账号。
提交接口变更时，请附上脱敏后的结构说明和对应测试。

不要提交 Cookie、Token、浏览器 profile、真实账号/租户资料、商品导出或日志。
Issue 中只提供版本、命令结构和简短的错误码；账号参数替换成占位符。
采集保持串行、每次完成请求后间隔至少 1.2 秒；使用页面自带 fetch，保留平台 SDK 行为。

项目仅提供商品主档读取。增加平台写入、账号管理或其他平台采集属于独立范围，请先通过 Issue 讨论。
