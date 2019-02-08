from functools import wraps
import time
import hashlib

from flask import g, make_response, render_template, redirect
from flask import url_for, request, abort

from .. import StickersFrontend

def initialize(config, accounts, access_log, engine, install):
	g.stickers = StickersFrontend(
		config,
		accounts,
		access_log,
		engine,
		install=install,
	)

	# use default sticker image file uri if custom uri isn't specified
	if not g.stickers.config['sticker_image_file_uri']:
		g.stickers.config['sticker_image_file_uri'] = url_for(
			'stickers_signed_out.sticker_image_file',
			sticker_image_filename='STICKER_IMAGE_FILENAME'
		).replace('STICKER_IMAGE_FILENAME', '{}')

	# use default sticker placements file uri if custom uri isn't specified
	if not g.stickers.config['sticker_placements_file_uri']:
		g.stickers.config['sticker_placements_file_uri'] = url_for(
			'stickers_static.placements_file',
			placements_filename='STICKER_PLACEMENTS_FILENAME'
		).replace('STICKER_PLACEMENTS_FILENAME', '{}')

	if g.stickers.accounts.current_user:
		# check for custom max stickers per target
		if '' in g.stickers.accounts.current_user.permissions:
			groups = g.stickers.accounts.current_user.permissions[''].group_names
			custom = g.stickers.config['maximum_stickers_per_target_custom']
			for group, maximum in custom.items():
				if group in groups:
					# no limit or no stickers
					if -1 == maximum or 0 == maximum:
						g.stickers.config['maximum_stickers_per_target'] = maximum
						break
					g.stickers.config['maximum_stickers_per_target'] = max(
						g.stickers.config['maximum_stickers_per_target'],
						maximum,
					)

# require objects or abort
def require_sticker(id):
	try:
		sticker = g.stickers.require_sticker(id)
	except ValueError as e:
		abort(404, str(e))
	else:
		return sticker

def require_collected_sticker(id):
	try:
		collected_sticker = g.stickers.require_collected_sticker(id)
	except ValueError as e:
		abort(404, str(e))
	else:
		return collected_sticker

def require_sticker_placement(id):
	try:
		sticker_placement = g.stickers.require_sticker_placement(id)
	except ValueError as e:
		abort(404, str(e))
	else:
		return sticker_placement
