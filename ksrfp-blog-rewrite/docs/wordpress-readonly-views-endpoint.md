# WordPress側の読み取り専用Views取得口

## 目的

過去記事リライト自動化が、WordPressへ書き込まずに次の情報を取得できるようにする。

- WP Statisticsの投稿別Views
- 直近N日間のViews
- WP Statisticsの文字数メタ
- 本文から計算した文字数
- H2/H3数
- カテゴリ・タグ

この取得口は読み取り専用です。投稿の作成、更新、下書き保存、メタ更新は行いません。

## 設置ファイル

対象ファイル:

```text
wordpress/ksrfp-rewrite-metrics-endpoint.php
```

WordPress側では、次のどちらかで設置する。

```text
wp-content/mu-plugins/ksrfp-rewrite-metrics-endpoint.php
```

または通常プラグインとして:

```text
wp-content/plugins/ksrfp-rewrite-metrics-endpoint/ksrfp-rewrite-metrics-endpoint.php
```

通常プラグインとして置く場合は、管理画面で有効化する。`mu-plugins` に置く場合は自動で読み込まれる。

## エンドポイント

```text
GET /wp-json/ksrfp-rewrite/v1/post-metrics
```

例:

```bash
curl -u 'wordpress_user:application_password' \
  'https://ksrfp.com/wp-json/ksrfp-rewrite/v1/post-metrics?post_type=post&status=publish&per_page=100&page=1&days=30'
```

## 認証と権限

WordPressのApplication PasswordによるBasic認証を想定している。

デフォルトでは、ログイン済みで `edit_posts` 権限を持つユーザーだけが読める。

権限を変えたい場合は、WordPress側で次のフィルターを使う。

```php
add_filter('ksrfp_rewrite_metrics_capability', function () {
    return 'manage_options';
});
```

## 主なクエリパラメータ

| パラメータ | 既定値 | 説明 |
| --- | --- | --- |
| `post_type` | `post` | 対象投稿タイプ |
| `status` | `publish` | 対象ステータス |
| `page` | `1` | ページ番号 |
| `per_page` | `100` | 1回の取得件数。最大100 |
| `days` | `30` | `views_recent` の集計期間 |
| `include_historical` | `true` | WP Statisticsのhistoricalテーブル分を `views_total` に足す |
| `include_content` | `false` | trueの場合のみ本文を返す |

## 返却例

```json
{
  "status": "ok",
  "version": "0.1.0",
  "generated_at": "2026-06-21 06:00:00",
  "source": {
    "wp_statistics_loaded": true,
    "wp_statistics_pages_exists": true,
    "historical_table_exists": true,
    "historical_included": true,
    "views_recent_days": 30,
    "word_count_meta_key": "wp_statistics_words_count"
  },
  "pagination": {
    "page": 1,
    "per_page": 100,
    "total": 320,
    "total_pages": 4
  },
  "items": [
    {
      "post_id": 123,
      "post_type": "post",
      "status": "publish",
      "title": "記事タイトル",
      "slug": "sample-post",
      "url": "https://ksrfp.com/sample-post/",
      "published_date": "2024-01-10T09:00:00+09:00",
      "modified_date": "2024-01-10T09:00:00+09:00",
      "views_total": 42,
      "views_recent": 1,
      "views_recent_days": 30,
      "views_historical": 0,
      "views_source_available": true,
      "wp_statistics_word_count": 1200,
      "computed_character_count": 1840,
      "computed_word_count": 33,
      "h2_count": 3,
      "h3_count": 4,
      "category_names": ["労務"],
      "tag_names": ["就業規則"],
      "excerpt": "記事の抜粋..."
    }
  ]
}
```

## 次工程での使い方

リライト候補選定側では、全ページを取得してからローカルでスコアリングする。

候補選定の基本方針:

```text
1. page=1からtotal_pagesまで全件取得
2. 日付・時期依存テーマや時事ネタを除外
3. views_totalまたはviews_recentが少ない記事を加点
4. computed_character_countが少ない記事を加点
5. h2_count/h3_countが少ない記事を加点
6. 最高スコアの記事を1件選ぶ
```

このエンドポイントではViews順の並び替えまでは行わない。候補選定ロジックをWordPress側に置かず、自動化スクリプト側で調整しやすくするため。
