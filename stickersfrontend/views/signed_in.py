import time
import json
from datetime import datetime
import random

from flask import Blueprint, render_template, abort, request, redirect
from flask import url_for, g, make_response

from accounts.views import require_sign_in
from . import require_sticker, require_sticker_placement

stickers_api = Blueprint(
	'stickers_api',
	__name__,
)

#TODO json response instead of plaintext for errors? this is fine for now.
@stickers_api.route('/place', methods=['POST'])
@require_sign_in
def api_place_sticker():
	if (
			'subject_id' not in request.form or not request.form['subject_id']
			or 'sticker_id' not in request.form or not request.form['sticker_id']
		):
		return 'Missing sticker placement information', 400
	if 'position_x' not in request.form or 'position_y' not in request.form:
		return 'Missing sticker placement position', 400

	sticker = require_sticker(request.form['sticker_id'])

	#TODO check for valid subject id?
	subject_id = request.form['subject_id']
	user_id = g.stickers.accounts.current_user.id_bytes
	if g.accounts.current_user.has_permission(group_names='manager'):
		if 'user_id' in request.form and request.form['user_id']:
			#TODO check for existing user?
			#TODO or at least for valid user id?
			user_id = request.form['user_id']
	else:
		if g.stickers.place_sticker_cooldown(
				remote_origin=str(request.remote_addr),
				user_id=g.stickers.accounts.current_user.id_bytes,
			):
			return 'Please wait a bit before placing another sticker', 429
		# check if user possesses sticker in attempted placement
		collected_sticker = g.stickers.search_collected_stickers(
			filter={
				'user_ids': g.stickers.accounts.current_user.id_bytes,
				'sticker_ids': sticker.id,
			}
		)
		if not collected_sticker.values():
			return 'Specified sticker not collected', 400
		g.stickers.prune_user_sticker_placements(
			subject_id,
			g.stickers.accounts.current_user.id_bytes,
			g.stickers.config['maximum_stickers_per_target'],
		)

	placement = g.stickers.place_sticker(
		user_id=user_id,
		sticker_id=sticker.id,
		subject_id=subject_id,
		position_x=float(request.form['position_x']),
		position_y=float(request.form['position_y']),
		#rotation=float(request.form['rotation']),
		#scale=float(request.form['scale']),
	)
	g.stickers.generate_sticker_placements_file(subject_id)

	r = make_response(
		json.dumps(
			{
				'placement_id': placement.id,
				'placement_time': placement.placement_time,
			}
		)
	)
	r.mimetype = 'application/json'
	return r, 200

#TODO json response instead of plaintext for errors? this is fine for now.
@stickers_api.route('/unplace', methods=['POST'])
@require_sign_in
def api_unplace_sticker():
	if 'placement_id' not in request.form or not request.form['placement_id']:
		return 'Missing sticker placement ID', 400

	placement = require_sticker_placement(request.form['placement_id'])

	if not g.stickers.accounts.current_user.has_permission(group_names='manager'):
		if placement.user_id != g.stickers.accounts.current_user.id:
			return 'Sticker placement user mismatch', 403

	g.stickers.unplace_sticker(
		placement.id,
		g.stickers.accounts.current_user.id,
	)
	g.stickers.generate_sticker_placements_file(placement.subject_id)
	return '', 200

def process_gachapon_request():
	collected_stickers = g.stickers.search_collected_stickers(
		filter={'user_ids': g.stickers.accounts.current_user.id_bytes},
	)
	sticker = None
	errors = []
	cooldown, last_received_sticker = g.stickers.gachapon_cooldown(collected_stickers)
	if cooldown:
		errors.append('You already got a sticker recently')
		next_available_datetime = datetime.fromtimestamp(cooldown)
		last_received_datetime = last_received_sticker.receive_datetime
	else:
		next_available_datetime = None
		last_received_datetime = None
		if '' in g.stickers.accounts.current_user.permissions:
			group_bits = g.stickers.accounts.current_user.permissions[''].group_bits
		else:
			group_bits = group_bits = 0
		potential_stickers = g.stickers.get_potential_stickers(group_bits)
		for collected_sticker in collected_stickers.values():
			potential_stickers.remove(collected_sticker.sticker)
		if 0 == len(potential_stickers):
			errors.append('You have all the stickers you can get')
		else:
			sticker_id = random.choice(potential_stickers.keys())
			sticker = potential_stickers.get(sticker_id)
			collected_sticker = g.stickers.grant_sticker(
				sticker.id_bytes,
				g.stickers.accounts.current_user.id_bytes,
			)
	return sticker, errors, next_available_datetime, last_received_datetime

@stickers_api.route('/gachapon', methods=['POST'])
@require_sign_in
def api_gachapon():
	def minify(text):
		return text.replace(
			'\r',
			'',
		).replace(
			'\n',
			'',
		).replace(
			'\t',
			'',
		)
	sticker, errors, next_available_datetime, last_received_datetime = process_gachapon_request()
	if errors:
		response_data = {
			'message': minify(
				render_template(
					'gachapon_errors.html',
					errors=errors,
					next_available_datetime=next_available_datetime,
					last_received_datetime=last_received_datetime,
				)
			)
		}
		status = 400
	else:
		response_data = {
			'sticker': minify(render_template('sticker.html', sticker=sticker)),
			'message': minify(render_template('gachapon_success.html')),
		}
		status = 200
	r = make_response(json.dumps(response_data))
	r.mimetype = 'application/json'
	return r, status

stickers_signed_in = Blueprint(
	'stickers_signed_in',
	__name__,
	template_folder='templates',
)

@stickers_signed_in.route('/gachapon')
@require_sign_in
def gachapon():
	if 'request' not in request.args:
		return render_template('gachapon.html')
	sticker, errors, next_available_datetime, last_received_datetime = process_gachapon_request()
	return render_template(
		'gachapon.html',
		sticker=sticker,
		errors=errors,
		next_available_datetime=next_available_datetime,
		last_received_datetime=last_received_datetime,
	)
