import { useRef, useState } from 'react';
import { detectLanguage } from '../services/api';
import './TextInput.css';

// Locale prefix → human-readable name (for display only)
const LOCALE_NAMES: Record<string, string> = {
  af: 'Afrikaans', ar: 'Arabic', bg: 'Bulgarian', bn: 'Bengali',
  ca: 'Catalan', cs: 'Czech', cy: 'Welsh', da: 'Danish',
  de: 'German', el: 'Greek', en: 'English', es: 'Spanish',
  et: 'Estonian', fa: 'Persian', fi: 'Finnish', fr: 'French',
  ga: 'Irish', gl: 'Galician', gu: 'Gujarati', he: 'Hebrew',
  hi: 'Hindi', hr: 'Croatian', hu: 'Hungarian', id: 'Indonesian',
  it: 'Italian', ja: 'Japanese', jv: 'Javanese', ka: 'Georgian',
  kk: 'Kazakh', km: 'Khmer', kn: 'Kannada', ko: 'Korean',
  lo: 'Lao', lt: 'Lithuanian', lv: 'Latvian', mk: 'Macedonian',
  ml: 'Malayalam', mn: 'Mongolian', mr: 'Marathi', ms: 'Malay',
  my: 'Burmese', nb: 'Norwegian', ne: 'Nepali', nl: 'Dutch',
  pl: 'Polish', pt: 'Portuguese', ro: 'Romanian', ru: 'Russian',
  si: 'Sinhala', sk: 'Slovak', sl: 'Slovenian', so: 'Somali',
  sq: 'Albanian', sr: 'Serbian', su: 'Sundanese', sv: 'Swedish',
  sw: 'Swahili', ta: 'Tamil', te: 'Telugu', th: 'Thai',
  tr: 'Turkish', uk: 'Ukrainian', ur: 'Urdu', uz: 'Uzbek',
  vi: 'Vietnamese', zh: 'Chinese', zu: 'Zulu',
};

function localeToName(locale: string): string {
  const prefix = locale.split('-')[0].toLowerCase();
  return LOCALE_NAMES[prefix] || locale;
}

interface TextInputProps {
  onTextChange: (text: string) => void;
  onLanguageDetected: (locale: string, langName: string) => void;
  disabled?: boolean;
  /** Externally controlled text value (for reset/clear) */
  value?: string;
}

const MAX_BYTES = 5 * 1024 * 1024; // 5 MB

export default function TextInput({ onTextChange, onLanguageDetected, disabled, value }: TextInputProps) {
  const [text, setText] = useState('');
  const [error, setError] = useState('');
  const [detectedLang, setDetectedLang] = useState('');
  const [detecting, setDetecting] = useState(false);
  const textareaRef = useRef<HTMLTextAreaElement>(null);

  // If parent provides a value (e.g., after reset), sync internal state
  const displayText = value !== undefined ? value : text;

  const wordCount = displayText.trim() ? displayText.trim().split(/\s+/).length : 0;
  const byteSize = new TextEncoder().encode(displayText).length;
  const hasMinWords = wordCount >= 5;

  async function handleDetectLanguage() {
    if (!hasMinWords || detecting) return;
    setDetecting(true);
    setError('');
    try {
      const locale = await detectLanguage(displayText);
      setDetectedLang(locale);
      const name = localeToName(locale);
      onLanguageDetected(locale, name);
    } catch {
      setDetectedLang('');
      setError('Language detection failed. Please try again.');
    } finally {
      setDetecting(false);
    }
  }

  function handleChange(e: React.ChangeEvent<HTMLTextAreaElement>) {
    const val = e.target.value;
    const bytes = new TextEncoder().encode(val).length;

    if (bytes > MAX_BYTES) {
      setError('Text exceeds 5 MB limit');
      return;
    }

    setError('');
    setText(val);
    onTextChange(val);
    // Reset detected language when text changes
    if (detectedLang) {
      setDetectedLang('');
    }
  }

  return (
    <div className="text-input animate-in" style={{ animationDelay: '0.1s' }}>
      <label htmlFor="tts-text-input" className="text-input__label">
        Paste your text
      </label>

      <div className={`text-input__wrapper ${error ? 'text-input__wrapper--error' : ''} ${disabled ? 'text-input__wrapper--disabled' : ''}`}>
        <textarea
          ref={textareaRef}
          id="tts-text-input"
          className="text-input__textarea"
          placeholder="Paste your long text here…"
          value={displayText}
          onChange={handleChange}
          disabled={disabled}
          rows={10}
          spellCheck={false}
        />
      </div>

      <div className="text-input__meta">
        <div className="text-input__stats">
          <span className="text-input__stat">{wordCount.toLocaleString()} words</span>
          <span className="text-input__dot">·</span>
          <span className="text-input__stat">{formatBytes(byteSize)}</span>
          {detecting && (
            <>
              <span className="text-input__dot">·</span>
              <span className="text-input__lang" style={{ opacity: 0.6 }}>
                Detecting…
              </span>
            </>
          )}
          {!detecting && detectedLang && (
            <>
              <span className="text-input__dot">·</span>
              <span className="text-input__lang">
                {localeToName(detectedLang)}
              </span>
            </>
          )}
        </div>
        {error && <span className="text-input__error">{error}</span>}
      </div>

      {hasMinWords && !detectedLang && !disabled && (
        <div className="card__actions animate-in" style={{ marginTop: '1rem' }}>
          <button
            id="detect-language-button"
            className="btn-primary"
            onClick={handleDetectLanguage}
            disabled={detecting}
            type="button"
          >
            {detecting ? 'Detecting…' : 'Detect Language'}
          </button>
        </div>
      )}
    </div>
  );
}

function formatBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(2)} MB`;
}
