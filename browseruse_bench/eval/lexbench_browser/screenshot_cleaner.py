"""Screenshot Cleaner Tool: Detect blank images and remove duplicates"""
import hashlib
import logging
from pathlib import Path

import numpy as np
from PIL import Image

logger = logging.getLogger(__name__)


def is_blank_image(image_path: Path, threshold: float = 0.99) -> bool:
    """Detect if image is blank (all white, all black, or almost monochrome)

    Args:
        image_path: Image path
        threshold: Ratio of monochrome pixels threshold, above which considered blank

    Returns:
        True if blank, False otherwise
    """
    try:
        img = Image.open(image_path)
        # Convert to RGB (if RGBA, convert to RGB)
        if img.mode == 'RGBA':
            # Create white background
            rgb_img = Image.new('RGB', img.size, (255, 255, 255))
            rgb_img.paste(img, mask=img.split()[3])  # Use alpha channel as mask
            img = rgb_img
        elif img.mode != 'RGB':
            img = img.convert('RGB')

        # Convert to numpy array
        img_array = np.array(img)

        # Calculate image statistics
        # Method 1: Check if empty
        if img_array.size == 0:
            return True

        # Calculate pixel value std dev
        std = np.std(img_array)
        if std < 5:  # Std dev very small, means almost monochrome
            return True

        # Method 2: Check monochrome pixel ratio
        # Calculate diff from mean for each pixel
        mean_color = np.mean(img_array, axis=(0, 1))
        diff = np.abs(img_array - mean_color)
        # If diff is small for all 3 channels, considered monochrome
        single_color_pixels = np.sum(np.all(diff < 10, axis=2))
        single_color_ratio = single_color_pixels / img_array.shape[0] / img_array.shape[1]

        if single_color_ratio > threshold:
            return True

        # Method 3: Check if all white (all pixels near 255)
        white_pixels = np.sum(np.all(img_array > 250, axis=2))
        white_ratio = white_pixels / img_array.shape[0] / img_array.shape[1]
        if white_ratio > threshold:
            return True

        # Method 4: Check if all black (all pixels near 0)
        black_pixels = np.sum(np.all(img_array < 5, axis=2))
        black_ratio = black_pixels / img_array.shape[0] / img_array.shape[1]
        return black_ratio > threshold

    except (OSError, Exception) as e:
        # If failed to read image, consider as abnormal image
        logger.warning(f"Warning: Failed to check image {image_path}: {e}")
        return True


def calculate_image_hash(image_path: Path) -> str:
    """Calculate image hash for deduplication

    Args:
        image_path: Image path

    Returns:
        Image MD5 hash
    """
    try:
        img = Image.open(image_path)
        # Convert to RGB mode
        if img.mode != 'RGB':
            img = img.convert('RGB')

        # Calculate image hash
        img_bytes = img.tobytes()
        return hashlib.md5(img_bytes).hexdigest()
    except (OSError, Exception) as e:
        logger.warning(f"Warning: Failed to hash image {image_path}: {e}")
        return ""


def clean_screenshots(screenshots: list[Path], remove_blank: bool = True, remove_duplicates: bool = True) -> tuple[list[Path], dict]:
    """Clean screenshot list: remove blank and duplicate images

    Args:
        screenshots: Screenshot path list (sorted)
        remove_blank: Whether to remove blank images
        remove_duplicates: Whether to remove duplicates

    Returns:
        (cleaned list, stats dict)
    """
    if not screenshots:
        return [], {"original_count": 0, "blank_removed": 0, "duplicate_removed": 0, "final_count": 0}

    stats = {
        "original_count": len(screenshots),
        "blank_removed": 0,
        "duplicate_removed": 0,
        "final_count": 0
    }

    cleaned = []
    seen_hashes = set()

    for screenshot in screenshots:
        # Check if blank
        if remove_blank and is_blank_image(screenshot):
            stats["blank_removed"] += 1
            continue

        # Check if duplicate
        if remove_duplicates:
            img_hash = calculate_image_hash(screenshot)
            if img_hash:  # Only check deduplication if hash calculated successfully
                if img_hash in seen_hashes:
                    stats["duplicate_removed"] += 1
                    continue
                seen_hashes.add(img_hash)
            # If failed to hash, keep the image (might be temp read error)

        cleaned.append(screenshot)

    stats["final_count"] = len(cleaned)

    return cleaned, stats
