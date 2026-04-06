"""
Session Recording & Transcript Log — Phase 10

Provides:
  - SessionRecorder         : accumulates per-language audio tracks and writes WAVs
  - TranscriptLogger        : accumulates structured transcript entries and writes text
  - upload_session_artifacts: uploads JSON transcript (always) and WAVs (if enabled) to GCS
  - write_manifest          : generates SHA-256 manifest JSON for all session artifacts

Output directory layout:
    recordings/sessions/{session_name}/
        {session_name}_en.wav
        {session_name}_es.wav
        {session_name}_transcript.txt
        {session_name}_manifest.json

GCS upload behaviour (controlled by env vars, not Pydantic settings):
    GCS_BUCKET_TRANSCRIPTS   — bucket for JSON transcript upload; skip if unset
    AUDIO_STORAGE_ENABLED    — "true" to also upload WAV files; default false (MVP off)

On session end:
    1. recorder.finalize()           → writes WAVs locally
    2. transcript_logger.finalize()  → writes .txt locally
    3. upload_session_artifacts()    → uploads JSON transcript + optionally WAVs to GCS
"""

import hashlib
import io
import json
import os
import tempfile
import time
import wave
from datetime import UTC, datetime
from pathlib import Path

import numpy as np

from courtaccess.core.config import get_settings
from courtaccess.core.logger import get_logger

logger = get_logger(__name__)


def _get_sessions_dir() -> Path:
    """Resolve session recordings directory from settings (lazy)."""
    recordings_dir = get_settings().session_recordings_dir or str(
        Path(tempfile.gettempdir()) / "courtaccess" / "sessions"
    )
    d = Path(recordings_dir)
    d.mkdir(parents=True, exist_ok=True)
    return d


# Module-level accessor — callers use SESSIONS_DIR as a function-like call.
# Kept as a plain variable that's reassigned to the function so existing
# code that does `SESSIONS_DIR / name` still works via __truediv__.
# We use a lazy wrapper class instead.
class _LazyPath:
    """Lazy Path proxy — resolves from settings on first attribute access."""

    def __truediv__(self, other):
        return _get_sessions_dir() / other

    def __str__(self):
        return str(_get_sessions_dir())

    def __fspath__(self):
        return str(_get_sessions_dir())


SESSIONS_DIR = _LazyPath()


# ------------------------------------------------------------------ #
#  SessionRecorder                                                     #
# ------------------------------------------------------------------ #


class SessionRecorder:
    """
    Accumulates parallel audio tracks — one per language — and writes
    them as WAV files when the session ends.

    Each track interleaves:
      - Original speaker PCM (when someone speaks that language)
      - TTS PCM (translation synthesised *into* that language)
      - Silence padding (to keep both tracks time-aligned)

    All audio is normalised to a uniform sample rate (16 kHz, 16-bit
    mono) regardless of the source.
    """

    SAMPLE_RATE = 16_000  # Uniform output sample rate
    SAMPLE_WIDTH = 2  # 16-bit PCM
    CHANNELS = 1  # Mono

    def __init__(
        self,
        session_name: str,
        language_a: str,
        language_b: str,
        name_a: str = "User A",
        name_b: str = "User B",
    ):
        self.session_name = session_name
        self.language_a = language_a
        self.language_b = language_b
        self.name_a = name_a
        self.name_b = name_b

        # Per-role PCM buffers keyed by role ("a" / "b").
        # Keying by role (not language) keeps buffers distinct when both
        # participants speak the same language.
        self._tracks: dict[str, list[bytes]] = {"a": [], "b": []}

        # Running sample count per role track (for alignment)
        self._sample_counts: dict[str, int] = {"a": 0, "b": 0}

        self._start_time = time.time()

    # ------------------------------------------------------------------ #
    #  Audio ingestion                                                     #
    # ------------------------------------------------------------------ #

    def add_speech_pcm(
        self,
        role: str,
        pcm: np.ndarray,
        source_sample_rate: int = 16_000,
    ) -> None:
        """
        Append a speaker's original PCM to their language track and
        pad the other track with equivalent silence for alignment.

        Args:
            role: "a" or "b" — determines which language track.
            pcm:  float32 numpy array in [-1, 1] at *source_sample_rate*.
            source_sample_rate: sample rate of the input PCM.
        """
        other_role = "b" if role == "a" else "a"

        pcm_16k = self._resample_if_needed(pcm, source_sample_rate)
        pcm_bytes = self._float32_to_int16_bytes(pcm_16k)
        n_samples = len(pcm_16k)

        # Append speech to speaker's track
        self._tracks[role].append(pcm_bytes)
        self._sample_counts[role] += n_samples

        # Pad other track with silence
        silence = b"\x00\x00" * n_samples  # 2 bytes per int16 sample
        self._tracks[other_role].append(silence)
        self._sample_counts[other_role] += n_samples

    def add_tts_pcm(self, role: str, wav_bytes: bytes) -> None:
        """
        Extract raw PCM from TTS WAV output and append to the target
        role track.  The other track is padded with equivalent silence.

        Args:
            role:      "a" or "b" — the participant whose track receives the TTS.
            wav_bytes: complete WAV file bytes from Piper TTS.
        """
        if not wav_bytes:
            return

        try:
            buf = io.BytesIO(wav_bytes)
            with wave.open(buf, "rb") as wf:
                tts_sr = wf.getframerate()
                raw_frames = wf.readframes(wf.getnframes())
                sample_width = wf.getsampwidth()
        except Exception as e:
            logger.warning("Failed to parse TTS WAV: %s", e)
            return

        # Convert to float32 for resampling
        if sample_width == 2:
            samples = np.frombuffer(raw_frames, dtype=np.int16).astype(np.float32) / 32768.0
        elif sample_width == 4:
            samples = np.frombuffer(raw_frames, dtype=np.int32).astype(np.float32) / 2147483648.0
        else:
            logger.warning("Unsupported sample width: %s", sample_width)
            return

        pcm_16k = self._resample_if_needed(samples, tts_sr)
        pcm_bytes = self._float32_to_int16_bytes(pcm_16k)
        n_samples = len(pcm_16k)

        other_role = "b" if role == "a" else "a"

        # Append TTS to target role track
        self._tracks[role].append(pcm_bytes)
        self._sample_counts[role] += n_samples

        # Pad the other track with silence
        silence = b"\x00\x00" * n_samples
        self._tracks[other_role].append(silence)
        self._sample_counts[other_role] += n_samples

    # ------------------------------------------------------------------ #
    #  Finalisation                                                        #
    # ------------------------------------------------------------------ #

    def finalize(self, output_dir: Path | None = None) -> dict[str, Path]:
        """
        Write both language tracks as WAV files.

        Returns:
            dict mapping language code → output WAV path.
        """
        if output_dir is None:
            output_dir = SESSIONS_DIR / self.session_name
        output_dir.mkdir(parents=True, exist_ok=True)

        paths: dict[str, Path] = {}

        # Map role → language for filenames/metadata; roles always differ so
        # buffers remain distinct even when language_a == language_b.
        role_lang = {"a": self.language_a, "b": self.language_b}

        for role, lang in role_lang.items():
            filename = f"{self.session_name}_{role}_{lang}.wav"
            wav_path = output_dir / filename
            pcm_data = b"".join(self._tracks[role])

            with wave.open(str(wav_path), "wb") as wf:
                wf.setnchannels(self.CHANNELS)
                wf.setsampwidth(self.SAMPLE_WIDTH)
                wf.setframerate(self.SAMPLE_RATE)
                wf.writeframes(pcm_data)

            duration_s = self._sample_counts[role] / self.SAMPLE_RATE
            logger.info("Wrote %s (%.1fs, %d bytes)", wav_path.name, duration_s, len(pcm_data))
            paths[role] = wav_path

        return paths

    # ------------------------------------------------------------------ #
    #  Helpers                                                             #
    # ------------------------------------------------------------------ #

    @staticmethod
    def _resample_if_needed(pcm: np.ndarray, source_sr: int) -> np.ndarray:
        """Simple decimation/interpolation to 16 kHz."""
        target_sr = SessionRecorder.SAMPLE_RATE
        if source_sr == target_sr:
            return pcm
        # Basic linear resampling
        ratio = target_sr / source_sr
        n_out = int(len(pcm) * ratio)
        if n_out == 0:
            return np.array([], dtype=np.float32)
        indices = np.linspace(0, len(pcm) - 1, n_out)
        return np.interp(indices, np.arange(len(pcm)), pcm).astype(np.float32)

    @staticmethod
    def _float32_to_int16_bytes(pcm: np.ndarray) -> bytes:
        """Convert float32 [-1, 1] PCM to 16-bit little-endian bytes."""
        clipped = np.clip(pcm, -1.0, 1.0)
        int16_data = (clipped * 32767).astype(np.int16)
        return int16_data.tobytes()


# ------------------------------------------------------------------ #
#  TranscriptLogger                                                    #
# ------------------------------------------------------------------ #


class TranscriptLogger:
    """
    Accumulates structured utterance dicts during a conversation and
    formats them as a readable turn-by-turn text file on finalisation.

    Nothing is written to the database per-utterance.  The in-memory
    list is flushed to the DB in bulk when the session ends (Phase 3.4).

    Each utterance dict stored by ``add_entry`` contains:
        turn_index              int      — 0-based turn counter
        speaker_role            str      — "a" (creator) or "b" (joiner)
        spoken_at               datetime — UTC wall-clock time of the utterance
        original_text           str      — ASR transcript
        translated_text         str|None — MT output (None if MT skipped)
        source_lang             str      — ISO/NLLB source language code
        target_lang             str      — ISO/NLLB target language code
        asr_confidence          float|None — Whisper segment avg_logprob (0-1 normalised)
        nllb_confidence         float|None — NLLB beam score (0-1 normalised)
        legal_verified          bool     — True if LegalVerifier approved the translation
        legal_correction_applied bool    — True if verifier rewrote the translation
    """

    def __init__(
        self,
        session_name: str,
        language_a: str,
        language_b: str,
        name_a: str = "User A",
        name_b: str = "User B",
    ):
        self.session_name = session_name
        self.language_a = language_a
        self.language_b = language_b
        self.name_a = name_a
        self.name_b = name_b
        self._utterances: list[dict] = []
        self._start_time = time.time()

    # ------------------------------------------------------------------
    #  Ingestion
    # ------------------------------------------------------------------

    def add_entry(
        self,
        *,
        speaker_role: str,
        original_text: str,
        source_lang: str,
        target_lang: str,
        translated_text: str | None = None,
        spoken_at: datetime | None = None,
        asr_confidence: float | None = None,
        nllb_confidence: float | None = None,
        legal_verified: bool = False,
        legal_correction_applied: bool = False,
    ) -> None:
        """
        Record one utterance turn.

        Args:
            speaker_role:              "a" (room creator) or "b" (joiner).
            original_text:             Raw ASR transcript.
            source_lang:               Language code of the speaker.
            target_lang:               Language code of the partner.
            translated_text:           MT output; None if translation was skipped.
            spoken_at:                 UTC timestamp; defaults to now if omitted.
            asr_confidence:            Whisper avg_logprob normalised to [0, 1].
            nllb_confidence:           NLLB beam score normalised to [0, 1].
            legal_verified:            True when LegalVerifier accepted the translation.
            legal_correction_applied:  True when LegalVerifier rewrote the translation.
        """
        self._utterances.append(
            {
                "turn_index": len(self._utterances),
                "speaker_role": speaker_role,
                "spoken_at": spoken_at or datetime.now(tz=UTC),
                "original_text": original_text,
                "translated_text": translated_text,
                "source_lang": source_lang,
                "target_lang": target_lang,
                "asr_confidence": asr_confidence,
                "nllb_confidence": nllb_confidence,
                "legal_verified": legal_verified,
                "legal_correction_applied": legal_correction_applied,
            }
        )

    # ------------------------------------------------------------------
    #  Accessors
    # ------------------------------------------------------------------

    @property
    def utterances(self) -> list[dict]:
        """Return the accumulated utterance list (read-only view)."""
        return self._utterances

    @property
    def entry_count(self) -> int:
        return len(self._utterances)

    # ------------------------------------------------------------------
    #  Formatting & finalisation
    # ------------------------------------------------------------------

    def format_text(self) -> str:
        """Render the transcript as human-readable turn-by-turn text."""
        total_duration = time.time() - self._start_time
        mins = int(total_duration // 60)
        secs = int(total_duration % 60)

        lines = [
            "SESSION TRANSCRIPT",
            "=" * 60,
            f"Session : {self.session_name}",
            f"Participants : A ({self.name_a}, {self.language_a.upper()}), "
            f"B ({self.name_b}, {self.language_b.upper()})",
            f"Duration: {mins}m {secs:02d}s",
            f"Entries : {len(self._utterances)}",
            "=" * 60,
            "",
        ]

        for utt in self._utterances:
            spoken_at: datetime = utt["spoken_at"]
            offset = (spoken_at.replace(tzinfo=None) - datetime.utcfromtimestamp(self._start_time + 0)).total_seconds()
            # Fall back to simple turn numbering if offset calculation is odd
            mm = max(0, int(offset // 60))
            ss = max(0, int(offset % 60))
            timestamp = f"[{mm:02d}:{ss:02d}]"

            role = utt["speaker_role"]
            name = self.name_a if role == "a" else self.name_b
            lang = utt["source_lang"].upper()

            line = f'{timestamp} USER {role.upper()} ({name}, {lang}): "{utt["original_text"]}"'

            if utt["translated_text"] and utt["target_lang"]:
                tgt = utt["target_lang"].upper()
                line += f'\n{"":>8}→ ({tgt}): "{utt["translated_text"]}"'

            flags: list[str] = []
            if utt["asr_confidence"] is not None:
                flags.append(f"ASR={utt['asr_confidence']:.2f}")
            if utt["nllb_confidence"] is not None:
                flags.append(f"MT={utt['nllb_confidence']:.2f}")
            if utt["legal_verified"]:
                flags.append("verified")
            if utt["legal_correction_applied"]:
                flags.append("corrected")
            if flags:
                line += f"\n{'':>8}[{', '.join(flags)}]"

            lines.append(line)
            lines.append("")

        return "\n".join(lines)

    def serialize(
        self,
        *,
        session_id: str,
        start_time: datetime | None = None,
        end_time: datetime | None = None,
    ) -> dict:
        """
        Build the full JSON payload for the GCS transcript upload.

        All ``datetime`` values in utterances are converted to ISO-8601 strings
        so the returned dict is directly JSON-serialisable with the standard
        library ``json`` module (no custom encoder needed).

        Args:
            session_id:  DB UUID for the session (used as the GCS path prefix).
            start_time:  Session start wall-clock time (UTC).
            end_time:    Session end wall-clock time (UTC); defaults to now.

        Returns:
            Dict with top-level session metadata and a ``utterances`` array.
        """
        _end = end_time or datetime.now(tz=UTC)
        duration_s: float | None = None
        if start_time is not None:
            duration_s = round((_end - start_time).total_seconds(), 2)

        serialised_utterances = [
            {
                **utt,
                "spoken_at": utt["spoken_at"].isoformat()
                if isinstance(utt.get("spoken_at"), datetime)
                else utt.get("spoken_at"),
            }
            for utt in self._utterances
        ]

        return {
            "session_id": session_id,
            "session_name": self.session_name,
            "language_a": self.language_a,
            "language_b": self.language_b,
            "name_a": self.name_a,
            "name_b": self.name_b,
            "start_time": start_time.isoformat() if start_time else None,
            "end_time": _end.isoformat(),
            "duration_seconds": duration_s,
            "total_utterances": len(self._utterances),
            "generated_at": datetime.now(tz=UTC).isoformat(),
            "utterances": serialised_utterances,
        }

    def finalize(self, output_dir: Path | None = None) -> Path:
        """Write transcript to a text file and return the path."""
        if output_dir is None:
            output_dir = SESSIONS_DIR / self.session_name
        output_dir.mkdir(parents=True, exist_ok=True)

        filename = f"{self.session_name}_transcript.txt"
        txt_path = output_dir / filename
        content = self.format_text()
        txt_path.write_text(content, encoding="utf-8")

        logger.info("Wrote %s (%d entries, %d bytes)", txt_path.name, len(self._utterances), len(content))
        return txt_path


# ------------------------------------------------------------------ #
#  Manifest writer                                                     #
# ------------------------------------------------------------------ #


def _sha256_file(path: Path) -> str:
    """Compute SHA-256 hex digest of a file."""
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            h.update(chunk)
    return h.hexdigest()


def write_manifest(
    session_dir: Path,
    session_name: str,
    *,
    start_time: datetime,
    end_time: datetime,
    language_a: str,
    language_b: str,
    name_a: str,
    name_b: str,
    room_id: str,
    transcript_entries: int = 0,
) -> Path:
    """
    Generate a SHA-256 manifest JSON for all session artifacts.

    Hashes every file in *session_dir* (WAVs + transcript) and writes
    the manifest alongside them.

    Returns:
        Path to the manifest JSON file.
    """
    session_dir.mkdir(parents=True, exist_ok=True)

    # Collect all non-manifest files in the session directory
    artifact_files = sorted(f for f in session_dir.iterdir() if f.is_file() and not f.name.endswith("_manifest.json"))

    files_info = []
    for f in artifact_files:
        files_info.append(
            {
                "filename": f.name,
                "size_bytes": f.stat().st_size,
                "sha256": _sha256_file(f),
            }
        )

    manifest = {
        "session_name": session_name,
        "room_id": room_id,
        "start_time": start_time.isoformat(),
        "end_time": end_time.isoformat(),
        "duration_seconds": round((end_time - start_time).total_seconds(), 2),
        "participants": {
            "a": {"name": name_a, "language": language_a},
            "b": {"name": name_b, "language": language_b},
        },
        "transcript_entries": transcript_entries,
        "files": files_info,
        "generated_at": datetime.now(tz=UTC).isoformat(),
    }

    manifest_path = session_dir / f"{session_name}_manifest.json"
    manifest_path.write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )

    logger.info("Wrote %s (%d files hashed)", manifest_path.name, len(files_info))
    return manifest_path


# ------------------------------------------------------------------ #
#  GCS upload                                                          #
# ------------------------------------------------------------------ #


def upload_wav_tracks(
    session_name: str,
    wav_paths: dict[str, Path],
) -> dict[str, str]:
    """
    Upload WAV audio tracks to GCS if ``AUDIO_STORAGE_ENABLED=true``.

    Controlled by env vars (``os.getenv``, never Pydantic — this module lives
    in ``courtaccess/``):

    ``GCS_BUCKET_TRANSCRIPTS``
        Bucket to upload into.  Skipped if unset.
    ``AUDIO_STORAGE_ENABLED``
        Must be ``"true"`` for uploads to proceed.  Defaults to ``"false"``
        (audio storage is **off** for MVP).

    Upload path: ``sessions/{session_name}/{wav_filename}``

    Args:
        session_name: Session identifier used as the GCS path prefix.
        wav_paths:    ``{role: local_wav_path}`` from ``SessionRecorder.finalize()``
                      where role is ``"a"`` or ``"b"``.  The WAV filename already
                      encodes the language (e.g. ``session_a_en.wav``).

    Returns:
        Mapping of ``audio_{role}`` → ``gs://`` URI for each uploaded track.
        Empty dict when audio storage is disabled or bucket is not configured.
    """
    from courtaccess.core import gcs

    bucket = os.getenv("GCS_BUCKET_TRANSCRIPTS", "").strip()
    audio_enabled = os.getenv("AUDIO_STORAGE_ENABLED", "false").lower() == "true"

    if not bucket or not audio_enabled:
        logger.debug("WAV upload skipped for %s (AUDIO_STORAGE_ENABLED=%s)", session_name, audio_enabled)
        return {}

    uploaded: dict[str, str] = {}
    for role, wav_path in wav_paths.items():
        blob_name = f"sessions/{session_name}/{wav_path.name}"
        try:
            gcs.upload_bytes(bucket, blob_name, wav_path.read_bytes(), "audio/wav")
            uri = gcs.gcs_uri(bucket, blob_name)
            uploaded[f"audio_{role}"] = uri
            logger.info("Uploaded audio track → %s", uri)
        except Exception as exc:
            logger.warning("Failed to upload audio %s: %s", wav_path.name, exc)
    return uploaded
