Official source: https://github.com/myshell-ai/OpenVoice ; commit 74a1d147b17a8c3092dd5430504bd83ef6c7eb23. MIT License retained. Conversion-only runner uses local V2 weights and Khmer audio from the existing TTS engine.

Compatibility patch: pop enable_watermark before forwarding constructor kwargs; upstream default remains True.
