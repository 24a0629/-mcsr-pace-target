# MCSR Ranked Pace Target
GitHub Pages + GitHub Actions で、データ収集から公開までを自動で回す。

## セットアップ
1. 公開リポジトリのルートに `index.html` / `collect.py` / `README.md` / `.gitignore` を置く。
2. `.github/workflows/update.yml` は「Add file → Create new file」で名前欄に `.github/workflows/update.yml` と入力して貼り付ける。
3. Settings → Pages → Source を「GitHub Actions」にする。
4. Actions → update-data → Run workflow で初回実行(以後は3時間ごとに自動)。
5. 公開URL: `https://<ユーザー名>.github.io/<リポジトリ名>/`

## データの置き場所
- リポジトリのルートに `data/` は無くてよい。蓄積データは `data` ブランチ(recent.jsonl / archive/ / runners.json / state.json)に自動で保存される(毎回1コミットに上書きするので履歴は増えない)。
- `data` ブランチを消すと集め直しになる。

## メモ
- 収集が遅いのはAPIの上限(10分で500リクエスト)のため。実行回数を増やすほど古いシーズンまで遡れる。
- サイト下部の「Thanks & credits」は同じページ内の `#thanks` 表示。XのURLなどは index.html 内の `XL` で変更できる。
- データは、完走した人だけでなく、その試合の全員分(完走しなかった人の区間タイム、試合の終了時刻、Elo)を保存する。今の画面は、完走した人だけで計算する(完走しなかった人を使う補正は、次の段階で追加する)。
- 右上の「Settings」で、確率のレベル(余裕/標準/厳しめ)、リセット(ペース限界線)の基準、表示の整え方、ゲームモード(Ranked / RSG)を変えられる。設定はブラウザに保存される(`#settings`)。

## データの集め方(2段階の抽出)
- 試合は数百万件あるので全部は取らない。①一覧(100試合/リクエスト)を新しい順に読んで、試合を「層」(シーズン × 実力帯 × スタート形態 × バスチオン × 途中棄権か)に分け、②層ごとに「1日あたり約N試合」になる確率で詳細を取る。
- 各試合に抽出確率 p を記録し、画面の計算では 1/p を重みにして、間引いた分を補正する(重みを使うと、画面に「weighted sample」と出る)。
- `collect.py` の `C_NEW` / `C_BACK` で、層ごとの1日あたりの狙い件数(新しい試合 / 遡る古い試合)を変えられる。
