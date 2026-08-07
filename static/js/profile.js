/**
 * Profile page — loads the current user, allows updating full_name/phone
 * and changing the password.
 */
document.addEventListener("DOMContentLoaded", () => {
  Profile.init();
});

const Profile = (() => {
  async function init() {
    await loadUser();
    document.getElementById("profile-form").addEventListener("submit", updateProfile);
    document.getElementById("password-form").addEventListener("submit", changePassword);
  }

  async function loadUser() {
    try {
      const data = await Api.get("/auth/me/");
      const u = data.user;
      Api.setUser(u); // keep local storage in sync
      const nameEl = document.getElementById("full_name");
      const phoneEl = document.getElementById("phone");
      const emailEl = document.getElementById("email");
      if (nameEl) nameEl.value = u.full_name || "";
      if (phoneEl) phoneEl.value = u.phone || "";
      if (emailEl) emailEl.value = u.email || "";

      const avatar = document.getElementById("profile-avatar");
      const name = document.getElementById("profile-name");
      const email = document.getElementById("profile-email");
      const role = document.getElementById("profile-role");
      if (avatar) avatar.textContent = UI.initials(u.full_name);
      if (name) name.textContent = u.full_name;
      if (email) email.textContent = u.email;
      if (role) role.textContent = I18n.t("role_" + u.role);

      const status = document.getElementById("profile-status");
      if (status && u.account_status) {
        const label = I18n.t((u.account_status || "active").toLowerCase()) || u.account_status;
        const cls = { APPROVED: "badge-verified", ACTIVE: "badge-verified", PENDING: "badge-pending", REJECTED: "badge-rejected", SUSPENDED: "badge-info", DEACTIVATED: "badge-rejected" };
        status.textContent = label;
        status.className = "badge " + (cls[u.account_status] || "badge-info");
      }
      const username = document.getElementById("profile-username");
      if (username) username.textContent = u.username ? "@" + u.username : "";
    } catch (err) {
      UI.toast(err.message, "error");
    }
  }

  async function updateProfile(e) {
    e.preventDefault();
    const btn = e.target.querySelector("button[type=submit]");
    btn.disabled = true;
    UI.showLoading();
    try {
      const data = await Api.put("/auth/profile/", {
        full_name: document.getElementById("full_name").value.trim(),
        phone: document.getElementById("phone").value.trim(),
      });
      Api.setUser(data.user);
      UI.hideLoading();
      UI.toast(I18n.t("profile_updated"), "success");
      loadUser();
    } catch (err) {
      UI.hideLoading();
      UI.toast(err.message, "error");
    } finally {
      btn.disabled = false;
    }
  }

  async function changePassword(e) {
    e.preventDefault();
    const form = e.target;
    const btn = form.querySelector("button[type=submit]");
    const currentPassword = document.getElementById("current_password").value;
    const newPassword = document.getElementById("new_password").value;
    const confirmPassword = document.getElementById("confirm_password").value;

    document.querySelectorAll(".field-error").forEach((el) => (el.textContent = ""));
    if (newPassword !== confirmPassword) {
      document.querySelector('[data-error-for="confirm_password"]').textContent = "Passwords do not match.";
      return;
    }
    btn.disabled = true;
    UI.showLoading();
    try {
      await Api.post("/auth/change-password/", { current_password: currentPassword, new_password: newPassword, confirm_password: confirmPassword });
      UI.hideLoading();
      UI.toast(I18n.t("password_updated"), "success");
      form.reset();
    } catch (err) {
      UI.hideLoading();
      UI.toast(err.message, "error");
    } finally {
      btn.disabled = false;
    }
  }

  return { init };
})();
