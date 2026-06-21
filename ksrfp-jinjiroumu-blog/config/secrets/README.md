# config/secrets

秘密情報を置くフォルダです。

現在の想定:

- WordPressアプリケーションパスワード情報
- SMTP通知設定: `email_smtp.json`

`email_smtp.json` の形式:

```json
{
  "host": "smtp.gmail.com",
  "port": 587,
  "username": "送信元メールアドレス",
  "password": "アプリパスワード",
  "from_email": "送信元メールアドレス",
  "use_tls": true
}
```

このフォルダはGit管理対象外です。
