# loca-engine

Loca の Location Engine。pymobiledevice3 を唯一隔離し、CLI / GUI / CI / Web から
共通利用できる位置シミュレーション層。

```
src/loca_engine/
├── domain/        測地線計算(geo) / エラーモデル(errors) / 共有DTO(models)（実機非依存）
├── backends/      base.py(Protocol) + fake.py(擬似) + pmd3/(pymobiledevice3 実装)
│                  pmd3/ = tunnel(RSD) / session(DVT保持) / devices / diagnostics(Doctor) / backend
├── location/      service.py — teleport / step / stop と状態の単一真実源
├── api/           app(REST+WS) / schemas(JSON形) / server(127.0.0.1・動的ポート)
└── cli.py         loca serve/devices/doctor/set/move/stop/status（API の薄い HTTP クライアント）
```

依存方向: `api → location → backends(Protocol) / domain`。実機依存は `backends/pmd3/` のみ。
ドメイン/サービス/APIテストは `backends/fake.py` で実機なしに回せる（`uv run pytest`）。

詳細な解説は [`../docs/milestones/M2-engine-rest-api.md`](../docs/milestones/M2-engine-rest-api.md)。
