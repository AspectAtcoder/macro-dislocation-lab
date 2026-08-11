# Prospective campaign activation runbook

このrunbookは将来のCPI／雇用統計をshadow captureするための手順である。売買、価格結合、
モデル学習は行わない。

## 1. 外部アクセスを24時間前までに閉じる

credentialは`TRADING_ECONOMICS_API_KEY`環境変数だけに置く。書面確認済みのrights
attestationはGit管理外の`data/private/`へ置き、次を実行する。

```bash
macro-lab vendor-access-preflight \
  --rights-attestation data/private/trading_economics_rights.json
```

`ready=true`でなければ通信を開始しない。出力にはcredential本体を含めない。さらにPhase 8
以降は、独立した32文字以上の`MACRO_LAB_AUTHORIZATION_KEY`をsecret managerから環境へ
注入する。

## 2. BLS公式日程を48時間以内に再確認する

CPIは<https://www.bls.gov/schedule/news_release/cpi.htm>、雇用統計は
<https://www.bls.gov/schedule/news_release/empsit.htm>を確認する。日付・08:30 Eastern・
対象月を、新しいversioned rosterへ記録する。`checked_at`は実確認時刻とし、日時変換は
固定オフセットでなく`America/New_York`を使う。

既存の登録済みファイルを無言で上書きしない。変更または次期日程は新しいroster IDで
事前登録し、そのcommit hashをtrial registryへ固定する。

## 3. activation packetを確認する

```bash
macro-lab campaign-roster-status \
  --roster config/phase6_campaign_roster_001.json \
  --rights-attestation data/private/trading_economics_rights.json \
  --output data/raw/campaign/readiness.json
```

現在時刻で`READY_FOR_ACTIVATION`になるには、発表前、日程がfresh、access-ready期限内、
credentialあり、rights有効のすべてが必要。`provider_component_ids_resolved=false`は、
pre-release vendor snapshot取得後にprovider IDを解決するまで残す。

`READY_FOR_ACTIVATION`の間に[capture authorization runbook](CAPTURE_AUTHORIZATION_RUNBOOK.md)
の`authorize-campaign-access`を実行し、署名付きaccess receiptを発行する。期限後に時刻を
巻き戻すオプションはなく、receiptがなければそのreleaseは欠測のまま残す。

## 4. rehearsalとshadow capture

発表2時間前までにNTP、二重時計、HTTPS snapshot、websocket heartbeat、reconnect、raw
store、空き容量を確認する。各capture直前に用途別permitを発行する。以後は
[shadow campaign runbook](SHADOW_CAMPAIGN_RUNBOOK.md)、
[provider binding runbook](PROVIDER_BINDING_RUNBOOK.md)、
[evidence enrollment runbook](EVIDENCE_ENROLLMENT_RUNBOOK.md)に従う。

失敗したtraceを編集しない。同じreleaseを後日APIで取得してlive captureとして登録しない。
missing／expired windowは0件のまま残す。

## 5. 昇格境界

異なる実発表6件（CPI 3、雇用統計 3）がissue-freeでledgerへ入るまで、価格を結合しない。
昇格後も別trialとしてentry時刻、予測target、最大5特徴、動的コスト、holdout、試行回数を
再事前登録してから価格実験を始める。
