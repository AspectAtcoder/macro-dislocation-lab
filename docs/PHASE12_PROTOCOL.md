# Phase 12 protocol: forward test and paper risk gate

Phase 12はsignalとoutcomeを同じ書込みで扱わない。まずmodel hash、PIT feature、entry quote、
予想コスト、risk判定をhash-chain journalへ記録し、exit時刻後に別eventとしてsettleする。
signal時点にoutcomeを渡した場合は拒否する。

kill switchは既定ON、open positionは最大1、spreadは8bp以下、quote ageは2秒以下、日次損失は
40bpまでとする。生成物はpaper intentだけで、broker送信コードやlive order権限を持たない。
登録runは分離済みsynthetic forward 12件の配管replayであり、prospective evidenceは0件である。
優位性reviewには少なくとも実event 30件のsettlementと6か月の経過を必要とする。
