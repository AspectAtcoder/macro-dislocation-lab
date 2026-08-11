# Phase 10 result

Phase 10は**READY_FOR_REGISTERED_WALK_FORWARD_BACKTEST**で完了した。

- synthetic event: 36件
- backtest role: 24件
- forward role: 12件
- quote point: 108行
- +15分／+60分label: 72行
- empirical event: 0件
- failure injection: 6件すべてfail-closed

発表+60秒をanchorとし、+15分／+60分のmidpoint残余returnを作成した。売買損益は各legの
bid/askと、同時点spreadおよび事前volatilityから計算するslippageを使用する。定数コスト、
anchor後にreadyとなったfeature、2秒を超えるquote lag、crossed marketを拒否する。

合成fixtureとは別に、`build-pit-labels`が実feature CSVとlicensed bid/ask tapeを同じ契約へ
結合する。各feature eventはPhase 5 ledgerの登録済みevidence packageへschedule・event family込み
で照合し、入力・出力hashをmanifestへ保存する。実データがないため登録runのempirical joinは0件である。
