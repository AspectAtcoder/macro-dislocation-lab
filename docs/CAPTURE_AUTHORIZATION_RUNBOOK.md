# Signed capture authorization runbook

このrunbookは認証付きTrading Economics captureを、登録済みrelease windowに限定して
開始する手順である。売買、価格結合、モデル学習は許可しない。

## 1. 外部条件を準備する

次の3点をGit外で準備する。

1. `TRADING_ECONOMICS_API_KEY`: 契約済みcredential。環境変数だけに注入する。
2. `MACRO_LAB_AUTHORIZATION_KEY`: 32文字以上の独立したランダム鍵。secret managerから
   環境変数へ注入し、ファイル、引数、shell履歴へ書かない。
3. rights attestation: `config/vendor_rights_attestation.schema.json`に従い、provider、
   retention、backtest、ML、derived-data等を承認したJSONを`data/private/`へ置く。

preflightを通す。

```bash
macro-lab vendor-access-preflight \
  --rights-attestation data/private/trading_economics_rights.json
```

出力が`ready=true`でなければ、以後を実行しない。

## 2. 公式日程を再確認してrosterを版管理する

対象releaseの48時間前以降にBLS公式ページを確認する。既存の登録済みrosterは上書きせず、
新しいroster IDのJSONを作成し、変更前にcommit hashをtrial registryへ固定する。
`checked_at`は実確認時刻、timezoneは`America/New_York`とする。

現在の次候補`BLS-NFP-2026-08`では、再確認可能時刻は2026-09-02 12:30 UTC以降、
access-ready期限は2026-09-03 12:30 UTCである。古いrosterはactivation gateを通らない。

## 3. access receiptを期限内に発行する

```bash
macro-lab authorize-campaign-access \
  --source-event-id BLS-NFP-2026-08 \
  --roster config/phase6_campaign_roster_002.json \
  --rights-attestation data/private/trading_economics_rights.json \
  --output data/private/authorization/BLS-NFP-2026-08-access.json
```

このコマンドは実時計を使い、過去時刻の指定を受け付けない。日程freshness、deadline、
credential、rights、署名鍵のどれかが欠ければreceiptを作らない。出力ファイルはmode 0600で
新規作成し、既存ファイルを上書きしない。

## 4. 用途別permitを発行してcaptureする

provider event IDを解決するbinding snapshotは、access認可後かつ発表前に実行できる。

```bash
macro-lab issue-capture-permit \
  --source-event-id BLS-NFP-2026-08 \
  --roster config/phase6_campaign_roster_002.json \
  --access-receipt data/private/authorization/BLS-NFP-2026-08-access.json \
  --action binding_snapshot \
  --output data/private/authorization/BLS-NFP-2026-08-binding.json

macro-lab capture-te-snapshot \
  --authorization-permit data/private/authorization/BLS-NFP-2026-08-binding.json \
  --permit-action binding_snapshot \
  --rights-attestation data/private/trading_economics_rights.json \
  --indicator "non farm payrolls" \
  --start 2026-09-04 \
  --end 2026-09-04
```

pre-release consensus snapshotは発表前180秒以内、calendar stream permitは発表前120秒以内に
別ファイルへ発行する。stream permitは発表後120秒で失効する。

```bash
macro-lab issue-capture-permit \
  --source-event-id BLS-NFP-2026-08 \
  --roster config/phase6_campaign_roster_002.json \
  --access-receipt data/private/authorization/BLS-NFP-2026-08-access.json \
  --action pre_release_snapshot \
  --output data/private/authorization/BLS-NFP-2026-08-pre.json

macro-lab capture-te-snapshot \
  --authorization-permit data/private/authorization/BLS-NFP-2026-08-pre.json \
  --permit-action pre_release_snapshot \
  --rights-attestation data/private/trading_economics_rights.json \
  --indicator "non farm payrolls" \
  --start 2026-09-04 \
  --end 2026-09-04

macro-lab issue-capture-permit \
  --source-event-id BLS-NFP-2026-08 \
  --roster config/phase6_campaign_roster_002.json \
  --access-receipt data/private/authorization/BLS-NFP-2026-08-access.json \
  --action calendar_stream \
  --output data/private/authorization/BLS-NFP-2026-08-stream.json

official-sdk-calendar-jsonl-command | macro-lab capture-te-stream-jsonl \
  --authorization-permit data/private/authorization/BLS-NFP-2026-08-stream.json \
  --rights-attestation data/private/trading_economics_rights.json
```

最後のproducer名は契約済み公式SDKの実コマンドへ置き換える。permit検証はHTTP接続または
stdin消費より前に行われる。失敗したreceipt／permitを編集せず、新しいファイルへ再発行する。
同じ`MACRO_LAB_AUTHORIZATION_KEY`をrelease window終了までsecret managerから利用可能にする。
成功したcapture observationにはpermit全体が格納され、capture IDのハッシュに含まれる。
streamは各メッセージでもpermitを再検証し、tail後の入力を保存しない。

## 5. capture後

raw store audit、provider binding、shadow trace、evidence enrollmentの順に検証する。異なる
実発表6件がissue-freeで登録されるまで価格を結合しない。permitはcaptureだけを許可し、
注文、価格実験、モデルfitの認可には転用しない。
