import './Header.css';

export default function Header() {
  return (
    <header className="header">
      <div className="header__inner">
        <div className="header__icon">
          <svg viewBox="0 0 32 32" fill="none" className="header__svg">
            <circle cx="16" cy="16" r="14" stroke="currentColor" strokeWidth="1.5" opacity="0.3" />
            <path d="M10 20V12l12 8V12" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" />
          </svg>
        </div>
        <div>
          <h1 className="header__title">Text to Speech</h1>
          <p className="header__subtitle">Convert long text into a downloadable MP3</p>
        </div>
      </div>
    </header>
  );
}
