/**
 * LeadDesk — script.js
 * Lightweight vanilla JS for client-side UX enhancements.
 */

// ── Delete confirmation ──────────────────────────────────────────────────────
/**
 * Called by the delete form's onsubmit handler.
 * Returns true (allow submit) or false (cancel submit).
 */
function confirmDelete(businessName) {
  return window.confirm(`Delete "${businessName}"?\n\nThis cannot be undone.`);
}


// ── Auto-dismiss flash messages ──────────────────────────────────────────────
document.addEventListener("DOMContentLoaded", function () {
  const alerts = document.querySelectorAll(".alert");
  alerts.forEach(function (alert) {
    // Fade out after 4 seconds
    setTimeout(function () {
      alert.style.transition = "opacity 0.5s";
      alert.style.opacity = "0";
      setTimeout(function () {
        alert.remove();
      }, 500);
    }, 4000);
  });
});


// ── Phone input helper ───────────────────────────────────────────────────────
// Show a small hint beneath the phone field as user types.
document.addEventListener("DOMContentLoaded", function () {
  const phoneInput = document.querySelector('input[name="phone"]');
  if (!phoneInput) return;

  const hint = document.createElement("span");
  hint.style.cssText = "font-size:0.72rem; color:#7a84a0; margin-top:2px;";
  phoneInput.parentNode.appendChild(hint);

  phoneInput.addEventListener("input", function () {
    const raw = phoneInput.value.trim().replace(/[\s\-]/g, "");
    if (raw.length === 0) {
      hint.textContent = "";
    } else if (!raw.startsWith("+")) {
      hint.textContent = "Will be saved as: +91" + raw;
    } else {
      hint.textContent = "Will be saved as: " + raw;
    }
  });
});
