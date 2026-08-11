# Provider component-binding runbook

このrunbookは、公式BLS rosterの論理componentを、licensed vendor snapshot内の安定した
event IDへ結び付ける。Phase 7の登録済みcommandはoffline drillであり、本番bindingを
自動取得しない。

## 1. activation前提

[campaign activation runbook](CAMPAIGN_ACTIVATION_RUNBOOK.md)に従い、credential、rights、
48時間以内のBLS日程再確認を完了する。`BLOCKED_*`または`EXPIRED`のwindowは中止する。

## 2. pre-release snapshotをimmutable storeへ保存

Phase 3 recorderを使用し、HTTPS receipt、raw blob、wall-clock receive time、monotonic timeを
保存する。provider IDを別画面や現在ページから転記せず、必ず同じreceiptから再生する。

## 3. bindingを作る

`config/activation_handoff_contract.json`に従い、各logical componentへprovider event ID、
indicator名、scheduled_at、reference period、unitを一対一で記録する。bindingのcapture ID、
時刻、license class、rightsはreceiptと完全一致させる。

同じprovider IDの再利用、component不足、BLS時刻とのずれ、48時間より古いsnapshotは失敗。
同時発表componentは別windowへ分割せず、1つのbundleへまとめる。

## 4. handoff監査

本番用の実行経路では`audit_component_binding(..., capture_store=STORE)`を必須とする。
capture storeを渡さない監査は`capture_receipt_not_verified`となり、schedule previewは作れても
execution permitを発行できない。

permitが発行された場合も用途はshadow captureだけで、release時刻に失効する。price join、
model fit、orderは別trialが昇格するまで禁止する。
