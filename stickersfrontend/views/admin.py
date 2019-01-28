import math
import json
import urllib
import time

from ipaddress import ip_address
from flask import Blueprint, render_template, abort, request, redirect
from flask import url_for, g
import dateutil.parser

from pagination_from_request import pagination_from_request
from . import require_sticker, require_collected_sticker
from . import require_sticker_placement
from accounts.views import require_permissions

stickers_admin = Blueprint(
	'stickers_admin',
	__name__,
	template_folder='templates',
)

def post_sticker(template, sticker=None, **kwargs):
	for field in ['name', 'display', 'category', 'category_order']:
		if field not in request.form:
			abort(400, 'Missing sticker settings fields')
	opts = {
		'name': request.form['name'],
		'display': request.form['display'],
		'category': request.form['category'],
		'category_order': request.form['category_order'],
		'group_bits': 0,
	}
	if not opts['category_order']:
		opts['category_order'] = 0
	try:
		opts['category_order'] = int(opts['category_order'])
	except:
		opts['category_order'] = 0
	selected_groups = []
	for group_name in g.stickers.accounts.available_groups:
		if 'group_' + group_name in request.form:
			selected_groups.append(group_name)
	if selected_groups:
		opts['group_bits'] = g.stickers.accounts.combine_groups(
			names=selected_groups,
		)
	if not sticker:
		sticker = g.stickers.create_sticker(**opts)
	else:
		g.stickers.update_sticker(sticker.id_bytes, **opts)
		sticker = g.stickers.get_sticker(sticker.id_bytes)
	errors = []
	if 'remove_sticker_image' in request.form:
		g.stickers.remove_sticker_image(sticker)
	elif 'sticker_image' in request.files:
		try:
			image = g.stickers.process_sticker_image(request.files['sticker_image'])
		except ValueError as e:
			errors.append(str(e))
		else:
			g.stickers.remove_sticker_image(sticker)
			g.stickers.add_sticker_image(sticker, image)
	if not errors:
		return redirect(
			url_for('stickers_admin.edit_sticker', sticker_id=sticker.id),
			code=303,
		)
	return render_template(
		template,
		sticker=sticker,
		name=request.form['name'],
		display=request.form['display'],
		category=request.form['category'],
		category_order=request.form['category_order'],
		errors=errors,
		groups=g.stickers.accounts.available_groups,
		selected_groups=selected_groups,
	)

@stickers_admin.route('/stickers/create', methods=['GET', 'POST'])
@require_permissions(group_names='admin')
def create_sticker():
	if 'POST' != request.method:
		return render_template(
			'create_sticker.html',
			sticker=None,
			groups=g.stickers.accounts.available_groups,
		)
	return post_sticker('create_sticker.html')

@stickers_admin.route('/stickers/<sticker_id>/edit', methods=['GET', 'POST'])
@require_permissions(group_names='admin')
def edit_sticker(sticker_id):
	sticker = require_sticker(sticker_id)
	if 'POST' != request.method:
		return render_template(
			'edit_sticker.html',
			sticker=sticker,
			name=sticker.name,
			display=sticker.display,
			category=sticker.category,
			category_order=sticker.category_order,
			groups=g.stickers.accounts.available_groups,
			selected_groups=sticker.group_names,
		)
	return post_sticker('edit_sticker.html', sticker)

@stickers_admin.route('/stickers/<sticker_id>/remove')
@require_permissions(group_names='admin')
def remove_sticker(sticker_id):
	sticker = require_sticker(sticker_id)
	g.stickers.delete_sticker(
		sticker,
		g.stickers.accounts.current_user.id_bytes,
	)
	if 'redirect_uri' in request.args:
		return redirect(request.args['redirect_uri'], code=303)
	return redirect(url_for('stickers_admin.stickers_list'), code=303)

@stickers_admin.route('/stickers')
@require_permissions(group_names='admin')
def stickers_list():
	search = {
		'id': '',
		'created_before': '',
		'created_after': '',
		'name': '',
		'display': '',
		'category': '',
		#'category_order_more_than': '',
		#'category_order_less_than': '',
	}
	for field in search:
		if field in request.args:
			search[field] = request.args[field]

	filter = {}
	escape = lambda value: (
		value
			.replace('\\', '\\\\')
			.replace('_', '\_')
			.replace('%', '\%')
			.replace('-', '\-')
	)
	# for parsing datetime and timestamp from submitted form
	# filter fields are named the same as search fields
	time_fields = [
		'created_before',
		'created_after',
	]
	for field, value in search.items():
		if not value:
			continue
		if 'id' == field:
			filter['ids'] = value
		elif field in time_fields:
			try:
				parsed = dateutil.parser.parse(value)
			except ValueError:
				filter[field] = 'bad_query'
			else:
				search[field] = parsed.strftime('%Y-%m-%dT%H:%M:%S.%f%z')
				filter[field] = parsed.timestamp()
		elif 'name' == field:
			filter['name'] = '%' + escape(value) + '%'
		elif 'display' == field:
			filter['display'] = '%' + escape(value) + '%'
		elif 'category' == field:
			filter['category'] = escape(value)

	pagination = pagination_from_request('creation_time', 'desc', 0, 32)

	total_results = g.stickers.count_stickers(filter=filter)
	results = g.stickers.search_stickers(filter=filter, **pagination)

	#TODO this is probably fine for now since the total number of stickers
	#TODO will probably remain small, and the admin panels will probably be
	#TODO accessed infrequently
	#TODO but eventually add another count method for multiple sticker_ids
	#TODO to stickers module so that this can be done in just two queries total
	#TODO instead of two queries per row
	for result in results.values():
		result.total_collected = g.stickers.count_collected_stickers(
			filter={'sticker_ids': result.id_bytes},
		)
		result.total_placed = 0
		result.total_placed = g.stickers.count_sticker_placements(
			filter={'sticker_ids': result.id_bytes},
		)

	categories = g.stickers.config['categories']
	unique_categories = g.stickers.get_unique_categories()
	for category in unique_categories:
		if category not in categories:
			categories.append(category)
	return render_template(
		'stickers_list.html',
		results=results,
		search=search,
		pagination=pagination,
		total_results=total_results,
		total_pages=math.ceil(total_results / pagination['perpage']),
		unique_categories=categories,
	)

@stickers_admin.route('/collected-stickers')
@require_permissions(group_names='admin')
def collected_stickers_list():
	search = {
		'id': '',
		'received_before': '',
		'received_after': '',
		'user_id': '',
		'sticker_id': '',
	}
	for field in search:
		if field in request.args:
			search[field] = request.args[field]

	filter = {}
	# for parsing datetime and timestamp from submitted form
	# filter fields are named the same as search fields
	time_fields = [
		'received_before',
		'received_after',
	]
	for field, value in search.items():
		if not value:
			continue
		if 'id' == field:
			filter['ids'] = value
		elif field in time_fields:
			try:
				parsed = dateutil.parser.parse(value)
			except ValueError:
				filter[field] = 'bad_query'
			else:
				search[field] = parsed.strftime('%Y-%m-%dT%H:%M:%S.%f%z')
				filter[field] = parsed.timestamp()
		elif 'user_id' == field:
			filter['user_ids'] = value
		elif 'sticker_id' == field:
			filter['sticker_ids'] = value

	pagination = pagination_from_request('receive_time', 'desc', 0, 32)

	total_results = g.stickers.count_collected_stickers(filter=filter)
	results = g.stickers.search_collected_stickers(filter=filter, **pagination)

	return render_template(
		'collected_stickers_list.html',
		results=results,
		search=search,
		pagination=pagination,
		total_results=total_results,
		total_pages=math.ceil(total_results / pagination['perpage']),
	)

@stickers_admin.route('/collected-stickers/grant', methods=['GET', 'POST'])
@require_permissions(group_names='admin')
def grant_sticker():
	stickers = g.stickers.search_stickers()
	if 'POST' != request.method:
		return render_template('grant_sticker.html', stickers=stickers)
	for field in ['user_id', 'sticker_id']:
		if field not in request.form:
			abort(400, 'Missing grant sticker fields')
	errors = []
	try:
		collected_sticker = g.stickers.grant_sticker(
			request.form['sticker_id'],
			request.form['user_id'],
			g.stickers.accounts.current_user.id_bytes,
		)
	except ValueError as e:
		if 'Specified user already has the specified sticker' == str(e):
			errors.append(str(e))
		else:
			raise
	if not errors:
		return redirect(
			url_for(
				'stickers_admin.collected_stickers_list',
				id=collected_sticker.id,
			),
			code=303,
		)
	return render_template(
		'grant_sticker.html',
		stickers=stickers,
		errors=errors,
		user_id=request.form['user_id'],
		sticker_id=request.form['sticker_id'],
	)

@stickers_admin.route('/collected-stickers/<collected_sticker_id>/revoke')
@require_permissions(group_names='admin')
def revoke_sticker(collected_sticker_id):
	collected_sticker = require_collected_sticker(collected_sticker_id)
	g.stickers.revoke_sticker(
		collected_sticker.id_bytes,
		collected_sticker.user_id_bytes,
		g.stickers.accounts.current_user.id_bytes,
	)
	if 'redirect_uri' in request.args:
		return redirect(request.args['redirect_uri'], code=303)
	return redirect(
		url_for('stickers_admin.collected_stickers_list'),
		code=303,
	)

@stickers_admin.route('/sticker-placements')
@require_permissions(group_names='admin')
def sticker_placements_list():
	search = {
		'id': '',
		'placed_before': '',
		'placed_after': '',
		'user_id': '',
		'sticker_id': '',
		'subject_id': '',
	}
	for field in search:
		if field in request.args:
			search[field] = request.args[field]

	filter = {}
	# for parsing datetime and timestamp from submitted form
	# filter fields are named the same as search fields
	time_fields = [
		'placed_before',
		'placed_after',
	]
	for field, value in search.items():
		if not value:
			continue
		if 'id' == field:
			filter['ids'] = value
		elif field in time_fields:
			try:
				parsed = dateutil.parser.parse(value)
			except ValueError:
				filter[field] = 'bad_query'
			else:
				search[field] = parsed.strftime('%Y-%m-%dT%H:%M:%S.%f%z')
				filter[field] = parsed.timestamp()
		elif 'user_id' == field:
			filter['user_ids'] = value
		elif 'sticker_id' == field:
			filter['sticker_ids'] = value
		elif 'subject_id' == field:
			filter['subject_ids'] = value

	pagination = pagination_from_request('placement_time', 'desc', 0, 32)

	total_results = g.stickers.count_sticker_placements(filter=filter)
	results = g.stickers.search_sticker_placements(filter=filter, **pagination)

	return render_template(
		'sticker_placements_list.html',
		results=results,
		search=search,
		pagination=pagination,
		total_results=total_results,
		total_pages=math.ceil(total_results / pagination['perpage']),
	)

@stickers_admin.route('/sticker-placements/<id>/unplace')
@require_permissions(group_names='admin')
def unplace_sticker(id):
	#TODO confirmation?
	placement = require_sticker_placement(id)
	g.stickers.unplace_sticker(placement.id)
	g.stickers.generate_sticker_placements_file(placement.subject_id)
	if 'redirect_uri' in request.args:
		return redirect(request.args['redirect_uri'], code=303)
	return redirect(
		url_for('stickers_admin.sticker_placements_list'),
		code=303,
	)

@stickers_admin.route('/sticker-placements/unplace', methods=['GET', 'POST'])
@require_permissions(group_names='admin')
def unplace_stickers():
	if 'POST' != request.method:
		return render_template('mass_unplace_stickers.html')
	if 'user_id' not in request.form:
		abort(400)
	#TODO get all subjects target user has placed stickers on
	#TODO and generate their sticker placements files?
	g.stickers.unplace_by_user(
		request.form['user_id'],
		g.stickers.accounts.current_user.id_bytes,
	)
	return redirect(url_for('stickers_admin.sticker_placements_list'), code=303)
