/**
 * Super Admin — user management.
 * Filters (role/status/search), paginated table, deactivate/activate,
 * reset-face, reset-password actions.
 */
document.addEventListener("DOMContentLoaded", () => {
  UI.bindModalClose();
  AdminUsers.init();
});

const AdminUsers = (() => {
  const state = { role: "", status: "", q: "", page: 1, pendingUserId: null };

  function init() {
    bindFilters();
    load(1);
    const btn = document.getElementById("reset-pw-confirm");
    if (btn) btn.addEventListener("click", confirmResetPw);
  }

  function bindFilters() {
    const role = document.getElementById("role-filter");
    const status = document.getElementById("status-filter");
    const q = document.getElementById("search-input");
    if (role) role.addEventListener("change", () => { state.role = role.value; load(1); });
    if (status) status.addEventListener("change", () => { state.status = status.value; load(1); });
    if (q) q.addEventListener("input", UI.debounce(() => { state.q = q.value.trim(); load(1); }, 350));
  }

  async function load(page) {
    const body = document.getElementById("users-body");
    body.innerHTML = "<tr><td colspan='6'><div class='skeleton-card'></div></td></tr>";
    const params = new URLSearchParams({ page: String(page) });
    if (state.role) params.set("role", state.role);
    if (state.status) params.set("status", state.status);
    if (state.q) params.set("q", state.q);

    try {
      const data = await Api.get("/admin/users/?" + params.toString());
      render(data.results || []);
      document.getElementById("empty-state").classList.toggle("hidden", (data.results || []).length > 0);
      UI.renderPagination(document.getElementById("pagination"), {
        page, totalPages: data.total_pages || 1, total: data.count,
        onPage: (p) => { state.page = p; load(p); },
      });
    } catch (err) {
      body.innerHTML = "";
      UI.toast(err.message, "error");
    }
  }

  function render(users) {
    const body = document.getElementById("users-body");
    if (!users.length) { body.innerHTML = ""; return; }
    body.innerHTML = users.map((u) => {
      const esc = UI.escapeHtml;
      const statusLabel = I18n.t((u.account_status || "active").toLowerCase());
      const statusClass = "badge-account-" + (u.account_status || "ACTIVE");
      const active = u.account_status === "APPROVED" || u.account_status === "ACTIVE";

      let actions = "";
      if (!u.is_super_admin) {
        if (active) {
          actions += '<button class="btn btn-outline btn-sm" data-deactivate="' + u.id + '" data-i18n="deactivate">Deactivate</button>';
        } else if (u.account_status === "SUSPENDED" || u.account_status === "DEACTIVATED") {
          actions += '<button class="btn btn-primary btn-sm" data-activate="' + u.id + '" data-i18n="activate">Activate</button>';
        }
        if (u.face_registered) {
          actions += '<button class="btn btn-danger-ghost btn-sm" data-reset-face="' + u.id + '" data-i18n="reset_face">Reset Face</button>';
        }
        actions += '<button class="btn btn-ghost btn-sm" data-reset-pw="' + u.id + '" data-i18n="reset_password">Reset Password</button>';
      }

      return (
        "<tr>" +
          "<td><b>" + esc(u.full_name) + "</b><br><span class='muted'>" + esc(u.employee_id || "") + "</span></td>" +
          "<td>" + esc(u.email) + "</td>" +
          "<td>" + I18n.t("role_" + u.role) + "</td>" +
          '<td><span class="badge ' + statusClass + '">' + statusLabel + "</span></td>" +
          '<td>' + (u.face_registered
            ? '<span class="badge badge-verified">' + I18n.t("face_registered_yes") + "</span>"
            : '<span class="badge badge-rejected">' + I18n.t("face_registered_no") + "</span>") + "</td>" +
          '<td class="actions-cell">' + actions + "</td>" +
        "</tr>"
      );
    }).join("");

    body.querySelectorAll("[data-deactivate]").forEach((b) =>
      b.addEventListener("click", () => deactivate(b.dataset.deactivate)));
    body.querySelectorAll("[data-activate]").forEach((b) =>
      b.addEventListener("click", () => activate(b.dataset.activate)));
    body.querySelectorAll("[data-reset-face]").forEach((b) =>
      b.addEventListener("click", () => resetFace(b.dataset.resetFace)));
    body.querySelectorAll("[data-reset-pw]").forEach((b) =>
      b.addEventListener("click", () => openResetPw(b.dataset.resetPw)));
  }

  async function deactivate(userId) {
    if (!window.confirm(I18n.t("confirm_action") + " (" + I18n.t("deactivate") + ")")) return;
    await act("/admin/users/" + userId + "/deactivate/", { suspended: true });
  }

  async function activate(userId) {
    if (!window.confirm(I18n.t("confirm_action") + " (" + I18n.t("activate") + ")")) return;
    await act("/admin/users/" + userId + "/activate/", {});
  }

  async function resetFace(userId) {
    if (!window.confirm(I18n.t("confirm_action") + " (" + I18n.t("reset_face") + ")")) return;
    await act("/admin/users/" + userId + "/reset-face/", {});
  }

  async function act(path, body) {
    UI.showLoading();
    try {
      const data = await Api.patch(path, body);
      UI.hideLoading();
      UI.toast(data.message || "Done.", "success");
      load(state.page);
    } catch (err) {
      UI.hideLoading();
      UI.toast(err.message, "error");
    }
  }

  function openResetPw(userId) {
    state.pendingUserId = userId;
    document.getElementById("temp-password").value = "";
    document.getElementById("pw-error").textContent = "";
    UI.openModal("reset-pw-modal");
  }

  async function confirmResetPw() {
    const pw = document.getElementById("temp-password").value.trim();
    const errorEl = document.getElementById("pw-error");
    if (pw.length < 8) {
      errorEl.textContent = I18n.t("enter_temp_password").replace(" (min 8 chars)", "");
      return;
    }
    UI.showLoading();
    try {
      const data = await Api.patch("/admin/users/" + state.pendingUserId + "/reset-password/", { temporary_password: pw });
      UI.hideLoading();
      UI.toast(data.message || "Password reset.", "success");
      UI.closeModal("reset-pw-modal");
      load(state.page);
    } catch (err) {
      UI.hideLoading();
      errorEl.textContent = err.message;
    }
  }

  return { init };
})();
