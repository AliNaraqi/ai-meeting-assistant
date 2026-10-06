/** Apply stored or system theme before paint (sync, no module). */
(function bootTheme() {
  try {
    const stored = localStorage.getItem("ama_theme");
    if (stored === "light" || stored === "dark") {
      document.documentElement.dataset.theme = stored;
    }
  } catch {
    /* ignore */
  }
})();
