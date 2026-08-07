"""Small Jinja-safe helpers for printer-independent Code 128 labels."""

import base64
from io import BytesIO


def code128_data_uri(value):
	from barcode import Code128
	from barcode.writer import SVGWriter

	stream = BytesIO()
	Code128(str(value or ""), writer=SVGWriter()).write(
		stream,
		options={"module_width": 0.28, "module_height": 13, "quiet_zone": 2, "write_text": False},
	)
	return "data:image/svg+xml;base64," + base64.b64encode(stream.getvalue()).decode()
