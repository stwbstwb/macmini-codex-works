<?php
/**
 * Plugin Name: KSRFP Rewrite Metrics Endpoint
 * Description: Read-only REST endpoint for rewrite automation. Exposes WP Statistics views and lightweight content metrics.
 * Version: 0.1.0
 * Author: KSRFP Automation
 */

if (!defined('ABSPATH')) {
    exit;
}

define('KSRFP_REWRITE_METRICS_VERSION', '0.1.0');

add_action('rest_api_init', 'ksrfp_rewrite_metrics_register_routes');

/**
 * Register read-only REST routes.
 */
function ksrfp_rewrite_metrics_register_routes()
{
    register_rest_route(
        'ksrfp-rewrite/v1',
        '/post-metrics',
        array(
            array(
                'methods'             => WP_REST_Server::READABLE,
                'callback'            => 'ksrfp_rewrite_metrics_get_post_metrics',
                'permission_callback' => 'ksrfp_rewrite_metrics_permission',
                'args'                => array(
                    'post_type'          => array(
                        'default'           => 'post',
                        'sanitize_callback' => 'sanitize_key',
                        'validate_callback' => 'ksrfp_rewrite_metrics_validate_post_type',
                    ),
                    'status'             => array(
                        'default'           => 'publish',
                        'sanitize_callback' => 'sanitize_key',
                        'validate_callback' => 'ksrfp_rewrite_metrics_validate_post_status',
                    ),
                    'page'               => array(
                        'default'           => 1,
                        'sanitize_callback' => 'absint',
                        'validate_callback' => 'ksrfp_rewrite_metrics_validate_positive_int',
                    ),
                    'per_page'           => array(
                        'default'           => 100,
                        'sanitize_callback' => 'absint',
                        'validate_callback' => 'ksrfp_rewrite_metrics_validate_per_page',
                    ),
                    'days'               => array(
                        'default'           => 30,
                        'sanitize_callback' => 'absint',
                        'validate_callback' => 'ksrfp_rewrite_metrics_validate_days',
                    ),
                    'include_historical' => array(
                        'default'           => true,
                        'sanitize_callback' => 'rest_sanitize_boolean',
                    ),
                    'include_content'    => array(
                        'default'           => false,
                        'sanitize_callback' => 'rest_sanitize_boolean',
                    ),
                ),
            ),
        )
    );
}

/**
 * Require an authenticated user with a low-but-editorial capability.
 */
function ksrfp_rewrite_metrics_permission()
{
    if (!is_user_logged_in()) {
        return new WP_Error(
            'ksrfp_rewrite_metrics_auth_required',
            'Authentication is required.',
            array('status' => 401)
        );
    }

    $capability = apply_filters('ksrfp_rewrite_metrics_capability', 'edit_posts');

    if (!current_user_can($capability)) {
        return new WP_Error(
            'ksrfp_rewrite_metrics_forbidden',
            'The current user cannot read rewrite metrics.',
            array('status' => 403)
        );
    }

    return true;
}

/**
 * Validate requested post type.
 *
 * @param string $value Request value.
 * @return bool|WP_Error
 */
function ksrfp_rewrite_metrics_validate_post_type($value)
{
    if (post_type_exists($value)) {
        return true;
    }

    return new WP_Error(
        'ksrfp_rewrite_metrics_invalid_post_type',
        'Invalid post_type.',
        array('status' => 400)
    );
}

/**
 * Validate requested post status.
 *
 * @param string $value Request value.
 * @return bool|WP_Error
 */
function ksrfp_rewrite_metrics_validate_post_status($value)
{
    $allowed = array('publish', 'private', 'draft', 'pending', 'future', 'any');

    if (in_array($value, $allowed, true)) {
        return true;
    }

    return new WP_Error(
        'ksrfp_rewrite_metrics_invalid_status',
        'Invalid status.',
        array('status' => 400)
    );
}

/**
 * Validate positive integer.
 *
 * @param int $value Request value.
 * @return bool|WP_Error
 */
function ksrfp_rewrite_metrics_validate_positive_int($value)
{
    if ((int) $value >= 1) {
        return true;
    }

    return new WP_Error(
        'ksrfp_rewrite_metrics_invalid_positive_int',
        'Value must be 1 or greater.',
        array('status' => 400)
    );
}

/**
 * Validate page size.
 *
 * @param int $value Request value.
 * @return bool|WP_Error
 */
function ksrfp_rewrite_metrics_validate_per_page($value)
{
    $value = (int) $value;

    if ($value >= 1 && $value <= 100) {
        return true;
    }

    return new WP_Error(
        'ksrfp_rewrite_metrics_invalid_per_page',
        'per_page must be between 1 and 100.',
        array('status' => 400)
    );
}

/**
 * Validate recent view window.
 *
 * @param int $value Request value.
 * @return bool|WP_Error
 */
function ksrfp_rewrite_metrics_validate_days($value)
{
    $value = (int) $value;

    if ($value >= 1 && $value <= 3650) {
        return true;
    }

    return new WP_Error(
        'ksrfp_rewrite_metrics_invalid_days',
        'days must be between 1 and 3650.',
        array('status' => 400)
    );
}

/**
 * Return post metrics for rewrite candidate selection.
 *
 * @param WP_REST_Request $request Request object.
 * @return WP_REST_Response
 */
function ksrfp_rewrite_metrics_get_post_metrics($request)
{
    $post_type          = sanitize_key($request->get_param('post_type'));
    $status             = sanitize_key($request->get_param('status'));
    $page               = max(1, absint($request->get_param('page')));
    $per_page           = min(100, max(1, absint($request->get_param('per_page'))));
    $days               = min(3650, max(1, absint($request->get_param('days'))));
    $include_historical = rest_sanitize_boolean($request->get_param('include_historical'));
    $include_content    = rest_sanitize_boolean($request->get_param('include_content'));

    $query = new WP_Query(
        array(
            'post_type'           => $post_type,
            'post_status'         => $status,
            'posts_per_page'      => $per_page,
            'paged'               => $page,
            'orderby'             => 'date',
            'order'               => 'DESC',
            'ignore_sticky_posts' => true,
            'no_found_rows'       => false,
        )
    );

    $items = array();

    foreach ($query->posts as $post) {
        $items[] = ksrfp_rewrite_metrics_build_item($post, $days, $include_historical, $include_content);
    }

    $pages_table      = ksrfp_rewrite_metrics_wp_statistics_table('pages');
    $historical_table = ksrfp_rewrite_metrics_wp_statistics_table('historical');

    return rest_ensure_response(
        array(
            'status'       => 'ok',
            'version'      => KSRFP_REWRITE_METRICS_VERSION,
            'generated_at' => current_time('mysql'),
            'source'       => array(
                'wp_statistics_loaded'        => class_exists('WP_STATISTICS\DB'),
                'wp_statistics_pages_table'   => $pages_table,
                'wp_statistics_pages_exists'  => ksrfp_rewrite_metrics_table_exists($pages_table),
                'historical_table'            => $historical_table,
                'historical_table_exists'     => ksrfp_rewrite_metrics_table_exists($historical_table),
                'historical_included'         => $include_historical,
                'views_recent_days'           => $days,
                'word_count_meta_key'         => 'wp_statistics_words_count',
            ),
            'pagination'   => array(
                'page'        => $page,
                'per_page'    => $per_page,
                'total'       => (int) $query->found_posts,
                'total_pages' => (int) $query->max_num_pages,
            ),
            'items'        => $items,
        )
    );
}

/**
 * Build one post payload.
 *
 * @param WP_Post $post Post object.
 * @param int     $days Recent view window.
 * @param bool    $include_historical Whether historical WP Statistics rows are included.
 * @param bool    $include_content Whether raw post content is returned.
 * @return array
 */
function ksrfp_rewrite_metrics_build_item($post, $days, $include_historical, $include_content)
{
    $views        = ksrfp_rewrite_metrics_count_views($post, $days, $include_historical);
    $content_text = ksrfp_rewrite_metrics_normalize_content_text($post->post_content);
    $excerpt      = has_excerpt($post) ? get_the_excerpt($post) : wp_trim_words($content_text, 80, '');

    $item = array(
        'post_id'                  => (int) $post->ID,
        'post_type'                => $post->post_type,
        'status'                   => $post->post_status,
        'title'                    => get_the_title($post),
        'slug'                     => $post->post_name,
        'url'                      => get_permalink($post),
        'published_date'           => get_post_time('c', false, $post),
        'modified_date'            => get_post_modified_time('c', false, $post),
        'views_total'              => $views['total'],
        'views_recent'             => $views['recent'],
        'views_recent_days'        => $days,
        'views_historical'         => $views['historical'],
        'views_source_available'   => $views['source_available'],
        'wp_statistics_word_count' => ksrfp_rewrite_metrics_get_wp_statistics_word_count($post->ID),
        'computed_character_count' => ksrfp_rewrite_metrics_character_count($content_text),
        'computed_word_count'      => ksrfp_rewrite_metrics_space_word_count($content_text),
        'h2_count'                 => ksrfp_rewrite_metrics_heading_count($post->post_content, 2),
        'h3_count'                 => ksrfp_rewrite_metrics_heading_count($post->post_content, 3),
        'category_names'           => ksrfp_rewrite_metrics_term_names($post->ID, 'category'),
        'tag_names'                => ksrfp_rewrite_metrics_term_names($post->ID, 'post_tag'),
        'excerpt'                  => wp_strip_all_tags($excerpt),
    );

    if ($include_content) {
        $item['content_raw']  = $post->post_content;
        $item['content_text'] = $content_text;
    }

    return $item;
}

/**
 * Count total and recent views from WP Statistics tables.
 *
 * @param WP_Post $post Post object.
 * @param int     $days Recent view window.
 * @param bool    $include_historical Whether historical rows should be included in total.
 * @return array
 */
function ksrfp_rewrite_metrics_count_views($post, $days, $include_historical)
{
    global $wpdb;

    $pages_table = ksrfp_rewrite_metrics_wp_statistics_table('pages');

    if (!ksrfp_rewrite_metrics_table_exists($pages_table)) {
        return array(
            'total'            => 0,
            'recent'           => 0,
            'historical'       => 0,
            'source_available' => false,
        );
    }

    $resource_types = ksrfp_rewrite_metrics_wp_statistics_resource_types($post->post_type);
    $placeholders   = implode(', ', array_fill(0, count($resource_types), '%s'));
    $type_args      = array_values($resource_types);

    $total_sql  = "SELECT COALESCE(SUM(`count`), 0) FROM `{$pages_table}` WHERE `id` = %d AND `type` IN ({$placeholders})";
    $total_args = array_merge(array((int) $post->ID), $type_args);
    $total      = (int) $wpdb->get_var(ksrfp_rewrite_metrics_prepare($total_sql, $total_args)); // phpcs:ignore WordPress.DB.PreparedSQL.NotPrepared

    $from_date   = wp_date('Y-m-d', time() - (($days - 1) * DAY_IN_SECONDS));
    $recent_sql  = "SELECT COALESCE(SUM(`count`), 0) FROM `{$pages_table}` WHERE `id` = %d AND `type` IN ({$placeholders}) AND `date` >= %s";
    $recent_args = array_merge(array((int) $post->ID), $type_args, array($from_date));
    $recent      = (int) $wpdb->get_var(ksrfp_rewrite_metrics_prepare($recent_sql, $recent_args)); // phpcs:ignore WordPress.DB.PreparedSQL.NotPrepared

    $historical = 0;

    if ($include_historical) {
        $historical = ksrfp_rewrite_metrics_count_historical_views($post);
        $total     += $historical;
    }

    return array(
        'total'            => $total,
        'recent'           => $recent,
        'historical'       => $historical,
        'source_available' => true,
    );
}

/**
 * Count historical views stored by WP Statistics migrations/imports.
 *
 * @param WP_Post $post Post object.
 * @return int
 */
function ksrfp_rewrite_metrics_count_historical_views($post)
{
    global $wpdb;

    $historical_table = ksrfp_rewrite_metrics_wp_statistics_table('historical');

    if (!ksrfp_rewrite_metrics_table_exists($historical_table)) {
        return 0;
    }

    $permalink = get_permalink($post);

    if (!$permalink || is_wp_error($permalink)) {
        return 0;
    }

    $uri = wp_make_link_relative($permalink);

    if ('' === $uri) {
        return 0;
    }

    $sql = "SELECT COALESCE(SUM(`value`), 0) FROM `{$historical_table}` WHERE `page_id` = %d AND `category` = %s AND `uri` = %s";

    return (int) $wpdb->get_var(
        $wpdb->prepare($sql, (int) $post->ID, 'uri', $uri) // phpcs:ignore WordPress.DB.PreparedSQL.NotPrepared
    );
}

/**
 * Get the WP Statistics physical table name.
 *
 * @param string $table Logical table name.
 * @return string
 */
function ksrfp_rewrite_metrics_wp_statistics_table($table)
{
    global $wpdb;

    $table = sanitize_key($table);

    if (class_exists('WP_STATISTICS\DB') && method_exists('WP_STATISTICS\DB', 'table')) {
        return WP_STATISTICS\DB::table($table);
    }

    return $wpdb->prefix . 'statistics_' . $table;
}

/**
 * Check whether a database table exists.
 *
 * @param string $table Table name.
 * @return bool
 */
function ksrfp_rewrite_metrics_table_exists($table)
{
    global $wpdb;

    static $cache = array();

    if (array_key_exists($table, $cache)) {
        return $cache[$table];
    }

    $cache[$table] = $wpdb->get_var($wpdb->prepare('SHOW TABLES LIKE %s', $table)) === $table;

    return $cache[$table];
}

/**
 * Prepare SQL with a dynamic argument list.
 *
 * @param string $sql SQL with placeholders.
 * @param array  $args Prepare arguments.
 * @return string
 */
function ksrfp_rewrite_metrics_prepare($sql, $args)
{
    global $wpdb;

    return call_user_func_array(array($wpdb, 'prepare'), array_merge(array($sql), $args));
}

/**
 * WP Statistics stores regular posts as "post" and custom post types as "post_type_{name}".
 *
 * @param string $post_type WordPress post type.
 * @return array
 */
function ksrfp_rewrite_metrics_wp_statistics_resource_types($post_type)
{
    $types = array($post_type);

    if (!in_array($post_type, array('post', 'page'), true)) {
        $types[] = 'post_type_' . $post_type;
    }

    if ('product' === $post_type) {
        $types[] = 'product';
    }

    return array_values(array_unique($types));
}

/**
 * Read WP Statistics word count meta if it is present.
 *
 * @param int $post_id Post ID.
 * @return int|null
 */
function ksrfp_rewrite_metrics_get_wp_statistics_word_count($post_id)
{
    $value = get_post_meta($post_id, 'wp_statistics_words_count', true);

    if ('' === $value) {
        return null;
    }

    return (int) $value;
}

/**
 * Normalize HTML/block content into plain text.
 *
 * @param string $content Raw post content.
 * @return string
 */
function ksrfp_rewrite_metrics_normalize_content_text($content)
{
    $text = strip_shortcodes($content);
    $text = wp_strip_all_tags($text, true);
    $text = html_entity_decode($text, ENT_QUOTES, get_bloginfo('charset') ? get_bloginfo('charset') : 'UTF-8');
    $text = preg_replace('/\s+/u', ' ', $text);

    return trim($text);
}

/**
 * Count non-whitespace characters. This works better than word count for Japanese content.
 *
 * @param string $text Plain text.
 * @return int
 */
function ksrfp_rewrite_metrics_character_count($text)
{
    $compact = preg_replace('/\s+/u', '', $text);

    if (function_exists('mb_strlen')) {
        return (int) mb_strlen($compact, 'UTF-8');
    }

    return strlen($compact);
}

/**
 * Count whitespace-separated tokens as a rough companion metric.
 *
 * @param string $text Plain text.
 * @return int
 */
function ksrfp_rewrite_metrics_space_word_count($text)
{
    $text = trim(preg_replace('/\s+/u', ' ', $text));

    if ('' === $text) {
        return 0;
    }

    return count(preg_split('/\s+/u', $text));
}

/**
 * Count heading tags in rendered post content.
 *
 * @param string $content Raw post content.
 * @param int    $level Heading level.
 * @return int
 */
function ksrfp_rewrite_metrics_heading_count($content, $level)
{
    $level = (int) $level;

    if ($level < 1 || $level > 6) {
        return 0;
    }

    preg_match_all('/<h' . $level . '\b[^>]*>/i', $content, $matches);

    return count($matches[0]);
}

/**
 * Return term names for a taxonomy.
 *
 * @param int    $post_id Post ID.
 * @param string $taxonomy Taxonomy.
 * @return array
 */
function ksrfp_rewrite_metrics_term_names($post_id, $taxonomy)
{
    $terms = get_the_terms($post_id, $taxonomy);

    if (empty($terms) || is_wp_error($terms)) {
        return array();
    }

    $names = array();

    foreach ($terms as $term) {
        $names[] = $term->name;
    }

    return $names;
}
