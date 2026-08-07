/* Shared progressive accessibility enhancements + lyrics/cast helpers. */
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

  function enhanceControls() {
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

  function lazyLoadCastThumbs() {
    var avatars = document.querySelectorAll(".cast-avatar[data-thumb]");
    if (!avatars.length) return;
    var queue = Array.prototype.slice.call(avatars);
    var index = 0;

    function next() {
      if (index >= queue.length) return;
      var avatar = queue[index++];
      var path = avatar.getAttribute("data-thumb") || "";
      if (!path) {
        next();
        return;
      }
      fetch("/api/cast-thumb", {
        method: "POST",
        headers: {"Content-Type": "application/json"},
        body: JSON.stringify({path: path})
      }).then(function (response) {
        return response.ok ? response.json() : null;
      }).then(function (data) {
        if (data && data.url) {
          var img = new Image();
          img.onload = function () {
            avatar.style.backgroundImage = "url('" + data.url + "')";
            avatar.classList.add("loaded");
          };
          img.src = data.url;
        }
      }).catch(function () {}).finally(function () {
        setTimeout(next, 80);
      });
    }
    setTimeout(next, 250);
  }

  var fanartHydrateState = {
    inFlight: false,
    currentIndex: 0
  };

  window.ensureFanartSlideshow = function () {
    var container = document.querySelector(".fanart-container");
    if (!container) return;
    var slides = container.querySelectorAll(".fanart-slide");
    if (slides.length < 2) return;
    if (typeof window.cycleFanarts !== "function") {
      // Templates may not have installed cycle yet; install a minimal cycler.
      fanartHydrateState.currentIndex = 0;
      for (var i = 0; i < slides.length; i++) {
        if (slides[i].classList.contains("active")) {
          fanartHydrateState.currentIndex = i;
          break;
        }
      }
      window.cycleFanarts = function () {
        var all = container.querySelectorAll(".fanart-slide");
        if (all.length < 2) return;
        var cur = all[fanartHydrateState.currentIndex % all.length];
        if (cur) {
          cur.classList.remove("active");
          cur.classList.add("fade-out");
        }
        fanartHydrateState.currentIndex = (fanartHydrateState.currentIndex + 1) % all.length;
        var next = all[fanartHydrateState.currentIndex];
        if (next) {
          next.classList.remove("fade-out");
          next.classList.add("active");
        }
      };
    }
    if (!window._fanartSlideshowStarted) {
      var intervalSec = parseInt(localStorage.getItem("fanartInterval") || "20", 10);
      if (!intervalSec || intervalSec < 5) intervalSec = 20;
      window._fanartSlideshowTimer = setInterval(window.cycleFanarts, intervalSec * 1000);
      window._fanartSlideshowStarted = true;
    }
  };

  window.hydrateFanartSlideshow = function (payload) {
    var boot = payload;
    if (!boot) {
      var el = document.getElementById("fanart-pending");
      if (!el || !el.textContent) return;
      try {
        boot = JSON.parse(el.textContent);
      } catch (err) {
        return;
      }
    }
    var items = (boot && boot.items) || [];
    var sessionId = (boot && boot.session_id) || "";
    if (!items.length || !sessionId || fanartHydrateState.inFlight) return;
    fanartHydrateState.inFlight = true;
    var container = document.querySelector(".fanart-container");
    if (!container) {
      fanartHydrateState.inFlight = false;
      return;
    }
    var index = 0;
    var inflight = 0;
    var maxParallel = 2;

    function pump() {
      while (inflight < maxParallel && index < items.length) {
        (function (item) {
          inflight += 1;
          fetch("/api/fanart", {
            method: "POST",
            headers: {"Content-Type": "application/json"},
            body: JSON.stringify({
              path: item.path,
              key: item.key,
              session_id: sessionId
            })
          }).then(function (response) {
            return response.ok ? response.json() : null;
          }).then(function (data) {
            if (data && data.url) {
              var slide = document.createElement("div");
              slide.className = "fanart-slide";
              slide.style.backgroundImage = "url('" + data.url + "')";
              container.appendChild(slide);
              if (typeof window.ensureFanartSlideshow === "function") {
                window.ensureFanartSlideshow();
              }
            }
          }).catch(function () {}).finally(function () {
            inflight -= 1;
            if (index >= items.length && inflight === 0) {
              fanartHydrateState.inFlight = false;
            } else {
              pump();
            }
          });
        })(items[index++]);
      }
      if (index >= items.length && inflight === 0) {
        fanartHydrateState.inFlight = false;
      }
    }
    setTimeout(pump, 200);
  };

  function resetFanartPendingBootstrap(boot) {
    var el = document.getElementById("fanart-pending");
    if (!el) {
      el = document.createElement("script");
      el.type = "application/json";
      el.id = "fanart-pending";
      document.body.appendChild(el);
    }
    el.textContent = JSON.stringify(boot || {session_id: "", items: []});
  }

  window.replaceFanartSlideshow = function (urls, pendingBoot) {
    var container = document.querySelector(".fanart-container");
    if (!container) return;
    if (window._fanartSlideshowTimer) {
      clearInterval(window._fanartSlideshowTimer);
      window._fanartSlideshowTimer = null;
    }
    window._fanartSlideshowStarted = false;
    container.innerHTML = "";
    (urls || []).forEach(function (url, i) {
      var slide = document.createElement("div");
      slide.className = "fanart-slide" + (i === 0 ? " active" : "");
      slide.style.backgroundImage = "url('" + url + "')";
      container.appendChild(slide);
    });
    if (pendingBoot) {
      resetFanartPendingBootstrap(pendingBoot);
      window.hydrateFanartSlideshow(pendingBoot);
    } else {
      resetFanartPendingBootstrap({session_id: "", items: []});
      window.ensureFanartSlideshow();
    }
  };

  var lyricsState = {
    lines: [],
    synced: false,
    activeIndex: -1,
    elements: [],
    loaded: false,
    requestId: 0
  };

  function playbackElapsed() {
    if (typeof window.getNowPlayingElapsed === "function") {
      return Number(window.getNowPlayingElapsed()) || 0;
    }
    return 0;
  }

  function playbackPaused() {
    if (typeof window.getNowPlayingPaused === "function") {
      return !!window.getNowPlayingPaused();
    }
    return false;
  }

  function setInfoPanel(panel) {
    var root = document.getElementById("music-info-panel");
    if (!root) return;
    root.querySelectorAll(".info-panel-tab").forEach(function (tab) {
      var selected = tab.getAttribute("data-panel") === panel;
      tab.setAttribute("aria-selected", selected ? "true" : "false");
    });
    root.querySelectorAll(".info-panel-pane").forEach(function (pane) {
      var match = pane.id === "panel-" + panel;
      if (match) pane.removeAttribute("hidden");
      else pane.setAttribute("hidden", "");
    });
    localStorage.setItem("lyricsPanelPreference", panel);
    fetch("/api/preferences", {
      method: "POST",
      headers: {"Content-Type": "application/json"},
      body: JSON.stringify({lyricsPanelPreference: panel})
    }).catch(function () {});
  }

  function renderLyricLines(lines, synced) {
    var inner = document.getElementById("lyrics-inner");
    var empty = document.getElementById("lyrics-empty");
    var panel = document.getElementById("lyrics-panel");
    if (!inner || !empty || !panel) return;
    inner.innerHTML = "";
    inner.style.transform = "";
    lyricsState.elements = [];
    lyricsState.activeIndex = -1;
    lyricsState.lines = lines || [];
    lyricsState.synced = !!synced;
    panel.classList.toggle("unsynced", !synced);

    if (!lyricsState.lines.length) {
      empty.textContent = "No lyrics found for this track";
      empty.classList.add("visible");
      return;
    }
    empty.classList.remove("visible");
    lyricsState.lines.forEach(function (line) {
      var el = document.createElement("div");
      var text = line && line.text != null ? String(line.text) : "";
      el.className = "lyric-line" + (text ? "" : " empty");
      el.textContent = text;
      inner.appendChild(el);
      lyricsState.elements.push(el);
    });
  }

  function tickLyrics() {
    if (!lyricsState.synced || !lyricsState.lines.length) return;
    if (playbackPaused()) return;
    var elapsed = playbackElapsed();
    var current = -1;
    for (var i = 0; i < lyricsState.lines.length; i++) {
      var t = lyricsState.lines[i].time;
      if (t == null) continue;
      if (t <= elapsed) current = i;
      else break;
    }
    if (current === lyricsState.activeIndex) return;
    lyricsState.activeIndex = current;
    lyricsState.elements.forEach(function (el, i) {
      el.classList.remove("active", "near");
      var dist = i - current;
      if (dist === 0) el.classList.add("active");
      else if (dist >= -1 && dist <= 2) el.classList.add("near");
    });
    var active = lyricsState.elements[current];
    var container = document.getElementById("lyrics-panel");
    var inner = document.getElementById("lyrics-inner");
    if (active && container && inner) {
      var target = active.offsetTop - container.offsetHeight * 0.35 + active.offsetHeight / 2;
      inner.style.transform = "translateY(" + (-target) + "px)";
    }
  }

  function updateLyricsBootstrap(patch) {
    var bootEl = document.getElementById("lyrics-bootstrap");
    if (!bootEl) return null;
    var boot = {};
    try {
      boot = JSON.parse(bootEl.textContent || "{}");
    } catch (e) {
      boot = {};
    }
    if (patch && typeof patch === "object") {
      Object.keys(patch).forEach(function (key) {
        boot[key] = patch[key];
      });
      bootEl.textContent = JSON.stringify(boot);
    }
    return boot;
  }

  function loadLyrics(bootstrapOverride) {
    var bootEl = document.getElementById("lyrics-bootstrap");
    if (!bootEl && !bootstrapOverride) return;
    var boot = bootstrapOverride || null;
    if (!boot) {
      try {
        boot = JSON.parse(bootEl.textContent || "{}");
      } catch (e) {
        boot = {};
      }
    } else {
      updateLyricsBootstrap(boot);
    }
    var empty = document.getElementById("lyrics-empty");
    if (empty) {
      empty.textContent = "Loading lyrics…";
      empty.classList.add("visible");
    }
    var requestId = ++lyricsState.requestId;
    lyricsState.loaded = false;
    fetch("/api/lyrics", {
      method: "POST",
      headers: {"Content-Type": "application/json"},
      body: JSON.stringify({
        artist: boot.artist || "",
        title: boot.title || "",
        album: boot.album || "",
        duration: boot.duration,
        kodi_lyrics: boot.kodi_lyrics || ""
      })
    }).then(function (response) {
      return response.ok ? response.json() : null;
    }).then(function (data) {
      if (requestId !== lyricsState.requestId) return; // stale response from prior track
      lyricsState.loaded = true;
      if (!data) {
        renderLyricLines([], false);
        return;
      }
      if (data.source) {
        console.debug("[lyrics] source=" + data.source + (data.synced ? " synced" : " plain"));
      }
      renderLyricLines(data.lines || [], !!data.synced);
    }).catch(function () {
      if (requestId !== lyricsState.requestId) return;
      renderLyricLines([], false);
    });
  }

  /** Soft-update hook: refresh lyrics when the track changes in place. */
  window.reloadNowPlayingLyrics = function (lyricsInfo) {
    if (!document.getElementById("lyrics-bootstrap") && !document.getElementById("lyrics-panel")) {
      return;
    }
    var patch = lyricsInfo && typeof lyricsInfo === "object" ? lyricsInfo : null;
    if (patch) {
      loadLyrics({
        artist: patch.artist || "",
        title: patch.title || "",
        album: patch.album || "",
        duration: patch.duration,
        kodi_lyrics: patch.kodi_lyrics || ""
      });
    } else {
      loadLyrics();
    }
  };

  function _panelTextLooksEmpty(el) {
    if (!el) return true;
    var text = (el.textContent || "").trim();
    if (!text) return true;
    if (el.classList && el.classList.contains("info-panel-empty")) return true;
    if (/^No album description available/i.test(text)) return true;
    if (/^No artist biography available/i.test(text)) return true;
    return false;
  }

  function applyMusicMetaResult(data) {
    if (!data) return;
    if (data.album_description) {
      var albumWrap = document.getElementById("soft-album-description");
      var albumText = document.getElementById("soft-album-description-text");
      if (albumWrap && albumText) {
        albumText.textContent = data.album_description;
        albumText.classList.remove("info-panel-empty");
        albumWrap.style.display = "";
      }
    }
    if (data.artist_bio) {
      var bioWrap = document.getElementById("soft-artist-bio");
      var bioText = document.getElementById("soft-artist-bio-text");
      if (bioWrap && bioText) {
        bioText.textContent = data.artist_bio;
        bioText.classList.remove("info-panel-empty");
        bioWrap.style.display = "";
        if (data.artist_born) {
          var bornEl = document.getElementById("soft-artist-born");
          if (bornEl) {
            bornEl.innerHTML = "<strong>Born:</strong> " + data.artist_born;
          } else {
            var p = document.createElement("p");
            p.id = "soft-artist-born";
            p.innerHTML = "<strong>Born:</strong> " + data.artist_born;
            bioWrap.insertBefore(p, bioText);
          }
        }
      }
    }
  }

  var musicMetaRequestId = 0;

  function loadMusicMetaFallback(override) {
    if (!document.getElementById("music-info-panel")) return;
    var boot = override || null;
    if (!boot) {
      var bootEl = document.getElementById("music-meta-bootstrap");
      if (bootEl) {
        try {
          boot = JSON.parse(bootEl.textContent || "{}");
        } catch (e) {
          boot = {};
        }
      } else {
        boot = {};
      }
    }
    var needAlbum = boot.need_album;
    var needArtist = boot.need_artist;
    if (needAlbum == null) needAlbum = _panelTextLooksEmpty(document.getElementById("soft-album-description-text"));
    if (needArtist == null) needArtist = _panelTextLooksEmpty(document.getElementById("soft-artist-bio-text"));
    if (!needAlbum && !needArtist) return;

    var identity = window.SOFT_IDENTITY || {};
    var requestId = ++musicMetaRequestId;
    fetch("/api/music-meta", {
      method: "POST",
      headers: {"Content-Type": "application/json"},
      body: JSON.stringify({
        artist: boot.artist || "",
        album: boot.album || "",
        album_id: boot.album_id != null ? boot.album_id : identity.album_id,
        artist_id: boot.artist_id != null ? boot.artist_id : identity.artist_id,
        need_album: !!needAlbum,
        need_artist: !!needArtist
      })
    }).then(function (response) {
      return response.ok ? response.json() : null;
    }).then(function (data) {
      if (requestId !== musicMetaRequestId) return;
      applyMusicMetaResult(data);
      if (data && (data.album_source || data.artist_source)) {
        console.debug(
          "[music-meta] album=" + (data.album_source || "none") +
          " artist=" + (data.artist_source || "none")
        );
      }
    }).catch(function () {});
  }

  window.reloadMusicMetaFallback = function (info) {
    loadMusicMetaFallback(info && typeof info === "object" ? info : null);
  };

  function initializeInfoPanel() {
    var root = document.getElementById("music-info-panel");
    if (!root) return;
    var tabs = root.querySelectorAll(".info-panel-tab");
    tabs.forEach(function (tab) {
      tab.addEventListener("click", function () {
        setInfoPanel(tab.getAttribute("data-panel"));
      });
    });

    var preferred = localStorage.getItem("lyricsPanelPreference") || "lyrics";
    fetch("/api/preferences").then(function (response) {
      return response.ok ? response.json() : {};
    }).then(function (prefs) {
      if (prefs.lyricsPanelPreference) preferred = prefs.lyricsPanelPreference;
      var albumText = (document.getElementById("soft-album-description-text") || {}).textContent || "";
      var artistText = (document.getElementById("soft-artist-bio-text") || {}).textContent || "";
      if (preferred === "album" && !albumText.trim()) preferred = "lyrics";
      if (preferred === "artist" && !artistText.trim()) preferred = albumText.trim() ? "album" : "lyrics";
      setInfoPanel(preferred);
    }).catch(function () {
      setInfoPanel(preferred);
    });

    loadLyrics();
    setInterval(tickLyrics, 200);
    // Defer remote album/artist text so first paint is not blocked
    setTimeout(loadMusicMetaFallback, 50);
  }

  function fitCastToSingleRow() {
    var cast = document.querySelector(".cast-strip");
    var row = cast && cast.querySelector(".cast-row");
    if (!cast || !row) return;
    var cards = row.querySelectorAll(".cast-card");
    var n = cards.length;
    if (!n) return;
    var gap = parseFloat(window.getComputedStyle(row).columnGap || window.getComputedStyle(row).gap) || 8;
    var avail = row.clientWidth || cast.clientWidth;
    if (avail < 40) return;
    // Prefer natural card size; only shrink when thumbs would overflow the row.
    var preferredCard = 116; // ~7.25rem
    var preferredAvatar = 96;
    var needed = preferredCard * n + gap * (n - 1);
    var cardW = preferredCard;
    var avatar = preferredAvatar;
    if (needed > avail) {
      cardW = Math.max(40, (avail - gap * (n - 1)) / n);
      avatar = Math.max(44, Math.min(110, Math.floor(cardW * 0.9)));
    }
    cast.style.setProperty("--cast-avatar", avatar + "px");
    for (var i = 0; i < cards.length; i++) {
      cards[i].style.width = Math.floor(cardW) + "px";
      cards[i].style.maxWidth = Math.floor(cardW) + "px";
    }
  }

  function fitNowPlayingToViewport() {
    var content = document.querySelector(".content");
    if (!content) return;

    // Reset before measuring
    content.classList.remove("np-fit-scale");
    content.style.transform = "";
    content.style.width = "";

    // Fit cast first so row height is stable before overflow scale
    fitCastToSingleRow();

    var rect = content.getBoundingClientRect();
    var pad = 16;
    var availW = Math.max(320, window.innerWidth - pad);
    var availH = Math.max(280, window.innerHeight - pad);
    var scaleW = availW / Math.max(rect.width, 1);
    var scaleH = availH / Math.max(rect.height, 1);
    var scale = Math.min(1, scaleW, scaleH);

    // Only apply mild shrink when still overflowing after layout constraints
    if (scale < 0.98) {
      scale = Math.max(0.72, scale);
      content.classList.add("np-fit-scale");
      content.style.transform = "scale(" + scale.toFixed(3) + ")";
      content.style.width = (100 / scale).toFixed(2) + "%";
    }
  }

  function initializeViewportFit() {
    if (!document.querySelector(".meta-column") && !document.querySelector(".cast-strip")) {
      return;
    }
    var scheduled = null;
    function schedule() {
      if (scheduled) cancelAnimationFrame(scheduled);
      scheduled = requestAnimationFrame(function () {
        scheduled = null;
        fitNowPlayingToViewport();
      });
    }
    schedule();
    window.addEventListener("resize", schedule);
    window.addEventListener("orientationchange", schedule);
    // Re-fit after cast thumbs load (layout can shift slightly)
    setTimeout(schedule, 600);
    setTimeout(schedule, 1600);
  }

  function enhance() {
    initializeReducedMotion();
    enhanceControls();
    lazyLoadCastThumbs();
    hydrateFanartSlideshow();
    initializeInfoPanel();
    initializeViewportFit();
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", enhance);
  } else {
    enhance();
  }
}());
