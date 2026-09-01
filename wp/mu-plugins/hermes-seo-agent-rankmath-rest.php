<?php
/**
 * Plugin Name: Hermes SEO Agent — Rank Math REST meta
 * Description: Exposes Rank Math SEO meta fields (title/description/focus
 *              keyword) to the WordPress REST API so the SEO agent can read
 *              and write them via Application Password (server-to-server).
 * Version: 1.0.0
 *
 * INSTALL: copy this file to wp-content/mu-plugins/ (no activation needed).
 * Required so `apply` (fix type wp_post_meta) can write Rank Math fields —
 * without it, WordPress REST silently drops the meta write.
 */

if ( ! defined( 'ABSPATH' ) ) {
	exit;
}

add_action( 'rest_api_init', function () {
	$fields = array(
		'rank_math_title'           => 'string',
		'rank_math_description'     => 'string',
		'rank_math_focus_keyword'   => 'string',
	);

	foreach ( $fields as $key => $type ) {
		register_post_meta(
			'post',
			$key,
			array(
				'show_in_rest'  => true,
				'single'        => true,
				'type'          => $type,
				'auth_callback' => function () {
					return current_user_can( 'edit_posts' );
				},
			)
		);
	}
} );
