#!/usr/bin/env python3
"""
Simple HEIC to PNG/JPG converter.
Usage: python convert.py /path/to/heic/files /path/to/output --format png
"""

import argparse
import sys
from pathlib import Path

from PIL import Image
import pillow_heif

# Register HEIF opener with Pillow
pillow_heif.register_heif_opener()


def convert_heic_to_image(input_folder: Path, output_folder: Path, fmt: str):
    """
    Convert all .heic files in `input_folder` to `fmt` images in `output_folder`.
    fmt must be 'png' or 'jpg'.
    """
    # Ensure output folder exists
    output_folder.mkdir(parents=True, exist_ok=True)

    # Find all HEIC files (case-insensitive)
    heic_files = list(input_folder.glob("*.heic")) + list(input_folder.glob("*.HEIC"))
    if not heic_files:
        print(f"No .heic files found in {input_folder}")
        return

    print(f"Found {len(heic_files)} HEIC file(s). Converting to {fmt.upper()}...")

    for heic_path in heic_files:
        try:
            image = Image.open(heic_path)
        except Exception as e:
            print(f"  ERROR opening {heic_path.name}: {e}")
            continue

        # Determine output path
        out_name = heic_path.stem + f".{fmt}"
        out_path = output_folder / out_name

        # Save with appropriate quality/compression
        if fmt == "jpg":
            image = image.convert("RGB")  # JPG doesn't support alpha
            image.save(out_path, "JPEG", quality=95)
        else:  # png
            image.save(out_path, "PNG")

        print(f"  ✓ {heic_path.name} -> {out_name}")

    print("Done.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Convert HEIC images to PNG or JPG."
    )
    parser.add_argument(
        "input", type=str, help="Folder containing .heic files"
    )
    parser.add_argument(
        "output", type=str, help="Folder where converted images will be saved"
    )
    parser.add_argument(
        "--format",
        choices=["png", "jpg"],
        default="png",
        help="Output image format (default: png)",
    )
    args = parser.parse_args()

    input_dir = Path(args.input)
    output_dir = Path(args.output)

    if not input_dir.is_dir():
        sys.exit(f"Input folder does not exist: {input_dir}")

    convert_heic_to_image(input_dir, output_dir, args.format)