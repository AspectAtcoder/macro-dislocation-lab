# Phase 10 protocol: PIT price and dynamic-cost labels

Phase 10は発表+60秒の最初の実行可能quoteをanchorとし、+15分／+60分への残余変化をlabel化する。
featureはanchorまでにreadyでなければならず、quote lagは2秒以下とする。各legの実bid/askと、
同時点spread・事前volatilityから計算したslippageを保存する。定数コストは禁止する。

登録runはUSD/JPYの合成36イベントだけを使う。24件をbacktest、後続12件をforward roleとして
時間順に完全分離する。同時発表componentは上流で1 event bundleに統合済みであり、この層では
1 bundleを1 sampleとして扱う。合成returnは予測可能性の証拠に数えない。
