/**
 * Settings page.
 *
 * Theme selection and language are handled globally by Theme.init() and
 * I18n.init() (both wired in common.js); this file only adds the account
 * summary that needs a network call.
 */
document.addEventListener("DOMContentLoaded", () => {
  Settings.init();
});

const Settings = (() => {
  async function init() {
    try {
      const data = await Api.get("/auth/me/");
      const accountEl = document.getElementById("settings-account");
      const roleEl = document.getElementById("settings-role");
      if (accountEl) accountEl.textContent = data.user.full_name + " · " + data.user.email;
      if (roleEl) roleEl.textContent = I18n.t("role_" + data.user.role);
    } catch (err) {
      console.warn("Could not load account info:", err.message);
    }
  }

  return { init };
})();
