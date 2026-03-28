import './Footer.css';

export default function Footer() {
  return (
    <footer className="footer">
      <span className="footer__text">
        Powered by{' '}
        <a
          href="https://github.com/rany2/edge-tts"
          target="_blank"
          rel="noopener noreferrer"
          className="footer__link"
        >
          edge-tts
        </a>
      </span>
    </footer>
  );
}
