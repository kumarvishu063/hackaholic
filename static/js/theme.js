/**
 * Theme management — light / dark mode persisted in localStorage.
 */
const Theme = (() => {
  const KEY = "jst_theme";

  function current() {
    return localStorage.getItem(KEY) || "light";
  }

  function apply(theme) {
    document.documentElement.setAttribute("data-theme", theme);
    localStorage.setItem(KEY, theme);
    // Swap the sun/moon glyph on every theme toggle button.
    const glyph = theme === "dark" ? "sun" : "moon";
    document.querySelectorAll("#theme-toggle").forEach((btn) => {
      const use = btn.querySelector("use");
      if (use) use.setAttribute("href", "/static/icons.svg#icon-" + glyph);
    });
    // Sync the settings page picker.
    document.querySelectorAll("[data-theme-option]").forEach((opt) => {
      opt.classList.toggle("is-active", opt.dataset.themeOption === theme);
    });
    document.dispatchEvent(new CustomEvent("theme:change", { detail: { theme } }));
  }

  function toggle() {
    apply(current() === "dark" ? "light" : "dark");
  }

  function init() {
    document.querySelectorAll("#theme-toggle").forEach((btn) => btn.addEventListener("click", toggle));
    document.querySelectorAll("[data-theme-option]").forEach((opt) => {
      opt.addEventListener("click", () => apply(opt.dataset.themeOption));
    });
    apply(current());
  }

  return { current, apply, toggle, init };
})();
