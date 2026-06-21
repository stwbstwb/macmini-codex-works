# WordPress投稿実行計画

- 生成日時: 2026-06-21T08:47:43
- ステータス: blocked
- APIベースURL: https://ksrfp.com/wp-json/wp/v2
- 認証情報準備OK: True
- 投稿ペイロード送信可能: False
- 投稿ステータス: draft
- 設定日時: 2026-06-22T09:00:00+09:00
- 投稿タイトル: 働き方改革関連法施行後に見直したい中小企業の労働時間管理
- アイキャッチ画像: /Users/ug/Desktop/codex_works/ksrfp-jinjiroumu-blog/03_generated/images/working-hours-item-3-featured.png
- アイキャッチ画像検出: False
- アイキャッチ品質OK: False
- アイキャッチ背景: requires_fresh_photorealistic_source
- アイキャッチ品質ゲート: blocked_until_fresh_article_photo_source_ready
- アイキャッチalt: 中小企業の労働時間管理と36協定の見直しを表すビジネスイメージ
- 書き込みガード: Use --execute with KSRFP_ALLOW_WORDPRESS_WRITE=1. Default is dry-run only.
- 次の対応: 停止理由を解消してから、動作確認フェーズで実行する。

## 停止理由

- アイキャッチ画像ファイルが存在しません。
- アイキャッチ画像がWordPressアップロード準備完了になっていません。
- アイキャッチ背景は、記事ごとに新規生成した写真品質ソースが必須です。過去画像・既存画像・同テーマ画像の再利用は不可です。

## Arkhe CSS Editor

- CSS設定あり: True
- REST meta key: 未確認
- メモ: Arkhe CSS EditorのREST API上のmeta keyは未確認。投稿API実装時に画面/APIで確認して反映する。

## 注意

- この計画ファイルの生成だけでは、WordPressへの書き込みは行わない。
- 実行には明示的な `--execute` と環境変数 `KSRFP_ALLOW_WORDPRESS_WRITE=1` が必要。
