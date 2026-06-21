# 05_drive

Googleドライブ連携に関するコード・設定メモを置きます。

現在の出力:

- `drive_status_latest.md`
- `drive_status_latest.json`

現在できること:

- Google DriveフォルダIDを設定から確認する
- Google Drive APIの認証トークン有無を確認する
- 公開Google DriveフォルダページからPDF一覧を取得する
- 最新号を判定する
- 最新号PDFを `01_inputs/newsletters/drive-downloads/` に保存する
- ローカルPDF候補を新しい号順に整理する
- 確認者向けテキストファイルの保存先フォルダIDを設定から確認する
- Google Drive APIトークンがある場合は確認用テキストを指定フォルダへアップロードする
- Google Drive APIトークンがない場合は `auth_required` として記録し、週次処理を継続する
- Google Driveプラグイン経由で確認用テキストを指定フォルダへ保存する
- 認証待ち・接続失敗時の次アクションを出力する

未実施:

- なし
