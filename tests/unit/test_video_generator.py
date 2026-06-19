"""Unit tests for video_generator (Seedance via kie.ai) — all calls mocked."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from ai_bag_agent.ai_content.services.video_generator import generate_video

MOD = "ai_bag_agent.ai_content.services.video_generator"
IMG = "https://res.cloudinary.com/x/photo.jpg"


def _submit_resp(task_id="task_1"):
    r = MagicMock()
    r.status_code = 200
    r.json.return_value = {"code": 200, "msg": "ok", "data": {"taskId": task_id}}
    return r


class TestGenerateVideo:
    def test_missing_api_key_fails(self):
        with patch.dict("os.environ", {}, clear=True):
            import os
            os.environ.pop("KIE_AI_API_KEY", None)
            os.environ.pop("KIEAI_API_KEY", None)
            out = generate_video(IMG, "motion prompt")
        assert out["success"] is False
        assert "KIE_AI_API_KEY" in out["error"]

    @patch.dict("os.environ", {"KIE_AI_API_KEY": "k"})
    def test_local_path_fails(self):
        out = generate_video("/tmp/local.jpg", "motion prompt")
        assert out["success"] is False
        assert "public URL" in out["error"]

    @patch.dict("os.environ", {"KIE_AI_API_KEY": "k"})
    @patch(f"{MOD}._poll_for_result")
    @patch(f"{MOD}.requests.post")
    def test_full_success(self, mock_post, mock_poll):
        mock_post.return_value = _submit_resp("task_1")
        mock_poll.return_value = ("https://v/out.mp4", None)
        out = generate_video(IMG, "motion prompt")
        assert out["success"] is True
        assert out["video_url"] == "https://v/out.mp4"
        assert out["error"] is None

    @patch.dict("os.environ", {"KIE_AI_API_KEY": "k"})
    @patch(f"{MOD}._poll_for_result")
    @patch(f"{MOD}.requests.post")
    def test_payload_has_seedance_fields(self, mock_post, mock_poll):
        mock_post.return_value = _submit_resp()
        mock_poll.return_value = ("https://v/out.mp4", None)
        generate_video(IMG, "motion prompt")

        _, kwargs = mock_post.call_args
        body = kwargs["json"]
        assert body["model"]  # non-empty model id
        inp = body["input"]
        assert inp["prompt"] == "motion prompt"
        assert inp["input_urls"] == [IMG]  # Seedance source-image field
        assert inp["aspect_ratio"] == "9:16"
        assert inp["resolution"] == "720p"
        assert inp["duration"] == 5
        assert inp["generate_audio"] is False

    @patch.dict("os.environ", {"KIE_AI_API_KEY": "k",
                               "KIE_VIDEO_ASPECT_RATIO": "1:1",
                               "KIE_VIDEO_GENERATE_AUDIO": "true"})
    @patch(f"{MOD}._poll_for_result")
    @patch(f"{MOD}.requests.post")
    def test_env_overrides_apply(self, mock_post, mock_poll):
        mock_post.return_value = _submit_resp()
        mock_poll.return_value = ("https://v/out.mp4", None)
        generate_video(IMG, "p")
        inp = mock_post.call_args.kwargs["json"]["input"]
        assert inp["aspect_ratio"] == "1:1"
        assert inp["generate_audio"] is True

    @patch.dict("os.environ", {"KIE_AI_API_KEY": "k"})
    @patch(f"{MOD}._poll_for_result")
    @patch(f"{MOD}.requests.post")
    def test_poll_error_returns_failure(self, mock_post, mock_poll):
        mock_post.return_value = _submit_resp()
        mock_poll.return_value = (None, "timeout")
        out = generate_video(IMG, "p")
        assert out["success"] is False
        assert out["error"] == "timeout"
