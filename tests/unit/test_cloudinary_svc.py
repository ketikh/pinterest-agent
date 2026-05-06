"""Unit tests for cloudinary_svc (all Cloudinary SDK calls mocked)."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from ai_bag_agent.ai_content.services.cloudinary_svc import (
    _error_result,
    _make_public_id,
    upload_generated_image,
    upload_image,
)

FAKE_ENV = {
    "CLOUDINARY_CLOUD_NAME": "test-cloud",
    "CLOUDINARY_API_KEY": "test-key",
    "CLOUDINARY_API_SECRET": "test-secret",
}

FAKE_UPLOAD_RESULT = {
    "secure_url": "https://res.cloudinary.com/test-cloud/image/upload/v123/tissu-ai/tenants/default/generated/test.png",
    "public_id": "tissu-ai/tenants/default/generated/test",
    "format": "png",
    "bytes": 1024 * 500,
    "width": 2048,
    "height": 2048,
}


# ---------------------------------------------------------------------------
# _make_public_id
# ---------------------------------------------------------------------------

class TestMakePublicId:
    def test_includes_tenant_and_category(self):
        pid = _make_public_id("default", "generated", None)
        assert "default" in pid
        assert "generated" in pid

    def test_prefix_overrides_default(self):
        pid = _make_public_id("default", "generated", "my-custom-prefix")
        assert pid == "my-custom-prefix"

    def test_unique_without_prefix(self):
        pid1 = _make_public_id("default", "generated", None)
        pid2 = _make_public_id("default", "generated", None)
        assert pid1 != pid2


# ---------------------------------------------------------------------------
# upload_image
# ---------------------------------------------------------------------------

class TestUploadImage:
    def test_missing_credentials_returns_failure(self, tmp_path):
        img = tmp_path / "test.png"
        img.write_bytes(b"fake")
        with patch.dict("os.environ", {}, clear=True):
            result = upload_image(str(img))
        assert result["success"] is False
        assert result["error"] is not None

    def test_file_not_found_returns_failure(self):
        with patch.dict("os.environ", FAKE_ENV):
            result = upload_image("/nonexistent/path/image.png")
        assert result["success"] is False
        assert "not found" in result["error"].lower()

    @patch.dict("os.environ", FAKE_ENV)
    @patch("ai_bag_agent.ai_content.services.cloudinary_svc.cloudinary.uploader.upload")
    def test_successful_upload_returns_all_keys(self, mock_upload, tmp_path):
        img = tmp_path / "test.png"
        img.write_bytes(b"fake image bytes")
        mock_upload.return_value = FAKE_UPLOAD_RESULT

        result = upload_image(str(img), tenant_id="default", category="generated")

        assert result["success"] is True
        assert result["public_url"] == FAKE_UPLOAD_RESULT["secure_url"]
        assert result["public_id"] == FAKE_UPLOAD_RESULT["public_id"]
        assert result["size_bytes"] == FAKE_UPLOAD_RESULT["bytes"]
        assert result["width"] == 2048
        assert result["height"] == 2048
        assert result["error"] is None

    @patch.dict("os.environ", FAKE_ENV)
    @patch("ai_bag_agent.ai_content.services.cloudinary_svc.cloudinary.uploader.upload")
    def test_correct_folder_structure(self, mock_upload, tmp_path):
        img = tmp_path / "test.png"
        img.write_bytes(b"fake")
        mock_upload.return_value = FAKE_UPLOAD_RESULT

        upload_image(str(img), tenant_id="acme", category="bags")

        _, kwargs = mock_upload.call_args
        assert kwargs["folder"] == "tissu-ai/tenants/acme/bags"
        assert kwargs["overwrite"] is False
        assert kwargs["unique_filename"] is False

    @patch.dict("os.environ", FAKE_ENV)
    @patch("ai_bag_agent.ai_content.services.cloudinary_svc.time.sleep")
    @patch("ai_bag_agent.ai_content.services.cloudinary_svc.cloudinary.uploader.upload")
    def test_retries_on_server_error(self, mock_upload, mock_sleep, tmp_path):
        import cloudinary.exceptions
        img = tmp_path / "test.png"
        img.write_bytes(b"fake")

        server_error = cloudinary.exceptions.Error("server error")
        server_error.http_code = 503
        mock_upload.side_effect = [server_error, FAKE_UPLOAD_RESULT]

        result = upload_image(str(img))
        assert result["success"] is True
        assert mock_upload.call_count == 2

    @patch.dict("os.environ", FAKE_ENV)
    @patch("ai_bag_agent.ai_content.services.cloudinary_svc.time.sleep")
    @patch("ai_bag_agent.ai_content.services.cloudinary_svc.cloudinary.uploader.upload")
    def test_fails_after_max_retries(self, mock_upload, mock_sleep, tmp_path):
        import cloudinary.exceptions
        img = tmp_path / "test.png"
        img.write_bytes(b"fake")

        server_error = cloudinary.exceptions.Error("repeated failure")
        server_error.http_code = 503
        mock_upload.side_effect = server_error

        result = upload_image(str(img))
        assert result["success"] is False
        assert mock_upload.call_count == 3


# ---------------------------------------------------------------------------
# upload_generated_image
# ---------------------------------------------------------------------------

class TestUploadGeneratedImage:
    def test_failed_generation_returns_error(self):
        result = upload_generated_image({"success": False, "error": "gen failed"})
        assert result["success"] is False

    def test_missing_local_path_returns_error(self):
        result = upload_generated_image({"success": True, "local_path": None})
        assert result["success"] is False

    @patch.dict("os.environ", FAKE_ENV)
    @patch("ai_bag_agent.ai_content.services.cloudinary_svc.cloudinary.uploader.upload")
    def test_delegates_to_upload_image(self, mock_upload, tmp_path):
        img = tmp_path / "generated.png"
        img.write_bytes(b"fake")
        mock_upload.return_value = FAKE_UPLOAD_RESULT

        gen_result = {"success": True, "local_path": str(img)}
        result = upload_generated_image(gen_result, tenant_id="default")

        assert result["success"] is True
        mock_upload.assert_called_once()
