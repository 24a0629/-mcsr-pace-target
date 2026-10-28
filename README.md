# MCSR Ranked Pace Target
1. GitHubで新しい公開リポジトリを作り、このフォルダの中身(index.html / collect.py / .github/workflows/update.yml / README.md)を置く。
   (.github は「Add file → Create new file」でパスに `.github/workflows/update.yml` と入力して貼り付けると確実)
2. Settings → Pages → Source を「GitHub Actions」にする。
3. Actions タブ → update-data → Run workflow で初回実行(以後は6時間ごとに自動)。
4. 公開URL: https://<ユーザー名>.github.io/<リポジトリ名>/
ローカル確認: python collect.py fetch --minutes 5 → python collect.py build → python -m http.server
