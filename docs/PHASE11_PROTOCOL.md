# Phase 11 protocol: registered walk-forward backtest

Phase 11はPhase 10のbacktest role 24件だけを使う。最初の12件から開始するexpanding one-step
walk-forwardで、各予測時点より後のscale・targetをfitへ入れない。特徴は登録済み5個、モデルは
alpha=1のRidge、thresholdは2bp、試行は1回で固定する。hyperparameter searchは行わない。

損益は予測方向に応じたentry ask/bidとexit bid/ask、およびPhase 10の動的slippageで計算する。
event Sharpe、drawdown、方向一致、MAE、Deflated Sharpe Ratioを報告するが、登録runはsynthetic
なので経済判断は常に`BACKTEST_IMPLEMENTED_EMPIRICAL_DATA_REQUIRED`である。
