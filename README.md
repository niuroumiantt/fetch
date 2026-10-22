# fetch

inresearch.ai 五个采集队的唯一源码仓库：`fetchspec`、`fetchstat`、`fetchfilings`、`fetchreports`、`fetchquotes`。`inews.today` 是独立产品，不在这里。

需求只来自 inresearch `framework/tco_targets.json`。交付只走供应中心一个入口。收到不等于采用。

```text
src/fetch/core/       HTTPS 白名单、robots、限速、条件请求、20 MiB、SHA、原件库
src/fetch/contract/   一份交付合同：manifest + SHA256SUMS + files/，可选 observations.jsonl
src/fetch/targets.py  冻结 inresearch 目标表
src/fetch/teams/      每队薄适配器
config/<队>/          来源登记
tests/                标准库 unittest
tools/replay.py       离线验包
```

## 命令

```sh
python3 fetch check-config                 # 五队配置
python3 fetch check-config --team fetchstat
python3 fetch run --team fetchstat --source-id fetchstat-eia-bootstrap \
  --existing fixture.html --provenance 'local fixture'
python3 fetch verify --team fetchstat path/to/delivery-...
python3 fetch release --team fetchstat     # 版本清单（须干净工作区）
python3 fetch sync-targets --upstream <inresearch checkout> \
  --ref <40位提交> --expected-sha256 <tco_targets.json SHA>
# 等价：PYTHONPATH=src python3 -m fetch …
PYTHONPATH=src python3 -m unittest discover -s tests -v
```

已登记的首批来源（`scheduled: false`）：EIA / Microsoft AR / LBNL 发布页 / Lambda 报价 / Astera Labs PT6162LX。



## 边界

- 只用 Python 标准库。原件、包、SQLite、凭据不进 Git。
- 一个来源只属一个队、一台主机、一个日历。
- 相同 `delivery_id` 不可改写；相同字节不重建信封。
- 本地测试通过 ≠ 生产接收。inresearch 当前接收器仍只认 `provider_id=fetchspec`；其余四队的正式接收适配在研究端另做。
- 旧仓库 `fetchspec` / 本地 `fetchdata` / 四个 10-11 壳仓库保留历史，不搬业务代码进本仓库。本仓库按测试吸收知识，不按文件合并。

现行规则见 inresearch `framework/06_acquisition.md` 与本仓库 `AGENTS.md`。
