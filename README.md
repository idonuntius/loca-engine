# loca-engine

Loca の Location Engine。pymobiledevice3 を唯一隔離し、CLI / GUI / CI / Web から
共通利用できる位置シミュレーション層。

```
src/loca_engine/
├── domain/        測地線計算・移動・エラーモデル（実機非依存・純粋ロジック）
├── device/        デバイス一覧 / 状態
├── diagnostics/   Connection Doctor（各チェックを明示的に state 化）
├── location/      set / move / stop（backend 越しに呼ぶ）
├── backends/      base.py(Protocol) + pmd3/(pymobiledevice3 実装)
├── api/           FastAPI (REST + WebSocket, 127.0.0.1 のみ)
└── cli.py         loca devices/set/move/stop
```

依存方向: `api → location/device/diagnostics → domain / backends(Protocol)`。
実機依存は `backends/pmd3/` のみ。ドメイン/APIテストは fake backend で実機なしに回せる。
