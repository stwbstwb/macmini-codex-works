# 04_wordpress

WordPress REST API連携に関するコード・設定メモを置きます。

現在の出力:

- `wordpress_status_latest.md`
- `wordpress_status_latest.json`
- `wordpress_readonly_check_latest.md`
- `wordpress_readonly_check_latest.json`
- `wordpress_publish_plan_latest.md`
- `wordpress_publish_plan_latest.json`
- `wordpress_publish_result_latest.md`
- `wordpress_publish_result_latest.json`
- `wordpress_post_verification_latest.md`
- `wordpress_post_verification_latest.json`
- `wordpress_browser_verification_latest.md`
- `wordpress_browser_verification_latest.json`

現在できること:

- WordPress REST APIベースURLを設定から確認する
- 秘密情報ファイルの有無を検出する
- WordPress REST APIの読み取り専用認証確認を行う
- カテゴリ一覧を取得し、設定IDと照合する
- タグ一覧を読み取り確認する
- 既存予約投稿一覧を取得し、`future` 投稿時の日付重複回避に使う
- 投稿ペイロードの有無と送信可否を確認する
- 未確認ファクトや表示確認待ちが残る場合は送信しない
- WordPress投稿のドライラン計画を作成する
- 明示的な `--execute` と `KSRFP_ALLOW_WORDPRESS_WRITE=1` がある場合だけメディアアップロード・下書き保存を実行する
- 作成済み下書きをREST APIで検証する
- ブラウザ上の編集画面・プレビュー画面で表示確認する
- 投稿本文HTML生成時にMarkdownのH1を除外する

未実施:

- Arkhe CSS Editorの完全なAPI自動保存経路の確定

## 初回投稿テスト結果

- 実施日: 2026-06-19
- 投稿ID: `4712`
- メディアID: `4711`
- 投稿ステータス: `draft`
- 予約日時: 2026-06-22 09:00
- 投稿URL: `https://ksrfp.com/?p=4712`
- カテゴリ: 労務管理（ID: `7`）
- タグ: なし
- アイキャッチ: `working-hours-featured.jpg`
- Arkhe CSS Editor meta field: `arkhe_css_editor_meta`
- プレビューでH1重複なし、h2/h3 CSS反映、アイキャッチ表示を確認済み
