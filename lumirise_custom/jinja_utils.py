# Jinja helpers available inside Print Formats (registered in hooks.py -> jinja).

from io import BytesIO

from markupsafe import Markup


def barcode_svg(value, height=12.0, module_width=0.28, font_size=8):
	"""Render a Code-128 barcode as inline SVG (server-side, python-barcode —
	no JS, so it prints identically in PDF/wkhtmltopdf and on paper labels).
	Usage in a Print Format:  {{ barcode_svg(doc.item_code) }}"""
	if not value:
		return ""
	import barcode
	from barcode.writer import SVGWriter

	code = barcode.get("code128", str(value), writer=SVGWriter())
	buf = BytesIO()
	code.write(buf, options={
		"module_height": height,
		"module_width": module_width,
		"font_size": font_size,
		"text_distance": 3.5,
		"quiet_zone": 2,
	})
	svg = buf.getvalue().decode("utf-8")
	# strip the XML prolog/doctype so it embeds inline in HTML
	svg = svg[svg.find("<svg"):]
	return Markup(svg)
