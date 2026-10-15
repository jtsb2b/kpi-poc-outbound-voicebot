from functools import lru_cache
from typing import Literal

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    mongo_uri: SecretStr = SecretStr("mongodb://127.0.0.1:27017")
    mongo_db: str = "kpi_voicebot"

    operator_token: SecretStr = Field(min_length=12)
    api_host: str = "127.0.0.1"
    api_port: int = 8000
    cors_origins: list[str] = ["http://localhost:5173", "http://127.0.0.1:5173"]

    retention_days: int = Field(default=30, ge=1)
    live_calls_enabled: bool = False
    calling_start_hour: int = Field(default=8, ge=0, le=23)
    calling_end_hour: int = Field(default=20, ge=1, le=24)
    timezone: str = "Asia/Bangkok"
    allow_internal_extensions: bool = False

    sim_turn_delay_ms: int = Field(default=700, ge=0)
    lease_seconds: int = Field(default=30, ge=5)
    worker_poll_seconds: float = Field(default=0.5, gt=0)

    # Reply understanding: "rules" (deterministic only) or "llm" (self-hosted OpenThai 2.0 + rule safety layer)
    interpreter: Literal["rules", "llm"] = "rules"
    # With the LLM: "agent" = it leads the conversation from the approved knowledge (checklist and
    # rules kept by code); "scripted" = the engine's approved lines, reworded by the LLM.
    conversation_mode: Literal["agent", "scripted"] = "agent"
    llm_base_url: str | None = None
    llm_api_key: SecretStr | None = None
    llm_model: str | None = None
    llm_timeout_seconds: float = Field(default=8.0, gt=0)
    # Client-side budget so one demo never exceeds the gateway quota; 0 disables a limit.
    llm_requests_per_minute: int = Field(default=30, ge=0)
    llm_tokens_per_minute: int = Field(default=0, ge=0)
    # Longest a turn may queue for that budget before it is said with the approved wording instead.
    llm_max_queue_seconds: float = Field(default=0.3, ge=0)

    # Speech recognition, chosen explicitly (never a silent fallback): Soniox real-time while JaiASR
    # is in maintenance and fine-tuning (decided by the user's senior, 15 Oct 2026), or JaiASR.
    asr_provider: Literal["soniox", "jai"] = "soniox"
    soniox_api_key: SecretStr | None = None
    soniox_model: str = "stt-rt-v5"
    # How long after speech stops Soniox may wait before ending the utterance (500-3000 ms).
    soniox_max_endpoint_delay_ms: int = Field(default=800, ge=500, le=3000)
    # JaiASR-Flash-v1.0 (JTS), streaming over WebSocket
    jaiasr_api_key: SecretStr | None = None
    jaiasr_model: str = "session-tenant-ai-engineer-jaiasr-flash-v1"
    jaiasr_stream_url: str = "wss://api.jasgpu.com/v1/audio/transcriptions/stream"
    jaiasr_http_url: str = "https://api.jasgpu.com/v1/audio/transcriptions"
    asr_chunk_seconds: float = Field(default=0.5, ge=0.25, le=10)

    # Voice: JAI TTS (JTS) by default; Gemini Live only when chosen explicitly, never as a fallback
    tts_provider: Literal["jai", "gemini"] = "jai"
    jaitts_base_url: str = "https://jai-tts.bai-ap.jts.co.th:10206"
    jaitts_api_key: SecretStr | None = None
    jaitts_cfg: float = Field(default=2.0, ge=0)
    jaitts_temperature: float = Field(default=0.7, ge=0)

    # Optional Gemini Live voice on the user's Google key (≈0.5 s first audio)
    google_api_key: SecretStr | None = None
    tts_model: str = "gemini-3.8-live"
    tts_voice: str = "Sulafat"
    # Short and constant: a long or changing style prompt makes the delivery drift.
    tts_style: str = (
        "a warm, polite Thai woman who is an experienced call-centre agent; speaks at a brisk, everyday "
        "conversational speed like a real Bangkok call-centre agent, not slow and not over-enunciated; "
        "steady, even tone from start to finish"
    )
    tts_cache_dir: str = ".local/tts_cache"

    # Phone calls: LiveKit Cloud + the project's outbound SIP trunk (owned by the user, never changed here)
    livekit_url: str | None = None
    livekit_api_key: SecretStr | None = None
    livekit_api_secret: SecretStr | None = None
    livekit_sip_outbound_trunk_id: str | None = None
    livekit_agent_name: str = "kpi-voicebot-outbound"
    livekit_room_prefix: str = "kpi-"
    sip_caller_number: str | None = None  # the extension the call is placed from
    sip_destination_format: Literal["national"] = "national"
    public_caller_id: str | None = None  # what the customer's phone shows (set on the PBX, not here)
    sip_ringing_timeout_seconds: int = Field(default=30, ge=10, le=80)
    max_call_seconds: int = Field(default=600, ge=60, le=1800)
    # Noise reduction on the caller's audio, as in the inbound voicebot: ai-coustics QUAIL_VF_S and
    # nothing else (Krisp plus WebRTC suppression and gain control together clipped speech).
    phone_noise_cancellation: Literal["ai_coustics", "krisp", "none"] = "ai_coustics"

    # Call recording to Tencent COS (S3-compatible), approved by the PM on 8 Oct 2026. Off until set.
    cos_secret_id: SecretStr | None = None
    cos_secret_key: SecretStr | None = None
    cos_region: str | None = None  # e.g. ap-bangkok
    cos_bucket: str | None = None  # name-appid
    cos_prefix: str = "kpi-voicebot/recordings/"

    @property
    def recording_enabled(self) -> bool:
        return bool(self.cos_secret_id and self.cos_secret_key and self.cos_region and self.cos_bucket)

    def livekit_missing(self) -> list[str]:
        """Settings a phone call needs that are not set."""
        needed: dict[str, object] = {
            "LIVEKIT_URL": self.livekit_url,
            "LIVEKIT_API_KEY": self.livekit_api_key,
            "LIVEKIT_API_SECRET": self.livekit_api_secret,
            "LIVEKIT_SIP_OUTBOUND_TRUNK_ID": self.livekit_sip_outbound_trunk_id,
            "SIP_CALLER_NUMBER": self.sip_caller_number,
        }
        if self.asr_provider == "soniox":
            needed["SONIOX_API_KEY"] = self.soniox_api_key
        else:
            needed["JAIASR_API_KEY"] = self.jaiasr_api_key
        if self.tts_provider == "jai":
            needed["JAITTS_API_KEY"] = self.jaitts_api_key
        else:
            needed["GOOGLE_API_KEY"] = self.google_api_key
        return [name for name, value in needed.items() if not value]


@lru_cache
def get_settings() -> Settings:
    return Settings()  # type: ignore[call-arg]
