/* Shared progressive accessibility enhancements. */
(function () {
  "use strict";
  function applyReducedMotion(enabled) {
    document.documentElement.classList.toggle("manual-reduced-motion", !!enabled);
    var toggle = document.getElementById("reducedMotionToggle");
    if (toggle) toggle.checked = !!enabled;
  }

  window.toggleReducedMotion = function () {
    var toggle = document.getElementById("reducedMotionToggle");
    var enabled = !!(toggle && toggle.checked);
    applyReducedMotion(enabled);
    localStorage.setItem("reducedMotionPreference", enabled ? "enabled" : "disabled");
    fetch("/api/preferences", {
      method: "POST",
      headers: {"Content-Type": "application/json"},
      body: JSON.stringify({reducedMotionPreference: enabled ? "enabled" : "disabled"})
    }).catch(function () {});
  };

  function initializeReducedMotion() {
    var local = localStorage.getItem("reducedMotionPreference") === "enabled";
    applyReducedMotion(local);
    fetch("/api/preferences").then(function (response) {
      return response.ok ? response.json() : {};
    }).then(function (prefs) {
      if (prefs.reducedMotionPreference) {
        applyReducedMotion(prefs.reducedMotionPreference === "enabled");
      }
    }).catch(function () {});
  }

  function enhance() {
    initializeReducedMotion();
    document.querySelectorAll(".marquee-toggle").forEach(function (control) {
      control.setAttribute("role", "button");
      control.setAttribute("tabindex", "0");
      control.setAttribute("aria-label", control.title || "Toggle marquee");
      control.addEventListener("keydown", function (event) {
        if (event.key === "Enter" || event.key === " ") {
          event.preventDefault();
          control.click();
        }
      });
    });
    var labels = {
      "side-panel-toggle": "Open settings"
    };
    document.querySelectorAll("[onclick]").forEach(function (control) {
      var id = control.id || "";
      if (!control.getAttribute("aria-label") && labels[id]) {
        control.setAttribute("role", "button");
        control.setAttribute("tabindex", "0");
        control.setAttribute("aria-label", labels[id]);
        control.addEventListener("keydown", function (event) {
          if (event.key === "Enter" || event.key === " ") {
            event.preventDefault();
            control.click();
          }
        });
      }
    });
    document.querySelectorAll('.badge[data-type="audio"], .badge[data-type="subtitle"]').forEach(function (badge) {
      var languages = (badge.dataset.all || "").split(",").map(function (value) {
        return value.trim();
      }).filter(Boolean);
      if (languages.length < 2) return;
      badge.classList.add("expandable-language");
      badge.setAttribute("role", "button");
      badge.setAttribute("tabindex", "0");
      badge.setAttribute("aria-label", "Expand " + badge.dataset.type + " languages");
      badge.setAttribute("aria-expanded", badge.classList.contains("expanded") ? "true" : "false");
      badge.addEventListener("keydown", function (event) {
        if (event.key === "Enter" || event.key === " ") {
          event.preventDefault();
          badge.click();
        }
      });
      badge.addEventListener("click", function () {
        badge.setAttribute("aria-expanded", badge.classList.contains("expanded") ? "true" : "false");
      });
    });
    document.querySelectorAll("img.poster, img.show-poster, img.season-poster").forEach(function (poster) {
      if (poster.classList.contains("no-image")) return;
      poster.setAttribute("role", "button");
      poster.setAttribute("tabindex", "0");
      poster.setAttribute("aria-label", "Open larger artwork");
      poster.addEventListener("keydown", function (event) {
        if (event.key === "Enter" || event.key === " ") {
          event.preventDefault();
          poster.click();
        }
      });
    });
    document.querySelectorAll("img").forEach(function (image) {
      if (!image.hasAttribute("alt")) image.setAttribute("alt", "");
    });
  }
  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", enhance);
  } else {
    enhance();
  }
}());
