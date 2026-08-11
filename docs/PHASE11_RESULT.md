# Phase 11 result

Phase 11は**BACKTEST_IMPLEMENTED_EMPIRICAL_DATA_REQUIRED**で完了した。

登録済みの1 trialだけを実行した。特徴は5個、Ridge alphaは1、最初の12件から始める
expanding one-step walk-forwardで、後続12件をOOS予測した。各foldのscaleと係数は予測時刻
より前の行だけでfitしている。

## 合成runの診断値

- OOS prediction: 12件
- active paper trade: 9件
- active direction accuracy: 100%
- MAE: 0.1991bp
- cost後合計: -6.3750bp
- cost後中央値: -0.2499bp
- event Sharpe: -2.3963
- maximum drawdown: -6.8749bp
- Deflated Sharpe Ratio: 0.0021

方向一致100%でもspreadと動的slippage後は負である。この値は合成fixtureの構造診断であり、
予測力や収益性の証拠ではない。`registered-backtest`はGitに登録済みのspec hashだけを受理し、
未登録trialや編集後specを拒否する。label CSVのPIT時刻、evidence ID、bid/ask、spread、動的cost、
long/short PnLも実行時に再計算し、全入出力hashをmanifestへ残す。edge claimにはempirical OOS
50件以上を別途要求する。
