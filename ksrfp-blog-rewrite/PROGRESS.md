# ksrfp-blog-rewrite progress

## 再発防止策の進捗

今回の設計ミスを再発させないため、以下の7項目を先に完了させる。

| No. | 対策 | 状態 | 完了条件 | 現在の状況 |
| --- | --- | --- | --- | --- |
| A1 | `ksrfp-jinjiroumu-blog` 準拠仕様を先に文書化する | 完了 | 元仕様から外してはいけない条件が文書化されている | `docs/spec-compliance-gate.md` を作成済み |
| A2 | 実装前に必ず差分表を作る | 完了 | 元仕様と今回仕様の同じ部分・変える部分が表で確認できる | `docs/ksrfp-jinjiroumu-blog-diff.md` を作成済み |
| A3 | 完成しない方式は進捗に入れない | 完了 | `launchd` を主仕様・残作業から外し、不採用または補助案として分離する | `launchd` plistを削除し、月次運用メモでは不採用方式として明記済み |
| A4 | 進捗表に「元仕様準拠」欄を追加する | 完了 | 進捗表で元仕様準拠・差分・不採用が見える | 実装方針と進捗テーブルに `元仕様準拠` 欄を追加済み |
| A5 | 矛盾に気づいたら即停止する | 完了 | `docs/spec-compliance-gate.md` と月次運用メモに停止条件が明記されている | `docs/monthly-automation.md` に停止条件を追加済み |
| A6 | 外部書き込み前に保存先・方式を再確認する | 完了 | Drive・通知・WordPress書き込み禁止の確認項目が運用メモに明記されている | `docs/monthly-automation.md` に外部書き込み前チェックを追加済み |
| A7 | No.8 を `Codex月次オートメーション設定` に修正する | 完了 | `launchd実機設置` を主仕様から外し、Codexオートメーション設定に置き換える | No.8と月次運用メモをCodexオートメーション前提へ修正済み |

## 実装方針と進捗

実装前ゲート:

- `docs/spec-compliance-gate.md` を確認する
- `ksrfp-jinjiroumu-blog` の該当仕様との差分を明示する
- 完成できない方式を部分実装として扱わない
- 外部書き込み前に保存先と方式を確認する

| No. | 項目 | 状態 | 元仕様準拠 | 完了条件 |
| --- | --- | --- | --- | --- |
| 1 | WordPress側の読み取り専用Views取得口 | 実測OK | 今回専用差分OK | 認証付きリクエストで投稿ごとの `views_total` / `views_recent` が返る |
| 2 | リライト候補選定ロジック | 実測OK | 今回専用差分OK | 全記事メトリクスを取得し、低Views・短文・構成薄め・時期依存除外を加味して候補を1件選べる |
| 3 | 既存記事からテーマ・SEOキーワードを抽出して既存生成系へ渡す変換層 | ブリーフ変換OK | 生成フロー活用 | 選定記事からテーマ・ターゲットSEOキーワードを抽出し、タイトル・構成・本文・画像・Drive保存の既存流れへ渡せる |
| 4 | ブリーフから新規タイトル・構成・本文を作る | 実測OK（ライフプラン系も通過） | 生成思想活用 | リライトブリーフから新規記事タイトル、構成、本文を生成し、品質ゲートを通過する |
| 5 | アイキャッチ画像生成とDrive保存用ファイル準備 | タイトル合成込み実測OK | 準拠 | 背景画像を生成し、記事タイトル入りアイキャッチとテンプレート形式の記事テキストを同じファイル名でローカルに揃える |
| 6 | Googleドライブ保存 | Google Driveプラグイン保存OK | 準拠 | Google Driveプラグインで同名のテキストファイルと画像ファイルを正しい所定フォルダへアップロードする |
| 7 | 通知メール | 修正版通知送信OK | 準拠 | 正しいDrive保存完了後に完了通知メールを送る |
| 8 | Codex月次オートメーション設定 | 設定済み / 手動起動相当検証OK / 初回月次実行待ち | 準拠 | Codexオートメーションで毎月1日6:00に実行され、画像生成ツールとGoogle Driveプラグインまで含む運用になる |
| 9 | リライト履歴 | 実装・検証OK | 強化差分OK | 過去に対象にしたWordPress投稿IDを記録し、次回以降の候補選定から除外する |

## 現在の詳細

### 1. WordPress側の読み取り専用Views取得口

作成済み:

- `wordpress/ksrfp-rewrite-metrics-endpoint.php`
- `docs/wordpress-readonly-views-endpoint.md`

設置確認:

- `wp-content/mu-plugins/ksrfp-rewrite-metrics-endpoint.php` に設置済み
- 未認証アクセスで `ksrfp_rewrite_metrics_auth_required` が返ることを確認済み
- 認証付きアクセスでHTTP 200、公開投稿111件、`items` ありを確認済み

取得サンプル:

- `post_id=4706`, `views_total=2`, `views_recent=2`
- `post_id=4696`, `views_total=5`, `views_recent=3`
- `post_id=4695`, `views_total=1`, `views_recent=1`

### 2. リライト候補選定ロジック

実装内容:

- Views取得口から全公開投稿を取得するクライアントを作る
- 低Views、短文、H2/H3の少なさでスコアリングする
- 日付・時期依存テーマや時事ネタを除外する
- リライト履歴に記録済みの投稿IDを除外する
- 最高スコアの記事を1件出力する

作成済み:

- `06_automation/select_rewrite_candidate.py`
- `src/ksrfp_blog_rewrite/wordpress_metrics_client.py`
- `src/ksrfp_blog_rewrite/candidate_selector.py`
- `config/project_settings.json`

実測結果:

- 入力記事数: 111
- 候補対象記事数: 36
- 除外記事数: 75
- 履歴除外数: 2
- 最新dry-runでの次候補: `post_id=4628` / `清掃・整頓を“仕事”として評価する：クリニックの安心感を生む基準づくり`
- 選定理由: `views_total=3`, `views_recent=0`

履歴除外の検証:

- `post_id=2787` と `post_id=229` を `08_state/rewrite_history.json` に登録済み
- `python3 06_automation/select_rewrite_candidate.py --dry-run` で、履歴除外数 `2` を確認
- dry-runでの次候補は `post_id=4628`
- dry-runは本番用 `rewrite_candidate_latest.json` と履歴を更新しない

出力:

- `02_analysis/rewrite-candidates/rewrite_candidate_latest.json`
- `02_analysis/rewrite-candidates/rewrite_candidate_latest.md`

### 3. 既存記事からテーマ・SEOキーワードを抽出する変換層

作成済み:

- `06_automation/build_rewrite_brief.py`
- `src/ksrfp_blog_rewrite/wordpress_post_client.py`
- `src/ksrfp_blog_rewrite/rewrite_brief.py`

実測結果:

- 元記事: `post_id=229` / `民間の医療保険は必要なのか？ライフステージごとに解説します。`
- リライトテーマ: `民間の医療保険は必要なのか？ライフステージごとに解説します。`
- ターゲットSEOキーワード: `民間の医療保険`
- 関連キーワード: `民間の医療保険`, `医療保険`, `年金`, `高額療養費`
- 想定読者: `制度を調べている個人、従業員から相談を受ける人事労務担当者`

出力:

- `03_generated/rewrite-briefs/rewrite_brief_latest.json`
- `03_generated/rewrite-briefs/rewrite_brief_latest.md`
- `03_generated/outlines/article_brief_latest.json`
- `03_generated/outlines/article_brief_latest.md`

### 4. ブリーフから新規タイトル・構成・本文を作る

作成済み:

- `06_automation/generate_rewrite_article.py`
- `src/ksrfp_blog_rewrite/article_generator.py`

実測結果:

- タイトル: `民間の医療保険は必要？ライフステージ別の考え方`
- ターゲットSEOキーワード: `民間の医療保険`
- 本文文字数: 5437
- H2数: 9
- H3数: 21
- 品質ゲート: 通過

出力:

- `03_generated/articles/rewrite_article_latest.json`
- `03_generated/articles/rewrite_article_latest.md`
- `03_generated/articles/rewrite_article_latest.txt`
- `03_generated/outlines/rewrite_outline_latest.json`
- `03_generated/outlines/rewrite_outline_latest.md`

### 5. アイキャッチ画像生成とDrive保存用ファイル準備

作成済み:

- `06_automation/prepare_featured_image_plan.py`
- `06_automation/apply_featured_image_title_overlay.py`
- `06_automation/prepare_drive_files.py`
- `06_automation/continue_after_image_generation.py`
- `06_automation/record_drive_upload.py`
- `src/ksrfp_blog_rewrite/featured_image_plan.py`
- `src/ksrfp_blog_rewrite/image_title_overlay.py`
- `src/ksrfp_blog_rewrite/drive_package.py`

実測結果:

- 画像: `03_generated/images/rewrite_featured_image_latest.png`
- 画像サイズ: `1200 x 630`
- アイキャッチ仕様: 写真背景に記事タイトルを青帯・白太字で中央合成
- Drive保存用テキスト: `03_generated/drive-ready/民間の医療保険は必要？ライフステージ別の考え方.txt`
- Drive保存用画像: `03_generated/drive-ready/民間の医療保険は必要？ライフステージ別の考え方.png`
- 同一ファイル名ベース: `true`
- Drive保存用テキスト形式: ユーザー提供テンプレートに合わせて、`リライト対象記事` / `記事タイトル` / `記事本文` の3ブロックで出力
- 本文形式: Markdown見出し付き。記事タイトルは別ブロックに出すため、本文冒頭のH1は除外。

現在の対応:

- `run_rewrite_pipeline.py` は画像が未生成または最新プロンプトより古い場合、`needs_image_generation` で停止する
- Codex画像生成ツールで背景画像を `03_generated/images/rewrite_featured_image_latest.png` に保存した後、`continue_after_image_generation.py` で記事タイトルを合成してからDrive保存用ファイル準備へ進める
- `continue_after_image_generation.py` の実測では、画像チェックOK、Drive保存用ファイル再作成OK、Driveアップロードログ検証OKまで確認済み
- 続行ログ: `07_logs/continue_after_image_generation_latest.json`

### 6. Googleドライブ保存

正しいアップロード先:

- フォルダ: `過去記事リライト`
- フォルダID: `1hjyAEFrqu8WPLazi-A6DeRCtv44PJlKC`
- フォルダURL: `https://drive.google.com/drive/folders/1hjyAEFrqu8WPLazi-A6DeRCtv44PJlKC`

誤アップロードとして扱うもの:

- 旧フォルダ: `人事労務だより_ブログ記事`
- 旧フォルダID: `1vFh7U9F2DhItpYRzVvJ2qRKUpvmOD7jp`
- テキストファイルID: `1M2uPqlnV4rBMnDbD1GmH4i2XqRbttVnn` / 削除済み
- 画像ファイルID: `1XigkKaO2NSj0CPfkDhCwXATMJFoSWZ3J` / 削除済み

現在の対応:

- `config/project_settings.json` に正しいDrive保存先を設定済み
- パイプラインはアップロードログのフォルダIDが `1hjyAEFrqu8WPLazi-A6DeRCtv44PJlKC` と一致しない場合、成功扱いにしない
- 誤アップロードログは `deleted_wrong_upload` に変更済み
- 誤アップロードログでは通知メールが送られないことを確認済み
- Google Driveプラグインで正しいフォルダへアップロード済み
- 本文修正後、同じDriveテキストファイルIDの中身を修正版TXTへ差し替え済み
- アップロード結果は `06_automation/record_drive_upload.py` で `03_generated/drive-ready/drive_upload_latest.json` に記録済み

実測結果:

- 保存先フォルダ: `過去記事リライト`
- テキストURL: `https://drive.google.com/file/d/1zENGtriHi7NF_Sw_dlny4oJ4qfgoOhDS/view?usp=drivesdk`
- 画像URL: `https://drive.google.com/file/d/1StfofemuqpJctrwbkX6bHseYZt5Kj2bO/view?usp=drivesdk`
- Drive上のテキストサイズ: `16936` bytes
- Drive上の画像サイズ: `793421` bytes
- 続行スクリプト実行結果: `ok`

### 7. 通知メール

作成済み:

- `06_automation/send_completion_notification.py`
- `src/ksrfp_blog_rewrite/notification.py`

実測結果:

- 宛先: `stonewebstoneweb@gmail.com`
- 件名: `[ksrfp-blog-rewrite] リライト記事生成完了: 民間の医療保険は必要？ライフステージ別の考え方`
- 送信結果: `sent`
- 正しいDrive保存先のURL、修正版テキスト、タイトル入りアイキャッチ画像を反映した通知を送信済み

出力:

- `07_logs/send_completion_notification_latest.json`
- `07_logs/notifications/latest_notification.json`
- `07_logs/notifications/latest_notification.eml`

### 8. 月次自動実行

作成済み:

- `06_automation/run_rewrite_pipeline.py`
- `06_automation/continue_after_image_generation.py`
- `docs/monthly-automation.md`
- `docs/spec-compliance-gate.md`
- `docs/ksrfp-jinjiroumu-blog-diff.md`

現在の扱い:

- 月次実行方式は `ksrfp-jinjiroumu-blog` に準拠し、Codexオートメーションを正とする
- WordPress取得、候補選定、ブリーフ化、記事生成、画像プロンプト作成、Drive保存用ファイル準備、通知メールはスクリプトで連結済み
- Codexの画像生成ツールとGoogle DriveプラグインはCodexオートメーション内の続行ステップとして扱う
- パイプラインは古い画像・古いDriveアップロードログを弾き、`needs_image_generation` または `needs_drive_upload` をログに残して停止できる
- `launchd` 単体の月次実行は完成仕様に到達しないため不採用

Codexオートメーション設定:

- ID: `ksrfp-blog-rewrite-monthly-automation`
- 名称: `ksrfp-blog-rewrite monthly automation`
- 状態: `ACTIVE`
- 実行日時: 毎月1日 6:00
- 実行環境: `local`
- 対象ワークスペース: `/Users/ug/Desktop/codex_works/ksrfp-blog-rewrite`
- モデル: `gpt-5.5`
- reasoning effort: `xhigh`
- プロンプト内の必須条件: 仕様準拠ゲート確認、差分表確認、WordPress書き込み禁止、Codex画像生成ツール使用、Google Driveプラグイン使用、Drive保存先確認、タイトル入りアイキャッチ確認

最新テスト結果:

- 実行: `python3 06_automation/run_rewrite_pipeline.py --send-notification`
- 結果: `needs_image_generation`
- 意味: WordPress取得、候補選定、ブリーフ化、本文生成、画像プロンプト作成までは成功。最新プロンプトに対応する新しい画像がまだないため停止。
- 対象: `post_id=229` / `民間の医療保険は必要なのか？ライフステージごとに解説します。`
- 生成タイトル: `民間の医療保険は必要？ライフステージ別の考え方`
- ターゲットSEOキーワード: `民間の医療保険`
- 品質ゲート: `5437`字 / H2 `9` / H3 `21` / 通過
- ログ: `07_logs/rewrite_pipeline_latest.json`

続行テスト結果:

- 実行: `python3 06_automation/continue_after_image_generation.py`
- 結果: `ok`
- 意味: Codex画像生成ツールで作成した最新背景画像を確認し、記事タイトルを合成し、Drive保存用テキストと画像を再作成し、Google Driveプラグイン経由のアップロードログも検証できた。
- アイキャッチ: `1200 x 630` / 青帯・白太字タイトル入り / 2行
- Driveテキスト: `民間の医療保険は必要？ライフステージ別の考え方.txt`
- Drive画像: `民間の医療保険は必要？ライフステージ別の考え方.png`
- 保存先フォルダID: `1hjyAEFrqu8WPLazi-A6DeRCtv44PJlKC`
- ログ: `07_logs/continue_after_image_generation_latest.json`

### 9. リライト履歴

作成済み:

- `src/ksrfp_blog_rewrite/rewrite_history.py`
- `08_state/rewrite_history.json`

現在の仕様:

- 完成済み、または品質ゲート通過後の進行中 `source_post_id` は候補選定から除外
- 品質ゲート未達などの失敗イベントは履歴に残すが、修正後に再試行できるよう候補除外対象にはしない
- 通常の候補選定では、選定した時点で履歴に記録
- 記事生成、Drive保存用ファイル作成でも同じ履歴にイベントを追記
- 検証用の `--dry-run` は履歴と本番latestを更新しない
- 明示的に確認したい場合のみ `--ignore-history` で履歴除外を無効化できる

最新履歴:

- `post_id=2787`: `drive_package_ready`
- `post_id=229`: `drive_package_ready`
- `post_id=229` の初回品質ゲート未達イベントも記録済み。ただし修正後に再生成し、品質ゲート通過・Drive保存完了まで確認済み。
- `python3 06_automation/select_rewrite_candidate.py --dry-run` で履歴除外数 `2` を確認済み。次候補は `post_id=4628`。

## 運用要件メモ

- 実行日は毎月1日 朝6:00
- WordPressへの投稿・下書き保存はしない
- Googleドライブへテキストファイルとアイキャッチ画像を保存する
- 通知メールあり
- リライト対象はアクセスが少ない記事、構成が薄い記事、文字数が少ない記事
- 日付や時期が関係するテーマ、時事ネタは除外する
- `ksrfp-jinjiroumu-blog` は仕組み・設計の参考元であり、Drive保存先などの運用資産は流用しない

## 残作業

- 初回月次実行日（毎月1日 6:00）の実運用監視
- 月次本番実行後、Codexオートメーションの実行ログとDrive保存結果を確認する
