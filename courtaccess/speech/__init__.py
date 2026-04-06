"""
courtaccess.speech — Real-time speech translation pipeline.

Modules:
  vad              — Silero VAD voice activity detection
  transcribe       — Faster-Whisper ASR
  tts              — Piper TTS synthesis
  mt_service       — CTranslate2 + NLLB-200 machine translation
  turn_taking      — Conversation turn-taking state machine
  session_recorder — Session WAV recording + transcript logging
  legal_verifier   — LLaMA 4 real-time legal verification (Vertex AI)
  session          — AudioSession, ConversationRoom, Participant
"""
