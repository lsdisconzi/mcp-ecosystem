(function () {
  'use strict';

  function qs(selector) {
    return document.querySelector(selector);
  }

  function qsa(selector) {
    return Array.prototype.slice.call(document.querySelectorAll(selector));
  }

  function toggleDrawer(forceOpen) {
    var hamburger = qs('.hamburger');
    var drawer = qs('.mobile-drawer');
    if (!hamburger || !drawer) return;

    var nextOpen = typeof forceOpen === 'boolean' ? forceOpen : !drawer.classList.contains('open');
    drawer.classList.toggle('open', nextOpen);
    hamburger.classList.toggle('open', nextOpen);
    hamburger.setAttribute('aria-expanded', nextOpen ? 'true' : 'false');
  }

  function init() {
    var hamburger = qs('.hamburger');
    if (!hamburger) return;

    if (!hamburger.getAttribute('aria-label')) {
      hamburger.setAttribute('aria-label', 'Abrir menu');
    }

    hamburger.addEventListener('click', function () {
      toggleDrawer();
    });

    qsa('.mobile-drawer a').forEach(function (link) {
      link.addEventListener('click', function () {
        toggleDrawer(false);
      });
    });

    document.addEventListener('keydown', function (event) {
      if (event.key === 'Escape') {
        toggleDrawer(false);
      }
    });
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
})();
