from __future__ import annotations

import base64
import io
import logging
import os
import platform
import re
from typing import TYPE_CHECKING

from browser_use.agent.views import AgentHistoryList
from browser_use.browser.views import PLACEHOLDER_4PX_SCREENSHOT
from browser_use.config import CONFIG
from browser_use.utils import is_new_tab_page

if TYPE_CHECKING:
	from PIL import Image, ImageFont

logger = logging.getLogger(__name__)

# Regex to strip emoji characters
_EMOJI_RE = re.compile(
	'['
	'\U0001F300-\U0001FAFF'
	'\U00002702-\U000027B0'
	'\U0000FE00-\U0000FE0F'
	'\U0000200D'
	'\U000020E3'
	'\U0000E000-\U0000F8FF'
	']+',
	flags=re.UNICODE,
)


def _resolve_font_name(font_name: str) -> str:
	"""Resolve font name to full path using fontconfig (fc-match)."""
	import shutil
	import subprocess

	if not shutil.which('fc-match'):
		return font_name
	try:
		result = subprocess.run(
			['fc-match', font_name, '--format=%{file}'],
			capture_output=True, text=True, timeout=5,
		)
		path = result.stdout.strip()
		if path and os.path.exists(path):
			return path
	except (subprocess.SubprocessError, OSError) as exc:
		logger.debug('fc-match failed for "%s": %s', font_name, exc)
	return font_name


def _strip_emoji(text: str) -> str:
	"""Remove emoji characters to avoid rendering as boxes."""
	return _EMOJI_RE.sub('', text).strip()


def decode_unicode_escapes_to_utf8(text: str) -> str:
	"""Handle decoding any unicode escape sequences embedded in a string (needed to render non-ASCII languages like chinese or arabic in the GIF overlay text)"""

	if r'\u' not in text:
		# doesn't have any escape sequences that need to be decoded
		return text

	try:
		# Try to decode Unicode escape sequences
		return text.encode('latin1').decode('unicode_escape')
	except (UnicodeEncodeError, UnicodeDecodeError):
		return text


def create_history_gif(
	task: str,
	history: AgentHistoryList,
	#
	output_path: str = 'agent_history.gif',
	duration: int = 3000,
	show_goals: bool = True,
	show_task: bool = True,
	show_logo: bool = False,
	font_size: int = 40,
	title_font_size: int = 56,
	margin: int = 40,
	line_spacing: float = 1.5,
) -> None:
	"""Create a GIF from the agent's history with overlaid task and goal text."""
	if not history.history:
		logger.warning('No history to create GIF from')
		return

	from PIL import Image, ImageFont

	images = []

	# Get all screenshots from history (including None placeholders)
	screenshots = history.screenshots(return_none_if_not_screenshot=True)

	if not screenshots:
		logger.warning('No screenshots found in history')
		return

	# Find the first non-placeholder screenshot
	first_real_screenshot = None
	for screenshot in screenshots:
		if screenshot and screenshot != PLACEHOLDER_4PX_SCREENSHOT:
			first_real_screenshot = screenshot
			break

	if not first_real_screenshot:
		logger.warning('No valid screenshots found (all are placeholders or from new tab pages)')
		return

	# Collect action_history as fallback for flash_mode (where next_goal is empty)
	action_history = history.extracted_content() or []

	# Try to load nicer fonts
	try:
		font_options = [
			'PingFang',
			'STHeiti Medium',
			'Microsoft YaHei',
			'SimHei',
			'SimSun',
			'Noto Sans CJK SC',
			'WenQuanYi Micro Hei',
			'Helvetica',
			'Arial',
			'DejaVuSans',
			'Verdana',
		]
		font_loaded = False

		for font_name in font_options:
			try:
				if platform.system() == 'Windows':
					font_name = os.path.join(CONFIG.WIN_FONT_DIR, font_name + '.ttf')
				else:
					font_name = _resolve_font_name(font_name)
				regular_font = ImageFont.truetype(font_name, font_size)
				title_font = ImageFont.truetype(font_name, title_font_size)
				font_loaded = True
				break
			except OSError:
				continue

		if not font_loaded:
			raise OSError('No preferred fonts found')

	except OSError:
		regular_font = ImageFont.load_default()
		title_font = ImageFont.load_default()

	# Load logo if requested
	logo = None
	if show_logo:
		try:
			logo = Image.open('./static/browser-use.png')
			# Resize logo to be small (e.g., 40px height)
			logo_height = 150
			aspect_ratio = logo.width / logo.height
			logo_width = int(logo_height * aspect_ratio)
			logo = logo.resize((logo_width, logo_height), Image.Resampling.LANCZOS)
		except Exception as e:
			logger.warning(f'Could not load logo: {e}')

	# Create task frame if requested
	if show_task and task:
		# Find the first non-placeholder screenshot for the task frame
		first_real_screenshot = None
		for item in history.history:
			screenshot_b64 = item.state.get_screenshot()
			if screenshot_b64 and screenshot_b64 != PLACEHOLDER_4PX_SCREENSHOT:
				first_real_screenshot = screenshot_b64
				break

		if first_real_screenshot:
			task_frame = _create_task_frame(
				task,
				first_real_screenshot,
				title_font,  # type: ignore
				regular_font,  # type: ignore
				logo,
				line_spacing,
			)
			images.append(task_frame)
		else:
			logger.warning('No real screenshots found for task frame, skipping task frame')

	# Process each history item with its corresponding screenshot
	for i, (item, screenshot) in enumerate(zip(history.history, screenshots), 1):
		if not screenshot:
			continue

		# Skip placeholder screenshots from about:blank pages
		if screenshot == PLACEHOLDER_4PX_SCREENSHOT:
			logger.debug(f'Skipping placeholder screenshot from about:blank page at step {i}')
			continue

		# Skip screenshots from new tab pages
		if is_new_tab_page(item.state.url):
			logger.debug(f'Skipping screenshot from new tab page ({item.state.url}) at step {i}')
			continue

		# Convert base64 screenshot to PIL Image
		img_data = base64.b64decode(screenshot)
		image = Image.open(io.BytesIO(img_data))

		if show_goals:
			# Determine overlay text: prefer next_goal, fallback to action_history
			goal_text = ''
			if item.model_output and item.model_output.current_state.next_goal:
				goal_text = item.model_output.current_state.next_goal
			elif i - 1 < len(action_history):
				goal_text = _strip_emoji(action_history[i - 1])

			if goal_text:
				image = _add_overlay_to_image(
					image=image,
					step_number=i,
					goal_text=goal_text,
					regular_font=regular_font,  # type: ignore
					title_font=title_font,  # type: ignore
					margin=margin,
					logo=logo,
				)

		images.append(image)

	if images:
		# Save the GIF
		images[0].save(
			output_path,
			save_all=True,
			append_images=images[1:],
			duration=duration,
			loop=0,
			optimize=False,
		)
		logger.info(f'Created GIF at {output_path}')
	else:
		logger.warning('No images found in history to create GIF')


def _create_task_frame(
	task: str,
	first_screenshot: str,
	title_font: ImageFont.FreeTypeFont,
	regular_font: ImageFont.FreeTypeFont,
	logo: Image.Image | None = None,
	line_spacing: float = 1.5,
) -> Image.Image:
	"""Create initial frame showing the task."""
	from PIL import Image, ImageDraw, ImageFont

	img_data = base64.b64decode(first_screenshot)
	template = Image.open(io.BytesIO(img_data))
	image = Image.new('RGB', template.size, (0, 0, 0))
	draw = ImageDraw.Draw(image)

	# Calculate vertical center of image
	center_y = image.height // 2

	# Draw task text with dynamic font size based on task length
	margin = 140
	max_width = image.width - (2 * margin)

	# Dynamic font size: cap at 32 to prevent overflow on long task text
	base_font_size = min(regular_font.size, 32)
	min_font_size = max(base_font_size - 10, 16)

	text_length = len(task)
	if text_length > 200:
		font_size = max(base_font_size - int(10 * (text_length / 200)), min_font_size)
	else:
		font_size = base_font_size

	# Try to create a font with calculated size
	try:
		larger_font = ImageFont.truetype(regular_font.path, font_size)  # type: ignore
	except (OSError, AttributeError):
		larger_font = regular_font

	# Generate wrapped text with the calculated font size
	wrapped_text = _wrap_text(task, larger_font, max_width)

	# Calculate line height with spacing
	line_height = larger_font.size * line_spacing

	# Split text into lines and draw with custom spacing
	lines = wrapped_text.split('\n')
	total_height = line_height * len(lines)

	# Start position for first line (slightly above center)
	text_y = center_y - (total_height / 2) - 50

	for line in lines:
		# Get line width for centering
		line_bbox = draw.textbbox((0, 0), line, font=larger_font)
		text_x = (image.width - (line_bbox[2] - line_bbox[0])) // 2

		draw.text(
			(text_x, text_y),
			line,
			font=larger_font,
			fill=(255, 255, 255),
		)
		text_y += line_height

	# Add logo if provided (top right corner)
	if logo:
		logo_margin = 20
		logo_x = image.width - logo.width - logo_margin
		image.paste(logo, (logo_x, logo_margin), logo if logo.mode == 'RGBA' else None)

	return image


def _add_overlay_to_image(
	image: Image.Image,
	step_number: int,
	goal_text: str,
	regular_font: ImageFont.FreeTypeFont,
	title_font: ImageFont.FreeTypeFont,
	margin: int,
	logo: Image.Image | None = None,
	display_step: bool = True,
	text_color: tuple[int, int, int, int] = (255, 255, 255, 255),
	text_box_color: tuple[int, int, int, int] = (0, 0, 0, 255),
) -> Image.Image:
	"""Add step number and goal overlay to an image."""

	from PIL import Image, ImageDraw

	goal_text = decode_unicode_escapes_to_utf8(goal_text)
	image = image.convert('RGBA')
	txt_layer = Image.new('RGBA', image.size, (0, 0, 0, 0))
	draw = ImageDraw.Draw(txt_layer)
	padding = 20
	y_step = image.height - margin - 40
	if display_step:
		# Add step number (bottom left)
		step_text = str(step_number)
		step_bbox = draw.textbbox((0, 0), step_text, font=title_font)
		step_width = step_bbox[2] - step_bbox[0]
		step_height = step_bbox[3] - step_bbox[1]

		# Position step number in bottom left
		x_step = margin + 10
		y_step = image.height - margin - step_height - 40
		step_bg_bbox = (
			x_step - padding,
			y_step - padding,
			x_step + step_width + padding,
			y_step + step_height + padding,
		)
		draw.rounded_rectangle(
			step_bg_bbox,
			radius=15,
			fill=text_box_color,
		)

		# Draw step number
		draw.text(
			(x_step, y_step),
			step_text,
			font=title_font,
			fill=text_color,
		)

	# Draw goal text (centered, bottom) — use regular_font for readable size
	max_width = image.width - (4 * margin)
	wrapped_goal = _wrap_text(goal_text, regular_font, max_width)
	goal_bbox = draw.multiline_textbbox((0, 0), wrapped_goal, font=regular_font)
	goal_width = goal_bbox[2] - goal_bbox[0]
	goal_height = goal_bbox[3] - goal_bbox[1]

	# Center goal text horizontally, place above step number
	x_goal = (image.width - goal_width) // 2
	y_goal = y_step - goal_height - padding * 4

	# Draw rounded rectangle background for goal
	padding_goal = 25
	goal_bg_bbox = (
		x_goal - padding_goal,
		y_goal - padding_goal,
		x_goal + goal_width + padding_goal,
		y_goal + goal_height + padding_goal,
	)
	draw.rounded_rectangle(
		goal_bg_bbox,
		radius=15,
		fill=text_box_color,
	)

	# Draw goal text
	draw.multiline_text(
		(x_goal, y_goal),
		wrapped_goal,
		font=regular_font,
		fill=text_color,
		align='center',
	)

	# Add logo if provided (top right corner)
	if logo:
		logo_layer = Image.new('RGBA', image.size, (0, 0, 0, 0))
		logo_margin = 20
		logo_x = image.width - logo.width - logo_margin
		logo_layer.paste(logo, (logo_x, logo_margin), logo if logo.mode == 'RGBA' else None)
		txt_layer = Image.alpha_composite(logo_layer, txt_layer)

	# Composite and convert
	result = Image.alpha_composite(image, txt_layer)
	return result.convert('RGB')


def _wrap_text(text: str, font: ImageFont.FreeTypeFont, max_width: int) -> str:
	"""
	Wrap text to fit within a given width.

	Args:
	    text: Text to wrap
	    font: Font to use for text
	    max_width: Maximum width in pixels

	Returns:
	    Wrapped text with newlines
	"""
	text = decode_unicode_escapes_to_utf8(text)
	words = text.split()
	lines = []
	current_line = []

	for word in words:
		current_line.append(word)
		line = ' '.join(current_line)
		bbox = font.getbbox(line)
		if bbox[2] > max_width:
			if len(current_line) == 1:
				lines.append(current_line.pop())
			else:
				current_line.pop()
				lines.append(' '.join(current_line))
				current_line = [word]

	if current_line:
		lines.append(' '.join(current_line))

	return '\n'.join(lines)
