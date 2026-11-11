# QNH Master Export · 牵牛花商品主档采集

[![CI](https://github.com/Jack-cmyk-glitch/qnh-master-export/actions/workflows/ci.yml/badge.svg)](https://github.com/Jack-cmyk-glitch/qnh-master-export/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)

将牵牛花后台当前账号**可访问的商品主档**导出为完整原始记录 JSONL 和 44 列 SKU 级 Excel。通过 OpenCLI 在已经登录的 Chrome 页面里调用页面自带 `window.fetch`，无需复制 Cookie，也不依赖私有采集项目。

An independent Python CLI for exporting accessible QianNiuHua product masters through an authenticated OpenCLI Browser Bridge session. Includes resumable JSONL collection, tenant validation and SKU-level XLSX export.

## 功能

- 主档按 SPU 采集，Excel 按 SKU 展开；保留主图、详情图、特殊图、配料图及视频 URL。
- 串行分页（100 SPU/页），每次请求完成后至少间隔 1.2 秒。
- 每条记录校验预期租户；缺页、重复 SPU、页码/条数异常和总量变化均停止。
- 中断后使用相同输出目录续采，逐页校验文件哈希和租户。
- 空结果明确报错，避免将权限或登录问题当作成功的零行导出。
- Excel 中保留条码前导零、长编码与价格 0；文本不被解释成公式。

项目为非官方工具，依赖平台现有页面接口；接口变化可能需要适配。导出的数据范围由当前账号决定，账号总数较少不等于租户实际商品总数。

## 安装

需要 Python 3.10+、Chrome/Chromium 和 [OpenCLI Browser Bridge](https://github.com/jackwener/opencli)。

```bash
git clone https://github.com/Jack-cmyk-glitch/qnh-master-export.git
cd qnh-master-export
python -m venv .venv
# macOS/Linux
source .venv/bin/activate
# Windows PowerShell: .venv\Scripts\Activate.ps1
python -m pip install -e .
```

安装 OpenCLI 并按其说明安装 **对应版本** 的 Browser Bridge 扩展：

```bash
npm install -g @jackwener/opencli@1.7.2
opencli doctor
```

本项目针对 OpenCLI 1.7.2 的 HTTP `bind-current` / `exec` 协议实现。上游单连接 daemon 可直接使用；支持 `/clients` 和 `targetClientId` 的多连接 daemon 可使用 `--client`。更高版本协议尚未验证，不能据此承诺兼容。

在自己的 Chrome 中登录牵牛花，停留在 `https://qnh.meituan.com/home.html` 下的商品页面。保留原页面，关闭该页 DevTools。

## 使用

```bash
# 列出扩展连接；上游单连接模式显示 default
qnh-master clients

# 只验证页面绑定，不读取商品，也不证明商品数据权限
qnh-master doctor

# 一步采集 + Excel：替换 YOUR_TENANT_ID
qnh-master run --tenant YOUR_TENANT_ID --out exports/my-master

# 多连接 daemon：client ID 从 clients 输出获取
qnh-master run --client YOUR_CLIENT_ID --tenant YOUR_TENANT_ID --out exports/my-master

# 只采原始数据
qnh-master pull --tenant YOUR_TENANT_ID --out exports/my-master

# 断点续采：重跑原命令，保持相同租户与 --out
qnh-master run --tenant YOUR_TENANT_ID --out exports/my-master

# 已有 JSONL 可以离线转换
qnh-master xlsx --jsonl exports/my-master/spus.jsonl --out exports/my-master/master.xlsx
```

也可使用 `python -m qnh_master_export` 代替 `qnh-master`。`--daemon http://127.0.0.1:19825` 可覆盖 daemon 地址，仅接受本机 HTTP 地址。`--gap` 最小 1.2 秒，`--retries` 为 1–5（默认 3）。只对已完成的 HTTP 500/502/503/504 请求有限重试；权限错误、限流、业务错误和超时直接停止。

### 无账号离线演示

仓库唯一的商品样例为虚构数据，图片使用 `example.invalid`，不包含真实商家记录：

```bash
qnh-master xlsx --jsonl examples/demo.jsonl --out exports/demo.xlsx
```

### 输出与续采

```text
exports/my-master/
├── .pages/          # 已验证的逐页原始响应；续采必须保留
├── manifest.json    # 租户、总数、进度、页文件哈希、完成状态
├── spus.jsonl       # 所有分页通过后生成；每行一条完整 SPU
└── master.xlsx      # run 命令生成的 44 列 SKU 级工作簿
```

只在全部页校验通过后将 manifest 标记为 `complete`，并生成完整 JSONL。失败返回非零退出码，不生成本次 Excel。续采会重新读取首页，核对租户、总量和已保存首页内容；已确认页不重复采集。

分页接口没有事务快照。即使数量不变，采集中其他页的商品仍可能变化；请尽量在资料稳定时采集。若需要一份新的数据，使用**新输出目录**；相同目录用于恢复原批次，不用于刷新商品。不要直接编辑 `.pages/` 或 manifest。

强制结束进程或断电可能留下 `.collect.lock`。确认没有进程使用该目录后手动移除锁文件，再用原命令续采。普通报错和 Ctrl+C 会自动释放锁。

## 字段与限制

完整列映射见 [docs/FIELDS.md](docs/FIELDS.md)。JSONL 保留接口返回的全部商品字段，Excel 是便于查看的字段投影，时间统一为 UTC。

主档接口通常无法提供美团/淘宝闪购/京东等渠道的门店零售价和活动价，也不保证提供外部编码、拣货标准或包装号；这些需要门店商品接口、详情接口或平台导出。当前项目范围是**租户商品主档**。图片只导出 URL，不下载媒体文件。

Excel 单元格最多 32767 字符，单表最多 1048575 条数据；超过时转换失败，原始 JSONL 保持完整。异常类型保留平台原始编码，避免错误解释新枚举。

## 排障与退出码

| 退出码 | 含义 |
| --- | --- |
| 0 | 当前命令完成 |
| 2 | 配置、连接、权限、数据校验或导出失败 |
| 3 | 返回空结果，无法确认商品访问范围 |
| 130 | 用户中断，可续采 |

`code:0`、`total:0` 只说明接口返回空集，**不能单凭这一点认定无权限或确实没有商品**。请在平台页面核对账号、租户和商品范围。更多情况见 [docs/TROUBLESHOOTING.md](docs/TROUBLESHOOTING.md)。

## 开发与许可证

离线验证与贡献方式见 [CONTRIBUTING.md](CONTRIBUTING.md)。GitHub Actions 配置覆盖 Python 3.10/3.12/3.14 与 Windows。MIT 许可证见 [LICENSE](LICENSE)。OpenCLI 作为独立的 Apache-2.0 上游项目安装，本仓库不捆绑其源码或浏览器扩展。
