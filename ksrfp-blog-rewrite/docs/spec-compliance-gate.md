# 仕様準拠ゲート

この文書は、`ksrfp-blog-rewrite` を実装するときに、AI側が一般的な実装案へ流れて元仕様から外れることを防ぐためのゲートです。

## 最上位条件

`ksrfp-jinjiroumu-blog` は単なる参考資料ではなく、今回の仕組みを作るうえでの準拠元とする。

ただし、保存先、WordPress書き込み、生成件数など、今回の運用要件と異なるものは差分として明示してから変更する。

## 実装前ゲート

新しい実装または運用方式を採用する前に、必ず次を確認する。

1. `ksrfp-jinjiroumu-blog` の該当仕様を確認したか
2. 今回の要件との差分を明示したか
3. その方式で完成条件まで到達できるか
4. 完成できない方式を、部分実装や残タスクとして扱っていないか
5. 外部書き込み先が今回専用設定になっているか

1つでも満たさない場合は、実装に進まない。

## 月次実行方式

準拠元の仕様:

- `ksrfp-jinjiroumu-blog` は Codexオートメーションで月次実行する
- オートメーションIDは `ksrfp-weekly-run`
- 画像生成はCodex画像生成ツールへ引き継ぐ
- Google Drive保存はGoogle Driveプラグインへ引き継ぐ経路を持つ
- 完成しない状態は `needs_image_generation_tool` や `needs_drive_upload_plugin` としてCodex側で続行する

今回の採用仕様:

- `ksrfp-blog-rewrite` も Codexオートメーションで月次実行する
- 実行日は今回要件に合わせて毎月1日 6:00 とする
- `launchd` は主仕様にしない
- Codex画像生成ツールとGoogle Driveプラグインを使えない方式は完成仕様として扱わない

## アイキャッチ画像

準拠元の仕様:

- 背景画像を記事ごとに作成する
- 背景画像そのものにはタイトル文字を入れない
- 後工程で記事タイトルを青帯・白太字で中央合成する

今回の採用仕様:

- Codex画像生成ツールで背景画像を作る
- `06_automation/apply_featured_image_title_overlay.py` でタイトル帯を合成する
- Driveへ保存する画像はタイトル合成後のPNGとする

## Google Drive保存

準拠元の仕様:

- Google Driveプラグインで保存できる場合は、プラグイン経由で指定フォルダへ保存する
- 保存後のDrive URLをローカルログへ記録し、通知へ反映する

今回の採用仕様:

- 保存先は `過去記事リライト`
- フォルダIDは `1hjyAEFrqu8WPLazi-A6DeRCtv44PJlKC`
- `06_automation/record_drive_upload.py` でDrive URLを記録する
- 別フォルダへの保存は成功扱いにしない

## WordPress反映

準拠元との差分:

- `ksrfp-jinjiroumu-blog` はWordPress下書き保存を行う
- `ksrfp-blog-rewrite` はWordPress投稿、下書き保存、既存記事更新を行わない

この差分は今回の明示要件によるものなので採用する。

## 不採用方式

次は完成仕様として採用しない。

- `launchd` 単体による月次実行
- Google Drive APIトークン必須のローカル直アップロード
- タイトル文字なしのアイキャッチ画像
- 保存先未確認のGoogle Driveアップロード
- WordPressへの下書き保存または投稿反映

## No.8へ進む条件

No.8「月次自動実行」は、次を満たすまで完了扱いにしない。

- Codexオートメーションとして設定されている
- スケジュールが毎月1日 6:00である
- 実行対象が `/Users/ug/Desktop/codex_works/ksrfp-blog-rewrite` である
- Codex画像生成ツールとGoogle Driveプラグインの続行手順がプロンプト内に含まれている
- WordPressへ書き込まないことがプロンプト内に明記されている
- `PROGRESS.md` に元仕様準拠の確認結果が残っている
