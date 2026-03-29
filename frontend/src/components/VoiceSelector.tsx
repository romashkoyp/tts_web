import { useState, useEffect } from 'react';
import type { VoiceOption } from '../services/api';
import './VoiceSelector.css';

interface VoiceSelectorProps {
  voices: VoiceOption[];
  onSelect: (shortName: string) => void;
  disabled?: boolean;
}

export default function VoiceSelector({ voices, onSelect, disabled }: VoiceSelectorProps) {
  const [selected, setSelected] = useState('');
  const [visible, setVisible] = useState(false);

  useEffect(() => {
    // Trigger slide-in animation
    const timer = setTimeout(() => setVisible(true), 50);
    return () => clearTimeout(timer);
  }, []);

  useEffect(() => {
    if (voices.length > 0 && !selected) {
      onSelect(voices[0].shortName);
    }
  }, [voices, selected, onSelect]);

  const effectiveSelected = selected || voices[0]?.shortName || '';

  function handleChange(e: React.ChangeEvent<HTMLSelectElement>) {
    const val = e.target.value;
    setSelected(val);
    onSelect(val);
  }

  return (
    <div className={`voice-selector ${visible ? 'voice-selector--visible' : ''}`}>
      <label htmlFor="voice-select" className="voice-selector__label">
        Voice
      </label>
      <div className="voice-selector__control">
        <select
          id="voice-select"
          className="voice-selector__select"
          value={effectiveSelected}
          onChange={handleChange}
          disabled={disabled}
        >
          {voices.map(v => (
            <option key={v.shortName} value={v.shortName}>{v.displayName}</option>
          ))}
        </select>
        <span className="voice-selector__arrow">▾</span>
      </div>
    </div>
  );
}
