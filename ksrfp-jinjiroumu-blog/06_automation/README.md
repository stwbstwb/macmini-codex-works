# 06_automation

Codexオートメーションで毎月実行する処理を置きます。

## 自動実行スケジュール

- 実行日時: 毎月1日 0:00
- タイムゾーン: `Asia/Tokyo`
- 実行対象: `/Users/ug/Desktop/codex_works/ksrfp-jinjiroumu-blog`
- 実行入口: `06_automation/run_weekly_automation.py`
- CodexオートメーションID: `ksrfp-weekly-run`
- 1回の生成件数: 3件
- WordPress下書き日付: 3件すべて翌週月曜9:00

現在のローカル実行:

```bash
/Users/ug/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3 06_automation/run_local_analysis.py
```

月次自動実行と同じラッパーで確認する場合:

```bash
/Users/ug/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3 06_automation/run_weekly_automation.py
```

`run_weekly_automation.py` は、生成ゲート通過後にWordPress下書き保存、WordPress一括検証、Google Drive確認用テキスト保存、最終通知まで順に進む。ローカルDrive APIトークンがなく、3件すべて `auth_required` になった場合は `needs_drive_upload_plugin` として返し、Codex Google Driveプラグインで保存を続行する。

終了コードは、`ok` と処理不要の終端だけを0にする。`needs_image_generation_tool` と `needs_drive_upload_plugin` は、Codex側で続行するためのハンドオフとして終了コード2を返す。`partial`、`error`、`blocked_*` は成功扱いにせず1終了にする。
同時に2本の月次ランナーが動かないよう、`07_logs/run_weekly_automation.lock` で実行ロックを取る。二重起動時は `blocked_concurrent_run` を記録し、WordPress下書き保存へ進まない。
3記事全体の品質ゲートがNGの場合は `blocked_batch_quality` とし、WordPress保存、Drive保存、最終成功通知へ進まない。
最新の未作成号に3件分の有効テーマがない場合は、その号を作成済みにせず、同じ実行内で次の未作成号へ遡る。遡っても3件分の有効テーマがない場合は `blocked_insufficient_articles` とし、ニュース区分・地域限定素材などで件数を埋めない。
WordPress下書き保存後は `reconcile_wordpress_state_from_publish_log.py` で `08_state` の投稿履歴を補修し、履歴が現在runの3件をカバーしない場合は後工程の成功扱いにしない。
最終通知前には `verify_final_run_contract.py --allow-missing-notification` を必ず通し、3件のWordPress下書き、Drive確認用テキスト、記事品質、画像品質、最新ログ、状態履歴が揃っていない場合は成功通知ではなく要確認通知にする。
最終通知前には `run_git_hygiene.py` も通し、生成物・実行ログ・状態ファイル・秘密情報パスがGit追跡対象に戻っていないこと、無視されていない未追跡ファイルが残っていないことを確認する。失敗した場合は成功通知へ進まず要確認扱いにする。
最終通知後の契約テストでは、通知結果の `manifest_sha256` も現在の `post_payloads_latest.json` と一致することを確認する。古い通知ログや別run通知は成功根拠にしない。
WordPress下書き保存、状態補修、WordPress読み返し検証、Drive保存、最終通知はステップ別に再試行する。外部一時エラーは最大3回まで再試行し、manifest不一致、件数不一致、同一run状態不一致など決定的な不整合は再試行で成功扱いにしない。
WordPress保存ログ、WordPress検証ログ、Drive保存メタデータ、最終通知payloadには現在の `post_payloads_latest.json` のSHA-256を記録する。後工程はこのハッシュが一致しないログを現在runの成功根拠に使わない。
月次ランナーの `weekly_latest.json` にも現在manifestのSHA-256を記録する。再実行時は、前回ステータスが未完了で、かつ現在manifestと一致する場合に限り、既存バッチを再開対象にできる。

外部連携の読み取り専用診断:

```bash
/Users/ug/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3 06_automation/run_external_diagnostics.py
```

本番同等の外部連携プリフライト:

```bash
/Users/ug/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3 06_automation/run_external_preflight.py
```

このプリフライトでは、同一実行環境でGoogle Drive PDF取得、WordPress REST API読み取り、WordPressカテゴリ取得、SMTP DNS/TCP、SMTPログインを確認する。
WordPressカテゴリは、実サイトから取得したslug/idと `config/project_settings.json` の設定値を照合し、不一致がある場合はNGにする。
Google DriveフォルダからPDFが0件の場合は、ソース取得不能としてNGにする。全号作成済みの判定は、PDF一覧が取得できたうえでランナー側が `processed_pdfs` と照合して行う。
プリフライトがNGの場合は、記事生成、Google Drive確認用テキスト保存、WordPress下書き保存へ進まない。

WordPress下書き保存のドライラン:

```bash
/Users/ug/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3 06_automation/run_wordpress_publish.py
```

3件まとめてWordPress下書き保存のドライラン:

```bash
/Users/ug/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3 06_automation/run_wordpress_publish.py --all
```

実際にWordPressへ3件まとめて書き込む場合は、動作確認フェーズで `--all --execute` と `KSRFP_ALLOW_WORDPRESS_WRITE=1` を明示する。
月次オートメーションでは、3件すべてのペイロードとアイキャッチ画像が準備できた場合のみこの投稿コマンドまで進む。
`post_payload_item_*.json` の件数が `articles_per_run` と一致しない場合は、1件もWordPressへ作成しない。
3件のうち1件でも `ready_to_send=false`、画像ゲートNG、選定ポリシー違反、画像ファイル不足がある場合も、1件もWordPressへ作成しない。バッチは作成前プリフライトで停止する。
投稿対象の正は `03_generated/wordpress-payloads/post_payloads_latest.json` の `items`。過去runの古い `post_payload_item_*.json` や `review_text_item_*.json` が残っていても、manifest外のitemはWordPress保存・Drive保存・Drive URL記録の対象にしない。
前回の部分成功で同名の下書き・予約・保留投稿が残っており、かつ `08_state/scheduled_posts.json` に投稿IDと同じトピックキーが記録済みの場合は、新規作成せず既存投稿を現在のペイロードと新規アイキャッチで更新して再利用する。状態ファイルにない手動下書き、由来不明の同名下書き、別トピックの同名下書きは上書きしない。公開済み投稿に同名がある場合はカニバリ防止のため停止する。
同名タイトルの確認では、最初に見つかった1件だけでなく、draft/future/pending/private/publish の完全一致候補を全件確認する。復旧可能な同名下書きがあっても、同名の公開済み記事、由来不明下書き、別トピック下書きが同時に存在する場合は停止する。
WordPress投稿作成/更新に成功した時点で、Arkhe CSS保存前でも `08_state/scheduled_posts.json` に投稿ID、トピックキー、アイキャッチ画像SHA-256を記録する。後続工程で失敗した場合も、次回実行では同じトピックの既存下書きを復旧対象として扱えるようにする。
同じペイロード・同じアイキャッチ画像SHA-256で既存下書きを再試行する場合のみ、既存メディアIDを再利用する。画像SHA-256が変わった場合は新規メディアをアップロードする。メディアアップロード後に投稿作成/更新が失敗した場合は、そのメディア削除を試行する。
同一runの `wordpress_posts_created` が既に `ok` の場合も、現在の3件ペイロードとpayload path、topic key、titleが一致しなければ `already_created` として扱わず停止する。
アイキャッチ画像は記事ごとに、その記事テーマ・本文内容に合う写真品質の背景ソース `*-featured-photo-source.png` を毎回新規生成し、その上にタイトル帯を合成する。
過去生成画像、既存の同名ソース、同テーマの別記事ソース、同一バッチ内の他記事ソースの再利用は禁止する。
写真ソースは記事ブリーフ作成後に更新されたものだけを新規生成扱いにする。古い写真ソースが残っているだけでは `stale_photo_source_rejected` とし、WordPress下書き保存へ進めない。
画像生成プロンプトは、記事タイトル、元トピック、PDF内区分、ラベル、素材抜粋からシーンを分岐する。助成金・採用は採用面談、給与計算は給与/社会保険実務デスク、無期転換は契約更新面談、安全衛生は工場/倉庫等の現場確認、年金・ライフプランは相談/ビジネス街など、記事ごとに構図を変える。
写真ソースがない場合、コード生成の簡易背景・プレースホルダー、既存画像再利用、同一写真ソース重複の場合は `requires_fresh_photorealistic_source` または `blocked` とし、WordPress下書き保存へ進めない。
この判定は、画像計画、WordPressペイロード、WordPress書き込み直前、3件一括保存前の同一ソース重複チェックで確認する。
画像パスは存在確認だけでなく、通常ファイルかつ非空ファイルであることを必須にする。

テーマ選定では、下書き済み・投稿済みの履歴があるテーマを再選定しない。最新号で未使用の有効テーマが3件に満たない場合は、履歴ありテーマで無理に埋めず、次の未作成号へ遡る。
前回までのプロセス中断などで `processed_pdfs.json` に `partially_drafted` または必要件数未満のWordPress下書きIDが残っている場合、月次ランナーはまず現在のmanifestバッチで再開できるか確認する。現在バッチが3件揃い、本文・ファクト・画像ゲートが通過済みなら、記事生成からやり直さずWordPress保存以降を再開する。画像のみ未完了なら `needs_image_generation_tool` としてCodex画像生成へ引き継ぐ。部分下書きPDF名と現在manifestのPDF名が一致し、既に作成済みのトピックキーを現在manifestが含む場合だけ再開を許可する。現在バッチが別号・別トピック、非画像ゲートNG、manifest件数不一致、manifest不一致などで再開不能な場合に限り、`blocked_partial_draft_issue` として通知し、同じ号で下書きが過剰作成されることを防ぐ。

Codex実行モードで写真ソース生成が必要になった場合は、記事ごとに組み込み画像生成ツールで写真背景を作成し、各 `featured_image_plan_item_*.json` の `base_image.source_path` にある `*-featured-photo-source.png` へ保存する。その後、次の再構築スクリプトを実行して、画像計画、WordPressペイロード、確認用テキスト、3記事バッチ品質を作り直す。

```bash
/Users/ug/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3 06_automation/rebuild_after_external_image_sources.py
```

この再構築が `status=ok` になるまでWordPress下書き保存へ進まない。

外部画像ソースの再構築後、そのままWordPress下書き保存、WordPress検証、Google Drive保存、最終通知まで進める場合:

```bash
/Users/ug/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3 06_automation/continue_after_external_image_sources.py
```

この続行スクリプトも、画像再構築後・WordPress保存前に外部連携プリフライトを再実行する。Drive/WordPress/SMTPがNGならWordPress保存へ進まない。Drive APIトークンがない場合は `needs_drive_upload_plugin` を返し、中間通知を送らずGoogle Driveプラグイン保存へ引き継ぐ。

確認者向けテキストファイル生成:

```bash
/Users/ug/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3 06_automation/run_review_text.py
```

月次生成段階では確認用テキストをローカル作成までに留める。
Google Drive保存は、WordPress下書き保存とREST読み返し検証が完了した後の最終工程で行う。
`run_review_text.py --upload` と `build_review_text_file(upload=True)` は、古い単体アップロード経路としてブロックする。
WordPress読み返し検証ログが現在の `post_payloads_latest.json` より古い場合は、検証結果が `ok` でもDrive保存へ進まない。
WordPress読み返し検証スクリプト自体も、現在の `post_payloads_latest.json` より古い保存ログや3件でない保存ログを検証しない。
WordPress保存ログ・検証ログ・Driveメタデータは、mtimeに加えてmanifestハッシュが現在の `post_payloads_latest.json` と一致することを必須にする。
Drive APIで同名の確認用テキストが見つかった場合は、新規作成ではなく既存ファイルを更新する。同名候補が複数ある場合は更新日時が新しい候補を更新し、候補数をログに残す。

`config/secrets/google_drive_access_token.txt` がある場合は指定Google Driveフォルダへアップロードする。
トークンがない場合は `auth_required` として記録し、処理は止めない。
Google Driveプラグインが使える場合は、プラグイン経由で指定フォルダへ直接保存する。

Google Driveプラグインで保存したURLを通知へ反映する場合:

```bash
/Users/ug/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3 06_automation/record_drive_plugin_uploads.py \
  --drive-upload '260622 記事タイトル1.txt=https://drive.google.com/file/d/...' \
  --drive-upload '260622 記事タイトル2.txt=https://drive.google.com/file/d/...' \
  --drive-upload '260622 記事タイトル3.txt=https://drive.google.com/file/d/...'
```

この記録後に最終通知を送ると、通知メールへDrive URLが反映される。
Drive URLの記録も、現在runのWordPress読み返し検証がOKの場合だけ許可する。URLからDriveファイルIDを取得できない場合は `uploaded` として記録しない。

WordPress保存ログから `08_state` を補修する場合:

```bash
/Users/ug/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3 06_automation/reconcile_wordpress_state_from_publish_log.py
```

保存ログが現在の `post_payloads_latest.json` より古い場合は `stale_publish_log` とし、古い投稿IDを現在runの履歴へ混ぜない。
保存ログのmanifestハッシュが現在の `post_payloads_latest.json` と一致しない場合も `stale_publish_log` と同等に扱い、状態補修には使わない。

最終契約テスト:

```bash
/Users/ug/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3 06_automation/verify_final_run_contract.py --allow-missing-notification
```

通知送信後の検証では `--allow-missing-notification` を外す。通知ログが最終成果物より古い場合はNGにする。

Git衛生チェック:

```bash
/Users/ug/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3 06_automation/run_git_hygiene.py
```

このチェックは、`02_analysis`、`03_generated`、`04_wordpress`、`05_drive`、`07_logs`、`08_state`、`config/secrets` などの実行生成物・秘密情報系パスがGit追跡対象に入っていないことを確認する。実行結果はローカルには残すが、Gitにはコード・仕様・README類だけを残す。

現在できること:

- 入力CSV・PDF解析
- テーマ選定
- 記事ブリーフ、構成、本文ドラフト生成
- 一次情報確認計画とファクトチェック項目生成
- アイキャッチ画像計画生成
- 写真品質のアイキャッチ背景ソース確認
- 写真背景ソース不足時のWordPress下書き保存停止
- WordPress投稿前ペイロード生成
- 3件分の記事候補・WordPressペイロード・確認用テキスト生成
- 確認者向けテキストファイル生成
- 確認用テキストのGoogle Drive APIアップロード試行
- 確認用テキストのGoogle Driveプラグイン保存
- Google Driveプラグイン保存URLのローカル記録
- Codex画像生成ツール後の画像計画・WordPressペイロード再構築
- Codex画像生成ツール後のWordPress保存・Drive保存・最終通知への続行
- WordPress保存ログからの `08_state` 投稿履歴補修
- 最終契約テストによる成功判定の一括検証
- WordPress投稿ドライラン計画生成
- WordPressへのメディアアップロード・下書き保存
- 作成済み下書きのREST API検証
- Google Drive最新PDF取得
- WordPress読み取り専用診断
- Google Drive/WordPress連携ステータス生成
- 本番同等の外部連携プリフライト
- 実行ログ保存
- 状態管理サマリー更新
- run単位のWordPress作成済み状態管理
- 最大3回のリトライ
- 成功・失敗を問わないメール通知処理
- 同一runの通知重複を防ぐ送信済みマーカー
- 最終通知本文が `partial` の場合に処理全体を成功扱いしない判定
- 最終通知前のGit衛生チェック
- 通知メールで3件分の人事労務だより号・掲載箇所・元トピック・重複確認を表示
- SMTP秘密ファイルを使ったメール送信
- メール送信できない場合の `.eml` バックアップ保存

未実施:

- 実行手順
- 本番運用チェックリスト
- 次回定期実行での投稿まで含む本番リハーサル

## 通知

- 通知先: `stonewebstoneweb@gmail.com`
- 成功時: 通知する
- 失敗時: 通知する
- SMTP設定: `config/secrets/email_smtp.json`
- SMTP設定がある場合はSMTP送信を試す
- SMTP設定がない場合はローカル `sendmail` を試す
- どちらも使えない場合でも、`07_logs/notifications/latest_notification.eml` と通知結果JSONを保存する
- 2026-06-19にSMTPサーバーへの実送信テストは成功済み

## 初回投稿テスト

- 実施日: 2026-06-19
- 投稿ID: `4712`
- 予約日時: 2026-06-22 09:00
- メディアID: `4717`
- 投稿ステータス、カテゴリ、タグなし、アイキャッチ、本文HTML、Arkhe CSS Editor反映を確認済み
- `wordpress_posting_requires_user_test` は `false` に変更済み
