# Phase 8 result

Phase 8は2026-08-11に
**READY_FOR_SIGNED_CAPTURE_AUTHORIZATION_PENDING_EXTERNAL_ACCESS** で完了した。
認証付きcapture経路は、ネットワーク接続またはstream入力の処理より前に、用途と有効時間を
HMAC-SHA256で固定したpermitを必須とする。

## 登録済み判定

- 対象: `BLS-CPI-2026-07`
- 評価時刻: 2026-08-11 13:41:13 UTC
- access-ready期限: 2026-08-11 12:30:00 UTC
- 期限超過: 4,273秒
- access receipt: 0件
- capture permit: 0件
- authenticated vendor request: 0件
- empirical window、価格結合、モデル学習: すべて0件

期限後のCPIをlive receiptとして再構成しない。次の候補は
`BLS-NFP-2026-08`（2026-09-04 12:30 UTC）であり、公式日程を2026-09-02
12:30 UTC以降に再確認したうえで、2026-09-03 12:30 UTCまでにaccess receiptを
発行する必要がある。

## 実装した境界

access receiptはroster hash、source event、公式日程、activation packet hash、rights
attestation hash、license class、credentialの存在、認可時刻を署名する。credentialと署名鍵
そのものは保存しない。receiptはaccess-ready期限後もrelease後のstream tailまで検証できる。

receiptから発行できるpermitは次の3用途だけである。

- `binding_snapshot`: 認可後から発表前まで
- `pre_release_snapshot`: 発表前180秒以内
- `calendar_stream`: 発表前120秒から発表後120秒まで

成功した認証付きcaptureは、使用した署名済みpermit全体をappend-only observationへ格納し、
permitもcapture IDのハッシュ対象にする。streamは各メッセージの受信時刻でもpermitを
再検証する。署名不一致、roster差し替え、期限切れ、用途混同など8種類のfailure injectionは
すべてfail-closedとなった。完全な回帰試験140件と独立verifierもPASSした。

## 経済的な意味

これは取得配管の認可統制であり、予測可能性、売買優位性、価格結合、モデル学習、注文生成を
許可するものではない。実shadow evidenceへの昇格には、契約済みcredential、承認済みrights
attestation、環境注入された署名鍵、prospectiveな実release captureが必要である。
