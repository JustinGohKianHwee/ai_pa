// Runs before paint to set the theme class on <html>, avoiding a flash of the
// wrong theme. Dark is the default (no class); 'light' is added when stored or
// when the OS prefers light and nothing is stored.
export function ThemeScript() {
  const js = `(function(){try{var t=localStorage.getItem('theme');var prefersLight=window.matchMedia('(prefers-color-scheme: light)').matches;if(t==='light'||(!t&&prefersLight)){document.documentElement.classList.add('light');}}catch(e){}})();`;
  return <script dangerouslySetInnerHTML={{ __html: js }} />;
}
