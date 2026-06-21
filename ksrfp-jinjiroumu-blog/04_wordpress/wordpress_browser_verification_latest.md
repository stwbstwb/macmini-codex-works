# WordPressブラウザ表示確認

- 確認日時: 2026-06-19 18:57
- 投稿ID: 4712
- 投稿ステータス: 下書き
- 設定日時: 2026-06-22 09:00
- プレビューURL: https://ksrfp.com/?p=4712&preview_id=4712&preview_nonce=513b49b81f&preview=true&_thumbnail_id=4711

## 管理画面確認

- ステータス: 下書き
- カテゴリ: 労務管理がチェック済み
- タグ: なし
- 投稿者: 柏谷英之
- アイキャッチ画像: タイトル入りの `working-hours-featured-1.jpg`（メディアID `4717`）が設定済み
- Arkhe CSS Editor: `arkhe_css_editor_meta` に指定CSSが入っていることを管理画面で確認

## プレビュー表示確認

- H1: `働き方改革関連法施行後に見直したい中小企業の労働時間管理`
- H1数: 1件。本文側の重複H1は削除済み
- アイキャッチ画像: タイトル入りの `working-hours-featured-1.jpg` が設定され、altも設定済み
- タイトル帯: ローカル生成画像で、記事タイトルが青帯・白太字・上下左右中央配置になっていることを確認
- `.c-postContent h2`: `border-bottom: 1px solid rgb(0, 0, 0)` を確認
- `.c-postContent h3`: `background: rgb(239, 239, 239)` を確認
- Arkhe CSS出力: `<style>` 内に指定CSSが出力されていることを確認
- プレビュー表示は2026-06-19 18:14に確認済み。2026-06-19 18:40の再確認では管理画面上のArkhe CSS Editor入力値を確認した。

## 補足

- WordPress REST APIレスポンスでは `arkhe_css_editor_meta` は公開されない。
- XML-RPCは `https://ksrfp.com/ksrfp/xmlrpc.php` が空応答のため利用不可。
- 初回は管理画面上でArkhe CSS Editorへ入力・保存して反映確認した。
- 本文HTMLは2026-06-19 18:40に客観トーン版へ更新し、投稿ステータスを下書きへ変更した。
- アイキャッチ画像は2026-06-19 18:57にタイトル入り版へ差し替えた。
