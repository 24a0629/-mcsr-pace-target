# MCSR Ranked Pace Target(自分用・手元で動かす版)
公開はしない前提。GitHub Pages / GitHub Actions は使いません。

## 使い方(管理者権限不要・Python 3 のみ)
1. この中身を好きなフォルダに展開する。
2. `collect.bat` をダブルクリック → 約25分でデータ収集 → `data/finishers.json` を生成。何度でも実行でき、続きから再開する。
3. `view.bat` をダブルクリック → ブラウザで http://127.0.0.1:8000/ が開く(自分のPCからしか見えない)。

## メモ
- データは `data/` に蓄積される(recent.jsonl / archive/ / runners.json / state.json)。消えると集め直しになるので、ときどきフォルダごとコピーしてバックアップ。
- 収集が遅いのはAPIの上限(10分で500リクエスト)のため。実行回数を増やすほど古いシーズンまで遡れる。
- 自動実行したいときは、Windowsのタスクスケジューラ(ユーザー権限)で `collect.bat` を定期実行する。
- Claude上の公開ページ(自分だけが見られるプレビュー)に `data/finishers.json` を読み込ませて使うこともできる。リンクは共有しないこと。

サイト下部の「Thanks & credits」は同じページ内の `#thanks` 表示。XのURLなどは index.html 内の `XL` で変更できる。
