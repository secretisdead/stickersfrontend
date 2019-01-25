import time
import os

from flask import Blueprint, render_template, abort, request, redirect
from flask import url_for, g, send_from_directory

stickers_signed_out = Blueprint(
	'stickers_signed_out',
	__name__,
)

@stickers_signed_out.route('/images/<sticker_image_filename>')
def sticker_image_file(sticker_image_filename):
	if '.' not in sticker_image_filename:
		sticker_image_filename += '.webp'
	if not os.path.exists(
			os.path.join(
				g.stickers.config['sticker_images_path'],
				sticker_image_filename,
			)
		):
		abort(404)
	return send_from_directory(
		g.stickers.config['sticker_images_path'],
		sticker_image_filename,
		conditional=True,
	)
