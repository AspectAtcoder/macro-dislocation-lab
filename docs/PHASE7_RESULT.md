# Phase 7 結果

Phase 7は **READY_FOR_LICENSED_HANDOFF_PENDING_VENDOR_ACCESS_AND_BINDING** で完了した。
Phase 6の論理componentと、Phase 4/5が実配信で追跡するprovider event IDの間に、明示的な
一対一binding層を追加した。

## 結果

- 選択したroster window: 1件（2026年7月分CPI）
- 論理component: 2件
- 合成provider component: 2件
- Phase 4 shadow schedule preview: 1件
- Phase 4 release planへの変換: 1件
- executable handoff: 0件
- 認証vendor request: 0件
- price join／model fit: 0件

合成bindingは構造的にはcompleteだが、`synthetic_binding_not_empirical`、
`missing_binding_rights`、`capture_receipt_not_verified`によりexecution eligibilityを
持たない。Phase 6のactivation packetも`BLOCKED_VENDOR_ACCESS`なのでpermitは発行されない。

## 不正な自己申告を通さない条件

binding JSONに`licensed`やrights=trueと記述するだけでは不十分である。実行可能判定には、
Phase 3のimmutable capture storeから次を再計算できる必要がある。

- capture IDが一意なreceiptへ解決する
- raw blob integrityが通る
- transportがHTTPS snapshotで、provenanceがauthenticated captureである
- receiptの受信時刻がbindingのcapture時刻と一致する
- 各provider event IDがraw blobから再生され、発表時刻がBLS rosterと一致する
- license classと全rightsがreceipt、snapshot、bindingで一致する

この経路はテスト用immutable storeで成功させ、自己申告だけのlicensed bindingは拒否した。

## 検証

7 failure injection、全input／preregistration hash、binding audit、schedule bytes、Phase 4
plan、handoff hashを独立再生し、119テストがPASSした。

次に実データで進むには、Trading Economics credentialと書面化されたrightsを用意し、
将来の発表前に取得したimmutable snapshotからprovider ID bindingを作る必要がある。過去に
失効した発表を後付けでbindingしてもempirical windowには数えない。
