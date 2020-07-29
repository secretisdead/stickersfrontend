import time
import json
from datetime import datetime, timezone
import re
import uuid
import os

from PIL import Image
from flask import render_template

from stickers import Stickers

class StickersFrontend(Stickers):
	def __init__(
			self,
			config,
			accounts,
			access_log,
			engine,
			install=False,
			connection=None,
		):
		super().__init__(
			engine,
			config['db_prefix'],
			install=install,
			connection=connection,
		)

		self.config = config
		self.accounts = accounts
		self.access_log = access_log

		self.config['maximum_name_length'] = min(
			self.name_length,
			self.config['maximum_name_length'],
		)
		self.config['maximum_display_length'] = min(
			self.display_length,
			self.config['maximum_display_length'],
		)
		self.config['maximum_category_length'] = self.category_length

		self.callbacks = {}

	def add_callback(self, name, f):
		if name not in self.callbacks:
			self.callbacks[name] = []
		self.callbacks[name].append(f)

	# cooldowns
	def gachapon_cooldown(self, collected_stickers):
		current_time = time.time()
		if not self.config['receive_sticker_cooldown_periods_by_utc']:
			period_start_time = (
				current_time - self.config['receive_sticker_cooldown_period']
			)
			oldest_this_period = current_time
			for collected_sticker in collected_stickers.values():
				if collected_sticker.receive_time > period_start_time:
					oldest_this_period = min(
						oldest_this_period,
						collected_sticker.receive_time,
					)
			period_end_time = (
				oldest_this_period + self.config['receive_sticker_cooldown_period']
			)
		else:
			# start at current utc day's midnight
			current_datetime = datetime.now(timezone.utc)
			period_end_time = datetime.datetime(
				current_datetime.year,
				current_datetime.month,
				current_datetime.day,
				0,
				0,
				0,
				0,
				timezone.utc,
			).timestamp()
			while period_end_time < current_time:
				period_end_time += self.config['receive_sticker_cooldown_period']
			period_start_time = (
				period_end_time
				+ self.config['receive_sticker_cooldown_period']
			)
		received_this_period = 0
		last_received_sticker = None
		for collected_sticker in collected_stickers.values():
			if (
					not last_received_sticker
					or last_received_sticker.receive_time < collected_sticker.receive_time
				):
				last_received_sticker = collected_sticker
			if collected_sticker.receive_time > period_start_time:
				received_this_period += 1
		if received_this_period < self.config['receive_sticker_cooldown_amount']:
			return 0, last_received_sticker
		return int(period_end_time), last_received_sticker

	def place_sticker_cooldown(self, remote_origin, user_id):
		return self.access_log.cooldown(
			'place_sticker',
			self.config['place_sticker_cooldown_amount'],
			self.config['place_sticker_cooldown_period'],
			remote_origin=remote_origin,
			subject_id=user_id,
		)

	# require object or raise
	def require_sticker(self, id):
		sticker = self.get_sticker(id)
		if not sticker:
			raise ValueError('Sticker not found')
		return sticker

	def require_collected_sticker(self, id):
		collected_sticker = self.get_collected_sticker(id)
		if not collected_sticker:
			raise ValueError('Collected sticker not found')
		return collected_sticker

	def require_sticker_placement(self, id):
		sticker_placement = self.get_sticker_placement(id)
		if not sticker_placement:
			raise ValueError('Sticker placement not found')
		return sticker_placement

	# extend stickers methods
	def get_sticker(self, sticker_id):
		sticker = super().get_sticker(sticker_id)
		if sticker:
			self.populate_sticker_properties(sticker)
		return sticker

	def search_stickers(self, **kwargs):
		stickers = super().search_stickers(**kwargs)
		for sticker in stickers.values():
			self.populate_sticker_properties(sticker)
		return stickers

	def get_collected_sticker(self, collected_sticker_id):
		collected_sticker = super().get_collected_sticker(collected_sticker_id)
		if collected_sticker:
			self.populate_sticker_properties(collected_sticker.sticker)
			users = self.accounts.search_users(
				filter={'ids': collected_sticker.user_id},
			)
			if collected_sticker.user_id in users:
				collected_sticker.user = users.get(collected_sticker.user_id_bytes)
		return collected_sticker

	def search_collected_stickers(self, **kwargs):
		collected_stickers = super().search_collected_stickers(**kwargs)
		user_ids = []
		for collected_sticker in collected_stickers.values():
			self.populate_sticker_properties(collected_sticker.sticker)
			if collected_sticker.user_id:
				user_ids.append(collected_sticker.user_id)
		users = self.accounts.search_users(filter={'ids': user_ids})
		for collected_sticker in collected_stickers.values():
			if collected_sticker.user_id in users:
				collected_sticker.user = users.get(collected_sticker.user_id_bytes)
		return collected_stickers

	def get_sticker_placement(self, sticker_placement_id):
		sticker_placement = super().get_sticker_placement(sticker_placement_id)
		if sticker_placement:
			self.populate_sticker_properties(sticker_placement.sticker)
			users = self.accounts.search_users(
				filter={'ids': sticker_placement.user_id},
			)
			if sticker_placement.user_id in users:
				sticker_placement.user = users.get(sticker_placement.user_id_bytes)
		return sticker_placement

	def search_sticker_placements(self, **kwargs):
		sticker_placements = super().search_sticker_placements(**kwargs)
		user_ids = []
		for sticker_placement in sticker_placements.values():
			self.populate_sticker_properties(sticker_placement.sticker)
			if sticker_placement.user_id:
				user_ids.append(sticker_placement.user_id)
		users = self.accounts.search_users(filter={'ids': user_ids})
		for sticker_placement in sticker_placements.values():
			if sticker_placement.user_id in users:
				sticker_placement.user = users.get(sticker_placement.user_id_bytes)
		return sticker_placements

	def create_sticker(self, **kwargs):
		sticker = super().create_sticker(**kwargs)
		subject_id = ''
		if self.accounts.current_user:
			subject_id = self.accounts.current_user.id_bytes
		self.access_log.create_log(
			scope='create_sticker',
			subject_id=subject_id,
			object_id=sticker.id,
		)
		return sticker

	def update_sticker(self, id, **kwargs):
		super().update_sticker(id, **kwargs)
		subject_id = ''
		if self.accounts.current_user:
			subject_id = self.accounts.current_user.id_bytes
		self.access_log.create_log(
			scope='update_sticker',
			subject_id=subject_id,
			object_id=id,
		)

	def delete_sticker(self, sticker, user_id):
		self.remove_sticker_image(sticker)
		super().delete_sticker(sticker.id_bytes)
		self.access_log.create_log(
			scope='delete_sticker',
			subject_id=user_id,
			object_id=sticker.id_bytes,
		)

	def add_sticker_image(self, sticker, image):
		sticker_image_path = os.path.join(self.config['sticker_images_path'], sticker.id)

		edge = self.config['sticker_edge']
		image_copy = image.copy()
		image_copy.thumbnail((edge, edge), Image.BICUBIC)

		# static
		thumbnail_path = sticker_image_path + '.webp'
		image_copy.save(thumbnail_path, 'WebP', lossless=True)

		# fallback
		thumbnail_path = sticker_image_path + '.png'
		image_copy.save(thumbnail_path, 'PNG', optimize=True)

		image_copy.close()

	def remove_sticker_image(self, sticker):
		sticker_image_path = os.path.join(self.config['sticker_images_path'], sticker.id)
		extensions = ['webp', 'png']
		for extension in extensions:
			if os.path.exists(sticker_image_path + '.' + extension):
				os.remove(sticker_image_path + '.' + extension)

	def process_sticker_image(self, sticker_image):
		errors = []
		try:
			file_contents = sticker_image.stream.read()
		except ValueError as e:
			raise ValueError('Problem uploading sticker_image')

		file_path = os.path.join(
			self.config['temp_path'],
			'temp_sticker_image_' + str(uuid.uuid4()),
		)
		f = open(file_path, 'w+b')
		f.write(file_contents)
		f.close()

		try:
			image = Image.open(file_path)
		# catch general exceptions here in case of problem reading image file
		except:
			#TODO file in use?
			#os.remove(file_path)
			raise ValueError('Problem opening sticker image')
		else:
			return image

	def populate_sticker_image(self, sticker):
		if not sticker:
			return
		sticker.image = ''
		extensions = ['webp', 'png']
		for extension in extensions:
			if not os.path.exists(
					os.path.join(
						self.config['sticker_images_path'],
						sticker.id + '.' + extension,
					)
				):
				return
		sticker.image = self.config['sticker_image_file_uri'].format(sticker.id)
		# serve files over same protocol as pages
		sticker.image = sticker.image.replace('https:', '').replace('http:', '')

	def populate_sticker_properties(self, sticker):
		if not sticker:
			return
		self.populate_sticker_image(sticker)
		sticker.group_names = self.accounts.group_names_from_bits(
			sticker.group_bits
		)
	def grant_sticker(self, sticker_id, user_id, receive_time=None, granting_user_id=''):
		collected_sticker = super().grant_sticker(
			sticker_id,
			user_id,
			receive_time=receive_time,
		)
		self.populate_sticker_properties(collected_sticker.sticker)
		self.access_log.create_log(
			scope='grant_sticker',
			subject_id=granting_user_id,
			object_id=collected_sticker.id,
		)
		return collected_sticker

	def revoke_sticker(self, collected_sticker_id, user_id, revoking_user_id):
		super().revoke_sticker(collected_sticker_id)
		self.access_log.create_log(
			scope='revoke_sticker',
			subject_id=revoking_user_id,
			object_id=collected_sticker_id,
		)

	def stickers_by_category(self, stickers):
		ordered = {}
		for category in self.config['categories']:
			ordered[category] = []
		for sticker in stickers.values():
			if sticker.category in ordered:
				ordered[sticker.category].append(
					sticker
				)
		for stickers in ordered.values():
			stickers.sort(key=lambda sticker: sticker.category_order)
		return ordered

	def collected_stickers_by_category(self, collected_stickers):
		ordered = {}
		for category in self.config['categories']:
			ordered[category] = []
		for collected_sticker in collected_stickers.values():
			if collected_sticker.sticker.category in ordered:
				ordered[collected_sticker.sticker.category].append(
					collected_sticker
				)
		for stickers in ordered.values():
			stickers.sort(
				key=lambda collected_sticker: collected_sticker.sticker.category_order
			)
		return ordered

	def place_sticker(self, **kwargs):
		placement = super().place_sticker(**kwargs)
		self.access_log.create_log(
			scope='place_sticker',
			subject_id=placement.user_id,
			object_id=placement.id,
		)
		return placement

	def unplace_sticker(self, placement_id, user_id=''):
		super().unplace_sticker(placement_id)
		self.access_log.create_log(
			scope='unplace_sticker',
			subject_id=user_id,
			object_id=placement_id,
		)

	def unplace_by_user(self, user_id, subject_id=''):
		super().unplace_by_user(user_id)
		self.access_log.create_log(
			scope='unplace_stickers_by_user',
			subject_id=subject_id,
			object_id=user_id,
		)

	def generate_sticker_placements_file(self, subject_id):
		sticker_placements = self.search_sticker_placements(
			filter={
				'subject_ids': subject_id,
			},
			sort='placement_time',
			order='asc',
		)
		sticker_ids = []
		placements_list = []
		for sticker_placement in sticker_placements.values():
			sticker_ids.append(sticker_placement.sticker_id)
			placements_list.append({
				'id': sticker_placement.id,
				'sticker_id': sticker_placement.sticker_id,
				'placement_time': sticker_placement.placement_time,
				'user_id': sticker_placement.user_id,
				'position_x': sticker_placement.position_x,
				'position_y': sticker_placement.position_y,
				#'rotation': sticker_placement.rotation,
				#'scale': sticker_placement.scale,
			})
		stickers = self.search_stickers(filter={'ids': sticker_ids})
		rendered_stickers = {}
		for sticker in stickers.values():
			rendered_stickers[sticker.id] = render_template(
				'sticker.html',
				sticker=sticker,
			).replace(
				'\r', '',
			).replace(
				'\n', '',
			).replace(
				'\t', '',
			)
		f = open(
			os.path.join(
				self.config['sticker_placements_path'],
				subject_id + '.json',
			),
			'w',
		)
		f.write(
			json.dumps(
				{
					'placements': placements_list,
					'stickers': rendered_stickers,
				}
			)
		)
		f.close()

	def get_potential_stickers(self, group_bits):
		without_group_bits = 0
		for group_bit in self.accounts.group_names_to_bits.values():
			if not self.accounts.contains_all_bits(group_bits, group_bit):
				without_group_bits += int.from_bytes(group_bit, 'big')
		filter = {}
		if 0 < without_group_bits:
			filter['without_group_bits'] = without_group_bits
		potential_stickers = self.search_stickers(filter=filter)
		return potential_stickers


