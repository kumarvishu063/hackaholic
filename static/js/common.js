/**
 * Behaviours shared by every page: sidebar, user chip, logout, language
 * selector wiring, scroll-to links, copy buttons and password toggles.
 */
document.addEventListener("DOMContentLoaded", () => {
  Theme.init();
  I18n.init();
  document.addEventListener("i18n:change", Common.initUserChip);
  Common.initSidebar();
  Common.initUserChip();
  Common.initLogout();
  Common.initScrollLinks();
  Common.initCopyButtons();
  Common.initTogglePassword();
  Common.initNotifications();
  Common.protectAdminRoutes();
});

const Common = (() => {

  // ------------------------------------------------ role → dashboard path
  function dashboardPath(role) {
    const map = {
      citizen: "/dashboard/citizen/",
      validator: "/dashboard/validator/",
      official: "/dashboard/official/",
      super_admin: "/dashboard/admin/",
    };
    return map[role] || "/login/";
  }

  // ------------------------------------------------------------- sidebar
  function initSidebar() {
    const sidebar = document.getElementById("sidebar");
    const openBtn = document.getElementById("sidebar-open");
    const closeBtn = document.getElementById("sidebar-close");
    const scrim = document.getElementById("sidebar-scrim");
    if (!sidebar) return;

    const setOpen = (open) => sidebar.classList.toggle("open", open);
    if (openBtn) openBtn.addEventListener("click", () => setOpen(true));
    if (closeBtn) closeBtn.addEventListener("click", () => setOpen(false));
    if (scrim) scrim.addEventListener("click", () => setOpen(false));

    // Resolve the dashboard link and role shortcuts from the stored user.
    const user = Api.getUser();
    if (user && user.role) {
      const dash = document.getElementById("sidebar-dashboard-link");
      if (dash) dash.setAttribute("href", dashboardPath(user.role));
      document.querySelectorAll("[data-role]").forEach((el) => {
        el.style.display = el.dataset.role === user.role ? "" : "none";
      });
    } else {
      // Not authenticated → bounce to login (client-side route protection).
      const protectedPage = !["/", "/login/", "/register/"].includes(window.location.pathname);
      if (protectedPage && (window.location.pathname.startsWith("/dashboard") ||
                            window.location.pathname.startsWith("/admin/"))) {
        window.location.href = "/login/";
      }
    }
  }

  // ------------------------------------------------------------ user chip
  function initUserChip() {
    const user = Api.getUser();
    const nameEl = document.getElementById("user-name");
    const roleEl = document.getElementById("user-role");
    const avatarEl = document.getElementById("user-avatar");
    if (nameEl && user) nameEl.textContent = user.full_name || user.email;
    if (avatarEl) avatarEl.textContent = UI.initials((user && user.full_name) || "?");
    if (roleEl) roleEl.textContent = I18n.t("role_" + (user ? user.role : "citizen"));

    // Role badge on the settings page.
    const settingsRole = document.getElementById("settings-role");
    const settingsAccount = document.getElementById("settings-account");
    if (settingsRole && user) settingsRole.textContent = (user.full_name || "") + " · " + user.email;
    if (settingsAccount && user) settingsAccount.textContent = user.email;

    // Profile page fields.
    const profileAvatar = document.getElementById("profile-avatar");
    const profileName = document.getElementById("profile-name");
    const profileEmail = document.getElementById("profile-email");
    const profileRole = document.getElementById("profile-role");
    if (profileAvatar) profileAvatar.textContent = UI.initials(user ? user.full_name : "?");
    if (profileName) profileName.textContent = user ? user.full_name : "—";
    if (profileEmail) profileEmail.textContent = user ? user.email : "—";
    if (profileRole) profileRole.textContent = I18n.t("role_" + (user ? user.role : "citizen"));
  }

  // --------------------------------------------------------------- logout
  function initLogout() {
    const doLogout = (e) => {
      e.preventDefault();
      Api.logout();
      UI.toast(I18n.t("logged_out"), "info");
      setTimeout(() => { window.location.href = "/login/"; }, 350);
    };
    document.querySelectorAll("#logout-btn, #settings-logout").forEach((btn) => {
      btn.addEventListener("click", doLogout);
    });
  }

  // ------------------------------------------------------ scroll shortcuts
  function initScrollLinks() {
    document.querySelectorAll("[data-scroll]").forEach((el) => {
      el.addEventListener("click", () => {
        const target = document.querySelector(el.dataset.scroll);
        if (target) {
          target.scrollIntoView({ behavior: "smooth", block: "start" });
          const sidebar = document.getElementById("sidebar");
          if (sidebar) sidebar.classList.remove("open");
        }
      });
    });
  }

  // ------------------------------------------------------- copy-to-clipboard
  function initCopyButtons() {
    document.querySelectorAll("[data-copy]").forEach((btn) => {
      btn.addEventListener("click", async () => {
        const el = document.querySelector(btn.dataset.copy);
        const text = el ? el.textContent : btn.dataset.copy;
        try {
          await navigator.clipboard.writeText(text.trim());
        } catch {
          const ta = document.createElement("textarea");
          ta.value = text.trim();
          document.body.appendChild(ta);
          ta.select();
          document.execCommand("copy");
          ta.remove();
        }
        UI.toast(I18n.t("copied"), "success", 1800);
      });
    });
  }

  // ------------------------------------------------------- password toggle
  function initTogglePassword() {
    document.querySelectorAll("[data-toggle-password]").forEach((btn) => {
      btn.addEventListener("click", () => {
        const input = btn.closest(".input-wrap").querySelector("input");
        if (!input) return;
        input.type = input.type === "password" ? "text" : "password";
        btn.querySelector("use").setAttribute("href",
          "/static/icons.svg#icon-" + (input.type === "password" ? "eye" : "eye"));
      });
    });
  }

  // ------------------------------------------------------- admin route guard
  function protectAdminRoutes() {
    const path = window.location.pathname;
    const isAdminPage = path.startsWith("/admin/") || path === "/dashboard/admin/";
    if (!isAdminPage) return;
    const user = Api.getUser();
    if (!user || user.role !== "super_admin") {
      window.location.href = "/login/";
    }
  }

  // ------------------------------------------------------- notifications
  function initNotifications() {
    const btn = document.getElementById("notif-btn");
    const dropdown = document.getElementById("notif-dropdown");
    const badge = document.getElementById("notif-badge");
    const list = document.getElementById("notif-list");
    const markAll = document.getElementById("notif-mark-read");
    if (!btn || !dropdown) return;

    let open = false;

    async function load() {
      try {
        const data = await Api.get("/auth/notifications/");
        render(data.notifications || [], data.unread_count || 0);
      } catch (err) { /* ignore — not authenticated or offline */ }
    }

    function render(items, unread) {
      if (badge) {
        badge.classList.toggle("hidden", !unread);
        badge.textContent = unread > 9 ? "9+" : String(unread);
      }
      if (!list) return;
      if (!items.length) {
        list.innerHTML = '<div class="notif-empty">' + I18n.t("no_notifications") + "</div>";
        return;
      }
      list.innerHTML = items.map((n) =>
        '<div class="notif-item' + (n.is_read ? "" : " unread") + '" data-id="' + n.id + '">' +
          "<strong>" + UI.escapeHtml(n.title || "") + "</strong>" +
          "<p>" + UI.escapeHtml(n.message || "") + "</p>" +
          "<time>" + UI.timeAgo(n.created_at) + "</time>" +
        "</div>"
      ).join("");
      list.querySelectorAll(".notif-item").forEach((el) => {
        el.addEventListener("click", async () => {
          await Api.post("/auth/notifications/read/", { notification_id: el.dataset.id });
          load();
        });
      });
    }

    btn.addEventListener("click", (e) => {
      e.stopPropagation();
      open = !open;
      dropdown.classList.toggle("hidden", !open);
      if (open) load();
    });
    document.addEventListener("click", (e) => {
      if (open && !dropdown.contains(e.target) && e.target !== btn) {
        dropdown.classList.add("hidden");
        open = false;
      }
    });
    if (markAll) {
      markAll.addEventListener("click", async () => {
        await Api.post("/auth/notifications/read/", {});
        load();
      });
    }
  }

  return {
    initSidebar, initUserChip, initLogout, initScrollLinks, initCopyButtons,
    initTogglePassword, initNotifications, protectAdminRoutes, dashboardPath,
  };
})();
