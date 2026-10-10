"""STT Benchmark and Evaluation Suite for Airi."""
from __future__ import annotations

import asyncio
import os
import re
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional

import structlog

from app.voice.stt.whisper_provider import WhisperSTTProvider

logger = structlog.get_logger(__name__)


def calculate_wer(reference: str, hypothesis: str) -> float:
    """Calculate Word Error Rate (WER) using dynamic programming Levenshtein distance."""
    ref_words = re.findall(r"\b\w+\b", reference.lower())
    hyp_words = re.findall(r"\b\w+\b", hypothesis.lower())
    if not ref_words:
        return 0.0 if not hyp_words else 1.0

    d = [[0] * (len(hyp_words) + 1) for _ in range(len(ref_words) + 1)]
    for i in range(len(ref_words) + 1):
        d[i][0] = i
    for j in range(len(hyp_words) + 1):
        d[0][j] = j

    for i in range(1, len(ref_words) + 1):
        for j in range(1, len(hyp_words) + 1):
            if ref_words[i - 1] == hyp_words[j - 1]:
                d[i][j] = d[i - 1][j - 1]
            else:
                substitution = d[i - 1][j - 1] + 1
                insertion = d[i][j - 1] + 1
                deletion = d[i - 1][j] + 1
                d[i][j] = min(substitution, insertion, deletion)

    return d[len(ref_words)][len(hyp_words)] / float(len(ref_words))


compute_wer = calculate_wer



@dataclass
class STTCandidate:
    name: str
    model_size: str
    device: str
    compute_type: str


DEFAULT_CANDIDATES = [
    STTCandidate("Large-v3-Turbo (CPU int8)", "large-v3-turbo", "cpu", "int8"),
    STTCandidate("Base (CPU int8)", "base", "cpu", "int8"),
]


async def run_stt_benchmark(
    samples: list[tuple[str, Optional[str]]],
    candidates: Optional[list[STTCandidate]] = None,
) -> list[dict[str, Any]]:
    """Run STT benchmark on saved WAV samples across candidate models.

    Args:
        samples: List of (audio_file_path, reference_transcript_or_None).
        candidates: List of candidate model configurations to evaluate.

    Returns:
        Structured benchmark results list.
    """
    if candidates is None:
        candidates = list(DEFAULT_CANDIDATES)
        # Add CUDA candidate if CUDA is available
        try:
            import torch
            if torch.cuda.is_available():
                candidates.append(
                    STTCandidate("Large-v3-Turbo (CUDA float16)", "large-v3-turbo", "cuda", "float16")
                )
        except Exception:
            pass

    print("=" * 75)
    print("  Airi Speech-to-Text (STT) Benchmark & Evaluation")
    print(f"  Evaluating {len(samples)} sample(s) across {len(candidates)} candidate configuration(s)")
    print("=" * 75)

    all_results = []

    for cand in candidates:
        print(f"\n▶ Evaluating Candidate: {cand.name}")
        print(f"  Model: {cand.model_size} | Device: {cand.device} | Compute: {cand.compute_type}")
        t_init0 = time.perf_counter()
        try:
            provider = WhisperSTTProvider(
                model_size=cand.model_size,
                device=cand.device,
                compute_type=cand.compute_type,
            )
        except Exception as e:
            print(f"  ❌ Failed to initialize provider {cand.name}: {e}")
            continue
        t_init = time.perf_counter() - t_init0
        print(f"  Loaded in {t_init:.2f}s")

        cand_results = []
        for sample_idx, (audio_path, ref_text) in enumerate(samples, 1):
            if not os.path.exists(audio_path):
                print(f"  Sample {sample_idx}: File not found ({audio_path})")
                continue

            try:
                stt_res = await provider.transcribe_file(audio_path)
            except Exception as e:
                print(f"  Sample {sample_idx}: Error during transcription: {e}")
                continue

            wer = None
            if ref_text:
                wer = calculate_wer(ref_text, stt_res.text)

            res_entry = {
                "candidate": cand.name,
                "model": cand.model_size,
                "device": cand.device,
                "actual_device": stt_res.metrics.get("device", cand.device),
                "compute_type": cand.compute_type,
                "sample_path": audio_path,
                "reference": ref_text,
                "transcript": stt_res.text,
                "latency_sec": stt_res.latency,
                "audio_duration_sec": stt_res.metrics.get("audio_duration_sec", 0.0),
                "real_time_factor": stt_res.metrics.get("real_time_factor", 0.0),
                "wer": wer,
                "decode_settings": {
                    "beam_size": provider.beam_size,
                    "temperature": provider.temperature,
                    "vad_filter": provider.vad_filter,
                    "hotwords": provider.hotwords,
                },
            }
            cand_results.append(res_entry)
            all_results.append(res_entry)

            print(f"  [{sample_idx}/{len(samples)}] Latency: {stt_res.latency:.3f}s (RTF: {res_entry['real_time_factor']:.3f}x)")
            if ref_text:
                print(f"    Ref:  {ref_text!r}")
            print(f"    Hyp:  {stt_res.text!r}")
            if wer is not None:
                print(f"    WER:  {wer:.1%}")

        # Summary for candidate
        if cand_results:
            avg_lat = sum(r["latency_sec"] for r in cand_results) / len(cand_results)
            avg_rtf = sum(r["real_time_factor"] for r in cand_results) / len(cand_results)
            wers = [r["wer"] for r in cand_results if r["wer"] is not None]
            avg_wer_str = f"{sum(wers) / len(wers):.1%}" if wers else "N/A"
            print(f"  Summary for {cand.name}: Avg Latency: {avg_lat:.3f}s | Avg RTF: {avg_rtf:.3f}x | Avg WER: {avg_wer_str}")

    print("\n" + "=" * 75)
    print("  Benchmark Complete")
    print("=" * 75)
    return all_results
