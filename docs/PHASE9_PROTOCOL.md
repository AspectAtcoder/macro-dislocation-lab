# Phase 9 protocol: campaign state machine

Phase 9はrelease運用をhash chain付きappend-only stateへ変換する。許可される順序は
`PLANNED → ACCESS_AUTHORIZED → BINDING_CAPTURED → PRE_RELEASE_CAPTURED →
STREAM_COMPLETE → EVIDENCE_ENROLLED`だけである。途中失敗は`ABORTED`へ遷移できるが、
再開や履歴編集は認めない。

登録runは合成IDだけを使い、外部通信を行わない。順序違反、重複、時計逆行、source差し替え、
evidence欠落、hash改ざんをfail-closedで確認する。完了は運用stateの構造検証であり、empirical
campaign、価格結合、モデルまたはsignalではない。
