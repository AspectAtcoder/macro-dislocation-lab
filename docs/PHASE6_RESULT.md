# Phase 6 結果

Phase 6は **READY_FOR_CAMPAIGN_ACTIVATION_PENDING_VENDOR_ACCESS** で完了した。
これは公式発表日程を実運用候補として固定し、期限・DST・外部アクセスをfail-closedで
判定できる、という配管上のGoである。実データ取得や価格予測のGoではない。

## 固定した6枠

| 発表 | 対象月 | UTC | JST |
|---|---:|---:|---:|
| CPI | 2026-07 | 2026-08-12 12:30 | 2026-08-12 21:30 |
| 雇用統計 | 2026-08 | 2026-09-04 12:30 | 2026-09-04 21:30 |
| CPI | 2026-08 | 2026-09-11 12:30 | 2026-09-11 21:30 |
| 雇用統計 | 2026-09 | 2026-10-02 12:30 | 2026-10-02 21:30 |
| CPI | 2026-09 | 2026-10-14 12:30 | 2026-10-14 21:30 |
| 雇用統計 | 2026-10 | 2026-11-06 13:30 | 2026-11-06 22:30 |

日時はBLSのCPIおよびEmployment Situation個別スケジュールページから確認した。
`America/New_York`で変換したため、米国夏時間終了後の11月6日だけUTC/JSTが1時間
後ろへ移る。

## 凍結時点の判定

評価時刻は2026-08-11 10:08:18 UTC。48時間以内のactivation candidateは直近CPI
1件で、日程はfreshだった。24時間前のaccess-ready期限までは8,502秒だったが、
Trading Economics credentialと承認済みrights attestationが存在しないため、判定は
`BLOCKED_VENDOR_ACCESS`となった。

ブロックされた発表を後日取得してlive receiptと呼ぶことは禁止する。取り逃した枠は
empirical evidence 0件のまま失効し、次の枠を公式日程から再確認する。

## 検証

- 6 failure injectionをすべて拒否
- 公式台帳、正規化台帳、activation packetのhashを独立再生
- 105テストを完走
- 認証vendor request 0件
- empirical window 0件
- market-price join 0件
- model fit 0件

次の外部アクションは、credentialと書面化された利用権が揃った後に、
[campaign activation runbook](CAMPAIGN_ACTIVATION_RUNBOOK.md)へ従って将来の発表枠を
prospectiveに捕捉すること。6枠のevidence enrollmentが完了するまで価格実験へ進まない。
