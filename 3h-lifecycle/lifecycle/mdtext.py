"""Safe text for Markdown tables.

Text from the CSV files ends up inside table cells. A "|" in a name or purpose would start a new
cell and break the table (and a reviewer could be misled about which column a value is in), so it
is escaped. Line breaks are already refused when the CSV is read; they are flattened here too.
"""


def cell(value: object) -> str:
    return str(value).replace("\\", "\\\\").replace("|", "\\|").replace("\r", " ").replace("\n", " ")
