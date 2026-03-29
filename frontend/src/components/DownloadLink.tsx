import { useEffect, useState } from 'react';
import './DownloadLink.css';

interface DownloadLinkProps {
  blob: Blob;
  filename?: string;
}

export default function DownloadLink({ blob, filename = 'speech.mp3' }: DownloadLinkProps) {
  const [durationStr, setDurationStr] = useState<string>('');

  useEffect(() => {
    // Decode audio data to find its precise duration
    const audioContextCtor = window.AudioContext || (window as Window & { webkitAudioContext?: typeof AudioContext }).webkitAudioContext;
    if (!audioContextCtor) {
      return;
    }
    const audioCtx = new audioContextCtor();
    const reader = new FileReader();

    reader.onload = async function() {
      try {
        const arrayBuffer = reader.result as ArrayBuffer;
        const audioBuffer = await audioCtx.decodeAudioData(arrayBuffer);
        
        const seconds = Math.floor(audioBuffer.duration);
        const hours = Math.floor(seconds / 3600);
        const minutes = Math.floor((seconds % 3600) / 60);
        const secs = seconds % 60;
        
        if (hours > 0) {
          setDurationStr(`${hours.toString().padStart(2, '0')}:${minutes.toString().padStart(2, '0')}:${secs.toString().padStart(2, '0')}`);
        } else {
          setDurationStr(`${minutes.toString().padStart(2, '0')}:${secs.toString().padStart(2, '0')}`);
        }
      } catch (err) {
        console.error('Failed to decode audio duration:', err);
      } finally {
        if (audioCtx.state !== 'closed') {
          audioCtx.close();
        }
      }
    };
    reader.readAsArrayBuffer(blob);

  }, [blob]);

  function handleDownload() {
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = filename;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    URL.revokeObjectURL(url);
  }

  return (
    <div className="download animate-in">
      <button
        id="download-button"
        className="download__button"
        onClick={handleDownload}
        type="button"
      >
        <svg className="download__icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
          <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4" />
          <polyline points="7 10 12 15 17 10" />
          <line x1="12" y1="15" x2="12" y2="3" />
        </svg>
        Download MP3
      </button>
      <span className="download__hint">
        {formatSize(blob.size)} {durationStr && `· ${durationStr}`} · Click to save
      </span>
    </div>
  );
}

function formatSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(2)} MB`;
}
