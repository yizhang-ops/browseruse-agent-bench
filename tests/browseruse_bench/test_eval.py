"""Tests for browseruse_bench.utils.eval_utils module."""

import base64
import io

import pytest
from PIL import Image

from browseruse_bench.utils import (
    calculate_success,
    encode_image,
    extract_score_from_response,
)


class TestEncodeImage:
    """Tests for encode_image function."""

    def test_encode_image_basic(self):
        """Test basic image encoding to base64."""
        # Create a simple test image
        img = Image.new("RGB", (100, 100), color="red")
        
        result = encode_image(img)
        
        assert isinstance(result, str)
        # Verify it's valid base64
        decoded = base64.b64decode(result)
        assert len(decoded) > 0

    def test_encode_image_with_scale_factor(self):
        """Test image encoding with scale factor."""
        img = Image.new("RGB", (200, 200), color="blue")
        
        result_full = encode_image(img, scale_factor=1.0)
        result_half = encode_image(img, scale_factor=0.5)
        
        # Scaled image should produce smaller base64
        assert len(result_half) < len(result_full)

    def test_encode_image_rgba_mode(self):
        """Test encoding RGBA image (should convert to RGB)."""
        img = Image.new("RGBA", (50, 50), color=(255, 0, 0, 128))
        
        result = encode_image(img)
        
        assert isinstance(result, str)
        assert len(result) > 0


class TestExtractScoreFromResponse:
    """Tests for extract_score_from_response function."""

    def test_extract_score_simple(self):
        """Test extracting score from simple response."""
        response = "Score: 85"
        assert extract_score_from_response(response) == 85

    def test_extract_score_with_text(self):
        """Test extracting score embedded in text."""
        response = "The agent performed well. Final Score: 70/100"
        assert extract_score_from_response(response) == 70

    def test_extract_score_multiple_numbers(self):
        """Test extracts last relevant score number."""
        response = "Step 1 complete. Step 2 complete. Score: 90"
        score = extract_score_from_response(response)
        assert score == 90

    def test_extract_score_no_score_returns_zero(self):
        """Test returns 0 when no score found."""
        response = "Unable to evaluate"
        assert extract_score_from_response(response) == 0


class TestCalculateSuccess:
    """Tests for calculate_success function."""

    def test_success_above_threshold(self):
        """Test score above threshold returns True."""
        assert calculate_success(80, threshold=60) is True

    def test_success_at_threshold(self):
        """Test score at threshold returns True."""
        assert calculate_success(60, threshold=60) is True

    def test_failure_below_threshold(self):
        """Test score below threshold returns False."""
        assert calculate_success(50, threshold=60) is False

    def test_success_default_threshold(self):
        """Test with default threshold (60)."""
        assert calculate_success(60) is True
        assert calculate_success(59) is False

    def test_success_custom_threshold(self):
        """Test with custom threshold."""
        assert calculate_success(70, threshold=70) is True
        assert calculate_success(69, threshold=70) is False
