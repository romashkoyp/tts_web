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

export async function generateTTS(
  text: string,
  voiceName: string,
  onProgress?: ProgressCallback,
  signal?: AbortSignal,
): Promise<Blob> {
  const res = await fetch(apiUrl('/api/tts'), {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ text, voice_name: voiceName }),
    signal,
  });

  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: 'TTS generation failed' }));
    throw new Error(err.detail || 'TTS generation failed');
  }

  if (!res.body) {
    throw new Error('Response body is missing');
  }

  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let buffer = '';
  let audioBase64 = '';

  while (true) {
    const { done, value } = await reader.read();
    if (done) break;

    buffer += decoder.decode(value, { stream: true });
    const lines = buffer.split('\n');
    buffer = lines.pop() ?? '';

    for (const line of lines) {
      const trimmed = line.trim();
      if (!trimmed) continue;

      try {
        const event = JSON.parse(trimmed);
        if (event.type === 'progress') {
          onProgress?.(event.percent, event.status);
        } else if (event.type === 'complete') {
          audioBase64 = event.audio_base64;
        } else if (event.type === 'error') {
          throw new Error(event.detail || 'TTS generation failed');
        }
      } catch (e) {
        if (e instanceof Error) {
          throw e;
        }
      }
    }
  }

  if (!audioBase64) {
    throw new Error('TTS generation failed to produce audio payload');
  }

  // Convert base64 to Uint8Array and Blob
  const binary = atob(audioBase64);
  const bytes = new Uint8Array(binary.length);
  for (let i = 0; i < binary.length; i++) {
    bytes[i] = binary.charCodeAt(i);
  }

  onProgress?.(100, 'Done!');
  return new Blob([bytes], { type: 'audio/mpeg' });
}

