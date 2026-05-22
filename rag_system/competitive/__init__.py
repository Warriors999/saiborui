"""Competitive video analysis pipeline — learn from top creators.

Pipeline:
  1. Search Bilibili/Douyin for top videos by category
  2. Download videos + audio
  3. Transcribe audio to text (Whisper)
  4. Analyze script structure, hooks, pacing
  5. Detect visual patterns (scene changes, shot rhythm)
  6. Store in knowledge base, generate weekly/monthly reports
"""
