# Macro Dislocation Lab

イベント直後のジャンプを取りに行くのではなく、ジャンプ後に残るドリフト／反転が
USD/JPYで観測・取引可能かを先に判定するためのPhase 0リポジトリです。

## 仮説と制約

- ヘッドラインの数値は秒〜数十秒で織り込まれる。
- 内訳、改定、同時発表の組み合わせ、文言差分の消化には数分以上かかる場合がある。
- したがって予測対象は発表ジャンプではなく、実行可能時刻から+15分／+60分までの
  **追加変化** とする。
- ニューラルネットは将来、文章から少数の構造化イベント軸を抽出する用途に限定する。
  価格予測部は線形・Ridge・低ランク／階層モデルを基本とする。
- SHAP等を導入しても「モデル上の推定寄与」であり、因果寄与とは呼ばない。

最初の対象はUSD/JPY、米CPIと雇用統計、2024年24イベントです。このサンプルは
実装と記述統計の検証用であり、優位性の証明には使えません。

## Phase 0 status

Phase 0は2026-08-10に完了しました。登録済み3特徴Ridgeモデルは後半12イベントで
方向一致50%、コスト控除後中央値-3.00bpとなり、現行数値仕様は**No-Go**です。
残余値幅の存在と予測可能性は別である、という結果です。詳細は
[Phase 0 result](docs/PHASE0_RESULT.md)を参照してください。

## Experiment 0

発表直前の最後の気配を基準に、+1秒、+5秒、+30秒、+1分、+5分、+15分、
+60分の価格を測定します。+60分を暫定的な最終水準とし、以下を出力します。

- 累積リターンと+60分への到達率
- オーバーシュートに頑健なcompletion ratio
- 方向一致率と残余リターン
- 各時点の実測スプレッド
- 各時点で入って+60分で閉じた場合のlong/short Bid/Ask後リターン

`abs(+60分リターン) < 2bp` は到達率の分母から除外します。+5分の中央値が
両イベントで95%以上なら「初動捕捉」はNo-Goです。残余予測の可否は別途、封印した
holdoutと試行回数管理を伴う低パラメータモデルで判断します。

## 再現手順

Python 3.11以上だけで動作します。

```bash
python -m venv .venv
. .venv/bin/activate
python -m pip install -e .

# 1. 研究用カレンダーCSVを取得（注意事項への明示同意が必要）
python scripts/fetch_calendar_with_curl.py --acknowledge-research-only

# 2. BLS公式日程と結合してイベントを正規化
macro-lab normalize-calendar \
  --raw-calendar data/raw/calendar/forex_factory_cache.csv

# 3. 24イベント×前後1時間のDukascopy BI5を取得
PYTHONPATH=src python scripts/fetch_dukascopy_with_curl.py --workers 4

# 4. キャッシュを正規化されたティックCSVに変換
macro-lab download-quotes

# 5. Experiment 0
macro-lab experiment0

# 6. 登録済み単一モデルを含むPhase 0最終判定
macro-lab phase0-complete

# テスト
python -m unittest discover -s tests -v
```

最終生成物は `artifacts/phase0_complete_2024/` のCSV、JSON、Markdown、SVGです。
生データ・処理済み相場データ・生成物はGit管理外です。

## リポジトリ規律

- 学習とライブは将来も同じ特徴量関数を呼ぶ。
- 同時刻発表は1つのイベント・ベクトルとして扱う。
- 直近2〜3年の最終holdoutは、仕様凍結まで開かない。
- 全試行を記録し、Deflated Sharpe Ratio等で多重検定を補正する。
- ペーパートレードは配管検証であり、4週間で優位性を判定しない。
- 本番ではNTP監視、DST、休日・短縮取引、動的証拠金、日次損失上限、
  キルスイッチを必須とする。

詳細は [Phase 0 protocol](docs/PHASE0_PROTOCOL.md) と
[data sources](docs/DATA_SOURCES.md)、[news sources](docs/NEWS_SOURCES.md)を参照してください。

## 免責

研究用コードであり、投資助言・収益保証ではありません。データ利用条件、税務、法令、
ブローカー約款、取引リスクは利用者が確認してください。
