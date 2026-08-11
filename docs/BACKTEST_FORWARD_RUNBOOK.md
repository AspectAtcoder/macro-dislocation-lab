# Backtest and forward-test runbook

このrunbookはPhase 10〜12の実データ運用手順である。合成fixtureの成績を実績として扱わない。

## 1. 実PIT featureを用意する

同時発表componentを1 event bundleへ統合し、次の列を時系列順CSVへ保存する。

```text
event_id,evidence_package_id,scheduled_at,event_family,feature_ready_at,
headline_surprise,revision_surprise,internal_breadth,regime_score,
pre_volatility_bp,dataset_role,provenance
```

`evidence_package_id`はPhase 5のappend-only ledgerへ登録済みのpackage IDであり、scheduleと
event familyも一致しなければならない。`feature_ready_at`はliveで全特徴が利用可能になった実時刻
である。revisionや内部構成を後日取得して過去時刻へ戻さない。`provenance`は
`licensed_shadow`等の実sourceとする。

## 2. 実bid/ask tapeを結合する

quote CSVは次の列を持つ。

```text
timestamp,bid,ask,asset,provenance
```

tickまたは1秒quoteを時系列順にし、イベント時の拡大spreadをそのまま残す。Phase 10 specを
新trial用にコピー・編集して事前commitした後、次を実行する。

```bash
macro-lab build-pit-labels \
  --specification config/phase10_empirical_trial_001.json \
  --features data/private/empirical_features.csv \
  --quotes data/private/usdjpy_bid_ask.csv \
  --evidence-ledger data/raw/evidence_ledger \
  --output-dir data/processed/phase10_empirical
```

first quote at-or-after +60秒／+15分／+60分を選び、lagが2秒を超えれば停止する。出力は実測
bid/askと動的slippageを含む。feature、quote、evidence ledger、出力CSVのhashと、使用した
evidence package IDはmanifestへ固定される。

## 3. バックテストを事前登録する

特徴、target horizon、alpha、initial train、threshold、試行回数、holdout、最低sampleをJSONへ
固定する。そのspecとtrial registry rowをモデル実行前にcommitする。未commit、hash変更、未登録
trialは`registered-backtest`が拒否する。

```bash
macro-lab registered-backtest \
  --specification config/phase11_empirical_trial_001.json \
  --labels data/processed/phase10_empirical/labeled_events.csv \
  --output-dir artifacts/phase11_empirical
```

実行時に全labelの時刻順、evidence ID、bid/ask、mid、spread、slippage、long/short PnLを入力CSV
から再計算し、不一致なら停止する。spec、registry、label、model、prediction、metric、summaryの
hashはmanifestへ保存される。OOS 50件未満は自動的に`INSUFFICIENT_EMPIRICAL_OOS_EVENTS`となる。Sharpeだけでなく、DSR、
drawdown、方向一致、MAE、event別安定性、実コスト感応度を確認する。thresholdやfeatureを変える
場合は同じtrialを上書きせず、新trialとして試行回数へ加える。

## 4. forward testを開始する

合成データだけでfitしたmodelはprospective CLIが拒否する。empirical backtestから生成したmodelと、
outcome列を含まないsignal input JSONを用意する。必須内容はevent ID、登録済みevidence package
ID、event family、schedule、feature-ready時刻、5 feature、現在のentry bid/ask・timestamp、
予定exit timestamp、provenanceである。

```bash
macro-lab paper-forward-signal \
  --model artifacts/phase11_empirical/model.json \
  --input data/private/current_signal_input.json \
  --evidence-ledger data/raw/evidence_ledger \
  --clear-kill-switch
```

`--clear-kill-switch`を明示しない限りsignalは拒否される。signal自身とmodel学習行の全evidence IDが
ledgerで検証される。risk stateはjournalの排他ロック内で再生・判定され、CLI引数でopen positionや
日次PnLを偽装できず、同時signalもposition limitをすり抜けない。exit時刻後、実bid/askでsettleする。

```bash
macro-lab paper-forward-settle \
  --signal-id signal:... \
  --exit-bid 150.00 \
  --exit-ask 150.02

macro-lab paper-forward-status
```

forward testは配管なら即日検証できるが、edge reviewは30件以上かつ6か月以上まで行わない。
paper journalは注文ではなく、brokerへの送信経路も存在しない。
