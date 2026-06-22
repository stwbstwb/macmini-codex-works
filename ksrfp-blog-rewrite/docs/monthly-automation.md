# 月次自動実行メモ

## 目的

毎月1日の朝6:00に、過去記事リライト用の記事本文とアイキャッチ画像を作成し、Googleドライブの所定フォルダへ保存し、完了通知メールを送る。

WordPressへの投稿、下書き保存、既存記事の更新は行わない。

## 活用する範囲

`ksrfp-jinjiroumu-blog` は、既存の処理設計、ファイル構成、生成フロー、通知フロー、月次実行方式を準拠元として扱う。

実装前に必ず次を確認する。

- `docs/spec-compliance-gate.md`
- `docs/ksrfp-jinjiroumu-blog-diff.md`

次の運用資産はそのまま流用しない。

- Google Drive保存先
- WordPressへの投稿先、下書き先、更新先
- 公開・配信に関わる設定
- このプロジェクト専用に確認されていない外部連携先

外部へ書き込む保存先は、必ず `config/project_settings.json` のこのプロジェクト専用設定を参照する。

## Google Drive保存先

過去記事リライト用の保存先:

- フォルダ名: `過去記事リライト`
- フォルダID: `1hjyAEFrqu8WPLazi-A6DeRCtv44PJlKC`
- フォルダURL: `https://drive.google.com/drive/folders/1hjyAEFrqu8WPLazi-A6DeRCtv44PJlKC`

このフォルダ以外へのアップロードログは、パイプライン上は成功扱いにしない。

## テキストファイル形式

Driveへ保存するテキストファイルは、ユーザー提供のテンプレート `過去記事リライトのサンプルテキストファイル.txt` に合わせる。

形式:

```text
＜リライト対象記事＞

タイトル；...
URL：...
投稿ID：...
公開日：...

ーーーーーーーーーー
＜記事タイトル＞

...

ーーーーーーーーーー
＜記事本文＞

## はじめに
...
```

本文はMarkdown見出し付きで保存する。記事タイトルは `<記事タイトル>` ブロックで出すため、本文冒頭のH1はDrive保存用テキストでは外す。

## 現在の実装状況

Codex月次オートメーション内で実行する工程:

1. リライト履歴を読み込み、過去に対象にした投稿IDを除外対象にする
2. WordPressからViews付き投稿一覧を取得する
3. 低Views・短文・構成薄め・時期依存除外・リライト履歴除外を加味して候補記事を1件選ぶ
4. 候補記事からテーマ、ターゲットSEOキーワード、想定読者を抽出する
5. 同じテーマ・SEOキーワードで新規タイトル、構成、本文を作る
6. アイキャッチ背景画像生成用プロンプトを作る
7. 最新の画像プロンプトより新しい背景画像ファイルがある場合、記事タイトルを青帯・白太字で中央合成する
8. 同じファイル名のテキストとタイトル入り画像をDrive保存用に揃える
9. Driveアップロードログ内の保存先、ファイル名、元記事ID、ファイルサイズが今回のDrive保存用パッケージと一致する場合、完了通知メールを送る

入口コマンド:

```bash
python3 06_automation/run_rewrite_pipeline.py --send-notification
```

テスト時に通知メールを送らない場合:

```bash
python3 06_automation/run_rewrite_pipeline.py
```

実行ログ:

- `07_logs/rewrite_pipeline_latest.json`

Codexオートメーションでは、入口コマンドが `needs_image_generation` または `needs_drive_upload` で止まった場合も、そこで完了扱いにせず、同じCodex実行内で後続の画像生成ツールまたはGoogle Driveプラグインへ進む。中間状態の通知は送らず、完了通知または異常時の要確認通知だけを送る。

## リライト履歴

同じWordPress記事を何度もリライト対象にしないため、リライト履歴を保存する。

履歴ファイル:

- `08_state/rewrite_history.json`

履歴に入った `source_post_id` は、次回以降の候補選定から除外する。通常運用では候補選定時に `selected` として履歴へ記録し、記事生成やDrive保存用ファイル作成の段階でもイベントを追記する。

検証だけ行う場合は、履歴と本番latestを更新しない。

```bash
python3 06_automation/select_rewrite_candidate.py --dry-run
```

履歴を無視して確認したい場合だけ、明示的に `--ignore-history` を使う。

## 重要な制約と停止条件

Pythonスクリプト単体では、次の2工程を直接実行できない。

- Codexの画像生成ツールによるアイキャッチ背景画像生成
- CodexのGoogle Driveプラグインによるファイルアップロード

そのため、`run_rewrite_pipeline.py` は次のどちらかで一時停止する可能性がある。

- `needs_image_generation`: `03_generated/images/featured_image_prompt_latest.md` を使って背景画像を生成し、最新プロンプトより新しい `03_generated/images/rewrite_featured_image_latest.png` として保存する必要がある
- `needs_drive_upload`: `03_generated/drive-ready/` 内の同名テキスト/画像を上記の `過去記事リライト` フォルダへアップロードし、`03_generated/drive-ready/drive_upload_latest.json` を更新する必要がある

`ksrfp-jinjiroumu-blog` の現行方式に合わせ、APIトークン前提ではなく、Codex側の続行ステップとして次を行う。

- Codex画像生成ツールでアイキャッチ背景画像を作成し、指定パスへ保存する
- 画像保存後に `06_automation/continue_after_image_generation.py` を実行し、記事タイトルを青帯・白太字で中央合成してからDrive保存用テキスト/画像を再準備する
- Google Driveプラグインで `過去記事リライト` フォルダへテキストと画像を保存する
- 保存後のDrive URLを `06_automation/record_drive_upload.py` でローカルログへ記録し、通知メールへ反映する

Google Drive APIトークンによるローカル直アップロードは、このプロジェクトの前提にしない。

次の状態になった場合は、実装を続けず仕様確認へ戻る。

- `ksrfp-jinjiroumu-blog` と異なる月次実行方式を採用しようとしている
- Codex画像生成ツールまたはGoogle Driveプラグインに到達できない方式を採用しようとしている
- `過去記事リライト` 以外のDriveフォルダへ保存しようとしている
- WordPressへ投稿、下書き保存、既存更新をしようとしている
- タイトル文字なしのアイキャッチ画像をDrive保存しようとしている

## 外部書き込み前チェック

Drive、通知、WordPressに関わる処理の前に、必ず次を確認する。

- Drive保存先は `過去記事リライト` か
- DriveフォルダIDは `1hjyAEFrqu8WPLazi-A6DeRCtv44PJlKC` か
- Google Drive保存はGoogle Driveプラグイン経由か
- WordPressへの投稿、下書き保存、既存更新を行わないか
- 通知メール内のDrive URLは現在の `drive_upload_latest.json` と一致しているか
- アイキャッチ画像はタイトル合成後のPNGか

## Codex月次オートメーション

採用する月次実行方式:

- 方式: Codexオートメーション
- オートメーションID: `ksrfp-blog-rewrite-monthly-automation`
- 状態: `ACTIVE`
- 実行環境: local
- 実行対象: `/Users/ug/Desktop/codex_works/ksrfp-blog-rewrite`
- 実行日時: 毎月1日 6:00
- モデル: `gpt-5.5`
- reasoning effort: `xhigh`
- 主な入口: `06_automation/run_rewrite_pipeline.py`

No.8は、Codexオートメーションを作成済み。2026-06-21の手動起動相当検証では、`needs_image_generation` からCodex画像生成、タイトル合成、Google Driveプラグイン保存、完了通知までの続行手順が最後まで通った。残る確認は、初回月次実行日（毎月1日 6:00）の実運用ログ確認とする。

## 不採用方式

- `launchd` 単体での月次実行
- Google Drive APIトークン必須のローカル直アップロード
- タイトルなしアイキャッチ画像の保存
- WordPressへの下書き保存または投稿反映
