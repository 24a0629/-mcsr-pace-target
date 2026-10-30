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
