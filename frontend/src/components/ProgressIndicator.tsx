import { useState, useEffect } from 'react';
import './ProgressIndicator.css';

interface ProgressIndicatorProps {
  percent: number;
  status: string;
}

export default function ProgressIndicator({ percent, status }: ProgressIndicatorProps) {
  const [elapsed, setElapsed] = useState(0);

  useEffect(() => {
    const timer = setInterval(() => {
      setElapsed((prev) => prev + 1);
    }, 1000);
    return () => clearInterval(timer);
  }, []);

  const minutes = Math.floor(elapsed / 60);
  const seconds = elapsed % 60;
  const timeString = `${minutes.toString().padStart(2, '0')}:${seconds.toString().padStart(2, '0')}`;
  
  return (
    <div className="progress animate-in">
      <div className="progress__header">
        <span className="progress__status">{status}</span>
        <div style={{ display: 'flex', gap: '1rem', alignItems: 'center' }}>
          <span className="progress__time" style={{ fontSize: '0.8rem', color: 'var(--text-dim)', fontVariantNumeric: 'tabular-nums' }}>{timeString}</span>
          <span className="progress__percent">{Math.round(percent)}%</span>
        </div>
      </div>
      <div className="progress__track">
        <div
          className="progress__bar"
          style={{ width: `${percent}%` }}
        >
          <div className="progress__shimmer" />
        </div>
      </div>
    </div>
  );
}
