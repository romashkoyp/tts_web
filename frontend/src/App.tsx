import { useState, useCallback, useRef } from 'react';
import Header from './components/Header';
import Footer from './components/Footer';
import TextInput from './components/TextInput';
import VoiceSelector from './components/VoiceSelector';
import ProgressIndicator from './components/ProgressIndicator';
import DownloadLink from './components/DownloadLink';
import { getVoices, generateTTS } from './services/api';
import type { VoiceOption } from './services/api';
import './App.css';

type AppState = 'idle' | 'detected' | 'loading-voices' | 'generating' | 'done';

export default function App() {
  const [state, setState] = useState<AppState>('idle');
  const [text, setText] = useState('');
  const [voices, setVoices] = useState<VoiceOption[]>([]);
  const [selectedVoice, setSelectedVoice] = useState('');
  const [progress, setProgress] = useState(0);
  const [statusText, setStatusText] = useState('');
  const [audioBlob, setAudioBlob] = useState<Blob | null>(null);
  const [error, setError] = useState('');
  const [filename, setFilename] = useState('');

  const abortControllerRef = useRef<AbortController | null>(null);

  const handleTextChange = useCallback((newText: string) => {
    setText(newText);
    const count = newText.trim() ? newText.trim().split(/\s+/).length : 0;
    
    // Reset state if text drops below minimum word count
    if (count < 5 && state !== 'idle') {
      setState('idle');
      setAudioBlob(null);
      setVoices([]);
      setSelectedVoice('');
      if (abortControllerRef.current) {
        abortControllerRef.current.abort();
        abortControllerRef.current = null;
      }
      setProgress(0);
      setStatusText('');
    } else if (state === 'done') {
      // Reset downstream state if text changes significantly after generation
      setState('idle');
      setAudioBlob(null);
    }
  }, [state]);

  const handleLanguageDetected = useCallback(async (locale: string, langName: string) => {
    void langName;
    setError('');
    setSelectedVoice('');

    try {
      setState('loading-voices');
      const voiceList = await getVoices(locale);
      setVoices(voiceList);
      setState('detected');
    } catch {
      setError('Could not load voices. Please try again.');
      setState('idle');
    }
  }, []);

  async function handleGenerate() {
    if (!text.trim()) {
      setError('Please enter some text first.');
      return;
    }
    if (!selectedVoice) {
      setError('Please select a voice variation.');
      return;
    }

    // Generate filename based on current time: long_text_to_speech_{DD.MM.YYYY}_{HH.MM.SS}.mp3
    const now = new Date();
    const pad = (n: number) => n.toString().padStart(2, '0');
    const newFilename = `long_text_to_speech_${pad(now.getDate())}.${pad(now.getMonth() + 1)}.${now.getFullYear()}_${pad(now.getHours())}.${pad(now.getMinutes())}.${pad(now.getSeconds())}.mp3`;
    setFilename(newFilename);

    setError('');
    setState('generating');
    setProgress(0);
    setStatusText('Starting…');

    abortControllerRef.current = new AbortController();

    try {
      const blob = await generateTTS(
        text, 
        selectedVoice, 
        (pct, status) => {
          setProgress(pct);
          setStatusText(status);
        }, 
        abortControllerRef.current.signal
      );
      
      setAudioBlob(blob);
      setState('done');
    } catch (err: unknown) {
      if (err instanceof DOMException && err.name === 'AbortError') {
        // Silently ignore if it was manually cancelled
      } else {
        setError('Generation failed. Please try again.');
        setState('detected');
      }
    } finally {
      abortControllerRef.current = null;
    }
  }

  function handleClear() {
    // Abort ongoing generation if any
    if (abortControllerRef.current) {
        abortControllerRef.current.abort();
        abortControllerRef.current = null;
    }
    
    // Reset everything to initial state
    setState('idle');
    setAudioBlob(null);
    setProgress(0);
    setStatusText('');
    setError('');
    setText('');
    setVoices([]);
    setSelectedVoice('');
  }

  const isGenerating = state === 'generating';
  const showVoiceSelector = state === 'detected' || state === 'generating' || state === 'done';
  const showSubmit = state === 'detected';
  const showProgress = state === 'generating';
  const showDownload = state === 'done' && audioBlob;
  const showClear = text.length > 0;

  return (
    <>
      <Header />

      <main className="main">
        <div className="card glass-card">
          <TextInput
            onTextChange={handleTextChange}
            onLanguageDetected={handleLanguageDetected}
            disabled={isGenerating}
            value={text}
          />

          {showVoiceSelector && (
            <div className="card__section">
              <VoiceSelector
                voices={voices}
                onSelect={setSelectedVoice}
                disabled={isGenerating}
              />
            </div>
          )}

          {error && (
            <div className="card__error animate-in">
              {error}
            </div>
          )}

          <div className="card__actions animate-in" style={{ animationDelay: '0.15s' }}>
            {showSubmit && (
              <button
                id="generate-button"
                className="btn-primary"
                onClick={handleGenerate}
                type="button"
              >
                <svg className="btn-primary__icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                  <polygon points="5 3 19 12 5 21 5 3" />
                </svg>
                Generate MP3
              </button>
            )}
            
            {showClear && (
              <button
                id="clear-button"
                className="btn-secondary"
                onClick={handleClear}
                type="button"
              >
                Clear
              </button>
            )}
          </div>

          {showProgress && (
            <div className="card__section">
              <ProgressIndicator percent={progress} status={statusText} />
            </div>
          )}

          {showDownload && (
            <div className="card__section" style={{ marginTop: '2rem' }}>
              <DownloadLink blob={audioBlob} filename={filename} />
            </div>
          )}
        </div>
      </main>

      <Footer />
    </>
  );
}
