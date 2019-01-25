import time
import os

from flask import Blueprint, abort, request
from flask import g, send_from_directory

stickers_static = Blueprint(
	'stickers_static',
	__name__,
)

@stickers_static.route('/placements/<placements_filename>')
def placements_file(placements_filename):
	if not os.path.exists(
			os.path.join(
				g.stickers.config['sticker_placements_path'],
				placements_filename,
			)
		):
		abort(404)
	return send_from_directory(
		g.stickers.config['sticker_placements_path'],
		placements_filename,
		conditional=True,
	)
