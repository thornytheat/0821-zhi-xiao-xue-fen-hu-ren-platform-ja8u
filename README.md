# 职校学分互认台

继续教育教务员可在工作台上传来源 CSV，对照规则判断差异，逐个申请签发或暂缓，并保留批次复核意见。

用最大权重课程匹配确认互认学分，避免同一门外校课程重复抵扣。核对齐全的申请可以先签；材料有冲突或坏行无归属时按申请或整批暂缓，材料更正后按新版重新核算。

## 启动

```sh
docker compose up --build -d --wait
```

打开 <http://localhost:18320>。页面预览带异常样例。选中阶段查看计算证据，选择可签发样例并执行批次，然后提交复核意见。

## 核验

```sh
docker compose exec -T app pytest -q
```

[输入字段](docs/DATA-DICTIONARY.md) · [阶段接口](docs/HTTP.md) · [操作步骤](docs/OPERATIONS.md) · [规则与测试](docs/DEPTH.md)
