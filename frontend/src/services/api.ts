/**
 * API Service — real backend integration.
 *
 * Local dev: calls go through the Vite proxy (/api -> localhost:8000).
 * Production: set VITE_API_URL so requests go to the Render backend URL.
 */

const RAW_API_BASE = (import.meta.env.VITE_API_URL as string | undefined)?.trim() ?? '';
const API_BASE = RAW_API_BASE.replace(/\/+$/, '');

function apiUrl(path: string): string {
  const normalizedPath = path.startsWith('/') ? path : `/${path}`;
  return API_BASE ? `${API_BASE}${normalizedPath}` : normalizedPath;
}

// ─── Types ───────────────────────────────────────────────────────────

/** A single voice option returned from the backend. */
export interface VoiceOption {
  shortName: string;
  displayName: string;
}

/** Progress callback signature */
export type ProgressCallback = (percent: number, status: string) => void;

// ─── Language Detection ──────────────────────────────────────────────

/**
 * Detect the language of the given text via the backend.
 * Returns an edge-tts locale code like "en-US".
 */
export async function detectLanguage(text: string): Promise<string> {
  const res = await fetch(apiUrl('/api/detect-language'), {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ text }),
  });

  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: 'Language detection failed' }));
    throw new Error(err.detail || 'Language detection failed');
  }

  const data: { language: string } = await res.json();
  return data.language;
}

// ─── Voices ──────────────────────────────────────────────────────────

/**
 * Fetch available voices for a given language locale (e.g. "en-US" or "en").
 */
export async function getVoices(language: string): Promise<VoiceOption[]> {
  const res = await fetch(apiUrl(`/api/voices?language=${encodeURIComponent(language)}`));

  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: 'Failed to load voices' }));
    throw new Error(err.detail || 'Failed to load voices');
  }

  const data: {
    language: string;
    voices: { short_name: string; gender: string; locale: string }[];
  } = await res.json();

  return data.voices.map((v) => ({
    shortName: v.short_name,
    displayName: formatVoiceDisplay(v.short_name, v.gender),
  }));
}

/**
 * Turn "en-US-GuyNeural" + "Male" into "Guy (Male)"
 */
function formatVoiceDisplay(shortName: string, gender: string): string {
  // ShortName format: "locale-NameNeural", e.g. "en-US-GuyNeural"
  const parts = shortName.split('-');
  // The name is everything after the locale parts, minus "Neural" suffix
  const namePart = parts.slice(2).join('-').replace(/Neural$/i, '').replace(/Multilingual$/i, '');
  return `${namePart || shortName} (${gender})`;
}

// ─── TTS Generation ──────────────────────────────────────────────────

/**
 * Generate TTS audio. Returns an MP3 Blob.
 *
 * Since the backend is synchronous (POST → wait → MP3), we simulate
 * progress updates based on estimated generation time.
 */
export async function generateTTS(
  text: string,
  voiceName: string,
  onProgress?: ProgressCallback,
  signal?: AbortSignal,
): Promise<Blob> {
  // Estimate total duration based on text length (rough heuristic)
  const wordCount = text.trim().split(/\s+/).length;
  const estimatedSeconds = Math.max(3, Math.min(60, wordCount / 50));

  // Start simulated progress in the background
  const { stop } = simulateProgress(estimatedSeconds, onProgress);

  try {
    const res = await fetch(apiUrl('/api/tts'), {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ text, voice_name: voiceName }),
      signal,
    });

    stop();

    if (!res.ok) {
      const err = await res.json().catch(() => ({ detail: 'TTS generation failed' }));
      throw new Error(err.detail || 'TTS generation failed');
    }

    onProgress?.(100, 'Done!');
    return await res.blob();

  } catch (err) {
    stop();
    throw err;
  }
}

/**
 * Simulate realistic progress updates while the backend works.
 * Returns a `stop` function to cancel the simulation.
 */
function simulateProgress(
  estimatedSeconds: number,
  onProgress?: ProgressCallback,
): { stop: () => void } {
  let cancelled = false;
  const totalMs = estimatedSeconds * 1000;

  const steps = [
    { at: 0.00, pct: 5,  msg: 'Sending request…' },
    { at: 0.05, pct: 10, msg: 'Analyzing text…' },
    { at: 0.15, pct: 20, msg: 'Splitting into chunks…' },
    { at: 0.25, pct: 35, msg: 'Generating audio…' },
    { at: 0.45, pct: 50, msg: 'Still generating…' },
    { at: 0.60, pct: 65, msg: 'Processing chunks…' },
    { at: 0.75, pct: 78, msg: 'Merging audio…' },
    { at: 0.88, pct: 88, msg: 'Almost done…' },
    { at: 0.95, pct: 93, msg: 'Finalizing…' },
  ];

  const timers: ReturnType<typeof setTimeout>[] = [];

  for (const step of steps) {
    const timer = setTimeout(() => {
      if (!cancelled) onProgress?.(step.pct, step.msg);
    }, step.at * totalMs);
    timers.push(timer);
  }

  return {
    stop: () => {
      cancelled = true;
      timers.forEach(clearTimeout);
    },
  };
}
