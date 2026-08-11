# Macro Dislocation Lab

イベント直後のジャンプを取りに行くのではなく、ジャンプ後に残るドリフト／反転と、
それを検証するためのpoint-in-timeニュース／公式文書基盤を段階的に評価する
リポジトリです。

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

## Phase 1 status

Phase 1は2026-08-10に **PASS_PIPELINE_ONLY** で完了しました。Fed FOMC声明24件と
EIA WPSR 52件を公式アーカイブから取得し、その後さらに2回ネットワーク再取得しました。
document vintageは76件のまま、各runの重複probeを含むobservationだけが231件へ増加。
固定6軸とEIA構造化特徴の再生hashは一致し、25テストと最終verifierが全項目PASSです。

これは取得・版管理・再現性のGoであり、価格予測のGoではありません。consensusと
ベンダー実配信時刻を含むpoint-in-time履歴は未契約です。詳細は
[Phase 1 result](docs/PHASE1_RESULT.md)と
[Phase 1 protocol](docs/PHASE1_PROTOCOL.md)を参照してください。

## Phase 2 status

Phase 2は2026-08-10に完了しました。PIT calendar contractとevent-bundle層は
**READY_FOR_LICENSED_VENDOR_INGESTION**、価格実験は
**NO_GO_PRICE_EXPERIMENT_VENDOR_DATA_REQUIRED**です。

2024年CPI/NFPの60 componentを24 bundleへ統合し、Phase 1のFOMC 24件・EIA 52件も
同じ表現へ接続しました。合計100 bundleを監査しましたが、pre-release vintage・
履歴live到着時刻・利用権が揃うbundleは0件です。既存研究データを価格学習へ流さない
negative controlが成功した、という結果です。詳細は
[Phase 2 result](docs/PHASE2_RESULT.md)と
[Phase 2 protocol](docs/PHASE2_PROTOCOL.md)を参照してください。

## Phase 3 status

Phase 3は2026-08-10に **READY_FOR_AUTHENTICATED_SHADOW_CAPTURE** で完了しました。
HTTPS snapshotとcalendar streamのpayloadを、credentialを残さずcontent-addressed raw
blobとappend-only observationへ保存し、同じPIT normalizerで再生する層です。

登録済みsynthetic fixtureで3受信・2 raw blob・3 snapshot・1 componentを再生し、
hash一致、二重時計の分離、5 failure injection、全53テストがPASSしました。実vendor
行は0件で、価格実験は引き続きNo-Goです。詳細は
[Phase 3 result](docs/PHASE3_RESULT.md)、
[Phase 3 protocol](docs/PHASE3_PROTOCOL.md)、
[vendor capture runbook](docs/VENDOR_CAPTURE_RUNBOOK.md)を参照してください。

## Phase 4 status

Phase 4は2026-08-11に **READY_TO_START_LICENSED_SHADOW_CAMPAIGN** で完了しました。
schedule hash、named-zone DST変換、3 clock sample、pre-release snapshot、stream
heartbeat／reconnect、同時発表component、raw-store auditを1つのrelease-window gateへ
統合しました。

登録済みsynthetic traceは20 event・2 component・1 reconnectでcomplete、6 failure
injectionはすべてfail-closed、全74テストがPASSしました。実shadow windowは0件なので
campaignは未昇格、価格実験もNo-Goです。詳細は
[Phase 4 result](docs/PHASE4_RESULT.md)、
[Phase 4 protocol](docs/PHASE4_PROTOCOL.md)、
[shadow campaign runbook](docs/SHADOW_CAMPAIGN_RUNBOOK.md)を参照してください。

## Phase 5 status

Phase 5は2026-08-11に **READY_FOR_LICENSED_EVIDENCE_ENROLLMENT** で完了しました。
Phase 3のimmutable captureとPhase 4のrelease-window traceをcapture ID、受信時計、
payload内component、実store監査、権利・license・provenanceで相互照合する層です。

登録済みoffline packageは2 capture receipt・2 raw blob・4 snapshot・20 trace event・
3 capture referenceを再生し、7 failure injectionと全92テストがPASSしました。
synthetic evidenceの登録は0件です。credentialと承認済みrights attestationは未配置なので、
外部状態は **WAITING_FOR_VENDOR_CREDENTIAL_RIGHTS_AND_RELEASE_WINDOWS**、価格実験は
No-Goです。詳細は[Phase 5 result](docs/PHASE5_RESULT.md)、
[Phase 5 protocol](docs/PHASE5_PROTOCOL.md)、
[evidence enrollment runbook](docs/EVIDENCE_ENROLLMENT_RUNBOOK.md)を参照してください。

## Phase 6 status

Phase 6は2026-08-11に **READY_FOR_CAMPAIGN_ACTIVATION_PENDING_VENDOR_ACCESS** で
完了しました。BLS公式ページから次のCPI 3件・雇用統計3件を固定し、48時間以内の
日程再確認、24時間前のaccess-ready期限、`America/New_York`によるDST変換を
activation packetへ統合しました。

凍結時点の候補は8月12日CPI 1件ですが、credentialと承認済みrights attestationが
ないためfail-closedでブロックされています。6 failure injectionと全105テストがPASSし、
実capture、価格結合、モデル学習はいずれも0件です。詳細は
[Phase 6 result](docs/PHASE6_RESULT.md)、
[Phase 6 protocol](docs/PHASE6_PROTOCOL.md)、
[campaign activation runbook](docs/CAMPAIGN_ACTIVATION_RUNBOOK.md)を参照してください。

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

# 7. 入力ハッシュ・試行回数・成果物・判定の完了監査
macro-lab verify-phase0

# Phase 1: 公式アーカイブを取得し、immutable storeと低次元特徴を生成
macro-lab phase1-complete

# Phase 1: 事前登録・blob hash・再生hash・テストを最終監査
macro-lab verify-phase1

# Phase 2: PIT data contract、同時発表bundle、vendor preflight
macro-lab phase2-complete

# Phase 2: 事前登録・全input／bundle hash・negative controlを監査
macro-lab verify-phase2

# Phase 3: immutable vendor captureとoffline failure injectionを実行
macro-lab phase3-complete

# Phase 3: preregistration、raw blob、replay hash、テストを監査
macro-lab verify-phase3

# Phase 4: release-window supervisorとoffline failure injectionを実行
macro-lab phase4-complete

# Phase 4: schedule、append-only trace、audit hash、campaign gateを監査
macro-lab verify-phase4

# Phase 5: capture-to-trace cross-linkとoffline failure injectionを実行
macro-lab phase5-complete

# Phase 5: preregistration、raw replay、package hash、ledger gateを監査
macro-lab verify-phase5

# Phase 6: BLS公式6枠を正規化し、activation gateを実行
macro-lab phase6-complete

# Phase 6: preregistration、roster hash、DST、失敗注入を監査
macro-lab verify-phase6

# 現在時刻で、認証情報を表示せず次の候補状態を確認
macro-lab campaign-roster-status

# テスト
python -m unittest discover -s tests -v
```

生成物は `artifacts/phase0_complete_2024/`、`artifacts/phase1_complete/`、
`artifacts/phase2_complete/`、`artifacts/phase3_complete/`、
`artifacts/phase4_complete/`、`artifacts/phase5_complete/`、
`artifacts/phase6_complete/` のCSV、JSON、
Markdown、SVGです。
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
