# ksrfp-jinjiroumu-blog

柏谷横浜社労士事務所の「人事労務だより」をもとに、SEOブログ記事を作成し、WordPressへ投稿する自動化プロジェクトです。

## 目的

- Googleドライブ上の最新「人事労務だより」PDFを確認する
- 中小企業に役立つ人事労務テーマを選定する
- 過去記事との重複・カニバリを確認する
- 法改正・ニュースの一次情報を確認する
- SEO記事、アイキャッチ画像、WordPress投稿データを生成する
- WordPress REST APIで投稿する
- Codexオートメーションで毎月1日0:00に実行する

## フォルダ構成

| フォルダ | 用途 |
| --- | --- |
| `00_project/` | 進捗管理、要件、運用ルール |
| `01_inputs/` | GSC、GA、投稿済み記事、PDF、既存プロンプトなどの入力データ |
| `02_analysis/` | SEO分析、カニバリ確認、テーマ選定の中間成果物 |
| `03_generated/` | 生成した記事、構成、画像、WordPress投稿データ |
| `04_wordpress/` | WordPress API連携のコード・設定メモ |
| `05_drive/` | Googleドライブ連携のコード・設定メモ |
| `06_automation/` | Codexオートメーション用の実行スクリプト・手順 |
| `07_logs/` | 実行ログ |
| `08_state/` | 処理済みPDF、投稿済みテーマなどの状態管理 |
| `config/` | 設定ファイル。秘密情報は `config/secrets/` に置く |
| `docs/` | 仕様書、設計メモ、運用ドキュメント |
| `src/` | 解析・選定・投稿自動化の実装コード |

## ローカル解析の実行

```bash
/Users/ug/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3 06_automation/run_local_analysis.py
```

このコマンドで、GSC・GA・投稿済み記事CSV・人事労務だよりPDFを解析し、`02_analysis/` 配下にSEO分析、PDF候補、テーマ選定スコアを出力します。
あわせて、過去記事テーマ分類、記事ブリーフ、構成、本文ドラフト、ファクトチェック項目、アイキャッチ画像計画、WordPress投稿前ペイロード、Drive/WordPress連携ステータス、状態管理サマリーを生成します。

月次自動実行と同じラッパーで確認する場合:

```bash
/Users/ug/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3 06_automation/run_weekly_automation.py
```

WordPress投稿直前の計画だけ確認する場合:

```bash
/Users/ug/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3 06_automation/run_wordpress_publish.py
```

このコマンドはデフォルトではドライランです。WordPressへの実書き込みには、初回動作確認フェーズで `--execute` と `KSRFP_ALLOW_WORDPRESS_WRITE=1` を明示する必要があります。

## 秘密情報

WordPressアプリケーションパスワード情報は `config/secrets/` に置きます。このフォルダはGit管理対象外です。

## 初期運用方針

- WordPress投稿ステータスは `下書き`（`draft`）を基本にします。日付は実行日9:00を設定します。
- 投稿カテゴリは記事テーマ・本文内容から自動設定します。
- タグは設定しません。
- 投稿者は `ksrfp`（ユーザーID `2`）を使います。
- スラッグは設定しません。
- WordPressには下書きで保存し、日付は月次実行日の9:00に設定します。
- Arkhe CSS Editorには見出し用CSSを設定します。
- 自動実行は毎月1日0:00に行います。
- 自動実行結果は成功・失敗を問わず `stonewebstoneweb@gmail.com` へ通知します。
- エラー時は最大3回リトライし、最終的にログと通知を残して処理を止めません。
- 法改正・制度情報は公的機関などの一次情報で確認します。
- 記事テーマは、最新性、中小企業への実務影響、SEO需要、過去記事との重複回避を基準に選定します。
- 未確認の法律・制度・日付・数値が残る場合、WordPress送信可能とは扱いません。
- 外部API呼び出しは `config/project_settings.json` の `enable_external_api_calls` が `true` の場合だけ実行します。
