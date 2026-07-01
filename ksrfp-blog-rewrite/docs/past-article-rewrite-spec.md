# 過去記事リライト自動化 仕様書

作成日: 2026-06-25

対象プロジェクト: `ksrfp-blog-rewrite`

## 1. この仕組みの目的

この仕組みは、ksrfp.com の過去記事の中から、リライトした方がよい記事を毎月1つ選び、新しい記事案を作るためのものです。

作るものは、次の2つです。

- リライト後の記事テキストファイル
- 記事タイトル入りのアイキャッチ画像

作成したファイルは、Google Driveの指定フォルダへ保存します。

WordPressへの投稿、下書き保存、既存記事の更新は行いません。

## 2. 基本方針

この仕組みは、`ksrfp-jinjiroumu-blog` の仕組みを準拠元として活用します。

ただし、今回の目的は「過去記事のリライト案を作ること」なので、次の点は今回専用の仕様に変えています。

- 対象はWordPressの過去記事
- 毎月1記事だけ作成
- WordPressには書き込まない
- Google Driveの保存先は `過去記事リライト` フォルダ
- リライト履歴はWordPress投稿IDで管理

`ksrfp-jinjiroumu-blog` と同じ考え方で使う部分は、次のとおりです。

- Codexオートメーションで毎月実行する
- 画像生成はCodex画像生成ツールを使う
- Google Drive保存はGoogle Driveプラグインを使う
- 保存後のURLをログに残し、通知メールへ反映する
- アイキャッチ画像は、写真背景に記事タイトルを青帯・白太字で合成する

## 3. 実行日時

毎月1日の朝6:00に自動実行します。

実行方式は、Codexオートメーションです。

- オートメーションID: `ksrfp-blog-rewrite-monthly-automation`
- 実行対象フォルダ: `/Users/ug/Desktop/codex_works/ksrfp-blog-rewrite`
- 実行日時: 毎月1日 6:00
- 実行環境: local
- モデル: `gpt-5.5`
- reasoning effort: `xhigh`

初回の実運用確認予定日は、2026年7月1日 6:00です。

## 4. リライト対象にする記事

リライト対象は、WordPressの公開済み投稿です。

次のような記事を優先します。

- アクセス数が少ない記事
- 文字数が少ない記事
- 見出し構成が薄い記事
- H2やH3が少ない記事

Viewsは、WordPress側に設置した読み取り専用の取得口から取得します。

取得する主な情報は次のとおりです。

- 投稿ID
- 記事タイトル
- URL
- 公開日
- 総Views
- 直近Views
- 文字数
- H2数
- H3数
- カテゴリ
- タグ

## 5. リライト対象から除外する記事

次の記事はリライト対象にしません。

- 日付や時期が関係する記事
- 時事ネタ
- ニュース記事
- お知らせ記事
- 改正、施行、期限、年度、助成金など、時期依存が強い記事
- すでにリライト履歴に登録されている記事

日付や時期が関係するかどうかは、記事タイトル、抜粋、カテゴリ、タグなどを見て判定します。

## 6. 全体の流れ

毎月の処理は、次の流れで進みます。

1. リライト履歴を確認する
2. WordPressから記事一覧とViews情報を取得する
3. リライト候補を1件選ぶ
4. 選んだ記事のテーマとSEOキーワードを分析する
5. 同じテーマ、同じSEOキーワードで新しい記事タイトルを作る
6. 新しい記事構成を作る
7. 新しい記事本文を作る
8. アイキャッチ画像の背景を生成する
9. 背景画像に記事タイトルを合成する
10. テキストファイルと画像ファイルを同じファイル名でGoogle Driveへ保存する
11. 完了通知メールを送る

途中で画像生成やGoogle Drive保存が必要になった場合は、Codex側の続行ステップとして処理します。

## 7. 記事生成の仕様

リライト記事は、元記事を単純に加筆するものではありません。

元記事と同じテーマ、同じターゲットSEOキーワードを使い、新しい記事として作り直します。

生成する内容は次のとおりです。

- 記事タイトル
- 記事構成
- 記事本文
- アイキャッチ画像用プロンプト

記事本文には品質ゲートがあります。

現在の基準は次のとおりです。

- 目標文字数: 4500字以上
- H2数: 8以上
- H3数: 12以上

この基準を満たさない場合は、次の工程へ進めません。

## 8. アイキャッチ画像の仕様

アイキャッチ画像は、2段階で作ります。

まず、Codex画像生成ツールで写真背景を作ります。

この背景画像には、記事タイトルの文字は入れません。

その後、後処理で記事タイトルを画像に合成します。

タイトル合成の仕様は次のとおりです。

- サイズ: 1200 x 630
- 形式: PNG
- 文字: 記事タイトル
- 文字色: 白
- 背景帯: 青
- 配置: 中央
- 行数: できるだけ2行、必要に応じて最大3行

Driveへ保存する画像は、タイトル合成後の画像です。

タイトルなし画像をDriveへ保存してはいけません。

## 9. テキストファイルの仕様

Google Driveへ保存するテキストファイルは、ユーザー提供のテンプレートに合わせます。

形式は次のとおりです。

```text
＜リライト対象記事＞

タイトル；元記事タイトル
URL：元記事URL
投稿ID：元記事の投稿ID
公開日：元記事の公開日

ーーーーーーーーーー
＜記事タイトル＞

新しい記事タイトル

ーーーーーーーーーー
＜記事本文＞

## はじめに

本文...
```

本文はMarkdown見出し付きで保存します。

記事タイトルは `<記事タイトル>` ブロックに出すため、本文冒頭のH1は入れません。

## 10. Google Drive保存の仕様

保存先は、次のGoogle Driveフォルダです。

- フォルダ名: `過去記事リライト`
- フォルダID: `1hjyAEFrqu8WPLazi-A6DeRCtv44PJlKC`
- フォルダURL: `https://drive.google.com/drive/folders/1hjyAEFrqu8WPLazi-A6DeRCtv44PJlKC`

保存するファイルは2つです。

- テキストファイル
- アイキャッチ画像

2つのファイルは、拡張子以外を同じファイル名にします。

例:

```text
民間の医療保険は必要？ライフステージ別の考え方.txt
民間の医療保険は必要？ライフステージ別の考え方.png
```

Google Drive保存は、Google Driveプラグイン経由で行います。

Google Drive APIトークンを前提にしたローカル直アップロードは、この仕組みでは採用しません。

保存後は、Drive上のファイルID、URL、ファイル名、サイズ、保存先フォルダIDをローカルログに記録します。

このログと実際のDrive保存内容が合わない場合は、成功扱いにしません。

## 11. 通知メールの仕様

Google Drive保存が完了したら、完了通知メールを送ります。

通知先は次のアドレスです。

```text
stonewebstoneweb@gmail.com
```

通知メールには、主に次の内容を含めます。

- 生成した記事タイトル
- 元記事の情報
- Google DriveのテキストファイルURL
- Google Driveの画像ファイルURL
- 処理結果

通知は、正しいGoogle Drive保存が確認できてから送ります。

誤った保存先にアップロードされた場合は、通知を送りません。

## 12. リライト履歴の仕様

同じ記事を何度もリライト対象にしないように、リライト履歴を保存します。

履歴ファイルは次の場所です。

```text
08_state/rewrite_history.json
```

履歴は、WordPress投稿ID単位で管理します。

履歴には、次のようなイベントを記録します。

- 候補として選ばれた
- 記事生成が完了した
- 品質ゲートに失敗した
- Drive保存用ファイルを作成した

完成済み、または品質ゲート通過後の進行中の記事は、次回以降の候補から除外します。

ただし、品質ゲート未達などの失敗イベントだけで終わった記事は、修正後に再試行できるようにします。

## 13. エラー時・要対応時の扱い

次の状態になった場合は、処理を止めます。

- 記事生成の品質ゲートに通らない
- 最新のアイキャッチ背景画像がない
- アイキャッチ画像が最新プロンプトより古い
- Google Drive保存ログがない
- Drive保存先フォルダIDが違う
- Drive上のファイル名やサイズがローカルの保存用ファイルと一致しない
- WordPressへ書き込もうとしている

画像生成が必要な場合は、`needs_image_generation` として止まります。

Google Drive保存が必要な場合は、`needs_drive_upload` として止まります。

Codexオートメーションでは、これらで止まった場合も、そこで完了扱いにせず、同じ実行の中で画像生成やGoogle Drive保存へ進みます。

## 14. この仕組みで行わないこと

次のことは行いません。

- WordPressへの投稿
- WordPressへの下書き保存
- WordPress既存記事の更新
- 人事労務だより用Driveフォルダへの保存
- タイトルなしアイキャッチ画像の保存
- Google Drive APIトークン必須のローカル直アップロード
- `launchd` 単体での月次実行

## 15. 主なファイル

設定ファイル:

- `config/project_settings.json`

WordPress側のViews取得口:

- `wordpress/ksrfp-rewrite-metrics-endpoint.php`

主な自動化スクリプト:

- `06_automation/run_rewrite_pipeline.py`
- `06_automation/select_rewrite_candidate.py`
- `06_automation/build_rewrite_brief.py`
- `06_automation/generate_rewrite_article.py`
- `06_automation/prepare_featured_image_plan.py`
- `06_automation/apply_featured_image_title_overlay.py`
- `06_automation/continue_after_image_generation.py`
- `06_automation/prepare_drive_files.py`
- `06_automation/record_drive_upload.py`
- `06_automation/send_completion_notification.py`

履歴:

- `08_state/rewrite_history.json`

ログ:

- `07_logs/rewrite_pipeline_latest.json`
- `07_logs/continue_after_image_generation_latest.json`
- `07_logs/drive_upload_latest.json`
- `07_logs/send_completion_notification_latest.json`

生成物:

- `03_generated/articles/`
- `03_generated/images/`
- `03_generated/drive-ready/`
- `03_generated/rewrite-briefs/`

## 16. 手動で確認するときのコマンド

候補選定だけ確認する場合:

```bash
python3 06_automation/select_rewrite_candidate.py --dry-run
```

月次処理の入口を手動で確認する場合:

```bash
python3 06_automation/run_rewrite_pipeline.py --send-notification
```

画像生成後に続きを確認する場合:

```bash
python3 06_automation/continue_after_image_generation.py
```

完了通知だけ送る場合:

```bash
python3 06_automation/send_completion_notification.py
```

## 17. 確認済みの動作

2026-06-21に、手動起動相当の検証を実施しました。

確認できたことは次のとおりです。

- WordPressからViews付き投稿一覧を取得できる
- リライト候補を1件選べる
- 履歴済みの記事を除外できる
- テーマとSEOキーワードを抽出できる
- 記事タイトル、構成、本文を生成できる
- 品質ゲートを通過できる
- Codex画像生成ツールで背景画像を作れる
- 記事タイトルをアイキャッチ画像へ合成できる
- テキストファイルと画像ファイルを同じ名前で作れる
- Google Driveプラグインで正しいフォルダへ保存できる
- Drive保存ログと実ファイルの整合性を確認できる
- 完了通知メールを送れる

この検証で作成した記事は次のとおりです。

- 元記事投稿ID: `229`
- 元記事タイトル: `民間の医療保険は必要なのか？ライフステージごとに解説します。`
- 生成タイトル: `民間の医療保険は必要？ライフステージ別の考え方`
- ターゲットSEOキーワード: `民間の医療保険`
- 本文文字数: `5437`
- H2数: `9`
- H3数: `21`

## 18. 今後の運用

開発としては完了扱いです。

今後は、毎月1日の自動実行結果を確認し、必要があれば改善します。

確認する主な点は次のとおりです。

- 自動実行が予定どおり起動したか
- 選ばれた記事が妥当か
- 記事の方向性が元記事テーマから外れていないか
- アイキャッチ画像に記事タイトルが入っているか
- Google Driveの保存先が正しいか
- 通知メールが届いたか
- 履歴除外が効いているか

初回の実運用確認は、2026年7月1日 6:00の自動実行後に行います。
