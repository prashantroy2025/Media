"""Perceptual Image Hashing & Near-Duplicate Detection."""

from pathlib import Path
from PIL import Image


def compute_dhash(image_or_path: Image.Image | str | Path, hash_size: int = 8) -> str:
    """Computes a difference hash (dhash) for an image or image path."""
    if isinstance(image_or_path, (str, Path)):
        img = Image.open(image_or_path)
    else:
        img = image_or_path

    # Convert to grayscale and resize to (hash_size + 1, hash_size)
    img_gray = img.convert("L").resize((hash_size + 1, hash_size), Image.Resampling.LANCZOS)
    if hasattr(img_gray, "get_flattened_data"):
        pixels = list(img_gray.get_flattened_data())
    else:
        pixels = list(img_gray.getdata())

    # Compare adjacent pixels
    difference = []
    width = hash_size + 1
    for row in range(hash_size):
        for col in range(hash_size):
            pixel_left = pixels[row * width + col]
            pixel_right = pixels[row * width + col + 1]
            difference.append(pixel_left > pixel_right)

    # Convert binary array to hex string
    decimal_val = 0
    hex_str = []
    for index, val in enumerate(difference):
        if val:
            decimal_val += 2 ** (index % 4)
        if index % 4 == 3:
            hex_str.append(hex(decimal_val)[2:])
            decimal_val = 0

    return "".join(hex_str)


def hamming_distance(hash1: str, hash2: str) -> int:
    """Calculates the Hamming distance between two hex hash strings."""
    if not hash1 or not hash2 or len(hash1) != len(hash2):
        return 999
    try:
        val1 = int(hash1, 16)
        val2 = int(hash2, 16)
        return bin(val1 ^ val2).count("1")
    except ValueError:
        return 999


def is_near_duplicate(hash1: str, hash2: str, threshold: int = 6) -> bool:
    """Returns True if the perceptual distance between two images is below threshold."""
    return hamming_distance(hash1, hash2) <= threshold
