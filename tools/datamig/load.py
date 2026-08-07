"""Load layer: write the S/4HANA load files and exception files."""

from __future__ import annotations

import csv
from pathlib import Path

LOAD_FILES = {
    "products": "s4_product.csv",
    "product_xref": "s4_product_xref.csv",
    "business_partners": "s4_business_partner.csv",
    "bp_xref": "s4_business_partner_xref.csv",
    "open_items": "s4_open_item.csv",
    "stock": "s4_stock_initial.csv",
}


def write_rows(path: str | Path, rows: list[dict[str, str]]) -> Path:
    """Write rows to CSV. An empty dataset still produces a file."""
    file_path = Path(path)
    file_path.parent.mkdir(parents=True, exist_ok=True)

    if not rows:
        file_path.write_text("", encoding="utf-8")
        return file_path

    fieldnames = list(rows[0].keys())
    with open(file_path, "w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)
    return file_path


def write_load_file(out_dir: str | Path, key: str, rows: list[dict[str, str]]) -> Path:
    return write_rows(Path(out_dir) / LOAD_FILES[key], rows)


def write_exceptions(out_dir: str | Path, object_name: str, issues) -> Path:
    rows = [issue.as_dict() for issue in issues]
    return write_rows(Path(out_dir) / f"exceptions_{object_name}.csv", rows)


def write_rejects(out_dir: str | Path, object_name: str, rows: list[dict[str, str]]) -> Path:
    return write_rows(Path(out_dir) / f"rejected_{object_name}.csv", rows)
